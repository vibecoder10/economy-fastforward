-- Migration 039: Add updated_at to content_intelligence
-- Fixes: re-distillation was overwriting created_at instead of tracking update time

ALTER TABLE content_intelligence
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

-- Backfill existing rows
UPDATE content_intelligence SET updated_at = created_at WHERE updated_at IS NULL;
