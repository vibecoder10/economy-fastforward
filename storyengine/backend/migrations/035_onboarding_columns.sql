-- Migration 035: Onboarding columns for redesigned wizard
-- Adds user type, onboarding tracking, style description, and YouTube channel fields

ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS user_type TEXT;
ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS onboarding_step INTEGER DEFAULT 0;
ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS onboarding_completed_at TIMESTAMPTZ;
ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS style_description TEXT;
ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS youtube_channel_id TEXT;
ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS youtube_channel_name TEXT;
ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS youtube_refresh_token TEXT;
