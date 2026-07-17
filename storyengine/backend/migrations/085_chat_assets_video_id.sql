-- Associates a dropped file with the video whose co-pilot dock it was dropped
-- into (checklist §0.6, C05 — docked co-pilot accepts file attachments). The
-- home chat still uploads with video_id = NULL (unscoped, conversation-only);
-- this column is purely additive and optional.
--
-- Idempotent (ADD COLUMN IF NOT EXISTS) — safe to run when already applied.

ALTER TABLE chat_assets ADD COLUMN IF NOT EXISTS video_id UUID;
CREATE INDEX IF NOT EXISTS idx_chat_assets_tenant_video ON chat_assets(tenant_id, video_id);
