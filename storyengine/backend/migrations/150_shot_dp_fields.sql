-- Migration 150 (D11-2): per-shot DP (director of photography) fields as
-- structured data — a follow-on to D11-1's shot-archetype library (migration
-- 149). The film-studio audit found the remaining CAMERA vocabulary — lens,
-- camera height, depth of field — still living ONLY as prose: the
-- channel-wide LensProfile (shared.channel_profile, injected once into the
-- coverage system prompt's <channel_style> block) and rule 11's per-panel
-- FOUR CAMERA FACTS, whose own storyboard.coverage.check_camera_facts_
-- present docstring admits facts (b) camera height and (c) frame-fraction
-- are "free prose with no fixed vocabulary to scan for... NOT mechanically
-- checkable today". Rule 11's own prose is UNCHANGED by this chunk — this is
-- additional, optional, structured data alongside it, not a replacement.
--
-- Same "repair-stamp" precedent as migration 147 (assets.purpose_kind /
-- assets.shot_purpose), migration 148 (assets.transition_kind / assets.
-- continuity_bridge / assets.caused_by), and migration 149 (assets.
-- shot_archetype): three columns, all nullable, additive.
--
-- assets.lens_mm INTEGER — a plain focal length in millimeters, parsed from
-- the planner's own per-shot "DP: <lens_mm> | <camera_height> | <dof>" row
-- (storyboard.coverage.parse_coverage's _DP_LINE_RE / _parse_dp_row, via
-- _strip_shot_metadata_rows) ONLY when that slot matched the taught
-- "<digits>mm" shape — no CHECK constraint enforcing the taught 10-200
-- range: storyboard.coverage.check_shot_dp_valid does that comparison at
-- read/parse time (WARN-only, D6 Ruling 1), not the database, same reasoning
-- migrations 147/148/149 give for skipping a DB-side enum/range constraint.
--
-- assets.camera_height TEXT — one of storyboard.coverage.CAMERA_HEIGHT_KINDS
-- (ground/low/waist/chest/eye/high/overhead), stored AS AUTHORED, lowercased,
-- with no CHECK constraint (same reasoning as above).
--
-- assets.dof TEXT — one of storyboard.coverage.DOF_KINDS (shallow/medium/
-- deep), stored AS AUTHORED, lowercased, with no CHECK constraint (same
-- reasoning as above).
--
-- All three NULL for the overwhelming majority of shots: the DP row is
-- entirely OPTIONAL (rule 28: "you MAY"), so every shot generated before
-- this migration AND any shot the planner simply chose not to tag going
-- forward, exactly mirroring migration 149's shot_archetype rollout.
--
-- Read-only from this migration's point of view — no backfill, existing
-- videos/assets keep working exactly as before with NULL; store_scene
-- (coverage_to_app.py) writes these going forward, from generate_coverage_
-- frames' frame dicts, which thread them straight from coverage.py's parsed
-- shot dicts (parse_coverage sets them directly via _strip_shot_metadata_
-- rows, same per-shot-at-parse-time shape as shot_archetype — no extra
-- per-shot copy loop needed).
--
-- Idempotent.

ALTER TABLE assets ADD COLUMN IF NOT EXISTS lens_mm INTEGER;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS camera_height TEXT;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS dof TEXT;

COMMENT ON COLUMN assets.lens_mm IS
  'D11-2 (per-shot DP fields as data, film-studio audit follow-on): this shot''s DP-planned focal length in millimeters, parsed from the planner''s own OPTIONAL per-shot "DP: <lens_mm> | <camera_height> | <dof>" row (storyboard.coverage.parse_coverage) — NULL for the overwhelming majority of shots (row/slot omitted, since tagging is optional, or a row generated before this migration)';
COMMENT ON COLUMN assets.camera_height IS
  'D11-2 (per-shot DP fields as data): this shot''s DP-planned camera height, one of storyboard.coverage.CAMERA_HEIGHT_KINDS (ground/low/waist/chest/eye/high/overhead), parsed from the same OPTIONAL "DP: ..." row — NULL for the overwhelming majority of shots';
COMMENT ON COLUMN assets.dof IS
  'D11-2 (per-shot DP fields as data): this shot''s DP-planned depth of field, one of storyboard.coverage.DOF_KINDS (shallow/medium/deep), parsed from the same OPTIONAL "DP: ..." row — NULL for the overwhelming majority of shots';
