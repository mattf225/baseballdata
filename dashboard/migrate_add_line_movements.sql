-- Migration: Add mlb_line_movements table for odds movement tracking
-- Run this in the Supabase SQL Editor before line movement detection goes live.

CREATE TABLE IF NOT EXISTS mlb_line_movements (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    player_name      TEXT NOT NULL,
    market           TEXT NOT NULL,
    sportsbook       TEXT NOT NULL,
    game_date        DATE,
    old_odds         INTEGER NOT NULL,
    new_odds         INTEGER NOT NULL,
    old_implied_prob NUMERIC(6,4),
    new_implied_prob NUMERIC(6,4),
    prob_shift       NUMERIC(6,4),   -- new - old; negative = line getting harder (book raising implied prob)
    detected_at      TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE mlb_line_movements DISABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS idx_movements_player   ON mlb_line_movements (player_name);
CREATE INDEX IF NOT EXISTS idx_movements_market   ON mlb_line_movements (market);
CREATE INDEX IF NOT EXISTS idx_movements_detected ON mlb_line_movements (detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_movements_player_market ON mlb_line_movements (player_name, market, sportsbook, detected_at DESC);
