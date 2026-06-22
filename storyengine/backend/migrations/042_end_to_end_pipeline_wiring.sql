-- End-to-end pipeline wiring: OAuth scopes, tenant Drive, upload metadata, channel history.

ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS youtube_oauth_scopes TEXT;
ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS youtube_connected_at TIMESTAMPTZ;
ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS google_drive_connected_at TIMESTAMPTZ;

ALTER TABLE videos ADD COLUMN IF NOT EXISTS seo_description TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS seo_tags TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS seo_hashtags TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS upload_status TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS youtube_video_id TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS upload_date TIMESTAMPTZ;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS drive_folder_id TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS drive_folder_link TEXT;

CREATE TABLE IF NOT EXISTS channel_videos (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  video_id TEXT NOT NULL,
  title TEXT,
  published_at TIMESTAMPTZ,
  view_count BIGINT,
  like_count BIGINT,
  comment_count BIGINT,
  duration_seconds INTEGER,
  thumbnail_url TEXT,
  ctr_percent NUMERIC(5,2),
  avg_view_duration_seconds INTEGER,
  avg_retention NUMERIC(7,2),
  impressions BIGINT,
  metadata JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(tenant_id, video_id)
);

ALTER TABLE channel_videos ADD COLUMN IF NOT EXISTS tenant_id UUID;
ALTER TABLE channel_videos ADD COLUMN IF NOT EXISTS video_id TEXT;
ALTER TABLE channel_videos ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE channel_videos ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ;
ALTER TABLE channel_videos ADD COLUMN IF NOT EXISTS view_count BIGINT;
ALTER TABLE channel_videos ADD COLUMN IF NOT EXISTS like_count BIGINT;
ALTER TABLE channel_videos ADD COLUMN IF NOT EXISTS comment_count BIGINT;
ALTER TABLE channel_videos ADD COLUMN IF NOT EXISTS duration_seconds INTEGER;
ALTER TABLE channel_videos ADD COLUMN IF NOT EXISTS thumbnail_url TEXT;
ALTER TABLE channel_videos ADD COLUMN IF NOT EXISTS ctr_percent NUMERIC(5,2);
ALTER TABLE channel_videos ADD COLUMN IF NOT EXISTS avg_view_duration_seconds INTEGER;
ALTER TABLE channel_videos ADD COLUMN IF NOT EXISTS avg_retention NUMERIC(7,2);
ALTER TABLE channel_videos ADD COLUMN IF NOT EXISTS impressions BIGINT;
ALTER TABLE channel_videos ADD COLUMN IF NOT EXISTS metadata JSONB;
ALTER TABLE channel_videos ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now();
ALTER TABLE channel_videos ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

CREATE UNIQUE INDEX IF NOT EXISTS idx_channel_videos_tenant_video_id
  ON channel_videos(tenant_id, video_id);
CREATE INDEX IF NOT EXISTS idx_channel_videos_tenant ON channel_videos(tenant_id);
CREATE INDEX IF NOT EXISTS idx_channel_videos_published ON channel_videos(tenant_id, published_at DESC);

ALTER TABLE channel_videos ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE tablename = 'channel_videos'
      AND policyname = 'channel_videos_tenant_isolation'
  ) THEN
    CREATE POLICY channel_videos_tenant_isolation ON channel_videos
      FOR ALL USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
  END IF;
END $$;
