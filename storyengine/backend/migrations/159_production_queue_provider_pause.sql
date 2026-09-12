-- A shared provider failure parks a tenant's list until an explicit recovery.
CREATE TABLE IF NOT EXISTS production_queue_controls (
    tenant_id UUID PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
    paused BOOLEAN NOT NULL DEFAULT FALSE,
    provider TEXT,
    reason TEXT,
    blocking_queue_id UUID REFERENCES production_queue(id) ON DELETE SET NULL,
    paused_at TIMESTAMPTZ,
    resumed_at TIMESTAMPTZ,
    resume_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE production_queue_controls ENABLE ROW LEVEL SECURITY;
