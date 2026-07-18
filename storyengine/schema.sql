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
  -- Idempotent render billing (migration 057): high-water mark of render
  -- minutes already charged for THIS video. A re-render (edit/retry) only
  -- charges the delta above this, so one deliverable isn't billed repeatedly.
  render_minutes_charged NUMERIC(10,2) NOT NULL DEFAULT 0,
  -- Output shape, chosen at creation, flows through image/clip gen + render.
  aspect_ratio TEXT NOT NULL DEFAULT '16:9' CHECK (aspect_ratio IN ('16:9', '9:16')),
  -- Clip quality, chosen at creation; passed to the clip generator (migration 064).
  video_resolution TEXT NOT NULL DEFAULT '720p' CHECK (video_resolution IN ('480p', '720p')),
  -- Creation-time pipeline toggles (migrations 052, 054). skip_voice drops the
  -- narration stage. pipeline_stages is the per-video plan: the set of enabled
  -- user-facing stages (research, script, voice, images, sound, video,
  -- thumbnail, render, upload) in chain order — NULL = run the full pipeline.
  skip_voice BOOLEAN NOT NULL DEFAULT false,
  pipeline_stages JSONB,
  -- True when the default autobuild chain skipped the optional research stage
  -- for this video (migration 086) — drives the "Research: skipped — Run
  -- research" transparency chip. Cleared back to false once research actually
  -- runs. Static-documentary videos always research first and never set this.
  research_skipped BOOLEAN DEFAULT false,

  -- Drive / YouTube
  final_video_url TEXT,
  drive_folder_link TEXT,
  drive_folder_id TEXT,
  -- Script <-> Drive sync mirror (migration 053): the app-created Google Doc
  -- holding the editable script, plus when we last synced and the Doc's Drive
  -- modifiedTime as of that sync (for "Drive has newer edits" detection).
  drive_script_doc_id TEXT,
  drive_script_synced_at TIMESTAMPTZ,
  drive_script_doc_modified_at TIMESTAMPTZ,
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
  dialogue_audio TEXT,  -- 'voice_over' (default) | 'grok_native'

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
  assigned_dialogue TEXT,  -- coverage-assigned spoken line for a speaking shot (migration 065)
  assigned_video_duration NUMERIC,
  estimated_clip_cost NUMERIC,
  -- WHICH image model actually drew this picture (migration 084): 'gpt-image-2',
  -- 'nano-banana-2', 'z-image', or NULL for pre-migration rows. May differ from
  -- videos.image_model_override when a content-policy/failure fallback fired.
  image_model TEXT,

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

  -- Extended video DNA (migration 038)
  comment_count INTEGER,
  channel_subscriber_count INTEGER,
  like_ratio NUMERIC,              -- likes / views
  comment_ratio NUMERIC,           -- comments / views
  views_per_sub_ratio NUMERIC,     -- views / channel_subs (virality signal)
  published_day_of_week INTEGER,   -- 0=Monday, 6=Sunday
  published_hour INTEGER,          -- 0-23 UTC
  has_chapters BOOLEAN DEFAULT false,
  chapter_count INTEGER DEFAULT 0,
  chapter_titles TEXT,             -- JSON array of chapter names
  tags TEXT,                       -- JSON array of video tags
  thumbnail_analyzed_at TIMESTAMPTZ,

  -- Distillation tracking
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

  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
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

  -- Onboarding wizard (migration 035)
  user_type TEXT,
  onboarding_step INTEGER DEFAULT 0,
  onboarding_completed_at TIMESTAMPTZ,
  style_description TEXT,

  -- Durable creator brief from chat onboarding (migration 061):
  -- {intent, goals, niche_angle, channel, competitors} — hydrated into every new
  -- chat conversation so the producer stays channel-aware across sessions.
  creator_brief JSONB DEFAULT '{}'::jsonb,

  -- YouTube connection (migration 035)
  youtube_channel_id TEXT,
  youtube_channel_name TEXT,
  youtube_refresh_token TEXT,

  -- Google Drive storage
  google_drive_folder_id TEXT,
  google_drive_folder_name TEXT,
  google_drive_refresh_token TEXT,

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
  trial_warning_sent BOOLEAN DEFAULT FALSE,
  trial_expired_handled BOOLEAN DEFAULT FALSE,
  -- Email verification (migration 059). New password signups must confirm before
  -- generating; existing accounts grandfathered true; Google signups set true in code.
  email_verified BOOLEAN NOT NULL DEFAULT false,
  email_verification_token TEXT,
  email_verification_expires TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_accounts_trial_expired_unhandled
  ON accounts (trial_ends_at)
  WHERE trial_expired_handled IS NOT TRUE AND stripe_subscription_id IS NULL;

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

