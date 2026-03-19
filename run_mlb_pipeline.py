import sys
import os
import logging
from datetime import datetime, timezone

sys.path.append(os.path.join(os.path.dirname(__file__), "tools"))

from api_client import DataIngestor
import ev_calculator
from db_client import DatabaseClient
from notifier import DiscordNotifier

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

# MLB regular season: April 1 – October 15
SEASON_START_MONTH, SEASON_START_DAY = 4, 1
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
        logger.info("Outside MLB regular season (Apr 1 – Oct 15). Pipeline exiting — spring training and off-season games are not supported.")
        logger.info("Set ALLOW_SPRING_TRAINING=true in .env to override for testing.")
        return

    validate_env()

    # Initialize Layer 3 Tools
    ingestor = DataIngestor()
    db = DatabaseClient()
    notifier = DiscordNotifier()

    # Step 1: Fetch live odds first — short-circuit if no events today
    logger.info("Fetching live odds from The Odds API...")
    events = ingestor.fetch_player_props_odds()
    if not events:
        logger.info("No events found. Exiting pipeline.")
        return

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

    # Step 3: Archive all odds to mlb_odds_log before processing
    fetched_at = datetime.now(timezone.utc).isoformat()
    odds_archive = []
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
                            "implied_prob":  round(ev_calculator.calculate_implied_prob(outcome['price']), 6),
                            "fetched_at":    fetched_at,
                        })
    db.log_odds_batch(odds_archive)
    logger.info(f"Archived {len(odds_archive):,} odds snapshots to mlb_odds_log.")

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

                    # Calculate Implied Probability
                    implied_prob = ev_calculator.calculate_implied_prob(odds_american)

                    # Map Odds API market text to internal model names
                    ml_market = market_name
                    if market_name == 'batter_total_bases':
                        ml_market = 'batter_total_bases_1.5'

                    supported_markets = [
                        'batter_home_runs', 'batter_hits', 'batter_total_bases_1.5', 'batter_strikeouts',
                        'pitcher_strikeouts', 'pitcher_outs', 'pitcher_hits_allowed', 'pitcher_walks_allowed'
                    ]

                    if ml_market not in supported_markets:
                        continue

                    true_prob = ev_calculator.generate_true_prob(
                        ml_market, player_name, batter_stats_df, pitcher_stats_df,
                        team_batting_df=team_batting_df,
                        home_team=event.get('home_team'),
                        away_team=event.get('away_team'),
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
                                db.log_alert(player_name, market_name, book_name, str(odds_american), edge)
                        else:
                            logger.info(f"Skipped: {player_name} already alerted in past 12 hrs.")


if __name__ == "__main__":
    main()
