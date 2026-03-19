import os
import sys
import pandas as pd
import pybaseball
from datetime import datetime

# Enable cache so we don't spam MLB servers
pybaseball.cache.enable()

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# Multi-year default: 2023–2025 gives 3x more positive examples for rare events
DEFAULT_START = "2023-04-01"
DEFAULT_END   = "2025-09-30"


# --------------------------------------------------------------------------------
# BATTER PIPELINE
# --------------------------------------------------------------------------------
def build_batter_gamelogs(df):
    """
    Accepts a pre-fetched Statcast DataFrame and groups it by batter + game date
    to create a daily game log for machine learning.
    """
    if df is None or df.empty:
        print("No batting data found.")
        return pd.DataFrame()

    ab_events = ['strikeout', 'walk', 'single', 'double', 'triple', 'home_run',
                 'field_out', 'force_out', 'grounded_into_dp', 'sac_fly', 'hit_by_pitch']
    df_ab = df[df['events'].isin(ab_events)].copy()

    df_ab['is_AB'] = df_ab['events'].apply(lambda x: 1 if x not in ['walk', 'hit_by_pitch', 'sac_fly'] else 0)
    df_ab['is_Hit'] = df_ab['events'].isin(['single', 'double', 'triple', 'home_run']).astype(int)
    df_ab['is_HR'] = (df_ab['events'] == 'home_run').astype(int)
    df_ab['is_SO'] = (df_ab['events'] == 'strikeout').astype(int)

    def calc_tb(event):
        if event == 'single': return 1
        if event == 'double': return 2
        if event == 'triple': return 3
        if event == 'home_run': return 4
        return 0
    df_ab['TB'] = df_ab['events'].apply(calc_tb)

    game_logs = df_ab.groupby(['batter', 'game_date']).agg(
        PA=('events', 'count'),
        AB=('is_AB', 'sum'),
        H=('is_Hit', 'sum'),
        HR=('is_HR', 'sum'),
        SO=('is_SO', 'sum'),
        TB=('TB', 'sum')
    ).reset_index()

    game_logs['game_date'] = pd.to_datetime(game_logs['game_date'])
    game_logs = game_logs.sort_values(by=['batter', 'game_date'])

    game_logs['Target_HR']          = (game_logs['HR'] >= 1).astype(int)
    game_logs['Target_Hit']         = (game_logs['H'] >= 1).astype(int)
    game_logs['Target_TB_Over_1_5'] = (game_logs['TB'] >= 2).astype(int)
    game_logs['Target_SO']          = (game_logs['SO'] >= 1).astype(int)

    return game_logs


def engineer_batter_rolling_averages(df):
    print("Engineering Batter Rolling Average Features...")
    features_df = df.copy()
    rolling_cols = ['PA', 'AB', 'H', 'HR', 'SO', 'TB']

    for col in rolling_cols:
        if col in features_df.columns:
            features_df[f'rolling_10_{col}'] = (
                features_df.groupby('batter')[col]
                .transform(lambda x: x.rolling(10, min_periods=1).mean().shift(1))
            )

    return features_df.dropna(subset=['rolling_10_HR'])


