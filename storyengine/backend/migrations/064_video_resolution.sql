-- 064: per-video clip resolution (quality selector).
--
-- Grok-imagine renders at 480p by default, which is low for a 16:9 YouTube
-- upload. It also supports 720p. This column lets the creator pick the clip
-- quality up front; it flows into clip generation (passed to the generator as
-- the `resolution` param) the same way aspect_ratio does. Defaults to 720p so
-- new videos are YouTube-ready unless the creator opts down to 480p for cost.
ALTER TABLE videos
  ADD COLUMN IF NOT EXISTS video_resolution TEXT NOT NULL DEFAULT '720p'
  CHECK (video_resolution IN ('480p', '720p'));
