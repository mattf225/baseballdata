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

# 2024 MLB league-average batter K% used as fallback when opponent team is unknown
_LEAGUE_AVG_OPP_K_PCT = 0.224

# Minimum DB entries required before switching from season-aggregate to DB-backed features
MIN_STARTS_FOR_DB_FEATURES = 3   # pitcher starts
MIN_GAMES_FOR_DB_FEATURES  = 5   # batter games

# Maps Odds API full team names → FanGraphs/pybaseball team abbreviations
MLB_TEAM_ABBREV = {
    "Arizona Diamondbacks": "ARI",
    "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL",
    "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHC",
    "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN",
    "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL",
    "Detroit Tigers": "DET",
    "Houston Astros": "HOU",
    "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA",
    "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA",
    "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN",
    "New York Mets": "NYM",
    "New York Yankees": "NYY",
    "Oakland Athletics": "OAK",
    "Athletics": "OAK",           # 2025+ Sacramento/Las Vegas rebranding
    "Las Vegas Athletics": "OAK",
    "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT",
    "San Diego Padres": "SD",
    "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA",
    "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TB",
    "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR",
    "Washington Nationals": "WSH",
}

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


def _resolve_opp_team_abbrev(player_name: str, pitcher_df, home_team: str, away_team: str):
    """
    Determines the opponent team abbreviation for a pitcher given game home/away teams.
    Looks up the pitcher's team from season stats, then returns the other team.
    """
    if pitcher_df is None or not home_team or not away_team:
        return None

    norm_name = _normalize_name(player_name)
    mask = pitcher_df['Name'].apply(lambda n: _normalize_name(str(n)) == norm_name)
    player_row = pitcher_df[mask]

    if player_row.empty or 'Team' not in player_row.columns:
        return None

    pitcher_team = str(player_row.iloc[0]['Team'])
    home_abbrev = MLB_TEAM_ABBREV.get(home_team)
    away_abbrev = MLB_TEAM_ABBREV.get(away_team)

    if pitcher_team == home_abbrev:
        return away_abbrev
    elif pitcher_team == away_abbrev:
        return home_abbrev
    return None


def _get_opp_k_pct(team_batting_df, opp_team_abbrev: str) -> float:
    """
    Returns the opponent team's season batter K% (SO/PA).
    Falls back to league average if team is unknown or data unavailable.
    """
    if team_batting_df is None or not opp_team_abbrev:
        return _LEAGUE_AVG_OPP_K_PCT

    if 'Team' not in team_batting_df.columns:
        return _LEAGUE_AVG_OPP_K_PCT

    mask = team_batting_df['Team'] == opp_team_abbrev
    team_row = team_batting_df[mask]

    if team_row.empty:
        return _LEAGUE_AVG_OPP_K_PCT

    # FanGraphs K% may be a decimal (0.224) or percentage string ("22.4%")
    k_pct = team_row.iloc[0].get('K%', None)
    if k_pct is None or (isinstance(k_pct, float) and pd.isna(k_pct)):
        # Fall back to computing from raw SO and PA
        try:
            so = float(team_row.iloc[0].get('SO', 0))
            pa = float(team_row.iloc[0].get('PA', 1))
            return so / pa if pa > 0 else _LEAGUE_AVG_OPP_K_PCT
        except Exception:
            return _LEAGUE_AVG_OPP_K_PCT

    if isinstance(k_pct, str):
        k_pct = float(k_pct.strip('%')) / 100

    k_pct = float(k_pct)
    return k_pct / 100 if k_pct > 1 else k_pct  # normalize if stored as percentage


def _windowed_mean(values: list, window: int) -> float:
    """Returns the mean of the last `window` values, or mean of all if fewer exist."""
    if not values:
        return 0.0
    subset = values[-window:]
    return sum(subset) / len(subset)


