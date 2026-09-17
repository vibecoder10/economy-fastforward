CREATE TABLE IF NOT EXISTS dvsu_script_operations (
    tenant_id UUID NOT NULL,
    video_id UUID NOT NULL,
    operation_id TEXT NOT NULL CHECK (operation_id ~ '^[0-9a-f]{64}$'),
    machine TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('submitted','received')),
    request_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    response TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,video_id,operation_id),
    FOREIGN KEY (tenant_id,video_id) REFERENCES videos(tenant_id,id) ON DELETE CASCADE,
    CHECK (status <> 'received' OR response IS NOT NULL)
);
ALTER TABLE dvsu_script_operations ENABLE ROW LEVEL SECURITY;
-- Backend-only receipts; no authenticated/anon PostgREST policies.
