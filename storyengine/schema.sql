-- StoryEngine Dashboard — Supabase PostgreSQL Schema
-- Run this in Supabase SQL Editor (replaces previous schema)
--
-- Drop all existing tables first if they exist (fresh start — no data in Supabase yet):

DROP TABLE IF EXISTS discovery_ideas CASCADE;
DROP TABLE IF EXISTS autopilot_config CASCADE;
DROP TABLE IF EXISTS learnings CASCADE;
DROP TABLE IF EXISTS competitor_videos CASCADE;
DROP TABLE IF EXISTS competitor_channels CASCADE;
DROP TABLE IF EXISTS title_insights CASCADE;
DROP TABLE IF EXISTS title_tests CASCADE;
DROP TABLE IF EXISTS bot_activity CASCADE;
DROP TABLE IF EXISTS stage_transitions CASCADE;
DROP TABLE IF EXISTS assets CASCADE;
DROP TABLE IF EXISTS scripts CASCADE;
DROP TABLE IF EXISTS videos CASCADE;
DROP TABLE IF EXISTS memberships CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS tenants CASCADE;

-- =============================================
-- CORE TABLES
-- =============================================

CREATE TABLE tenants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL,
  plan TEXT DEFAULT 'free',
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT NOT NULL,
  display_name TEXT,
  avatar_url TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE memberships (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
  role TEXT DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member')),
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(user_id, tenant_id)
);

-- =============================================
-- VIDEOS (from Airtable: Idea Concepts)
-- =============================================

