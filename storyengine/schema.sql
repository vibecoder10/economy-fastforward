-- StoryEngine Dashboard — Supabase PostgreSQL Schema
-- Run this in Supabase SQL Editor (left sidebar → SQL icon)

-- =====================================================================
-- CORE TABLES
-- =====================================================================

-- Tenants (workspaces/channels)
CREATE TABLE IF NOT EXISTS tenants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL,
  plan TEXT DEFAULT 'free',
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Users
CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY REFERENCES auth.users(id),
  email TEXT NOT NULL,
  display_name TEXT,
  avatar_url TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Memberships (user <-> tenant)
CREATE TABLE IF NOT EXISTS memberships (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
  role TEXT DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member')),
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(user_id, tenant_id)
);

-- =====================================================================
-- VIDEOS (maps to Airtable "Idea Concepts")
-- =====================================================================

CREATE TABLE IF NOT EXISTS videos (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'idea_logged',
  airtable_record_id TEXT UNIQUE,

  -- Pipeline metadata
  framework_angle TEXT,
  research_payload JSONB,
  original_dna JSONB,
  script TEXT,
  story_bible TEXT,
  thumbnail_url TEXT,
  thumbnail_prompt TEXT,
  accent_color TEXT DEFAULT '#00D4AA',
  visual_style TEXT DEFAULT 'holographic_hud',
  video_length_minutes INTEGER DEFAULT 10,
  clip_duration_seconds INTEGER DEFAULT 10,

  -- Performance (lifetime)
  views INTEGER DEFAULT 0,
  ctr DECIMAL(5,2),
  avg_retention DECIMAL(5,2),
  youtube_url TEXT,
  likes INTEGER DEFAULT 0,
  comments INTEGER DEFAULT 0,
  impressions INTEGER DEFAULT 0,
  subscribers_gained INTEGER DEFAULT 0,
  watch_time_hours DECIMAL(10,2),
  avg_view_duration_seconds INTEGER,

  -- Performance snapshots (written once at milestones)
  views_24h INTEGER,
  views_48h INTEGER,
  views_7d INTEGER,
  views_30d INTEGER,
  ctr_48h DECIMAL(5,2),
  retention_48h DECIMAL(5,2),

  -- Osiris analysis
  post_mortem_48h TEXT,
  post_mortem_7d TEXT,
  performance_verdict TEXT,
  upload_date TIMESTAMPTZ,

  -- Costs
  total_cost DECIMAL(10,2) DEFAULT 0,

  -- Timestamps
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- =====================================================================
-- PIPELINE STAGES LOG
-- =====================================================================

CREATE TABLE IF NOT EXISTS stage_transitions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  video_id UUID REFERENCES videos(id) ON DELETE CASCADE NOT NULL,
  tenant_id UUID REFERENCES tenants(id) NOT NULL,
  from_status TEXT,
  to_status TEXT NOT NULL,
  triggered_by TEXT,
  cost DECIMAL(10,2) DEFAULT 0,
  duration_seconds INTEGER,
  error_message TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- =====================================================================
-- ASSETS (images, storyboards, thumbnails, voice files)
-- =====================================================================

CREATE TABLE IF NOT EXISTS assets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  video_id UUID REFERENCES videos(id) ON DELETE CASCADE NOT NULL,
  tenant_id UUID REFERENCES tenants(id) NOT NULL,
  airtable_record_id TEXT UNIQUE,
  asset_type TEXT NOT NULL CHECK (asset_type IN ('image', 'storyboard_grid', 'storyboard_frame', 'thumbnail', 'voice', 'video_clip', 'render')),
  scene_number INTEGER,
  image_index INTEGER,
  url TEXT NOT NULL,
  prompt TEXT,
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'generating', 'done', 'approved', 'rejected')),
  metadata JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- =====================================================================
-- SCRIPTS (scene-level text)
-- =====================================================================

