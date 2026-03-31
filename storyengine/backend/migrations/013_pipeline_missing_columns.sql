-- Migration 013: Add missing columns discovered during E2E pipeline testing
-- These columns are written by the pipeline executor and video-pipeline skills
-- but were missing from the schema.

-- stage_transitions: cost tracking and error messages
ALTER TABLE stage_transitions ADD COLUMN IF NOT EXISTS cost NUMERIC DEFAULT 0;
ALTER TABLE stage_transitions ADD COLUMN IF NOT EXISTS error_message TEXT;

-- videos: drive folder, reasoning, validation
ALTER TABLE videos ADD COLUMN IF NOT EXISTS drive_folder_link TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS drive_folder_id TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS idea_reasoning TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS script_validation TEXT;

-- assets: title, sentence index, aspect ratio
ALTER TABLE assets ADD COLUMN IF NOT EXISTS video_title TEXT;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS sentence_index INTEGER;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS aspect_ratio TEXT DEFAULT '16:9';
