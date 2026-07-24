-- M2-4B2a: exact provider-operation reconciliation for section runtime.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'background_tasks_tenant_video_job_uidx'
      AND conrelid = 'background_tasks'::regclass
  ) THEN
    ALTER TABLE background_tasks
      ADD CONSTRAINT background_tasks_tenant_video_job_uidx
      UNIQUE (tenant_id, video_id, job_id);
  END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS custom_film_provider_operations (
  operation_id TEXT PRIMARY KEY
    CHECK (operation_id ~ '^custom-film-op:[0-9a-f]{64}$'),
  tenant_id UUID NOT NULL,
  video_id UUID NOT NULL,
  runtime_job_id TEXT NOT NULL
    CHECK (runtime_job_id ~ '^custom-film-runtime:[0-9a-f]{64}$'),
  runtime_hash TEXT NOT NULL CHECK (runtime_hash ~ '^[0-9a-f]{64}$'),
  stage_key TEXT NOT NULL CHECK (stage_key <> ''),
  provider TEXT NOT NULL CHECK (provider <> ''),
  request_hash TEXT NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  reconciliation_mode TEXT NOT NULL
    CHECK (reconciliation_mode IN (
      'provider_query', 'provider_idempotency', 'none'
    )),
  state TEXT NOT NULL DEFAULT 'prepared'
    CHECK (state IN (
      'prepared', 'submitted', 'completed', 'failed',
      'reconciliation_required'
    )),
  provider_operation_id TEXT,
  result JSONB,
  reconciliation_detail TEXT,
  submitted_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, video_id, runtime_job_id, stage_key),
  CHECK (state <> 'completed' OR result IS NOT NULL),
  CHECK (state <> 'submitted' OR provider_operation_id IS NOT NULL),
  FOREIGN KEY (tenant_id, video_id)
    REFERENCES videos(tenant_id, id) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, video_id, runtime_job_id)
    REFERENCES background_tasks(tenant_id, video_id, job_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS custom_film_provider_operations_runtime_idx
  ON custom_film_provider_operations (tenant_id, video_id, runtime_job_id);

CREATE OR REPLACE FUNCTION protect_custom_film_provider_operation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF (
    NEW.operation_id, NEW.tenant_id, NEW.video_id, NEW.runtime_job_id,
    NEW.runtime_hash, NEW.stage_key, NEW.provider, NEW.request_hash,
    NEW.reconciliation_mode
  ) IS DISTINCT FROM (
    OLD.operation_id, OLD.tenant_id, OLD.video_id, OLD.runtime_job_id,
    OLD.runtime_hash, OLD.stage_key, OLD.provider, OLD.request_hash,
    OLD.reconciliation_mode
  ) THEN
    RAISE EXCEPTION 'Custom Film provider operation identity is immutable';
  END IF;
  IF OLD.provider_operation_id IS NOT NULL
     AND NEW.provider_operation_id IS DISTINCT FROM OLD.provider_operation_id THEN
    RAISE EXCEPTION 'Custom Film provider task identity is write-once';
  END IF;
  IF OLD.result IS NOT NULL AND NEW.result IS DISTINCT FROM OLD.result THEN
    RAISE EXCEPTION 'Custom Film provider result is write-once';
  END IF;
  IF OLD.reconciliation_detail IS NOT NULL
     AND NEW.reconciliation_detail IS DISTINCT FROM OLD.reconciliation_detail THEN
    RAISE EXCEPTION 'Custom Film reconciliation detail is write-once';
  END IF;
  IF OLD.state IN ('completed', 'failed', 'reconciliation_required')
     AND (
       NEW.provider_operation_id, NEW.result, NEW.reconciliation_detail
     ) IS DISTINCT FROM (
       OLD.provider_operation_id, OLD.result, OLD.reconciliation_detail
     ) THEN
    RAISE EXCEPTION 'Custom Film terminal provider operation is immutable';
  END IF;
  IF (
    (OLD.state = 'prepared' AND NEW.state NOT IN (
      'prepared', 'submitted', 'completed', 'failed',
      'reconciliation_required'
    ))
    OR (OLD.state = 'submitted' AND NEW.state NOT IN (
      'submitted', 'completed', 'failed', 'reconciliation_required'
    ))
    OR (OLD.state IN ('completed', 'failed', 'reconciliation_required')
        AND NEW.state <> OLD.state)
  ) THEN
    RAISE EXCEPTION 'Custom Film provider operation state cannot regress';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS custom_film_provider_operation_protect
  ON custom_film_provider_operations;
CREATE TRIGGER custom_film_provider_operation_protect
  BEFORE UPDATE ON custom_film_provider_operations
  FOR EACH ROW EXECUTE FUNCTION protect_custom_film_provider_operation();

ALTER TABLE custom_film_provider_operations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE custom_film_provider_operations FROM anon, authenticated;
