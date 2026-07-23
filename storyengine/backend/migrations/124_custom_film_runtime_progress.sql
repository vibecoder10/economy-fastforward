-- M2-4B1: durable progress for restart-safe per-section runtime consumption.
ALTER TABLE background_tasks
  ADD COLUMN IF NOT EXISTS runtime_progress JSONB;

ALTER TABLE background_tasks
  DROP CONSTRAINT IF EXISTS background_tasks_custom_film_runtime_progress_check;
ALTER TABLE background_tasks
  ADD CONSTRAINT background_tasks_custom_film_runtime_progress_check CHECK (
    runtime_progress IS NULL
    OR (
      task_type = 'custom_film_runtime'
      AND jsonb_typeof(runtime_progress) = 'object'
      AND runtime_progress->>'runtime_hash' ~ '^[0-9a-f]{64}$'
      AND jsonb_typeof(runtime_progress->'completed_stage_keys') = 'array'
    )
  );
