-- MCP_CONFIRM_TOKENS (checklist P2.4b, chunk C27 — the MCP money gate,
-- tasks/storyengine-copilot-ux-map.md §7: "paid tools return a quote +
-- confirm_token first; the agent must call confirm(confirm_token) to
-- spend"). See backend/confirm_tokens.py for the full design rationale
-- (why this needs a DB row instead of chat's in-conversation
-- pending_action, and why single-use + expiry + param-binding are ALL
-- enforced by one atomic UPDATE rather than three separate checks).
--
-- token_hash: sha256 hex digest of the plaintext token (same non-recoverable,
-- non-slow-KDF rationale as agent_tokens.token_hash — this hashes a 256-bit
-- random secret, not a human password).
-- params_hash: sha256 of the canonical (verb, scene, change, length_min,
-- target) the quote was computed for — confirm_tokens.redeem()'s WHERE
-- clause requires the confirming call's OWN recomputed hash to match this
-- exactly, so a token minted for one action/scene can't be replayed against
-- a different one (a "bait and switch" on params fails closed).
-- used_at: NULL = unused. Set once by redeem()'s atomic UPDATE; a second
-- redeem attempt on the same row finds used_at already set and fails.
-- expires_at: 10 minutes from mint (confirm_tokens.TTL_SECONDS) — a quote
-- an agent never acts on simply goes stale; nothing sweeps these rows today
-- (a follow-up cron could, but an unbounded few-KB/day table of expired
-- rows is not a problem worth a chunk of its own yet).
--
-- Idempotent (CREATE TABLE IF NOT EXISTS / IF NOT EXISTS index) — applied
-- LIVE via the Supabase MCP against project wrromlupsmyzrrcqlucn, confirmed
-- via information_schema.columns (same pattern as migrations 088-099).
--
-- RLS: enabled, NO policies (same playbook §7 pattern as agent_tokens/
-- generation_claims/generation_passes/style_presets above — the backend
-- connects as the `postgres` role, which bypasses RLS via rolbypassrls=true;
-- this only closes the public PostgREST/anon/authenticated path).

CREATE TABLE IF NOT EXISTS mcp_confirm_tokens (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
  verb TEXT NOT NULL,
  params_hash TEXT NOT NULL,
  token_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL,
  used_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS mcp_confirm_tokens_token_hash_unique
  ON mcp_confirm_tokens (token_hash);

CREATE INDEX IF NOT EXISTS mcp_confirm_tokens_tenant_video_idx
  ON mcp_confirm_tokens (tenant_id, video_id) WHERE used_at IS NULL;

ALTER TABLE mcp_confirm_tokens ENABLE ROW LEVEL SECURITY;
-- No policies (deny-all to anon/authenticated/PostgREST); backend bypasses
-- via table ownership + BYPASSRLS (see migration 083 for the proof).
