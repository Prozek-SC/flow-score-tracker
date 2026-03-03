-- ============================================================
-- FLOW SCORE TRACKER — SUPABASE SCHEMA v2
-- Run in Supabase SQL Editor
-- ============================================================

-- Watchlist
CREATE TABLE IF NOT EXISTS watchlist (
    id BIGSERIAL PRIMARY KEY,
    ticker TEXT NOT NULL UNIQUE,
    sector TEXT DEFAULT '',
    active BOOLEAN DEFAULT TRUE,
    added_at TIMESTAMPTZ DEFAULT NOW(),
    notes TEXT
);

-- Weekly Flow Scores (full 3-pillar score)
CREATE TABLE IF NOT EXISTS weekly_scores (
    id BIGSERIAL PRIMARY KEY,
    ticker TEXT NOT NULL,
    date DATE NOT NULL,
    flow_score NUMERIC(5,2) DEFAULT 0,
    rating TEXT,
    label TEXT,
    action TEXT,
    price NUMERIC(12,4),
    sector TEXT,
    pillars JSONB,
    burst JSONB,
    scored_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(ticker, date)
);

-- Daily Price Updates (lightweight — no full rescore)
CREATE TABLE IF NOT EXISTS daily_prices (
    id BIGSERIAL PRIMARY KEY,
    ticker TEXT NOT NULL,
    date DATE NOT NULL,
    price NUMERIC(12,4),
    ma50 NUMERIC(12,4),
    ma200 NUMERIC(12,4),
    relative_volume NUMERIC(8,4),
    above_50ma BOOLEAN,
    above_200ma BOOLEAN,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(ticker, date)
);

-- Sector Flow Scores
CREATE TABLE IF NOT EXISTS sector_scores (
    id BIGSERIAL PRIMARY KEY,
    date DATE NOT NULL,
    sector TEXT NOT NULL,
    etf TEXT,
    flow_score NUMERIC(5,2),
    capital_flow NUMERIC(5,2),
    trend NUMERIC(5,2),
    momentum NUMERIC(5,2),
    etf_flow_m NUMERIC(12,2),
    ytd_perf NUMERIC(8,4),
    status TEXT,
    rank INTEGER,
    UNIQUE(date, sector)
);

-- ICI Fund Flow Data (manually entered weekly)
CREATE TABLE IF NOT EXISTS fund_flows (
    id BIGSERIAL PRIMARY KEY,
    week_ending DATE NOT NULL UNIQUE,
    equity_total NUMERIC(12,2),
    equity_domestic NUMERIC(12,2),
    equity_world NUMERIC(12,2),
    bond_total NUMERIC(12,2),
    commodity NUMERIC(12,2),
    entered_at TIMESTAMPTZ DEFAULT NOW()
);

-- Capital Flow Leaders (top 10 from watchlist)
CREATE TABLE IF NOT EXISTS flow_leaders (
    id BIGSERIAL PRIMARY KEY,
    date DATE NOT NULL,
    ticker TEXT NOT NULL,
    flow_score NUMERIC(5,2),
    rating TEXT,
    sector TEXT,
    capital_flow NUMERIC(5,2),
    trend NUMERIC(5,2),
    momentum NUMERIC(5,2)
);

-- Smart Money Exits (bottom from watchlist)
CREATE TABLE IF NOT EXISTS flow_exits (
    id BIGSERIAL PRIMARY KEY,
    date DATE NOT NULL,
    ticker TEXT NOT NULL,
    flow_score NUMERIC(5,2),
    rating TEXT,
    sector TEXT,
    capital_flow NUMERIC(5,2),
    trend NUMERIC(5,2),
    momentum NUMERIC(5,2)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_weekly_ticker ON weekly_scores(ticker);
CREATE INDEX IF NOT EXISTS idx_weekly_date ON weekly_scores(date DESC);
CREATE INDEX IF NOT EXISTS idx_weekly_score ON weekly_scores(flow_score DESC);
CREATE INDEX IF NOT EXISTS idx_daily_ticker ON daily_prices(ticker);
CREATE INDEX IF NOT EXISTS idx_sector_date ON sector_scores(date DESC);

-- RLS
ALTER TABLE watchlist ENABLE ROW LEVEL SECURITY;
ALTER TABLE weekly_scores ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_prices ENABLE ROW LEVEL SECURITY;
ALTER TABLE sector_scores ENABLE ROW LEVEL SECURITY;
ALTER TABLE fund_flows ENABLE ROW LEVEL SECURITY;
ALTER TABLE flow_leaders ENABLE ROW LEVEL SECURITY;
ALTER TABLE flow_exits ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_all" ON watchlist FOR ALL USING (true);
CREATE POLICY "service_all" ON weekly_scores FOR ALL USING (true);
CREATE POLICY "service_all" ON daily_prices FOR ALL USING (true);
CREATE POLICY "service_all" ON sector_scores FOR ALL USING (true);
CREATE POLICY "service_all" ON fund_flows FOR ALL USING (true);
CREATE POLICY "service_all" ON flow_leaders FOR ALL USING (true);
CREATE POLICY "service_all" ON flow_exits FOR ALL USING (true);
