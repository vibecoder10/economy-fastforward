-- YouTube now exposes separate daily call buckets for videos.insert and
-- search.list. Keep units_used as the general Data API bucket and add the
-- two call counters without changing or reinterpreting historical rows.
BEGIN;

ALTER TABLE youtube_quota_usage
  ADD COLUMN IF NOT EXISTS video_uploads_used INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS search_calls_used INTEGER NOT NULL DEFAULT 0;

COMMIT;
