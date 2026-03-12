"""
B.L.A.S.T. 2025 Season Backtest Seeder
----------------------------------------
Fetches the full 2025 MLB season from Statcast, runs every trained ML model
against every player+game combination, and inserts rows into mlb_alert_log
for any prediction that would have cleared the EV threshold.
actual_outcome is resolved immediately from real game results.

Run once:
    python3 dashboard/seed_2025_season.py

Takes 20-60 minutes on first run (large Statcast downloads).
Subsequent runs are fast due to pybaseball cache.

Requirements:
    - migrate_add_outcome.sql must have been run against Supabase first
    - Trained .pkl models must exist in model/trained_models/
    - SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env
"""

import os
import sys
import unicodedata
from datetime import date, datetime, timezone, timedelta
from typing import Optional

import joblib
import pandas as pd
import pybaseball
from dotenv import load_dotenv
from supabase import create_client

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv()

pybaseball.cache.enable()

# ---------------------------------------------------------------------------
# Season config
# ---------------------------------------------------------------------------
SEASON_MONTHS = [
    ("2025-04-01", "2025-04-30"),
    ("2025-05-01", "2025-05-31"),
    ("2025-06-01", "2025-06-30"),
    ("2025-07-01", "2025-07-31"),
    ("2025-08-01", "2025-08-31"),
    ("2025-09-01", "2025-09-30"),
]

MODELS_DIR = os.path.join(os.path.dirname(__file__), "../model/trained_models")

EV_THRESHOLD = float(os.environ.get("EV_THRESHOLD", "0.05"))

# Typical mid-market sportsbook implied probabilities per market
# Used to synthesize realistic odds for backtesting
MARKET_IMPLIED = {
    "batter_home_runs":       0.220,   # ~+350
    "batter_hits":            0.520,   # ~-108
    "batter_total_bases_1.5": 0.510,   # ~-104
    "batter_strikeouts":      0.560,   # ~-127 (batter K)
    "pitcher_strikeouts":     0.500,   # ~+100 (over 4.5 K)
    "pitcher_outs":           0.490,   # ~+104 (over 15.5 outs)
    "pitcher_hits_allowed":   0.480,   # ~+108 (over 4.5 HA)
    "pitcher_walks_allowed":  0.540,   # ~-117 (over 1.5 BB)
}

# implied → representative American odds string (for odds_formatted column)
MARKET_ODDS_STR = {
    "batter_home_runs":       "+350",
    "batter_hits":            "-108",
    "batter_total_bases_1.5": "-104",
    "batter_strikeouts":      "-127",
    "pitcher_strikeouts":     "+100",
    "pitcher_outs":           "+104",
    "pitcher_hits_allowed":   "+108",
    "pitcher_walks_allowed":  "-117",
}

# Actual outcome thresholds (mirrors backfill_outcomes.py)
MARKET_THRESHOLDS = {
    "batter_home_runs":       ("HR",   1),
    "batter_hits":            ("H",    1),
    "batter_total_bases_1.5": ("TB",   2),
    "batter_strikeouts":      ("SO_b", 1),
    "pitcher_strikeouts":     ("SO_p", 5),
    "pitcher_outs":           ("Outs", 16),
    "pitcher_hits_allowed":   ("HA",   5),
    "pitcher_walks_allowed":  ("BBA",  2),
}

BATTER_MARKETS  = {k for k in MARKET_THRESHOLDS if k.startswith("batter")}
PITCHER_MARKETS = {k for k in MARKET_THRESHOLDS if k.startswith("pitcher")}

BATTER_FEATURES  = ["rolling_10_PA", "rolling_10_AB", "rolling_10_H",
                     "rolling_10_HR", "rolling_10_SO", "rolling_10_TB"]
PITCHER_FEATURES = ["rolling_5_BF", "rolling_5_SO", "rolling_5_BBA",
                    "rolling_5_HA", "rolling_5_Outs"]

BATTER_TARGETS = {
    "batter_home_runs":       "Target_HR",
    "batter_hits":            "Target_Hit",
    "batter_total_bases_1.5": "Target_TB_Over_1_5",
    "batter_strikeouts":      "Target_SO",
}
PITCHER_TARGETS = {
    "pitcher_strikeouts":    "Target_SO_Over_4_5",
    "pitcher_outs":          "Target_Outs_Over_15_5",
    "pitcher_hits_allowed":  "Target_HA_Over_4_5",
    "pitcher_walks_allowed": "Target_BBA_Over_1_5",
}

