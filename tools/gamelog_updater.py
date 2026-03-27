"""
B.L.A.S.T. Pitcher Gamelog Updater
------------------------------------
Fetches yesterday's Statcast data and stores per-start pitcher stats in Supabase.
This enables the inference pipeline to use true rolling game logs instead of
season-average approximations.

Usage:
    python tools/gamelog_updater.py              # defaults to yesterday
    python tools/gamelog_updater.py 2025-04-15   # backfill a specific date
"""

import os
import sys
import unicodedata
from datetime import date, timedelta

import pandas as pd
import pybaseball
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv()

pybaseball.cache.enable()

# Statcast → FanGraphs team abbreviation mapping (for known differences)
_STATCAST_TO_FG = {
    'CWS': 'CHW', 'KC': 'KCR', 'SD': 'SDP',
    'SF': 'SFG', 'TB': 'TBR', 'WSH': 'WSN',
}

# ab_events list mirrors model/build_dataset.py:build_pitcher_gamelogs
_AB_EVENTS = [
    'strikeout', 'walk', 'single', 'double', 'triple', 'home_run',
    'field_out', 'force_out', 'grounded_into_dp', 'sac_fly', 'hit_by_pitch',
    'double_play', 'sac_bunt', 'strikeout_double_play',
]


def _normalize_name(name: str) -> str:
    """Strips accents and lowercases a player name. Mirrors ev_calculator version."""
    return unicodedata.normalize('NFD', name).encode('ascii', 'ignore').decode('utf-8').lower().strip()


def _fetch_season_team_k_pct(year: int) -> dict:
    """
    Returns {FanGraphs_team_abbrev: k_pct} from pybaseball.team_batting().
    Matches build_dataset.py season-level computation.  Falls back to
    previous year if current year has no data (early season).
    """
    for y in [year, year - 1]:
        try:
            tb = pybaseball.team_batting(y)
            if tb is None or tb.empty:
                continue
            result = {}
            for _, row in tb.iterrows():
                team = str(row.get('Team', ''))
                k_pct = row.get('K%', None)
                if k_pct is None or (isinstance(k_pct, float) and pd.isna(k_pct)):
                    so = float(row.get('SO', 0))
                    pa = float(row.get('PA', 1))
                    result[team] = round(so / pa, 4) if pa > 0 else 0.0
                else:
                    if isinstance(k_pct, str):
                        k_pct = float(k_pct.strip('%')) / 100
                    k_pct = float(k_pct)
                    result[team] = round(k_pct / 100 if k_pct > 1 else k_pct, 4)
            if result:
                if y != year:
                    print(f"  Note: Using {y} team K% data (current season not yet available).")
                return result
        except Exception as e:
            print(f"  Warning: team_batting({y}) failed: {e}")
    return {}


def fetch_statcast_for_date(game_date: str) -> pd.DataFrame:
    """Returns Statcast pitch-by-pitch data for a single date. Returns empty DF on error."""
    print(f"  Fetching Statcast for {game_date}...")
    try:
        df = pybaseball.statcast(start_dt=game_date, end_dt=game_date)
        return df if df is not None and not df.empty else pd.DataFrame()
    except Exception as e:
        print(f"  Warning: Statcast fetch failed for {game_date}: {e}")
        return pd.DataFrame()


