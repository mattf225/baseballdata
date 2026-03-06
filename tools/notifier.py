import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

class DiscordNotifier:
    def __init__(self):
        self.webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
        if not self.webhook_url:
            raise ValueError("DISCORD_WEBHOOK_URL is missing in .env")

    def send_mlb_alert(self, player_name, market, sportsbook, odds, implied_prob, true_prob, edge):
        """Builds and sends the analytical Discord Embed for a +EV MLB bet."""
        
        # Format the numbers for the display
        odds_str = f"+{odds}" if odds > 0 else str(odds)
        implied_str = f"{implied_prob * 100:.1f}%"
        true_str = f"{true_prob * 100:.1f}%"
        edge_str = f"+{edge * 100:.1f}%"
        
        # Clean up market name for display
        market_display = market.replace("_", " ").title()

        payload = {
            "embeds": [
                {
                    "title": "🚨 MLB +EV Alert Identified",
                    "color": 3447003, # Blue
                    "fields": [
                        {
                            "name": "Player & Market",
                            "value": f"{player_name} - {market_display}",
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
            response = requests.post(
                self.webhook_url, 
                data=json.dumps(payload), 
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            print(f"📡 Successfully fired Discord Alert for {player_name}")
            return True
        except Exception as e:
            print(f"❌ Failed to send Discord Webhook: {e}")
            return False
