import os
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

class DatabaseClient:
    def __init__(self):
        url = os.environ.get("SUPABASE_URL")
        # Use service role key for write access; anon key is read-only
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            raise ValueError("SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY missing in .env")
        self.supabase: Client = create_client(url, key)

    def log_alert(self, player_name, market, sportsbook, odds_formatted, edge):
        """Logs a sent alert to the mlb_alert_log table."""
        data = {
            "player_name": player_name,
            "market": market,
            "sportsbook": sportsbook,
            "odds_formatted": odds_formatted,
            "calculated_edge_percentage": float(edge)
        }
        try:
            self.supabase.table("mlb_alert_log").insert(data).execute()
        except Exception as e:
            raise Exception(f"Failed to log alert to Supabase: {e}")

    def is_spam(self, player_name, market, sportsbook) -> bool:
        """
        Checks if an identical alert (player + market + sportsbook) was sent
        within the last 12 hours. Uses a server-side time filter for accuracy.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
        try:
            response = (
                self.supabase.table("mlb_alert_log")
                .select("sent_at", count="exact")
                .eq("player_name", player_name)
                .eq("market", market)
                .eq("sportsbook", sportsbook)
                .gte("sent_at", cutoff)
                .limit(1)
                .execute()
            )
            return bool(response.data)
        except Exception as e:
            raise Exception(f"Failed to check spam log: {e}")
