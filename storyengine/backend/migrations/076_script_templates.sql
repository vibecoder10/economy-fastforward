-- 076: the channel's house script format ("remember how this script is built").
-- One template per tenant in practice (uploading a new example replaces it) —
-- stored as a table, not tenant_prompt_defaults, because that slot is owned by
-- the system-prompts editor and this must never clobber manual prompt edits.
-- The structure text is distilled FORMAT instructions (hook shape, segments,
-- transitions, pacing, recurring devices, sign-off), never topic content; it is
-- prepended to videos.script_system_prompt at creation/launch so every script
-- pathway (chat, queue, autopilot, UI) inherits it via the existing precedence
-- chain.
CREATE TABLE IF NOT EXISTS script_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    name TEXT NOT NULL,
    structure TEXT NOT NULL,
    example_excerpt TEXT,
    source_asset_id UUID,
    is_default BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_script_templates_tenant ON script_templates (tenant_id);
