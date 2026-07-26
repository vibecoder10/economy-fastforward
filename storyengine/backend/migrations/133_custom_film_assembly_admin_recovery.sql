-- Audited, one-time recovery for an assembly that product code incorrectly
-- classified as terminal. Normal terminal assemblies remain immutable.
BEGIN;

CREATE TABLE IF NOT EXISTS custom_film_assembly_recoveries (
  recovery_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  video_id UUID NOT NULL,
  runtime_job_id TEXT NOT NULL
    CHECK (runtime_job_id ~ '^custom-film-runtime:[0-9a-f]{64}$'),
  runtime_hash TEXT NOT NULL CHECK (runtime_hash ~ '^[0-9a-f]{64}$'),
  manifest_version TEXT NOT NULL,
  manifest_hash TEXT NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
  render_engine TEXT NOT NULL,
  storage_path TEXT NOT NULL CHECK (storage_path <> ''),
  source_state TEXT NOT NULL CHECK (source_state = 'terminal_failed'),
  target_state TEXT NOT NULL CHECK (target_state = 'retryable_failed'),
  prior_failure_kind TEXT NOT NULL CHECK (prior_failure_kind = 'terminal'),
  prior_failure_detail TEXT NOT NULL,
  prior_failure_detail_sha256 TEXT NOT NULL
    CHECK (prior_failure_detail_sha256 ~ '^[0-9a-f]{64}$'),
  replacement_failure_detail TEXT NOT NULL,
  prior_progress JSONB NOT NULL CHECK (jsonb_typeof(prior_progress) = 'object'),
  prior_retry_count INTEGER NOT NULL CHECK (prior_retry_count >= 0),
  expected_task_attempt INTEGER NOT NULL CHECK (expected_task_attempt > 0),
  expected_completed_stage_count INTEGER NOT NULL
    CHECK (expected_completed_stage_count > 0),
  expected_provider_operation_count INTEGER NOT NULL
    CHECK (expected_provider_operation_count > 0),
  expected_ledger_rows INTEGER NOT NULL CHECK (expected_ledger_rows > 0),
  expected_ledger_cost NUMERIC NOT NULL CHECK (expected_ledger_cost >= 0),
  expected_approved_cumulative_cap NUMERIC NOT NULL
    CHECK (expected_approved_cumulative_cap >= 0),
  expected_max_new_provider_spend NUMERIC NOT NULL
    CHECK (expected_max_new_provider_spend >= 0),
  task_error_sha256 TEXT NOT NULL CHECK (task_error_sha256 ~ '^[0-9a-f]{64}$'),
  fixed_by_commit TEXT NOT NULL CHECK (fixed_by_commit ~ '^[0-9a-f]{40}$'),
  authorization_reference TEXT NOT NULL CHECK (authorization_reference <> ''),
  requested_by TEXT NOT NULL CHECK (requested_by <> ''),
  transaction_id BIGINT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (tenant_id, video_id, runtime_hash)
);

CREATE OR REPLACE FUNCTION protect_custom_film_assembly_recovery_audit()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
  RAISE EXCEPTION 'Custom Film assembly recovery audit is immutable';
END;
$$;

DROP TRIGGER IF EXISTS custom_film_assembly_recovery_audit_immutable
  ON custom_film_assembly_recoveries;
CREATE TRIGGER custom_film_assembly_recovery_audit_immutable
  BEFORE UPDATE OR DELETE ON custom_film_assembly_recoveries
  FOR EACH ROW EXECUTE FUNCTION protect_custom_film_assembly_recovery_audit();

CREATE OR REPLACE FUNCTION protect_custom_film_assembly()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  old_phase_rank INTEGER;
  new_phase_rank INTEGER;
  authorized_terminal_recovery BOOLEAN := FALSE;
