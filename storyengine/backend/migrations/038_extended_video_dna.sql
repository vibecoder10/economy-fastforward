-- Migration 038: Extended video DNA columns for full competitor intelligence
--
-- Captures everything yt-dlp provides + derived metrics for understanding
-- why a video worked: engagement ratios, timing, chapters, subscriber context.

-- New raw fields from yt-dlp
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS comment_count INTEGER;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS channel_subscriber_count INTEGER;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS has_chapters BOOLEAN DEFAULT false;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS chapter_count INTEGER DEFAULT 0;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS chapter_titles TEXT;  -- JSON array of chapter names
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS tags TEXT;            -- JSON array of video tags

-- Derived performance metrics (calculated at scrape time)
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS like_ratio NUMERIC;           -- likes / views
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS comment_ratio NUMERIC;        -- comments / views
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS views_per_sub_ratio NUMERIC;  -- views / channel_subs (virality signal)

-- Publish timing (for day-of-week and time-of-day analysis)
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS published_day_of_week INTEGER;  -- 0=Monday, 6=Sunday
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS published_hour INTEGER;          -- 0-23 UTC

-- Thumbnail analysis (populated by Gemini vision during distillation)
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS thumbnail_analyzed_at TIMESTAMPTZ;

-- Index for timing analysis queries
CREATE INDEX IF NOT EXISTS idx_cv_published_timing
  ON competitor_videos(tenant_id, published_day_of_week, published_hour);

-- Index for virality analysis
CREATE INDEX IF NOT EXISTS idx_cv_virality
  ON competitor_videos(tenant_id, views_per_sub_ratio DESC NULLS LAST)
  WHERE views_per_sub_ratio IS NOT NULL;
