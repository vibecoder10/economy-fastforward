-- Migration 041: Onboarding Intelligence tables
-- Adds intelligence_reports + channel_videos tables for onboarding flow
-- Extends channel_profiles + competitor_channels with metadata

-- =============================================
-- INTELLIGENCE REPORTS (onboarding + recurring)
-- =============================================

CREATE TABLE IF NOT EXISTS intelligence_reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  report_type TEXT DEFAULT 'onboarding',
  title_ideas JSONB,
  thumbnail_insights JSONB,
  hook_ideas JSONB,
  channel_analysis JSONB,
  competitors_analyzed INTEGER DEFAULT 0,
  videos_analyzed INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_intelligence_reports_tenant ON intelligence_reports(tenant_id);

ALTER TABLE intelligence_reports ENABLE ROW LEVEL SECURITY;


-- =============================================
-- CHANNEL VIDEOS (user's own YouTube videos)
-- =============================================

CREATE TABLE IF NOT EXISTS channel_videos (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  video_id TEXT NOT NULL,
  title TEXT,
  published_at TIMESTAMPTZ,
  view_count BIGINT,
  like_count BIGINT,
  comment_count BIGINT,
  duration_seconds INTEGER,
  thumbnail_url TEXT,
  ctr_percent NUMERIC(5,2),
  avg_view_duration_seconds INTEGER,
  metadata JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(tenant_id, video_id)
);

CREATE INDEX IF NOT EXISTS idx_channel_videos_tenant ON channel_videos(tenant_id);

ALTER TABLE channel_videos ENABLE ROW LEVEL SECURITY;


-- =============================================
-- EXTEND CHANNEL PROFILES (onboarding state)
-- =============================================

ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS competitors_added BOOLEAN DEFAULT false;
ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS intelligence_generated BOOLEAN DEFAULT false;
ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS tutorial_completed BOOLEAN DEFAULT false;


-- =============================================
-- EXTEND COMPETITOR CHANNELS (metadata)
-- =============================================

ALTER TABLE competitor_channels ADD COLUMN IF NOT EXISTS subscriber_count BIGINT;
ALTER TABLE competitor_channels ADD COLUMN IF NOT EXISTS video_count INTEGER;
ALTER TABLE competitor_channels ADD COLUMN IF NOT EXISTS youtube_channel_id TEXT;