CREATE TABLE videos (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,
  project_id UUID REFERENCES projects(id),
  airtable_record_id TEXT UNIQUE,

  -- Core
  video_title TEXT,
  status TEXT,
  headline TEXT,
  source TEXT,

  -- Editorial
  framework_angle TEXT,
  thematic_framework TEXT,
  hook_script TEXT,
  past_context TEXT,
  present_parallel TEXT,
  future_prediction TEXT,
  writer_guidance TEXT,
  thesis TEXT,
  executive_hook TEXT,
  script TEXT,
  seo_description TEXT,
  seo_tags TEXT,
  seo_hashtags TEXT,

  -- Research
  research_payload JSONB,
  original_dna JSONB,
  source_urls TEXT,
  date_surfaced DATE,

  -- Scoring
  timeliness_score NUMERIC,
  audience_fit_score NUMERIC,
  content_gap_score NUMERIC,
  structure_confidence NUMERIC,
  curiosity_structure TEXT,
  monetization_risk TEXT,

  -- Visual
  thumbnail_prompt TEXT,
  thumbnail_style_override TEXT,
  thumbnail_text TEXT,
  thumbnail_approach TEXT,
  accent_color TEXT DEFAULT '#00D4AA',
  visual_style TEXT,
  image_model_override TEXT,
  image_style_override TEXT,
  story_bible TEXT,
  script_validation TEXT,
  title_candidates TEXT,
  title_formula TEXT,
  character_reference_url TEXT,
  thumbnail_url TEXT,

  -- Video config
  video_length_minutes NUMERIC,
  clip_duration_seconds NUMERIC,

  -- Drive / YouTube
  final_video_url TEXT,
  drive_folder_link TEXT,
  drive_folder_id TEXT,
  youtube_video_id TEXT,
  youtube_url TEXT,
  upload_status TEXT,
  upload_date TIMESTAMPTZ,

  -- Performance metrics
  views INTEGER DEFAULT 0,
  impressions INTEGER DEFAULT 0,
  likes INTEGER DEFAULT 0,
  comments INTEGER DEFAULT 0,
  subscribers_gained INTEGER DEFAULT 0,
  ctr NUMERIC,
  avg_view_duration_seconds NUMERIC,
  avg_retention NUMERIC,
  watch_time_hours NUMERIC,
  views_24h INTEGER,
  views_48h INTEGER,
  views_7d INTEGER,
  views_30d INTEGER,
  ctr_48h NUMERIC,
  retention_48h NUMERIC,
  last_analytics_sync TIMESTAMPTZ,

  -- Post-mortem
  post_mortem_48h TEXT,
  post_mortem_7d TEXT,
  performance_verdict TEXT,

  -- Storyboard
  storyboard_status TEXT,
  storyboard_preview_url TEXT,
  storyboard_beat_count INTEGER,
  video_model TEXT,

  -- Pipeline state
  scene_file_path TEXT,
  core_image_url TEXT,
  scene_count INTEGER,
  validation_status TEXT,
  video_id_internal TEXT,
  framework TEXT,
  sources TEXT,
  pipeline_mode TEXT,
  notes TEXT,

  -- Source tracking
  reference_url TEXT,
  idea_reasoning TEXT,
  source_views INTEGER,
  source_channel TEXT,

  -- Upload (additional)
  final_video_attachment_url TEXT,

  -- Curiosity Gap (additional)
  structure_source TEXT,
  pattern_library_snapshot TEXT,
  title_poll_result TEXT,
  poll_closed BOOLEAN DEFAULT false,

  -- Thumbnail (additional)
  thumbnail_palette TEXT,
  summary TEXT,

  -- Performance snapshots (additional)
  ctr_12h NUMERIC,
  ctr_24h NUMERIC,

  -- Agent quality
  agent_paper_trail JSONB,
  agent_hook_score NUMERIC,
  agent_body_score NUMERIC,
  agent_tier TEXT,
  agent_cost NUMERIC,

  -- Suggestions (agent proposes, human approves)
  suggested_script TEXT,
  suggested_title TEXT,
  suggested_thumbnail_prompt TEXT,
  suggested_thumbnail_urls JSONB,
  suggestion_source TEXT,
  suggestion_scores JSONB,
  suggestion_status TEXT,

  -- System prompt overrides (per-video)
  video_motion_system_prompt TEXT,
  script_system_prompt TEXT,
  thumbnail_system_prompt TEXT,
  sound_system_prompt TEXT,

  -- Costs
  total_cost NUMERIC DEFAULT 0,

  -- Learning loop tracking
  learnings_extracted_at TIMESTAMPTZ,

  -- Soft delete
  deleted_at TIMESTAMPTZ,

  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- =============================================
-- SCRIPTS (from Airtable: Script)
-- =============================================

CREATE TABLE scripts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,
  video_id UUID REFERENCES videos(id) ON DELETE CASCADE,
  airtable_record_id TEXT UNIQUE,

  airtable_id NUMERIC, -- Airtable "ID" field (their auto-number)
  scene INTEGER,
  title TEXT, -- video title string (for matching)
  scene_text TEXT,
  script_status TEXT,
  voice_status TEXT,
  voice_over_url TEXT,
  voice_duration_seconds NUMERIC,
  voice_id TEXT,
  sources TEXT,
  framework TEXT,
  psych_angle TEXT,
  sound_map TEXT,
  sfx_status TEXT,
  drive_folder TEXT,
  script_validation TEXT,
  unverified_claims TEXT,

  -- Storyboard fields
  storyboard_on_off TEXT,
  storyboard_prompts TEXT,
  storyboard_beat_count NUMERIC,
  storyboard_status TEXT,
  storyboard_1_url TEXT,
  storyboard_2_url TEXT,
  storyboard_3_url TEXT,
  storyboard_4_url TEXT,
  storyboard_5_url TEXT,

  voice_duration_seconds NUMERIC,

  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- =============================================
-- ASSETS (from Airtable: Images)
-- =============================================

CREATE TABLE assets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,
  video_id UUID REFERENCES videos(id) ON DELETE CASCADE,
  airtable_record_id TEXT UNIQUE,

  video_title TEXT, -- for matching to parent
  scene INTEGER,
  sentence_index INTEGER,
  sentence_text TEXT,
  image_index INTEGER,
  duration_seconds NUMERIC,
  image_prompt TEXT,
  original_image_prompt TEXT,
  shot_type TEXT,
  image_url TEXT,
  status TEXT,

  -- Sound
  sound_prompt TEXT,
  sound_effect_url TEXT,
  sound_volume NUMERIC,

  -- Video/Animation
  video_prompt TEXT,
  video_url TEXT,
  video_status TEXT,
  video_duration NUMERIC,
  video_clip_url TEXT,
  aspect_ratio TEXT,
  animation_status TEXT,
  intensity TEXT,
  content_type TEXT,

  -- Flags
  hero_shot BOOLEAN DEFAULT false,

  -- Video clip prompts
  video_clip_prompt TEXT,

  -- Storyboard tracking
  drive_image_url TEXT,
  storyboard_grid_url TEXT,
  panel_position INTEGER,
  generation_method TEXT,
  camera_movement TEXT,
  assigned_video_duration NUMERIC,
  estimated_clip_cost NUMERIC,

  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- =============================================
-- COMPETITOR CHANNELS (from Airtable)
-- =============================================

CREATE TABLE competitor_channels (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,
  airtable_record_id TEXT UNIQUE,

  channel_url TEXT,
  channel_name TEXT,
  category TEXT,
  active BOOLEAN DEFAULT true,
  last_scraped DATE,
  notes TEXT,

  created_at TIMESTAMPTZ DEFAULT now()
);

-- =============================================
-- COMPETITOR VIDEOS (from Airtable)
-- =============================================

CREATE TABLE competitor_videos (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,
  airtable_record_id TEXT UNIQUE,

  video_id TEXT,
  title TEXT,
  published_date DATE,
  vph NUMERIC,
  views INTEGER,
  channel TEXT,
  url TEXT,
  channel_url TEXT,
  hours_old NUMERIC,
  scrape_date DATE,
  modeled BOOLEAN DEFAULT false,
  our_video TEXT,
  topic_cluster TEXT,
  curiosity_structure TEXT,
  structure_confidence NUMERIC,
  thumbnail_style_json TEXT,
  yin_yang_approach TEXT,
  yin_yang_text TEXT,
  analysis_date DATE,
  modeled_by_us BOOLEAN DEFAULT false,
  our_ctr_result NUMERIC,

  modeled_at TIMESTAMPTZ,
  our_video_id UUID REFERENCES videos(id),
  updated_at TIMESTAMPTZ DEFAULT now(),

  -- yt-dlp enrichment columns (migration 016)
  thumbnail_url TEXT,
  transcript TEXT,
  duration_seconds INTEGER,
  description TEXT,
  likes INTEGER,
  distilled_at TIMESTAMPTZ,  -- Set when transcript has been vectorized

  UNIQUE(tenant_id, video_id),

  created_at TIMESTAMPTZ DEFAULT now()
);

-- =============================================
-- CONTENT INTELLIGENCE (distilled data + vectors)
-- =============================================

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE content_intelligence (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,

  -- Source reference
  source_type TEXT NOT NULL,   -- 'competitor_transcript', 'video_script', 'research_payload', 'agent_trail'
  source_id UUID NOT NULL,     -- FK to the source table row
  source_table TEXT NOT NULL,  -- 'competitor_videos', 'videos', etc.

  -- Distilled intelligence
  summary TEXT NOT NULL,
  structured_metadata JSONB NOT NULL,

  -- Vector embedding (OpenAI text-embedding-3-small = 1536 dimensions)
  embedding vector(1536),

  -- Provenance
  model_used TEXT,
  embedding_model TEXT,
  raw_char_count INTEGER,

  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_ci_tenant_source_type ON content_intelligence(tenant_id, source_type);
CREATE INDEX idx_ci_source_id ON content_intelligence(source_id);
CREATE UNIQUE INDEX idx_ci_unique_source ON content_intelligence(tenant_id, source_type, source_id);
CREATE INDEX idx_ci_metadata ON content_intelligence USING gin (structured_metadata);
CREATE INDEX idx_ci_embedding ON content_intelligence USING hnsw (embedding vector_cosine_ops);

-- =============================================
-- OSIRIS LEARNINGS (from Airtable)
-- =============================================

CREATE TABLE learnings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,
  airtable_record_id TEXT UNIQUE,

  pattern TEXT,
  category TEXT,
  detail TEXT,
  confidence NUMERIC,
  sample_size NUMERIC,
  avg_ctr NUMERIC,
  avg_retention NUMERIC,
  source_videos TEXT,
  active BOOLEAN DEFAULT true,
  created_date DATE,
  last_updated DATE,

  created_at TIMESTAMPTZ DEFAULT now()
);

-- =============================================
-- TITLE INSIGHTS (from Airtable)
-- =============================================

CREATE TABLE title_insights (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,
  airtable_record_id TEXT UNIQUE,

  name TEXT,
  pattern_name TEXT,
  description TEXT,
  example_titles TEXT,
  analysis_date DATE,
  pattern_type TEXT,
  avg_vph NUMERIC,
  count INTEGER,
  confidence NUMERIC,
  videos_analyzed INTEGER,
  vph_threshold NUMERIC,

  created_at TIMESTAMPTZ DEFAULT now()
);

-- =============================================
-- TITLE TESTS (from Airtable)
-- =============================================

CREATE TABLE title_tests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,
  airtable_record_id TEXT UNIQUE,

  idea TEXT,
  title_text TEXT,
  structure TEXT,
  structure_confidence NUMERIC,
  thumbnail_text TEXT,
  thumbnail_approach TEXT,
  source_patterns TEXT,
  pattern_library_snapshot TEXT,
  poll_result TEXT,
  poll_closed BOOLEAN DEFAULT false,
  ctr_12h NUMERIC,
  ctr_24h NUMERIC,
  ctr_48h NUMERIC,
  selected BOOLEAN DEFAULT false,
  video_title TEXT,

  created_at TIMESTAMPTZ DEFAULT now()
);

