-- AUTOPILOT_PROPOSALS (migration 108 — checklist C51, P4.2-b candidate
-- auto-launch loop, propose_only dial-level).
--
-- A propose_only-dial dry run never creates a video, never dispatches the
-- pipeline, never spends money — it only records here that "candidate X
-- scored above the tenant's min_confidence_score threshold and was the
-- best available pick this cadence window." A human (C52's UI/chat
-- surface) turns a proposal into a real launch by calling the SAME
-- routes.autopilot.launch_candidate path a manual click already uses; this
-- table never gates or replaces that call — it only stops the auto-launch
-- loop (backend/autopilot_launch.py) from re-proposing the same
-- competitor_videos row while a proposal is still undecided
-- (status='proposed').
--
-- Row shape:
--   candidate_id           -- competitor_videos.id this proposal scored.
--   video_title            -- snapshot of the candidate's title at
--                             proposal time (competitor_videos rows can be
--                             re-scraped/updated later; the proposal keeps
--                             what was actually shown/decided on).
--   confidence_score       -- the total_score from
--                             routes.autopilot.calculate_confidence_with_breakdown
--                             at proposal time.
--   confidence_breakdown   -- jsonb snapshot of the full breakdown (vph/
--                             freshness/intelligence sub-scores + reasoning
--                             strings) for a future proposals UI (C52).
--   status                 -- 'proposed' (the only status this chunk ever
--                             writes) -> 'accepted' | 'dismissed' (C52's
--                             job, a human decision) | 'expired' (reserved
--                             for a future housekeeping sweep; no writer
--                             sets it yet in this chunk).
--   decided_at/decided_by  -- stamped on the transition OUT of 'proposed'
--                             (C52); NULL for a still-undecided row.
--   video_id               -- set if/when an 'accepted' proposal's launch
--                             creates a video (C52); NULL until then.
--
-- Idempotent (CREATE TABLE IF NOT EXISTS / IF NOT EXISTS index) — applied
-- LIVE via the Supabase MCP against project wrromlupsmyzrrcqlucn, confirmed
-- via information_schema.columns + pg_constraint, and re-applied a second
-- time with zero errors to prove idempotency (same pattern as migrations
-- 088-107).
--
-- RLS: enabled, NO policies (same playbook as channel_patterns/quality_rules
-- above — backend connects as the postgres role, bypasses RLS via
-- rolbypassrls=true; this only closes the public PostgREST/anon/
-- authenticated path).

CREATE TABLE IF NOT EXISTS autopilot_proposals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  candidate_id UUID NOT NULL REFERENCES competitor_videos(id) ON DELETE CASCADE,
  video_title TEXT NOT NULL,
  confidence_score NUMERIC NOT NULL DEFAULT 0,
  confidence_breakdown JSONB,
  status TEXT NOT NULL DEFAULT 'proposed'
    CHECK (status IN ('proposed', 'accepted', 'dismissed', 'expired')),
  decided_at TIMESTAMPTZ,
  decided_by TEXT,
  video_id UUID REFERENCES videos(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS autopilot_proposals_tenant_status_idx
  ON autopilot_proposals (tenant_id, status);

CREATE INDEX IF NOT EXISTS autopilot_proposals_tenant_candidate_idx
  ON autopilot_proposals (tenant_id, candidate_id, status);

ALTER TABLE autopilot_proposals ENABLE ROW LEVEL SECURITY;
-- No policies (deny-all to anon/authenticated/PostgREST); backend bypasses
-- via table ownership + BYPASSRLS (see migration 083 for the proof).