def build_pitcher_gamelogs(df: pd.DataFrame, game_date: str) -> list:
    """
    Aggregates Statcast pitch-by-pitch data into per-starter game logs.
    Mirrors model/build_dataset.py:build_pitcher_gamelogs() logic.
    Filters to BF >= 12 (starters only).
    Returns a list of dicts ready for Supabase upsert.
    """
    if df is None or df.empty:
        return []

    df_ev = df[df['events'].isin(_AB_EVENTS)].copy()
    if df_ev.empty:
        return []

    df_ev['is_SO']  = df_ev['events'].isin(['strikeout', 'strikeout_double_play']).astype(int)
    df_ev['is_BB']  = (df_ev['events'] == 'walk').astype(int)
    df_ev['is_Hit'] = df_ev['events'].isin(['single', 'double', 'triple', 'home_run']).astype(int)

    def calc_outs(event):
        if event in ['field_out', 'force_out', 'strikeout', 'sac_fly', 'sac_bunt']:
            return 1
        if event in ['grounded_into_dp', 'double_play', 'strikeout_double_play']:
            return 2
        return 0

    df_ev['Outs_Recorded'] = df_ev['events'].apply(calc_outs)

    # Opponent team: inning_topbot='Top' → away team batting; 'Bot' → home team batting
    has_opp_data = all(c in df_ev.columns for c in ['inning_topbot', 'home_team', 'away_team'])
    if has_opp_data:
        df_ev['batter_team'] = df_ev.apply(
            lambda r: r['away_team'] if str(r.get('inning_topbot', '')).lower() == 'top' else r['home_team'],
            axis=1
        )

        # Opponent per pitcher appearance today
        pitcher_opp = df_ev.groupby('pitcher').agg(
            opp_team=('batter_team', 'first')
        ).reset_index()

    # Season-level team K% (matches build_dataset.py training pipeline)
    season_year = int(game_date[:4])
    season_k_pct = _fetch_season_team_k_pct(season_year)

    # Aggregate per pitcher
    game_logs = df_ev.groupby('pitcher').agg(
        BF=('events', 'count'),
        SO=('is_SO', 'sum'),
        BBA=('is_BB', 'sum'),
        HA=('is_Hit', 'sum'),
        Outs=('Outs_Recorded', 'sum'),
    ).reset_index()

    # Filter to starters only
    game_logs = game_logs[game_logs['BF'] >= 12].copy()

    if game_logs.empty:
        return []

    # Compute K%
    game_logs['K_pct'] = (game_logs['SO'] / game_logs['BF'].replace(0, 1)).round(4)

    # Join opponent info with season-level K% (not single-day)
    if has_opp_data:
        game_logs = game_logs.merge(pitcher_opp, on='pitcher', how='left')
        game_logs['opp_k_pct'] = game_logs['opp_team'].apply(
            lambda t: season_k_pct.get(_STATCAST_TO_FG.get(t, t)) if pd.notna(t) else None
        )
    else:
        game_logs['opp_team'] = None
        game_logs['opp_k_pct'] = None

    # Merge pitcher name from Statcast
    # pybaseball statcast() uses 'player_name'; older builds may use 'pitcher_name'
    name_col = next((c for c in ['player_name', 'pitcher_name'] if c in df_ev.columns), None)
    if name_col:
        names = df_ev[['pitcher', name_col]].rename(columns={name_col: 'pitcher_name'}).drop_duplicates('pitcher')
    else:
        names = df_ev[['pitcher']].assign(pitcher_name=None).drop_duplicates('pitcher')
    game_logs = game_logs.merge(names, on='pitcher', how='left')

    # For any rows still missing a name, resolve via playerid_reverse_lookup
    missing_mask = game_logs['pitcher_name'].isna()
    if missing_mask.any():
        missing_ids = game_logs.loc[missing_mask, 'pitcher'].astype(int).tolist()
        try:
            lookup = pybaseball.playerid_reverse_lookup(missing_ids, key_type='mlbam')
            id_to_name = {
                int(r['key_mlbam']): f"{r['name_first']} {r['name_last']}".strip()
                for _, r in lookup.iterrows()
            }
            game_logs.loc[missing_mask, 'pitcher_name'] = (
                game_logs.loc[missing_mask, 'pitcher'].astype(int).map(id_to_name)
            )
        except Exception as e:
            print(f"  Warning: playerid_reverse_lookup failed: {e}")

    # Drop rows we still can't name (rare: unknown pitcher ID)
    game_logs = game_logs[game_logs['pitcher_name'].notna()].copy()
    if game_logs.empty:
        return []

    # Build upsert rows
    rows = []
    for _, row in game_logs.iterrows():
        norm_name = _normalize_name(str(row['pitcher_name']))

        opp_team = row.get('opp_team')
        opp_k_pct = row.get('opp_k_pct')

        rows.append({
            'pitcher_name': norm_name,
            'game_date':    game_date,
            'BF':           int(row['BF']),
            'SO':           int(row['SO']),
            'BBA':          int(row['BBA']),
            'HA':           int(row['HA']),
            'Outs':         int(row['Outs']),
            'K_pct':        float(row['K_pct']) if pd.notna(row['K_pct']) else None,
            'opp_team':     str(opp_team) if pd.notna(opp_team) else None,
            'opp_k_pct':    float(opp_k_pct) if pd.notna(opp_k_pct) else None,
        })

    return rows


def _resolve_batter_names(batter_ids: list) -> dict:
    """Returns {mlbam_id: 'first last'} via playerid_reverse_lookup."""
    try:
        lookup = pybaseball.playerid_reverse_lookup(batter_ids, key_type='mlbam')
        return {
            int(r['key_mlbam']): f"{r['name_first']} {r['name_last']}".strip()
            for _, r in lookup.iterrows()
        }
    except Exception as e:
        print(f"  Warning: batter name lookup failed: {e}")
        return {}


