-- Migration 147 (D9-1): the missing per-shot "why does this shot exist"
-- signal — the 22-point film-studio audit found the flagship coverage
-- pipeline's planned shots carry NO motivation at all ({shot_type,
-- description} only), while the dormant Custom Film director's ShotDraft
-- HARD-requires narrative_purpose + progression_kinds on every shot
-- (backend/custom_film_director.py:279-284, progression_kinds enum: story/
-- action/information/emotion/spatial; narrative_purpose free prose). Ryan's
-- ruling: harvest that schema into the flagship. Enforcement is WARN-only
-- (storyboard.coverage.check_shot_purpose_present) per the standing D6
-- Ruling 1 — a gate may only be HARD when it compares against something
-- CANONICAL, and there is no canonical "correct" purpose to check a shot's
-- prose against, only whether the planner stated one at all.
--
-- Two columns, both nullable, both additive — same "repair-stamp" precedent
-- as migration 143's assets.shot_location / assets.group_arrangement:
--
-- 1. assets.purpose_kind TEXT — the shot's progression kind, ONE of story/
--    action/information/emotion/spatial (coverage.py's ShotDraft-mirrored
--    vocabulary), parsed from the planner's own per-shot "PURPOSE: <kind> |
--    <text>" row (storyboard.coverage.parse_coverage's _PURPOSE_LINE_RE) —
--    stored AS AUTHORED, lowercased, with no CHECK constraint against the
--    5-word vocabulary (there is no canonical enum persisted anywhere in
--    this system to check it against — same reasoning as skipping a hard
--    gate). NULL for a shot the planner didn't tag (every shot generated
--    before this migration, and any code-synthesized floor/filler shot
--    going forward — enforce_reaction_insert_floors' additions have no
--    LLM-authored prose to draw a purpose from).
--
-- 2. assets.shot_purpose TEXT — the free-prose "why this shot exists" text
--    from that same PURPOSE row (ShotDraft's narrative_purpose field,
--    extended with the audit's own taxonomy — reveal/tension/scale/
--    geography/introduction/transition/foreshadow — as ordinary words
--    inside this free text, never as a separate enum). NULL under the
--    same conditions as purpose_kind above.
--
-- Both columns are read-only from this migration's point of view — no
-- backfill, existing videos/assets keep working exactly as before with
-- NULLs; store_scene (coverage_to_app.py) writes them going forward, from
-- generate_coverage_frames' frame dicts, which thread them straight from
-- coverage.py's parsed shot dicts (parse_coverage sets them directly, no
-- extra per-shot copy loop needed — unlike shot_location, which is copied
-- onto each shot inside run_coverage from the moment-level "location"
-- field; purpose is already per-shot at parse time).
--
-- Idempotent.

ALTER TABLE assets ADD COLUMN IF NOT EXISTS purpose_kind TEXT;

COMMENT ON COLUMN assets.purpose_kind IS
  'D9-1 (Custom Film director ShotDraft harvest): this shot''s progression kind — one of story/action/information/emotion/spatial, parsed from the planner''s own per-shot "PURPOSE: <kind> | <text>" row (storyboard.coverage.parse_coverage) — NULL for a shot the planner didn''t tag or a row generated before this migration';

ALTER TABLE assets ADD COLUMN IF NOT EXISTS shot_purpose TEXT;

COMMENT ON COLUMN assets.shot_purpose IS
  'D9-1 (Custom Film director ShotDraft harvest): free-prose narrative_purpose text for this shot — why it exists, not what it shows — from the same per-shot "PURPOSE: <kind> | <text>" row — NULL under the same conditions as purpose_kind';
