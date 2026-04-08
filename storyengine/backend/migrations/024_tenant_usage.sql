CREATE TABLE IF NOT EXISTS tenant_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    period_start DATE NOT NULL DEFAULT date_trunc('month', now())::date,
    videos_created INT DEFAULT 0,
    api_calls INT DEFAULT 0,
    render_minutes NUMERIC(10,2) DEFAULT 0,
    storage_bytes BIGINT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(tenant_id, period_start)
);

CREATE INDEX IF NOT EXISTS idx_tenant_usage_tenant_period ON tenant_usage(tenant_id, period_start);
