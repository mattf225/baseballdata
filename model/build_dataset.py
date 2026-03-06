import os
import pandas as pd
import pybaseball
from datetime import datetime, timedelta

# Enable cache so we don't spam MLB servers
pybaseball.cache.enable()

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

def build_batter_gamelogs(start_date, end_date):
    """
    Fetches pitch-by-pitch Statcast data and groups it by Player and Game Date
    to create a daily game log for machine learning.
    """
    print(f"Fetching Statcast pitch data from {start_date} to {end_date} (This may take a minute)...")
    
    # statcast() pulls every pitch thrown in the date range. 
    # It is exhaustive and requires pandas grouping to turn into 'game logs'
    df = pybaseball.statcast(start_dt=start_date, end_dt=end_date)
    
    if df is None or df.empty:
         print("No batting data found.")
         return pd.DataFrame()
         
    print(f"Filtering {len(df)} total pitches...")
    
    # We only care about pitches that resulted in the end of an At Bat
    ab_events = ['strikeout', 'walk', 'single', 'double', 'triple', 'home_run', 
                 'field_out', 'force_out', 'grounded_into_dp', 'sac_fly', 'hit_by_pitch']
    df_ab = df[df['events'].isin(ab_events)].copy()
    
    # Create Binary outcome columns for the pitch event
    df_ab['is_AB'] = df_ab['events'].apply(lambda x: 1 if x not in ['walk', 'hit_by_pitch', 'sac_fly'] else 0)
    df_ab['is_Hit'] = df_ab['events'].isin(['single', 'double', 'triple', 'home_run']).astype(int)
    df_ab['is_HR'] = (df_ab['events'] == 'home_run').astype(int)
    df_ab['is_SO'] = (df_ab['events'] == 'strikeout').astype(int)
    
    # Calculate Total Bases for the event
    def calc_tb(event):
        if event == 'single': return 1
        if event == 'double': return 2
        if event == 'triple': return 3
        if event == 'home_run': return 4
        return 0
    df_ab['TB'] = df_ab['events'].apply(calc_tb)

    # Group by Batter and Game Date to create Daily Game Logs
    game_logs = df_ab.groupby(['batter', 'game_date']).agg(
        PA=('events', 'count'),
        AB=('is_AB', 'sum'),
        H=('is_Hit', 'sum'),
        HR=('is_HR', 'sum'),
        SO=('is_SO', 'sum'),
        TB=('TB', 'sum')
    ).reset_index()

    # Sort chronologically
    game_logs['game_date'] = pd.to_datetime(game_logs['game_date'])
    game_logs = game_logs.sort_values(by=['batter', 'game_date'])
    
    # Generate Target Labels (The Prop Bet Outcomes)
    game_logs['Target_HR'] = (game_logs['HR'] >= 1).astype(int)
    game_logs['Target_Hit'] = (game_logs['H'] >= 1).astype(int)
    game_logs['Target_TB_Over_1_5'] = (game_logs['TB'] >= 2).astype(int)
    game_logs['Target_SO'] = (game_logs['SO'] >= 1).astype(int)
    
    return game_logs

def feature_engineer_rolling_averages(df):
     """
     Calculates past performance metrics (Input Features) to predict the Target Labels.
     """
     print("Engineeing Rolling Average Features...")
     features_df = df.copy()
     
     # Calculate 10-game rolling averages for each player (Shifted by 1 so it doesn't leak today's result)
     rolling_cols = ['PA', 'AB', 'H', 'HR', 'SO', 'TB']
     
     for col in rolling_cols:
          if col in features_df.columns:
               # Group by batter ID, calculate rolling mean, shift 1 game back
               features_df[f'rolling_10_{col}'] = features_df.groupby('batter')[col].transform(lambda x: x.rolling(10, min_periods=1).mean().shift(1))
               
     # Drop rows where we don't have enough history (the NA shifted rows)
     features_df = features_df.dropna(subset=[f'rolling_10_HR'])
     return features_df

def main():
    # Use a smaller 1-month window for the prototype test to save time
    start_date = "2023-05-01"
    end_date = "2023-05-31"
    
    raw_batter_df = build_batter_gamelogs(start_date, end_date)
    if not raw_batter_df.empty:
         ml_dataset = feature_engineer_rolling_averages(raw_batter_df)
         
         output_path = os.path.join(DATA_DIR, "mlb_training_dataset.csv")
         ml_dataset.to_csv(output_path, index=False)
         print(f"✅ ML Dataset Built successfully: {len(ml_dataset)} game logs saved to {output_path}")
         print("\nSample Columns:")
         print(ml_dataset[['batter', 'game_date', 'Target_HR', 'rolling_10_HR', 'rolling_10_TB']].head())

if __name__ == "__main__":
    main()