SPORTSBOOK = "backtested_2025"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _normalize(name: str) -> str:
    return unicodedata.normalize("NFD", name).encode("ascii", "ignore").decode().lower().strip()


def load_models() -> dict:
    models = {}
    for market in list(BATTER_MARKETS) + list(PITCHER_MARKETS):
        path = os.path.join(MODELS_DIR, f"{market}_model.pkl")
        if os.path.exists(path):
            models[market] = joblib.load(path)
        else:
            print(f"  Warning: no model found for {market}")
    return models


def fetch_player_names(player_ids: list) -> dict:
    """Returns {mlbam_id: 'First Last'} for a list of MLB IDs."""
    if not player_ids:
        return {}
    try:
        lookup = pybaseball.playerid_reverse_lookup(player_ids, key_type="mlbam")
        lookup["full_name"] = lookup["name_first"].str.title() + " " + lookup["name_last"].str.title()
        return lookup.set_index("key_mlbam")["full_name"].to_dict()
    except Exception as e:
        print(f"  Warning: player name lookup failed: {e}")
        return {}


# ---------------------------------------------------------------------------
# Game log builders  (same logic as model/build_dataset.py)
# ---------------------------------------------------------------------------
def build_batter_gamelogs(df: pd.DataFrame) -> pd.DataFrame:
    ab_events = ["strikeout", "walk", "single", "double", "triple", "home_run",
                 "field_out", "force_out", "grounded_into_dp", "sac_fly", "hit_by_pitch"]
    df_ab = df[df["events"].isin(ab_events)].copy()

    def calc_tb(event):
        return {"single": 1, "double": 2, "triple": 3, "home_run": 4}.get(event, 0)

    df_ab["is_AB"]  = df_ab["events"].apply(lambda x: 0 if x in ["walk", "hit_by_pitch", "sac_fly"] else 1)
    df_ab["is_Hit"] = df_ab["events"].isin(["single", "double", "triple", "home_run"]).astype(int)
    df_ab["is_HR"]  = (df_ab["events"] == "home_run").astype(int)
    df_ab["is_SO"]  = (df_ab["events"] == "strikeout").astype(int)
    df_ab["TB"]     = df_ab["events"].apply(calc_tb)

    logs = df_ab.groupby(["batter", "game_date"]).agg(
        PA=("events", "count"),
        AB=("is_AB", "sum"),
        H=("is_Hit", "sum"),
        HR=("is_HR", "sum"),
        SO_b=("is_SO", "sum"),
        TB=("TB", "sum"),
    ).reset_index()

    logs["game_date"] = pd.to_datetime(logs["game_date"])
    logs = logs.sort_values(["batter", "game_date"]).reset_index(drop=True)

    logs["Target_HR"]          = (logs["HR"]  >= 1).astype(int)
    logs["Target_Hit"]         = (logs["H"]   >= 1).astype(int)
    logs["Target_TB_Over_1_5"] = (logs["TB"]  >= 2).astype(int)
    logs["Target_SO"]          = (logs["SO_b"] >= 1).astype(int)

    # Rolling features (shift(1) so we only use history available at game time)
    for col in ["PA", "AB", "H", "HR", "SO_b", "TB"]:
        logs[f"rolling_10_{col.replace('SO_b','SO')}"] = (
            logs.groupby("batter")[col]
            .transform(lambda x: x.rolling(10, min_periods=1).mean().shift(1))
        )

    return logs.dropna(subset=["rolling_10_HR"])


