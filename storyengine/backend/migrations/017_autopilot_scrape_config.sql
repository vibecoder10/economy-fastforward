-- Add configurable scrape limit to autopilot config
ALTER TABLE autopilot_config ADD COLUMN IF NOT EXISTS videos_per_scrape INTEGER DEFAULT 10;
