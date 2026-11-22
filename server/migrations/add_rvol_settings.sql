-- Add RVOL calculation configuration columns to settings table
-- These control how RVOL is calculated for the user

ALTER TABLE settings ADD COLUMN rvol_anchor_timeframe TEXT DEFAULT 'day';
ALTER TABLE settings ADD COLUMN rvol_length INTEGER DEFAULT 10;
ALTER TABLE settings ADD COLUMN rvol_calculation_mode TEXT DEFAULT 'cumulative';

-- Valid values:
-- rvol_anchor_timeframe: 'day', 'session', 'week', 'month'
-- rvol_length: integer (lookback period)
-- rvol_calculation_mode: 'cumulative', 'per_bar', 'mean', 'median'
