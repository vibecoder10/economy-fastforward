-- Migration 023: Dashboard fixes — soft delete, video clip prompts, user preferences
-- Date: 2026-04-03

-- 1. Soft delete: add deleted_at column to videos
ALTER TABLE videos ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_videos_deleted_at ON videos(tenant_id, deleted_at);

-- 2. Video clip prompts: add video_clip_prompt column to assets
-- (assets already has video_prompt TEXT, but we need explicit clip prompt tracking)
ALTER TABLE assets ADD COLUMN IF NOT EXISTS video_clip_prompt TEXT;

-- 3. User preferences table for tab order and UI settings
CREATE TABLE IF NOT EXISTS user_preferences (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id UUID REFERENCES accounts(id) ON DELETE CASCADE NOT NULL,
  preference_key TEXT NOT NULL,
  preference_value JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(account_id, preference_key)
);

CREATE INDEX IF NOT EXISTS idx_user_preferences_account ON user_preferences(account_id);
