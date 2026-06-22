-- Migration 060: chat-first creative-producer conversations
--
-- Backs the chat-first experience (GOAL.md Phase 1). One row per conversation;
-- the whole transcript lives in a JSONB array (no second table, no joins). The
-- producer replays `transcript` to Claude each turn; `state.last_spec` holds the
-- approved-pending production spec; `video_id` is set once the conversation
-- creates a video (after which follow-up turns drive that video's pipeline).
--
-- Tenant isolation is enforced by an explicit `WHERE tenant_id = $1` in every
-- query (the asyncpg pool does not set app.tenant_id); RLS below is defense in
-- depth, mirroring video_characters (046).
--
-- Idempotent.

CREATE TABLE IF NOT EXISTS chat_conversations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,
  project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
  video_id UUID REFERENCES videos(id) ON DELETE SET NULL,
  transcript JSONB NOT NULL DEFAULT '[]'::jsonb,   -- [{role, content}, ...]
  state JSONB NOT NULL DEFAULT '{}'::jsonb,         -- {selections, last_spec}
  phase TEXT NOT NULL DEFAULT 'asking',             -- asking | plan | created
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chat_conversations_tenant ON chat_conversations(tenant_id);

ALTER TABLE chat_conversations ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS chat_conversations_tenant_isolation ON chat_conversations;
CREATE POLICY chat_conversations_tenant_isolation ON chat_conversations
  FOR ALL TO authenticated
  USING (
    tenant_id IN (
      SELECT m.tenant_id FROM memberships m
      WHERE m.user_id = (SELECT auth.uid())
    )
    OR tenant_id = current_setting('app.tenant_id', true)::uuid
  );