def build_pitcher_gamelogs(df: pd.DataFrame) -> pd.DataFrame:
    ab_events = ["strikeout", "walk", "single", "double", "triple", "home_run",
                 "field_out", "force_out", "grounded_into_dp", "sac_fly", "hit_by_pitch",
                 "double_play", "sac_bunt", "strikeout_double_play"]
    df_ev = df[df["events"].isin(ab_events)].copy()

    def calc_outs(event):
        if event in ["field_out", "force_out", "strikeout", "sac_fly", "sac_bunt"]: return 1
        if event in ["grounded_into_dp", "double_play", "strikeout_double_play"]: return 2
        return 0

    df_ev["is_SO_p"] = df_ev["events"].isin(["strikeout", "strikeout_double_play"]).astype(int)
    df_ev["is_BB"]   = (df_ev["events"] == "walk").astype(int)
    df_ev["is_Hit"]  = df_ev["events"].isin(["single", "double", "triple", "home_run"]).astype(int)
    df_ev["Outs"]    = df_ev["events"].apply(calc_outs)

    logs = df_ev.groupby(["pitcher", "game_date"]).agg(
        BF=("events", "count"),
        SO_p=("is_SO_p", "sum"),
        BBA=("is_BB", "sum"),
        HA=("is_Hit", "sum"),
        Outs=("Outs", "sum"),
    ).reset_index()

    logs["game_date"] = pd.to_datetime(logs["game_date"])
    logs = logs.sort_values(["pitcher", "game_date"]).reset_index(drop=True)

    logs["Target_SO_Over_4_5"]    = (logs["SO_p"] >= 5).astype(int)
    logs["Target_Outs_Over_15_5"] = (logs["Outs"] >= 16).astype(int)
    logs["Target_HA_Over_4_5"]    = (logs["HA"]   >= 5).astype(int)
    logs["Target_BBA_Over_1_5"]   = (logs["BBA"]  >= 2).astype(int)

    for col in ["BF", "SO_p", "BBA", "HA", "Outs"]:
        feat = f"rolling_5_{col.replace('SO_p','SO').replace('BBA','BBA').replace('HA','HA')}"
        logs[feat] = (
            logs.groupby("pitcher")[col]
            .transform(lambda x: x.rolling(5, min_periods=1).mean().shift(1))
        )

    return logs.dropna(subset=["rolling_5_SO"])


