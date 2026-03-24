-- 006_niche_columns.sql
-- Adds niche configuration to autopilot_config
-- All statements idempotent

ALTER TABLE autopilot_config ADD COLUMN IF NOT EXISTS niche_category TEXT;
ALTER TABLE autopilot_config ADD COLUMN IF NOT EXISTS sub_niche TEXT;
