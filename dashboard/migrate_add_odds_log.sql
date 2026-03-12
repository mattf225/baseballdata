-- B.L.A.S.T. Migration: Add mlb_odds_log table
-- Run this once in your Supabase SQL Editor.
-- After this, every pipeline run will archive the live odds it fetches,
-- building a real historical dataset for future backtesting.

CREATE TABLE IF NOT EXISTS mlb_odds_log (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id         TEXT NOT NULL,
    game_date        DATE,
    player_name      TEXT NOT NULL,
    market           TEXT NOT NULL,
    sportsbook       TEXT NOT NULL,
    odds_american    INTEGER NOT NULL,
    implied_prob     NUMERIC(6, 4),
    fetched_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Disable RLS (private internal table)
ALTER TABLE mlb_odds_log DISABLE ROW LEVEL SECURITY;

-- Indexes for backtesting queries
CREATE INDEX IF NOT EXISTS idx_odds_log_player   ON mlb_odds_log (player_name);
CREATE INDEX IF NOT EXISTS idx_odds_log_market   ON mlb_odds_log (market);
CREATE INDEX IF NOT EXISTS idx_odds_log_date     ON mlb_odds_log (game_date DESC);
CREATE INDEX IF NOT EXISTS idx_odds_log_fetched  ON mlb_odds_log (fetched_at DESC);

-- Composite index for backtest lookups: "give me all odds for player X on date Y"
CREATE INDEX IF NOT EXISTS idx_odds_log_player_date ON mlb_odds_log (player_name, game_date, market);
