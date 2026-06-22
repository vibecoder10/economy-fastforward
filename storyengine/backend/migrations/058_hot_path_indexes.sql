-- Composite indexes for the hottest tenant query paths. Today assets/scripts
-- only have single-column indexes on video_id and tenant_id separately, but the
-- pipeline filters by (video_id, tenant_id), (video_id, status), and
-- (video_id, scene, image_index) constantly (pipeline_executor + routes/videos +
-- the adapter). These composites turn repeated seq-scans-over-an-index into
-- single index lookups as per-tenant asset volume grows.
CREATE INDEX IF NOT EXISTS idx_assets_video_status ON assets(video_id, status);
CREATE INDEX IF NOT EXISTS idx_assets_video_scene ON assets(video_id, scene, image_index);
CREATE INDEX IF NOT EXISTS idx_scripts_video_tenant ON scripts(video_id, tenant_id);
