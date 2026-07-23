-- M2-4B2a: exact provider-operation reconciliation for section runtime.
CREATE TABLE IF NOT EXISTS custom_film_provider_operations (
  operation_id TEXT PRIMARY KEY
    CHECK (operation_id ~ '^custom-film-op:[0-9a-f]{64}$'),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
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
  CHECK (state <> 'completed' OR result IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS custom_film_provider_operations_runtime_idx
  ON custom_film_provider_operations (tenant_id, video_id, runtime_job_id);

ALTER TABLE custom_film_provider_operations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE custom_film_provider_operations FROM anon, authenticated;
