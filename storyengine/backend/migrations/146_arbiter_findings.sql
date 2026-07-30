-- D8 chunk 3b (found by D8-3, storyengine/FRAME-ARBITER-PLAN.md): the GAP
-- that chunk surfaced was structural, not cosmetic. frame_arbiter.py's judge
-- calls (judge_frame / judge_scene_batch / judge_board_sheet) each return a
-- per-instance "findings" list — one dict per frame or panel, carrying an
-- image reference, a classification, and a human-readable description — but
-- that list only ever lived in the HTTP response of the call that produced
-- it. frame_arbiter_hook.run_after_storyboard_sheet attached it to
-- run_storyboard_sheet's own return value, which task_store.db_persist_task
-- never stores (a status + a message STRING only, no JSON payload). So the
-- Review feed's Findings tab (routes/review.py get_findings, merged D8-3)
-- could only show two REAL, already-persisted tables: arbiter_fingerprints
-- (migration 139, a CLASS of defect, not a single instance) and
-- generation_ledger frame_qa rows (migration 140, spend, not content). This
-- table is the missing per-instance layer both of those were always meant to
-- sit alongside.
--
-- Field names are copied verbatim from the THREE finding-dict shapes
-- frame_arbiter.py's judge functions actually return (read that module
-- before touching this file — the plan's own "do not invent a parallel
-- vocabulary" law): judge_frame's dict has image_index/shot_type/
-- neighbor_indices/cost/usage; judge_scene_batch's per-frame dict has
-- image_index/shot_type/new_vs_previous (cost/usage are call-level, one
-- ledger row per call, per that function's own comment); judge_board_sheet's
-- per-panel dict has panel/label/expected_set/new_vs_previous (cost/usage
-- again call-level). classification/failure_class/rule_id/rubric_level/
-- decisive_prompt_fragment/description are the one shared vocabulary all
-- three share (parse_verdict's own output shape) — those columns are named
-- IDENTICALLY to the dict keys, no renaming.
--
-- Because "image_index" (frame station) and "panel" (board station) are two
-- different identity vocabularies for the same idea — which sheet-or-frame,
-- within this station, is this finding about — they are folded into one
-- generic `reference` TEXT column here (e.g. "image_index 108" or
-- "panel 3"), tagged by `station` so a reader can always tell which
-- vocabulary produced it. `label` carries the frame's own `shot_type` or the
-- board panel's own `label`, when the judge call provided one — free text,
-- not re-parsed. This is a deliberate, documented generalization (not
-- invented vocabulary): frame_arbiter_hook.py today only ever calls
-- judge_board_sheet (the board station), but the table is shaped to also
-- hold judge_frame/judge_scene_batch rows without a second migration, since
-- all three already return the identical parse_verdict-derived fields.
--
-- `cost` is the call's own real dollar cost (frame_arbiter.usage_cost, read
-- off the vision response's usage block, never estimated) — for
-- judge_scene_batch/judge_board_sheet this is a CALL-level figure (one
-- vision call judges N frames/panels at once, see those functions' own
-- ledger-write comments) duplicated onto every finding row that call
-- produced, not a per-finding share; summing this column across multiple
-- rows from the SAME call double-counts spend. generation_ledger (migration
-- 140) remains the one authoritative SUM-safe spend table; this column
-- exists only so a single finding row is self-describing without a join.
--
-- `fingerprint_key` mirrors arbiter_fingerprints.fingerprint_key(rule_id,
-- failure_class) (migration 139) — NOT a foreign key to that table, for the
-- exact reason 139's own rule_id column isn't one: an instance row must be
-- writable before/independent of that table's upsert, and a finding whose
-- classification is OK never touches arbiter_fingerprints at all (A2's
-- record_finding only fires for the three defect buckets) but still gets a
-- row here, still carrying its own computed fingerprint_key.
--
-- RLS: enabled + REVOKE ALL FROM anon, authenticated (no policies) — the
-- same pattern 139/145 use; backend bypasses via table ownership + BYPASSRLS
-- (migration 083's proof).
--
-- $0 to build — pure data-layer chunk. Persistence-writing wiring lands in
-- the SAME chunk (backend/frame_arbiter_hook.py), advisory only: a write
-- failure here must never fail the storyboard stage or skip the freeze/
-- budget logic that already runs around it (see that file's own comment at
-- the write call site).

BEGIN;

CREATE TABLE IF NOT EXISTS arbiter_findings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
  scene INTEGER,
  station TEXT NOT NULL CHECK (station IN ('frame', 'scene_batch', 'board')),
  reference TEXT NOT NULL CHECK (length(reference) > 0),
  label TEXT,
  image_url TEXT,
  classification TEXT NOT NULL CHECK (classification IN ('MODEL_DEFECT', 'AUTHORING_DEFECT', 'TASTE_QUESTION', 'OK')),
  failure_class TEXT,
  rule_id TEXT,
  fingerprint_key TEXT,
  rubric_level TEXT,
  decisive_prompt_fragment TEXT,
  description TEXT,
  new_vs_previous TEXT,
  cost NUMERIC,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The Findings tab's own natural read shape: latest instances for a tenant,
-- optionally narrowed to one video/scene (mirrors idx_generation_ledger_
-- frame_qa_scene's (video_id, scene) shape from migration 140).
CREATE INDEX IF NOT EXISTS arbiter_findings_tenant_created_idx
  ON arbiter_findings (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS arbiter_findings_video_scene_idx
  ON arbiter_findings (video_id, scene);

ALTER TABLE arbiter_findings ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON arbiter_findings FROM anon, authenticated;

COMMIT;
