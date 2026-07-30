-- Migration 143 (D6-2): the missing per-shot signals BOARD-LAWS.md L17
-- (LOCK THE HEADCOUNT) and L22 (STATE GROUP ARRANGEMENT PER CAMERA
-- POSITION) need — confirmed live against the 52-column `assets` table
-- (D6 sweep, 2026-07-29): there is NO per-shot LOCATION column (location_id
-- is scene-level, not per-panel) and NO GROUP ARRANGEMENT column anywhere.
-- The per-moment location and the computed group arrangement both already
-- exist only in memory during coverage planning (storyboard/coverage.py's
-- run_coverage) and were, until this migration, only ever baked into shot
-- prose — never persisted as data. This is that missing signal, made real.
--
-- Two columns, both nullable, both additive:
--
-- 1. assets.shot_location TEXT — the per-shot/per-moment location name
--    (coverage.py's moment["location"], set by parse_coverage from a
--    "LOCATION: <name> | " moment-header prefix — L3's multi-location
--    schema). A single-location scene's shots persist NULL, unchanged from
--    the prior "location only exists in the scene-level [SET|...] prose"
--    behavior. NOT a foreign key to video_environments — this is the
--    PLANNER'S OWN per-moment location label, which may or may not match
--    an approved environment name; that matching already happens
--    separately (coverage_to_app._match_scene_env).
--
-- 2. assets.group_arrangement TEXT — the text stating who is where AS SEEN
--    FROM THIS CAMERA (L22's own phrasing), computed by
--    storyboard.coverage.apply_group_arrangement_lock: the establishing
--    shot's own stated arrangement, OR — for a later shot on the matched
--    REVERSE of that establishing setup — the MECHANICALLY FLIPPED order
--    (compute_reverse_arrangement: the ordered clauses reversed, frame-
--    left/frame-right swapped), computed from the [SETUPS|...] line's own
--    "the matched reverse of X" phrasing (parse_reverse_setup_pairs) —
--    never re-asked of a model. NULL for any shot with no group/headcount
--    content at all (the overwhelming majority of shots), and for legacy
--    coverage rows generated before this migration.
--
-- Both columns are read-only from this migration's point of view — no
-- backfill, existing videos/assets keep working exactly as before with
-- NULLs; store_scene (coverage_to_app.py) writes them going forward,
-- redraw_asset_image fresh-re-derives L16/L22 at redraw time using the
-- SAME parse_reverse_setup_pairs/compute_reverse_arrangement functions
-- against the scene's persisted coverage_directive, so a later fix to
-- those functions heals an OLD shot's next redraw without regenerating the
-- scene.
--
-- Idempotent.

ALTER TABLE assets ADD COLUMN IF NOT EXISTS shot_location TEXT;

COMMENT ON COLUMN assets.shot_location IS
  'D6-2 (L3/L17/L22): the per-shot/per-moment location name persisted from coverage.py''s in-memory moment["location"] (parse_coverage''s "LOCATION: <name> | " prefix) — NULL for a single-location scene or any row generated before this migration';

ALTER TABLE assets ADD COLUMN IF NOT EXISTS group_arrangement TEXT;

COMMENT ON COLUMN assets.group_arrangement IS
  'D6-2 (L17 LOCK THE HEADCOUNT + L22 STATE GROUP ARRANGEMENT PER CAMERA POSITION): who is where AS SEEN FROM THIS CAMERA — the establishing shot''s own stated arrangement, or a computed reverse-angle flip for a matched-reverse setup (storyboard.coverage.apply_group_arrangement_lock / compute_reverse_arrangement) — NULL for a shot with no group content or a row generated before this migration';
