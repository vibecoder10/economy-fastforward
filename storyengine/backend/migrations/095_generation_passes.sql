-- GENERATION_PASSES (checklist C17 — §1.3 "Draft cheap, finish expensive",
-- S7 design requirements, docs/reports/2026-07-17-storyengine-agent-audit-
-- findings.md §S7 "C17 design requirements derived"). Durable identity for
-- a completed draft_pass/finalize pass, distinct from generation_claims
-- (migration 092): the claim guards CONCURRENT double-dispatch and is
-- released the instant a run ends; this table answers a different question
-- — "has THIS EXACT pass already run to completion?" — for a SEQUENTIAL
-- repeat that arrives after the claim was already released.
--
-- pass: 'draft_pass' | 'finalize'.
-- scene_set_hash: backend/generation_passes.py::scene_set_hash() — a hash of
--   the sorted (scene, target_model_id) pairs this pass covers, NOT just the
--   scene numbers, so a routing change (e.g. a model_override edit) on an
--   otherwise-identical scene set also counts as a legitimately new pass.
--
-- A row is written ONLY on successful completion (see generation_passes.py's
-- mark_done, called after run_clip_generation returns with no error) — a
-- failed run leaves no row, so it stays retryable with the identical scene
-- set. The UNIQUE index is the actual dedup mechanism: ON CONFLICT DO
-- NOTHING at insert time, checked via a SELECT before dispatch
-- (generation_passes.already_done) so a genuine repeat of the SAME pass is
-- told "already done" instead of re-billing; approving MORE scenes (or a
-- routing change) changes the hash, so it is never wrongly deduped.
--
-- Idempotent (CREATE TABLE IF NOT EXISTS / IF NOT EXISTS index) — apply via
-- the Supabase MCP against project wrromlupsmyzrrcqlucn, confirm via
-- information_schema.columns (same pattern as migrations 088-094).
--
-- RLS: enabled, NO policies (playbook §7 pattern — the backend connects as
-- the `postgres` role, which bypasses RLS via rolbypassrls=true; proven safe
-- already for generation_claims/director_preferences/secrets etc.).

CREATE TABLE IF NOT EXISTS generation_passes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
  pass TEXT NOT NULL,
  scene_set_hash TEXT NOT NULL,
  completed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS generation_passes_unique
  ON generation_passes (tenant_id, video_id, pass, scene_set_hash);

ALTER TABLE generation_passes ENABLE ROW LEVEL SECURITY;
-- No policies (deny-all to anon/authenticated/PostgREST); backend bypasses
-- via table ownership + BYPASSRLS (see migration 083 for the proof).
