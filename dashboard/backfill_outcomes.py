"""
B.L.A.S.T. Outcome Backfiller
------------------------------
Fetches actual 2025 MLB game results from Statcast (pybaseball) and
resolves each alert in mlb_alert_log to TRUE (hit) or FALSE (miss).

Run once after the season, or periodically during the season:
    python dashboard/backfill_outcomes.py

Requirements:
    - migrate_add_outcome.sql must have been run against your Supabase DB first.
    - SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env
"""

import os
import sys
import unicodedata
from datetime import date, datetime, timezone
from typing import Optional

import pandas as pd
import pybaseball
from dotenv import load_dotenv
from supabase import create_client

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv()

pybaseball.cache.enable()

# ---------------------------------------------------------------------------
# Market → (stat column, threshold) for outcome resolution
# Mirrors the target labels defined in model/build_dataset.py
# ---------------------------------------------------------------------------
MARKET_THRESHOLDS = {
    "batter_home_runs":       ("HR",   1),
    "batter_hits":            ("H",    1),
    "batter_total_bases_1.5": ("TB",   2),
    "batter_strikeouts":      ("SO_b", 1),   # SO as batter
    "pitcher_strikeouts":     ("SO_p", 5),
    "pitcher_outs":           ("Outs", 16),
    "pitcher_hits_allowed":   ("HA",   5),
    "pitcher_walks_allowed":  ("BBA",  2),
}

BATTER_MARKETS   = {k for k in MARKET_THRESHOLDS if k.startswith("batter")}
PITCHER_MARKETS  = {k for k in MARKET_THRESHOLDS if k.startswith("pitcher")}


def _normalize(name: str) -> str:
    return unicodedata.normalize("NFD", name).encode("ascii", "ignore").decode().lower().strip()


def fetch_statcast_for_date(game_date: str) -> pd.DataFrame:
    """Returns full Statcast pitch-by-pitch data for a single date."""
    print(f"  Fetching Statcast for {game_date}...")
    try:
        df = pybaseball.statcast(start_dt=game_date, end_dt=game_date)
        return df if df is not None and not df.empty else pd.DataFrame()
    except Exception as e:
        print(f"  Warning: Statcast fetch failed for {game_date}: {e}")
        return pd.DataFrame()


def _last_first_to_first_last(name: str) -> str:
    """Converts 'Webb, Logan' → 'Logan Webb' to match alert player names."""
    if "," in name:
        parts = name.split(",", 1)
        return f"{parts[1].strip()} {parts[0].strip()}"
    return name


def _resolve_batter_names(batter_ids: list) -> dict:
    """Returns {batter_id: 'First Last'} via playerid_reverse_lookup."""
    try:
        lookup = pybaseball.playerid_reverse_lookup(batter_ids, key_type="mlbam")
        return {
            int(r["key_mlbam"]): f"{r['name_first']} {r['name_last']}".strip()
            for _, r in lookup.iterrows()
        }
    except Exception as e:
        print(f"  Warning: batter name lookup failed: {e}")
        return {}


