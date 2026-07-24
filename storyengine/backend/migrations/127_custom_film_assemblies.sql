-- M2-5: immutable, restart-safe Custom Film assembly and upload journal.
CREATE TABLE IF NOT EXISTS custom_film_assemblies (
  tenant_id UUID NOT NULL,
  video_id UUID NOT NULL,
  runtime_job_id TEXT NOT NULL,
  runtime_hash TEXT NOT NULL CHECK (runtime_hash ~ '^[0-9a-f]{64}$'),
  manifest_version TEXT NOT NULL CHECK (
    manifest_version = 'custom-film-assembly-v1'
  ),
  manifest_hash TEXT NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
  manifest JSONB NOT NULL CHECK (jsonb_typeof(manifest) = 'object'),
  progress JSONB NOT NULL CHECK (
    jsonb_typeof(progress) = 'object'
    AND progress->>'phase' IN (
      'prepared', 'normalizing', 'assembling', 'rendering',
      'uploading', 'finalized', 'retryable_failed', 'terminal_failed'
    )
    AND (progress->>'completed_sections') ~ '^[0-9]+$'
    AND (progress->>'total_sections') ~ '^[1-9][0-9]*$'
    AND (progress->>'completed_sections')::integer
      <= (progress->>'total_sections')::integer
  ),
  state TEXT NOT NULL DEFAULT 'prepared' CHECK (
    state IN (
      'prepared', 'rendering', 'rendered', 'uploading', 'uploaded',
      'finalized', 'retryable_failed', 'terminal_failed'
    )
  ),
  artifact_sha256 TEXT CHECK (
    artifact_sha256 IS NULL OR artifact_sha256 ~ '^[0-9a-f]{64}$'
  ),
  artifact_probe JSONB,
  storage_path TEXT NOT NULL CHECK (storage_path <> ''),
  final_video_url TEXT,
  failure_detail TEXT,
  failure_kind TEXT CHECK (
    failure_kind IS NULL OR failure_kind IN ('retryable', 'terminal')
  ),
  retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
  render_started_at TIMESTAMPTZ,
  rendered_at TIMESTAMPTZ,
  upload_started_at TIMESTAMPTZ,
  uploaded_at TIMESTAMPTZ,
  finalized_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, video_id, runtime_hash),
  UNIQUE (tenant_id, video_id, manifest_hash),
  FOREIGN KEY (tenant_id, video_id)
    REFERENCES videos(tenant_id, id) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, video_id, runtime_job_id)
    REFERENCES background_tasks(tenant_id, video_id, job_id),
  CHECK (
    manifest->>'assembly_version' = manifest_version
    AND manifest->>'manifest_hash' = manifest_hash
    AND manifest->>'runtime_hash' = runtime_hash
    AND manifest->>'runtime_job_id' = runtime_job_id
    AND manifest->>'tenant_id' = tenant_id::text
    AND manifest->>'video_id' = video_id::text
  ),
  CHECK (
    state NOT IN ('rendered', 'uploading', 'uploaded', 'finalized')
    OR (artifact_sha256 IS NOT NULL AND artifact_probe IS NOT NULL
        AND rendered_at IS NOT NULL)
  ),
  CHECK (
    state NOT IN ('uploaded', 'finalized')
    OR (final_video_url IS NOT NULL AND uploaded_at IS NOT NULL)
  ),
  CHECK (state <> 'finalized' OR finalized_at IS NOT NULL)
);

CREATE OR REPLACE FUNCTION protect_custom_film_assembly()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  old_phase_rank INTEGER;
  new_phase_rank INTEGER;
BEGIN
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
    OR (OLD.state IN ('finalized', 'terminal_failed') AND NEW.state <> OLD.state)
  ) THEN
    RAISE EXCEPTION 'Custom Film assembly state cannot regress or skip';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS custom_film_assembly_protect
  ON custom_film_assemblies;
CREATE TRIGGER custom_film_assembly_protect
  BEFORE UPDATE ON custom_film_assemblies
  FOR EACH ROW EXECUTE FUNCTION protect_custom_film_assembly();

CREATE INDEX IF NOT EXISTS custom_film_assemblies_state_idx
  ON custom_film_assemblies (tenant_id, state, updated_at);

ALTER TABLE custom_film_assemblies ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE custom_film_assemblies FROM anon, authenticated;
