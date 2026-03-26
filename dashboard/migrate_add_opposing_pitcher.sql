-- Add opposing_pitcher column to mlb_odds_log
-- Stores the probable starting pitcher the player is facing
ALTER TABLE mlb_odds_log ADD COLUMN IF NOT EXISTS opposing_pitcher TEXT;
