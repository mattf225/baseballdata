import os
import requests
import pybaseball
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

# Enable pybaseball cache once at module level (global config, not per-instance)
pybaseball.cache.enable()

PROP_MARKETS = (
    "batter_home_runs,batter_hits,batter_total_bases,batter_strikeouts,"
    "pitcher_strikeouts,pitcher_outs,pitcher_hits_allowed,pitcher_walks_allowed"
)

def _current_season_year():
    """Returns the active season year: current year Apr–Oct, prior year otherwise."""
    now = datetime.now()
    return now.year if 4 <= now.month <= 10 else now.year - 1

def _is_regular_season_date(commence_time_str: str) -> bool:
    """
    Returns True only if a game's commence_time falls within the MLB regular
    season window (April 1 – October 15).  Filters out spring training (Feb–Mar)
    and postseason outliers we don't have models for.
    """
    try:
        dt = datetime.fromisoformat(commence_time_str.replace("Z", "+00:00"))
        return (dt.month == 4 and dt.day >= 1) or (5 <= dt.month <= 9) or (dt.month == 10 and dt.day <= 15)
    except Exception:
        return True  # allow through if we can't parse the date


class DataIngestor:
    def fetch_player_props_odds(self):
        """Fetches live MLB player prop odds from The Odds API."""
        if not ODDS_API_KEY:
            raise ValueError("ODDS_API_KEY is not set.")

        # Step 1: Get today's MLB events
        events_response = requests.get(
            "https://api.the-odds-api.com/v4/sports/baseball_mlb/events",
            params={"apiKey": ODDS_API_KEY},
            timeout=10
        )
        events_response.raise_for_status()
        events = events_response.json()

        if not events:
            return []

        # Filter out spring training unless explicitly overridden for testing
        if not os.environ.get("ALLOW_SPRING_TRAINING"):
            events = [e for e in events if _is_regular_season_date(e.get("commence_time", ""))]
            if not events:
                print("No regular-season events found (spring training or off-season games filtered out).")
                return []

        all_odds = []
        # Step 2: Fetch Player Props for each event
        for event in events:
            event_id = event['id']
            odds_res = requests.get(
                f"https://api.the-odds-api.com/v4/sports/baseball_mlb/events/{event_id}/odds",
                params={
                    "apiKey": ODDS_API_KEY,
                    "regions": "us",
                    "markets": PROP_MARKETS,
                    "oddsFormat": "american"
                },
                timeout=10
            )
            if odds_res.status_code == 200:
                all_odds.append(odds_res.json())
            else:
                print(f"Failed to fetch odds for event {event_id}: {odds_res.status_code}")

        return all_odds

    def fetch_batter_stats(self, year=None):
        """Fetches aggregate batter exit velocity and barrel data from Statcast."""
        if year is None:
            year = _current_season_year()

        try:
            return pybaseball.batting_stats(year)
        except Exception as e:
            print(f"Error fetching pybaseball batting stats: {e}")
            return None

    def fetch_pitcher_stats(self, year=None):
        """Fetches aggregate pitcher strikeout data from Statcast."""
        if year is None:
            year = _current_season_year()

        try:
            return pybaseball.pitching_stats(year)
        except Exception as e:
            print(f"Error fetching pybaseball pitching stats: {e}")
            return None
