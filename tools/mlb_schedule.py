"""
MLB Schedule & Lineup Lookup
-----------------------------
Uses the free MLB Stats API (statsapi.mlb.com) to fetch:
- Today's schedule with probable starting pitchers
- Player-to-team and player-to-opposing-pitcher mapping via rosters

No API key required.
"""

import statsapi
from datetime import datetime


# Fetch team ID → abbreviation once
_TEAM_ABBREVS = {}


def _get_team_abbrevs() -> dict:
    """Returns {team_id: abbreviation} for all MLB teams. Cached after first call."""
    global _TEAM_ABBREVS
    if _TEAM_ABBREVS:
        return _TEAM_ABBREVS
    try:
        data = statsapi.get("teams", {"sportIds": 1})
        _TEAM_ABBREVS = {t["id"]: t["abbreviation"] for t in data.get("teams", [])}
    except Exception as e:
        print(f"Warning: failed to fetch MLB teams: {e}")
    return _TEAM_ABBREVS


def get_todays_games(game_date: str = None) -> list:
    """
    Returns today's MLB games with probable pitchers and team IDs.
    Accepts game_date as YYYY-MM-DD or defaults to today.
    """
    if game_date is None:
        fmt_date = datetime.now().strftime("%m/%d/%Y")
    else:
        dt = datetime.strptime(game_date, "%Y-%m-%d")
        fmt_date = dt.strftime("%m/%d/%Y")

    try:
        schedule = statsapi.schedule(date=fmt_date)
    except Exception as e:
        print(f"Warning: MLB schedule fetch failed: {e}")
        return []

    abbrevs = _get_team_abbrevs()

    games = []
    for g in schedule:
        games.append({
            "game_id": g.get("game_id"),
            "home_team": g.get("home_name"),
            "away_team": g.get("away_name"),
            "home_id": g.get("home_id"),
            "away_id": g.get("away_id"),
            "home_abbrev": abbrevs.get(g.get("home_id"), ""),
            "away_abbrev": abbrevs.get(g.get("away_id"), ""),
            "home_pitcher": g.get("home_probable_pitcher", "TBD") or "TBD",
            "away_pitcher": g.get("away_probable_pitcher", "TBD") or "TBD",
            "game_date": g.get("game_date"),
            "status": g.get("status"),
        })
    return games


def get_probable_starters(games: list) -> set:
    """
    Returns a set of probable starting pitcher names (lowercase) for today's games.
    Excludes 'TBD' entries. Returns empty set if no games or all pitchers are TBD.
    """
    starters = set()
    for game in games:
        for key in ("home_pitcher", "away_pitcher"):
            name = game.get(key, "TBD")
            if name and name != "TBD":
                starters.add(name.lower())
    return starters


def build_matchup_map(games: list) -> dict:
    """
    Builds a mapping of player_name (lowercase) → opposing pitcher name.

    Uses probable pitchers + active rosters from today's games.
    Home team batters face the away_pitcher; away team batters face the home_pitcher.
    Pitchers map to the opposing starter.

    Returns dict like {"aaron judge": "Logan Webb", "logan webb": "Max Fried"}.
    """
    matchup_map = {}

    for game in games:
        hp = game["home_pitcher"]
        ap = game["away_pitcher"]

        # Pitchers face each other
        if hp != "TBD":
            matchup_map[hp.lower()] = ap
        if ap != "TBD":
            matchup_map[ap.lower()] = hp

        # Fetch active rosters for both teams
        for team_id, opp_pitcher in [
            (game["home_id"], ap),   # home batters face away pitcher
            (game["away_id"], hp),   # away batters face home pitcher
        ]:
            if not team_id:
                continue
            try:
                roster_data = statsapi.get("team_roster", {"teamId": team_id, "rosterType": "active"})
                for p in roster_data.get("roster", []):
                    name = p.get("person", {}).get("fullName", "")
                    if name:
                        matchup_map[name.lower()] = opp_pitcher
            except Exception:
                continue

    return matchup_map


if __name__ == "__main__":
    print("Fetching today's MLB schedule...")
    games = get_todays_games()
    if not games:
        print("No games found today.")
    else:
        for g in games:
            print(f"  {g['away_team']} ({g['away_abbrev']}) @ {g['home_team']} ({g['home_abbrev']})")
            print(f"    {g['away_pitcher']} vs {g['home_pitcher']}")

        print("\nBuilding matchup map...")
        matchup_map = build_matchup_map(games)
        print(f"  {len(matchup_map)} players mapped.")
        for name, opp in list(matchup_map.items())[:10]:
            print(f"  {name} → vs {opp}")
