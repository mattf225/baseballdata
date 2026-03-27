-- Migration: Add batter_gamelogs table for per-game rolling feature storage
-- Run this in the Supabase SQL Editor before the 2026 season starts
-- Mirrors pitcher_gamelogs structure for batter-side inference

CREATE TABLE IF NOT EXISTS batter_gamelogs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batter_name  TEXT NOT NULL,       -- pre-normalized: lowercase, accent-stripped
    game_date    DATE NOT NULL,
    "PA"         INTEGER NOT NULL,
    "AB"         INTEGER NOT NULL,
    "H"          INTEGER NOT NULL,
    "HR"         INTEGER NOT NULL,
    "SO"         INTEGER NOT NULL,
    "TB"         INTEGER NOT NULL,
    fetched_at   TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_batter_gamedate UNIQUE (batter_name, game_date)
);

ALTER TABLE batter_gamelogs DISABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS idx_batter_gamelogs_name_date ON batter_gamelogs (batter_name, game_date DESC);
CREATE INDEX IF NOT EXISTS idx_batter_gamelogs_date ON batter_gamelogs (game_date DESC);