CREATE TABLE IF NOT EXISTS scripts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  video_id UUID REFERENCES videos(id) ON DELETE CASCADE NOT NULL,
  tenant_id UUID REFERENCES tenants(id) NOT NULL,
  airtable_record_id TEXT UNIQUE,
  scene_number INTEGER NOT NULL,
  scene_text TEXT NOT NULL,
  voice_url TEXT,
  voice_status TEXT DEFAULT 'pending',
  sources TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- =====================================================================
-- BOT ACTIVITY LOG
-- =====================================================================

CREATE TABLE IF NOT EXISTS bot_activity (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) NOT NULL,
  bot_name TEXT NOT NULL,
  video_id UUID REFERENCES videos(id),
  status TEXT NOT NULL CHECK (status IN ('started', 'running', 'completed', 'failed')),
  message TEXT,
  cost DECIMAL(10,2) DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- =====================================================================
-- COMPETITOR VIDEOS (Osiris training data)
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
-- OSIRIS LEARNINGS
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
-- INDEXES
-- =====================================================================

CREATE INDEX IF NOT EXISTS idx_videos_tenant ON videos(tenant_id);
CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_videos_airtable ON videos(airtable_record_id);
CREATE INDEX IF NOT EXISTS idx_assets_video ON assets(video_id);
CREATE INDEX IF NOT EXISTS idx_assets_tenant ON assets(tenant_id);
CREATE INDEX IF NOT EXISTS idx_assets_airtable ON assets(airtable_record_id);
CREATE INDEX IF NOT EXISTS idx_scripts_video ON scripts(video_id);
CREATE INDEX IF NOT EXISTS idx_scripts_airtable ON scripts(airtable_record_id);
CREATE INDEX IF NOT EXISTS idx_bot_activity_tenant ON bot_activity(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_stage_transitions_video ON stage_transitions(video_id);
CREATE INDEX IF NOT EXISTS idx_competitor_videos_tenant ON competitor_videos(tenant_id);
CREATE INDEX IF NOT EXISTS idx_competitor_videos_channel ON competitor_videos(channel_name);
CREATE INDEX IF NOT EXISTS idx_competitor_videos_airtable ON competitor_videos(airtable_record_id);
CREATE INDEX IF NOT EXISTS idx_learnings_tenant ON learnings(tenant_id);
CREATE INDEX IF NOT EXISTS idx_learnings_category ON learnings(tenant_id, category);
CREATE INDEX IF NOT EXISTS idx_learnings_airtable ON learnings(airtable_record_id);

-- =====================================================================
-- ROW LEVEL SECURITY
-- =====================================================================

ALTER TABLE videos ENABLE ROW LEVEL SECURITY;
ALTER TABLE assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE scripts ENABLE ROW LEVEL SECURITY;
ALTER TABLE bot_activity ENABLE ROW LEVEL SECURITY;
ALTER TABLE stage_transitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE competitor_videos ENABLE ROW LEVEL SECURITY;
ALTER TABLE learnings ENABLE ROW LEVEL SECURITY;

-- RLS Policies (idempotent via DO blocks)
DO $$ BEGIN
  CREATE POLICY "Tenant isolation" ON videos
    FOR ALL TO authenticated
    USING (tenant_id IN (
      SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid())
    ));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE POLICY "Tenant isolation" ON assets
    FOR ALL TO authenticated
    USING (tenant_id IN (
      SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid())
    ));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE POLICY "Tenant isolation" ON scripts
    FOR ALL TO authenticated
    USING (tenant_id IN (
      SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid())
    ));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE POLICY "Tenant isolation" ON bot_activity
    FOR ALL TO authenticated
    USING (tenant_id IN (
      SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid())
    ));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE POLICY "Tenant isolation" ON stage_transitions
    FOR ALL TO authenticated
    USING (tenant_id IN (
      SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid())
    ));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

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

-- =====================================================================
-- SEED DATA
-- =====================================================================

INSERT INTO tenants (name, slug) VALUES ('Economy FastForward', 'eff')
ON CONFLICT (slug) DO NOTHING;
