import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

def test_notification():
    if not DISCORD_WEBHOOK_URL:
        print("❌ Error: DISCORD_WEBHOOK_URL must be set in .env")
        return False

    print("Testing Discord Webhook Connection...")

    payload = {
        "content": "🚀 **B.L.A.S.T. System Notification Test**\n\n✅ If you are seeing this, the Data Golf +EV webhook routing is successful!"
    }

    try:
        response = requests.post(
            DISCORD_WEBHOOK_URL, 
            data=json.dumps(payload), 
            headers={"Content-Type": "application/json"}
        )
        if response.status_code == 204 or response.status_code == 200:
            print("✅ Webhook Connection Server-Side Successful!")
            return True
        else:
            print(f"❌ Webhook failed with status code {response.status_code}: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Webhook request failed: {e}")
        return False

if __name__ == "__main__":
    test_notification()