-- =============================================
-- AUTOPILOT CONFIG (per-tenant settings)
-- =============================================

CREATE TABLE autopilot_config (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE UNIQUE NOT NULL,
  enabled BOOLEAN DEFAULT TRUE,
  videos_per_month INT DEFAULT 15,
  production_interval_days INT DEFAULT 2,
  videos_per_scrape INT DEFAULT 10,  -- How many videos to scrape per competitor channel
  weights JSONB DEFAULT '{"competitor_vph": 0.55, "timing_freshness": 0.45}'::jsonb,
  thresholds JSONB DEFAULT '{
      "min_confidence_score": 60,
      "min_competitor_vph": 50,
      "max_idea_age_days": 7,
      "ctr_success_threshold": 4.0,
      "ctr_failure_threshold": 2.5
  }'::jsonb,
  last_cycle TIMESTAMPTZ,
  niche_category TEXT,
  sub_niche TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================
-- DISCOVERY IDEAS (AI-generated video ideas)
-- =============================================

CREATE TABLE discovery_ideas (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,

  -- Source
  source_type TEXT NOT NULL,  -- 'competitor' or 'headline'
  competitor_video_id UUID REFERENCES competitor_videos(id),
  competitor_title TEXT,
  competitor_channel TEXT,
  competitor_url TEXT,
  competitor_vph NUMERIC,
  competitor_thumbnail_url TEXT,

  -- AI-generated content
  our_angle TEXT NOT NULL,
  hook TEXT,
  framework TEXT,
  estimated_appeal NUMERIC,
  appeal_breakdown JSONB,

  -- Title options (3 per idea)
  title_options JSONB NOT NULL DEFAULT '[]'::jsonb,

  -- State
  status TEXT DEFAULT 'fresh',
  selected_title_index INTEGER,
  launched_video_id UUID REFERENCES videos(id),

  -- Batch tracking
  batch_date DATE DEFAULT CURRENT_DATE,
  batch_id TEXT,

  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- =============================================
-- CHANNEL PROFILES (legacy — kept for backward compat)
-- =============================================

CREATE TABLE channel_profiles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE UNIQUE NOT NULL,

  channel_name TEXT DEFAULT '',
  niche TEXT DEFAULT '',
  target_audience TEXT DEFAULT '',
  frameworks JSONB DEFAULT '[]'::jsonb,

  -- Brand Kit
  accent_color TEXT DEFAULT '#00D4AA',
  logo_url TEXT,

  -- Google Drive storage
  google_drive_folder_id TEXT,
  google_drive_folder_name TEXT,

  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- =============================================
-- ACCOUNTS (the human who logs in)
-- =============================================

CREATE TABLE accounts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT,
  display_name TEXT,
  google_id TEXT UNIQUE,
  avatar_url TEXT,
  plan TEXT DEFAULT 'free',
  stripe_customer_id TEXT UNIQUE,
  stripe_subscription_id TEXT,
  stripe_plan TEXT,
  stripe_status TEXT,
  trial_ends_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- =============================================
-- PROJECTS (a channel — replaces channel_profiles)
-- =============================================

CREATE TABLE projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id UUID REFERENCES accounts(id) ON DELETE CASCADE NOT NULL,
  tenant_id UUID REFERENCES tenants(id),

  -- Channel identity
  name TEXT NOT NULL DEFAULT '',
  niche TEXT,
  target_audience TEXT,

  -- Visual system
  visual_style TEXT DEFAULT 'cinematic_illustration',
  visual_profile_json JSONB,
  accent_color TEXT DEFAULT '#00D4AA',
  custom_accent_color TEXT,

  -- Frameworks
  frameworks JSONB DEFAULT '[]'::jsonb,

  -- Character consistency
  character_references JSONB DEFAULT '[]'::jsonb,

  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- =============================================
-- USER PREFERENCES
-- =============================================

CREATE TABLE user_preferences (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id UUID REFERENCES accounts(id) ON DELETE CASCADE NOT NULL,
  preference_key TEXT NOT NULL,
  preference_value JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(account_id, preference_key)
);

-- =============================================
-- TENANT PROMPT DEFAULTS
-- =============================================

CREATE TABLE tenant_prompt_defaults (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  prompt_key TEXT NOT NULL,
  prompt_text TEXT NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(tenant_id, prompt_key)
);

CREATE INDEX idx_tenant_prompt_defaults_tenant ON tenant_prompt_defaults(tenant_id);

-- =============================================
-- PIPELINE TRACKING (StoryEngine internal)
-- =============================================

CREATE TABLE stage_transitions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  video_id UUID REFERENCES videos(id) ON DELETE CASCADE NOT NULL,
  tenant_id UUID REFERENCES tenants(id) NOT NULL,
  from_status TEXT,
  to_status TEXT NOT NULL,
  triggered_by TEXT,
  cost NUMERIC DEFAULT 0,
  duration_seconds INTEGER,
  error_message TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE bot_activity (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) NOT NULL,
  bot_name TEXT NOT NULL,
  video_id UUID REFERENCES videos(id),
  status TEXT NOT NULL CHECK (status IN ('started', 'running', 'completed', 'failed')),
  message TEXT,
  cost NUMERIC DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- =============================================
-- INDEXES
-- =============================================

CREATE INDEX idx_videos_tenant ON videos(tenant_id);
CREATE INDEX idx_videos_status ON videos(tenant_id, status);
CREATE INDEX idx_videos_deleted_at ON videos(tenant_id, deleted_at);
CREATE INDEX idx_videos_airtable ON videos(airtable_record_id);
CREATE INDEX idx_scripts_video ON scripts(video_id);
CREATE INDEX idx_scripts_tenant ON scripts(tenant_id);
CREATE INDEX idx_scripts_airtable ON scripts(airtable_record_id);
CREATE INDEX idx_assets_video ON assets(video_id);
CREATE INDEX idx_assets_tenant ON assets(tenant_id);
CREATE INDEX idx_assets_airtable ON assets(airtable_record_id);
CREATE INDEX idx_competitor_channels_tenant ON competitor_channels(tenant_id);
CREATE INDEX idx_competitor_videos_tenant ON competitor_videos(tenant_id);
CREATE INDEX idx_competitor_videos_airtable ON competitor_videos(airtable_record_id);
CREATE INDEX idx_learnings_tenant ON learnings(tenant_id);
CREATE INDEX idx_learnings_category ON learnings(tenant_id, category);
CREATE INDEX idx_title_insights_tenant ON title_insights(tenant_id);
CREATE INDEX idx_title_tests_tenant ON title_tests(tenant_id);
CREATE INDEX idx_discovery_ideas_tenant ON discovery_ideas(tenant_id);
CREATE INDEX idx_discovery_ideas_status ON discovery_ideas(tenant_id, status, batch_date DESC);
CREATE INDEX idx_bot_activity_tenant ON bot_activity(tenant_id, created_at DESC);
CREATE INDEX idx_stage_transitions_video ON stage_transitions(video_id);
CREATE INDEX idx_channel_profiles_tenant ON channel_profiles(tenant_id);
CREATE INDEX idx_accounts_email ON accounts(email);
CREATE INDEX idx_projects_account ON projects(account_id);
CREATE INDEX idx_projects_tenant ON projects(tenant_id);
CREATE INDEX idx_user_preferences_account ON user_preferences(account_id);
CREATE INDEX idx_videos_project ON videos(project_id);

-- =============================================
-- USAGE TRACKING
-- =============================================

CREATE TABLE tenant_usage (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  period_start DATE NOT NULL DEFAULT date_trunc('month', now())::date,
  videos_created INT DEFAULT 0,
  api_calls INT DEFAULT 0,
  render_minutes NUMERIC(10,2) DEFAULT 0,
  storage_bytes BIGINT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(tenant_id, period_start)
);

CREATE INDEX idx_tenant_usage_tenant_period ON tenant_usage(tenant_id, period_start);

-- =============================================
-- PASSWORD RESET TOKENS
-- =============================================

CREATE TABLE password_reset_tokens (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  token TEXT NOT NULL UNIQUE,
  expires_at TIMESTAMPTZ NOT NULL,
  used_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_password_reset_token ON password_reset_tokens(token);
CREATE INDEX idx_password_reset_account ON password_reset_tokens(account_id);

-- =============================================
-- ROW LEVEL SECURITY
-- =============================================

ALTER TABLE videos ENABLE ROW LEVEL SECURITY;
ALTER TABLE accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE scripts ENABLE ROW LEVEL SECURITY;
ALTER TABLE assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE competitor_channels ENABLE ROW LEVEL SECURITY;
ALTER TABLE competitor_videos ENABLE ROW LEVEL SECURITY;
ALTER TABLE learnings ENABLE ROW LEVEL SECURITY;
ALTER TABLE title_insights ENABLE ROW LEVEL SECURITY;
ALTER TABLE title_tests ENABLE ROW LEVEL SECURITY;
ALTER TABLE stage_transitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE bot_activity ENABLE ROW LEVEL SECURITY;
ALTER TABLE autopilot_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE discovery_ideas ENABLE ROW LEVEL SECURITY;
ALTER TABLE channel_profiles ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Tenant isolation" ON videos FOR ALL TO authenticated
  USING (tenant_id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid())));
