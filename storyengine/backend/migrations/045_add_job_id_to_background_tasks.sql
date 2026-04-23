-- Add arq job tracking columns to background_tasks
ALTER TABLE background_tasks
  ADD COLUMN IF NOT EXISTS job_id TEXT,
  ADD COLUMN IF NOT EXISTS attempt INTEGER NOT NULL DEFAULT 1;

-- Index for fast job_id lookup (recovery + dedup)
CREATE INDEX IF NOT EXISTS background_tasks_job_id_idx
  ON background_tasks (job_id) WHERE job_id IS NOT NULL;
