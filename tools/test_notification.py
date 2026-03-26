import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
DISCORD_WEBHOOK_URL_KALSHI = os.environ.get("DISCORD_WEBHOOK_URL_KALSHI")


def _send_test(url, label):
    payload = {
        "content": f"**B.L.A.S.T. System Notification Test — {label}**\n\nIf you are seeing this, the {label} webhook routing is successful!"
    }
    try:
        response = requests.post(
            url,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        if response.status_code in (200, 204):
            print(f"  {label}: Webhook successful!")
            return True
        else:
            print(f"  {label}: Webhook failed with status {response.status_code}: {response.text}")
            return False
    except Exception as e:
        print(f"  {label}: Webhook request failed: {e}")
        return False


def test_notification():
    print("Testing Discord Webhook Connections...\n")

    if not DISCORD_WEBHOOK_URL:
        print("Error: DISCORD_WEBHOOK_URL must be set in .env")
        return False

    ok_main = _send_test(DISCORD_WEBHOOK_URL, "Bovada / Main")

    if DISCORD_WEBHOOK_URL_KALSHI:
        ok_kalshi = _send_test(DISCORD_WEBHOOK_URL_KALSHI, "Kalshi")
    else:
        print("  Kalshi: DISCORD_WEBHOOK_URL_KALSHI not set — skipping")
        ok_kalshi = False

    print()
    if ok_main and ok_kalshi:
        print("Both webhooks working!")
    elif ok_main:
        print("Main webhook working. Kalshi webhook failed or not configured.")
    else:
        print("Main webhook failed.")

    return ok_main and ok_kalshi


if __name__ == "__main__":
    test_notification()