-- Actual-spend receipt table backing videos.total_cost (migration 087,
-- checklist §0.3/C07). One row per completed paid-generation unit (clips
-- first; images/voice/thumbnail/sound land in C08). total_cost is always a
-- recompute of SUM(actual_cost) for the video — see
-- backend/generation_ledger.py::record_ledger_entry(). RLS enabled with no
-- policies (backend connects as postgres, bypasses RLS) — same pattern as
-- migration 083.
CREATE TABLE generation_ledger (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) NOT NULL,
  video_id UUID REFERENCES videos(id) ON DELETE CASCADE NOT NULL,
  stage TEXT NOT NULL,
  model TEXT,
  units NUMERIC NOT NULL DEFAULT 1,
  unit_cost NUMERIC NOT NULL DEFAULT 0,
  actual_cost NUMERIC NOT NULL DEFAULT 0,
  kie_task_id TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE generation_ledger ENABLE ROW LEVEL SECURITY;
-- No policies (deny-all to anon/authenticated/PostgREST) — same reasoning as
-- `secrets` above: the backend connects as postgres (BYPASSRLS), so app
-- access is unaffected; this only closes the direct-PostgREST/browser path.

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
-- Composite hot-path indexes (migration 058) — pipeline filters assets by
-- (video_id, status) and (video_id, scene, image_index), scripts by (video_id, tenant_id).
CREATE INDEX idx_assets_video_status ON assets(video_id, status);
CREATE INDEX idx_assets_video_scene ON assets(video_id, scene, image_index);
CREATE INDEX idx_scripts_video_tenant ON scripts(video_id, tenant_id);
CREATE INDEX idx_competitor_channels_tenant ON competitor_channels(tenant_id);
CREATE INDEX idx_competitor_videos_tenant ON competitor_videos(tenant_id);
CREATE INDEX idx_competitor_videos_airtable ON competitor_videos(airtable_record_id);
CREATE INDEX idx_learnings_tenant ON learnings(tenant_id);
CREATE INDEX idx_learnings_category ON learnings(tenant_id, category);
CREATE INDEX idx_title_insights_tenant ON title_insights(tenant_id);
CREATE INDEX idx_discovery_ideas_tenant ON discovery_ideas(tenant_id);
CREATE INDEX idx_discovery_ideas_status ON discovery_ideas(tenant_id, status, batch_date DESC);
CREATE INDEX idx_bot_activity_tenant ON bot_activity(tenant_id, created_at DESC);
CREATE INDEX idx_stage_transitions_video ON stage_transitions(video_id);
CREATE INDEX idx_generation_ledger_video ON generation_ledger(video_id);
CREATE INDEX idx_generation_ledger_tenant_created ON generation_ledger(tenant_id, created_at);
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

-- Stripe webhook idempotency (migration 056). Dedup record per delivered event.
CREATE TABLE stripe_events (
  event_id     TEXT PRIMARY KEY,
  event_type   TEXT,
  processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

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
    created_at TIMESTAMPTZ DEFAULT now(),
    job_id TEXT,
    attempt INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_bg_tasks_tenant ON background_tasks(tenant_id);
CREATE INDEX IF NOT EXISTS idx_bg_tasks_status ON background_tasks(status) WHERE status IN ('pending', 'running');
CREATE INDEX IF NOT EXISTS idx_bg_tasks_video ON background_tasks(video_id, status);
CREATE INDEX IF NOT EXISTS idx_bg_tasks_created_at ON background_tasks(created_at DESC);

ALTER TABLE background_tasks ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Tenant isolation" ON background_tasks FOR ALL TO authenticated
  USING (tenant_id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid())));


-- =============================================
-- NICHE META-INSIGHTS (Second-Order Distillation)
-- =============================================

CREATE TABLE niche_meta_insights (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  generated_at TIMESTAMPTZ DEFAULT now(),
  sample_size INTEGER DEFAULT 0,
  meta_report TEXT,
  structured_insights JSONB,
  top_hook_types JSONB,
  top_thumbnail_patterns JSONB,
  top_title_structures JSONB,
  optimal_timing JSONB,
  niche_signature JSONB
);