# --------------------------------------------------------------------------------
# PITCHER PIPELINE
# --------------------------------------------------------------------------------
def build_pitcher_gamelogs(df):
    """
    Accepts a pre-fetched Statcast DataFrame and aggregates pitcher data
    into a daily game log for ML. Filters to starters only (BF >= 12).
    Adds opponent team K% as a feature for each start.
    Targets: Strikeouts (SO), Outs, Hits Allowed (HA), Walks Allowed (BBA)
    """
    if df is None or df.empty:
        print("No pitching data found.")
        return pd.DataFrame()

    ab_events = ['strikeout', 'walk', 'single', 'double', 'triple', 'home_run',
                 'field_out', 'force_out', 'grounded_into_dp', 'sac_fly', 'hit_by_pitch',
                 'double_play', 'sac_bunt', 'strikeout_double_play']

    df_events = df[df['events'].isin(ab_events)].copy()

    df_events['is_SO']  = df_events['events'].isin(['strikeout', 'strikeout_double_play']).astype(int)
    df_events['is_BB']  = (df_events['events'] == 'walk').astype(int)
    df_events['is_Hit'] = df_events['events'].isin(['single', 'double', 'triple', 'home_run']).astype(int)

    def calc_outs(event):
        if event in ['field_out', 'force_out', 'strikeout', 'sac_fly', 'sac_bunt']: return 1
        if event in ['grounded_into_dp', 'double_play', 'strikeout_double_play']: return 2
        return 0
    df_events['Outs_Recorded'] = df_events['events'].apply(calc_outs)

    # ------------------------------------------------------------------
    # Opponent team K% — identify which team is batting against each pitcher
    # inning_topbot='Top' → away team batting; 'Bot' → home team batting
    has_opp_data = all(c in df_events.columns for c in ['inning_topbot', 'home_team', 'away_team'])
    if has_opp_data:
        df_events['batter_team'] = df_events.apply(
            lambda r: r['away_team'] if str(r.get('inning_topbot', '')).lower() == 'top' else r['home_team'],
            axis=1
        )
        df_events['season_year'] = pd.to_datetime(df_events['game_date']).dt.year

        # Per-season, per-team K% (year-level to avoid cross-season leakage)
        team_k = df_events.groupby(['batter_team', 'season_year']).agg(
            _so=('is_SO', 'sum'),
            _pa=('events', 'count')
        ).reset_index()
        team_k['opp_k_pct'] = (team_k['_so'] / team_k['_pa']).round(4)
        team_k = team_k[['batter_team', 'season_year', 'opp_k_pct']]

        # Opponent team per pitcher start
        pitcher_opp = df_events.groupby(['pitcher', 'game_date']).agg(
            opp_team=('batter_team', 'first'),
            season_year=('season_year', 'first')
        ).reset_index()
        pitcher_opp['game_date'] = pd.to_datetime(pitcher_opp['game_date'])

    # ------------------------------------------------------------------
    game_logs = df_events.groupby(['pitcher', 'game_date']).agg(
        BF=('events', 'count'),
        SO=('is_SO', 'sum'),
        BBA=('is_BB', 'sum'),
        HA=('is_Hit', 'sum'),
        Outs=('Outs_Recorded', 'sum')
    ).reset_index()

    game_logs['game_date'] = pd.to_datetime(game_logs['game_date'])
    game_logs = game_logs.sort_values(by=['pitcher', 'game_date'])

    # Filter to starters only: relievers rarely face 12+ batters in one outing
    game_logs = game_logs[game_logs['BF'] >= 12].copy()

    # Join opponent K%
    if has_opp_data:
        game_logs = game_logs.merge(pitcher_opp, on=['pitcher', 'game_date'], how='left')
        game_logs = game_logs.merge(
            team_k,
            left_on=['opp_team', 'season_year'],
            right_on=['batter_team', 'season_year'],
            how='left'
        )
        game_logs.drop(columns=['batter_team'], inplace=True, errors='ignore')
        median_k_pct = game_logs['opp_k_pct'].median()
        game_logs['opp_k_pct'] = game_logs['opp_k_pct'].fillna(median_k_pct)

    game_logs['Target_SO_Over_4_5']    = (game_logs['SO'] >= 5).astype(int)
    game_logs['Target_Outs_Over_15_5'] = (game_logs['Outs'] >= 16).astype(int)
    game_logs['Target_HA_Over_4_5']    = (game_logs['HA'] >= 5).astype(int)
    game_logs['Target_BBA_Over_1_5']   = (game_logs['BBA'] >= 2).astype(int)

    return game_logs


def engineer_pitcher_rolling_averages(df):
    print("Engineering Pitcher Rolling Average Features...")
    features_df = df.copy()

    # Single rolling window for volume/context stats
    for col in ['BF', 'BBA', 'HA', 'Outs']:
        if col in features_df.columns:
            features_df[f'rolling_5_{col}'] = (
                features_df.groupby('pitcher')[col]
                .transform(lambda x: x.rolling(5, min_periods=1).mean().shift(1))
            )

    # Multi-window for SO to capture hot/cold streaks
    for window in [3, 5, 10]:
        features_df[f'rolling_{window}_SO'] = (
            features_df.groupby('pitcher')['SO']
            .transform(lambda x: x.rolling(window, min_periods=1).mean().shift(1))
        )

    # K% = strikeouts per batter faced per start, then rolling average
    features_df['K_pct'] = features_df['SO'] / features_df['BF'].replace(0, 1)
    for window in [3, 5, 10]:
        features_df[f'rolling_{window}_K_pct'] = (
            features_df.groupby('pitcher')['K_pct']
            .transform(lambda x: x.rolling(window, min_periods=1).mean().shift(1))
        )

    return features_df.dropna(subset=['rolling_5_SO'])


# --------------------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------------------
def main():
    start_date = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_START
    end_date   = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_END

    print(f"Fetching Statcast data from {start_date} to {end_date} (this may take several minutes)...")
    # Fetch once — both batter and pitcher data live in the same Statcast payload
    raw_df = pybaseball.statcast(start_dt=start_date, end_dt=end_date)

    if raw_df is None or raw_df.empty:
        print("No Statcast data returned. Exiting.")
        return

    # 1. Batter Pipeline
    raw_batter_df = build_batter_gamelogs(raw_df)
    if not raw_batter_df.empty:
        ml_batter_dataset = engineer_batter_rolling_averages(raw_batter_df)
        batter_out = os.path.join(DATA_DIR, "mlb_training_dataset.csv")
        ml_batter_dataset.to_csv(batter_out, index=False)
        print(f"Batter Dataset Built: {len(ml_batter_dataset)} rows saved to {batter_out}")

    # 2. Pitcher Pipeline
    raw_pitcher_df = build_pitcher_gamelogs(raw_df)
    if not raw_pitcher_df.empty:
        ml_pitcher_dataset = engineer_pitcher_rolling_averages(raw_pitcher_df)
        pitcher_out = os.path.join(DATA_DIR, "mlb_pitcher_training_dataset.csv")
        ml_pitcher_dataset.to_csv(pitcher_out, index=False)
        print(f"Pitcher Dataset Built: {len(ml_pitcher_dataset)} rows saved to {pitcher_out}")
        target_dist = ml_pitcher_dataset['Target_SO_Over_4_5'].value_counts().to_dict()
        print(f"  pitcher_strikeouts class balance: {target_dist}")


if __name__ == "__main__":
    main()
