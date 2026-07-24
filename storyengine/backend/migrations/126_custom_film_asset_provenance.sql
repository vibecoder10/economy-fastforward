-- M2-4B2c: exact per-asset ownership for Custom Film section media.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'assets_tenant_video_id_uidx'
      AND conrelid = 'assets'::regclass
  ) THEN
    ALTER TABLE assets
      ADD CONSTRAINT assets_tenant_video_id_uidx
      UNIQUE (tenant_id, video_id, id);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'custom_film_provider_operations_identity_uidx'
      AND conrelid = 'custom_film_provider_operations'::regclass
  ) THEN
    ALTER TABLE custom_film_provider_operations
      ADD CONSTRAINT custom_film_provider_operations_identity_uidx
      UNIQUE (operation_id, tenant_id, video_id, runtime_hash);
  END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS custom_film_asset_provenance (
  tenant_id UUID NOT NULL,
  video_id UUID NOT NULL,
  asset_id UUID NOT NULL,
  plan_id UUID NOT NULL,
  section_id UUID NOT NULL,
  runtime_hash TEXT NOT NULL CHECK (runtime_hash ~ '^[0-9a-f]{64}$'),
  stage TEXT NOT NULL CHECK (stage IN ('pictures', 'motion', 'clips')),
  operation_id TEXT NOT NULL
    CHECK (operation_id ~ '^custom-film-op:[0-9a-f]{64}$'),
  request_hash TEXT NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  section_contract_hash TEXT NOT NULL
    CHECK (section_contract_hash ~ '^[0-9a-f]{64}$'),
  generation_method TEXT NOT NULL CHECK (generation_method <> ''),
  provider_model TEXT,
  status TEXT NOT NULL DEFAULT 'prepared'
    CHECK (status IN ('prepared', 'completed', 'failed')),
  artifact_url_hash TEXT CHECK (
    artifact_url_hash IS NULL OR artifact_url_hash ~ '^[0-9a-f]{64}$'
  ),
  exact_duration_seconds NUMERIC(12,3) CHECK (
    exact_duration_seconds IS NULL OR exact_duration_seconds > 0
  ),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, video_id, asset_id, runtime_hash, stage),
  FOREIGN KEY (tenant_id, video_id, asset_id)
    REFERENCES assets(tenant_id, video_id, id) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, plan_id, video_id, section_id)
    REFERENCES custom_film_sections(tenant_id, plan_id, video_id, section_id)
    ON DELETE CASCADE,
  FOREIGN KEY (operation_id, tenant_id, video_id, runtime_hash)
    REFERENCES custom_film_provider_operations(
      operation_id, tenant_id, video_id, runtime_hash
    ) ON DELETE CASCADE,
  CHECK (
    (status = 'completed' AND artifact_url_hash IS NOT NULL
     AND completed_at IS NOT NULL)
    OR
    (status <> 'completed' AND completed_at IS NULL)
  )
);

CREATE INDEX IF NOT EXISTS custom_film_asset_provenance_section_idx
  ON custom_film_asset_provenance
    (tenant_id, video_id, plan_id, section_id, runtime_hash, stage);

CREATE OR REPLACE FUNCTION protect_custom_film_asset_provenance()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF (
    NEW.tenant_id, NEW.video_id, NEW.asset_id, NEW.plan_id, NEW.section_id,
    NEW.runtime_hash, NEW.stage, NEW.operation_id, NEW.request_hash,
    NEW.section_contract_hash,
    NEW.generation_method
  ) IS DISTINCT FROM (
    OLD.tenant_id, OLD.video_id, OLD.asset_id, OLD.plan_id, OLD.section_id,
    OLD.runtime_hash, OLD.stage, OLD.operation_id, OLD.request_hash,
    OLD.section_contract_hash,
    OLD.generation_method
  ) THEN
    RAISE EXCEPTION 'Custom Film asset provenance identity is immutable';
  END IF;
  IF OLD.provider_model IS NOT NULL
     AND NEW.provider_model IS DISTINCT FROM OLD.provider_model THEN
    RAISE EXCEPTION 'Custom Film asset provider model is write-once';
  END IF;
  IF OLD.artifact_url_hash IS NOT NULL
     AND NEW.artifact_url_hash IS DISTINCT FROM OLD.artifact_url_hash THEN
    RAISE EXCEPTION 'Custom Film asset URL identity is write-once';
  END IF;
  IF OLD.exact_duration_seconds IS NOT NULL
     AND NEW.exact_duration_seconds IS DISTINCT FROM OLD.exact_duration_seconds THEN
    RAISE EXCEPTION 'Custom Film asset duration is write-once';
  END IF;
  IF (
    (OLD.status = 'prepared' AND NEW.status NOT IN ('prepared', 'completed', 'failed'))
    OR (OLD.status IN ('completed', 'failed') AND NEW.status <> OLD.status)
  ) THEN
    RAISE EXCEPTION 'Custom Film asset provenance status cannot regress';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS custom_film_asset_provenance_protect
  ON custom_film_asset_provenance;
CREATE TRIGGER custom_film_asset_provenance_protect
  BEFORE UPDATE ON custom_film_asset_provenance
  FOR EACH ROW EXECUTE FUNCTION protect_custom_film_asset_provenance();

ALTER TABLE custom_film_asset_provenance ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE custom_film_asset_provenance FROM anon, authenticated;
