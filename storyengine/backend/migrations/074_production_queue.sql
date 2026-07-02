-- 074: the creator's own ordered production queue ("queue these titles").
-- Filled from chat (a dropped CSV of title ideas) or any future UI. The calendar
-- shows queued items as the FIRST slots; Autopilot drains the queue in order
-- BEFORE falling back to its scored competitor candidates. Positions move in
-- gaps of 10 so reordering is a single-row UPDATE.
CREATE TABLE IF NOT EXISTS production_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    position INT NOT NULL,
    title TEXT NOT NULL,
    framework_angle TEXT,
    writer_guidance TEXT,
    user_script TEXT,              -- Phase F3: a supplied script rides the queue
    script_template_id UUID,       -- Phase F4
    source_asset_id UUID,          -- chat_assets.id this item came from
    status TEXT NOT NULL DEFAULT 'queued',  -- queued | launched | skipped
    video_id UUID,
    launched_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_prod_queue_tenant ON production_queue (tenant_id, status, position);