CREATE POLICY "Tenant isolation" ON scripts FOR ALL TO authenticated
  USING (tenant_id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid())));
CREATE POLICY "Tenant isolation" ON assets FOR ALL TO authenticated
  USING (tenant_id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid())));
CREATE POLICY "Tenant isolation" ON competitor_channels FOR ALL TO authenticated
  USING (tenant_id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid())));
CREATE POLICY "Tenant isolation" ON competitor_videos FOR ALL TO authenticated
  USING (tenant_id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid())));
CREATE POLICY "Tenant isolation" ON learnings FOR ALL TO authenticated
  USING (tenant_id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid())));
CREATE POLICY "Tenant isolation" ON title_insights FOR ALL TO authenticated
  USING (tenant_id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid())));
CREATE POLICY "Tenant isolation" ON title_tests FOR ALL TO authenticated
  USING (tenant_id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid())));
CREATE POLICY "Tenant isolation" ON stage_transitions FOR ALL TO authenticated
  USING (tenant_id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid())));
CREATE POLICY "Tenant isolation" ON bot_activity FOR ALL TO authenticated
  USING (tenant_id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid())));
CREATE POLICY "Tenant isolation" ON autopilot_config FOR ALL TO authenticated
  USING (tenant_id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid())));
CREATE POLICY "Tenant isolation" ON discovery_ideas FOR ALL TO authenticated
  USING (tenant_id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid())));
