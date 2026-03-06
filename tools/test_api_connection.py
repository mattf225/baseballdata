import os
import requests
from dotenv import load_dotenv

load_dotenv()

ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

def test_mlb_api_connections():
    print("Testing MLB API Connections...")
    
    # ----------------------------------------------------
    # TEST 1: pybaseball (Statcast Data)
    # ----------------------------------------------------
    print("\n--- Testing pybaseball (Statcast) ---")
    try:
        from pybaseball import statcast
        # Fetching a single day's worth of data as a light test
        # We wrap in try-except because occasionally pybaseball throws a non-fatal warning
        data = statcast(start_dt="2024-05-01", end_dt="2024-05-01")
        if not data.empty:
            print(f"✅ pybaseball Connection Successful! (Fetched {len(data)} pitches)")
        else:
            print("⚠️ pybaseball returned an empty dataframe for 2024-05-01. Check season dates.")
    except Exception as e:
        print(f"❌ pybaseball connection failed: {e}")

    # ----------------------------------------------------
    # TEST 2: The Odds API (MLB Props)
    # ----------------------------------------------------
    print("\n--- Testing The Odds API ---")
    if not ODDS_API_KEY:
        print("❌ Error: ODDS_API_KEY must be set in .env")
    else:
        # We test the active events endpoint for MLB
        url_odds = f"https://api.the-odds-api.com/v4/sports/baseball_mlb/odds/?apiKey={ODDS_API_KEY}&regions=us&markets=h2h&oddsFormat=american"
        try:
            response_odds = requests.get(url_odds)
            if response_odds.status_code == 200:
                data = response_odds.json()
                print(f"✅ The Odds API Connection Successful! (Found {len(data)} upcoming MLB events)")
            elif response_odds.status_code == 401:
                 print("❌ Authentication failed for The Odds API. Check your ODDS_API_KEY.")
            else:
                print(f"❌ Odds API failed with status code {response_odds.status_code}: {response_odds.text}")
        except Exception as e:
            print(f"❌ Odds API request failed: {e}")

if __name__ == "__main__":
    test_mlb_api_connections()