CREATE UNIQUE INDEX idx_nmi_tenant_unique ON niche_meta_insights(tenant_id);

ALTER TABLE niche_meta_insights ENABLE ROW LEVEL SECURITY;
CREATE POLICY niche_meta_insights_tenant_isolation ON niche_meta_insights
  FOR ALL TO authenticated
  USING (
    tenant_id IN (
      SELECT m.tenant_id FROM memberships m
      WHERE m.user_id = (SELECT auth.uid())
    )
    OR tenant_id = current_setting('app.tenant_id', true)::uuid
  );


-- =============================================
-- VISUAL STYLES (migration 010 — user-creatable visual style presets)
-- =============================================

CREATE TABLE visual_styles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID REFERENCES projects(id) ON DELETE CASCADE NOT NULL,

  name TEXT NOT NULL,
  style_profile JSONB NOT NULL,
  reference_image_url TEXT,
  is_active BOOLEAN DEFAULT false,
  is_default BOOLEAN DEFAULT false,

  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_visual_styles_project ON visual_styles(project_id);
CREATE INDEX idx_visual_styles_active ON visual_styles(project_id, is_active) WHERE is_active = true;

ALTER TABLE visual_styles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Project owner access" ON visual_styles FOR ALL TO authenticated
  USING (project_id IN (
    SELECT p.id FROM projects p
    WHERE p.account_id = (SELECT auth.uid())
       OR p.tenant_id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid()))
  ));


-- =============================================
-- STYLE CHARACTERS (migration 010 — characters within a visual style)
-- =============================================

CREATE TABLE style_characters (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  visual_style_id UUID REFERENCES visual_styles(id) ON DELETE CASCADE NOT NULL,

  name TEXT NOT NULL,
  image_url TEXT NOT NULL,
  sort_order INTEGER DEFAULT 0,

  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_style_characters_style ON style_characters(visual_style_id);

ALTER TABLE style_characters ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Style owner access" ON style_characters FOR ALL TO authenticated
  USING (visual_style_id IN (
    SELECT vs.id FROM visual_styles vs
    JOIN projects p ON vs.project_id = p.id
    WHERE p.account_id = (SELECT auth.uid())
       OR p.tenant_id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid()))
  ));


-- =============================================
-- NOTIFICATION PREFERENCES (migration 031 — per-tenant email toggles)
-- =============================================

CREATE TABLE notification_preferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE UNIQUE NOT NULL,
    email_weekly_digest BOOLEAN DEFAULT true,
    email_video_complete BOOLEAN DEFAULT true,
    email_error_alerts BOOLEAN DEFAULT true,
    email_ctr_alerts BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);


-- =============================================
-- SEED DATA
-- =============================================

INSERT INTO tenants (name, slug) VALUES ('Economy FastForward', 'eff');
INSERT INTO accounts (id, email, display_name) VALUES ('00000000-0000-0000-0000-000000000001', 'dev@local', 'Dev User');


