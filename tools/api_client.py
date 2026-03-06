import os
import requests
import pybaseball
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

class DataIngestor:
    def __init__(self):
        # Optional: enable cache to speed up pybaseball requests during testing
        pybaseball.cache.enable()
        
    def fetch_player_props_odds(self):
        """Fetches live MLB player prop odds from The Odds API."""
        if not ODDS_API_KEY:
             raise ValueError("ODDS_API_KEY is not set.")
             
        # Step 1: Get today's MLB events
        events_url = f"https://api.the-odds-api.com/v4/sports/baseball_mlb/events?apiKey={ODDS_API_KEY}"
        events_response = requests.get(events_url)
        events_response.raise_for_status()
        events = events_response.json()
        
        all_odds = []
        # Step 2: Fetch Player Props for each event
        for event in events:
             event_id = event['id']
             # Markets: batter_home_runs, pitcher_strikeouts
             odds_url = f"https://api.the-odds-api.com/v4/sports/baseball_mlb/events/{event_id}/odds?apiKey={ODDS_API_KEY}&regions=us&markets=batter_home_runs,pitcher_strikeouts&oddsFormat=american"
             odds_res = requests.get(odds_url)
             if odds_res.status_code == 200:
                  event_odds = odds_res.json()
                  all_odds.append(event_odds)
             else:
                  print(f"Failed to fetch odds for event {event_id}: {odds_res.status_code}")
                  continue
                  
        return all_odds

    def fetch_batter_stats(self, year=None):
        """Fetches aggregate batter exit velocity and barrel data from Statcast."""
        if not year:
            year = 2024 # Hardcode 2024 for prototype testing as current year might be empty in offseason
            
        try:
             # Fetch batting stats (requires at least min qualification)
             stats = pybaseball.batting_stats(year)
             return stats
        except Exception as e:
             print(f"Error fetching pybaseball batting stats: {e}")
             return None

    def fetch_pitcher_stats(self, year=None):
         """Fetches aggregate pitcher strikeout data from Statcast."""
         if not year:
             year = 2024 # Hardcode 2024 for prototype testing as current year might be empty in offseason
             
         try:
              stats = pybaseball.pitching_stats(year)
              return stats
         except Exception as e:
              print(f"Error fetching pybaseball pitching stats: {e}")
              return None
