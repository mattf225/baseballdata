-- Add projection column to mlb_alert_log
-- Stores the model's projected stat value (e.g., 6.8 K for a pitcher_strikeouts alert).
ALTER TABLE mlb_alert_log ADD COLUMN IF NOT EXISTS projection REAL;
