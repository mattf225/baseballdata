"""
Diagnostic script — inspect raw Bovada API response structure.
Run this to verify the parser is reading fields correctly before using in prod.

Usage: python3 tools/test_bovada_connection.py
"""

import json
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from bovada_client import _get_raw_events, fetch_bovada_props


def inspect_raw():
    print("=== RAW BOVADA STRUCTURE ===\n")
    events = _get_raw_events()

    if not events:
        print("No events returned. Check connectivity or headers.")
        return

    print(f"Total raw events: {len(events)}\n")

    # Print first event in full to understand structure
    print("--- First event (full JSON) ---")
    print(json.dumps(events[0], indent=2))

    # Print all unique market descriptions across all events
    print("\n--- All unique market descriptions ---")
    market_descs = set()
    for ev in events:
        for group in ev.get("displayGroups", []):
            for market in group.get("markets", []):
                market_descs.add(f"[{group.get('description')}] {market.get('description')}")
    for d in sorted(market_descs):
        print(f"  {d}")


def inspect_parsed():
    print("\n=== PARSED BOVADA PROPS ===\n")
    events = fetch_bovada_props()

    if not events:
        print("No prop events parsed. Check market name mapping in bovada_client.py.")
        return

    for ev in events:
        print(f"{ev['away_team']} @ {ev['home_team']}")
        for bm in ev["bookmakers"]:
            for market in bm["markets"]:
                print(f"  [{market['key']}]")
                for o in market["outcomes"][:3]:  # show first 3 outcomes per market
                    print(f"    {o['name']}: {o['price']} (line: {o['point']})")
        print()


if __name__ == "__main__":
    inspect_raw()
    inspect_parsed()
