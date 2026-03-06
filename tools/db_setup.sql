-- Supabase Setup Script for MLB Data Automation (+EV Betting)
-- Run this in the Supabase SQL Editor

-- Optional: Drop the old Golf tables if they exist to keep the database clean
DROP TABLE IF EXISTS public.historical_performance;
DROP TABLE IF EXISTS public.weekly_probabilities;
DROP TABLE IF EXISTS public.alert_log;


-- 1. mlb_historical_performance table
-- Tracks Statcast/pybaseball data
CREATE TABLE public.mlb_historical_performance (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    player_name TEXT UNIQUE NOT NULL,
    mlb_id INTEGER,
    avg_exit_velo NUMERIC,
    k_rate NUMERIC,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 2. mlb_daily_probabilities table
-- Stores daily model outputs based on stadium, weather, and matchups
CREATE TABLE public.mlb_daily_probabilities (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    game_id TEXT NOT NULL,
    player_name TEXT NOT NULL,
    market TEXT NOT NULL,
    model_probability NUMERIC NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Index for faster lookups when mapping live odds to daily probabilities
CREATE INDEX idx_mlb_daily_prob_player_market ON public.mlb_daily_probabilities(player_name, market);


-- 3. mlb_alert_log table
-- Logs Discord webhooks to enforce the 12-hour Anti-Spam rule
CREATE TABLE public.mlb_alert_log (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    player_name TEXT NOT NULL,
    market TEXT NOT NULL,
    sportsbook TEXT NOT NULL,
    odds_formatted TEXT,
    calculated_edge_percentage NUMERIC,
    sent_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Index for the 12-hour anti-spam query
CREATE INDEX idx_mlb_alert_log_spam_check ON public.mlb_alert_log(player_name, market, sportsbook, sent_at);