def _features_from_gamelogs(recent_df: pd.DataFrame) -> dict:
    """
    Converts a DataFrame of recent pitcher starts (from pitcher_gamelogs) into
    the 11-feature dict expected by pitcher ML models.
    Rows should be sorted descending by game_date (most recent first).
    opp_k_pct in the returned dict is a placeholder — callers must override it
    with today's live opponent K% via _get_opp_k_pct().
    """
    # Sort ascending for rolling windows (oldest → newest)
    df = recent_df.sort_values('game_date').reset_index(drop=True)

    bf_vals   = df['BF'].tolist()
    so_vals   = df['SO'].tolist()
    bba_vals  = df['BBA'].tolist()
    ha_vals   = df['HA'].tolist()
    outs_vals = df['Outs'].tolist()
    kpct_vals = df['K_pct'].fillna(0.0).tolist()

    # opp_k_pct: use stored value as a fallback; overridden by live value in generate_true_prob
    stored_opp_k = df['opp_k_pct'].dropna()
    opp_k_pct_fallback = float(stored_opp_k.iloc[-1]) if not stored_opp_k.empty else _LEAGUE_AVG_OPP_K_PCT

    return {
        'rolling_5_BF':     _windowed_mean(bf_vals,   5),
        'rolling_3_SO':     _windowed_mean(so_vals,   3),
        'rolling_5_SO':     _windowed_mean(so_vals,   5),
        'rolling_10_SO':    _windowed_mean(so_vals,  10),
        'rolling_3_K_pct':  _windowed_mean(kpct_vals, 3),
        'rolling_5_K_pct':  _windowed_mean(kpct_vals, 5),
        'rolling_10_K_pct': _windowed_mean(kpct_vals,10),
        'rolling_5_BBA':    _windowed_mean(bba_vals,  5),
        'rolling_5_HA':     _windowed_mean(ha_vals,   5),
        'rolling_5_Outs':   _windowed_mean(outs_vals, 5),
        'opp_k_pct':        opp_k_pct_fallback,
    }


def _batter_features_from_gamelogs(recent_df: pd.DataFrame) -> dict:
    """
    Converts a DataFrame of recent batter games (from batter_gamelogs) into
    the 6-feature dict expected by batter ML models.
    Features are rolling-10 means matching build_dataset.py training logic.
    """
    df = recent_df.sort_values('game_date').reset_index(drop=True)

    return {
        'rolling_10_PA': _windowed_mean(df['PA'].tolist(), 10),
        'rolling_10_AB': _windowed_mean(df['AB'].tolist(), 10),
        'rolling_10_H':  _windowed_mean(df['H'].tolist(),  10),
        'rolling_10_HR': _windowed_mean(df['HR'].tolist(), 10),
        'rolling_10_SO': _windowed_mean(df['SO'].tolist(), 10),
        'rolling_10_TB': _windowed_mean(df['TB'].tolist(), 10),
    }


