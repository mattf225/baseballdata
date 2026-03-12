-- B.L.A.S.T. Migration: Add actual_outcome to mlb_alert_log
-- Run this once in your Supabase SQL Editor before running backfill_outcomes.py

ALTER TABLE mlb_alert_log
  ADD COLUMN IF NOT EXISTS actual_outcome BOOLEAN DEFAULT NULL;

-- NULL  = outcome not yet resolved (pending)
-- TRUE  = the prop bet HIT (model was correct)
-- FALSE = the prop bet MISSED (model was wrong)

-- Disable RLS on mlb_alert_log (private internal table — not exposed to public)
-- Without this, inserts from the seeder and pipeline will be blocked.
ALTER TABLE mlb_alert_log DISABLE ROW LEVEL SECURITY;

-- Optional: index for dashboard queries
CREATE INDEX IF NOT EXISTS idx_alert_log_outcome ON mlb_alert_log (actual_outcome);
CREATE INDEX IF NOT EXISTS idx_alert_log_sent_at ON mlb_alert_log (sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_alert_log_market  ON mlb_alert_log (market);
