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

# ab_events list mirrors model/build_dataset.py:build_pitcher_gamelogs
_AB_EVENTS = [
    'strikeout', 'walk', 'single', 'double', 'triple', 'home_run',
    'field_out', 'force_out', 'grounded_into_dp', 'sac_fly', 'hit_by_pitch',
    'double_play', 'sac_bunt', 'strikeout_double_play',
]


def _normalize_name(name: str) -> str:
    """Strips accents and lowercases a player name. Mirrors ev_calculator version."""
    return unicodedata.normalize('NFD', name).encode('ascii', 'ignore').decode('utf-8').lower().strip()


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

        # Single-day opp K% (all teams who batted today)
        team_k = df_ev.groupby('batter_team').agg(
            _so=('is_SO', 'sum'),
            _pa=('events', 'count')
        ).reset_index()
        team_k['opp_k_pct'] = (team_k['_so'] / team_k['_pa']).round(4)

        # Opponent per pitcher appearance today
        pitcher_opp = df_ev.groupby('pitcher').agg(
            opp_team=('batter_team', 'first')
        ).reset_index()

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

    # Join opponent info
    if has_opp_data:
        game_logs = game_logs.merge(pitcher_opp, on='pitcher', how='left')
        game_logs = game_logs.merge(
            team_k[['batter_team', 'opp_k_pct']],
            left_on='opp_team', right_on='batter_team', how='left'
        )
        game_logs.drop(columns=['batter_team'], inplace=True, errors='ignore')
    else:
        game_logs['opp_team'] = None
        game_logs['opp_k_pct'] = None

    # Merge pitcher name from Statcast
    if 'pitcher_name' in df_ev.columns:
        names = df_ev[['pitcher', 'pitcher_name']].drop_duplicates('pitcher')
    else:
        names = df_ev[['pitcher']].assign(pitcher_name=None).drop_duplicates('pitcher')
    game_logs = game_logs.merge(names, on='pitcher', how='left')

    # Build upsert rows
    rows = []
    for _, row in game_logs.iterrows():
        raw_name = row.get('pitcher_name') or str(row['pitcher'])
        norm_name = _normalize_name(str(raw_name))

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


def run_gamelog_update(game_date: str = None) -> int:
    """
    Fetches Statcast for game_date (defaults to yesterday), builds pitcher gamelogs,
    and upserts to Supabase. Returns number of rows upserted. Never raises.
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

        rows = build_pitcher_gamelogs(raw_df, game_date)
        if not rows:
            print(f"  No qualifying starter gamelogs for {game_date}.")
            return 0

        db.upsert_pitcher_gamelogs(rows)
        print(f"  Upserted {len(rows)} pitcher gamelogs for {game_date}.")
        return len(rows)

    except Exception as e:
        print(f"  Warning: gamelog update failed for {game_date}: {e}")
        return 0


if __name__ == "__main__":
    target_date = sys.argv[1] if len(sys.argv) > 1 else None
    count = run_gamelog_update(target_date)
    print(f"Done. {count} rows upserted.")
