-- D5 chunk A1 (FRAME-ARBITER-PLAN.md): two new OPTIONAL columns on the
-- existing generation_ledger table (migration 087), not a new table.
--
-- Frame Arbiter QA spend and arbiter-triggered repairs are metered as
-- generation_ledger rows with stage='frame_qa' — same "one row per paid
-- unit" convention every other stage already uses (generation_ledger.py's
-- record_ledger_entry, checklist §0.3/C07). Two things that stage needs
-- that no existing row shape carries:
--
--   * scene INTEGER — the per-scene $0.25 cap (FRAME-ARBITER-PLAN DoC #3)
--     has nothing to group by without this. Every other stage's cap
--     (actions.budget_check/budget_refusal) is per-VIDEO only
--     (videos.max_spend vs SUM(actual_cost) for the whole video) — frame_qa
--     is the first stage that needs a tighter, per-scene ceiling, and
--     generation_ledger has never carried a scene number.
--   * fingerprint TEXT — the learning-ratchet's repeat-failure key
--     (rule_id/failure_class, stage, failure_class — see the plan's
--     "Learning-ratchet mechanics" section). A2 owns the fingerprint TABLE
--     (violation counts, frozen flag); this column is just A1's ledger-row
--     tag so a frame_qa spend row can be traced back to which fingerprint
--     it was judging/repairing, independent of whatever table A2 lands.
--
-- Both columns are NULLable with no default and no backfill — every
-- existing generation_ledger row (every stage other than frame_qa) keeps
-- scene=NULL, fingerprint=NULL forever; this is purely additive, byte-
-- identical behavior for every reader that doesn't know these columns
-- exist yet (video_summary's total_cost rollup, the dashboard spend tiles,
-- migration 093's dedup index — none of them reference scene or
-- fingerprint, so none of them change behavior).
--
-- No CHECK constraint tying scene/fingerprint to stage='frame_qa' on
-- purpose — a future stage may legitimately want a scene-scoped ledger row
-- too (e.g. a per-scene image cap), and this column shouldn't have to be
-- renamed for that. frame_qa is the only stage that WRITES scene/
-- fingerprint today; that's enforced by backend/frame_arbiter_budget.py's
-- writer, not by the schema.

ALTER TABLE generation_ledger ADD COLUMN IF NOT EXISTS scene INTEGER;
ALTER TABLE generation_ledger ADD COLUMN IF NOT EXISTS fingerprint TEXT;

-- Partial index scoped to frame_qa rows only (the only stage that filters
-- by scene today) — mirrors idx_generation_ledger_video's shape, narrowed
-- so the guard's per-scene SUM(actual_cost) read (backend/
-- frame_arbiter_budget.py::_frame_qa_spend) doesn't scan every stage's rows
-- for a video with heavy clip/image spend.
CREATE INDEX IF NOT EXISTS idx_generation_ledger_frame_qa_scene
  ON generation_ledger (video_id, scene)
  WHERE stage = 'frame_qa';