CREATE POLICY "Tenant isolation" ON channel_profiles FOR ALL TO authenticated
  USING (tenant_id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid())));
CREATE POLICY "Own account only" ON accounts FOR ALL TO authenticated
  USING (id = (SELECT auth.uid()));
CREATE POLICY "Owner or tenant member" ON projects FOR ALL TO authenticated
  USING (
    account_id = (SELECT auth.uid())
    OR tenant_id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid()))
  );

-- =============================================
-- BACKGROUND TASKS (persistent pipeline task tracking)
-- =============================================

CREATE TABLE IF NOT EXISTS background_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,
    video_id UUID REFERENCES videos(id) ON DELETE SET NULL,
    task_type TEXT NOT NULL DEFAULT 'pipeline',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    message TEXT,
    error_message TEXT,
    started_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bg_tasks_tenant ON background_tasks(tenant_id);
CREATE INDEX IF NOT EXISTS idx_bg_tasks_status ON background_tasks(status) WHERE status IN ('pending', 'running');
CREATE INDEX IF NOT EXISTS idx_bg_tasks_video ON background_tasks(video_id, status);

ALTER TABLE background_tasks ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Tenant isolation" ON background_tasks FOR ALL TO authenticated
  USING (tenant_id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid())));


-- =============================================
-- SEED DATA
-- =============================================

INSERT INTO tenants (name, slug) VALUES ('Economy FastForward', 'eff');
INSERT INTO accounts (id, email, display_name) VALUES ('00000000-0000-0000-0000-000000000001', 'dev@local', 'Dev User');
