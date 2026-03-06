# MLB Notification SOP

## Goal
Format the resulting +EV bet into a sterile, analytical JSON payload and dispatch it to the Discord Webhook. The payload must adhere to the 'Objective Tone' behavioral rule in the Project Constitution.

## Discord Payload Structure
Discord webhooks accept a standard JSON payload with a `"content"` key for simple text, or an `"embeds"` array for rich formatting. We will use the `"embeds"` format for cleaner data presentation.

```json
{
  "embeds": [
    {
      "title": "🚨 MLB +EV Alert Identified",
      "color": 3447003,
      "fields": [
        {
          "name": "Player & Market",
          "value": "Shohei Ohtani - To Hit a Home Run",
          "inline": false
        },
        {
          "name": "Sportsbook",
          "value": "DraftKings",
          "inline": true
        },
        {
          "name": "Odds",
          "value": "+300 (25.0% Implied)",
          "inline": true
        },
        {
          "name": "Model Analytics",
          "value": "True Probability: 28.0% | Calculated Edge: +3.0%",
          "inline": false
        }
      ],
      "footer": {
        "text": "B.L.A.S.T. MLB Automation System"
      }
    }
  ]
}
```

## Anti-Spam Gate
Before `notifier.py` is called, the Layer 2 orchestrator MUST verify with `db_client.py` that this exact `Player + Market + Sportsbook` combination has not been fired in the last 12 hours.
