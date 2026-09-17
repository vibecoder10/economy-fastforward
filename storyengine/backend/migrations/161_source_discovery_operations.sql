-- Durable provider outcomes remain separate from immutable historical evidence.
CREATE TABLE IF NOT EXISTS source_discovery_operations (
    tenant_id UUID NOT NULL,
    video_id UUID NOT NULL,
    operation_id TEXT NOT NULL CHECK (operation_id ~ '^[0-9a-f]{64}$'),
    machine TEXT NOT NULL,
    state JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(state)='object'),
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,video_id,operation_id),
    FOREIGN KEY (tenant_id,video_id) REFERENCES videos(tenant_id,id) ON DELETE CASCADE
);
ALTER TABLE source_discovery_operations ENABLE ROW LEVEL SECURITY;
-- Backend-only table: deliberately no PostgREST authenticated/anon policies.
