-- Migration: Add point (line) column to mlb_alert_log
-- Run this in the Supabase SQL Editor

ALTER TABLE mlb_alert_log ADD COLUMN IF NOT EXISTS point FLOAT;