def build_batter_game_log(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregates Statcast data into per-batter game totals."""
    ab_events = [
        "strikeout", "walk", "single", "double", "triple", "home_run",
        "field_out", "force_out", "grounded_into_dp", "sac_fly", "hit_by_pitch",
    ]
    df_ab = df[df["events"].isin(ab_events)].copy()

    def calc_tb(event):
        return {"single": 1, "double": 2, "triple": 3, "home_run": 4}.get(event, 0)

    df_ab["is_Hit"] = df_ab["events"].isin(["single", "double", "triple", "home_run"]).astype(int)
    df_ab["is_HR"]  = (df_ab["events"] == "home_run").astype(int)
    df_ab["is_SO"]  = (df_ab["events"] == "strikeout").astype(int)
    df_ab["TB"]     = df_ab["events"].apply(calc_tb)

    game_log = df_ab.groupby("batter").agg(
        H=("is_Hit", "sum"),
        HR=("is_HR", "sum"),
        SO_b=("is_SO", "sum"),
        TB=("TB", "sum"),
    ).reset_index()

    # Resolve batter IDs → "First Last" names
    batter_ids = game_log["batter"].astype(int).tolist()
    id_to_name = _resolve_batter_names(batter_ids)
    game_log["batter_name"] = game_log["batter"].astype(int).map(id_to_name)
    return game_log


def build_pitcher_game_log(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregates Statcast data into per-pitcher game totals."""
    ab_events = [
        "strikeout", "walk", "single", "double", "triple", "home_run",
        "field_out", "force_out", "grounded_into_dp", "sac_fly", "hit_by_pitch",
        "double_play", "sac_bunt", "strikeout_double_play",
    ]
    df_ev = df[df["events"].isin(ab_events)].copy()

    def calc_outs(event):
        if event in ["field_out", "force_out", "strikeout", "sac_fly", "sac_bunt"]:
            return 1
        if event in ["grounded_into_dp", "double_play", "strikeout_double_play"]:
            return 2
        return 0

    df_ev["is_SO_p"] = df_ev["events"].isin(["strikeout", "strikeout_double_play"]).astype(int)
    df_ev["is_BB"]   = (df_ev["events"] == "walk").astype(int)
    df_ev["is_Hit"]  = df_ev["events"].isin(["single", "double", "triple", "home_run"]).astype(int)
    df_ev["Outs"]    = df_ev["events"].apply(calc_outs)

    game_log = df_ev.groupby("pitcher").agg(
        SO_p=("is_SO_p", "sum"),
        BBA=("is_BB", "sum"),
        HA=("is_Hit", "sum"),
        Outs=("Outs", "sum"),
    ).reset_index()

    # player_name in Statcast is "Last, First" keyed to pitcher ID
    if "player_name" in df_ev.columns:
        names = df_ev[["pitcher", "player_name"]].drop_duplicates("pitcher").copy()
        names["pitcher_name"] = names["player_name"].apply(_last_first_to_first_last)
        game_log = game_log.merge(names[["pitcher", "pitcher_name"]], on="pitcher", how="left")
    else:
        game_log["pitcher_name"] = None
    return game_log


def resolve_outcome(player_name: str, market: str, batter_log: pd.DataFrame, pitcher_log: pd.DataFrame) -> Optional[bool]:
    """
    Returns True (hit), False (miss), or None (player not found in Statcast).
    """
    stat_col, threshold = MARKET_THRESHOLDS[market]
    norm_target = _normalize(player_name)

    if market in BATTER_MARKETS:
        name_col = "batter_name"
        log = batter_log
    else:
        name_col = "pitcher_name"
        log = pitcher_log

    if log.empty or name_col not in log.columns:
        return None

    mask = log[name_col].apply(lambda n: False if pd.isna(n) else _normalize(str(n)) == norm_target)
    row = log[mask]

    if row.empty:
        return None

    val = row.iloc[0].get(stat_col, 0)
    return bool(val >= threshold)


def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise EnvironmentError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set.")

    supabase = create_client(url, key)

    # Fetch all alerts without a resolved outcome
    print("Fetching unresolved alerts from Supabase...")
    response = (
        supabase.table("mlb_alert_log")
        .select("id, player_name, market, sent_at")
        .is_("actual_outcome", "null")
        .execute()
    )
    alerts = response.data
    if not alerts:
        print("No unresolved alerts. Nothing to do.")
        return

    print(f"Found {len(alerts)} unresolved alerts.")

    # Group alerts by game date.
    # Alerts sent between midnight–8am UTC belong to the previous calendar day's games
    # (pipeline runs overnight after games finish). Convert sent_at to PST to get game date.
    from datetime import timedelta, timezone as tz
    PST_OFFSET = timedelta(hours=8)  # UTC-8 (PST)

    alerts_by_date: dict[str, list] = {}
    for alert in alerts:
        sent_utc = pd.to_datetime(alert["sent_at"], utc=True).to_pydatetime()
        sent_pst = sent_utc - PST_OFFSET
        game_date = sent_pst.date().isoformat()
        alerts_by_date.setdefault(game_date, []).append(alert)

    total_resolved = 0
    total_not_found = 0

    for game_date, day_alerts in sorted(alerts_by_date.items()):
        # Skip future dates
        if date.fromisoformat(game_date) > date.today():
            print(f"  Skipping future date: {game_date}")
            continue

        print(f"\nProcessing {game_date} ({len(day_alerts)} alerts)...")
        statcast_df = fetch_statcast_for_date(game_date)

        if statcast_df.empty:
            print(f"  No Statcast data for {game_date}, skipping.")
            continue

        batter_log  = build_batter_game_log(statcast_df)
        pitcher_log = build_pitcher_game_log(statcast_df)

        for alert in day_alerts:
            alert_id    = alert["id"]
            player_name = alert["player_name"]
            market      = alert["market"]

            if market not in MARKET_THRESHOLDS:
                continue

            outcome = resolve_outcome(player_name, market, batter_log, pitcher_log)

            if outcome is None:
                total_not_found += 1
                print(f"  ? {player_name} ({market}) — not found in Statcast")
                continue

            # Update Supabase
            supabase.table("mlb_alert_log").update(
                {"actual_outcome": outcome}
            ).eq("id", alert_id).execute()

            status = "HIT ✓" if outcome else "MISS ✗"
            print(f"  {status}  {player_name} ({market})")
            total_resolved += 1

    print(f"\nDone. Resolved: {total_resolved} | Not found in Statcast: {total_not_found}")


if __name__ == "__main__":
    main()