-- =============================================
-- VIDEO CHARACTERS (per-video character design — migration 046)
-- Designed/uploaded character references, approved before storyboards;
-- approved refs feed Nano Banana image_input for consistency.
-- =============================================
CREATE TABLE video_characters (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,
  video_id UUID REFERENCES videos(id) ON DELETE CASCADE NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  reference_url TEXT,
  status TEXT DEFAULT 'draft' CHECK (status IN ('draft', 'approved')),
  source TEXT DEFAULT 'generated' CHECK (source IN ('generated', 'uploaded', 'project')),
  sort INT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_video_characters_video ON video_characters(video_id);
CREATE INDEX idx_video_characters_tenant ON video_characters(tenant_id);

ALTER TABLE video_characters ENABLE ROW LEVEL SECURITY;
CREATE POLICY video_characters_tenant_isolation ON video_characters
  FOR ALL TO authenticated
  USING (
    tenant_id IN (
      SELECT m.tenant_id FROM memberships m
      WHERE m.user_id = (SELECT auth.uid())
    )
    OR tenant_id = current_setting('app.tenant_id', true)::uuid
  );
-- videos.characters_approved_at TIMESTAMPTZ added by migration 046

-- videos.story_locked_at TIMESTAMPTZ (storyboard lock gate) added by migration 047
-- scripts.storyboard_on_off DEFAULT 'On' as of migration 047


-- =============================================
-- VIDEO ENVIRONMENTS (per-video location design — migration 051)
-- Mirror of video_characters but for LOCATIONS. One approved reference
-- image per Story Bible location; at grid time the beat's location is
-- passed as a second image_input (alongside the cast sheet) so the setting
-- stays consistent across panels. name == story_bible.locations[].id.
-- =============================================
CREATE TABLE video_environments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,
  video_id UUID REFERENCES videos(id) ON DELETE CASCADE NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  reference_url TEXT,
  status TEXT DEFAULT 'draft' CHECK (status IN ('draft', 'approved')),
  source TEXT DEFAULT 'generated' CHECK (source IN ('generated', 'uploaded', 'project')),
  sort INT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_video_environments_video ON video_environments(video_id);
CREATE INDEX idx_video_environments_tenant ON video_environments(tenant_id);

ALTER TABLE video_environments ENABLE ROW LEVEL SECURITY;
CREATE POLICY video_environments_tenant_isolation ON video_environments
  FOR ALL TO authenticated
  USING (
    tenant_id IN (
      SELECT m.tenant_id FROM memberships m
      WHERE m.user_id = (SELECT auth.uid())
    )
    OR tenant_id = current_setting('app.tenant_id', true)::uuid
  );
-- videos.environments_approved_at TIMESTAMPTZ added by migration 051
-- assets.location_id TEXT (structured per-panel location) added by migration 051


-- =============================================
-- CHAT CONVERSATIONS (chat-first creative producer — migration 060)
-- One row per conversation; the whole transcript lives in a JSONB array
-- (no second table, no joins). state.last_spec holds the approval-pending
-- production spec; video_id is set once the conversation creates a video.
-- =============================================
CREATE TABLE chat_conversations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,
  project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
  video_id UUID REFERENCES videos(id) ON DELETE SET NULL,
  transcript JSONB NOT NULL DEFAULT '[]'::jsonb,
  state JSONB NOT NULL DEFAULT '{}'::jsonb,
  phase TEXT NOT NULL DEFAULT 'asking',
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_chat_conversations_tenant ON chat_conversations(tenant_id);

ALTER TABLE chat_conversations ENABLE ROW LEVEL SECURITY;
CREATE POLICY chat_conversations_tenant_isolation ON chat_conversations
  FOR ALL TO authenticated
  USING (
    tenant_id IN (
      SELECT m.tenant_id FROM memberships m
      WHERE m.user_id = (SELECT auth.uid())
    )
    OR tenant_id = current_setting('app.tenant_id', true)::uuid
  );


-- =============================================================================
-- LIVE SCHEMA ADDENDUM (regenerated 2026-07-17 — C01a schema hygiene, S6 sweep)
--
-- Everything above this line was hand-maintained and had drifted from prod:
-- it was missing the 11 tables below (created by migrations 041-081) and it
-- declared a `title_tests` table that was removed from this file because it
-- has never existed live and had zero code references.
--
-- This addendum was generated by introspecting the LIVE Supabase project
-- (wrromlupsmyzrrcqlucn) via information_schema.columns / pg_indexes /
-- pg_policies — it is not hand-written. This file is documentation only:
-- the app never executes schema.sql (see storyengine/backend/main.py
-- _run_pending_migrations(), which only runs migrations/*.sql, tracked in
-- the `_migrations` table). Treat this as a periodic snapshot, not a source
-- of truth to diff against for new work — migrations/*.sql is that source.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- INTELLIGENCE_REPORTS (migration 041_onboarding_intelligence.sql)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS intelligence_reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,
  report_type TEXT DEFAULT 'onboarding',
  title_ideas JSONB,
  thumbnail_insights JSONB,
  hook_ideas JSONB,
  channel_analysis JSONB,
  competitors_analyzed INTEGER DEFAULT 0,
  videos_analyzed INTEGER DEFAULT 0,
  creation_guidance JSONB,  -- added by migration 045_intelligence_creation_guidance.sql
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_intelligence_reports_tenant ON intelligence_reports(tenant_id);

ALTER TABLE intelligence_reports ENABLE ROW LEVEL SECURITY;
-- Tenant-isolation policy added by migration 048_tenant_rls_core_tables.sql
CREATE POLICY tenant_id_isolation ON intelligence_reports FOR ALL TO authenticated
  USING (
    tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
    OR tenant_id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid()))
  );

-- ---------------------------------------------------------------------------
-- CHANNEL_VIDEOS (migration 066_channel_intel.sql + later additions)
-- Shared analytics table for the channel's own YouTube uploads — do not
-- recreate; extend it (see storyengine/CLAUDE.md).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS channel_videos (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,
  video_id TEXT NOT NULL,
  title TEXT,
  published_at TIMESTAMPTZ,
  view_count BIGINT,
  like_count BIGINT,
  comment_count BIGINT,
  duration_seconds INTEGER,
  thumbnail_url TEXT,
  ctr_percent NUMERIC,
  avg_view_duration_seconds INTEGER,
  avg_retention NUMERIC,
  impressions BIGINT,
  transcript TEXT,
  transcript_source TEXT,
  transcript_fetched_at TIMESTAMPTZ,
  privacy_status TEXT,
  watch_time_hours NUMERIC,
  subscribers_gained INTEGER,
  last_synced_at TIMESTAMPTZ,
  internal_video_id UUID REFERENCES videos(id),
  metadata JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(tenant_id, video_id)
);
CREATE INDEX idx_channel_videos_tenant ON channel_videos(tenant_id);
CREATE INDEX idx_channel_videos_published ON channel_videos(tenant_id, published_at DESC);

ALTER TABLE channel_videos ENABLE ROW LEVEL SECURITY;
-- Two RLS policies coexist live (both apply, OR'd) — a public-role tenant
-- check plus the standard authenticated/membership check. Reflected as-is,
-- not de-duplicated, since this file is a snapshot, not something applied.
CREATE POLICY channel_videos_tenant_isolation ON channel_videos FOR ALL
  USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY tenant_id_isolation ON channel_videos FOR ALL TO authenticated
  USING (
    tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
    OR tenant_id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid()))
  );

-- ---------------------------------------------------------------------------
-- SECRETS (vault.py::_ensure_secrets_table() — in-process CREATE TABLE IF
-- NOT EXISTS, now also tracked via migrations/082_untracked_ad_hoc_tables.sql)
-- Tenant scoping is a `tenant_id:name` string convention inside `name`, not
-- a tenant_id column + RLS policy (deliberate design, see vault.py).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS secrets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT UNIQUE NOT NULL,
  value TEXT NOT NULL,
  description TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE secrets ENABLE ROW LEVEL SECURITY;
-- No policies (deny-all to anon/authenticated/PostgREST). The backend
-- connects as the table owner (postgres, BYPASSRLS) so app access is
-- unaffected; this only closes the direct-PostgREST/browser-client path.

-- ---------------------------------------------------------------------------
-- CHANNEL_PROFILE_DOCUMENTS (migration 046_channel_profile_documents.sql)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS channel_profile_documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,
  doc_type TEXT NOT NULL,
  title TEXT NOT NULL,
  drive_file_id TEXT NOT NULL,
  drive_url TEXT NOT NULL,
  drive_folder_id TEXT,
  source_counts JSONB DEFAULT '{}'::jsonb,
  metadata JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(tenant_id, doc_type)
);
CREATE INDEX idx_channel_profile_documents_tenant ON channel_profile_documents(tenant_id);

ALTER TABLE channel_profile_documents ENABLE ROW LEVEL SECURITY;
CREATE POLICY channel_profile_documents_tenant_isolation ON channel_profile_documents FOR ALL
  USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- ---------------------------------------------------------------------------
-- CHAT_ASSETS (migration 073_chat_assets.sql; video_id added in 085_chat_assets_video_id.sql)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_assets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  conversation_id UUID,
  video_id UUID,  -- set when the file was dropped into a video's docked co-pilot (NULL = home chat)
  kind TEXT NOT NULL,
  filename TEXT,
  content_type TEXT,
  storage_url TEXT,
  parsed JSONB,
  parsed_text TEXT,
  summary TEXT,
  status TEXT NOT NULL DEFAULT 'uploaded',
  filed_as TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_chat_assets_tenant_conv ON chat_assets(tenant_id, conversation_id);
CREATE INDEX idx_chat_assets_tenant_video ON chat_assets(tenant_id, video_id);

ALTER TABLE chat_assets ENABLE ROW LEVEL SECURITY;
-- RLS enabled live with zero policies (deny-all to anon/authenticated);
-- the FastAPI backend reads/writes as the bypassing owner role.

-- ---------------------------------------------------------------------------
-- PRODUCTION_QUEUE (migration 074_production_queue.sql)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS production_queue (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  "position" INTEGER NOT NULL,
  title TEXT NOT NULL,
  framework_angle TEXT,
  writer_guidance TEXT,
  user_script TEXT,
  script_template_id UUID,
  source_asset_id UUID,
  status TEXT NOT NULL DEFAULT 'queued',
  video_id UUID,
  launched_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_prod_queue_tenant ON production_queue(tenant_id, status, "position");

ALTER TABLE production_queue ENABLE ROW LEVEL SECURITY;
-- RLS enabled live with zero policies (deny-all to anon/authenticated).

-- ---------------------------------------------------------------------------
-- SCRIPT_TEMPLATES (migration 076_script_templates.sql)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS script_templates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  name TEXT NOT NULL,
  structure TEXT NOT NULL,
  example_excerpt TEXT,
  source_asset_id UUID,
  is_default BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_script_templates_tenant ON script_templates(tenant_id);

ALTER TABLE script_templates ENABLE ROW LEVEL SECURITY;
-- RLS enabled live with zero policies (deny-all to anon/authenticated).

-- ---------------------------------------------------------------------------
-- CHANNEL_ANALYTICS_DAILY (migration 070_channel_identity.sql or nearby)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS channel_analytics_daily (
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,
  date DATE NOT NULL,
  views INTEGER DEFAULT 0,
  impressions BIGINT,
  ctr NUMERIC,
  watch_time_minutes NUMERIC,
  avg_view_duration_seconds NUMERIC,
  subscribers_gained INTEGER,
  subscribers_lost INTEGER,
  PRIMARY KEY (tenant_id, date)
);

ALTER TABLE channel_analytics_daily ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_id_isolation ON channel_analytics_daily FOR ALL TO authenticated
  USING (
    tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
    OR tenant_id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid()))
  );

-- ---------------------------------------------------------------------------
-- STATIC_REFERENCE_CACHE (static_docu.py — in-process CREATE TABLE IF NOT
-- EXISTS, now also tracked via migrations/082_untracked_ad_hoc_tables.sql)
-- Real tenant_id column — RLS closed by migrations/083_enable_rls_ad_hoc_tables.sql (C01a).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS static_reference_cache (
  tenant_id UUID NOT NULL,
  machine_key TEXT NOT NULL,
  machine TEXT,
  hosted_url TEXT NOT NULL,
  source_url TEXT,
  verified_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (tenant_id, machine_key)
);

ALTER TABLE static_reference_cache ENABLE ROW LEVEL SECURITY;
-- No policies (deny-all to anon/authenticated/PostgREST); backend bypasses
-- via table ownership + BYPASSRLS (see migration 083 for the proof).

-- ---------------------------------------------------------------------------
-- CHANNEL_VIDEO_RETENTION (migration 080_video_retention.sql)
-- Opt-in per-channel cap for complete StoryEngine video records.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS channel_video_retention (
  tenant_id UUID PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
  max_videos INTEGER NOT NULL CHECK (max_videos > 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE channel_video_retention ENABLE ROW LEVEL SECURITY;
-- No policies (deny-all to anon/authenticated/PostgREST); backend bypasses
-- via table ownership + BYPASSRLS (see migration 083 for the proof).

-- ---------------------------------------------------------------------------
-- MACHINE_RESEARCH_CARDS (migration 081_machine_research_cards.sql)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS machine_research_cards (
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  video_id UUID NOT NULL,
  machine_key TEXT NOT NULL,
  machine_name TEXT NOT NULL,
  roster_index INTEGER NOT NULL,
  card JSONB NOT NULL,
  validation JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- Live composite FK ties (tenant_id, video_id) to videos(tenant_id, id);
  -- simplified here to a single-column reference for readability.
  FOREIGN KEY (video_id) REFERENCES videos(id) ON DELETE CASCADE,
  PRIMARY KEY (tenant_id, video_id, machine_key),
  UNIQUE (tenant_id, video_id, roster_index)
);
CREATE INDEX machine_research_cards_video_order_idx
  ON machine_research_cards(tenant_id, video_id, roster_index);

ALTER TABLE machine_research_cards ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Tenant isolation" ON machine_research_cards FOR ALL TO authenticated
  USING (tenant_id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid())));
