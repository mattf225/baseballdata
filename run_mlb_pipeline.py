import sys
import os
import logging
from datetime import datetime, timezone

sys.path.append(os.path.join(os.path.dirname(__file__), "tools"))

from api_client import DataIngestor
import ev_calculator
from db_client import DatabaseClient
from notifier import DiscordNotifier
from gamelog_updater import run_gamelog_update
from bovada_client import fetch_bovada_props
from kalshi_client import fetch_kalshi_props
from mlb_schedule import get_todays_games, build_matchup_map, get_probable_starters

# Configure structured logging
log_dir = os.path.join(os.path.dirname(__file__), "logs")
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

log_file = os.path.join(log_dir, f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

REQUIRED_ENV_VARS = ["ODDS_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "DISCORD_WEBHOOK_URL"]

# MLB regular season: March 26 – October 15 (2026 season opens in Tokyo)
SEASON_START_MONTH, SEASON_START_DAY = 3, 26
SEASON_END_MONTH,   SEASON_END_DAY   = 10, 15

def validate_env():
    """Fail fast if any required environment variable is missing."""
    missing = [v for v in REQUIRED_ENV_VARS if not os.environ.get(v)]
    if missing:
        raise EnvironmentError(f"Missing required environment variables: {', '.join(missing)}")

def is_regular_season() -> bool:
    """Returns True if today falls within the MLB regular season window."""
    today = datetime.now()
    m, d = today.month, today.day
    after_start = (m > SEASON_START_MONTH) or (m == SEASON_START_MONTH and d >= SEASON_START_DAY)
    before_end  = (m < SEASON_END_MONTH)   or (m == SEASON_END_MONTH   and d <= SEASON_END_DAY)
    return after_start and before_end

def main():
    logger.info("Initializing B.L.A.S.T. MLB Pipeline...")

    if not is_regular_season() and not os.environ.get("ALLOW_SPRING_TRAINING"):
        logger.info("Outside MLB regular season (Mar 26 – Oct 15). Pipeline exiting — set ALLOW_SPRING_TRAINING=true to override.")
        logger.info("Set ALLOW_SPRING_TRAINING=true in .env to override for testing.")
        return

    validate_env()

    # Initialize Layer 3 Tools
    ingestor = DataIngestor()
    db = DatabaseClient()
    notifier = DiscordNotifier()

    # Step 0: Store yesterday's pitcher gamelogs before today's inference
    logger.info("Updating pitcher gamelogs from yesterday's results...")
    gamelog_count = run_gamelog_update()
    logger.info(f"Pitcher gamelog update complete: {gamelog_count} rows upserted.")

    # Step 1: Fetch live odds — Bovada + Kalshi only
    logger.info("Fetching live odds from Bovada...")
    events = fetch_bovada_props()

    logger.info("Fetching live odds from Kalshi...")
    kalshi_events = fetch_kalshi_props()
    events = events + kalshi_events

    if not events:
        logger.info("No events found. Exiting pipeline.")
        return

    # Step 1.5: Fetch MLB schedule for opposing pitcher matchups
    logger.info("Fetching MLB schedule for player matchup data...")
    mlb_games = get_todays_games()
    matchup_map = {}
    probable_starters_norm = set()
    if mlb_games:
        matchup_map = build_matchup_map(mlb_games)
        logger.info(f"Matchup map built: {len(matchup_map)} players mapped to opposing pitchers.")
        probable_starters = get_probable_starters(mlb_games)
        probable_starters_norm = {ev_calculator._normalize_name(s) for s in probable_starters}
        if probable_starters_norm:
            logger.info(f"Pitcher lineup filter active: {len(probable_starters_norm)} confirmed starters today.")
        else:
            logger.warning("No confirmed starters found yet — pitcher lineup filter disabled.")
    else:
        logger.warning("No MLB games found today — matchup data and pitcher lineup filter unavailable.")

    # Step 2: Fetch stats only after confirming there are events to process
    logger.info("Fetching global batter stats from Statcast...")
    batter_stats_df = ingestor.fetch_batter_stats()

    logger.info("Fetching global pitcher stats from Statcast...")
    pitcher_stats_df = ingestor.fetch_pitcher_stats()

    logger.info("Fetching team batting stats for opponent K% calculation...")
    team_batting_df = ingestor.fetch_team_batting_stats()
    if team_batting_df is None:
        logger.warning("Could not fetch team batting stats — opponent K% will fall back to league average.")

    if batter_stats_df is None:
        logger.error("Failed to fetch batter stats. Exiting pipeline.")
        return
    if pitcher_stats_df is None:
        logger.error("Failed to fetch pitcher stats. Exiting pipeline.")
        return

    # Bulk-fetch pitcher gamelogs for all pitchers with odds today
    pitcher_names_in_odds = set()
    for event in events:
        for bookmaker in event.get('bookmakers', []):
            for market in bookmaker['markets']:
                if market['key'].startswith('pitcher'):
                    for outcome in market['outcomes']:
                        pitcher_names_in_odds.add(outcome['name'])

    pitcher_gamelogs_cache = {}
    if pitcher_names_in_odds:
        logger.info(f"Fetching pitcher gamelogs for {len(pitcher_names_in_odds)} pitchers...")
        for pname in pitcher_names_in_odds:
            norm = ev_calculator._normalize_name(pname)
            df = db.get_pitcher_recent_starts(norm, n=10)
            if not df.empty:
                pitcher_gamelogs_cache[norm] = df
        logger.info(f"Pitcher gamelog cache loaded: {len(pitcher_gamelogs_cache)} pitchers with DB history.")

    # Bulk-fetch batter gamelogs for all batters with odds today
    batter_names_in_odds = set()
    for event in events:
        for bookmaker in event.get('bookmakers', []):
            for market in bookmaker['markets']:
                if market['key'].startswith('batter'):
                    for outcome in market['outcomes']:
                        batter_names_in_odds.add(outcome['name'])

    batter_gamelogs_cache = {}
    if batter_names_in_odds:
        logger.info(f"Fetching batter gamelogs for {len(batter_names_in_odds)} batters...")
        for bname in batter_names_in_odds:
            norm = ev_calculator._normalize_name(bname)
            df = db.get_batter_recent_games(norm, n=15)
            if not df.empty:
                batter_gamelogs_cache[norm] = df
        logger.info(f"Batter gamelog cache loaded: {len(batter_gamelogs_cache)} batters with DB history.")

    # Step 3: Archive all odds to mlb_odds_log before processing
    fetched_at = datetime.now(timezone.utc).isoformat()
    odds_archive = []
    supported_markets = [
        'batter_home_runs', 'batter_hits', 'batter_total_bases_1.5', 'batter_strikeouts',
        'pitcher_strikeouts', 'pitcher_outs', 'pitcher_hits_allowed', 'pitcher_walks_allowed'
    ]
    for event in events:
        if 'bookmakers' not in event:
            continue
        game_date      = event.get('commence_time', fetched_at)[:10]
        home_team      = event.get('home_team')
        away_team      = event.get('away_team')
        commence_time  = event.get('commence_time')
        for bookmaker in event['bookmakers']:
            for market in bookmaker['markets']:
                for outcome in market['outcomes']:
                    if abs(outcome['price']) <= 50000:
                        implied = round(ev_calculator.calculate_implied_prob(outcome['price']), 6)

                        # Compute model probability for supported markets
                        ml_market = market['key']
                        if ml_market == 'batter_total_bases':
                            ml_market = 'batter_total_bases_1.5'

                        model_prob = None
                        edge = None
                        if ml_market in supported_markets:
                            tp = ev_calculator.generate_true_prob(
                                ml_market, outcome['name'], batter_stats_df, pitcher_stats_df,
                                team_batting_df=team_batting_df,
                                home_team=home_team, away_team=away_team,
                                pitcher_gamelogs_cache=pitcher_gamelogs_cache,
                                batter_gamelogs_cache=batter_gamelogs_cache,
                            )
                            if tp is not None:
                                model_prob = round(tp, 6)
                                edge = round(tp - implied, 6)

                        # Look up opposing pitcher from matchup map
                        opp_pitcher = matchup_map.get(outcome['name'].lower())

                        odds_archive.append({
                            "event_id":      event['id'],
                            "game_date":     game_date,
                            "home_team":     home_team,
                            "away_team":     away_team,
                            "commence_time": commence_time,
                            "player_name":   outcome['name'],
                            "market":        market['key'],
                            "sportsbook":    bookmaker['key'],
                            "odds_american": int(outcome['price']),
                            "point":         outcome.get('point'),
                            "implied_prob":  implied,
                            "model_prob":    model_prob,
                            "edge":          edge,
                            "opposing_pitcher": opp_pitcher,
                            "fetched_at":    fetched_at,
                        })
    # Fetch previous snapshot BEFORE writing new one (to detect movements)
    today_str = datetime.now(timezone.utc).date().isoformat()
    previous_snapshot = db.get_latest_odds_snapshot(today_str)

    db.log_odds_batch(odds_archive)
    logger.info(f"Archived {len(odds_archive):,} odds snapshots to mlb_odds_log.")

    # Step 3.5: Detect and log line movements
    if previous_snapshot:
        movements = []
        MIN_PROB_SHIFT = 0.01  # ignore sub-1% noise
        for row in odds_archive:
            key = (row["player_name"], row["market"], row["sportsbook"])
            prev = previous_snapshot.get(key)
            if not prev:
                continue
            if prev["odds_american"] == row["odds_american"]:
                continue
            prob_shift = round(float(row["implied_prob"]) - float(prev["implied_prob"]), 4)
            if abs(prob_shift) < MIN_PROB_SHIFT:
                continue
            movements.append({
                "player_name":      row["player_name"],
                "market":           row["market"],
                "sportsbook":       row["sportsbook"],
                "game_date":        row["game_date"],
                "old_odds":         prev["odds_american"],
                "new_odds":         row["odds_american"],
                "old_implied_prob": float(prev["implied_prob"]),
                "new_implied_prob": float(row["implied_prob"]),
                "prob_shift":       prob_shift,
                "old_point":        prev.get("point"),
                "new_point":        row.get("point"),
            })
        db.log_line_movements_batch(movements)
        logger.info(f"Line movement detection: {len(movements)} movements logged.")

    # For every event (game)
    for event in events:
        if 'bookmakers' not in event:
            continue

        # Parse through the nested Odds API structure
        for bookmaker in event['bookmakers']:
            book_name = bookmaker['key']

            for market in bookmaker['markets']:
                market_name = market['key']  # e.g., batter_home_runs

                for outcome in market['outcomes']:
                    player_name = outcome['name']
                    odds_american = outcome['price']

                    # Sanity check: ignore obviously erroneous odds
                    if abs(odds_american) > 50000:
                        logger.warning(f"Skipping suspicious odds for {player_name}: {odds_american}")
                        continue

                    # Skip heavily juiced lines (-200 and beyond) and Kalshi extreme longshots (+9900)
                    if odds_american <= -200:
                        continue
                    if book_name == "kalshi" and odds_american >= 9900:
                        continue

                    # Calculate Implied Probability
                    implied_prob = ev_calculator.calculate_implied_prob(odds_american)

                    # Map Odds API market text to internal model names
                    ml_market = market_name
                    if market_name == 'batter_total_bases':
                        ml_market = 'batter_total_bases_1.5'

                    if ml_market not in supported_markets:
                        continue

                    # Skip pitcher alerts when player isn't a confirmed starter today.
                    # Only enforced when schedule fetch succeeded (probable_starters_norm non-empty).
                    if ml_market.startswith('pitcher_') and probable_starters_norm:
                        if ev_calculator._normalize_name(player_name) not in probable_starters_norm:
                            logger.debug(f"Skipping {player_name} ({ml_market}) — not a confirmed starter today.")
                            continue

                    true_prob = ev_calculator.generate_true_prob(
                        ml_market, player_name, batter_stats_df, pitcher_stats_df,
                        team_batting_df=team_batting_df,
                        home_team=event.get('home_team'),
                        away_team=event.get('away_team'),
                        pitcher_gamelogs_cache=pitcher_gamelogs_cache,
                        batter_gamelogs_cache=batter_gamelogs_cache,
                    )

                    # Skip if model couldn't find the player
                    if true_prob is None:
                        logger.debug(f"No model prediction for {player_name} in {ml_market} — player not in stats dataset.")
                        continue

                    # Check Edge
                    ev_result = ev_calculator.check_ev(true_prob, implied_prob)

                    if ev_result['is_ev']:
                        edge = ev_result['edge']
                        logger.info(f"+EV Found! {player_name} | {ml_market} | {odds_american} (Edge: {edge*100:.1f}%)")

                        # Anti-spam db check
                        if not db.is_spam(player_name, market_name, book_name):
                            success = notifier.send_mlb_alert(
                                player_name, market_name, book_name,
                                odds_american, implied_prob, true_prob, edge
                            )
                            if success:
                                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                                db.log_alert(player_name, market_name, book_name, str(odds_american), edge, point=outcome.get('point'), game_date=today)
                        else:
                            logger.info(f"Skipped: {player_name} already alerted in past 12 hrs.")


if __name__ == "__main__":
    main()
