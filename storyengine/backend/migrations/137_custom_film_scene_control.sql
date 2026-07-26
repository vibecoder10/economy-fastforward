-- M9: deterministic scene-by-scene Custom Film control.
--
-- Film locks and scene events are append-only. Scene heads are mutable only
-- through revision-hash compare-and-set operations and become immutable once
-- accepted. This migration schedules no work and calls no provider.
BEGIN;

CREATE TABLE IF NOT EXISTS custom_film_film_locks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  plan_id UUID NOT NULL,
  video_id UUID NOT NULL,
  director_contract_id UUID NOT NULL,
  lock_kind TEXT NOT NULL CHECK (
    lock_kind IN (
      'story', 'dialogue', 'style', 'cast', 'environments', 'techniques'
    )
  ),
  revision INTEGER NOT NULL CHECK (revision > 0),
  payload JSONB NOT NULL,
  content_hash TEXT NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  approval_hash TEXT NOT NULL CHECK (approval_hash ~ '^[0-9a-f]{64}$'),
  synthetic BOOLEAN NOT NULL DEFAULT false,
  approved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, director_contract_id, lock_kind, revision),
  UNIQUE (tenant_id, director_contract_id, lock_kind, content_hash),
  UNIQUE (tenant_id, approval_hash),
  FOREIGN KEY (tenant_id, director_contract_id, plan_id, video_id)
    REFERENCES custom_film_director_contracts(
      tenant_id, id, plan_id, video_id
    ) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS custom_film_film_locks_latest_idx
  ON custom_film_film_locks
    (tenant_id, director_contract_id, lock_kind, revision DESC);

CREATE TABLE IF NOT EXISTS custom_film_scene_controls (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  plan_id UUID NOT NULL,
  video_id UUID NOT NULL,
  director_contract_id UUID NOT NULL,
  scene_number INTEGER NOT NULL CHECK (scene_number > 0),
  scene_contract JSONB NOT NULL
    CHECK (jsonb_typeof(scene_contract) = 'object'),
  revision INTEGER NOT NULL CHECK (revision > 0),
  revision_hash TEXT NOT NULL CHECK (revision_hash ~ '^[0-9a-f]{64}$'),
  film_lock_set_hash TEXT NOT NULL
    CHECK (film_lock_set_hash ~ '^[0-9a-f]{64}$'),
  artifact_hashes JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(artifact_hashes) = 'object'),
  artifact_manifest JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(artifact_manifest) = 'object'),
  state TEXT NOT NULL CHECK (
    state IN (
      'draft', 'plan_approved', 'storyboard_approved', 'imagery_approved',
      'animation_approved', 'audio_approved', 'assembled', 'accepted'
    )
  ),
  accepted_revision_hash TEXT CHECK (
    accepted_revision_hash IS NULL
    OR accepted_revision_hash ~ '^[0-9a-f]{64}$'
  ),
  synthetic BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, director_contract_id, scene_number),
  UNIQUE (tenant_id, director_contract_id, revision_hash),
  FOREIGN KEY (tenant_id, director_contract_id, plan_id, video_id)
    REFERENCES custom_film_director_contracts(
      tenant_id, id, plan_id, video_id
    ) ON DELETE CASCADE,
  CHECK (
    (state = 'accepted' AND accepted_revision_hash = revision_hash)
    OR (state <> 'accepted' AND accepted_revision_hash IS NULL)
  )
);

CREATE INDEX IF NOT EXISTS custom_film_scene_controls_rail_idx
  ON custom_film_scene_controls (tenant_id, video_id, scene_number);

CREATE TABLE IF NOT EXISTS custom_film_scene_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  plan_id UUID NOT NULL,
  video_id UUID NOT NULL,
  director_contract_id UUID NOT NULL,
  scene_id UUID NOT NULL,
  revision_hash TEXT NOT NULL CHECK (revision_hash ~ '^[0-9a-f]{64}$'),
  event_kind TEXT NOT NULL CHECK (
    event_kind IN (
      'scene_created', 'gate_approved', 'scene_revised',
      'film_lock_invalidated', 'scene_accepted'
    )
  ),
  from_state TEXT NOT NULL CHECK (
    from_state IN (
      'draft', 'plan_approved', 'storyboard_approved', 'imagery_approved',
      'animation_approved', 'audio_approved', 'assembled', 'accepted'
    )
  ),
  to_state TEXT NOT NULL CHECK (
    to_state IN (
      'draft', 'plan_approved', 'storyboard_approved', 'imagery_approved',
      'animation_approved', 'audio_approved', 'assembled', 'accepted'
    )
  ),
  evidence_hash TEXT NOT NULL CHECK (evidence_hash ~ '^[0-9a-f]{64}$'),
  invalidated_states JSONB NOT NULL DEFAULT '[]'::jsonb
    CHECK (jsonb_typeof(invalidated_states) = 'array'),
  event JSONB NOT NULL CHECK (jsonb_typeof(event) = 'object'),
  event_hash TEXT NOT NULL CHECK (event_hash ~ '^[0-9a-f]{64}$'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, event_hash),
  FOREIGN KEY (tenant_id, scene_id)
    REFERENCES custom_film_scene_controls(tenant_id, id) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, director_contract_id, plan_id, video_id)
    REFERENCES custom_film_director_contracts(
      tenant_id, id, plan_id, video_id
    ) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS custom_film_scene_events_history_idx
  ON custom_film_scene_events
    (tenant_id, scene_id, created_at DESC);

CREATE OR REPLACE FUNCTION protect_custom_film_scene_append_only()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$;

CREATE OR REPLACE FUNCTION protect_accepted_custom_film_scene()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Custom Film scene controls cannot be deleted';
  END IF;
  IF OLD.state = 'accepted' AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'Accepted Custom Film scenes are immutable';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS custom_film_film_locks_append_only
  ON custom_film_film_locks;
CREATE TRIGGER custom_film_film_locks_append_only
  BEFORE UPDATE OR DELETE ON custom_film_film_locks
  FOR EACH ROW EXECUTE FUNCTION protect_custom_film_scene_append_only();

DROP TRIGGER IF EXISTS custom_film_scene_events_append_only
  ON custom_film_scene_events;
CREATE TRIGGER custom_film_scene_events_append_only
  BEFORE UPDATE OR DELETE ON custom_film_scene_events
  FOR EACH ROW EXECUTE FUNCTION protect_custom_film_scene_append_only();

DROP TRIGGER IF EXISTS custom_film_scene_controls_protect
  ON custom_film_scene_controls;
CREATE TRIGGER custom_film_scene_controls_protect
  BEFORE UPDATE OR DELETE ON custom_film_scene_controls
  FOR EACH ROW EXECUTE FUNCTION protect_accepted_custom_film_scene();

ALTER TABLE custom_film_film_locks ENABLE ROW LEVEL SECURITY;
ALTER TABLE custom_film_scene_controls ENABLE ROW LEVEL SECURITY;
ALTER TABLE custom_film_scene_events ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON custom_film_film_locks FROM anon, authenticated;
REVOKE ALL ON custom_film_scene_controls FROM anon, authenticated;
REVOKE ALL ON custom_film_scene_events FROM anon, authenticated;

DO $policies$
DECLARE
  table_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'custom_film_film_locks',
    'custom_film_scene_controls',
    'custom_film_scene_events'
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
