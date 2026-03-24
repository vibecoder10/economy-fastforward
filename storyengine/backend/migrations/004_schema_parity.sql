-- 004_schema_parity.sql
-- Adds all missing Airtable fields to Supabase for 100% parity
-- Run in Supabase SQL Editor
-- All statements are idempotent (safe to re-run)

-- =============================================
-- VIDEOS — Add 26 missing columns
-- =============================================

ALTER TABLE videos ADD COLUMN IF NOT EXISTS scene_file_path TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS core_image_url TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS reference_url TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS idea_reasoning TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS source_views INTEGER;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS source_channel TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS pipeline_mode TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS notes TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS final_video_attachment_url TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS framework TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS sources TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS scene_count INTEGER;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS validation_status TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS video_id_internal TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS storyboard_status TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS storyboard_preview_url TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS storyboard_beat_count INTEGER;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS video_model TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS structure_source TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS pattern_library_snapshot TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS title_poll_result TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS poll_closed BOOLEAN DEFAULT false;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS thumbnail_palette TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS summary TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS ctr_12h NUMERIC;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS ctr_24h NUMERIC;

-- Rename image_model → image_model_override (only if old exists AND new doesn't)
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'videos' AND column_name = 'image_model')
     AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'videos' AND column_name = 'image_model_override')
  THEN
    ALTER TABLE videos RENAME COLUMN image_model TO image_model_override;
  END IF;
END $$;

-- =============================================
-- ASSETS — Add 7 missing columns
-- =============================================

ALTER TABLE assets ADD COLUMN IF NOT EXISTS drive_image_url TEXT;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS storyboard_grid_url TEXT;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS panel_position INTEGER;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS generation_method TEXT;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS camera_movement TEXT;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS assigned_video_duration NUMERIC;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS estimated_clip_cost NUMERIC;

-- =============================================
-- COMPETITOR_VIDEOS — Add columns missing from migration 003
-- (migration 003 has a stripped-down schema; these columns exist
--  in schema.sql but may not exist if 003 was the actual DDL run)
-- =============================================

ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS airtable_record_id TEXT;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS our_video TEXT;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS topic_cluster TEXT;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS curiosity_structure TEXT;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS structure_confidence NUMERIC;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS thumbnail_style_json TEXT;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS yin_yang_approach TEXT;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS yin_yang_text TEXT;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS analysis_date DATE;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS modeled_by_us BOOLEAN DEFAULT false;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS our_ctr_result NUMERIC;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS modeled_at TIMESTAMPTZ;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS our_video_id UUID REFERENCES videos(id);
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

-- Add unique constraint if not exists (idempotent via DO block)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'competitor_videos_tenant_video_unique'
  ) THEN
    ALTER TABLE competitor_videos ADD CONSTRAINT competitor_videos_tenant_video_unique
      UNIQUE (tenant_id, video_id);
  END IF;
END $$;

-- Add VPH index for autopilot ranking
CREATE INDEX IF NOT EXISTS idx_competitor_videos_vph ON competitor_videos(vph DESC);
CREATE INDEX IF NOT EXISTS idx_competitor_videos_modeled ON competitor_videos(modeled);

-- =============================================
-- AUTOPILOT_CONFIG — Create if not exists
-- =============================================

CREATE TABLE IF NOT EXISTS autopilot_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) UNIQUE,
    enabled BOOLEAN DEFAULT TRUE,
    videos_per_month INT DEFAULT 15,
    production_interval_days INT DEFAULT 2,
    weights JSONB DEFAULT '{"competitor_vph": 0.55, "timing_freshness": 0.45}'::jsonb,
    thresholds JSONB DEFAULT '{
        "min_confidence_score": 60,
        "min_competitor_vph": 50,
        "max_idea_age_days": 7,
        "ctr_success_threshold": 4.0,
        "ctr_failure_threshold": 2.5
    }'::jsonb,
    last_cycle TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE autopilot_config ENABLE ROW LEVEL SECURITY;

-- Use same RLS pattern as other tables
-- Check both policy name variants (migration 003 used lowercase, schema.sql uses capitalized)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'autopilot_config'
      AND (policyname = 'Tenant isolation' OR policyname = 'tenant_isolation')
  ) THEN
    CREATE POLICY "Tenant isolation" ON autopilot_config FOR ALL TO authenticated
      USING (tenant_id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid())));
  END IF;
END $$;

-- =============================================
-- LEARNINGS — Add missing columns from schema.sql
-- (migration 003 version is missing these)
-- =============================================

ALTER TABLE learnings ADD COLUMN IF NOT EXISTS airtable_record_id TEXT;
ALTER TABLE learnings ADD COLUMN IF NOT EXISTS detail TEXT;
ALTER TABLE learnings ADD COLUMN IF NOT EXISTS created_date DATE;
ALTER TABLE learnings ADD COLUMN IF NOT EXISTS last_updated DATE;

-- Fix type mismatch: migration 003 created source_videos as JSONB,
-- but sync script writes plain strings via _str(). Normalize to TEXT.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'learnings' AND column_name = 'source_videos' AND data_type = 'jsonb'
  ) THEN
    ALTER TABLE learnings ALTER COLUMN source_videos TYPE TEXT USING source_videos::TEXT;
  END IF;
END $$;

-- Add unique constraint on airtable_record_id if not exists (needed for upsert)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'learnings_airtable_record_id_key'
  ) THEN
    ALTER TABLE learnings ADD CONSTRAINT learnings_airtable_record_id_key UNIQUE (airtable_record_id);
  END IF;
EXCEPTION WHEN duplicate_object THEN
  NULL; -- constraint already exists under different name
END $$;
