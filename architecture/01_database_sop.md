# Database Architecture (MLB Supabase)

## Goal
Establish a relational database in Supabase (PostgreSQL) to store raw probability numbers from our custom MLB model (`pybaseball`), track historical performance metrics (like Exit Velocity or Strikeout Rates), and log all alerts sent to Discord to enforce the 12-hour anti-spam rule. A single source of truth for the entire pipeline.

## Schema Details

### Table: `mlb_historical_performance`
Tracks underlying structural data for MLB players, scraped or updated periodically from `pybaseball`/Statcast.

* `id` (UUID, Primary Key)
* `player_name` (Text, Unique)
* `mlb_id` (Integer, Optional, Maps to MLB proprietary ID)
* `avg_exit_velo` (Numeric, Average Exit Velocity baseline)
* `k_rate` (Numeric, Strikeout Rate)
* `last_updated` (Timestamp with time zone)

### Table: `mlb_daily_probabilities`
Stores the outputs of the custom predictive model for the current day's active games.

* `id` (UUID, Primary Key)
* `game_id` (Text)
* `player_name` (Text)
* `market` (Text, e.g., 'batter_home_runs', 'pitcher_strikeouts')
* `model_probability` (Numeric, e.g., 0.280 for 28.0%)
* `created_at` (Timestamp with time zone)

### Table: `mlb_alert_log`
The authoritative log to ensure the system does not spam the same +EV bet multiple times in a 12-hour window.

* `id` (UUID, Primary Key)
* `player_name` (Text)
* `market` (Text)
* `sportsbook` (Text)
* `odds_formatted` (Text)
* `calculated_edge_percentage` (Numeric)
* `sent_at` (Timestamp with time zone, Default: now())

**Constraint:** The `run_mlb_pipeline.py` script must query `mlb_alert_log` before sending a webhook:
`SELECT id FROM mlb_alert_log WHERE player_name = ? AND market = ? AND sportsbook = ? AND sent_at > NOW() - INTERVAL '12 hours'`
If a record exists, the alert is suppressed.

## Authentication
Connection string and Supabase service role keys must be stored in `.env`:
* `SUPABASE_URL`
* `SUPABASE_ANON_KEY`
