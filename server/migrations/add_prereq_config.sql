-- Add prerequisite configuration columns to settings table
-- These control mandatory checks before any strategy (ORB/SMC) evaluation

ALTER TABLE settings ADD COLUMN prereq_min_rvol REAL DEFAULT 1.0;
ALTER TABLE settings ADD COLUMN prereq_rvol_enabled INTEGER DEFAULT 1;
ALTER TABLE settings ADD COLUMN prereq_min_liquidity_cr REAL;
ALTER TABLE settings ADD COLUMN prereq_min_price REAL;
ALTER TABLE settings ADD COLUMN prereq_max_price REAL;
ALTER TABLE settings ADD COLUMN prereq_allowed_sectors TEXT;  -- JSON array
ALTER TABLE settings ADD COLUMN prereq_blocked_symbols TEXT;  -- JSON array
