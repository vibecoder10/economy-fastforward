-- Channel-first YouTube sync (Analytics rehaul). Idempotent.
--
-- channel_videos (created in migration 041 for onboarding intelligence)
-- already mirrors the tenant's own channel: video_id holds the YouTube video
-- id, with view_count/like_count/comment_count/ctr_percent/avg_retention and
-- transcript columns used by identity_builder and channel_profile_documents.
-- The channel-first sync (routes/youtube_sync.py) now feeds this same table;
-- here we add the columns it needs:
--   privacy_status      public | unlisted | private (from Data API status)
--   watch_time_hours    from the Analytics API
--   subscribers_gained  from the Analytics API
--   last_synced_at      sync bookkeeping
--   internal_video_id   optional link to the production row in `videos`
--
-- channel_analytics_daily stores the channel-level day-by-day timeseries from
-- the YouTube Analytics API, which powers the Views & CTR chart even when the
-- channel only has a handful of videos.

ALTER TABLE channel_videos
  ADD COLUMN IF NOT EXISTS privacy_status TEXT,
  ADD COLUMN IF NOT EXISTS watch_time_hours NUMERIC,
  ADD COLUMN IF NOT EXISTS subscribers_gained INTEGER,
  ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS internal_video_id UUID REFERENCES videos(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS channel_videos_tenant_published_idx
  ON channel_videos (tenant_id, published_at DESC);

CREATE TABLE IF NOT EXISTS channel_analytics_daily (
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  date DATE NOT NULL,
  views INTEGER DEFAULT 0,
  impressions BIGINT,
  ctr NUMERIC,
  watch_time_minutes NUMERIC,
  avg_view_duration_seconds NUMERIC,
  subscribers_gained INTEGER,
  subscribers_lost INTEGER,
  PRIMARY KEY (tenant_id, date)
);

-- Channel-level identity + lifetime stats cached on the profile.
ALTER TABLE channel_profiles
  ADD COLUMN IF NOT EXISTS youtube_subscriber_count BIGINT,
  ADD COLUMN IF NOT EXISTS youtube_channel_total_views BIGINT,
  ADD COLUMN IF NOT EXISTS youtube_channel_video_count INTEGER,
  ADD COLUMN IF NOT EXISTS youtube_channel_thumbnail TEXT,
  ADD COLUMN IF NOT EXISTS youtube_stats_synced_at TIMESTAMPTZ;

-- Tenant isolation, same policy shape as migration 048.
DO $$
DECLARE
  tenant_table text;
  tenant_tables text[] := ARRAY['channel_videos', 'channel_analytics_daily'];
  tenant_check text := $policy$
    tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
    OR tenant_id IN (
      SELECT m.tenant_id
      FROM public.memberships m
      WHERE m.user_id = (SELECT auth.uid())
    )
  $policy$;
BEGIN
  FOREACH tenant_table IN ARRAY tenant_tables LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', tenant_table);
    EXECUTE format('DROP POLICY IF EXISTS tenant_id_isolation ON public.%I', tenant_table);
    EXECUTE format(
      'CREATE POLICY tenant_id_isolation ON public.%I FOR ALL TO authenticated USING (%s) WITH CHECK (%s)',
      tenant_table,
      tenant_check,
      tenant_check
    );
  END LOOP;
END $$;

-- One-time cleanup: the AI producer used to write framework_angle with
-- markdown formatting ("** Comic escalation ..."). Strip it so grouping works.
UPDATE videos
   SET framework_angle = btrim(regexp_replace(framework_angle, '[*_`#]', '', 'g'))
 WHERE framework_angle ~ '[*_`#]';
