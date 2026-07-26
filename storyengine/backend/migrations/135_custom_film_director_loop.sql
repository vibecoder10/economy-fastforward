-- M8: storyboard-driven Custom Film director loop.
--
-- Public production profiles are shot techniques, never competing film
-- identities. One immutable director contract owns story, style, cast,
-- environments, props, geography, timeline, and exact shot state. Reference,
-- storyboard, and visual-verification evidence is append-only. Exact cumulative
-- stage authorities list every billable operation, including helper work.
--
-- This migration schedules no work and calls no provider.
BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS video_characters_tenant_id_id_uidx
  ON video_characters (tenant_id, id);
CREATE UNIQUE INDEX IF NOT EXISTS video_environments_tenant_id_id_uidx
  ON video_environments (tenant_id, id);

CREATE TABLE IF NOT EXISTS custom_film_director_contracts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  plan_id UUID NOT NULL,
  video_id UUID NOT NULL,
  revision INTEGER NOT NULL CHECK (revision > 0),
  schema_version INTEGER NOT NULL CHECK (schema_version > 0),
  fps INTEGER NOT NULL CHECK (fps > 0 AND fps <= 120),
  total_frames INTEGER NOT NULL CHECK (total_frames > 0),
  plan_hash TEXT NOT NULL CHECK (plan_hash ~ '^[0-9a-f]{64}$'),
  film_bible JSONB NOT NULL CHECK (jsonb_typeof(film_bible) = 'object'),
  film_bible_hash TEXT NOT NULL CHECK (film_bible_hash ~ '^[0-9a-f]{64}$'),
  director_contract JSONB NOT NULL
    CHECK (jsonb_typeof(director_contract) = 'object'),
  contract_hash TEXT NOT NULL CHECK (contract_hash ~ '^[0-9a-f]{64}$'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, plan_id, revision),
  UNIQUE (tenant_id, plan_id, contract_hash),
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, id, plan_id, video_id),
  FOREIGN KEY (tenant_id, plan_id, video_id)
    REFERENCES custom_film_plans(tenant_id, id, video_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS custom_film_director_video_idx
  ON custom_film_director_contracts (tenant_id, video_id, revision DESC);

CREATE TABLE IF NOT EXISTS custom_film_shots (
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  director_contract_id UUID NOT NULL,
  plan_id UUID NOT NULL,
  video_id UUID NOT NULL,
  section_id UUID NOT NULL,
  shot_id UUID NOT NULL,
  shot_key TEXT NOT NULL CHECK (shot_key ~ '^[a-z][a-z0-9_]{1,63}$'),
  order_index INTEGER NOT NULL CHECK (order_index >= 0),
  start_frame INTEGER NOT NULL CHECK (start_frame >= 0),
  end_frame INTEGER NOT NULL CHECK (end_frame >= start_frame),
  duration_frames INTEGER NOT NULL CHECK (
    duration_frames > 0 AND duration_frames = end_frame - start_frame + 1
  ),
  technique TEXT NOT NULL CHECK (
    technique IN (
      'poco_dialogue',
      'dvsu_documentary',
      'power_doctrine_exposition',
      'cinematic_action'
    )
  ),
  performance_mode TEXT NOT NULL CHECK (
    performance_mode IN ('dialogue', 'exposition', 'silent_action')
  ),
  shot_contract JSONB NOT NULL CHECK (jsonb_typeof(shot_contract) = 'object'),
  shot_hash TEXT NOT NULL CHECK (shot_hash ~ '^[0-9a-f]{64}$'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, director_contract_id, shot_id),
  UNIQUE (tenant_id, director_contract_id, shot_key),
  UNIQUE (tenant_id, director_contract_id, order_index),
  UNIQUE (tenant_id, director_contract_id, shot_hash),
  FOREIGN KEY (tenant_id, director_contract_id, plan_id, video_id)
    REFERENCES custom_film_director_contracts(
      tenant_id, id, plan_id, video_id
    ) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, plan_id, video_id, section_id)
    REFERENCES custom_film_sections(tenant_id, plan_id, video_id, section_id)
    ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS custom_film_shots_section_idx
  ON custom_film_shots
    (tenant_id, director_contract_id, section_id, order_index);

CREATE TABLE IF NOT EXISTS custom_film_lock_references (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  director_contract_id UUID NOT NULL,
  lock_kind TEXT NOT NULL CHECK (lock_kind IN ('character', 'environment')),
  lock_id TEXT NOT NULL CHECK (lock_id ~ '^[a-z][a-z0-9_]{1,63}$'),
  review_revision INTEGER NOT NULL CHECK (review_revision > 0),
  character_reference_id UUID,
  environment_reference_id UUID,
  reference_artifact_id TEXT NOT NULL CHECK (btrim(reference_artifact_id) <> ''),
  reference_image_sha256 TEXT NOT NULL
    CHECK (reference_image_sha256 ~ '^[0-9a-f]{64}$'),
  lock_prompt_hash TEXT NOT NULL CHECK (lock_prompt_hash ~ '^[0-9a-f]{64}$'),
  review JSONB NOT NULL CHECK (jsonb_typeof(review) = 'object'),
  review_hash TEXT NOT NULL CHECK (review_hash ~ '^[0-9a-f]{64}$'),
  verdict TEXT NOT NULL CHECK (verdict IN ('approved', 'rejected')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (
    tenant_id,
    director_contract_id,
    lock_kind,
    lock_id,
    review_revision
  ),
  FOREIGN KEY (tenant_id, director_contract_id)
    REFERENCES custom_film_director_contracts(tenant_id, id)
    ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, character_reference_id)
    REFERENCES video_characters(tenant_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (tenant_id, environment_reference_id)
    REFERENCES video_environments(tenant_id, id) ON DELETE RESTRICT,
  CHECK (
    (
      lock_kind = 'character'
      AND character_reference_id IS NOT NULL
      AND environment_reference_id IS NULL
    )
    OR
    (
      lock_kind = 'environment'
      AND environment_reference_id IS NOT NULL
      AND character_reference_id IS NULL
    )
  )
);

CREATE INDEX IF NOT EXISTS custom_film_lock_references_latest_idx
  ON custom_film_lock_references
    (tenant_id, director_contract_id, lock_kind, lock_id, review_revision DESC);

CREATE TABLE IF NOT EXISTS custom_film_storyboard_reviews (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  director_contract_id UUID NOT NULL,
  shot_id UUID NOT NULL,
  review_revision INTEGER NOT NULL CHECK (review_revision > 0),
  reference_gate_hash TEXT NOT NULL
    CHECK (reference_gate_hash ~ '^[0-9a-f]{64}$'),
  storyboard_artifact_id TEXT NOT NULL
    CHECK (btrim(storyboard_artifact_id) <> ''),
  storyboard_image_sha256 TEXT NOT NULL
    CHECK (storyboard_image_sha256 ~ '^[0-9a-f]{64}$'),
  storyboard_prompt_hash TEXT NOT NULL
    CHECK (storyboard_prompt_hash ~ '^[0-9a-f]{64}$'),
  review JSONB NOT NULL CHECK (jsonb_typeof(review) = 'object'),
  review_hash TEXT NOT NULL CHECK (review_hash ~ '^[0-9a-f]{64}$'),
  verdict TEXT NOT NULL CHECK (verdict IN ('approved', 'rejected')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, director_contract_id, shot_id, review_revision),
  FOREIGN KEY (tenant_id, director_contract_id, shot_id)
    REFERENCES custom_film_shots(tenant_id, director_contract_id, shot_id)
    ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS custom_film_storyboard_reviews_latest_idx
  ON custom_film_storyboard_reviews
    (tenant_id, director_contract_id, shot_id, review_revision DESC);

CREATE TABLE IF NOT EXISTS custom_film_picture_reviews (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  director_contract_id UUID NOT NULL,
  shot_id UUID NOT NULL,
  review_revision INTEGER NOT NULL CHECK (review_revision > 0),
  storyboard_gate_hash TEXT NOT NULL
    CHECK (storyboard_gate_hash ~ '^[0-9a-f]{64}$'),
  final_picture_artifact_id TEXT NOT NULL
    CHECK (btrim(final_picture_artifact_id) <> ''),
  final_picture_sha256 TEXT NOT NULL
    CHECK (final_picture_sha256 ~ '^[0-9a-f]{64}$'),
  final_picture_prompt_hash TEXT NOT NULL
    CHECK (final_picture_prompt_hash ~ '^[0-9a-f]{64}$'),
  review JSONB NOT NULL CHECK (jsonb_typeof(review) = 'object'),
  review_hash TEXT NOT NULL CHECK (review_hash ~ '^[0-9a-f]{64}$'),
  verdict TEXT NOT NULL CHECK (verdict IN ('approved', 'rejected')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, director_contract_id, shot_id, review_revision),
  FOREIGN KEY (tenant_id, director_contract_id, shot_id)
    REFERENCES custom_film_shots(tenant_id, director_contract_id, shot_id)
    ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS custom_film_picture_reviews_latest_idx
  ON custom_film_picture_reviews
    (tenant_id, director_contract_id, shot_id, review_revision DESC);

CREATE TABLE IF NOT EXISTS custom_film_visual_verifications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  director_contract_id UUID NOT NULL,
  shot_id UUID NOT NULL,
  attempt INTEGER NOT NULL CHECK (attempt > 0),
  storyboard_gate_hash TEXT NOT NULL
    CHECK (storyboard_gate_hash ~ '^[0-9a-f]{64}$'),
  picture_gate_hash TEXT NOT NULL
    CHECK (picture_gate_hash ~ '^[0-9a-f]{64}$'),
  clip_artifact_id TEXT NOT NULL CHECK (btrim(clip_artifact_id) <> ''),
  observations JSONB NOT NULL CHECK (jsonb_typeof(observations) = 'array'),
  issue_codes JSONB NOT NULL CHECK (jsonb_typeof(issue_codes) = 'array'),
  verification JSONB NOT NULL CHECK (jsonb_typeof(verification) = 'object'),
  verification_hash TEXT NOT NULL CHECK (verification_hash ~ '^[0-9a-f]{64}$'),
  verdict TEXT NOT NULL CHECK (verdict IN ('approved', 'rejected')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, director_contract_id, shot_id, attempt),
  UNIQUE (tenant_id, director_contract_id, shot_id, verification_hash),
  FOREIGN KEY (tenant_id, director_contract_id, shot_id)
    REFERENCES custom_film_shots(tenant_id, director_contract_id, shot_id)
    ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS custom_film_visual_verifications_latest_idx
  ON custom_film_visual_verifications
    (tenant_id, director_contract_id, shot_id, attempt DESC);

CREATE TABLE IF NOT EXISTS custom_film_stage_authorities (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  plan_id UUID NOT NULL,
  video_id UUID NOT NULL,
  director_contract_id UUID,
  stage TEXT NOT NULL CHECK (
    stage IN (
      'script_director',
      'references',
      'storyboards',
      'final_pictures',
      'animation_voice',
      'assembly'
    )
  ),
  stage_binding_hash TEXT NOT NULL
    CHECK (stage_binding_hash ~ '^[0-9a-f]{64}$'),
  upstream_gate_hash TEXT NOT NULL
    CHECK (upstream_gate_hash ~ '^[0-9a-f]{64}$'),
  quote_hash TEXT NOT NULL CHECK (quote_hash ~ '^[0-9a-f]{64}$'),
  approval_hash TEXT NOT NULL CHECK (approval_hash ~ '^[0-9a-f]{64}$'),
  prior_cumulative_cents BIGINT NOT NULL CHECK (prior_cumulative_cents >= 0),
  approved_cumulative_cents BIGINT NOT NULL CHECK (
    approved_cumulative_cents >= prior_cumulative_cents
  ),
  bill_of_materials JSONB NOT NULL
    CHECK (jsonb_typeof(bill_of_materials) = 'array'),
  authority JSONB NOT NULL CHECK (jsonb_typeof(authority) = 'object'),
  authority_hash TEXT NOT NULL CHECK (authority_hash ~ '^[0-9a-f]{64}$'),
  approved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  consumed_at TIMESTAMPTZ,
  consumed_by TEXT,
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, plan_id, stage, approval_hash),
  UNIQUE (tenant_id, approval_hash),
  FOREIGN KEY (tenant_id, plan_id, video_id)
    REFERENCES custom_film_plans(tenant_id, id, video_id) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, director_contract_id, plan_id, video_id)
    REFERENCES custom_film_director_contracts(
      tenant_id, id, plan_id, video_id
    ) ON DELETE CASCADE,
  CHECK (
    (stage = 'script_director' AND director_contract_id IS NULL)
    OR
    (stage <> 'script_director' AND director_contract_id IS NOT NULL)
  ),
  CHECK (
    (consumed_at IS NULL AND consumed_by IS NULL)
    OR
    (consumed_at IS NOT NULL AND btrim(consumed_by) <> '')
  )
);

CREATE INDEX IF NOT EXISTS custom_film_stage_authorities_stage_idx
  ON custom_film_stage_authorities
    (tenant_id, plan_id, stage, approved_at DESC);

CREATE TABLE IF NOT EXISTS custom_film_director_stage_schedules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  plan_id UUID NOT NULL,
  video_id UUID NOT NULL,
  director_contract_id UUID,
  authority_id UUID NOT NULL,
  stage TEXT NOT NULL CHECK (
    stage IN (
      'script_director',
      'references',
      'storyboards',
      'final_pictures',
      'animation_voice',
      'assembly'
    )
  ),
  stage_binding_hash TEXT NOT NULL
    CHECK (stage_binding_hash ~ '^[0-9a-f]{64}$'),
  upstream_gate_hash TEXT NOT NULL
    CHECK (upstream_gate_hash ~ '^[0-9a-f]{64}$'),
  authority_hash TEXT NOT NULL CHECK (authority_hash ~ '^[0-9a-f]{64}$'),
  schedule JSONB NOT NULL CHECK (jsonb_typeof(schedule) = 'object'),
  schedule_hash TEXT NOT NULL CHECK (schedule_hash ~ '^[0-9a-f]{64}$'),
  task_count INTEGER NOT NULL CHECK (task_count > 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, authority_id),
  UNIQUE (tenant_id, schedule_hash),
  FOREIGN KEY (tenant_id, plan_id, video_id)
    REFERENCES custom_film_plans(tenant_id, id, video_id) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, authority_id)
    REFERENCES custom_film_stage_authorities(tenant_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (tenant_id, director_contract_id, plan_id, video_id)
    REFERENCES custom_film_director_contracts(
      tenant_id, id, plan_id, video_id
    ) ON DELETE CASCADE,
  CHECK (
    (stage = 'script_director' AND director_contract_id IS NULL)
    OR
    (stage <> 'script_director' AND director_contract_id IS NOT NULL)
  )
);

CREATE INDEX IF NOT EXISTS custom_film_director_stage_schedule_idx
  ON custom_film_director_stage_schedules
    (tenant_id, plan_id, stage, created_at DESC);

CREATE OR REPLACE FUNCTION protect_custom_film_director_append_only()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$;

CREATE OR REPLACE FUNCTION protect_custom_film_stage_authority()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Custom Film stage authorities cannot be deleted';
  END IF;
  IF OLD.consumed_at IS NOT NULL
     OR NEW.consumed_at IS NULL
     OR NEW.consumed_by IS NULL
     OR btrim(NEW.consumed_by) = ''
     OR (
       NEW.id,
       NEW.tenant_id,
       NEW.plan_id,
       NEW.video_id,
       NEW.director_contract_id,
       NEW.stage,
       NEW.stage_binding_hash,
       NEW.upstream_gate_hash,
       NEW.quote_hash,
       NEW.approval_hash,
       NEW.prior_cumulative_cents,
       NEW.approved_cumulative_cents,
       NEW.bill_of_materials,
       NEW.authority,
       NEW.authority_hash,
       NEW.approved_at
     ) IS DISTINCT FROM (
       OLD.id,
       OLD.tenant_id,
       OLD.plan_id,
       OLD.video_id,
       OLD.director_contract_id,
       OLD.stage,
       OLD.stage_binding_hash,
       OLD.upstream_gate_hash,
       OLD.quote_hash,
       OLD.approval_hash,
       OLD.prior_cumulative_cents,
       OLD.approved_cumulative_cents,
       OLD.bill_of_materials,
       OLD.authority,
       OLD.authority_hash,
       OLD.approved_at
     ) THEN
    RAISE EXCEPTION 'Custom Film stage authority is immutable';
  END IF;
  RETURN NEW;
END;
$$;

DO $triggers$
DECLARE
  table_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'custom_film_director_contracts',
    'custom_film_shots',
    'custom_film_lock_references',
    'custom_film_storyboard_reviews',
    'custom_film_picture_reviews',
    'custom_film_visual_verifications',
    'custom_film_director_stage_schedules'
  ]
  LOOP
    EXECUTE format(
      'DROP TRIGGER IF EXISTS %I ON %I',
      table_name || '_append_only',
      table_name
    );
    EXECUTE format(
      'CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I '
      'FOR EACH ROW EXECUTE FUNCTION protect_custom_film_director_append_only()',
      table_name || '_append_only',
      table_name
    );
  END LOOP;
