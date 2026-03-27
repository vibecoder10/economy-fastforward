-- Add voice_duration_seconds to scripts table for sentence splitting
-- The deterministic splitter uses voice duration to calculate words-per-second
ALTER TABLE scripts ADD COLUMN IF NOT EXISTS voice_duration_seconds NUMERIC;

-- updated_at columns (referenced by existing UPDATE queries but never created)
ALTER TABLE scripts ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();
ALTER TABLE assets ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();
