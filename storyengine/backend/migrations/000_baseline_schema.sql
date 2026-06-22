-- Baseline schema for fresh StoryEngine Supabase projects.
-- Existing migrations start at 003 and assume these core tables already exist.
-- Keep this non-destructive and idempotent so it is safe for existing databases.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS tenants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL,
  plan TEXT DEFAULT 'free',
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT,
  display_name TEXT,
  avatar_url TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS accounts (
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

CREATE TABLE IF NOT EXISTS memberships (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
  role TEXT DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member')),
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(user_id, tenant_id)
);

CREATE TABLE IF NOT EXISTS projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id UUID REFERENCES accounts(id) ON DELETE CASCADE NOT NULL,
  tenant_id UUID REFERENCES tenants(id),
  name TEXT NOT NULL DEFAULT '',
  niche TEXT,
  target_audience TEXT,
  visual_style TEXT DEFAULT 'cinematic_illustration',
  visual_profile_json JSONB,
  accent_color TEXT DEFAULT '#00D4AA',
  custom_accent_color TEXT,
  frameworks JSONB DEFAULT '[]'::jsonb,
  character_references JSONB DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS videos (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,
  project_id UUID REFERENCES projects(id),
  airtable_record_id TEXT UNIQUE,
  video_title TEXT,
  status TEXT,
  headline TEXT,
  source TEXT,
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
  revision_notes TEXT,
  seo_description TEXT,
  seo_tags TEXT,
  seo_hashtags TEXT,
  research_payload JSONB,
  original_dna JSONB,
  source_urls TEXT,
  date_surfaced DATE,
  timeliness_score NUMERIC,
  audience_fit_score NUMERIC,
  content_gap_score NUMERIC,
  structure_confidence NUMERIC,
  curiosity_structure TEXT,
  monetization_risk TEXT,
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
  video_length_minutes NUMERIC,
  clip_duration_seconds NUMERIC,
  final_video_url TEXT,
  drive_folder_link TEXT,
  drive_folder_id TEXT,
  youtube_video_id TEXT,
  youtube_url TEXT,
  upload_status TEXT,
  upload_date TIMESTAMPTZ,
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
  post_mortem_48h TEXT,
  post_mortem_7d TEXT,
  performance_verdict TEXT,
  storyboard_status TEXT,
  storyboard_preview_url TEXT,
  storyboard_beat_count INTEGER,
  video_model TEXT,
  scene_file_path TEXT,
  core_image_url TEXT,
  scene_count INTEGER,
  validation_status TEXT,
  video_id_internal TEXT,
  framework TEXT,
  sources TEXT,
  pipeline_mode TEXT,
  notes TEXT,
  reference_url TEXT,
  idea_reasoning TEXT,
  source_views INTEGER,
  source_channel TEXT,
  final_video_attachment_url TEXT,
  structure_source TEXT,
  pattern_library_snapshot TEXT,
  title_poll_result TEXT,
  poll_closed BOOLEAN DEFAULT false,
  thumbnail_palette TEXT,
  summary TEXT,
  ctr_12h NUMERIC,
  ctr_24h NUMERIC,
  agent_paper_trail JSONB,
  agent_hook_score NUMERIC,
  agent_body_score NUMERIC,
  agent_tier TEXT,
  agent_cost NUMERIC,
  suggested_script TEXT,
  suggested_title TEXT,
  suggested_thumbnail_prompt TEXT,
  suggested_thumbnail_urls JSONB,
  suggestion_source TEXT,
  suggestion_scores JSONB,
  suggestion_status TEXT,
  video_motion_system_prompt TEXT,
  script_system_prompt TEXT,
  thumbnail_system_prompt TEXT,
  sound_system_prompt TEXT,
  total_cost NUMERIC DEFAULT 0,
  learnings_extracted_at TIMESTAMPTZ,
  deleted_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scripts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,
  video_id UUID REFERENCES videos(id) ON DELETE CASCADE,
  airtable_record_id TEXT UNIQUE,
  airtable_id NUMERIC,
  scene INTEGER,
  title TEXT,
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
  storyboard_on_off TEXT,
  storyboard_prompts TEXT,
  storyboard_beat_count NUMERIC,
  storyboard_status TEXT,
  storyboard_1_url TEXT,
  storyboard_2_url TEXT,
  storyboard_3_url TEXT,
  storyboard_4_url TEXT,
  storyboard_5_url TEXT,
  tone TEXT DEFAULT 'serious',
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS assets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,
  video_id UUID REFERENCES videos(id) ON DELETE CASCADE,
  airtable_record_id TEXT UNIQUE,
  video_title TEXT,
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
  sound_prompt TEXT,
  sound_effect_url TEXT,
  sound_volume NUMERIC,
  video_prompt TEXT,
  video_url TEXT,
  video_status TEXT,
  video_duration NUMERIC,
  video_clip_url TEXT,
  video_clip_prompt TEXT,
  aspect_ratio TEXT DEFAULT '16:9',
  animation_status TEXT,
  intensity TEXT,
  content_type TEXT,
  hero_shot BOOLEAN DEFAULT false,
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

CREATE TABLE IF NOT EXISTS competitor_channels (
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

CREATE TABLE IF NOT EXISTS stage_transitions (
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

CREATE TABLE IF NOT EXISTS bot_activity (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) NOT NULL,
  bot_name TEXT NOT NULL,
  video_id UUID REFERENCES videos(id),
  status TEXT NOT NULL CHECK (status IN ('started', 'running', 'completed', 'failed')),
  message TEXT,
  cost NUMERIC DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_accounts_email ON accounts(email);
CREATE INDEX IF NOT EXISTS idx_memberships_tenant ON memberships(tenant_id);
CREATE INDEX IF NOT EXISTS idx_projects_account ON projects(account_id);
CREATE INDEX IF NOT EXISTS idx_projects_tenant ON projects(tenant_id);
CREATE INDEX IF NOT EXISTS idx_videos_tenant ON videos(tenant_id);
CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_videos_project ON videos(project_id);
CREATE INDEX IF NOT EXISTS idx_scripts_video ON scripts(video_id);
CREATE INDEX IF NOT EXISTS idx_scripts_tenant ON scripts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_assets_video ON assets(video_id);
CREATE INDEX IF NOT EXISTS idx_assets_tenant ON assets(tenant_id);
CREATE INDEX IF NOT EXISTS idx_competitor_channels_tenant ON competitor_channels(tenant_id);
CREATE INDEX IF NOT EXISTS idx_stage_transitions_video ON stage_transitions(video_id);
CREATE INDEX IF NOT EXISTS idx_bot_activity_tenant ON bot_activity(tenant_id, created_at DESC);
