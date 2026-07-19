-- CHANNEL_PATTERNS (checklist C46e — OR-6 EXPANDED: per-channel,
-- data-derived pattern tagging capability).
--
-- Ryan's 2026-07-19 ruling on OR-6 REJECTED the recommendation to hardcode
-- MostHated-Warships (or any style) as a universal anti-pattern — "it might
-- work for another channel or niche." What's built instead is the CAPABILITY
-- to tag a video/style as an anti-pattern (or a good-pattern) excluded from
-- style-seed/few-shot sets, PER CHANNEL, opt-in, nothing tagged by default.
-- The follow-up decision that same day expanded this further: patterns are
-- PROPOSED FROM THE CHANNEL'S OWN ANALYTICS (never hardcoded, never copied
-- cross-channel), each proposal carrying its evidence, and a human must
-- CONFIRM before any tag takes effect.
--
-- Row shape:
--   pattern      -- the testable, human-readable claim, e.g. "'Most Hated'-
--                   style openers underperform this channel's median VPH by
--                   38% across 4 videos."
--   polarity     -- 'anti' (exclude from style-seed/few-shot) | 'good'
--                   (reinforce / a positive exemplar) — the OR-6 capability
--                   is symmetric even though the motivating example was
--                   anti-only.
--   evidence     -- jsonb: whatever backs the claim. Import-time analysis
--                   (source='import_analysis') always carries at minimum
--                   {"video_ids": [...], "metric": "vph"|"ctr"|"retention",
--                   "channel_median": float, "group_value": float,
--                   "delta_pct": float, "cohort_size": int} — see
--                   backend/channel_patterns.py::propose_patterns_from_analytics
--                   for the exact shape. `video_ids` (when present) is what
--                   `channel_patterns.confirmed_anti_video_ids()` reads to
--                   drive the style-seed/few-shot EXCLUSION.
--   source       -- 'import_analysis' (this chunk's bulk import-time
--                   learner, channel_dna.py::learn_channel) |
--                   'launch_analysis' (P4.2's per-launch incremental
--                   flywheel — NOT built this chunk, seam only) | 'manual'
--                   (a creator tags one directly, no machine evidence
--                   required to PROPOSE, though retiring a manually-tagged
--                   row still needs a human confirm — see status below).
--   status       -- 'proposed' (machine- or human-suggested, NOT yet in
--                   effect) | 'confirmed' (human has confirmed it; only
--                   confirmed+anti rows ever exclude anything) | 'retired'
--                   (previously confirmed, since undone — reversible, never
--                   hard-deleted, so the audit trail of "we tried this and
--                   walked it back" survives).
--   confirmed_at/confirmed_by -- stamped on the transition INTO 'confirmed'
--                   (and again on a retirement confirm); NULL for a row
--                   that has never been confirmed.
--
-- Idempotent (CREATE TABLE IF NOT EXISTS / IF NOT EXISTS index) — applied
-- LIVE via the Supabase MCP against project wrromlupsmyzrrcqlucn, confirmed
-- via information_schema.columns (same pattern as migrations 088-105).
--
-- RLS: enabled, NO policies (same playbook as quality_rules/agent_tokens/
-- generation_claims above — the backend connects as the `postgres` role,
-- which bypasses RLS via rolbypassrls=true; this only closes the public
-- PostgREST/anon/authenticated path).

CREATE TABLE IF NOT EXISTS channel_patterns (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  pattern TEXT NOT NULL,
  polarity TEXT NOT NULL CHECK (polarity IN ('anti', 'good')),
  evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
  source TEXT NOT NULL CHECK (source IN ('import_analysis', 'launch_analysis', 'manual')),
  status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'confirmed', 'retired')),
  confirmed_at TIMESTAMPTZ,
  confirmed_by TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS channel_patterns_tenant_status_idx
  ON channel_patterns (tenant_id, status);

ALTER TABLE channel_patterns ENABLE ROW LEVEL SECURITY;
-- No policies (deny-all to anon/authenticated/PostgREST); backend bypasses
-- via table ownership + BYPASSRLS (see migration 083 for the proof).
