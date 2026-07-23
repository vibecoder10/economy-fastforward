-- 117: one scripts row per (video, scene) — enforce what every reader and
-- writer already assumes.
--
-- Bug this closes: nothing stopped two scripts rows from sharing the same
-- scene number for one video. A raced/retried script write left exactly that
-- on prod (2 videos, June 2026): the pipeline page rendered both rows as
-- "Scene 1" (React "two children with the same key" error), and every
-- per-scene action — stage runs, asset joins, voice, storyboards — became
-- ambiguous, since the whole app addresses scenes by number.
--
-- Every current write path is already compatible: user_script.py and
-- pipeline_executor.py either DELETE the video's rows before re-inserting or
-- do UPDATE-then-INSERT-WHERE-NOT-EXISTS. Under this index a future race
-- fails loudly on the second insert instead of silently duplicating a scene.
--
-- Partial (scene IS NOT NULL): Airtable-era imports can leave scene NULL
-- (the API backfills display numbers at read time); those rows stay legal.
-- The 4 duplicate rows that existed were deleted (keep-newest-per-scene)
-- before this migration shipped, so CREATE will not collide on prod.
--
-- Idempotent (IF NOT EXISTS).

CREATE UNIQUE INDEX IF NOT EXISTS scripts_video_scene_unique
  ON scripts (video_id, scene)
  WHERE scene IS NOT NULL;

COMMENT ON INDEX scripts_video_scene_unique IS
  'one script row per (video, scene); partial — Airtable-era rows with NULL scene are exempt';
