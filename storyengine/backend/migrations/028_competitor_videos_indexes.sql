-- Performance indexes for competitor_videos queries
-- Covers: pagination, sorting, filtering by channel, VPH ordering

CREATE INDEX IF NOT EXISTS idx_competitor_videos_tenant_vph
    ON competitor_videos(tenant_id, vph DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_competitor_videos_tenant_channel
    ON competitor_videos(tenant_id, channel_url);

CREATE INDEX IF NOT EXISTS idx_competitor_videos_tenant_scrape
    ON competitor_videos(tenant_id, scrape_date DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_competitor_videos_tenant_published
    ON competitor_videos(tenant_id, published_date DESC NULLS LAST);
