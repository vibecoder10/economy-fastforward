-- DIRECTOR_PREFERENCES (checklist C15c — "Director memory: durable preference
-- store"). A correction said once ("the kitten is gray", "never use premium
-- models on Poco") becomes a STANDING preference the chat remembers across
-- conversations and videos, instead of only living in that one transcript.
--
-- Distinct from channel_profiles.creator_brief (onboarding-shaped facts —
-- intent/goals/niche/channel/competitors, see _save_creator_brief/
-- _hydrate_creator_brief in routes/chat.py): a real table was chosen over
-- more creator_brief JSONB because preferences need to be LISTED
-- individually ("what do you remember?"), DELETED individually ("forget
-- #2"), and scoped per-VIDEO as well as per-channel — a JSONB blob keyed by
-- onboarding field names has no natural row identity for any of that.
--
-- scope: the literal string 'channel' (applies everywhere for this tenant)
--        or a video_id's text form (applies only inside that one video's
--        copilot chat). Stored as TEXT, not a videos(id) FK, so a channel-
--        scoped row (scope='channel') isn't forced through a UUID FK check.
-- source: 'user' always, for this chunk (explicit corrections only — no
--        auto-learning). Column exists so a future inferred-preference path
--        (not built here) has somewhere to land without a schema change.
-- active: soft-delete only ("forget that" sets this false; the row is kept
--        for history/undo, never hard-deleted).
--
-- Idempotent (CREATE TABLE IF NOT EXISTS / IF NOT EXISTS index) — applied
-- LIVE via the Supabase MCP against project wrromlupsmyzrrcqlucn, confirmed
-- via information_schema.columns (same pattern as migrations 088/089/090:
-- the app's own migration runner tracks applied files by name in
-- `_migrations`, MCP applies land in Supabase's own tracking instead, so a
-- restart may re-run this file — IF NOT EXISTS makes that a no-op).
--
-- RLS: enabled, NO policies (playbook §7 pattern — the backend connects as
-- the `postgres` role, which bypasses RLS via rolbypassrls=true, so this
-- only closes the public PostgREST/anon/authenticated path; proven safe
-- already for `secrets` / `static_reference_cache` / `channel_video_retention`,
-- see migration 083).

CREATE TABLE IF NOT EXISTS director_preferences (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  scope TEXT NOT NULL DEFAULT 'channel',
  text TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'user',
  active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_director_preferences_tenant_scope_active
  ON director_preferences(tenant_id, scope, active, created_at DESC);

ALTER TABLE director_preferences ENABLE ROW LEVEL SECURITY;
-- No policies (deny-all to anon/authenticated/PostgREST); backend bypasses
-- via table ownership + BYPASSRLS (see migration 083 for the proof).
