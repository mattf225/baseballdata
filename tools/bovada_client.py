"""
Bovada odds fetcher.
Uses Bovada's undocumented public JSON API — no auth required.
Returns events in the same format as DataIngestor.fetch_player_props_odds()
so the pipeline can merge them without modification.

Bovada market structure (confirmed from live API):
  displayGroup: "Pitcher Props" or "Player Props"
  market description: "{Stat Type} - {Player Name} ({Team})"
    e.g. "Total Strikeouts - Logan Webb (SF)"
  outcomes: [{"description": "Over", "price": {"american": "-115", "handicap": "5.5"}}, ...]
  outcome status: "O" = open (string, not object)
"""

import re
import requests
from datetime import datetime, timezone

_BASE_URL = "https://www.bovada.lv/services/sports/event/v2/events/A/description/baseball/mlb"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bovada.lv/sports/baseball/mlb",
    "Accept": "application/json, text/plain, */*",
}

# Bovada prop display groups (lowercased)
_PROP_GROUPS = {"pitcher props", "player props"}

# Bovada stat type (lowercased, before " - Player Name") → internal pipeline market key
_STAT_TYPE_MAP = {
    # Pitcher props
    "total strikeouts":   "pitcher_strikeouts",
    "total pitcher outs": "pitcher_outs",
    "total hits allowed": "pitcher_hits_allowed",
    "total walks allowed": "pitcher_walks_allowed",
    # Batter props
    "total bases":        "batter_total_bases",
    "hits":               "batter_hits",
    "home runs":          "batter_home_runs",
    "strikeouts":         "batter_strikeouts",
}

# Market description pattern: "Total Strikeouts - Logan Webb (SF)"
# Group 1: stat type, Group 2: player name, Group 3: team abbrev
_MARKET_RE = re.compile(r'^(.+?)\s+-\s+(.+?)\s+\(([A-Z0-9]+)\)$')


def _parse_market_desc(description: str):
    """
    Parses a Bovada market description into (internal_key, player_name).
    Returns (None, None) if not a recognized player prop format.
    """
    m = _MARKET_RE.match(description.strip())
    if not m:
        return None, None
    stat_type = m.group(1).strip().lower()
    player_name = m.group(2).strip()
    internal_key = _STAT_TYPE_MAP.get(stat_type)
    return internal_key, player_name


def _parse_american_odds(price_str):
    try:
        val = int(str(price_str).replace("+", ""))
        return val if abs(val) <= 50000 else None
    except (ValueError, TypeError):
        return None


def _parse_point(handicap):
    try:
        return float(handicap) if handicap is not None else None
    except (ValueError, TypeError):
        return None


def _get_raw_events() -> list:
    """Fetches raw event list from Bovada. Returns empty list on error."""
    try:
        resp = requests.get(_BASE_URL, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        raw = resp.json()
    except Exception as e:
        print(f"Bovada: fetch failed: {e}")
        return []

    # Bovada wraps events in coupling objects: [{"events": [...]}, ...]
    event_list = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and "events" in item:
                event_list.extend(item["events"])
            elif isinstance(item, dict) and "id" in item:
                event_list.append(item)
    return event_list


def fetch_bovada_props() -> list:
    """
    Fetches MLB player prop odds from Bovada's public API.
    Returns a list of events in the same format as DataIngestor.fetch_player_props_odds().
    Only includes "Over" outcomes — our models predict P(over threshold).
    Returns empty list on any error or if no props are found.
    """
    event_list = _get_raw_events()
    if not event_list:
        return []

    events_out = []
    for ev in event_list:
        competitors = ev.get("competitors", [])
        home_team = next((c["name"] for c in competitors if c.get("home")), None)
        away_team = next((c["name"] for c in competitors if not c.get("home")), None)
        if not home_team or not away_team:
            continue

        start_ms = ev.get("startTime", 0)
        commence_time = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).isoformat()

        # Collect markets grouped by (internal_key, player_name)
        # Each Bovada market = one player + one stat type, outcomes = Over/Under
        prop_markets = []
        for group in ev.get("displayGroups", []):
            if group.get("description", "").lower() not in _PROP_GROUPS:
                continue

            for market in group.get("markets", []):
                internal_key, player_name = _parse_market_desc(market.get("description", ""))
                if not internal_key or not player_name:
                    continue

                # Only process "Over" outcomes — our models output P(over)
                for outcome in market.get("outcomes", []):
                    if outcome.get("status") != "O":
                        continue
                    if outcome.get("description", "").lower() != "over":
                        continue

                    price = outcome.get("price", {})
                    american = _parse_american_odds(price.get("american"))
                    if american is None:
                        continue

                    prop_markets.append({
                        "key": internal_key,
                        "outcomes": [{
                            "name":  player_name,
                            "price": american,
                            "point": _parse_point(price.get("handicap")),
                        }],
                    })

        if prop_markets:
            events_out.append({
                "id":            f"bovada_{ev.get('id', '')}",
                "home_team":     home_team,
                "away_team":     away_team,
                "commence_time": commence_time,
                "bookmakers": [{
                    "key":     "bovada",
                    "title":   "Bovada",
                    "markets": prop_markets,
                }],
            })

    print(f"Bovada: {len(events_out)} events with player props.")
    return events_out
