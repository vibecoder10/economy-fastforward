-- Add revision_notes column to videos table for persisting feedback from Research/Script tabs
ALTER TABLE videos ADD COLUMN IF NOT EXISTS revision_notes TEXT;
