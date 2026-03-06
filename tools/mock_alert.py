import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__)))

from notifier import DiscordNotifier

def send_demo_alert():
    print("Sending demo +EV alert to Discord...")
    notifier = DiscordNotifier()
    
    # Dummy data for the demonstration
    player_name = "Aaron Judge"
    market_name = "batter_home_runs"
    book_name = "draftkings"
    odds_american = 250
    implied_prob = 0.285  # 28.5%
    true_prob = 0.330     # 33.0%
    edge = 0.045          # 4.5% edge
    
    success = notifier.send_mlb_alert(
        player_name, market_name, book_name, 
        odds_american, implied_prob, true_prob, edge
    )
    
    if success:
        print("✅ Demo alert sent successfully. Please check your Discord channel!")

if __name__ == "__main__":
    send_demo_alert()
