-- Autopilot tables for competitor tracking and learnings
-- Run this migration in Supabase SQL Editor

-- Competitor Videos table - stores scraped competitor videos for modeling
CREATE TABLE IF NOT EXISTS competitor_videos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),

    -- Video info
    video_id TEXT NOT NULL,  -- YouTube video ID
    title TEXT NOT NULL,
    url TEXT,
    channel TEXT,
    channel_url TEXT,

    -- Metrics
    views BIGINT DEFAULT 0,
    vph DECIMAL(10,2) DEFAULT 0,  -- Views per hour
    hours_old DECIMAL(10,2) DEFAULT 0,
    published_date TIMESTAMPTZ,
    scrape_date TIMESTAMPTZ DEFAULT NOW(),

    -- Status
    modeled BOOLEAN DEFAULT FALSE,
    modeled_at TIMESTAMPTZ,
    our_video_id UUID REFERENCES videos(id),

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(tenant_id, video_id)
);

-- Create index for fast lookups
CREATE INDEX IF NOT EXISTS idx_competitor_videos_tenant ON competitor_videos(tenant_id);
CREATE INDEX IF NOT EXISTS idx_competitor_videos_vph ON competitor_videos(vph DESC);
CREATE INDEX IF NOT EXISTS idx_competitor_videos_modeled ON competitor_videos(modeled);

-- Learnings table - stores patterns learned from video performance
CREATE TABLE IF NOT EXISTS learnings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),

    -- Learning info
    category TEXT NOT NULL,  -- 'title', 'hook', 'thumbnail', 'retention', 'framework'
    pattern TEXT NOT NULL,

    -- Confidence metrics
    confidence DECIMAL(5,2) DEFAULT 0,  -- 0-100
    sample_size INT DEFAULT 0,
    avg_ctr DECIMAL(5,2),
    avg_retention DECIMAL(5,2),

    -- Source
    source_videos JSONB,  -- Array of video titles/IDs that inform this learning

    -- Status
    active BOOLEAN DEFAULT TRUE,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_learnings_tenant ON learnings(tenant_id);
CREATE INDEX IF NOT EXISTS idx_learnings_category ON learnings(category);
CREATE INDEX IF NOT EXISTS idx_learnings_active ON learnings(active);

-- Autopilot config table - stores per-tenant autopilot settings
CREATE TABLE IF NOT EXISTS autopilot_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) UNIQUE,

    -- Status
    enabled BOOLEAN DEFAULT TRUE,

    -- Cadence
    videos_per_month INT DEFAULT 15,
    production_interval_days INT DEFAULT 2,

    -- Weights (stored as JSONB for flexibility)
    weights JSONB DEFAULT '{"competitor_vph": 0.55, "timing_freshness": 0.45}'::jsonb,

    -- Thresholds
    thresholds JSONB DEFAULT '{
        "min_confidence_score": 60,
        "min_competitor_vph": 50,
        "max_idea_age_days": 7,
        "ctr_success_threshold": 4.0,
        "ctr_failure_threshold": 2.5
    }'::jsonb,

    -- State
    last_cycle TIMESTAMPTZ,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Enable RLS
ALTER TABLE competitor_videos ENABLE ROW LEVEL SECURITY;
ALTER TABLE learnings ENABLE ROW LEVEL SECURITY;
ALTER TABLE autopilot_config ENABLE ROW LEVEL SECURITY;

-- RLS policies (tenant isolation)
CREATE POLICY "tenant_isolation" ON competitor_videos
    FOR ALL USING (tenant_id = current_setting('app.tenant_id')::uuid);

CREATE POLICY "tenant_isolation" ON learnings
    FOR ALL USING (tenant_id = current_setting('app.tenant_id')::uuid);

CREATE POLICY "tenant_isolation" ON autopilot_config
    FOR ALL USING (tenant_id = current_setting('app.tenant_id')::uuid);
