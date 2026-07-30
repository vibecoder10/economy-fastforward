-- Migration 152 (D9-3): harvest EnvironmentLock-grade fields from the
-- dormant Custom Film system into the flagship's locations. Custom Film's
-- EnvironmentLock (backend/custom_film_director.py:176-197) proved a
-- location description needs to split into narrower, more BINDING facts
-- than one prose blob: architecture_lock (immutable structural facts),
-- lighting_time_weather_lock (the exact light/time/weather), and
-- palette_lock (the fixed color palette). This migration adds the same
-- three concepts to video_environments — nullable, additive, mirrors
-- migration 151's video_characters shape (face_body_lock/wardrobe_lock/
-- forbidden_drift) exactly: NULL means "not authored yet", every existing
-- row and every existing consumer keeps working byte-identical until these
-- are populated.
--
-- geography_lock (the fourth Custom Film EnvironmentLock field) is
-- DELIBERATELY NOT harvested here: the flagship already has its own,
-- older, more thorough treatment of "where a location sits relative to
-- everything else" — the L3 LOCATION SCOPING law (story_laws.
-- check_scene_location_law / check_location_transit_law, migrations
-- 143/144) governs per-scene location assignment and transit continuity
-- across the whole film, which is what Custom Film's single per-location
-- geography_lock sentence is a much smaller version of. Adding a second,
-- narrower geography concept here would compete with the law that already
-- covers this ground instead of extending it.
--
-- Populated at environment-approval time (routes/environments.py's
-- approve_environments), extending the SAME vision call that already
-- rewrites `description` from the approved reference pixels — ONE paid
-- call, not two. A parse failure on any of the three leaves that column
-- untouched (NULL on a first approval) and logs a warning; it never fails
-- the approval. Mirrors migration 151's populate mechanism exactly.
--
-- All three are consumed VERBATIM (same precedence philosophy as
-- material_map, migration 142: "canonical beats planner prose") by the
-- board-sheet-preview prompt composer and the redraw/repair leg
-- (scripts/coverage_to_app.py's _canonical_environment_locks_line /
-- _env_locks_text and their callers) — inserted as their own ENVIRONMENT
-- LOCKS block/clause, WINS over whatever the scene text or planner
-- happened to imply, whenever populated.
--
-- Idempotent.

ALTER TABLE video_environments ADD COLUMN IF NOT EXISTS architecture_lock TEXT;
ALTER TABLE video_environments ADD COLUMN IF NOT EXISTS lighting_time_weather_lock TEXT;
ALTER TABLE video_environments ADD COLUMN IF NOT EXISTS palette_lock TEXT;

COMMENT ON COLUMN video_environments.architecture_lock IS
  'D9-3: immutable structural facts (walls, floors, ceiling, fixed structural features, layout), extracted from the approved reference pixels at environment-approval time -- mirrors Custom Film''s EnvironmentLock.architecture_lock (custom_film_director.py:176-197). Read VERBATIM into board/final-picture ENVIRONMENT LOCKS blocks, taking precedence over description''s corresponding aspects. NULL = not yet extracted, falls back to description exactly as before this column existed.';

COMMENT ON COLUMN video_environments.lighting_time_weather_lock IS
  'D9-3: the exact lighting, time of day, and weather visible in the approved reference (precise enough that a different generation run would redraw the identical light and atmosphere), extracted at environment-approval time -- mirrors Custom Film''s EnvironmentLock.lighting_time_weather_lock. Same VERBATIM/precedence contract as architecture_lock.';

COMMENT ON COLUMN video_environments.palette_lock IS
  'D9-3: this location''s fixed color palette (dominant + accent colors), extracted at environment-approval time -- mirrors Custom Film''s EnvironmentLock.palette_lock. Same VERBATIM/precedence contract as architecture_lock.';
