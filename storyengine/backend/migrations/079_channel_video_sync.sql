-- Channel-first YouTube sync (Analytics rehaul).
--
-- channel_videos mirrors what is actually on the tenant's connected YouTube
-- channel (imported from the uploads playlist), separate from the production
-- pipeline rows in `videos` so dashboard/pipeline/review counts stay untouched.
-- An optional video_id FK links a channel video back to the internal row that
-- produced it, letting the learning loop keep reading `videos`.
--
-- channel_analytics_daily stores the channel-level day-by-day timeseries from
-- the YouTube Analytics API, which powers the Views & CTR chart even when the
-- channel only has a handful of videos.

CREATE TABLE IF NOT EXISTS channel_videos (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  youtube_video_id TEXT NOT NULL,
  video_id UUID REFERENCES videos(id) ON DELETE SET NULL,
  title TEXT,
  thumbnail_url TEXT,
  published_at TIMESTAMPTZ,
  duration_seconds INTEGER,
  privacy_status TEXT,
  views BIGINT DEFAULT 0,
  likes INTEGER DEFAULT 0,
  comments INTEGER DEFAULT 0,
  impressions BIGINT,
  ctr NUMERIC,
  avg_view_duration_seconds NUMERIC,
  avg_view_percentage NUMERIC,
  watch_time_hours NUMERIC,
  subscribers_gained INTEGER,
  last_synced_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (tenant_id, youtube_video_id)
);

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
