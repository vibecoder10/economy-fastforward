-- Durable, restart-safe Custom Film runtime contract.
ALTER TABLE background_tasks
  ADD COLUMN IF NOT EXISTS runtime_envelope JSONB;

ALTER TABLE background_tasks
  DROP CONSTRAINT IF EXISTS background_tasks_custom_film_runtime_envelope_check;
ALTER TABLE background_tasks
  ADD CONSTRAINT background_tasks_custom_film_runtime_envelope_check CHECK (
    task_type <> 'custom_film_runtime'
    OR (
      runtime_envelope IS NOT NULL
      AND jsonb_typeof(runtime_envelope) = 'object'
      AND runtime_envelope->>'runtime_version' = 'custom-film-runtime-v1'
      AND runtime_envelope->>'runtime_hash' ~ '^[0-9a-f]{64}$'
      AND runtime_envelope->>'approval_hash' ~ '^[0-9a-f]{64}$'
      AND jsonb_typeof(runtime_envelope->'sections') = 'array'
      AND jsonb_typeof(runtime_envelope->'stage_plan') = 'array'
    )
  );

CREATE INDEX IF NOT EXISTS background_tasks_custom_film_approval_idx
  ON background_tasks (
    tenant_id,
    video_id,
    (runtime_envelope->>'approval_hash')
  )
  WHERE task_type = 'custom_film_runtime';
