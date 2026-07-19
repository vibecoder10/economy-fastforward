-- youtube_quota_usage: the YouTube Data API quota guard's counter (checklist
-- §3.4, C33 — docs/reports/2026-07-17-storyengine-agent-audit-findings.md
-- Sweep 3 finding #4: "YouTube quota (10k units/day ~ 6 uploads) documented
-- but not enforced in code").
--
-- GLOBAL scope, no tenant_id: YouTube's 10,000-units/day quota is billed to
-- a Google Cloud PROJECT, and every tenant's OAuth token here is minted from
-- the SAME OAuth client (one shared GOOGLE_OAUTH_CLIENT_ID/SECRET env-var
-- pair — youtube_publish.py, routes/youtube_sync.py, routes/google_auth.py
-- all read those same two env vars; there is no per-tenant client id). So
-- every tenant's Data API calls draw down the SAME pool — a per-tenant
-- counter would under-count the real cross-tenant risk. One row per
-- Pacific-Time calendar day (YouTube resets at midnight PT, not UTC —
-- backend/youtube_quota.py::_pt_today() computes the key in
-- America/Los_Angeles).
--
-- Not reusing generation_ledger (migration 087) on purpose: that table is
-- shaped for a different question ("what did THIS VIDEO cost in dollars",
-- video_id NOT NULL, actual_cost in USD). This counter has no video, no
-- tenant, and no dollar figure — forcing it through generation_ledger would
-- need nullable-video/tenant hacks for a worse fit than this 3-column table.
--
-- RLS: enabled with NO policies, matching the proven-safe pattern already
-- running for `secrets` / `static_reference_cache` / `channel_video_retention`
-- (migration 083 — the backend connects as the `postgres` role, which
-- bypasses RLS via rolbypassrls=true, so this only closes the public
-- PostgREST/anon/authenticated path; it does not affect the backend itself).

CREATE TABLE IF NOT EXISTS youtube_quota_usage (
  day DATE PRIMARY KEY,
  units_used INTEGER NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE youtube_quota_usage ENABLE ROW LEVEL SECURITY;
