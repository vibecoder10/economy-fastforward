-- Migration 019: Storyboard expansion
-- Add storyboard 4 & 5 grid URL columns + original image prompt backup

-- Scripts table: additional storyboard grid columns for hero expansion
ALTER TABLE scripts ADD COLUMN IF NOT EXISTS storyboard_4_url TEXT;
ALTER TABLE scripts ADD COLUMN IF NOT EXISTS storyboard_5_url TEXT;

-- Assets table: backup of original image prompt before storyboard enrichment
ALTER TABLE assets ADD COLUMN IF NOT EXISTS original_image_prompt TEXT;
