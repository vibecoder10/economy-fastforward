-- Migration 047: Visual style proof frames
-- Stores a generated example frame and explicit creator approval for a style.

ALTER TABLE visual_styles
  ADD COLUMN IF NOT EXISTS proof_image_url TEXT,
  ADD COLUMN IF NOT EXISTS proof_drive_url TEXT,
  ADD COLUMN IF NOT EXISTS proof_drive_file_id TEXT,
  ADD COLUMN IF NOT EXISTS proof_prompt TEXT,
  ADD COLUMN IF NOT EXISTS proof_model TEXT,
  ADD COLUMN IF NOT EXISTS proof_status TEXT DEFAULT 'not_generated',
  ADD COLUMN IF NOT EXISTS proof_generated_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS proof_approved_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_visual_styles_proof_status
  ON visual_styles(project_id, proof_status);
