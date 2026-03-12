import os
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

MARKET_DISPLAY = {
    'batter_home_runs':       'To Hit a Home Run',
    'batter_hits':            'To Record a Hit',
    'batter_total_bases_1.5': 'Total Bases Over 1.5',
    'batter_strikeouts':      'To Strike Out',
    'pitcher_strikeouts':     'Pitcher Strikeouts Over 4.5',
    'pitcher_outs':           'Pitcher Outs Over 15.5',
    'pitcher_hits_allowed':   'Pitcher Hits Allowed Over 4.5',
    'pitcher_walks_allowed':  'Pitcher Walks Over 1.5',
}


class DiscordNotifier:
    def __init__(self):
        self.webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
        if not self.webhook_url:
            raise ValueError("DISCORD_WEBHOOK_URL is missing in .env")

    def send_mlb_alert(self, player_name, market, sportsbook, odds, implied_prob, true_prob, edge):
        """Builds and sends the analytical Discord Embed for a +EV MLB bet."""

        odds_str = f"+{odds}" if odds > 0 else str(odds)
        implied_str = f"{implied_prob * 100:.1f}%"
        true_str = f"{true_prob * 100:.1f}%"
        edge_str = f"+{edge * 100:.1f}%"

        market_display = MARKET_DISPLAY.get(market, market.replace("_", " ").title())

        payload = {
            "embeds": [
                {
                    "title": "MLB +EV Alert Identified",
                    "color": 3447003,  # Blue
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "fields": [
                        {
                            "name": "Player & Market",
                            "value": f"{player_name} — {market_display}",
                            "inline": False
                        },
                        {
                            "name": "Sportsbook",
                            "value": sportsbook.title(),
                            "inline": True
                        },
                        {
                            "name": "Odds",
                            "value": f"{odds_str} ({implied_str} Implied)",
                            "inline": True
                        },
                        {
                            "name": "Model Analytics",
                            "value": f"**True Probability:** {true_str}\n**Calculated Edge:** {edge_str}",
                            "inline": False
                        }
                    ],
                    "footer": {
                        "text": "B.L.A.S.T. MLB Automation System"
                    }
                }
            ]
        }

        try:
            response = requests.post(self.webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            print(f"Successfully fired Discord Alert for {player_name}")
            return True
        except Exception as e:
            print(f"Failed to send Discord Webhook: {e}")
            return False
