"""
Diagnostic script — inspect raw Kalshi API response structure.
Run after setting KALSHI_API_KEY in .env.

Usage: python3 tools/test_kalshi_connection.py
"""

import json
import os
import sys
import requests
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

def get_headers():
    api_key = os.environ.get("KALSHI_API_KEY", "")
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Token {api_key}"
    return headers


def inspect_series(series_ticker: str):
    print(f"\n--- Series: {series_ticker} ---")
    try:
        resp = requests.get(
            f"{BASE_URL}/markets",
            headers=get_headers(),
            params={"series_ticker": series_ticker, "status": "open", "limit": 5},
            timeout=15,
        )
        print(f"  Status: {resp.status_code}")
        if resp.status_code != 200:
            print(f"  Response: {resp.text[:300]}")
            return

        data = resp.json()
        markets = data.get("markets", [])
        print(f"  Open markets: {data.get('cursor', 'N/A')} cursor, {len(markets)} returned")
        if markets:
            print("  First market:")
            print(json.dumps(markets[0], indent=4))
    except Exception as e:
        print(f"  Error: {e}")


def inspect_events():
    """Try fetching MLB events directly."""
    print("\n--- MLB Events ---")
    try:
        resp = requests.get(
            f"{BASE_URL}/events",
            headers=get_headers(),
            params={"series_ticker": "MLB", "status": "open", "limit": 5},
            timeout=15,
        )
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(json.dumps(data, indent=2)[:2000])
        else:
            print(resp.text[:500])
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    api_key = os.environ.get("KALSHI_API_KEY", "")
    print(f"KALSHI_API_KEY: {'set (' + api_key[:8] + '...)' if api_key else 'NOT SET'}")

    # Try fetching events first
    inspect_events()

    # Try known series tickers
    for series in ["MLBHR", "MLBK", "MLBHITS", "MLBTB", "MLBOUTS", "MLB"]:
        inspect_series(series)
