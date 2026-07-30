-- 145_script_staleness_hash.sql
-- D7-2 (STORY-LAWS S6): a script edit must flag downstream cast/environments
-- as stale instead of silently leaving them pinned to text that no longer
-- matches — the exact bug that shipped a real production video with
-- characters the (already-rewritten) script no longer contained.
--
-- Generalizes the existing _scene_text_hash / coverage_directive_hash
-- pattern (scripts/coverage_to_app.py) from "one scene's saved coverage
-- plan" to "the whole videos.script text a cast/environment batch was
-- generated from": one hash per family, stored on the videos row (not per
-- video_characters/video_environments row) because a single
-- design_characters / run_environments_design_step call always (re)writes
-- the WHOLE cast/environment set together from the SAME script snapshot —
-- there is no case where two rows of the same family were stamped from two
-- different script states. characters_hash/environments_hash are
-- recomputed and compared on every write to videos.script
-- (routes/videos.py's sync_video_script — the D7-1/D7-1b choke point for
-- update_scene_text, rewrite_scene_text and chat.py's script save — plus
-- the Drive pull-sync and pipeline/Custom-Film inline-sync paths).
--
-- FLAG, NEVER DELETE: on a hash mismatch the matching family's
-- video_characters/video_environments rows get status='stale' — existing
-- reference images and descriptions are left completely intact so a
-- creator/reviewer can see exactly what needs a redraw, and a wrong
-- deletion never re-triggers a real-money re-generation.
ALTER TABLE videos ADD COLUMN IF NOT EXISTS characters_hash TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS environments_hash TEXT;

-- Both status columns were CHECK'd to ('draft', 'approved') only (migrations
-- 046 / 051) — no bucket for a staleness flag. Extend, don't replace, so
-- existing rows/values are unaffected.
ALTER TABLE video_characters DROP CONSTRAINT IF EXISTS video_characters_status_check;
ALTER TABLE video_characters ADD CONSTRAINT video_characters_status_check
  CHECK (status IN ('draft', 'approved', 'stale'));

ALTER TABLE video_environments DROP CONSTRAINT IF EXISTS video_environments_status_check;
ALTER TABLE video_environments ADD CONSTRAINT video_environments_status_check
  CHECK (status IN ('draft', 'approved', 'stale'));
