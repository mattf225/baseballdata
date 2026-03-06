import os
import pandas as pd
import pybaseball
from datetime import datetime, timedelta

# Enable cache so we don't spam MLB servers
pybaseball.cache.enable()

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# --------------------------------------------------------------------------------
# BATTER PIPELINE
# --------------------------------------------------------------------------------
def build_batter_gamelogs(start_date, end_date):
    """
    Fetches pitch-by-pitch Statcast data and groups it by Player and Game Date
    to create a daily game log for machine learning.
    """
    print(f"Fetching Statcast BATTER pitch data from {start_date} to {end_date} (This may take a minute)...")
    
    df = pybaseball.statcast(start_dt=start_date, end_dt=end_date)
    
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
    
    game_logs['Target_HR'] = (game_logs['HR'] >= 1).astype(int)
    game_logs['Target_Hit'] = (game_logs['H'] >= 1).astype(int)
    game_logs['Target_TB_Over_1_5'] = (game_logs['TB'] >= 2).astype(int)
    game_logs['Target_SO'] = (game_logs['SO'] >= 1).astype(int)
    
    return game_logs

def engineer_batter_rolling_averages(df):
     print("Engineeing Batter Rolling Average Features...")
     features_df = df.copy()
     rolling_cols = ['PA', 'AB', 'H', 'HR', 'SO', 'TB']
     
     for col in rolling_cols:
          if col in features_df.columns:
               features_df[f'rolling_10_{col}'] = features_df.groupby('batter')[col].transform(lambda x: x.rolling(10, min_periods=1).mean().shift(1))
               
     return features_df.dropna(subset=[f'rolling_10_HR'])

# --------------------------------------------------------------------------------
# PITCHER PIPELINE
# --------------------------------------------------------------------------------
def build_pitcher_gamelogs(start_date, end_date):
    """
    Fetches Statcast Pitcher data and aggregates it into a game log for ML.
    We target: Strikeouts (SO), Outs, Hits Allowed (HA), Walks Allowed (BBA)
    """
    print(f"Fetching Statcast PITCHER pitch data from {start_date} to {end_date}...")
    
    # Re-using statcast payload because it contains the pitcher data as well!
    df = pybaseball.statcast(start_dt=start_date, end_dt=end_date)
    
    if df is None or df.empty:
         print("No pitching data found.")
         return pd.DataFrame()

    # Filter to end-of-at-bat events
    ab_events = ['strikeout', 'walk', 'single', 'double', 'triple', 'home_run', 
                 'field_out', 'force_out', 'grounded_into_dp', 'sac_fly', 'hit_by_pitch',
                 'double_play', 'sac_bunt', 'strikeout_double_play']
                 
    df_events = df[df['events'].isin(ab_events)].copy()
    
    # Binary assignments
    df_events['is_SO'] = df_events['events'].isin(['strikeout', 'strikeout_double_play']).astype(int)
    df_events['is_BB'] = (df_events['events'] == 'walk').astype(int)
    df_events['is_Hit'] = df_events['events'].isin(['single', 'double', 'triple', 'home_run']).astype(int)
    
    # Calculating Outs generated on the pitch
    def calc_outs(event):
         if event in ['field_out', 'force_out', 'strikeout', 'sac_fly', 'sac_bunt']: return 1
         if event in ['grounded_into_dp', 'double_play', 'strikeout_double_play']: return 2
         return 0
    df_events['Outs_Recorded'] = df_events['events'].apply(calc_outs)
    
    # Group by Pitcher and Game Date
    game_logs = df_events.groupby(['pitcher', 'game_date']).agg(
        BF=('events', 'count'), # Batters Faced
        SO=('is_SO', 'sum'),
        BBA=('is_BB', 'sum'),
        HA=('is_Hit', 'sum'),
        Outs=('Outs_Recorded', 'sum')
    ).reset_index()
    
    game_logs['game_date'] = pd.to_datetime(game_logs['game_date'])
    game_logs = game_logs.sort_values(by=['pitcher', 'game_date'])
    
    # Target Labels (Based on standard Sportsbook Lines)
    # E.g., Did they get >4.5 Strikeouts? Did they get >15.5 Outs?
    game_logs['Target_SO_Over_4_5'] = (game_logs['SO'] >= 5).astype(int)
    game_logs['Target_Outs_Over_15_5'] = (game_logs['Outs'] >= 16).astype(int)
    game_logs['Target_HA_Over_4_5'] = (game_logs['HA'] >= 5).astype(int)
    game_logs['Target_BBA_Over_1_5'] = (game_logs['BBA'] >= 2).astype(int)
    
    return game_logs

def engineer_pitcher_rolling_averages(df):
     print("Engineeing Pitcher Rolling Average Features...")
     features_df = df.copy()
     
     # Use 5-game rolling for pitchers (since they play less frequently)
     rolling_cols = ['BF', 'SO', 'BBA', 'HA', 'Outs']
     
     for col in rolling_cols:
          if col in features_df.columns:
               features_df[f'rolling_5_{col}'] = features_df.groupby('pitcher')[col].transform(lambda x: x.rolling(5, min_periods=1).mean().shift(1))
               
     return features_df.dropna(subset=[f'rolling_5_SO'])

# --------------------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------------------
def main():
    # Use a smaller 2-month window for the prototype test to generate both datasets
    start_date = "2023-05-01"
    end_date = "2023-06-30"
    
    # 1. Batter Pipeline
    raw_batter_df = build_batter_gamelogs(start_date, end_date)
    if not raw_batter_df.empty:
         ml_batter_dataset = engineer_batter_rolling_averages(raw_batter_df)
         batter_out = os.path.join(DATA_DIR, "mlb_training_dataset.csv")
         ml_batter_dataset.to_csv(batter_out, index=False)
         print(f"✅ Batter Dataset Built: {len(ml_batter_dataset)} rows saved to {batter_out}")
         
    # 2. Pitcher Pipeline
    raw_pitcher_df = build_pitcher_gamelogs(start_date, end_date)
    if not raw_pitcher_df.empty:
         ml_pitcher_dataset = engineer_pitcher_rolling_averages(raw_pitcher_df)
         pitcher_out = os.path.join(DATA_DIR, "mlb_pitcher_training_dataset.csv")
         ml_pitcher_dataset.to_csv(pitcher_out, index=False)
         print(f"✅ Pitcher Dataset Built: {len(ml_pitcher_dataset)} rows saved to {pitcher_out}")

if __name__ == "__main__":
    main()
