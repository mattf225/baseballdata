import os
import joblib
import unicodedata
import pandas as pd

MODELS_DIR = os.path.join(os.path.dirname(__file__), "../model/trained_models")

EV_THRESHOLD = float(os.environ.get("EV_THRESHOLD", "0.05"))

EXPECTED_MARKETS = [
    'batter_home_runs',
    'batter_hits',
    'batter_total_bases_1.5',
    'batter_strikeouts',
    'pitcher_strikeouts',
    'pitcher_outs',
    'pitcher_hits_allowed',
    'pitcher_walks_allowed',
]

# Lazy-load models on first use
_models = None

def _load_models():
    global _models
    if _models is not None:
        return _models
    _models = {}
    for market in EXPECTED_MARKETS:
        model_path = os.path.join(MODELS_DIR, f"{market}_model.pkl")
        if os.path.exists(model_path):
            _models[market] = joblib.load(model_path)
        else:
            print(f"Warning: ML Model for {market} not found at {model_path}")
    return _models


def _normalize_name(name: str) -> str:
    """Strips accents and lowercases a player name for fuzzy matching."""
    return unicodedata.normalize('NFD', name).encode('ascii', 'ignore').decode('utf-8').lower().strip()


def calculate_implied_prob(american_odds: int) -> float:
    """
    Converts American Odds to no-vig implied probability.
    Removes the sportsbook margin by normalizing against both sides of the market.
    For single-outcome props, applies a simple vig-strip assuming ~5% book margin.
    """
    if american_odds > 0:
        raw = 100 / (american_odds + 100)
    elif american_odds < 0:
        odds_abs = abs(american_odds)
        raw = odds_abs / (odds_abs + 100)
    else:
        return 0.0

    # Strip approximate vig (assume ~5% book overround on binary props)
    no_vig = raw / 1.05
    return min(no_vig, 1.0)


def _get_rolling_stat(player_name: str, stats_df, stat_col: str) -> float:
    """Extracts a season stat for a player using accent-insensitive name matching."""
    if stats_df is None or stats_df.empty:
        return 0.0

    normalized_target = _normalize_name(player_name)
    mask = stats_df['Name'].apply(lambda n: _normalize_name(str(n)) == normalized_target)
    player_row = stats_df[mask]

    if player_row.empty:
        return None  # Signal: player not found in dataset

    try:
        val = float(player_row.iloc[0][stat_col]) if stat_col in player_row.columns else 0.0
        return 0.0 if pd.isna(val) else val
    except Exception:
        return 0.0


def generate_true_prob(market_name, player_name, batter_df, pitcher_df=None):
    """
    Uses calibrated Random Forest ML models to output the true probability
    for a given sportsbook market and player.
    Returns None if the player cannot be found in the stats dataset.
    """
    models = _load_models()

    if market_name not in models:
        return None

    clf = models[market_name]

    # ---------------------------------------------------------
    # BATTER PIPELINE INFERENCE
    # ---------------------------------------------------------
    if market_name.startswith('batter'):
        games_played = _get_rolling_stat(player_name, batter_df, 'G')
        if games_played is None:
            return None  # Player not found
        if games_played == 0:
            games_played = 1

        live_features = {
            'rolling_10_PA': _get_rolling_stat(player_name, batter_df, 'PA') / games_played * 10,
            'rolling_10_AB': _get_rolling_stat(player_name, batter_df, 'AB') / games_played * 10,
            'rolling_10_H':  _get_rolling_stat(player_name, batter_df, 'H')  / games_played * 10,
            'rolling_10_HR': _get_rolling_stat(player_name, batter_df, 'HR') / games_played * 10,
            'rolling_10_SO': _get_rolling_stat(player_name, batter_df, 'SO') / games_played * 10,
            'rolling_10_TB': _get_rolling_stat(player_name, batter_df, 'TB') / games_played * 10,
        }

    # ---------------------------------------------------------
    # PITCHER PIPELINE INFERENCE
    # ---------------------------------------------------------
    elif market_name.startswith('pitcher'):
        games_played = _get_rolling_stat(player_name, pitcher_df, 'G')
        if games_played is None:
            return None  # Player not found
        if games_played == 0:
            games_played = 1

        ip = _get_rolling_stat(player_name, pitcher_df, 'IP') or 0.0
        # Note: BF is approximated from IP until per-game logs are available
        mock_bf = (ip * 3.5) / games_played * 5

        live_features = {
            'rolling_5_BF':   mock_bf,
            'rolling_5_SO':   _get_rolling_stat(player_name, pitcher_df, 'SO')  / games_played * 5,
            'rolling_5_BBA':  _get_rolling_stat(player_name, pitcher_df, 'BB')  / games_played * 5,
            'rolling_5_HA':   _get_rolling_stat(player_name, pitcher_df, 'H')   / games_played * 5,
            'rolling_5_Outs': (ip * 3) / games_played * 5,  # IP * 3 = Total Outs
        }

    else:
        return None

    X_live = pd.DataFrame([live_features])
    true_prob = clf.predict_proba(X_live)[0][1]
    return float(true_prob)


def check_ev(true_prob: float, implied_prob: float) -> dict:
    """Determines if a positive edge exists above the configured threshold."""
    edge = true_prob - implied_prob
    return {"is_ev": edge >= EV_THRESHOLD, "edge": edge}
