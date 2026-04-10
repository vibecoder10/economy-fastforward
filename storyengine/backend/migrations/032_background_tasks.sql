-- Persistent background task tracking (replaces in-memory dict for durability)
CREATE TABLE IF NOT EXISTS background_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,
    video_id UUID REFERENCES videos(id) ON DELETE SET NULL,
    task_type TEXT NOT NULL DEFAULT 'pipeline',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    message TEXT,
    error_message TEXT,
    started_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bg_tasks_tenant ON background_tasks(tenant_id);
CREATE INDEX IF NOT EXISTS idx_bg_tasks_status ON background_tasks(status) WHERE status IN ('pending', 'running');
CREATE INDEX IF NOT EXISTS idx_bg_tasks_video ON background_tasks(video_id, status);

ALTER TABLE background_tasks ENABLE ROW LEVEL SECURITY;

-- RLS: tenants can only see their own tasks
CREATE POLICY bg_tasks_tenant_read ON background_tasks
    FOR SELECT USING (tenant_id = auth.uid());

-- Cleanup: no client deletes (admin only via service role)
