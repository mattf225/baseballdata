-- Migration: Add model_prob and edge columns to mlb_odds_log
-- Run this in the Supabase SQL Editor

ALTER TABLE mlb_odds_log ADD COLUMN IF NOT EXISTS model_prob FLOAT;
ALTER TABLE mlb_odds_log ADD COLUMN IF NOT EXISTS edge FLOAT;
