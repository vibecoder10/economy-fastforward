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
      AND runtime_progress ? 'last_stage_key'
      AND runtime_progress ? 'in_flight'
      AND runtime_progress->>'runtime_hash' ~ '^[0-9a-f]{64}$'
      AND jsonb_typeof(runtime_progress->'completed_stage_keys') = 'array'
      AND (
        runtime_progress->'last_stage_key' = 'null'::jsonb
        OR jsonb_typeof(runtime_progress->'last_stage_key') = 'string'
      )
      AND (
        runtime_progress->'in_flight' = 'null'::jsonb
        OR (
          jsonb_typeof(runtime_progress->'in_flight') = 'object'
          AND runtime_progress->'in_flight'->>'stage_key' <> ''
          AND runtime_progress->'in_flight'->>'operation_id'
            ~ '^custom-film-op:[0-9a-f]{64}$'
          AND runtime_progress->'in_flight'->>'state' = 'started'
        )
      )
    )
  );
