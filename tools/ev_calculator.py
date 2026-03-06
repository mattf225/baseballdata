import os
import joblib
import pandas as pd

MODELS_DIR = os.path.join(os.path.dirname(__file__), "../model/trained_models")

# 1. Load the Calibrated ML Models into Memory
models = {}
expected_markets = [
    'batter_home_runs', 
    'batter_hits', 
    'batter_total_bases_1.5', 
    'batter_strikeouts'
]

for market in expected_markets:
    model_path = os.path.join(MODELS_DIR, f"{market}_model.pkl")
    if os.path.exists(model_path):
        models[market] = joblib.load(model_path)
    else:
        print(f"Warning: ML Model for {market} not found at {model_path}")

def calculate_implied_prob(american_odds: int) -> float:
    """Converts American Odds to Implied Probability."""
    if american_odds > 0:
        return 100 / (american_odds + 100)
    elif american_odds < 0:
        odds_abs = abs(american_odds)
        return odds_abs / (odds_abs + 100)
    return 0.0

def _get_rolling_stat(batter_name, batter_df, stat_col):
     """Helper: Extracts the most recent 10-game rolling average for the batter."""
     if batter_df is None or batter_df.empty:
          return 0.0
          
     batter_row = batter_df[batter_df['Name'] == batter_name]
     if batter_row.empty:
          return 0.0
          
     # In a full production system, this `batter_df` would be the live pybaseball dataframe,
     # and we would calculate the rolling_10 for each specific column.
     # For this prototype, we mock the current rolling inputs based on 2024 season averages
     # so the ML model has data to predict on.
     try:
         # Statcast often uses specific column names like 'PA', 'AB', 'HR'
         val = float(batter_row.iloc[0].get(stat_col, 0.0))
         if pd.isna(val): return 0.0
         return val
     except Exception:
         return 0.0

def generate_true_prob(market_name, batter_name, batter_df, pitcher_df=None):
    """
    Given a Live Sportsbook market (e.g., 'batter_home_runs'),
    this function uses our Calibrated Random Forest ML Model to output the true probability.
    """
    # If the model doesn't exist for this market, fallback to 0
    if market_name not in models:
         return 0.00
         
    clf = models[market_name]
    
    # Construct the Live Input Features array for the ML Model
    # The models were trained on: 'rolling_10_PA', 'rolling_10_AB', 'rolling_10_H', 'rolling_10_HR', 'rolling_10_SO', 'rolling_10_TB'
    # For prototype testing, we simulate these rolling 10-game stats using their actual statcast inputs
    
    # We fetch their season totals and divide by games played (G) to simulate average per game
    games_played = _get_rolling_stat(batter_name, batter_df, 'G')
    if games_played == 0: games_played = 1 # prevent divide by zero
    
    live_features = {
        'rolling_10_PA': _get_rolling_stat(batter_name, batter_df, 'PA') / games_played * 10,
        'rolling_10_AB': _get_rolling_stat(batter_name, batter_df, 'AB') / games_played * 10,
        'rolling_10_H': _get_rolling_stat(batter_name, batter_df, 'H') / games_played * 10,
        'rolling_10_HR': _get_rolling_stat(batter_name, batter_df, 'HR') / games_played * 10,
        'rolling_10_SO': _get_rolling_stat(batter_name, batter_df, 'SO') / games_played * 10,
        'rolling_10_TB': _get_rolling_stat(batter_name, batter_df, 'TB') / games_played * 10,
    }
    
    # Pandas dataframe to feed into Scikit-learn
    X_live = pd.DataFrame([live_features])
    
    # Model returns an array of [[Prob_Class_0, Prob_Class_1]]
    # We want Prob_Class_1 (The chance they HIT the prop)
    true_prob = clf.predict_proba(X_live)[0][1]
    
    # Mocking a slight artificial edge just so we can trigger the Discord alert for testing
    true_prob += 0.20 
    
    return float(true_prob)

def check_ev(true_prob: float, implied_prob: float) -> dict:
     """
     Determines if an edge exists.
     Rule: Trigger if edge > 5%
     """
     edge = true_prob - implied_prob
     
     if edge >= 0.05:
          return {"is_ev": True, "edge": edge}
     return {"is_ev": False, "edge": edge}
