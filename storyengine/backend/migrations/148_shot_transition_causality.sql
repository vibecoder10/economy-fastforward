-- Migration 148 (D9-6/D9-7): the missing per-shot "how does this cut in" and
-- "what caused this shot to exist" signals — the second "Custom Film harvest"
-- chunk, mirroring migration 147's D9-1 pattern exactly. The dormant Custom
-- Film director's ShotDraft HARD-requires transition_from_previous +
-- continuity_bridge (backend/custom_film_director.py:288-291, :895-898) and
-- caused_by (:280, :882-884) on every shot; the flagship coverage pipeline
-- planned shots with no cut-type or causal-chain signal at all. Ryan's
-- ruling: harvest both into the flagship. Enforcement is WARN-only
-- (storyboard.coverage.check_shot_transition_present /
-- check_shot_transition_bridge_present / check_shot_causality_present /
-- check_shot_causality_valid) per the standing D6 Ruling 1 — a gate may only
-- be HARD when it compares against something CANONICAL, and there is no
-- canonical "correct" cut type or cause to check a shot's stated value
-- against — except caused_by's OWN internal reference (does the named label
-- exist, and is it earlier), which check_shot_causality_valid does check
-- deterministically, but Ryan's ruling keeps even that warn-only: a planner
-- mistake is worth a human glance, not grounds to block a draw.
--
-- Three columns, all nullable, all additive — same "repair-stamp" precedent
-- as migration 143's assets.shot_location / assets.group_arrangement and
-- migration 147's assets.purpose_kind / assets.shot_purpose:
--
-- 1. assets.transition_kind TEXT — the shot's cut type, ONE of opening/
--    continuous/time_cut/location_cut/montage/memory (coverage.py's
--    ShotDraft-mirrored TRANSITION_KINDS vocabulary), parsed from the
--    planner's own per-shot "TRANSITION: <kind> | <bridge>" row
--    (storyboard.coverage.parse_coverage's _TRANSITION_LINE_RE, via
--    _strip_shot_metadata_rows) — stored AS AUTHORED, lowercased, with no
--    CHECK constraint against the 6-word vocabulary (same reasoning as
--    migration 147 skipping one: no canonical enum persisted anywhere in
--    this system to check it against). NULL for a shot the planner didn't
--    tag (every shot generated before this migration, and any code-
--    synthesized floor/filler shot going forward).
--
-- 2. assets.continuity_bridge TEXT — the free-prose "what carries the viewer
--    across this cut" text from that same TRANSITION row (ShotDraft's
--    continuity_bridge field) — present only for a non-"continuous" kind
--    that stated one (the coverage prompt's rule 25 makes the bridge
--    optional exactly when the kind is "continuous"). NULL when the row is
--    absent, the kind is "continuous", or the planner stated a kind with no
--    bridge clause (flagged by check_shot_transition_bridge_present, not
--    blocked).
--
-- 3. assets.caused_by TEXT — a SINGLE reference to an earlier shot in the
--    same scene plan, in the label format "M<moment_number>-MASTER" or
--    "M<moment_number>-ANGLE<k>" (there is no LLM-assigned shot_key in the
--    flagship grammar the way Custom Film's ShotDraft.shot_key provides one,
--    so a moment/role label is what the planner can express reliably —
--    derivable from context it already wrote, never a running global shot
--    count). Parsed from the planner's own per-shot "CAUSED_BY: <label>" row
--    (_CAUSED_BY_LINE_RE). Stored AS AUTHORED (not normalized/uppercased —
--    check_shot_causality_valid does that comparison at read time). NULL for
--    a shot the planner didn't tag, INCLUDING the scene's very first shot,
--    which the prompt (rule 26) and check_shot_causality_present both
--    exempt from needing one at all (nothing precedes it to be caused by —
--    same exemption Custom Film's own HARD gate makes for its first shot,
--    custom_film_director.py:870-874).
--
-- All three columns are read-only from this migration's point of view — no
-- backfill, existing videos/assets keep working exactly as before with
-- NULLs; store_scene (coverage_to_app.py) writes them going forward, from
-- generate_coverage_frames' frame dicts, which thread them straight from
-- coverage.py's parsed shot dicts (parse_coverage sets them directly via
-- _strip_shot_metadata_rows, same per-shot-at-parse-time shape as
-- purpose_kind/shot_purpose — no extra per-shot copy loop needed).
--
-- Idempotent.

ALTER TABLE assets ADD COLUMN IF NOT EXISTS transition_kind TEXT;

COMMENT ON COLUMN assets.transition_kind IS
  'D9-6 (Custom Film director ShotDraft harvest): this shot''s cut type — one of opening/continuous/time_cut/location_cut/montage/memory, parsed from the planner''s own per-shot "TRANSITION: <kind> | <bridge>" row (storyboard.coverage.parse_coverage) — NULL for a shot the planner didn''t tag or a row generated before this migration';

ALTER TABLE assets ADD COLUMN IF NOT EXISTS continuity_bridge TEXT;

COMMENT ON COLUMN assets.continuity_bridge IS
  'D9-6 (Custom Film director ShotDraft harvest): free-prose "what carries the viewer across this cut" text for this shot, from the same per-shot "TRANSITION: <kind> | <bridge>" row — NULL when absent, when the kind is "continuous" (no bridge needed), or when a non-continuous kind was stated with no bridge clause (flagged by check_shot_transition_bridge_present, not blocked)';

ALTER TABLE assets ADD COLUMN IF NOT EXISTS caused_by TEXT;

COMMENT ON COLUMN assets.caused_by IS
  'D9-7 (Custom Film director ShotDraft harvest): a single reference to an earlier shot in the same scene plan, in the label format "M<moment_number>-MASTER" or "M<moment_number>-ANGLE<k>", parsed from the planner''s own per-shot "CAUSED_BY: <label>" row (storyboard.coverage.parse_coverage) — NULL for a shot the planner didn''t tag, including the scene''s very first shot, which is exempt (nothing precedes it)';
