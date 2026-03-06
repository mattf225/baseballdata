import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "tools"))

from api_client import DataIngestor
import ev_calculator
from db_client import DatabaseClient
from notifier import DiscordNotifier

def main():
    print("🚀 Initializing B.L.A.S.T. MLB Pipeline...")
    
    # Initialize Layer 3 Tools
    ingestor = DataIngestor()
    db = DatabaseClient()
    notifier = DiscordNotifier()

    print("Fetching global batter stats from Statcast...")
    # Fetching the whole dataframe locally for fast in-memory heuristic lookups
    batter_stats_df = ingestor.fetch_batter_stats()

    print("Fetching live odds from The Odds API...")
    events = ingestor.fetch_player_props_odds()
    
    # For every event (game)
    for event in events:
         if 'bookmakers' not in event:
              continue
              
         # Parse through the nested Odds API structure
         for bookmaker in event['bookmakers']:
              book_name = bookmaker['key']
              
              for market in bookmaker['markets']:
                   market_name = market['key'] # e.g., batter_home_runs
                   
                   for outcome in market['outcomes']:
                        player_name = outcome['name']
                        odds_american = outcome['price']
                        
                        # Calculate Implied Probability
                        implied_prob = ev_calculator.calculate_implied_prob(odds_american)
                        
                        # Generate True Probability based on the ML Model
                        # Our ML model supports: batter_home_runs, batter_hits, batter_total_bases_1.5, batter_strikeouts
                        
                        # We map the Odds API market text to our internal model names
                        ml_market = market_name
                        if market_name == 'batter_total_bases': ml_market = 'batter_total_bases_1.5'
                        
                        # Only run if we actually trained a model for this
                        if ml_market in ['batter_home_runs', 'batter_hits', 'batter_total_bases_1.5', 'batter_strikeouts']:
                             true_prob = ev_calculator.generate_true_prob(ml_market, player_name, batter_stats_df, None)
                             
                             # Check Edge
                             ev_result = ev_calculator.check_ev(true_prob, implied_prob)
                             
                             if ev_result['is_ev']:
                                  edge = ev_result['edge']
                                  print(f"🎯 +EV Found! {player_name} HR at {odds_american} (Edge: {edge*100:.1f}%)")
                                  
                                  # Anti-spam db check
                                  if not db.is_spam(player_name, market_name, book_name):
                                       # Fire webhook
                                       success = notifier.send_mlb_alert(
                                           player_name, market_name, book_name, 
                                           odds_american, implied_prob, true_prob, edge
                                       )
                                       if success:
                                            # Log to Supabase
                                            db.log_alert(player_name, market_name, book_name, str(odds_american), edge)
                                  else:
                                       print(f"  ↪️ Skipped: {player_name} already alerted in past 12 hrs.")


if __name__ == "__main__":
    main()