def generate_true_prob(market_name, player_name, batter_df, pitcher_df=None,
                       team_batting_df=None, home_team=None, away_team=None,
                       pitcher_gamelogs_cache=None, batter_gamelogs_cache=None):
    """
    Uses calibrated Random Forest ML models to output the true probability
    for a given sportsbook market and player.
    Returns None if the player cannot be found in the stats dataset.

    For pitcher markets, pass team_batting_df + home_team + away_team to enable
    opponent K% feature (otherwise falls back to league average).
    Pass pitcher_gamelogs_cache / batter_gamelogs_cache (dicts keyed by normalized
    name → DataFrame of recent games) for DB-backed rolling features.
    """
    models = _load_models()

    if market_name not in models:
        return None

    clf = models[market_name]

    # ---------------------------------------------------------
    # BATTER PIPELINE INFERENCE
    # ---------------------------------------------------------
    if market_name.startswith('batter'):
        # Try DB-backed rolling features first
        norm_name = _normalize_name(player_name)
        recent_df = None
        if batter_gamelogs_cache is not None:
            recent_df = batter_gamelogs_cache.get(norm_name)

        if recent_df is not None and len(recent_df) >= MIN_GAMES_FOR_DB_FEATURES:
            live_features = _batter_features_from_gamelogs(recent_df)
        else:
            # Fallback: season-aggregate approximation (per-game means)
            games_played = _get_rolling_stat(player_name, batter_df, 'G')
            if games_played is None:
                return None  # Player not found
            if games_played == 0:
                games_played = 1

            live_features = {
                'rolling_10_PA': _get_rolling_stat(player_name, batter_df, 'PA') / games_played,
                'rolling_10_AB': _get_rolling_stat(player_name, batter_df, 'AB') / games_played,
                'rolling_10_H':  _get_rolling_stat(player_name, batter_df, 'H')  / games_played,
                'rolling_10_HR': _get_rolling_stat(player_name, batter_df, 'HR') / games_played,
                'rolling_10_SO': _get_rolling_stat(player_name, batter_df, 'SO') / games_played,
                'rolling_10_TB': _get_rolling_stat(player_name, batter_df, 'TB') / games_played,
            }

    # ---------------------------------------------------------
    # PITCHER PIPELINE INFERENCE
    # ---------------------------------------------------------
    elif market_name.startswith('pitcher'):
        # Always resolve today's live opponent K% for both branches
        opp_team_abbrev = _resolve_opp_team_abbrev(player_name, pitcher_df, home_team, away_team)
        live_opp_k_pct = _get_opp_k_pct(team_batting_df, opp_team_abbrev)

        # Try DB-backed rolling features first
        norm_name = _normalize_name(player_name)
        recent_df = None
        if pitcher_gamelogs_cache is not None:
            recent_df = pitcher_gamelogs_cache.get(norm_name)

        if recent_df is not None and len(recent_df) >= MIN_STARTS_FOR_DB_FEATURES:
            live_features = _features_from_gamelogs(recent_df)
            # Always override with today's live opponent K%
            live_features['opp_k_pct'] = live_opp_k_pct
        else:
            # Fallback: season-aggregate approximation
            games_played = _get_rolling_stat(player_name, pitcher_df, 'G')
            if games_played is None:
                return None  # Player not found
            if games_played == 0:
                games_played = 1

            ip = _get_rolling_stat(player_name, pitcher_df, 'IP') or 0.0

            so_per_game   = (_get_rolling_stat(player_name, pitcher_df, 'SO') or 0.0) / games_played
            bb_per_game   = (_get_rolling_stat(player_name, pitcher_df, 'BB') or 0.0) / games_played
            h_per_game    = (_get_rolling_stat(player_name, pitcher_df, 'H')  or 0.0) / games_played
            ip_per_game   = ip / games_played
            bf_per_game   = ip_per_game * 3.5   # BF approximated from IP
            outs_per_game = ip_per_game * 3      # IP * 3 = total outs recorded

            k_pct = so_per_game / bf_per_game if bf_per_game > 0 else 0.0

            live_features = {
                'rolling_5_BF':     bf_per_game * 5,
                'rolling_3_SO':     so_per_game * 3,
                'rolling_5_SO':     so_per_game * 5,
                'rolling_10_SO':    so_per_game * 10,
                'rolling_3_K_pct':  k_pct,
                'rolling_5_K_pct':  k_pct,
                'rolling_10_K_pct': k_pct,
                'rolling_5_BBA':    bb_per_game * 5,
                'rolling_5_HA':     h_per_game * 5,
                'rolling_5_Outs':   outs_per_game * 5,
                'opp_k_pct':        live_opp_k_pct,
            }

    else:
        return None

    # Build feature vector using only the columns the model was trained on
    model_features = clf.feature_names_in_ if hasattr(clf, 'feature_names_in_') else list(live_features.keys())
    X_live = pd.DataFrame([{f: live_features.get(f, 0.0) for f in model_features}])
    true_prob = clf.predict_proba(X_live)[0][1]
    return float(true_prob)


def check_ev(true_prob: float, implied_prob: float) -> dict:
    """Determines if a positive edge exists above the configured threshold."""
    edge = true_prob - implied_prob
    return {"is_ev": edge >= EV_THRESHOLD, "edge": edge}
