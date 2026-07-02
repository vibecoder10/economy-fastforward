-- 073: files dropped into the chat ("drop it in the chat" intake layer).
-- One row per uploaded asset: the raw file goes to storage (Drive), the parsed
-- content lives here so the producer can read it without re-fetching. `filed_as`
-- records where the asset ended up once a filing op runs (queue / video_script /
-- template / cast / format) — Phase 1 only uploads + describes.
-- NOTE: named chat_assets because `assets` is already the per-scene media table.
CREATE TABLE IF NOT EXISTS chat_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    conversation_id UUID,          -- chat_conversations.id (set when first attached to a turn)
    kind TEXT NOT NULL,            -- 'csv' | 'pdf' | 'text' | 'image'
    filename TEXT,
    content_type TEXT,
    storage_url TEXT,              -- raw file (drive proxy URL); NULL if storage upload failed
    parsed JSONB,                  -- csv: {headers, rows, n_rows, title_column, ambiguous}
    parsed_text TEXT,              -- pdf/text extraction (capped)
    summary TEXT,                  -- one-line description injected into the producer brief
    status TEXT NOT NULL DEFAULT 'uploaded',  -- uploaded | filed | discarded
    filed_as TEXT,                 -- 'queue' | 'video_script' | 'template' | 'cast' | 'format'
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_chat_assets_tenant_conv ON chat_assets (tenant_id, conversation_id);
