-- generation_ledger: the actual-spend receipt table backing videos.total_cost.
-- Checklist §0.3 (tasks/storyengine-wiring-fix-checklist.md, C07/P0.3a): the
-- cost counter was wrong — price estimates were duplicated in 3 places and
-- videos.total_cost was never rolled up from real spend (it just sat at its
-- DEFAULT 0 forever). This table is the single write path into total_cost
-- going forward: backend/generation_ledger.py::record_ledger_entry() inserts
-- one row per completed paid-generation unit, then recomputes
-- `videos.total_cost = SUM(actual_cost)` for that video — never an
-- incremental add, so retries can't double-count.
--
-- C07 wires the FIRST call site only (pipeline_executor.run_clip_generation —
-- one row per completed clip). C08 adds images/voice/thumbnail/sound.
--
-- Reconciled with existing cost columns (S6 finding): stage_transitions.cost
-- and bot_activity.cost already exist and overlap this table's purpose, but
-- neither ever rolled up into videos.total_cost (see the callers — cost is
-- an informational activity-feed number written into rows that
-- /api/activity and /api/dashboard sum server-side per request; nothing
-- writes it back into videos.total_cost). Left as-is in C07 — not touched,
-- not double-counted against, possible deprecation candidate for a later
-- chunk once every stage's spend also flows through generation_ledger.
--
-- tenant_id is included per the S6 sweep's forward guidance (multi-tenant
-- correctness + a `(tenant_id, created_at)` index for tenant-spend queries),
-- matching the FK pattern used by stage_transitions/bot_activity below.
--
-- RLS: enabled with NO policies, mirroring migration 083's proven-safe
-- pattern (secrets / static_reference_cache / channel_video_retention) —
-- the backend connects as the `postgres` role (rolbypassrls = true), so
-- this only closes the public PostgREST/anon/authenticated access path; it
-- does not affect the backend's own reads/writes.

CREATE TABLE IF NOT EXISTS generation_ledger (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) NOT NULL,
  video_id UUID REFERENCES videos(id) ON DELETE CASCADE NOT NULL,
  stage TEXT NOT NULL,
  model TEXT,
  units NUMERIC NOT NULL DEFAULT 1,
  unit_cost NUMERIC NOT NULL DEFAULT 0,
  actual_cost NUMERIC NOT NULL DEFAULT 0,
  kie_task_id TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Rollup reads: SUM(actual_cost) WHERE video_id = $1 (record_ledger_entry).
CREATE INDEX IF NOT EXISTS idx_generation_ledger_video ON generation_ledger(video_id);
-- Tenant spend queries over a date range.
CREATE INDEX IF NOT EXISTS idx_generation_ledger_tenant_created ON generation_ledger(tenant_id, created_at);

ALTER TABLE generation_ledger ENABLE ROW LEVEL SECURITY;
