-- Migration 018: Add unique constraint on (tenant_id, video_id) for competitor_videos
-- Required for UPSERT (ON CONFLICT) to work during scraping.
-- Without this, every INSERT fails with "there is no unique or exclusion constraint"

-- First deduplicate any existing rows (keep newest by updated_at)
DELETE FROM competitor_videos a
  USING competitor_videos b
  WHERE a.tenant_id = b.tenant_id
    AND a.video_id = b.video_id
    AND a.id < b.id;

-- Now add the constraint (IF NOT EXISTS not available for constraints, use DO block)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'competitor_videos_tenant_id_video_id_key'
  ) THEN
    ALTER TABLE competitor_videos ADD CONSTRAINT competitor_videos_tenant_id_video_id_key UNIQUE (tenant_id, video_id);
  END IF;
END $$;
