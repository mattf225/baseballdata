-- Add game_date column to mlb_alert_log
-- Separates the actual game date from when the alert was triggered (sent_at).
ALTER TABLE mlb_alert_log ADD COLUMN IF NOT EXISTS game_date DATE;

-- Backfill existing rows: derive game_date from sent_at
UPDATE mlb_alert_log SET game_date = (sent_at AT TIME ZONE 'America/New_York')::date WHERE game_date IS NULL;