# ---------------------------------------------------------------------------
# Prediction + alert generation
# ---------------------------------------------------------------------------
def generate_alerts(batter_logs: pd.DataFrame, pitcher_logs: pd.DataFrame,
                    models: dict, name_map: dict) -> list:
    """
    For every player+game row, runs all applicable ML models.
    Returns a list of alert dicts for rows where model_prob - implied_prob >= threshold.
    """
    alerts = []

    # ── Batter markets ────────────────────────────────────────────────────────
    batter_feat_cols = {
        "rolling_10_PA": "rolling_10_PA",
        "rolling_10_AB": "rolling_10_AB",
        "rolling_10_H":  "rolling_10_H",
        "rolling_10_HR": "rolling_10_HR",
        "rolling_10_SO": "rolling_10_SO",
        "rolling_10_TB": "rolling_10_TB",
    }

    for market, target_col in BATTER_TARGETS.items():
        if market not in models:
            continue
        clf = models[market]
        implied = MARKET_IMPLIED[market]

        sub = batter_logs.dropna(subset=list(batter_feat_cols.values()))
        if sub.empty:
            continue

        X = sub[[batter_feat_cols[f] for f in BATTER_FEATURES]].copy()
        X.columns = BATTER_FEATURES

        probs = clf.predict_proba(X)[:, 1]

        for i, (idx, row) in enumerate(sub.iterrows()):
            model_prob = float(probs[i])
            edge = model_prob - implied
            if edge < EV_THRESHOLD:
                continue

            player_id = int(row["batter"])
            player_name = name_map.get(player_id, f"Player #{player_id}")
            actual_outcome = bool(row[target_col] == 1)

            alerts.append({
                "player_name": player_name,
                "market": market,
                "sportsbook": SPORTSBOOK,
                "odds_formatted": MARKET_ODDS_STR[market],
                "calculated_edge_percentage": round(edge, 6),
                "actual_outcome": actual_outcome,
                "sent_at": row["game_date"].strftime("%Y-%m-%dT12:00:00+00:00"),
            })

    # ── Pitcher markets ───────────────────────────────────────────────────────
    pitcher_feat_map = {
        "rolling_5_BF":   "rolling_5_BF",
        "rolling_5_SO":   "rolling_5_SO",
        "rolling_5_BBA":  "rolling_5_BBA",
        "rolling_5_HA":   "rolling_5_HA",
        "rolling_5_Outs": "rolling_5_Outs",
    }

    for market, target_col in PITCHER_TARGETS.items():
        if market not in models:
            continue
        clf = models[market]
        implied = MARKET_IMPLIED[market]

        sub = pitcher_logs.dropna(subset=list(pitcher_feat_map.values()))
        if sub.empty:
            continue

        X = sub[[pitcher_feat_map[f] for f in PITCHER_FEATURES]].copy()
        X.columns = PITCHER_FEATURES

        probs = clf.predict_proba(X)[:, 1]

        for i, (idx, row) in enumerate(sub.iterrows()):
            model_prob = float(probs[i])
            edge = model_prob - implied
            if edge < EV_THRESHOLD:
                continue

            player_id = int(row["pitcher"])
            player_name = name_map.get(player_id, f"Pitcher #{player_id}")
            actual_outcome = bool(row[target_col] == 1)

            alerts.append({
                "player_name": player_name,
                "market": market,
                "sportsbook": SPORTSBOOK,
                "odds_formatted": MARKET_ODDS_STR[market],
                "calculated_edge_percentage": round(edge, 6),
                "actual_outcome": actual_outcome,
                "sent_at": row["game_date"].strftime("%Y-%m-%dT12:00:00+00:00"),
            })

    return alerts


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise EnvironmentError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set.")

    supabase = create_client(url, key)

    print("Loading ML models...")
    models = load_models()
    if not models:
        raise RuntimeError(f"No models found in {MODELS_DIR}. Run model/train_model.py first.")
    print(f"  Loaded {len(models)} models: {list(models.keys())}")

    # Check if backtested data already exists
    existing = (
        supabase.table("mlb_alert_log")
        .select("id", count="exact")
        .eq("sportsbook", SPORTSBOOK)
        .execute()
    )
    if existing.count and existing.count > 0:
        print(f"\nFound {existing.count:,} existing backtested rows in mlb_alert_log.")
        answer = input("Delete and re-seed? [y/N]: ").strip().lower()
        if answer == "y":
            supabase.table("mlb_alert_log").delete().eq("sportsbook", SPORTSBOOK).execute()
            print("  Deleted existing rows.")
        else:
            print("Aborted.")
            return

    # Fetch full 2025 season month-by-month
    all_statcast = []
    for start, end in SEASON_MONTHS:
        print(f"\nFetching Statcast {start} → {end}...")
        try:
            chunk = pybaseball.statcast(start_dt=start, end_dt=end)
            if chunk is not None and not chunk.empty:
                all_statcast.append(chunk)
                print(f"  {len(chunk):,} rows")
            else:
                print("  No data returned.")
        except Exception as e:
            print(f"  Error: {e} — skipping month.")

    if not all_statcast:
        print("No Statcast data fetched. Cannot seed.")
        return

    print("\nCombining monthly data...")
    df = pd.concat(all_statcast, ignore_index=True)
    print(f"Total rows: {len(df):,}")

    print("Building batter game logs...")
    batter_logs = build_batter_gamelogs(df)
    print(f"  {len(batter_logs):,} batter-game rows across {batter_logs['batter'].nunique():,} players")

    print("Building pitcher game logs...")
    pitcher_logs = build_pitcher_gamelogs(df)
    print(f"  {len(pitcher_logs):,} pitcher-game rows across {pitcher_logs['pitcher'].nunique():,} pitchers")

    # Resolve player names
    print("Resolving player names...")
    all_ids = (
        batter_logs["batter"].unique().tolist() +
        pitcher_logs["pitcher"].unique().tolist()
    )
    name_map = fetch_player_names([int(i) for i in all_ids])
    print(f"  Resolved {len(name_map):,} player names")

    # Run models and collect alerts
    print("\nRunning model predictions...")
    alerts = generate_alerts(batter_logs, pitcher_logs, models, name_map)
    print(f"Found {len(alerts):,} predictions above EV threshold ({EV_THRESHOLD*100:.0f}%)")

    if not alerts:
        print("No alerts generated. Check that models are trained and thresholds are reasonable.")
        return

    # Summarise before inserting
    hits   = sum(1 for a in alerts if a["actual_outcome"])
    misses = sum(1 for a in alerts if not a["actual_outcome"])
    win_rate = hits / len(alerts) * 100
    print(f"  Hits: {hits:,}  |  Misses: {misses:,}  |  Win Rate: {win_rate:.1f}%")

    by_market = {}
    for a in alerts:
        m = a["market"]
        by_market.setdefault(m, {"hits": 0, "total": 0})
        by_market[m]["total"] += 1
        if a["actual_outcome"]:
            by_market[m]["hits"] += 1
    print("\nBy market:")
    for m, stats in sorted(by_market.items()):
        wr = stats["hits"] / stats["total"] * 100
        print(f"  {m:<30} {stats['total']:>5} alerts  {wr:>5.1f}% win rate")

    # Insert in batches of 500
    print(f"\nInserting {len(alerts):,} rows into mlb_alert_log...")
    batch_size = 500
    for i in range(0, len(alerts), batch_size):
        batch = alerts[i:i + batch_size]
        supabase.table("mlb_alert_log").insert(batch).execute()
        print(f"  Inserted rows {i+1}–{min(i+batch_size, len(alerts))}")

    print(f"\nDone. {len(alerts):,} backtested alerts seeded.")
    print("Launch dashboard:  python3 -m streamlit run dashboard/app.py")


if __name__ == "__main__":
    main()