END;
$triggers$;

DROP TRIGGER IF EXISTS custom_film_stage_authorities_protect
  ON custom_film_stage_authorities;
CREATE TRIGGER custom_film_stage_authorities_protect
  BEFORE UPDATE OR DELETE ON custom_film_stage_authorities
  FOR EACH ROW EXECUTE FUNCTION protect_custom_film_stage_authority();

ALTER TABLE custom_film_director_contracts ENABLE ROW LEVEL SECURITY;
ALTER TABLE custom_film_shots ENABLE ROW LEVEL SECURITY;
ALTER TABLE custom_film_lock_references ENABLE ROW LEVEL SECURITY;
ALTER TABLE custom_film_storyboard_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE custom_film_picture_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE custom_film_visual_verifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE custom_film_stage_authorities ENABLE ROW LEVEL SECURITY;
ALTER TABLE custom_film_director_stage_schedules ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON custom_film_director_contracts FROM anon, authenticated;
REVOKE ALL ON custom_film_shots FROM anon, authenticated;
REVOKE ALL ON custom_film_lock_references FROM anon, authenticated;
REVOKE ALL ON custom_film_storyboard_reviews FROM anon, authenticated;
REVOKE ALL ON custom_film_picture_reviews FROM anon, authenticated;
REVOKE ALL ON custom_film_visual_verifications FROM anon, authenticated;
REVOKE ALL ON custom_film_stage_authorities FROM anon, authenticated;
REVOKE ALL ON custom_film_director_stage_schedules FROM anon, authenticated;

DO $policies$
DECLARE
  table_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'custom_film_director_contracts',
    'custom_film_shots',
    'custom_film_lock_references',
    'custom_film_storyboard_reviews',
    'custom_film_picture_reviews',
    'custom_film_visual_verifications',
    'custom_film_stage_authorities',
    'custom_film_director_stage_schedules'
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
