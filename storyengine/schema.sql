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
  -- Editorial-voice pick (migration 098, checklist §2.3/C24): a profile id
  -- from shared.profiles.script (neutral_v1 default, or the opt-in
  -- power_doctrine_v1/v2), written by the New Video "Advanced" select, the
  -- Script tab, or the copilot's "write it in the investigative style".
  -- NULL = no explicit pick, so pipeline_executor.py's
  -- _resolve_script_profile_id falls back to "neutral_v1" — the SAME
  -- default shared.profiles.script.load_script_profile() already uses when
  -- SCRIPT_PROFILE is unset. No FK (unlike style_preset_id): the catalog is
  -- a small code-reviewed registry, not admin-mutable data — same
  -- rationale as assets.camera_preset_id (migration 097).
  script_profile TEXT,
  seo_description TEXT,
  seo_tags TEXT,
  seo_hashtags TEXT,
  -- YouTube videoCategory id computed by generate_and_store_seo() (migration
  -- 102, checklist §S10.6/C34c) from the video's own title+script — persisted
  -- so upload_video_to_youtube() can actually pass it through instead of
  -- always shipping the hardcoded _DEFAULT_CATEGORY ("27" — Education). NULL
  -- (SEO never generated) falls back to _DEFAULT_CATEGORY at upload time.
  seo_category_id TEXT,

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
  -- FK to style_presets(id) added further down (migration 096/C20) — that
  -- table is defined later in this file; schema.sql is run top-to-bottom
  -- on a fresh DB (see header), so the constraint is attached via ALTER
  -- TABLE right after style_presets exists, not inline here.
  style_preset_id TEXT,
  -- High-level production shape (migration 121), separate from visual look.
  -- The selected public row is snapshotted so later catalog revisions never
  -- mutate an in-flight or completed video.
  production_style_id TEXT,
  production_style_version INTEGER,
  production_style_snapshot JSONB,
  -- Custom Film points at one immutable instantiated plan revision. NULL on
  -- every legacy/single-profile video. Approval is a future exact-hash gate;
  -- migration 122 adds storage only and does not approve or dispatch work.
  custom_film_plan_id UUID,
  custom_film_plan_revision INTEGER,
  custom_film_plan_hash TEXT,
  custom_film_quote_inputs_hash TEXT,
  custom_film_approval_hash TEXT,
  custom_film_approved_at TIMESTAMPTZ,
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
  -- migration 116: who set the current skip_voice value — 'auto' (dialogue
  -- detector, bidirectional with its own re-classification) | 'manual'
  -- (creator action, never auto-reverted) | NULL (legacy row, treated as
  -- manual). See migration 116 for the full rationale.
  skip_voice_source TEXT CHECK (skip_voice_source IN ('auto', 'manual')),
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
  -- Per-launch pattern flywheel write-once marker (migration 110, C56):
  -- when this video's analytics (ctr populated + impressions >= 1000, the
  -- SAME bar routes/learning_extraction.py::extract_learnings() uses)
  -- first mature, this stamps so the channel-wide outlier scan only ever
  -- runs once for this video, not on every sync.
  launch_pattern_analyzed_at TIMESTAMPTZ,
  -- Early-warning launch classifier (migration 111, C58): 'ok' | 'watch' |
  -- 'underperforming', comparing this video's ctr_48h write-once snapshot
  -- against the channel's OWN historical ctr_48h distribution at the SAME
  -- 48h milestone. early_signal_at is a write-once marker (NULL = not yet
  -- classified, either too early or too little channel history to trust a
  -- median -- both retry on a later sync, never guessed). Read-only signal
  -- -- never trips the kill switch, never touches spend. See
  -- backend/early_warning.py.
  early_signal TEXT,
  early_signal_evidence JSONB,
  early_signal_at TIMESTAMPTZ,

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
  -- C13b: the channel's declared LOOK — 'animated' | 'realistic' | NULL
  -- (undeclared, the default for every video today). Gates shared.
  -- model_router.route_shot_model()'s per-shot recommendations to models
  -- whose ModelProfile.styles include this value; NULL turns tier-upgrade
  -- routing OFF and returns video_model unchanged (money-safe default).
  -- Migration 089.
  render_style TEXT,

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
  -- Optional per-video spend ceiling (migration 103, checklist §3.3/C36).
  -- NULL = no cap (default, byte-identical to pre-migration behavior). The
  -- money gate (actions.py's cost estimator + the chat autobuild loop)
  -- refuses/pauses a paid verb whose quote would push total_cost over this —
  -- never silently, always with an honest quote the human can override.
  max_spend NUMERIC,

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

  -- Per-scene/shot video-model routing (migration 088, checklist §1.2/C12):
  -- routed_model + routing_reason are computed at shot-plan time (storyboard/
  -- coverage.py's plan_camera_moves(), via shared.model_router) and persisted
  -- by store_scene(). model_used stays NULL until C13 wires clip generation
  -- to record which model actually ran. All nullable — pre-migration rows
  -- and any write path other than store_scene() simply leave them NULL.
  routed_model TEXT,
  routing_reason TEXT,
  model_used TEXT,
  -- Explicit per-scene creator override (migration 090, checklist §1.2/C14):
  -- NULL = no manual override, so resolve_clip_model() falls through to
  -- routed_model then the video's own video_model, unchanged from C13.
  model_override TEXT,
  -- Explicit per-shot camera-move override (migration 097, checklist §2.2/
  -- C23): a catalog id from image_prompts.engine.camera_moves, written by
  -- PATCH /api/assets/{id}/camera-preset. NULL = no manual pick, so clip
  -- generation keeps composing the motion prompt from the auto/"earned"
  -- camera_movement exactly as before this migration.
  camera_preset_id TEXT,
  -- STS voice-lock marker (migration 114): the clip's audio already carries
  -- this shot's spoken line in the pinned cast voice at the clip's own timing
  -- (ElevenLabs speech-to-speech over the Grok take). The performance
  -- assembler must NOT overlay the TTS line for spans this shot claims;
  -- clip_speech_start/end (seconds into the clip) size its window instead.
  carries_own_line BOOLEAN NOT NULL DEFAULT false,
  clip_speech_start REAL,
  clip_speech_end REAL,
  -- Motion-prompt gate BLOCK marker (migration 118, fail-closed code law):
  -- 'blocked' when scripts/coverage_to_app.py's motion-prompt gate rejected
  -- this shot's line twice (write + one repair retry) and video_prompt was
  -- left NULL rather than auto-substituting fallback text — the reason
  -- lives in a bot_activity row, not here. NULL = no block (default).
  -- run_clip_generation (pipeline_executor.py) skips a 'blocked' or
  -- promptless row with zero spend; saving a human-edited video_prompt via
  -- PATCH /api/assets/{id}/video-prompt clears this back to NULL.
  motion_gate_status TEXT,

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
  -- Autopilot dial (migration 107, checklist C50) — see that migration's
  -- header comment for the full semantics (dial_level's autonomy levels,
  -- and why kill_switch_* is distinct from `enabled`).
  dial_level TEXT NOT NULL DEFAULT 'propose_only'
    CHECK (dial_level IN ('propose_only', 'auto_draft', 'full_auto')),
  weekly_budget_cap NUMERIC,
  weekly_spend_reset_at TIMESTAMPTZ,
  kill_switch_tripped_at TIMESTAMPTZ,
  kill_switch_reason TEXT,
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

  -- Optional channel default from the global public production-style catalog.
  production_style_id TEXT,

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
  -- Beta access code redeemed at signup (migration 119), NULL if none —
  -- see backend/routes/google_auth.py::register() and beta_codes below.
  beta_code TEXT,
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
-- One scripts row per (video, scene) — migration 117. Partial: Airtable-era
-- rows may have scene NULL (backfilled at read time), so those stay exempt.
CREATE UNIQUE INDEX scripts_video_scene_unique ON scripts(video_id, scene) WHERE scene IS NOT NULL;
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
-- Dedup backstop (migration 093 / C16c, S7-5 HIGH): a double-spend race that
-- fires the same provider task's ledger write twice must be refused, not
-- recorded twice. Partial — rows with kie_task_id IS NULL (most stages
-- today) are NEVER deduped by this index; see migration 093's header for
-- the full per-stage audit of which stages carry a real task id.
CREATE UNIQUE INDEX generation_ledger_dedup_idx
  ON generation_ledger (video_id, stage, kie_task_id)
  WHERE kie_task_id IS NOT NULL;
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
    attempt INTEGER NOT NULL DEFAULT 1,
    runtime_envelope JSONB,
    runtime_progress JSONB,
    CONSTRAINT background_tasks_tenant_video_job_uidx
      UNIQUE (tenant_id, video_id, job_id),
    CONSTRAINT background_tasks_custom_film_runtime_envelope_check CHECK (
      task_type <> 'custom_film_runtime'
      OR (
        runtime_envelope IS NOT NULL
        AND jsonb_typeof(runtime_envelope) = 'object'
        AND runtime_envelope->>'runtime_version' = 'custom-film-runtime-v1'
        AND runtime_envelope->>'runtime_hash' ~ '^[0-9a-f]{64}$'
        AND runtime_envelope->>'approval_hash' ~ '^[0-9a-f]{64}$'
        AND jsonb_typeof(runtime_envelope->'sections') = 'array'
        AND jsonb_typeof(runtime_envelope->'stage_plan') = 'array'
      )
    ),
    CONSTRAINT background_tasks_custom_film_runtime_progress_check CHECK (
      runtime_progress IS NULL
      OR (
        task_type = 'custom_film_runtime'
        AND jsonb_typeof(runtime_progress) = 'object'
        AND runtime_progress ? 'last_stage_key'
        AND runtime_progress ? 'in_flight'
        AND runtime_progress->>'runtime_hash' ~ '^[0-9a-f]{64}$'
        AND jsonb_typeof(runtime_progress->'completed_stage_keys') = 'array'
        AND (
          runtime_progress->'last_stage_key' = 'null'::jsonb
          OR jsonb_typeof(runtime_progress->'last_stage_key') = 'string'
        )
        AND (
          runtime_progress->'in_flight' = 'null'::jsonb
          OR (
            jsonb_typeof(runtime_progress->'in_flight') = 'object'
            AND runtime_progress->'in_flight'->>'stage_key' <> ''
            AND runtime_progress->'in_flight'->>'operation_id'
              ~ '^custom-film-op:[0-9a-f]{64}$'
            AND runtime_progress->'in_flight'->>'state' = 'started'
          )
        )
      )
    )
);

CREATE INDEX IF NOT EXISTS idx_bg_tasks_tenant ON background_tasks(tenant_id);
CREATE INDEX IF NOT EXISTS idx_bg_tasks_status ON background_tasks(status) WHERE status IN ('pending', 'running');
CREATE INDEX IF NOT EXISTS idx_bg_tasks_video ON background_tasks(video_id, status);
CREATE INDEX IF NOT EXISTS idx_bg_tasks_created_at ON background_tasks(created_at DESC);
-- migration 094 (checklist C16d — S7-8 LOW fix): partial UNIQUE backstop
-- behind db_persist_task()'s check-then-insert race on the "pending" branch.
-- NULL job_id (the in-process fallback path) is never deduped.
CREATE UNIQUE INDEX IF NOT EXISTS background_tasks_job_id_uidx ON background_tasks(job_id) WHERE job_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS background_tasks_custom_film_approval_idx
  ON background_tasks (
    tenant_id,
    video_id,
    (runtime_envelope->>'approval_hash')
  )
  WHERE task_type = 'custom_film_runtime';

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
  props JSONB,  -- migration 115: canonical {name, position} prop manifest, authored once at approval
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

-- ---------------------------------------------------------------------------
-- DIRECTOR_PREFERENCES (migration 091_director_preferences.sql, checklist
-- C15c — "Director memory: durable preference store"). A correction said
-- once ("the kitten is gray", "never use premium models on Poco") becomes a
-- STANDING preference remembered across future conversations and videos,
-- instead of only living in that one transcript.
--
-- scope: the literal string 'channel' (applies everywhere for this tenant)
--        or a video_id's text form (applies only inside that one video's
--        copilot chat).
-- source: 'user' always for this chunk (explicit corrections only, no
--        auto-learning) — reserved for a future inferred-preference path.
-- active: soft-delete only ("forget that" flips this false; never hard-deleted).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS director_preferences (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  scope TEXT NOT NULL DEFAULT 'channel',
  text TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'user',
  active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_director_preferences_tenant_scope_active
  ON director_preferences(tenant_id, scope, active, created_at DESC);

ALTER TABLE director_preferences ENABLE ROW LEVEL SECURITY;
-- No policies (deny-all to anon/authenticated/PostgREST); backend bypasses
-- via table ownership + BYPASSRLS (see migration 083 for the proof).

-- ---------------------------------------------------------------------------
-- GENERATION_CLAIMS (migration 092_generation_claims.sql, checklist C16a —
-- S7-1 CRITICAL + S7-6 MED fix). DB-backed concurrency lock: both the
-- chat-driven autobuild/copilot dispatch (routes/chat.py) and the manual
-- routes/pipeline.py (+ videos.py/environments.py/characters.py) endpoints
-- acquire a row here before dispatching paid generation, and release it in
-- a finally block when the run ends — so a double-tap/retry can't run two
-- concurrent paid generation loops on the same video, and a claim survives
-- a backend restart (unlike the in-process _running_tasks/_side_lanes
-- dicts it now backstops). See backend/generation_claims.py.
--
-- stage: "main" (the exclusive full-pipeline lane) or one of the
--   independent side lanes (voice/characters/environments/thumbnail) —
--   mirrors routes/pipeline.py's existing lane vocabulary exactly.
-- claimed_at: a claim older than 2 hours is stale and gets swept + retaken
--   (a crashed run must never wedge a video for good).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS generation_claims (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
  stage TEXT NOT NULL,
  claimed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  claimed_by TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS generation_claims_unique
  ON generation_claims (tenant_id, video_id, stage);

ALTER TABLE generation_claims ENABLE ROW LEVEL SECURITY;
-- No policies (deny-all to anon/authenticated/PostgREST); backend bypasses
-- via table ownership + BYPASSRLS (see migration 083 for the proof).

-- ---------------------------------------------------------------------------
-- GENERATION_PASSES (migration 095_generation_passes.sql, checklist C17 —
-- §1.3 "Draft cheap, finish expensive"). Durable identity for a completed
-- draft_pass/finalize pass — distinct from generation_claims above: the
-- claim guards CONCURRENT double-dispatch and is released the instant a run
-- ends; this table answers "has this EXACT pass already run to completion?"
-- for a SEQUENTIAL repeat that arrives after the claim was already released.
-- See backend/generation_passes.py.
--
-- pass: 'draft_pass' | 'finalize'.
-- scene_set_hash: generation_passes.py::scene_set_hash() — a hash of the
--   sorted (scene, target_model_id) pairs this pass covers, NOT just the
--   scene numbers, so a routing change on an otherwise-identical scene set
--   also counts as a legitimately new pass.
--
-- A row is written ONLY on successful completion (never before dispatch) —
-- a failed run leaves no row, so it stays retryable with the identical
-- scene set. The UNIQUE index is the actual dedup mechanism.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS generation_passes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
  pass TEXT NOT NULL,
  scene_set_hash TEXT NOT NULL,
  completed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS generation_passes_unique
  ON generation_passes (tenant_id, video_id, pass, scene_set_hash);

ALTER TABLE generation_passes ENABLE ROW LEVEL SECURITY;
-- No policies (deny-all to anon/authenticated/PostgREST); backend bypasses
-- via table ownership + BYPASSRLS (see migration 083 for the proof).


-- =============================================================================
-- STYLE_PRESETS (migration 096 — checklist §2.1 [D]+[B], chunk C20)
-- =============================================================================
-- Catalog for the VISUAL_PROFILE axis — the structural image-engine choice
-- (shared.profiles.visual/*.py: scene-type variety, camera/composition
-- cycling, anti-clustering). `id` is the profile MODULE NAME (shared.
-- profiles.visual._PROFILE_MODULES key), so a valid row id is always a
-- value load_profile() already knows how to resolve.
--
-- NOT the same axis as visual_styles (migration 010, above) or the
-- frontend's hardcoded VISUAL_PRESETS (pixar_3d/flat_2d/realistic/anime/
-- watercolor/comic) — those feed VISUAL_STYLE_DESCRIPTION, a free-text
-- aesthetic overlay (image_style_override), a DIFFERENT env seam. See
-- docs/reports/2026-07-17-storyengine-agent-audit-findings.md §S9-5 and
-- SYSTEM_STATE.md §C20 for the reconciliation note (left for C21).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS style_presets (
  id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  description TEXT,
  tags JSONB NOT NULL DEFAULT '[]'::jsonb,
  best_for JSONB NOT NULL DEFAULT '[]'::jsonb,
  cost_tier TEXT,
  preview_url TEXT,
  source TEXT NOT NULL DEFAULT 'python_profile',
  sort INT NOT NULL DEFAULT 0,
  active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE style_presets ENABLE ROW LEVEL SECURITY;
-- No policies (deny-all to anon/authenticated/PostgREST); backend bypasses
-- via table ownership + BYPASSRLS (see migration 083 for the proof). This
-- is a global catalog, not tenant data — no tenant-scoped policy to write.

-- Seed: the 5 real profiles in shared.profiles.visual._PROFILE_MODULES
-- (excludes the "mannequin_storytelling" legacy alias — same module as
-- cinematic_illustration, not a distinct 6th profile). Copied verbatim from
-- each module's TemplateMetadata. See migrations/096_style_presets.sql for
-- the full INSERT ... ON CONFLICT DO UPDATE (idempotent reseed of the
-- code-derived columns only — `active`/`preview_url` stay admin-owned).

-- videos.style_preset_id's FK is attached here (not inline on the `videos`
-- CREATE TABLE far above) because this table is defined later in the file,
-- which is run top-to-bottom on a fresh DB (see file header).
ALTER TABLE videos ADD CONSTRAINT videos_style_preset_id_fkey
  FOREIGN KEY (style_preset_id) REFERENCES style_presets(id) ON DELETE SET NULL;


-- =============================================================================
-- PRODUCTION_STYLE_PROFILES (migration 121 — public pipeline-shape catalog)
-- =============================================================================
-- Distinct from image aesthetics and visual-profile engines. The backend is the
-- only writer; authenticated users read it through /api/production-styles.
CREATE TABLE IF NOT EXISTS production_style_profiles (
  id TEXT PRIMARY KEY,
  version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
  label TEXT NOT NULL,
  description TEXT NOT NULL,
  knobs JSONB NOT NULL,
  estimate JSONB NOT NULL DEFAULT '{}'::jsonb,
  requires_byok BOOLEAN NOT NULL DEFAULT TRUE CHECK (requires_byok),
  public BOOLEAN NOT NULL DEFAULT TRUE,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  sort INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE production_style_profiles ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON production_style_profiles FROM anon;
REVOKE ALL ON production_style_profiles FROM authenticated;

CREATE INDEX IF NOT EXISTS idx_videos_production_style
  ON videos (production_style_id) WHERE production_style_id IS NOT NULL;

INSERT INTO production_style_profiles
  (id, version, label, description, knobs, estimate, requires_byok, public, sort)
VALUES
  (
    'bilingual_character_animation', 1, 'Bilingual Character Animation',
    'Animated character stories with dialogue in two languages and natural dubbed voices.',
    '{"render_mode":"coverage","script_profile":"neutral_v1","visual_profile":"neutral_v1","image_density":{"mode":"dialogue_shape","target_per_minute":8},"animation":{"enabled":true,"mode":"grok_native"},"language":{"mode":"bilingual"},"dubbing":{"enabled":true,"mode":"speech_to_speech"},"segmentation":{"mode":"speaker_turn"},"camera":{"mode":"dialogue_coverage"},"quality_laws":["character_continuity","lip_sync","translation_fidelity"],"image_source":"generate"}'::jsonb,
    '{"cost_tier":"high","image_count_mode":"duration","images_per_minute":8,"clips_per_image":1,"copy":"Animated images + clips + bilingual dubbing. You pay providers directly with your keys."}'::jsonb,
    TRUE, TRUE, 10
  ),
  (
    'simple_language_animation', 1, 'Simple-Language Animation',
    'Simple-language animated stories built for learners and clear comprehension.',
    '{"render_mode":"coverage","script_profile":"neutral_v1","visual_profile":"neutral_v1","image_density":{"mode":"dialogue_shape","target_per_minute":8},"animation":{"enabled":true,"mode":"grok_native"},"language":{"mode":"simple_single_language"},"dubbing":{"enabled":false,"mode":"none"},"segmentation":{"mode":"speaker_turn"},"camera":{"mode":"dialogue_coverage"},"quality_laws":["character_continuity","clear_language","lip_sync"],"image_source":"generate"}'::jsonb,
    '{"cost_tier":"medium","image_count_mode":"duration","images_per_minute":8,"clips_per_image":1,"copy":"Animated images + clips in one clear language. You pay providers directly with your keys."}'::jsonb,
    TRUE, TRUE, 20
  ),
  (
    'photo_documentary', 1, 'Photo Documentary',
    'Item-by-item narration using still images, captions, and slow cinematic pan-and-zoom.',
    '{"render_mode":"static_docu","script_profile":"neutral_v1","visual_profile":"neutral_v1","image_density":{"mode":"per_item","target":3,"minimum":2},"animation":{"enabled":false,"mode":"ken_burns"},"language":{"mode":"narrator"},"dubbing":{"enabled":false,"mode":"none"},"segmentation":{"mode":"item"},"camera":{"mode":"three_complementary_views"},"quality_laws":["verified_reference","variant_accuracy","caption_grounding"],"image_source":"generate"}'::jsonb,
    '{"cost_tier":"low","image_count_mode":"per_item","images_per_item":3,"clips_per_image":0,"copy":"Three still images per item, no generated animation clips. You pay providers directly with your keys."}'::jsonb,
    TRUE, TRUE, 30
  ),
  (
    'animated_investigative_documentary', 1, 'Animated Investigative Documentary',
    'Investigative narration with a fresh animated visual for nearly every sentence or visual cue.',
    '{"render_mode":"coverage","script_profile":"power_doctrine_v2","visual_profile":"cinematic_illustration","image_density":{"mode":"visual_cue","target_per_minute":10},"animation":{"enabled":true,"mode":"grok_native"},"language":{"mode":"narrator"},"dubbing":{"enabled":false,"mode":"none"},"segmentation":{"mode":"visual_cue"},"camera":{"mode":"investigative_coverage"},"quality_laws":["source_grounding","visual_cue_fidelity","motion_prompt_presence"],"image_source":"generate"}'::jsonb,
    '{"cost_tier":"highest","image_count_mode":"duration","images_per_minute":10,"clips_per_image":1,"copy":"About one image and clip per meaningful visual cue. You pay providers directly with your keys."}'::jsonb,
    TRUE, TRUE, 40
  )
ON CONFLICT (id) DO UPDATE SET
  version = EXCLUDED.version,
  label = EXCLUDED.label,
  description = EXCLUDED.description,
  knobs = EXCLUDED.knobs,
  estimate = EXCLUDED.estimate,
  requires_byok = EXCLUDED.requires_byok,
  public = EXCLUDED.public,
  sort = EXCLUDED.sort,
  updated_at = now();

-- =============================================================================
-- CUSTOM FILM CONTRACT (migration 122)
-- =============================================================================
-- Tenant-owned reusable recipes are topic-free immutable versions. Instantiated
-- plans/sections are also immutable; only a plan's future approval fields may
-- change. Stable section UUIDs intentionally do not depend on scene numbers.
CREATE UNIQUE INDEX IF NOT EXISTS videos_tenant_id_id_uidx
  ON videos (tenant_id, id);
CREATE UNIQUE INDEX IF NOT EXISTS scripts_tenant_video_id_uidx
  ON scripts (tenant_id, video_id, id);

CREATE TABLE IF NOT EXISTS custom_film_recipes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  recipe_family_id UUID NOT NULL,
  version INTEGER NOT NULL CHECK (version > 0),
  name TEXT NOT NULL CHECK (btrim(name) <> ''),
  compatibility_version TEXT NOT NULL CHECK (btrim(compatibility_version) <> ''),
  recipe JSONB NOT NULL CHECK (jsonb_typeof(recipe) = 'object'),
  signature TEXT NOT NULL CHECK (signature ~ '^[0-9a-f]{64}$'),
  archived_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, recipe_family_id, version)
);

CREATE UNIQUE INDEX IF NOT EXISTS custom_film_recipes_active_signature_uidx
  ON custom_film_recipes (tenant_id, signature)
  WHERE archived_at IS NULL;
CREATE INDEX IF NOT EXISTS custom_film_recipes_family_idx
  ON custom_film_recipes (tenant_id, recipe_family_id, version DESC);

CREATE TABLE IF NOT EXISTS custom_film_plans (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  video_id UUID NOT NULL,
  revision INTEGER NOT NULL CHECK (revision > 0),
  compatibility_version TEXT NOT NULL CHECK (btrim(compatibility_version) <> ''),
  plan JSONB NOT NULL CHECK (jsonb_typeof(plan) = 'object'),
  plan_hash TEXT NOT NULL CHECK (plan_hash ~ '^[0-9a-f]{64}$'),
  quote_inputs JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(quote_inputs) = 'object'),
  quote_inputs_hash TEXT NOT NULL CHECK (quote_inputs_hash ~ '^[0-9a-f]{64}$'),
  approval_hash TEXT CHECK (
    approval_hash IS NULL OR approval_hash ~ '^[0-9a-f]{64}$'
  ),
  approved_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, video_id, revision),
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, id, video_id),
  FOREIGN KEY (tenant_id, video_id)
    REFERENCES videos(tenant_id, id) ON DELETE CASCADE,
  CHECK (
    (approval_hash IS NULL AND approved_at IS NULL)
    OR (approval_hash IS NOT NULL AND approved_at IS NOT NULL)
  )
);

CREATE INDEX IF NOT EXISTS custom_film_plans_video_revision_idx
  ON custom_film_plans (tenant_id, video_id, revision DESC);

CREATE TABLE IF NOT EXISTS custom_film_sections (
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  plan_id UUID NOT NULL,
  video_id UUID NOT NULL,
  section_id UUID NOT NULL,
  order_index INTEGER NOT NULL CHECK (order_index >= 0),
  role TEXT NOT NULL CHECK (btrim(role) <> ''),
  purpose TEXT NOT NULL CHECK (btrim(purpose) <> ''),
  duration_units INTEGER NOT NULL CHECK (
    duration_units > 0 AND duration_units <= 1000000
  ),
  knobs JSONB NOT NULL CHECK (jsonb_typeof(knobs) = 'object'),
  provenance JSONB NOT NULL CHECK (jsonb_typeof(provenance) = 'object'),
  estimated_media JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(estimated_media) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, plan_id, section_id),
  UNIQUE (tenant_id, plan_id, video_id, section_id),
  UNIQUE (tenant_id, plan_id, order_index),
  FOREIGN KEY (tenant_id, plan_id, video_id)
    REFERENCES custom_film_plans(tenant_id, id, video_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS custom_film_sections_order_idx
  ON custom_film_sections (tenant_id, plan_id, order_index);

CREATE TABLE IF NOT EXISTS custom_film_section_scenes (
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  plan_id UUID NOT NULL,
  video_id UUID NOT NULL,
  section_id UUID NOT NULL,
  script_id UUID NOT NULL,
  scene_order INTEGER NOT NULL CHECK (scene_order >= 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, plan_id, section_id, script_id),
  UNIQUE (tenant_id, plan_id, script_id),
  UNIQUE (tenant_id, plan_id, section_id, scene_order),
  FOREIGN KEY (tenant_id, plan_id, video_id, section_id)
    REFERENCES custom_film_sections(tenant_id, plan_id, video_id, section_id)
    ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, video_id, script_id)
    REFERENCES scripts(tenant_id, video_id, id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS custom_film_section_scenes_order_idx
  ON custom_film_section_scenes
    (tenant_id, plan_id, section_id, scene_order);

-- M2-4B2a: provider request/result journal keyed by the stable stage
-- operation_id. Provider callers may query a persisted provider task, repeat
-- an idempotent request with the same operation ID, or fail closed; they may
-- never blindly replay an unresolved opaque request.
CREATE TABLE IF NOT EXISTS custom_film_provider_operations (
  operation_id TEXT PRIMARY KEY
    CHECK (operation_id ~ '^custom-film-op:[0-9a-f]{64}$'),
  tenant_id UUID NOT NULL,
  video_id UUID NOT NULL,
  runtime_job_id TEXT NOT NULL
    CHECK (runtime_job_id ~ '^custom-film-runtime:[0-9a-f]{64}$'),
  runtime_hash TEXT NOT NULL CHECK (runtime_hash ~ '^[0-9a-f]{64}$'),
  stage_key TEXT NOT NULL CHECK (stage_key <> ''),
  provider TEXT NOT NULL CHECK (provider <> ''),
  request_hash TEXT NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  reconciliation_mode TEXT NOT NULL
    CHECK (reconciliation_mode IN (
      'provider_query', 'provider_idempotency', 'none'
    )),
  state TEXT NOT NULL DEFAULT 'prepared'
    CHECK (state IN (
      'prepared', 'submitted', 'completed', 'failed',
      'reconciliation_required'
    )),
  provider_operation_id TEXT,
  result JSONB,
  reconciliation_detail TEXT,
  submitted_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, video_id, runtime_job_id, stage_key),
  CHECK (state <> 'completed' OR result IS NOT NULL),
  CHECK (state <> 'submitted' OR provider_operation_id IS NOT NULL),
  FOREIGN KEY (tenant_id, video_id)
    REFERENCES videos(tenant_id, id) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, video_id, runtime_job_id)
    REFERENCES background_tasks(tenant_id, video_id, job_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS custom_film_provider_operations_runtime_idx
  ON custom_film_provider_operations (tenant_id, video_id, runtime_job_id);

ALTER TABLE assets
  ADD CONSTRAINT assets_tenant_video_id_uidx
  UNIQUE (tenant_id, video_id, id);

ALTER TABLE custom_film_provider_operations
  ADD CONSTRAINT custom_film_provider_operations_identity_uidx
  UNIQUE (operation_id, tenant_id, video_id, runtime_hash);

CREATE TABLE IF NOT EXISTS custom_film_asset_provenance (
  tenant_id UUID NOT NULL,
  video_id UUID NOT NULL,
  asset_id UUID NOT NULL,
  plan_id UUID NOT NULL,
  section_id UUID NOT NULL,
  runtime_hash TEXT NOT NULL CHECK (runtime_hash ~ '^[0-9a-f]{64}$'),
  stage TEXT NOT NULL CHECK (stage IN ('pictures', 'motion', 'clips')),
  operation_id TEXT NOT NULL
    CHECK (operation_id ~ '^custom-film-op:[0-9a-f]{64}$'),
  request_hash TEXT NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  section_contract_hash TEXT NOT NULL
    CHECK (section_contract_hash ~ '^[0-9a-f]{64}$'),
  generation_method TEXT NOT NULL CHECK (generation_method <> ''),
  provider_model TEXT,
  status TEXT NOT NULL DEFAULT 'prepared'
    CHECK (status IN ('prepared', 'submitted', 'completed', 'failed')),
  artifact_url_hash TEXT CHECK (
    artifact_url_hash IS NULL OR artifact_url_hash ~ '^[0-9a-f]{64}$'
  ),
  actual_duration_ms BIGINT CHECK (
    actual_duration_ms IS NULL OR actual_duration_ms > 0
  ),
  assigned_duration_ms BIGINT CHECK (
    assigned_duration_ms IS NULL OR assigned_duration_ms > 0
  ),
  timing_transform JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, video_id, asset_id, runtime_hash, stage),
  FOREIGN KEY (tenant_id, video_id, asset_id)
    REFERENCES assets(tenant_id, video_id, id) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, plan_id, video_id, section_id)
    REFERENCES custom_film_sections(tenant_id, plan_id, video_id, section_id)
    ON DELETE CASCADE,
  FOREIGN KEY (operation_id, tenant_id, video_id, runtime_hash)
    REFERENCES custom_film_provider_operations(
      operation_id, tenant_id, video_id, runtime_hash
    ) ON DELETE CASCADE,
  CHECK (
    (status = 'completed' AND artifact_url_hash IS NOT NULL
     AND completed_at IS NOT NULL)
    OR
    (status <> 'completed' AND completed_at IS NULL)
  ),
  CHECK (
    (stage = 'clips' AND assigned_duration_ms IS NOT NULL)
    OR
    (stage <> 'clips' AND actual_duration_ms IS NULL
      AND assigned_duration_ms IS NULL AND timing_transform IS NULL)
  ),
  CHECK (
    stage <> 'clips' OR status <> 'completed'
    OR (actual_duration_ms IS NOT NULL AND timing_transform IS NOT NULL)
  )
);

CREATE INDEX IF NOT EXISTS custom_film_asset_provenance_section_idx
  ON custom_film_asset_provenance
    (tenant_id, video_id, plan_id, section_id, runtime_hash, stage);

CREATE OR REPLACE FUNCTION protect_custom_film_provider_operation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF (
    NEW.operation_id, NEW.tenant_id, NEW.video_id, NEW.runtime_job_id,
    NEW.runtime_hash, NEW.stage_key, NEW.provider, NEW.request_hash,
    NEW.reconciliation_mode
  ) IS DISTINCT FROM (
    OLD.operation_id, OLD.tenant_id, OLD.video_id, OLD.runtime_job_id,
    OLD.runtime_hash, OLD.stage_key, OLD.provider, OLD.request_hash,
    OLD.reconciliation_mode
  ) THEN
    RAISE EXCEPTION 'Custom Film provider operation identity is immutable';
  END IF;
  IF OLD.provider_operation_id IS NOT NULL
     AND NEW.provider_operation_id IS DISTINCT FROM OLD.provider_operation_id THEN
    RAISE EXCEPTION 'Custom Film provider task identity is write-once';
  END IF;
  IF OLD.result IS NOT NULL AND NEW.result IS DISTINCT FROM OLD.result THEN
    RAISE EXCEPTION 'Custom Film provider result is write-once';
  END IF;
  IF OLD.reconciliation_detail IS NOT NULL
     AND NEW.reconciliation_detail IS DISTINCT FROM OLD.reconciliation_detail THEN
    RAISE EXCEPTION 'Custom Film reconciliation detail is write-once';
  END IF;
  IF OLD.state IN ('completed', 'failed', 'reconciliation_required')
     AND (
       NEW.provider_operation_id, NEW.result, NEW.reconciliation_detail
     ) IS DISTINCT FROM (
       OLD.provider_operation_id, OLD.result, OLD.reconciliation_detail
     ) THEN
    RAISE EXCEPTION 'Custom Film terminal provider operation is immutable';
  END IF;
  IF (
    (OLD.state = 'prepared' AND NEW.state NOT IN (
      'prepared', 'submitted', 'completed', 'failed',
      'reconciliation_required'
    ))
    OR (OLD.state = 'submitted' AND NEW.state NOT IN (
      'submitted', 'completed', 'failed', 'reconciliation_required'
    ))
    OR (OLD.state IN ('completed', 'failed', 'reconciliation_required')
        AND NEW.state <> OLD.state)
  ) THEN
    RAISE EXCEPTION 'Custom Film provider operation state cannot regress';
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION protect_custom_film_asset_provenance()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF (
    NEW.tenant_id, NEW.video_id, NEW.asset_id, NEW.plan_id, NEW.section_id,
    NEW.runtime_hash, NEW.stage, NEW.operation_id, NEW.request_hash,
    NEW.section_contract_hash,
    NEW.generation_method
  ) IS DISTINCT FROM (
    OLD.tenant_id, OLD.video_id, OLD.asset_id, OLD.plan_id, OLD.section_id,
    OLD.runtime_hash, OLD.stage, OLD.operation_id, OLD.request_hash,
    OLD.section_contract_hash,
    OLD.generation_method
  ) THEN
    RAISE EXCEPTION 'Custom Film asset provenance identity is immutable';
  END IF;
  IF OLD.provider_model IS NOT NULL
     AND NEW.provider_model IS DISTINCT FROM OLD.provider_model THEN
    RAISE EXCEPTION 'Custom Film asset provider model is write-once';
  END IF;
  IF OLD.artifact_url_hash IS NOT NULL
     AND NEW.artifact_url_hash IS DISTINCT FROM OLD.artifact_url_hash THEN
    RAISE EXCEPTION 'Custom Film asset URL identity is write-once';
  END IF;
  IF OLD.actual_duration_ms IS NOT NULL
     AND NEW.actual_duration_ms IS DISTINCT FROM OLD.actual_duration_ms THEN
    RAISE EXCEPTION 'Custom Film asset actual duration is write-once';
  END IF;
  IF OLD.assigned_duration_ms IS NOT NULL
     AND NEW.assigned_duration_ms IS DISTINCT FROM OLD.assigned_duration_ms THEN
    RAISE EXCEPTION 'Custom Film asset assigned duration is write-once';
  END IF;
  IF OLD.timing_transform IS NOT NULL
     AND NEW.timing_transform IS DISTINCT FROM OLD.timing_transform THEN
    RAISE EXCEPTION 'Custom Film asset timing transform is write-once';
  END IF;
  IF (
    (OLD.status = 'prepared' AND NEW.status NOT IN (
      'prepared', 'submitted', 'failed'
    ))
    OR (OLD.status = 'submitted' AND NEW.status NOT IN (
      'submitted', 'completed', 'failed'
    ))
    OR (OLD.status IN ('completed', 'failed') AND NEW.status <> OLD.status)
  ) THEN
    RAISE EXCEPTION 'Custom Film asset provenance status cannot regress';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER custom_film_provider_operation_protect
  BEFORE UPDATE ON custom_film_provider_operations
  FOR EACH ROW EXECUTE FUNCTION protect_custom_film_provider_operation();

CREATE TRIGGER custom_film_asset_provenance_protect
  BEFORE UPDATE ON custom_film_asset_provenance
  FOR EACH ROW EXECUTE FUNCTION protect_custom_film_asset_provenance();

ALTER TABLE videos
  ADD CONSTRAINT videos_custom_film_plan_fkey
  FOREIGN KEY (tenant_id, custom_film_plan_id)
  REFERENCES custom_film_plans(tenant_id, id)
  DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE videos
  ADD CONSTRAINT videos_custom_film_plan_revision_check
  CHECK (
    (custom_film_plan_id IS NULL
     AND custom_film_plan_revision IS NULL
     AND custom_film_plan_hash IS NULL
     AND custom_film_quote_inputs_hash IS NULL
     AND custom_film_approval_hash IS NULL
     AND custom_film_approved_at IS NULL)
    OR
    (custom_film_plan_id IS NOT NULL
     AND custom_film_plan_revision > 0
     AND custom_film_plan_hash ~ '^[0-9a-f]{64}$'
     AND custom_film_quote_inputs_hash ~ '^[0-9a-f]{64}$'
     AND (
       (custom_film_approval_hash IS NULL AND custom_film_approved_at IS NULL)
       OR
       (custom_film_approval_hash ~ '^[0-9a-f]{64}$'
        AND custom_film_approved_at IS NOT NULL)
     ))
  );

CREATE OR REPLACE FUNCTION protect_custom_film_immutable_contract()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_TABLE_NAME = 'custom_film_sections' THEN
    RAISE EXCEPTION 'Custom Film section contracts are immutable';
  END IF;
  IF TG_TABLE_NAME = 'custom_film_recipes'
     AND (
       NEW.tenant_id, NEW.recipe_family_id, NEW.version,
       NEW.compatibility_version, NEW.recipe, NEW.signature
     ) IS DISTINCT FROM (
       OLD.tenant_id, OLD.recipe_family_id, OLD.version,
       OLD.compatibility_version, OLD.recipe, OLD.signature
     ) THEN
    RAISE EXCEPTION 'Custom Film recipe versions are immutable';
  END IF;
  IF TG_TABLE_NAME = 'custom_film_plans'
     AND (
       NEW.tenant_id, NEW.video_id, NEW.revision,
       NEW.compatibility_version, NEW.plan, NEW.plan_hash,
       NEW.quote_inputs, NEW.quote_inputs_hash
     ) IS DISTINCT FROM (
       OLD.tenant_id, OLD.video_id, OLD.revision,
       OLD.compatibility_version, OLD.plan, OLD.plan_hash,
       OLD.quote_inputs, OLD.quote_inputs_hash
     ) THEN
    RAISE EXCEPTION 'Custom Film plan revisions are immutable';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER custom_film_recipes_immutable
  BEFORE UPDATE ON custom_film_recipes
  FOR EACH ROW EXECUTE FUNCTION protect_custom_film_immutable_contract();
CREATE TRIGGER custom_film_plans_immutable
  BEFORE UPDATE ON custom_film_plans
  FOR EACH ROW EXECUTE FUNCTION protect_custom_film_immutable_contract();
CREATE TRIGGER custom_film_sections_immutable
  BEFORE UPDATE ON custom_film_sections
  FOR EACH ROW EXECUTE FUNCTION protect_custom_film_immutable_contract();

ALTER TABLE custom_film_recipes ENABLE ROW LEVEL SECURITY;
ALTER TABLE custom_film_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE custom_film_sections ENABLE ROW LEVEL SECURITY;
ALTER TABLE custom_film_section_scenes ENABLE ROW LEVEL SECURITY;
ALTER TABLE custom_film_provider_operations ENABLE ROW LEVEL SECURITY;
ALTER TABLE custom_film_asset_provenance ENABLE ROW LEVEL SECURITY;

-- M2-5: immutable, restart-safe Custom Film assembly and upload journal.
CREATE TABLE IF NOT EXISTS custom_film_assemblies (
  tenant_id UUID NOT NULL,
  video_id UUID NOT NULL,
  runtime_job_id TEXT NOT NULL,
  runtime_hash TEXT NOT NULL CHECK (runtime_hash ~ '^[0-9a-f]{64}$'),
  manifest_version TEXT NOT NULL CHECK (manifest_version = 'custom-film-assembly-v1'),
  manifest_hash TEXT NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
  manifest JSONB NOT NULL CHECK (jsonb_typeof(manifest) = 'object'),
  progress JSONB NOT NULL CHECK (
    jsonb_typeof(progress) = 'object'
    AND progress->>'phase' IN (
      'prepared', 'normalizing', 'assembling', 'rendering',
      'uploading', 'finalized', 'retryable_failed', 'terminal_failed'
    )
    AND (progress->>'completed_sections') ~ '^[0-9]+$'
    AND (progress->>'total_sections') ~ '^[1-9][0-9]*$'
    AND (progress->>'completed_sections')::integer
      <= (progress->>'total_sections')::integer
  ),
  state TEXT NOT NULL DEFAULT 'prepared' CHECK (
    state IN ('prepared', 'rendering', 'rendered', 'uploading', 'uploaded', 'finalized', 'retryable_failed', 'terminal_failed')
  ),
  artifact_sha256 TEXT CHECK (artifact_sha256 IS NULL OR artifact_sha256 ~ '^[0-9a-f]{64}$'),
  artifact_probe JSONB,
  storage_path TEXT NOT NULL CHECK (storage_path <> ''),
  final_video_url TEXT,
  failure_detail TEXT,
  failure_kind TEXT CHECK (failure_kind IS NULL OR failure_kind IN ('retryable', 'terminal')),
  retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
  render_started_at TIMESTAMPTZ,
  rendered_at TIMESTAMPTZ,
  upload_started_at TIMESTAMPTZ,
  uploaded_at TIMESTAMPTZ,
  finalized_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, video_id, runtime_hash),
  UNIQUE (tenant_id, video_id, manifest_hash),
  FOREIGN KEY (tenant_id, video_id) REFERENCES videos(tenant_id, id) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, video_id, runtime_job_id)
    REFERENCES background_tasks(tenant_id, video_id, job_id),
  CHECK (
    manifest->>'assembly_version' = manifest_version
    AND manifest->>'manifest_hash' = manifest_hash
    AND manifest->>'runtime_hash' = runtime_hash
    AND manifest->>'runtime_job_id' = runtime_job_id
    AND manifest->>'tenant_id' = tenant_id::text
    AND manifest->>'video_id' = video_id::text
  ),
  CHECK (
    state NOT IN ('rendered', 'uploading', 'uploaded', 'finalized')
    OR (artifact_sha256 IS NOT NULL AND artifact_probe IS NOT NULL AND rendered_at IS NOT NULL)
  ),
  CHECK (
    state NOT IN ('uploaded', 'finalized')
    OR (final_video_url IS NOT NULL AND uploaded_at IS NOT NULL)
  ),
  CHECK (state <> 'finalized' OR finalized_at IS NOT NULL)
);

CREATE OR REPLACE FUNCTION protect_custom_film_assembly()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  old_phase_rank INTEGER;
  new_phase_rank INTEGER;
BEGIN
  IF (
    NEW.tenant_id, NEW.video_id, NEW.runtime_job_id, NEW.runtime_hash, NEW.manifest_version,
    NEW.manifest_hash, NEW.manifest, NEW.storage_path
  ) IS DISTINCT FROM (
    OLD.tenant_id, OLD.video_id, OLD.runtime_job_id, OLD.runtime_hash, OLD.manifest_version,
    OLD.manifest_hash, OLD.manifest, OLD.storage_path
  ) THEN
    RAISE EXCEPTION 'Custom Film assembly identity is immutable';
  END IF;
  IF OLD.artifact_sha256 IS NOT NULL
     AND NEW.artifact_sha256 IS DISTINCT FROM OLD.artifact_sha256 THEN
    RAISE EXCEPTION 'Custom Film assembly artifact hash is write-once';
  END IF;
  IF OLD.artifact_probe IS NOT NULL
     AND NEW.artifact_probe IS DISTINCT FROM OLD.artifact_probe THEN
    RAISE EXCEPTION 'Custom Film assembly probe is write-once';
  END IF;
  IF OLD.final_video_url IS NOT NULL
     AND NEW.final_video_url IS DISTINCT FROM OLD.final_video_url THEN
    RAISE EXCEPTION 'Custom Film assembly storage result is write-once';
  END IF;
  IF (NEW.progress->>'total_sections')::integer
       <> (OLD.progress->>'total_sections')::integer
     OR (NEW.progress->>'completed_sections')::integer
       < (OLD.progress->>'completed_sections')::integer THEN
    RAISE EXCEPTION 'Custom Film assembly progress cannot regress';
  END IF;
  old_phase_rank := CASE OLD.progress->>'phase'
    WHEN 'prepared' THEN 0 WHEN 'normalizing' THEN 1
    WHEN 'assembling' THEN 2 WHEN 'rendering' THEN 3
    WHEN 'uploading' THEN 4 WHEN 'finalized' THEN 5 ELSE 6 END;
  new_phase_rank := CASE NEW.progress->>'phase'
    WHEN 'prepared' THEN 0 WHEN 'normalizing' THEN 1
    WHEN 'assembling' THEN 2 WHEN 'rendering' THEN 3
    WHEN 'uploading' THEN 4 WHEN 'finalized' THEN 5 ELSE 6 END;
  IF OLD.state <> 'retryable_failed'
     AND NEW.progress->>'phase' NOT IN ('retryable_failed', 'terminal_failed')
     AND new_phase_rank < old_phase_rank THEN
    RAISE EXCEPTION 'Custom Film assembly phase cannot regress';
  END IF;
  IF (
    (OLD.state = 'prepared' AND NEW.state NOT IN ('prepared', 'rendering', 'retryable_failed', 'terminal_failed'))
    OR (OLD.state = 'rendering' AND NEW.state NOT IN ('rendering', 'rendered', 'retryable_failed', 'terminal_failed'))
    OR (OLD.state = 'rendered' AND NEW.state NOT IN ('rendered', 'uploading', 'retryable_failed', 'terminal_failed'))
    OR (OLD.state = 'uploading' AND NEW.state NOT IN ('uploading', 'uploaded', 'retryable_failed', 'terminal_failed'))
    OR (OLD.state = 'uploaded' AND NEW.state NOT IN ('uploaded', 'finalized', 'retryable_failed', 'terminal_failed'))
    OR (OLD.state = 'retryable_failed' AND NEW.state NOT IN ('retryable_failed', 'rendering', 'terminal_failed'))
    OR (OLD.state IN ('finalized', 'terminal_failed') AND NEW.state <> OLD.state)
  ) THEN
    RAISE EXCEPTION 'Custom Film assembly state cannot regress or skip';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS custom_film_assembly_protect ON custom_film_assemblies;
CREATE TRIGGER custom_film_assembly_protect
  BEFORE UPDATE ON custom_film_assemblies
  FOR EACH ROW EXECUTE FUNCTION protect_custom_film_assembly();

CREATE INDEX IF NOT EXISTS custom_film_assemblies_state_idx
  ON custom_film_assemblies (tenant_id, state, updated_at);

ALTER TABLE custom_film_assemblies ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE custom_film_assemblies FROM anon, authenticated;

REVOKE ALL ON custom_film_recipes FROM anon;
REVOKE ALL ON custom_film_plans FROM anon;
REVOKE ALL ON custom_film_sections FROM anon;
REVOKE ALL ON custom_film_section_scenes FROM anon;
REVOKE ALL ON custom_film_provider_operations FROM anon;
REVOKE ALL ON custom_film_asset_provenance FROM anon;
REVOKE ALL ON custom_film_recipes FROM authenticated;
REVOKE ALL ON custom_film_plans FROM authenticated;
REVOKE ALL ON custom_film_sections FROM authenticated;
REVOKE ALL ON custom_film_section_scenes FROM authenticated;
REVOKE ALL ON custom_film_provider_operations FROM authenticated;
REVOKE ALL ON custom_film_asset_provenance FROM authenticated;

CREATE POLICY "Tenant isolation" ON custom_film_recipes
  FOR ALL TO authenticated
  USING (
    tenant_id IN (
      SELECT m.tenant_id FROM memberships m
      WHERE m.user_id = (SELECT auth.uid())
    )
  )
  WITH CHECK (
    tenant_id IN (
      SELECT m.tenant_id FROM memberships m
      WHERE m.user_id = (SELECT auth.uid())
    )
  );

CREATE POLICY "Tenant isolation" ON custom_film_plans
  FOR ALL TO authenticated
  USING (
    tenant_id IN (
      SELECT m.tenant_id FROM memberships m
      WHERE m.user_id = (SELECT auth.uid())
    )
  )
  WITH CHECK (
    tenant_id IN (
      SELECT m.tenant_id FROM memberships m
      WHERE m.user_id = (SELECT auth.uid())
    )
    AND EXISTS (
      SELECT 1 FROM videos v
      WHERE v.id = custom_film_plans.video_id
        AND v.tenant_id = custom_film_plans.tenant_id
    )
  );

CREATE POLICY "Tenant isolation" ON custom_film_sections
  FOR ALL TO authenticated
  USING (
    tenant_id IN (
      SELECT m.tenant_id FROM memberships m
      WHERE m.user_id = (SELECT auth.uid())
    )
  )
  WITH CHECK (
    tenant_id IN (
      SELECT m.tenant_id FROM memberships m
      WHERE m.user_id = (SELECT auth.uid())
    )
    AND EXISTS (
      SELECT 1 FROM custom_film_plans p
      WHERE p.id = custom_film_sections.plan_id
        AND p.tenant_id = custom_film_sections.tenant_id
    )
  );

CREATE POLICY "Tenant isolation" ON custom_film_section_scenes
  FOR ALL TO authenticated
  USING (
    tenant_id IN (
      SELECT m.tenant_id FROM memberships m
      WHERE m.user_id = (SELECT auth.uid())
    )
  )
  WITH CHECK (
    tenant_id IN (
      SELECT m.tenant_id FROM memberships m
      WHERE m.user_id = (SELECT auth.uid())
    )
    AND EXISTS (
      SELECT 1 FROM custom_film_sections s
      WHERE s.plan_id = custom_film_section_scenes.plan_id
        AND s.video_id = custom_film_section_scenes.video_id
        AND s.section_id = custom_film_section_scenes.section_id
        AND s.tenant_id = custom_film_section_scenes.tenant_id
    )
  );


-- =============================================================================
-- AGENT_TOKENS (migration 099 — checklist P2.4a, chunk C26)
-- =============================================================================
-- DB-row-backed, individually revocable per-tenant API tokens for external
-- MCP clients (the StoryEngine MCP server, tasks/storyengine-copilot-ux-map.md
-- §7). See migrations/099_agent_tokens.sql for the full design rationale
-- (S5-3/S5-4 in docs/reports/2026-07-17-storyengine-agent-audit-findings.md)
-- and backend/agent_tokens.py for mint/list/revoke/authenticate.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_tokens (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  token_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_used_at TIMESTAMPTZ,
  revoked_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS agent_tokens_token_hash_unique
  ON agent_tokens (token_hash);

CREATE INDEX IF NOT EXISTS agent_tokens_tenant_idx
  ON agent_tokens (tenant_id) WHERE revoked_at IS NULL;

ALTER TABLE agent_tokens ENABLE ROW LEVEL SECURITY;
-- No policies (deny-all to anon/authenticated/PostgREST); backend bypasses
-- via table ownership + BYPASSRLS (see migration 083 for the proof).


-- =============================================================================
-- MCP_CONFIRM_TOKENS (migration 100 — checklist P2.4b, chunk C27)
-- =============================================================================
-- The MCP money gate's single-use, param-bound confirm token. See
-- migrations/100_mcp_confirm_tokens.sql for the full design rationale and
-- backend/confirm_tokens.py for create()/redeem()/params_hash().
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mcp_confirm_tokens (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
  verb TEXT NOT NULL,
  params_hash TEXT NOT NULL,
  token_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL,
  used_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS mcp_confirm_tokens_token_hash_unique
  ON mcp_confirm_tokens (token_hash);

CREATE INDEX IF NOT EXISTS mcp_confirm_tokens_tenant_video_idx
  ON mcp_confirm_tokens (tenant_id, video_id) WHERE used_at IS NULL;

ALTER TABLE mcp_confirm_tokens ENABLE ROW LEVEL SECURITY;
-- No policies (deny-all to anon/authenticated/PostgREST); backend bypasses
-- via table ownership + BYPASSRLS (see migration 083 for the proof).


-- =============================================================================
-- YOUTUBE_QUOTA_USAGE (migration 101 — checklist P3.4, chunk C33)
-- =============================================================================
-- The YouTube Data API quota guard's counter. GLOBAL scope, no tenant_id:
-- the 10,000-units/day quota is billed to a Google Cloud PROJECT, and every
-- tenant's OAuth token in this app is minted from the SAME OAuth client (one
-- shared GOOGLE_OAUTH_CLIENT_ID/SECRET env-var pair), so every tenant's Data
-- API calls draw down the SAME pool. One row per Pacific-Time calendar day
-- (YouTube resets at midnight PT, not UTC). See
-- migrations/101_youtube_quota_usage.sql and backend/youtube_quota.py for
-- the full design rationale.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS youtube_quota_usage (
  day DATE PRIMARY KEY,
  units_used INTEGER NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE youtube_quota_usage ENABLE ROW LEVEL SECURITY;
-- No policies (deny-all to anon/authenticated/PostgREST); backend bypasses
-- via table ownership + BYPASSRLS (see migration 083 for the proof).

-- =============================================================================
-- QUALITY_RULES (migration 105 — checklist C46b, per-channel quality-rules store)
-- =============================================================================
-- The real per-channel rules table C46a's `rules_text` seam was a stopgap for
-- (script_templates.structure). Discrete, severity-tagged LAW rows modeled on
-- storyengine/notes/dvsu-quality-law.md's QL/QD row shape, scoped per-video
-- via `applies_to`. Full applies_to vocabulary + scope-resolution rationale
-- documented in migrations/105_quality_rules.sql's header (read it before
-- touching this table) and implemented in backend/quality_rules.py's
-- `active_rules_for_video()`.
CREATE TABLE IF NOT EXISTS quality_rules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  rule_id TEXT NOT NULL,
  law TEXT NOT NULL,
  evidence TEXT,
  severity TEXT NOT NULL CHECK (severity IN ('hard_gate', 'warn', 'guidance')),
  applies_to JSONB NOT NULL DEFAULT '{"all": true}'::jsonb,
  source TEXT NOT NULL CHECK (source IN ('doc_upload', 'chat', 'seed')),
  active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, rule_id)
);

CREATE INDEX IF NOT EXISTS quality_rules_tenant_active_idx
  ON quality_rules (tenant_id, active);

ALTER TABLE quality_rules ENABLE ROW LEVEL SECURITY;
-- No policies (deny-all to anon/authenticated/PostgREST); backend bypasses
-- via table ownership + BYPASSRLS (see migration 083 for the proof).

-- =============================================================================
-- CHANNEL_PATTERNS (migration 106 — checklist C46e, OR-6 EXPANDED). Per-
-- channel, data-derived style/pattern tagging: a pattern proposal (polarity
-- 'anti'|'good', evidence jsonb, source import_analysis|launch_analysis|
-- manual) that takes effect ONLY once a human confirms it (status
-- proposed -> confirmed -> optionally retired). Confirmed 'anti' rows are
-- read by `channel_patterns.confirmed_anti_video_ids()` to exclude their
-- evidence-linked videos from style-seed/few-shot selection
-- (identity_builder.py's `_ranked_videos`). Full rationale in
-- migrations/106_channel_patterns.sql's header (read it before touching
-- this table) and implemented in backend/channel_patterns.py.
CREATE TABLE IF NOT EXISTS channel_patterns (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  pattern TEXT NOT NULL,
  polarity TEXT NOT NULL CHECK (polarity IN ('anti', 'good')),
  evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
  source TEXT NOT NULL CHECK (source IN ('import_analysis', 'launch_analysis', 'manual')),
  status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'confirmed', 'retired')),
  confirmed_at TIMESTAMPTZ,
  confirmed_by TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS channel_patterns_tenant_status_idx
  ON channel_patterns (tenant_id, status);

ALTER TABLE channel_patterns ENABLE ROW LEVEL SECURITY;
-- No policies (deny-all to anon/authenticated/PostgREST); backend bypasses
-- via table ownership + BYPASSRLS (see migration 083 for the proof).

-- =============================================================================
-- AUTOPILOT_PROPOSALS (migration 108 — checklist C51, P4.2-b candidate
-- auto-launch loop, propose_only dial-level).
-- =============================================================================
-- A propose_only-dial dry run never creates a video, never dispatches the
-- pipeline, never spends money — it only records here that "candidate X
-- scored above the tenant's min_confidence_score threshold and was the best
-- available pick this cadence window." A human (C52's UI/chat surface)
-- turns a proposal into a real launch by calling the SAME
-- routes.autopilot.launch_candidate path a manual click already uses; this
-- table never gates or replaces that call — it only stops the auto-launch
-- loop (backend/autopilot_launch.py) from re-proposing the same
-- competitor_videos row while a proposal is still undecided
-- (status='proposed'). Full rationale in
-- migrations/108_autopilot_proposals.sql's header (read it before touching
-- this table) and implemented in backend/autopilot_proposals.py.
CREATE TABLE IF NOT EXISTS autopilot_proposals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  candidate_id UUID NOT NULL REFERENCES competitor_videos(id) ON DELETE CASCADE,
  video_title TEXT NOT NULL,
  confidence_score NUMERIC NOT NULL DEFAULT 0,
  confidence_breakdown JSONB,
  status TEXT NOT NULL DEFAULT 'proposed'
    CHECK (status IN ('proposed', 'accepted', 'dismissed', 'expired')),
  decided_at TIMESTAMPTZ,
  decided_by TEXT,
  video_id UUID REFERENCES videos(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS autopilot_proposals_tenant_status_idx
  ON autopilot_proposals (tenant_id, status);

CREATE INDEX IF NOT EXISTS autopilot_proposals_tenant_candidate_idx
  ON autopilot_proposals (tenant_id, candidate_id, status);

ALTER TABLE autopilot_proposals ENABLE ROW LEVEL SECURITY;
-- No policies (deny-all to anon/authenticated/PostgREST); backend bypasses
-- via table ownership + BYPASSRLS (see migration 083 for the proof).

-- =============================================================================
-- FEATURE_REQUESTS / FEATURE_REQUEST_VOTES (migration 112 — checklist C65,
-- tasks/decisions.md 2026-07-20 "Feature board" entry).
-- =============================================================================
-- The platform's FIRST deliberately CROSS-TENANT surface: every customer
-- sees the SAME board, regardless of tenant. These two tables carry NO
-- tenant_id at all, on purpose — reads are global, writes are attributed per
-- ACCOUNT (accounts.id, the same UUID space auth users live in — see
-- routes/workspaces.py's `_is_operator` for the precedent of keying straight
-- off accounts.id rather than a tenant/membership join). Core loop: suggest
-- -> upvote (one per account per idea, enforced by the composite PRIMARY KEY
-- below, not application code) -> a status ladder (under_review -> planned
-- -> building -> in_beta -> shipped / declined) that only an operator
-- account can advance. Full rationale in migrations/112_feature_board.sql's
-- header (read it before touching these tables) and implemented in
-- backend/routes/feature_board.py.
CREATE TABLE IF NOT EXISTS feature_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  title TEXT NOT NULL CHECK (char_length(title) <= 120),
  body TEXT CHECK (body IS NULL OR char_length(body) <= 2000),
  channel_archetype TEXT,
  status TEXT NOT NULL DEFAULT 'under_review'
    CHECK (status IN ('under_review', 'planned', 'building', 'in_beta', 'shipped', 'declined')),
  declined_reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS feature_requests_status_idx
  ON feature_requests (status);

CREATE INDEX IF NOT EXISTS feature_requests_account_created_idx
  ON feature_requests (account_id, created_at);

ALTER TABLE feature_requests ENABLE ROW LEVEL SECURITY;
-- No policies (deny-all to anon/authenticated/PostgREST); backend bypasses
-- via table ownership + BYPASSRLS (see migration 083 for the proof).

CREATE TABLE IF NOT EXISTS feature_request_votes (
  request_id UUID NOT NULL REFERENCES feature_requests(id) ON DELETE CASCADE,
  account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (request_id, account_id)
);

CREATE INDEX IF NOT EXISTS feature_request_votes_request_idx
  ON feature_request_votes (request_id);

ALTER TABLE feature_request_votes ENABLE ROW LEVEL SECURITY;
-- No policies (deny-all to anon/authenticated/PostgREST); backend bypasses
-- via table ownership + BYPASSRLS (see migration 083 for the proof).


-- =============================================================================
-- BETA_CODES (migration 119)
-- =============================================================================
-- Launch beta access codes redeemed at signup for a longer free trial. See
-- migrations/119_beta_codes.sql for the full design rationale and
-- backend/routes/google_auth.py::register() for the atomic redeem call site.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS beta_codes (
  code TEXT PRIMARY KEY,              -- stored lowercased
  trial_days INT NOT NULL DEFAULT 60,
  max_redemptions INT,                -- NULL = unlimited
  redemptions_used INT NOT NULL DEFAULT 0,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  note TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE beta_codes ENABLE ROW LEVEL SECURITY;
-- No policies (deny-all to anon/authenticated/PostgREST); backend bypasses
-- via table ownership + BYPASSRLS (see migration 083 for the proof).

INSERT INTO beta_codes (code, trial_days, max_redemptions, active, note)
VALUES ('beta26', 60, NULL, TRUE, 'launch beta - 2 months free')
ON CONFLICT (code) DO NOTHING;


-- =============================================================================
-- APPLICATION_DRAIN_STATE (migration 120)
-- =============================================================================
-- Durable, global deployment drain. The backend and operator CLI share a
-- PostgreSQL advisory lock around transitions and generation claims, so once
-- draining commits no later paid claim can enter. Existing work and reads
-- continue; only backend service credentials can access this control row.
CREATE TABLE IF NOT EXISTS application_drain_state (
  singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
  mode TEXT NOT NULL DEFAULT 'normal' CHECK (mode IN ('normal', 'draining')),
  reason TEXT,
  owner TEXT,
  changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO application_drain_state (singleton, mode)
VALUES (TRUE, 'normal')
ON CONFLICT (singleton) DO NOTHING;

ALTER TABLE application_drain_state ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON application_drain_state FROM anon;
REVOKE ALL ON application_drain_state FROM authenticated;
