-- Notification preferences per tenant
CREATE TABLE IF NOT EXISTS notification_preferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE UNIQUE NOT NULL,
    email_weekly_digest BOOLEAN DEFAULT true,
    email_video_complete BOOLEAN DEFAULT true,
    email_error_alerts BOOLEAN DEFAULT true,
    email_ctr_alerts BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
