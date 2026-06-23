-- 062: per-scene stitched video URL.
--
-- After a scene's clips are all animated we FFmpeg-concat them into ONE clip so
-- the creator can watch the whole scene (and the final render just concats the
-- per-scene stitches). The stitched mp4 lives at scenes/S{NN}.mp4 in storage;
-- this column points the UI at it. NULL until the scene is fully animated +
-- stitched; re-stitched in place when a clip changes.
ALTER TABLE scripts
  ADD COLUMN IF NOT EXISTS scene_video_url TEXT;
