-- Per-channel video retention.
--
-- Only channels explicitly listed in channel_video_retention are capped. The
-- initial policy applies to Designed vs Used and keeps its 10 newest videos.
-- Other StoryEngine workspaces are untouched.
--
-- Deleting an old video also deletes its video-owned scripts/assets/stage rows
-- through their existing CASCADE foreign keys. Historical analytics and source
-- records survive with their optional video link cleared. External Google Drive
-- and object-storage files are not deleted by this migration.

BEGIN;

CREATE TABLE IF NOT EXISTS channel_video_retention (
  tenant_id UUID PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
  max_videos INTEGER NOT NULL CHECK (max_videos > 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Designed vs Used only. Upsert makes the migration idempotent.
INSERT INTO channel_video_retention (tenant_id, max_videos)
VALUES ('561b872d-7b73-45e3-9c44-7f30c3566eda', 10)
ON CONFLICT (tenant_id) DO UPDATE
SET max_videos = EXCLUDED.max_videos,
    updated_at = now();

-- These audit/source tables should survive retention cleanup. Their video links
-- are optional, so make the intended behavior explicit instead of blocking the
-- hard delete.
ALTER TABLE bot_activity
  DROP CONSTRAINT IF EXISTS bot_activity_video_id_fkey,
  ADD CONSTRAINT bot_activity_video_id_fkey
    FOREIGN KEY (video_id) REFERENCES videos(id) ON DELETE SET NULL;

ALTER TABLE competitor_videos
  DROP CONSTRAINT IF EXISTS competitor_videos_our_video_id_fkey,
  ADD CONSTRAINT competitor_videos_our_video_id_fkey
    FOREIGN KEY (our_video_id) REFERENCES videos(id) ON DELETE SET NULL;

ALTER TABLE discovery_ideas
  DROP CONSTRAINT IF EXISTS discovery_ideas_launched_video_id_fkey,
  ADD CONSTRAINT discovery_ideas_launched_video_id_fkey
    FOREIGN KEY (launched_video_id) REFERENCES videos(id) ON DELETE SET NULL;

CREATE OR REPLACE FUNCTION enforce_channel_video_retention()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  retention_limit INTEGER;
BEGIN
  SELECT max_videos
  INTO retention_limit
  FROM channel_video_retention
  WHERE tenant_id = NEW.tenant_id;

  -- No configured policy means no deletion for this channel.
  IF retention_limit IS NULL THEN
    RETURN NEW;
  END IF;

  -- Serialize retention decisions for one tenant. This prevents simultaneous
  -- inserts from both observing the old count and leaving an extra row behind.
  PERFORM pg_advisory_xact_lock(hashtextextended(NEW.tenant_id::text, 0));

  DELETE FROM videos
  WHERE tenant_id = NEW.tenant_id
    AND id IN (
      SELECT id
      FROM videos
      WHERE tenant_id = NEW.tenant_id
      ORDER BY created_at DESC NULLS LAST, id DESC
      OFFSET retention_limit
    );

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS videos_enforce_tenant_retention ON videos;
DROP TRIGGER IF EXISTS videos_enforce_channel_retention ON videos;
CREATE TRIGGER videos_enforce_channel_retention
AFTER INSERT ON videos
FOR EACH ROW
EXECUTE FUNCTION enforce_channel_video_retention();

-- Bring only explicitly configured channels under their cap on migration.
WITH ranked AS (
  SELECT
    v.id,
    row_number() OVER (
      PARTITION BY v.tenant_id
      ORDER BY v.created_at DESC NULLS LAST, v.id DESC
    ) AS retention_rank,
    r.max_videos
  FROM videos v
  JOIN channel_video_retention r ON r.tenant_id = v.tenant_id
)
DELETE FROM videos
WHERE id IN (
  SELECT id FROM ranked WHERE retention_rank > max_videos
);

COMMENT ON TABLE channel_video_retention IS
  'Opt-in per-channel cap for complete StoryEngine video records.';
COMMENT ON FUNCTION enforce_channel_video_retention() IS
  'Hard-deletes videos older than an explicitly configured channel retention cap.';

COMMIT;
