-- Add voice_duration_seconds to scripts table for sentence splitting
-- The deterministic splitter uses voice duration to calculate words-per-second
ALTER TABLE scripts ADD COLUMN IF NOT EXISTS voice_duration_seconds NUMERIC;
