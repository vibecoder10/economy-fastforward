-- Migration 046: per-video character design (Creator Control Run, phase 2)
-- Spec: docs/superpowers/specs/2026-06-10-creator-control-run.md
--
-- Each video gets designed character references (AI-generated portrait per
-- Story Bible character, regenerable / replaceable by upload) that are
-- reviewed and approved before storyboards. Approved refs feed Nano Banana's
-- image_input for grids/scene images so the same character looks the same in
-- every frame. videos.characters_approved_at is the gate timestamp;
-- videos.character_reference_url keeps pointing at the primary character for
-- backward compatibility with the storyboard bot.
--
-- Idempotent.

CREATE TABLE IF NOT EXISTS video_characters (
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

CREATE INDEX IF NOT EXISTS idx_video_characters_video ON video_characters(video_id);
CREATE INDEX IF NOT EXISTS idx_video_characters_tenant ON video_characters(tenant_id);

ALTER TABLE video_characters ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS video_characters_tenant_isolation ON video_characters;
CREATE POLICY video_characters_tenant_isolation ON video_characters
  FOR ALL TO authenticated
  USING (
    tenant_id IN (
      SELECT m.tenant_id FROM memberships m
      WHERE m.user_id = (SELECT auth.uid())
    )
    OR tenant_id = current_setting('app.tenant_id', true)::uuid
  );

ALTER TABLE videos ADD COLUMN IF NOT EXISTS characters_approved_at TIMESTAMPTZ;
