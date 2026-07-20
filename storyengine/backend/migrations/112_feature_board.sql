-- C65 (tasks/decisions.md 2026-07-20 "Feature board" entry): the platform's
-- FIRST deliberately CROSS-TENANT surface. "Suggest a feature" + upvotes +
-- a status ladder (under_review -> planned -> building -> in_beta -> shipped
-- / declined) that every customer sees the SAME board of, regardless of
-- tenant. Do NOT copy the tenant-isolation idiom here: these two tables
-- carry NO tenant_id at all, on purpose — reads are global, writes are
-- attributed per ACCOUNT (accounts.id, the same UUID space auth users live
-- in — see routes/workspaces.py's `_is_operator` for the precedent of
-- keying straight off accounts.id rather than a tenant/membership join).
--
-- feature_requests       -- one row per suggestion. account_id is the
--                            author (FK accounts). status starts
--                            'under_review' and only an operator (Ryan,
--                            accounts.is_operator) can move it along the
--                            ladder (routes/feature_board.py's PATCH
--                            .../status). declined_reason is set only when
--                            status='declined', free text, optional.
-- feature_request_votes  -- one row per (request, account) upvote. The
--                            composite PRIMARY KEY *is* the "one vote per
--                            account per idea" rule — enforced by Postgres,
--                            not application code — and doubles as the
--                            ON CONFLICT (request_id, account_id) DO NOTHING
--                            target for the idempotent vote endpoint.
--
-- Idempotent (CREATE TABLE IF NOT EXISTS) -- applied LIVE via Supabase MCP
-- against project wrromlupsmyzrrcqlucn, confirmed via information_schema,
-- same pattern as migrations 105/106/108/111.

CREATE TABLE IF NOT EXISTS feature_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  title TEXT NOT NULL CHECK (char_length(title) <= 120),
  body TEXT CHECK (body IS NULL OR char_length(body) <= 2000),
  channel_archetype TEXT,
  status TEXT NOT NULL DEFAULT 'under_review'
    CHECK (status IN ('under_review', 'planned', 'building', 'in_beta', 'shipped', 'declined')),
  declined_reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS feature_requests_status_idx
  ON feature_requests (status);

CREATE INDEX IF NOT EXISTS feature_requests_account_created_idx
  ON feature_requests (account_id, created_at);

ALTER TABLE feature_requests ENABLE ROW LEVEL SECURITY;
-- No policies (deny-all to anon/authenticated/PostgREST); backend bypasses
-- via table ownership + BYPASSRLS (see migration 083 for the proof).

CREATE TABLE IF NOT EXISTS feature_request_votes (
  request_id UUID NOT NULL REFERENCES feature_requests(id) ON DELETE CASCADE,
  account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (request_id, account_id)
);

CREATE INDEX IF NOT EXISTS feature_request_votes_request_idx
  ON feature_request_votes (request_id);

ALTER TABLE feature_request_votes ENABLE ROW LEVEL SECURITY;
-- No policies (deny-all to anon/authenticated/PostgREST); backend bypasses
-- via table ownership + BYPASSRLS (see migration 083 for the proof).
