-- 007_tone_column.sql
-- Add tone column for per-scene tone control (Module 3: Interactive Features)
ALTER TABLE scripts ADD COLUMN IF NOT EXISTS tone TEXT DEFAULT 'serious';
