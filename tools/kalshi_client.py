"""
Kalshi odds fetcher.
Kalshi is a regulated prediction market exchange.

API base: https://api.elections.kalshi.com/trade-api/v2
Auth: Authorization: Token {KALSHI_API_KEY}

Confirmed market structure (from live API inspection):
  - series_ticker: KXMLBHR, KXMLBKS, KXMLBHIT, KXMLBTB, etc.
  - title: "Casey Schmitt: 3+ hits?" — player name before colon
  - floor_strike: numeric threshold (e.g. 0.5 = 1+ HR, 4.5 = 5+ Ks)
  - yes_ask_dollars: string dollar price (e.g. "0.15" = 15% implied prob)
  - status: "active" for open markets

We only process markets whose floor_strike matches the threshold our models
were trained on, so implied prob vs true prob are apples-to-apples.
We convert yes_ask_dollars to American odds so the rest of the pipeline is unchanged.
"""

import os
import re
import requests
from collections import defaultdict
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

# Confirmed Kalshi series tickers → internal pipeline market key
_SERIES_MAP = {
    "KXMLBHR":  "batter_home_runs",
    "KXMLBHIT": "batter_hits",
    "KXMLBTB":  "batter_total_bases",
    "KXMLBKS":  "pitcher_strikeouts",
}

# Only process Kalshi markets whose floor_strike matches our model's training threshold.
# Models predict P(stat >= threshold + 0.5), e.g. floor_strike=4.5 → P(SO >= 5).
_MODEL_THRESHOLDS = {
    "batter_home_runs":      0.5,   # Target_HR = HR >= 1
    "batter_hits":           0.5,   # Target_Hit = H >= 1
    "batter_total_bases":    1.5,   # Target_TB_Over_1_5 = TB >= 2
    "pitcher_strikeouts":    4.5,   # Target_SO_Over_4_5 = SO >= 5
}


def _get_headers() -> dict:
    api_key = os.environ.get("KALSHI_API_KEY", "")
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Token {api_key}"
    return headers


def _yes_ask_to_american(yes_ask_dollars: str) -> int:
    """
    Converts a Kalshi yes_ask_dollars price (e.g. "0.15") to American odds.
    0.15 → implied prob 15% → American +567
    0.60 → implied prob 60% → American -150
    """
    prob = max(0.01, min(0.99, float(yes_ask_dollars)))
    if prob < 0.5:
        return round((1 / prob - 1) * 100)
    else:
        return round(-(prob / (1 - prob)) * 100)


def _extract_player_name(title: str) -> str:
    """
    Parses player name from Kalshi market title.
    Format: "Casey Schmitt: 3+ hits?" → "Casey Schmitt"
    """
    if ":" in title:
        return title.split(":")[0].strip()
    return ""


def _fetch_series(series_ticker: str) -> list:
    """Fetches all active markets for a Kalshi series. Returns empty list on error."""
    markets = []
    cursor = ""
    while True:
        try:
            params = {"series_ticker": series_ticker, "status": "open", "limit": 200}
            if cursor:
                params["cursor"] = cursor
            resp = requests.get(
                f"{_BASE_URL}/markets",
                headers=_get_headers(),
                params=params,
                timeout=15,
            )
            if resp.status_code in (404, 401):
                break
            resp.raise_for_status()
            data = resp.json()
            markets.extend(data.get("markets", []))
            cursor = data.get("cursor", "")
            if not cursor:
                break
        except Exception as e:
            print(f"Kalshi: failed to fetch {series_ticker}: {e}")
            break
    return markets


def fetch_kalshi_props() -> list:
    """
    Fetches MLB player prop markets from Kalshi.
    Returns events in the same format as fetch_bovada_props().
    Only includes markets whose floor_strike matches our model's training threshold.
    Returns empty list if API key is missing or no matching markets found.
    """
    if not os.environ.get("KALSHI_API_KEY"):
        print("Kalshi: KALSHI_API_KEY not set — skipping.")
        return []

    # Fetch all markets across known MLB series
    all_markets = []
    for series_ticker, internal_key in _SERIES_MAP.items():
        markets = _fetch_series(series_ticker)
        for m in markets:
            m["_internal_key"] = internal_key
        all_markets.extend(markets)

    if not all_markets:
        print("Kalshi: no open MLB markets found.")
        return []

    # Filter to only markets matching our model thresholds
    matching = []
    for m in all_markets:
        key = m.get("_internal_key")
        threshold = _MODEL_THRESHOLDS.get(key)
        floor_strike = m.get("floor_strike")
        if threshold is not None and floor_strike is not None:
            if abs(float(floor_strike) - threshold) < 0.01:
                matching.append(m)

    if not matching:
        print("Kalshi: no markets matching model thresholds found.")
        return []

    # Group by event_ticker → one event per game
    events_by_ticker = defaultdict(list)
    for market in matching:
        events_by_ticker[market.get("event_ticker", "unknown")].append(market)

    events_out = []
    for event_ticker, markets in events_by_ticker.items():
        prop_markets = []
        for market in markets:
            yes_ask = market.get("yes_ask_dollars")
            if not yes_ask:
                continue
            if market.get("status") != "active":
                continue

            player_name = _extract_player_name(market.get("title", ""))
            if not player_name:
                continue

            try:
                american = _yes_ask_to_american(yes_ask)
            except (ValueError, TypeError):
                continue

            prop_markets.append({
                "key": market["_internal_key"],
                "outcomes": [{
                    "name":  player_name,
                    "price": american,
                    "point": float(market.get("floor_strike", 0)),
                }],
            })

        if prop_markets:
            # Use expected_expiration_time as game start proxy
            game_time = markets[0].get("expected_expiration_time",
                                       datetime.now(timezone.utc).isoformat())
            events_out.append({
                "id":            f"kalshi_{event_ticker}",
                "home_team":     "",  # Kalshi doesn't expose teams — opp K% falls back to league avg
                "away_team":     "",
                "commence_time": game_time,
                "bookmakers": [{
                    "key":     "kalshi",
                    "title":   "Kalshi",
                    "markets": prop_markets,
                }],
            })

    print(f"Kalshi: {len(events_out)} events with player props.")
    return events_out
