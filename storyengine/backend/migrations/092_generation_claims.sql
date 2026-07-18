-- GENERATION_CLAIMS (checklist C16a — S7-1 CRITICAL + S7-6 MED fix, queue/
-- idempotency sweep, docs/reports/2026-07-17-storyengine-agent-audit-
-- findings.md §S7). The chat-driven autobuild/copilot dispatch
-- (routes/chat.py's _handle_approve/_run_pending_action -> actions.py's
-- make_autobuild_step/make_action_step) scheduled paid background work via a
-- bare background_tasks.add_task with ZERO concurrency guard — a double-tap
-- or retried chat turn ran two concurrent generation loops on the same
-- video. The existing guard (_running_tasks/_side_lanes in-process dicts,
-- routes/pipeline.py:139/152) is in-process only: wiped on every restart,
-- and chat never consulted it at all.
--
-- This table is the DB-backed authority both chat AND the manual
-- routes/pipeline.py (+ videos.py/environments.py/characters.py) endpoints
-- consult before dispatching paid work — see backend/generation_claims.py.
--
-- stage: the lane name ("main" for the exclusive full-pipeline lane —
--   script/storyboards/images/render/... and chat's whole-video autobuild —
--   or one of the independent side lanes: voice/characters/environments/
--   thumbnail). Mirrors routes/pipeline.py's existing _lane_begin/
--   _is_task_active lane vocabulary exactly (see generation_claims.py's
--   stage_for_verb + SIDE_LANES) so the DB claim and the in-process dict
--   never disagree about what counts as "main".
-- claimed_at: reset on every successful acquire; a claim older than 2 hours
--   is treated as stale and retaken (a crashed run must never wedge a
--   video for good — see generation_claims.acquire()).
-- claimed_by: free-text debug label (which dispatch site/verb took it),
--   nullable — never used for access control.
--
-- Idempotent (CREATE TABLE IF NOT EXISTS / IF NOT EXISTS index) — applied
-- LIVE via the Supabase MCP against project wrromlupsmyzrrcqlucn, confirmed
-- via information_schema.columns (same pattern as migrations 088-091: the
-- app's own migration runner tracks applied files by name in `_migrations`,
-- MCP applies land in Supabase's own tracking instead, so a restart may
-- re-run this file — IF NOT EXISTS makes that a no-op).
--
-- RLS: enabled, NO policies (playbook §7 pattern — the backend connects as
-- the `postgres` role, which bypasses RLS via rolbypassrls=true; this only
-- closes the public PostgREST/anon/authenticated path, proven safe already
-- for secrets/static_reference_cache/channel_video_retention/
-- director_preferences).

CREATE TABLE IF NOT EXISTS generation_claims (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
  stage TEXT NOT NULL,
  claimed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  claimed_by TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS generation_claims_unique
  ON generation_claims (tenant_id, video_id, stage);

ALTER TABLE generation_claims ENABLE ROW LEVEL SECURITY;
-- No policies (deny-all to anon/authenticated/PostgREST); backend bypasses
-- via table ownership + BYPASSRLS (see migration 083 for the proof).