def build_batter_gamelogs(df: pd.DataFrame, game_date: str) -> list:
    """
    Aggregates Statcast pitch-by-pitch data into per-batter game totals.
    Mirrors model/build_dataset.py:build_batter_gamelogs() logic.
    Returns a list of dicts ready for Supabase upsert.
    """
    if df is None or df.empty:
        return []

    ab_events = [
        'strikeout', 'walk', 'single', 'double', 'triple', 'home_run',
        'field_out', 'force_out', 'grounded_into_dp', 'sac_fly', 'hit_by_pitch',
    ]
    df_ab = df[df['events'].isin(ab_events)].copy()
    if df_ab.empty:
        return []

    df_ab['is_AB'] = df_ab['events'].apply(lambda x: 1 if x not in ['walk', 'hit_by_pitch', 'sac_fly'] else 0)
    df_ab['is_Hit'] = df_ab['events'].isin(['single', 'double', 'triple', 'home_run']).astype(int)
    df_ab['is_HR'] = (df_ab['events'] == 'home_run').astype(int)
    df_ab['is_SO'] = (df_ab['events'] == 'strikeout').astype(int)

    def calc_tb(event):
        return {'single': 1, 'double': 2, 'triple': 3, 'home_run': 4}.get(event, 0)
    df_ab['TB'] = df_ab['events'].apply(calc_tb)

    game_logs = df_ab.groupby('batter').agg(
        PA=('events', 'count'),
        AB=('is_AB', 'sum'),
        H=('is_Hit', 'sum'),
        HR=('is_HR', 'sum'),
        SO=('is_SO', 'sum'),
        TB=('TB', 'sum'),
    ).reset_index()

    # Resolve batter MLBAM IDs → "First Last" names
    batter_ids = game_logs['batter'].astype(int).tolist()
    id_to_name = _resolve_batter_names(batter_ids)
    game_logs['batter_name'] = game_logs['batter'].astype(int).map(id_to_name)

    # Drop rows we can't name
    game_logs = game_logs[game_logs['batter_name'].notna()].copy()
    if game_logs.empty:
        return []

    rows = []
    for _, row in game_logs.iterrows():
        rows.append({
            'batter_name': _normalize_name(str(row['batter_name'])),
            'game_date':   game_date,
            'PA':          int(row['PA']),
            'AB':          int(row['AB']),
            'H':           int(row['H']),
            'HR':          int(row['HR']),
            'SO':          int(row['SO']),
            'TB':          int(row['TB']),
        })

    return rows


def run_gamelog_update(game_date: str = None) -> int:
    """
    Fetches Statcast for game_date (defaults to yesterday), builds pitcher + batter
    gamelogs, and upserts both to Supabase. Returns total rows upserted. Never raises.
    """
    if game_date is None:
        game_date = (date.today() - timedelta(days=1)).isoformat()

    print(f"Running gamelog update for {game_date}...")

    try:
        from db_client import DatabaseClient
        db = DatabaseClient()

        raw_df = fetch_statcast_for_date(game_date)
        if raw_df.empty:
            print(f"  No Statcast data found for {game_date}. Skipping.")
            return 0

        total = 0

        # Pitcher gamelogs
        pitcher_rows = build_pitcher_gamelogs(raw_df, game_date)
        if pitcher_rows:
            db.upsert_pitcher_gamelogs(pitcher_rows)
            print(f"  Upserted {len(pitcher_rows)} pitcher gamelogs for {game_date}.")
            total += len(pitcher_rows)

        # Batter gamelogs
        batter_rows = build_batter_gamelogs(raw_df, game_date)
        if batter_rows:
            db.upsert_batter_gamelogs(batter_rows)
            print(f"  Upserted {len(batter_rows)} batter gamelogs for {game_date}.")
            total += len(batter_rows)

        if total == 0:
            print(f"  No gamelogs produced for {game_date}.")

        return total

    except Exception as e:
        print(f"  Warning: gamelog update failed for {game_date}: {e}")
        return 0


def backfill_range(start_date: str, end_date: str) -> int:
    """
    Backfills pitcher gamelogs for every date in [start_date, end_date].
    Usage: python tools/gamelog_updater.py 2024-04-01 2024-09-29
    """
    from datetime import datetime
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    total = 0
    current = start
    while current <= end:
        count = run_gamelog_update(current.isoformat())
        total += count
        current += timedelta(days=1)
    return total


if __name__ == "__main__":
    if len(sys.argv) == 3:
        # Range backfill: python tools/gamelog_updater.py 2024-04-01 2024-09-29
        total = backfill_range(sys.argv[1], sys.argv[2])
        print(f"Done. {total} total rows upserted across date range.")
    else:
        target_date = sys.argv[1] if len(sys.argv) > 1 else None
        count = run_gamelog_update(target_date)
        print(f"Done. {count} rows upserted.")
