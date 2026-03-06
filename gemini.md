# Project Constitution: MLB Automation (+EV Betting)

## Core Principles
1. **North Star:** Automatically identify positive expected value (+EV) MLB bets by comparing a statistical baseline model (using pitch types, weather, and stadium data) against real-time sportsbook player props odds, and instantly alert the user.
2. **Deliverables vs Intermediates:** Local data in `.tmp/` is ephemeral. The payload is delivered to Discord. 
3. **Architecture First:** Always update SOP files in `architecture/` before touching code in `tools/`. 

## Behavioral Rules
* **Logic Constraint:** Only trigger an alert if the expected value (EV) exceeds the configured confidence threshold (e.g., > 5% edge).
* **Anti-Spam:** Ensure the system hasn't already sent an alert for the exact same player, market, and odds combination within the last 12 hours. Supabase is the single source of truth.
* **Do Not Rules:** 
  - Do NOT include players who are not in the starting lineup.
  - Ignore any odds that look like obvious sportsbook API errors.
* **Tone Requirements:** The delivery message must be purely analytical, objective, and sterile. Use data points only.

## Integrations & Services
* **MLB Data (Baseline):** `pybaseball` library to scrape Statcast (pitch types, exit velocity) and `python-mlb-statsapi` (weather, stadium dimensions).
* **Sportsbook Odds API:** `The Odds API` for live MLB player props (`batter_home_runs`, `batter_total_bases`, `batter_hits`, `batter_runs_scored`, `batter_rbis`, `pitcher_strikeouts`, `pitcher_outs`).
* **Messaging/Notification:** Send real-time alerts to Discord Webhook.
* **Relational Database:** Supabase (PostgreSQL) housing 3 core tables: `mlb_historical_performance`, `mlb_daily_probabilities`, `mlb_alert_log`.

## Architectural Invariants
* **Layer 1: Architecture:** Technical SOPs (Markdown files mapping inputs to outputs).
* **Layer 2: Navigation:** Core execution script routing data between tools.
* **Layer 3: Tools:** Deterministic Python scripts interacting with external APIs or the database.
* **Layer 4: Machine Learning (New):** Scikit-learn/XGBoost models trained on historical Statcast data to output mathematically calibrated True Probabilities.

---

## Data Schema definitions

### 1. MLB Model Output Schema (Input)
```json
{
  "player_name": "Shohei Ohtani",
  "game_id": "12345",
  "market": "batter_home_runs",
  "model_probability": 0.280,
  "factors": {"weather": "wind blowing out", "stadium": "Coors Field"}
}
```

### 2. Live Odds Schema (Input)
```json
{
  "player_name": "Shohei Ohtani",
  "sportsbook": "DraftKings",
  "market": "batter_home_runs",
  "odds": 300,
  "implied_probability": 0.250
}
```

### 3. Delivery Payload Schema (Output)
```json
{
  "player_name": "Shohei Ohtani",
  "market": "To Hit a Home Run",
  "sportsbook": "DraftKings",
  "odds_formatted": "+300",
  "implied_probability_percentage": "25.0%",
  "model_probability_percentage": "28.0%",
  "calculated_edge_percentage": "+3.0%"
}
```

---

## Maintenance Log & Automation Strategy
* **Local Run:** `python3 run_mlb_pipeline.py`
* **Scheduled Trigger:** The pipeline runs on an hourly GitHub Actions Cron Schedule (`.github/workflows/mlb_cron.yml`) during active MLB hours (12pm-2am EST), capped at 15 runs per day.
* **Container:** A `Dockerfile` and `requirements.txt` are included to allow hosting the script on any containerized cloud server (e.g. Render, AWS, Google Cloud Run) natively.
* **Updates:** Before each MLB season, re-run `model/build_dataset.py` followed by `model/train_model.py` to bake in the newest statistical baselines into the Machine Learning prediction `.pkl` files.