BEGIN
  IF OLD.state = 'terminal_failed' AND NEW.state = 'retryable_failed' THEN
    SELECT EXISTS (
      SELECT 1
      FROM public.custom_film_assembly_recoveries recovery
      WHERE recovery.tenant_id = OLD.tenant_id
        AND recovery.video_id = OLD.video_id
        AND recovery.runtime_job_id = OLD.runtime_job_id
        AND recovery.runtime_hash = OLD.runtime_hash
        AND recovery.manifest_version = OLD.manifest_version
        AND recovery.manifest_hash = OLD.manifest_hash
        AND recovery.storage_path = OLD.storage_path
        AND recovery.source_state = OLD.state
        AND recovery.target_state = NEW.state
        AND recovery.prior_failure_kind = OLD.failure_kind
        AND recovery.prior_failure_detail = OLD.failure_detail
        AND recovery.prior_progress = OLD.progress
        AND recovery.prior_retry_count = OLD.retry_count
        AND recovery.replacement_failure_detail = NEW.failure_detail
        AND recovery.transaction_id = txid_current()
    ) INTO authorized_terminal_recovery;

    authorized_terminal_recovery := authorized_terminal_recovery
      AND NEW.failure_kind = 'retryable'
      AND NEW.progress = jsonb_build_object(
        'phase', 'retryable_failed',
        'completed_sections', (OLD.progress->>'completed_sections')::integer,
        'total_sections', (OLD.progress->>'total_sections')::integer
      )
      AND NEW.retry_count = OLD.retry_count
      AND NEW.updated_at > OLD.updated_at
      AND (
        NEW.tenant_id, NEW.video_id, NEW.runtime_job_id, NEW.runtime_hash,
        NEW.manifest_version, NEW.manifest_hash, NEW.manifest,
        NEW.artifact_sha256, NEW.artifact_probe, NEW.storage_path,
        NEW.final_video_url, NEW.render_started_at, NEW.rendered_at,
        NEW.upload_started_at, NEW.uploaded_at, NEW.finalized_at, NEW.created_at
      ) IS NOT DISTINCT FROM (
        OLD.tenant_id, OLD.video_id, OLD.runtime_job_id, OLD.runtime_hash,
        OLD.manifest_version, OLD.manifest_hash, OLD.manifest,
        OLD.artifact_sha256, OLD.artifact_probe, OLD.storage_path,
        OLD.final_video_url, OLD.render_started_at, OLD.rendered_at,
        OLD.upload_started_at, OLD.uploaded_at, OLD.finalized_at, OLD.created_at
      );
  END IF;

  IF OLD.state = 'terminal_failed'
     AND NEW.state = 'terminal_failed'
     AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'Custom Film terminal assembly is immutable';
  END IF;
  IF (
    NEW.tenant_id, NEW.video_id, NEW.runtime_job_id, NEW.runtime_hash, NEW.manifest_version,
    NEW.manifest_hash, NEW.manifest, NEW.storage_path
  ) IS DISTINCT FROM (
    OLD.tenant_id, OLD.video_id, OLD.runtime_job_id, OLD.runtime_hash, OLD.manifest_version,
    OLD.manifest_hash, OLD.manifest, OLD.storage_path
  ) THEN
    RAISE EXCEPTION 'Custom Film assembly identity is immutable';
  END IF;
  IF OLD.artifact_sha256 IS NOT NULL
     AND NEW.artifact_sha256 IS DISTINCT FROM OLD.artifact_sha256 THEN
    RAISE EXCEPTION 'Custom Film assembly artifact hash is write-once';
  END IF;
  IF OLD.artifact_probe IS NOT NULL
     AND NEW.artifact_probe IS DISTINCT FROM OLD.artifact_probe THEN
    RAISE EXCEPTION 'Custom Film assembly probe is write-once';
  END IF;
  IF OLD.final_video_url IS NOT NULL
     AND NEW.final_video_url IS DISTINCT FROM OLD.final_video_url THEN
    RAISE EXCEPTION 'Custom Film assembly storage result is write-once';
  END IF;
  IF (NEW.progress->>'total_sections')::integer
       <> (OLD.progress->>'total_sections')::integer
     OR (NEW.progress->>'completed_sections')::integer
       < (OLD.progress->>'completed_sections')::integer THEN
    RAISE EXCEPTION 'Custom Film assembly progress cannot regress';
  END IF;
  old_phase_rank := CASE OLD.progress->>'phase'
    WHEN 'prepared' THEN 0 WHEN 'normalizing' THEN 1
    WHEN 'assembling' THEN 2 WHEN 'rendering' THEN 3
    WHEN 'uploading' THEN 4 WHEN 'finalized' THEN 5 ELSE 6 END;
  new_phase_rank := CASE NEW.progress->>'phase'
    WHEN 'prepared' THEN 0 WHEN 'normalizing' THEN 1
    WHEN 'assembling' THEN 2 WHEN 'rendering' THEN 3
    WHEN 'uploading' THEN 4 WHEN 'finalized' THEN 5 ELSE 6 END;
  IF OLD.state <> 'retryable_failed'
     AND NEW.progress->>'phase' NOT IN ('retryable_failed', 'terminal_failed')
     AND new_phase_rank < old_phase_rank THEN
    RAISE EXCEPTION 'Custom Film assembly phase cannot regress';
  END IF;
  IF (
    (OLD.state = 'prepared' AND NEW.state NOT IN ('prepared', 'rendering', 'retryable_failed', 'terminal_failed'))
    OR (OLD.state = 'rendering' AND NEW.state NOT IN ('rendering', 'rendered', 'retryable_failed', 'terminal_failed'))
    OR (OLD.state = 'rendered' AND NEW.state NOT IN ('rendered', 'uploading', 'retryable_failed', 'terminal_failed'))
    OR (OLD.state = 'uploading' AND NEW.state NOT IN ('uploading', 'uploaded', 'retryable_failed', 'terminal_failed'))
    OR (OLD.state = 'uploaded' AND NEW.state NOT IN ('uploaded', 'finalized', 'retryable_failed', 'terminal_failed'))
    OR (OLD.state = 'retryable_failed' AND NEW.state NOT IN ('retryable_failed', 'rendering', 'terminal_failed'))
    OR (OLD.state = 'finalized' AND NEW.state <> OLD.state)
    OR (
      OLD.state = 'terminal_failed'
      AND NEW.state <> OLD.state
      AND NOT authorized_terminal_recovery
    )
  ) THEN
    RAISE EXCEPTION 'Custom Film assembly state cannot regress or skip';
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION recover_custom_film_assembly_misclassification(
  p_tenant_id UUID,
  p_video_id UUID,
  p_runtime_job_id TEXT,
  p_runtime_hash TEXT,
  p_manifest_version TEXT,
  p_manifest_hash TEXT,
  p_render_engine TEXT,
  p_expected_total_sections INTEGER,
  p_expected_retry_count INTEGER,
  p_expected_task_attempt INTEGER,
  p_expected_completed_stage_count INTEGER,
  p_expected_provider_operation_count INTEGER,
  p_expected_ledger_rows INTEGER,
  p_expected_ledger_cost NUMERIC,
  p_expected_approved_cumulative_cap NUMERIC,
  p_expected_max_new_provider_spend NUMERIC,
  p_expected_video_status TEXT,
  p_expected_task_error_sha256 TEXT,
  p_expected_failure_detail_sha256 TEXT,
  p_fixed_by_commit TEXT,
  p_authorization_reference TEXT
) RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
STRICT
SET search_path = pg_catalog, public
AS $$
DECLARE
  task_row public.background_tasks%ROWTYPE;
  video_row public.videos%ROWTYPE;
  assembly_row public.custom_film_assemblies%ROWTYPE;
  provider_total INTEGER;
  provider_completed INTEGER;
  ledger_rows INTEGER;
  ledger_cost NUMERIC;
  claims_count INTEGER;
  active_count INTEGER;
  recovery UUID := gen_random_uuid();
  replacement_detail TEXT;
  updated_count INTEGER;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'Custom Film assembly recovery requires a serializable transaction';
  END IF;
  IF p_runtime_job_id <> 'custom-film-runtime:' || p_runtime_hash
     OR p_runtime_hash !~ '^[0-9a-f]{64}$'
     OR p_manifest_hash !~ '^[0-9a-f]{64}$'
     OR p_fixed_by_commit !~ '^[0-9a-f]{40}$'
     OR p_expected_task_error_sha256 !~ '^[0-9a-f]{64}$'
     OR p_expected_failure_detail_sha256 !~ '^[0-9a-f]{64}$'
     OR p_expected_total_sections <= 0
     OR p_expected_retry_count < 0
     OR p_expected_task_attempt <= 0
     OR p_expected_completed_stage_count <= 0
     OR p_expected_provider_operation_count <= 0
     OR p_expected_ledger_rows <= 0
     OR p_expected_ledger_cost < 0
     OR p_expected_approved_cumulative_cap < p_expected_ledger_cost
     OR p_expected_max_new_provider_spend < p_expected_ledger_cost
     OR btrim(p_authorization_reference) = ''
     OR btrim(p_expected_video_status) = '' THEN
    RAISE EXCEPTION 'Custom Film assembly recovery authorization is invalid';
  END IF;

  PERFORM pg_advisory_xact_lock(
    hashtextextended(
      p_tenant_id::text || ':' || p_video_id::text || ':' || p_runtime_hash,
      0
    )
  );

  SELECT * INTO STRICT task_row
  FROM public.background_tasks
  WHERE tenant_id = p_tenant_id
    AND video_id = p_video_id
    AND task_type = 'custom_film_runtime'
    AND job_id = p_runtime_job_id
  FOR UPDATE;

  SELECT * INTO STRICT video_row
  FROM public.videos
  WHERE tenant_id = p_tenant_id
    AND id = p_video_id
    AND deleted_at IS NULL
  FOR UPDATE;

  SELECT * INTO STRICT assembly_row
  FROM public.custom_film_assemblies
  WHERE tenant_id = p_tenant_id
    AND video_id = p_video_id
    AND runtime_hash = p_runtime_hash
  FOR UPDATE;

  PERFORM 1
  FROM public.custom_film_provider_operations
  WHERE tenant_id = p_tenant_id
    AND video_id = p_video_id
    AND runtime_job_id = p_runtime_job_id
    AND runtime_hash = p_runtime_hash
  ORDER BY operation_id
  FOR SHARE;

  PERFORM 1
  FROM public.generation_ledger
  WHERE tenant_id = p_tenant_id AND video_id = p_video_id
  ORDER BY id
  FOR SHARE;

  PERFORM 1
  FROM public.generation_claims
  WHERE tenant_id = p_tenant_id AND video_id = p_video_id
  ORDER BY id
  FOR UPDATE;

  PERFORM 1
  FROM public.background_tasks
  WHERE tenant_id = p_tenant_id
    AND video_id = p_video_id
    AND status IN ('pending', 'running')
  ORDER BY id
  FOR UPDATE;

  SELECT count(*),
         count(*) FILTER (WHERE state = 'completed' AND result IS NOT NULL)
  INTO provider_total, provider_completed
  FROM public.custom_film_provider_operations
  WHERE tenant_id = p_tenant_id
    AND video_id = p_video_id
    AND runtime_job_id = p_runtime_job_id
    AND runtime_hash = p_runtime_hash;

  SELECT count(*), COALESCE(sum(actual_cost), 0)
  INTO ledger_rows, ledger_cost
  FROM public.generation_ledger
  WHERE tenant_id = p_tenant_id AND video_id = p_video_id;

  SELECT count(*) INTO claims_count
  FROM public.generation_claims
  WHERE tenant_id = p_tenant_id AND video_id = p_video_id;

  SELECT count(*) INTO active_count
  FROM public.background_tasks
  WHERE tenant_id = p_tenant_id
    AND video_id = p_video_id
    AND status IN ('pending', 'running');

  IF task_row.status <> 'failed'
     OR task_row.attempt <> p_expected_task_attempt
     OR task_row.message <> 'Approved section runtime stopped'
     OR task_row.error_message IS NULL
     OR encode(digest(convert_to(task_row.error_message, 'UTF8'), 'sha256'), 'hex')
          <> p_expected_task_error_sha256
     OR task_row.completed_at IS NULL
     OR task_row.runtime_envelope->>'runtime_hash' <> p_runtime_hash
     OR task_row.runtime_envelope->>'video_id' <> p_video_id::text
     OR task_row.runtime_progress->>'runtime_hash' <> p_runtime_hash
     OR jsonb_typeof(task_row.runtime_progress->'completed_stage_keys') <> 'array'
     OR jsonb_array_length(task_row.runtime_progress->'completed_stage_keys')
          <> p_expected_completed_stage_count
     OR task_row.runtime_progress->'in_flight' <> 'null'::jsonb
     OR task_row.runtime_progress->>'last_stage_key'
          <> (task_row.runtime_progress->'completed_stage_keys')->>(
            p_expected_completed_stage_count - 1
          )
     OR task_row.runtime_progress->>'last_stage_key' NOT LIKE '%:quality'
     OR task_row.runtime_envelope->'spend_authority'->>'authority_version'
          <> 'custom-film-cumulative-authority-v1'
     OR task_row.runtime_envelope->'spend_authority'->>'approval_source'
          <> 'creator_exact_cumulative_approval'
     OR (task_row.runtime_envelope->'spend_authority'->>'approved_cumulative_cap')::numeric
          <> p_expected_approved_cumulative_cap
     OR (task_row.runtime_envelope->'spend_authority'->>'max_new_provider_spend')::numeric
          <> p_expected_max_new_provider_spend
     OR task_row.runtime_envelope->'spend_authority'->>'upload_authorized' <> 'false'
     OR task_row.runtime_envelope->'spend_authority'->>'publication_authorized' <> 'false'
     OR video_row.status IS DISTINCT FROM p_expected_video_status
     OR video_row.total_cost IS DISTINCT FROM p_expected_ledger_cost
     OR video_row.max_spend IS DISTINCT FROM p_expected_max_new_provider_spend
     OR video_row.final_video_url IS NOT NULL
     OR provider_total <> p_expected_provider_operation_count
     OR provider_completed <> p_expected_provider_operation_count
     OR ledger_rows <> p_expected_ledger_rows
     OR ledger_cost IS DISTINCT FROM p_expected_ledger_cost
     OR claims_count <> 0
     OR active_count <> 0 THEN
    RAISE EXCEPTION 'Custom Film paid-runtime recovery precondition drifted';
  END IF;

  IF assembly_row.state <> 'terminal_failed'
     OR assembly_row.runtime_job_id <> p_runtime_job_id
     OR assembly_row.manifest_version <> p_manifest_version
     OR assembly_row.manifest_hash <> p_manifest_hash
     OR assembly_row.manifest->>'assembly_version' <> p_manifest_version
     OR assembly_row.manifest->>'manifest_hash' <> p_manifest_hash
     OR assembly_row.manifest->>'runtime_hash' <> p_runtime_hash
     OR assembly_row.manifest->>'runtime_job_id' <> p_runtime_job_id
     OR assembly_row.manifest->>'tenant_id' <> p_tenant_id::text
     OR assembly_row.manifest->>'video_id' <> p_video_id::text
     OR assembly_row.manifest->>'render_engine' <> p_render_engine
     OR (assembly_row.manifest->>'max_spend')::numeric
          <> p_expected_max_new_provider_spend
     OR assembly_row.storage_path <> (
       p_video_id::text || '/final/custom-film-'
       || left(p_runtime_hash, 16) || '-' || left(p_manifest_hash, 16) || '.mp4'
     )
     OR assembly_row.failure_kind <> 'terminal'
     OR assembly_row.failure_detail IS NULL
     OR encode(
       digest(convert_to(assembly_row.failure_detail, 'UTF8'), 'sha256'),
       'hex'
     ) <> p_expected_failure_detail_sha256
     OR assembly_row.progress <> jsonb_build_object(
       'phase', 'terminal_failed',
       'completed_sections', 0,
       'total_sections', p_expected_total_sections
     )
     OR assembly_row.retry_count <> p_expected_retry_count
     OR assembly_row.artifact_sha256 IS NOT NULL
     OR assembly_row.artifact_probe IS NOT NULL
     OR assembly_row.final_video_url IS NOT NULL
     OR assembly_row.rendered_at IS NOT NULL
     OR assembly_row.upload_started_at IS NOT NULL
     OR assembly_row.uploaded_at IS NOT NULL
     OR assembly_row.finalized_at IS NOT NULL THEN
    RAISE EXCEPTION 'Custom Film terminal assembly recovery identity drifted';
  END IF;

  replacement_detail := 'Audited product-code recovery ' || recovery::text
    || ' (' || p_authorization_reference || ')';

  INSERT INTO public.custom_film_assembly_recoveries (
    recovery_id, tenant_id, video_id, runtime_job_id, runtime_hash,
    manifest_version, manifest_hash, render_engine, storage_path,
    source_state, target_state, prior_failure_kind, prior_failure_detail,
    prior_failure_detail_sha256, replacement_failure_detail, prior_progress,
    prior_retry_count, expected_task_attempt, expected_completed_stage_count,
    expected_provider_operation_count, expected_ledger_rows,
    expected_ledger_cost, expected_approved_cumulative_cap,
    expected_max_new_provider_spend, task_error_sha256, fixed_by_commit,
    authorization_reference, requested_by, transaction_id
  ) VALUES (
    recovery, p_tenant_id, p_video_id, p_runtime_job_id, p_runtime_hash,
    p_manifest_version, p_manifest_hash, p_render_engine,
    assembly_row.storage_path, 'terminal_failed', 'retryable_failed',
    assembly_row.failure_kind, assembly_row.failure_detail,
    p_expected_failure_detail_sha256, replacement_detail,
    assembly_row.progress, assembly_row.retry_count, p_expected_task_attempt,
    p_expected_completed_stage_count, p_expected_provider_operation_count,
    p_expected_ledger_rows, p_expected_ledger_cost,
    p_expected_approved_cumulative_cap, p_expected_max_new_provider_spend,
    p_expected_task_error_sha256, p_fixed_by_commit,
    p_authorization_reference, session_user, txid_current()
  );

  UPDATE public.custom_film_assemblies
  SET state = 'retryable_failed',
      failure_kind = 'retryable',
      failure_detail = replacement_detail,
      progress = jsonb_build_object(
        'phase', 'retryable_failed',
        'completed_sections', 0,
        'total_sections', p_expected_total_sections
      ),
      updated_at = clock_timestamp()
  WHERE tenant_id = p_tenant_id
    AND video_id = p_video_id
    AND runtime_hash = p_runtime_hash
    AND state = 'terminal_failed';
  GET DIAGNOSTICS updated_count = ROW_COUNT;
  IF updated_count <> 1 THEN
    RAISE EXCEPTION 'Custom Film terminal assembly recovery was not applied once';
  END IF;

  RETURN recovery;
END;
$$;

ALTER TABLE custom_film_assembly_recoveries ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE custom_film_assembly_recoveries
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION protect_custom_film_assembly_recovery_audit()
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION protect_custom_film_assembly()
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION recover_custom_film_assembly_misclassification(
  UUID, UUID, TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER, INTEGER, INTEGER,
  INTEGER, INTEGER, INTEGER, NUMERIC, NUMERIC, NUMERIC, TEXT, TEXT, TEXT,
  TEXT, TEXT
) FROM PUBLIC, anon, authenticated;

COMMIT;
