-- Migration 016: Add yt-dlp enrichment columns to competitor_videos
-- Supports: thumbnail URL extraction, transcript analysis, richer metadata

ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS thumbnail_url TEXT;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS transcript TEXT;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS duration_seconds INTEGER;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS likes INTEGER;
