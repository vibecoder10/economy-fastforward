-- Per-title video length for the "Run a title list" queue. Nullable, no
-- backfill — an item queued before this migration keeps launching a video
-- with no explicit length (existing behavior), while a new item can carry
-- its own length through to _prepare_video's videos INSERT so roster
-- selection has a real videos.video_length_minutes to read.

ALTER TABLE production_queue ADD COLUMN IF NOT EXISTS video_length_minutes NUMERIC;
