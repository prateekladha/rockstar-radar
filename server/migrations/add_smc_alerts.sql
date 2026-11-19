-- Add SMC alert configuration to alert_configs table
-- Run this migration: sqlite3 data/app.db < server/migrations/add_smc_alerts.sql

-- Add columns for SMC alerts
ALTER TABLE alert_configs ADD COLUMN smc_alerts_enabled INTEGER DEFAULT 0;
ALTER TABLE alert_configs ADD COLUMN smc_min_score INTEGER DEFAULT 70;

-- Add columns to track SMC alert deliveries (reuse existing alert_deliveries table)
-- No changes needed - we can use symbol + 'SMC' as the state field
