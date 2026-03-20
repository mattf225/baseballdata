import os
from datetime import datetime, timezone, timedelta
import pandas as pd
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

    def log_odds_batch(self, rows: list) -> None:
        """
        Bulk-inserts a batch of live odds snapshots into mlb_odds_log.
        Each row dict must have: event_id, game_date, player_name, market,
        sportsbook, odds_american, implied_prob, fetched_at.
        Silently skips on error so odds archiving never blocks the main pipeline.
        """
        if not rows:
            return
        try:
            # Insert in chunks of 500 to stay within Supabase request limits
            for i in range(0, len(rows), 500):
                self.supabase.table("mlb_odds_log").insert(rows[i:i + 500]).execute()
        except Exception as e:
            print(f"Warning: failed to archive odds snapshot: {e}")

    def upsert_pitcher_gamelogs(self, rows: list) -> None:
        """
        Bulk-upserts pitcher gamelogs into pitcher_gamelogs table.
        Inserts in chunks of 500. On conflict (pitcher_name, game_date), updates.
        Silently skips on error so gamelog archiving never blocks the main pipeline.
        """
        if not rows:
            return
        try:
            for i in range(0, len(rows), 500):
                self.supabase.table("pitcher_gamelogs").upsert(
                    rows[i:i + 500], on_conflict="pitcher_name,game_date"
                ).execute()
        except Exception as e:
            print(f"Warning: failed to upsert pitcher gamelogs: {e}")

    def get_pitcher_recent_starts(self, pitcher_name: str, n: int = 10) -> pd.DataFrame:
        """
        Returns the last n starts for a pitcher as a DataFrame.
        Columns: game_date, BF, SO, BBA, HA, Outs, K_pct, opp_k_pct
        Returns empty DataFrame on error or if pitcher not found (never None).
        """
        try:
            response = (
                self.supabase.table("pitcher_gamelogs")
                .select("game_date, BF, SO, BBA, HA, Outs, K_pct, opp_k_pct")
                .eq("pitcher_name", pitcher_name)
                .order("game_date", desc=True)
                .limit(n)
                .execute()
            )
            if response.data:
                return pd.DataFrame(response.data)
            return pd.DataFrame()
        except Exception as e:
            print(f"Warning: failed to fetch pitcher gamelogs for {pitcher_name}: {e}")
            return pd.DataFrame()

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
