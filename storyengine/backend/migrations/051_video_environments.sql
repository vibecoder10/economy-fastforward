-- Migration 051: per-video ENVIRONMENT locking (content-quality tightening, Fix #2)
--
-- Mirror of 046_video_characters but for LOCATIONS. Each video gets a designed
-- reference image per Story Bible location (sunny_garden, vet_examination_room,
-- …), reviewed + approved before storyboards. At grid time, the ONE location a
-- beat sits in is passed as a second image_input (alongside the cast sheet) so
-- the setting stays consistent across panels — exactly two refs, never more
-- (≥6 refs drifts characters; see pipeline_executor character-ref note).
--
-- video_environments.name == story_bible.locations[].id (snake_case join key).
-- videos.environments_approved_at is the gate timestamp (mirrors
-- characters_approved_at). assets.location_id is the structured per-panel
-- location (== block_location_id from the image-prompt stage) — the reliable
-- key that lets a grid resolve its dominant location at conditioning time.
--
-- Idempotent.

CREATE TABLE IF NOT EXISTS video_environments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,
  video_id UUID REFERENCES videos(id) ON DELETE CASCADE NOT NULL,
  name TEXT NOT NULL,            -- == story_bible.locations[].id (join key)
  description TEXT,              -- seeded from bible description + lighting
  reference_url TEXT,
  status TEXT DEFAULT 'draft' CHECK (status IN ('draft', 'approved')),
  source TEXT DEFAULT 'generated' CHECK (source IN ('generated', 'uploaded', 'project')),
  sort INT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_video_environments_video ON video_environments(video_id);
CREATE INDEX IF NOT EXISTS idx_video_environments_tenant ON video_environments(tenant_id);

ALTER TABLE video_environments ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS video_environments_tenant_isolation ON video_environments;
CREATE POLICY video_environments_tenant_isolation ON video_environments
  FOR ALL TO authenticated
  USING (
    tenant_id IN (
      SELECT m.tenant_id FROM memberships m
      WHERE m.user_id = (SELECT auth.uid())
    )
    OR tenant_id = current_setting('app.tenant_id', true)::uuid
  );

ALTER TABLE videos ADD COLUMN IF NOT EXISTS environments_approved_at TIMESTAMPTZ;

-- Structured per-panel location (== block_location_id from the image-prompt
-- stage). Lets a storyboard grid resolve its dominant location at grid time
-- and pick the matching environment ref. Null for legacy panels = safe skip.
ALTER TABLE assets ADD COLUMN IF NOT EXISTS location_id TEXT;
