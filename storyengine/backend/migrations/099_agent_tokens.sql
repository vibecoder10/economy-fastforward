-- AGENT_TOKENS (checklist P2.4a, chunk C26 — docs/reports/2026-07-17-
-- storyengine-agent-audit-findings.md §S5-3/S5-4, the MCP "Higgsfield-killer
-- door" in tasks/storyengine-copilot-ux-map.md §7). DB-row-backed,
-- individually revocable per-tenant API tokens for external MCP clients
-- (Claude, any MCP host). S5-3 explicitly names the wrong precedent this
-- must NOT follow: auth.py's session JWTs are 30-day stateless (fine for a
-- browser tab, unrevocable by design) — an agent credential an external
-- process may hold for months needs the opposite property. Every MCP
-- request re-checks `revoked_at IS NULL` against THIS table
-- (backend/agent_tokens.py::authenticate), so a revoke takes effect on the
-- very next call, never "eventually when the token expires."
--
-- token_hash: sha256 hex digest of the plaintext secret
-- (backend/agent_tokens.py hashes with hashlib.sha256, NOT bcrypt/pbkdf2 —
-- this hashes a high-entropy 256-bit random token, not a human-chosen
-- password, so a slow KDF buys no security and costs every single MCP call
-- a deliberate slowdown; distinct from google_auth.py's pbkdf2 hashing,
-- which defends a LOW-entropy human secret against offline guessing).
-- Plaintext is NEVER stored — shown to the user exactly once at mint time
-- (create_agent_token()'s return value, surfaced by C28's Settings UI).
--
-- name: user-facing label ("Claude Desktop", "CI bot") — free text, no
-- uniqueness constraint (a tenant may hold two same-named tokens mid-rotation).
-- last_used_at: updated fail-soft on every successful auth
-- (agent_tokens.py's authenticate()) — best-effort telemetry for C28's
-- "last used" column, never part of the auth decision itself.
-- revoked_at: NULL = active. Set once, never cleared — revocation is
-- one-directional; a replacement token is a new row, never an un-revoke.
--
-- Idempotent (CREATE TABLE IF NOT EXISTS / IF NOT EXISTS index) — applied
-- LIVE via the Supabase MCP against project wrromlupsmyzrrcqlucn, confirmed
-- via information_schema.columns (same pattern as migrations 088-098).
--
-- RLS: enabled, NO policies (playbook §7 pattern, same as generation_claims/
-- generation_passes/style_presets above — the backend connects as the
-- `postgres` role, which bypasses RLS via rolbypassrls=true; this only
-- closes the public PostgREST/anon/authenticated path).

CREATE TABLE IF NOT EXISTS agent_tokens (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  token_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_used_at TIMESTAMPTZ,
  revoked_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS agent_tokens_token_hash_unique
  ON agent_tokens (token_hash);

CREATE INDEX IF NOT EXISTS agent_tokens_tenant_idx
  ON agent_tokens (tenant_id) WHERE revoked_at IS NULL;

ALTER TABLE agent_tokens ENABLE ROW LEVEL SECURITY;
-- No policies (deny-all to anon/authenticated/PostgREST); backend bypasses
-- via table ownership + BYPASSRLS (see migration 083 for the proof).
