-- Migration: Add sync support tables and columns
-- Run this if you already have the base schema from the original schema.sql.
-- If starting fresh, just run the updated schema.sql instead.

-- =====================================================================
-- Add airtable_record_id to scripts and assets for upsert support
-- =====================================================================

ALTER TABLE scripts ADD COLUMN IF NOT EXISTS airtable_record_id TEXT UNIQUE;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS airtable_record_id TEXT UNIQUE;

-- =====================================================================
-- Add performance snapshot columns to videos
-- =====================================================================

ALTER TABLE videos ADD COLUMN IF NOT EXISTS post_mortem_48h TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS post_mortem_7d TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS performance_verdict TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS upload_date TIMESTAMPTZ;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS views_24h INTEGER;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS views_48h INTEGER;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS views_7d INTEGER;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS views_30d INTEGER;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS ctr_48h DECIMAL(5,2);
ALTER TABLE videos ADD COLUMN IF NOT EXISTS retention_48h DECIMAL(5,2);
ALTER TABLE videos ADD COLUMN IF NOT EXISTS likes INTEGER DEFAULT 0;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS comments INTEGER DEFAULT 0;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS impressions INTEGER DEFAULT 0;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS subscribers_gained INTEGER DEFAULT 0;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS watch_time_hours DECIMAL(10,2);
ALTER TABLE videos ADD COLUMN IF NOT EXISTS avg_view_duration_seconds INTEGER;

-- =====================================================================
-- Competitor Videos table
-- =====================================================================

CREATE TABLE IF NOT EXISTS competitor_videos (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,
  airtable_record_id TEXT UNIQUE,
  channel_name TEXT,
  channel_id TEXT,
  video_title TEXT NOT NULL,
  video_url TEXT,
  video_id TEXT,
  published_at TIMESTAMPTZ,
  views INTEGER DEFAULT 0,
  likes INTEGER DEFAULT 0,
  comments INTEGER DEFAULT 0,
  duration_seconds INTEGER,
  thumbnail_url TEXT,
  description TEXT,
  tags JSONB,
  category TEXT,
  topic TEXT,
  framework_match TEXT,
  relevance_score INTEGER,
  scraped_at TIMESTAMPTZ DEFAULT now(),
  metadata JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- =====================================================================
-- Osiris Learnings table
-- =====================================================================

CREATE TABLE IF NOT EXISTS learnings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,
  airtable_record_id TEXT UNIQUE,
  pattern TEXT NOT NULL,
  category TEXT CHECK (category IN ('title', 'hook', 'thumbnail', 'retention', 'framework')),
  detail TEXT,
  confidence INTEGER,
  sample_size INTEGER,
  avg_ctr DECIMAL(5,2),
  avg_retention DECIMAL(5,2),
  source_videos TEXT,
  active BOOLEAN DEFAULT true,
  learned_at TIMESTAMPTZ,
  last_updated TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- =====================================================================
-- New indexes
-- =====================================================================

CREATE INDEX IF NOT EXISTS idx_assets_airtable ON assets(airtable_record_id);
CREATE INDEX IF NOT EXISTS idx_scripts_airtable ON scripts(airtable_record_id);
CREATE INDEX IF NOT EXISTS idx_competitor_videos_tenant ON competitor_videos(tenant_id);
CREATE INDEX IF NOT EXISTS idx_competitor_videos_channel ON competitor_videos(channel_name);
CREATE INDEX IF NOT EXISTS idx_competitor_videos_airtable ON competitor_videos(airtable_record_id);
CREATE INDEX IF NOT EXISTS idx_learnings_tenant ON learnings(tenant_id);
CREATE INDEX IF NOT EXISTS idx_learnings_category ON learnings(tenant_id, category);
CREATE INDEX IF NOT EXISTS idx_learnings_airtable ON learnings(airtable_record_id);

-- =====================================================================
-- RLS for new tables
-- =====================================================================

ALTER TABLE competitor_videos ENABLE ROW LEVEL SECURITY;
ALTER TABLE learnings ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  CREATE POLICY "Tenant isolation" ON competitor_videos
    FOR ALL TO authenticated
    USING (tenant_id IN (
      SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid())
    ));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE POLICY "Tenant isolation" ON learnings
    FOR ALL TO authenticated
    USING (tenant_id IN (
      SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid())
    ));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
