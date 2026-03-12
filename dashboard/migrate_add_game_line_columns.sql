-- Migration: add game line columns to mlb_odds_log
-- Run once in Supabase SQL Editor

ALTER TABLE mlb_odds_log
    ADD COLUMN IF NOT EXISTS point         DECIMAL(6,2),
    ADD COLUMN IF NOT EXISTS home_team     TEXT,
    ADD COLUMN IF NOT EXISTS away_team     TEXT,
    ADD COLUMN IF NOT EXISTS commence_time TIMESTAMPTZ;

-- Index on commence_time for game-line views ordered by game time
CREATE INDEX IF NOT EXISTS idx_odds_log_commence ON mlb_odds_log (commence_time DESC);
