-- Production activation backstop for the Custom Film multipass director.
--
-- Migration 135 was extended while the feature flag was held off. Existing
-- databases may already have recorded that filename, so this migration
-- explicitly converges both earlier-135 and fresh-schema installations.
BEGIN;

DO $constraint$
BEGIN
  BEGIN
    ALTER TABLE custom_film_director_stage_schedules
      ADD CONSTRAINT custom_film_director_schedule_execution_fk_key
      UNIQUE (tenant_id, id, plan_id, video_id, authority_id);
  EXCEPTION WHEN duplicate_object THEN
    NULL;
  END;
END;
$constraint$;

CREATE TABLE IF NOT EXISTS custom_film_director_call_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  plan_id UUID NOT NULL,
  video_id UUID NOT NULL,
  schedule_id UUID NOT NULL,
  authority_id UUID NOT NULL,
  operation_id TEXT NOT NULL CHECK (
    operation_id ~ '^custom-film-director-op:[0-9a-f]{64}$'
  ),
  operation_kind TEXT NOT NULL CHECK (btrim(operation_kind) <> ''),
  operation_order_index INTEGER NOT NULL CHECK (operation_order_index >= 0),
  event_sequence INTEGER NOT NULL CHECK (event_sequence IN (0, 1)),
  event_kind TEXT NOT NULL CHECK (
    event_kind IN ('attempt_started', 'attempt_completed', 'attempt_failed')
  ),
  input_hash TEXT NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
  output_hash TEXT CHECK (
    output_hash IS NULL OR output_hash ~ '^[0-9a-f]{64}$'
  ),
  request_id TEXT,
  actual_cost_nusd BIGINT NOT NULL DEFAULT 0 CHECK (actual_cost_nusd >= 0),
  actual_cost_cents BIGINT NOT NULL DEFAULT 0 CHECK (actual_cost_cents >= 0),
  event JSONB NOT NULL CHECK (jsonb_typeof(event) = 'object'),
  event_hash TEXT NOT NULL CHECK (event_hash ~ '^[0-9a-f]{64}$'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, schedule_id, operation_id, event_sequence),
  UNIQUE (tenant_id, event_hash),
  FOREIGN KEY (tenant_id, schedule_id, plan_id, video_id, authority_id)
    REFERENCES custom_film_director_stage_schedules(
      tenant_id, id, plan_id, video_id, authority_id
    ) ON DELETE RESTRICT,
  CHECK (
    (event_sequence = 0 AND event_kind = 'attempt_started')
    OR (
      event_sequence = 1
      AND event_kind IN ('attempt_completed', 'attempt_failed')
    )
  ),
  CHECK (
    (event_kind = 'attempt_started' AND output_hash IS NULL)
    OR event_kind <> 'attempt_started'
  )
);

ALTER TABLE custom_film_director_call_events
  ADD COLUMN IF NOT EXISTS actual_cost_nusd BIGINT NOT NULL DEFAULT 0;
ALTER TABLE custom_film_director_call_events
  DROP CONSTRAINT IF EXISTS custom_film_director_call_events_actual_cost_nusd_check;
ALTER TABLE custom_film_director_call_events
  ADD CONSTRAINT custom_film_director_call_events_actual_cost_nusd_check
  CHECK (actual_cost_nusd >= 0);

CREATE INDEX IF NOT EXISTS custom_film_director_call_event_operation_idx
  ON custom_film_director_call_events
    (tenant_id, schedule_id, operation_order_index, event_sequence);

CREATE TABLE IF NOT EXISTS custom_film_director_executions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  plan_id UUID NOT NULL,
  video_id UUID NOT NULL,
  schedule_id UUID NOT NULL,
  authority_id UUID NOT NULL,
  director_contract_id UUID NOT NULL,
  execution_hash TEXT NOT NULL CHECK (execution_hash ~ '^[0-9a-f]{64}$'),
  receipt_manifest_hash TEXT NOT NULL
    CHECK (receipt_manifest_hash ~ '^[0-9a-f]{64}$'),
  actual_spend_nusd BIGINT NOT NULL DEFAULT 0 CHECK (actual_spend_nusd >= 0),
  actual_spend_cents BIGINT NOT NULL CHECK (actual_spend_cents >= 0),
  execution JSONB NOT NULL CHECK (jsonb_typeof(execution) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, schedule_id),
  UNIQUE (tenant_id, director_contract_id),
  UNIQUE (tenant_id, execution_hash),
  FOREIGN KEY (tenant_id, schedule_id, plan_id, video_id, authority_id)
    REFERENCES custom_film_director_stage_schedules(
      tenant_id, id, plan_id, video_id, authority_id
    ) ON DELETE RESTRICT,
  FOREIGN KEY (tenant_id, director_contract_id, plan_id, video_id)
    REFERENCES custom_film_director_contracts(
      tenant_id, id, plan_id, video_id
    ) ON DELETE RESTRICT
);

ALTER TABLE custom_film_director_executions
  ADD COLUMN IF NOT EXISTS actual_spend_nusd BIGINT NOT NULL DEFAULT 0;
ALTER TABLE custom_film_director_executions
  DROP CONSTRAINT IF EXISTS custom_film_director_executions_actual_spend_nusd_check;
ALTER TABLE custom_film_director_executions
  ADD CONSTRAINT custom_film_director_executions_actual_spend_nusd_check
  CHECK (actual_spend_nusd >= 0);

ALTER TABLE custom_film_director_call_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE custom_film_director_executions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON custom_film_director_call_events FROM anon, authenticated;
REVOKE ALL ON custom_film_director_executions FROM anon, authenticated;

CREATE OR REPLACE FUNCTION protect_custom_film_director_append_only()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$;

DROP TRIGGER IF EXISTS custom_film_director_call_events_append_only
  ON custom_film_director_call_events;
CREATE TRIGGER custom_film_director_call_events_append_only
  BEFORE UPDATE OR DELETE ON custom_film_director_call_events
  FOR EACH ROW EXECUTE FUNCTION protect_custom_film_director_append_only();

DROP TRIGGER IF EXISTS custom_film_director_executions_append_only
  ON custom_film_director_executions;
CREATE TRIGGER custom_film_director_executions_append_only
  BEFORE UPDATE OR DELETE ON custom_film_director_executions
  FOR EACH ROW EXECUTE FUNCTION protect_custom_film_director_append_only();

DO $policies$
DECLARE
  table_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'custom_film_director_call_events',
    'custom_film_director_executions'
  ]
  LOOP
    BEGIN
      EXECUTE format(
        'CREATE POLICY "Tenant isolation" ON %I '
        'FOR ALL TO authenticated '
        'USING (tenant_id IN ('
        'SELECT m.tenant_id FROM memberships m '
        'WHERE m.user_id = (SELECT auth.uid())'
        ')) '
        'WITH CHECK (tenant_id IN ('
        'SELECT m.tenant_id FROM memberships m '
        'WHERE m.user_id = (SELECT auth.uid())'
        '))',
        table_name
      );
    EXCEPTION WHEN duplicate_object THEN
      NULL;
    END;
  END LOOP;
END;
$policies$;

COMMIT;
