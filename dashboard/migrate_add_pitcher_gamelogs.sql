-- Migration: Add pitcher_gamelogs table for per-start rolling feature storage
-- Run this in the Supabase SQL Editor before using tools/gamelog_updater.py

CREATE TABLE IF NOT EXISTS pitcher_gamelogs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pitcher_name TEXT NOT NULL,      -- pre-normalized: lowercase, accent-stripped
    game_date    DATE NOT NULL,
    BF           INTEGER NOT NULL,
    SO           INTEGER NOT NULL,
    BBA          INTEGER NOT NULL,
    HA           INTEGER NOT NULL,
    Outs         INTEGER NOT NULL,
    K_pct        NUMERIC(6,4),
    opp_team     TEXT,
    opp_k_pct    NUMERIC(6,4),
    fetched_at   TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_pitcher_gamedate UNIQUE (pitcher_name, game_date)
);

ALTER TABLE pitcher_gamelogs DISABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS idx_gamelogs_pitcher_date ON pitcher_gamelogs (pitcher_name, game_date DESC);
CREATE INDEX IF NOT EXISTS idx_gamelogs_date ON pitcher_gamelogs (game_date DESC);
