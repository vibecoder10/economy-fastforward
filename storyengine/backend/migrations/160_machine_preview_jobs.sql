CREATE TABLE IF NOT EXISTS machine_preview_jobs (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    machine TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'needs_review', 'failed', 'cancelled')),
    result JSONB,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS machine_preview_jobs_video_created_idx
    ON machine_preview_jobs (tenant_id, video_id, created_at DESC);
ALTER TABLE machine_preview_jobs ENABLE ROW LEVEL SECURITY;
