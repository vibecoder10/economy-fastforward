-- Data freshness (GOAL v2 Phase 1): soft-flag competitor videos that no longer
-- exist on YouTube (removed by uploader / made private). A liveness check
-- (videos.list by id) marks these; queries that surface "worth modeling" picks,
-- channel intelligence, and length anchors exclude removed_at IS NOT NULL so dead
-- videos stop being promoted as fresh top picks. Soft-flag (not delete) so rows we
-- already modeled keep their referential links.
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS removed_at TIMESTAMPTZ;
