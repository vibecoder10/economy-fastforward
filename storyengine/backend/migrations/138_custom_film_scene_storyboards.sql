-- M10-1: exact five-shot Scene Control storyboard execution.
BEGIN;

CREATE TABLE IF NOT EXISTS custom_film_scene_storyboard_runs (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  video_id UUID NOT NULL,
  scene_id UUID NOT NULL,
  scene_revision_hash TEXT NOT NULL CHECK (scene_revision_hash ~ '^[0-9a-f]{64}$'),
  approval_card JSONB NOT NULL CHECK (jsonb_typeof(approval_card)='object'),
  approval_card_hash TEXT NOT NULL CHECK (approval_card_hash ~ '^[0-9a-f]{64}$'),
  exact_cumulative_amount_cents INTEGER NOT NULL CHECK (exact_cumulative_amount_cents >= 25),
  state TEXT NOT NULL CHECK (state IN ('approved','running','completed','stopped','reconciliation_required')),
  approved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, scene_id, scene_revision_hash),
  FOREIGN KEY (tenant_id, scene_id)
    REFERENCES custom_film_scene_controls(tenant_id, id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS custom_film_scene_storyboard_operations (
  id UUID PRIMARY KEY,
  run_id UUID NOT NULL REFERENCES custom_film_scene_storyboard_runs(id) ON DELETE CASCADE,
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  video_id UUID NOT NULL,
  scene_id UUID NOT NULL,
  shot_id UUID NOT NULL,
  order_index INTEGER NOT NULL CHECK (order_index BETWEEN 1 AND 5),
  provider TEXT NOT NULL CHECK (provider='kie'),
  model TEXT NOT NULL CHECK (model='gpt-image-2'),
  prompt TEXT NOT NULL CHECK (length(prompt)>0),
  request JSONB NOT NULL CHECK (jsonb_typeof(request)='object'),
  request_hash TEXT NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  state TEXT NOT NULL CHECK (state IN ('prepared','creating','submitted','completed','failed','reconciliation_required')),
  provider_task_id TEXT,
  result JSONB CHECK (result IS NULL OR jsonb_typeof(result)='object'),
  error TEXT,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (run_id, shot_id),
  UNIQUE (run_id, order_index),
  UNIQUE (tenant_id, video_id, provider_task_id),
  FOREIGN KEY (tenant_id, scene_id)
    REFERENCES custom_film_scene_controls(tenant_id, id) ON DELETE CASCADE
);

CREATE OR REPLACE FUNCTION protect_scene_storyboard_run()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'Scene storyboard runs cannot be deleted';
  END IF;
  IF (NEW.id,NEW.tenant_id,NEW.video_id,NEW.scene_id,NEW.scene_revision_hash,
      NEW.approval_card,NEW.approval_card_hash,NEW.exact_cumulative_amount_cents,
      NEW.approved_at)
     IS DISTINCT FROM
     (OLD.id,OLD.tenant_id,OLD.video_id,OLD.scene_id,OLD.scene_revision_hash,
      OLD.approval_card,OLD.approval_card_hash,OLD.exact_cumulative_amount_cents,
      OLD.approved_at) THEN
    RAISE EXCEPTION 'Scene storyboard approval is immutable';
  END IF;
  IF NOT (
    NEW.state=OLD.state OR
    (OLD.state='approved' AND NEW.state IN ('running','completed','stopped','reconciliation_required')) OR
    (OLD.state='running' AND NEW.state IN ('completed','stopped','reconciliation_required')) OR
    (OLD.state='stopped' AND NEW.state IN ('running','completed','reconciliation_required'))
  ) THEN
    RAISE EXCEPTION 'Scene storyboard run state cannot regress';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS custom_film_scene_storyboard_runs_protect
  ON custom_film_scene_storyboard_runs;
CREATE TRIGGER custom_film_scene_storyboard_runs_protect
  BEFORE UPDATE OR DELETE ON custom_film_scene_storyboard_runs
  FOR EACH ROW EXECUTE FUNCTION protect_scene_storyboard_run();

CREATE OR REPLACE FUNCTION protect_scene_storyboard_operation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'Scene storyboard operations cannot be deleted';
  END IF;
  IF (NEW.id,NEW.run_id,NEW.tenant_id,NEW.video_id,NEW.scene_id,NEW.shot_id,
      NEW.order_index,NEW.provider,NEW.model,NEW.prompt,NEW.request,NEW.request_hash)
     IS DISTINCT FROM
     (OLD.id,OLD.run_id,OLD.tenant_id,OLD.video_id,OLD.scene_id,OLD.shot_id,
      OLD.order_index,OLD.provider,OLD.model,OLD.prompt,OLD.request,OLD.request_hash) THEN
    RAISE EXCEPTION 'Scene storyboard operation identity is immutable';
  END IF;
  IF OLD.provider_task_id IS NOT NULL AND NEW.provider_task_id IS DISTINCT FROM OLD.provider_task_id THEN
    RAISE EXCEPTION 'Scene storyboard provider identity is write-once';
  END IF;
  IF OLD.result IS NOT NULL AND NEW.result IS DISTINCT FROM OLD.result THEN
    RAISE EXCEPTION 'Scene storyboard result is write-once';
  END IF;
  IF NOT (
    NEW.state=OLD.state OR
    (OLD.state='prepared' AND NEW.state='creating') OR
    (OLD.state='creating' AND NEW.state IN ('submitted','reconciliation_required')) OR
    (OLD.state='submitted' AND NEW.state IN ('completed','failed','reconciliation_required'))
  ) THEN
    RAISE EXCEPTION 'Scene storyboard operation state cannot regress';
  END IF;
  IF NEW.state IN ('submitted','completed') AND NEW.provider_task_id IS NULL THEN
    RAISE EXCEPTION 'Scene storyboard submitted operation needs a provider task id';
  END IF;
  IF NEW.state='completed' AND NEW.result IS NULL THEN
    RAISE EXCEPTION 'Scene storyboard completed operation needs a result';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS custom_film_scene_storyboard_operations_protect
  ON custom_film_scene_storyboard_operations;
CREATE TRIGGER custom_film_scene_storyboard_operations_protect
  BEFORE UPDATE OR DELETE ON custom_film_scene_storyboard_operations
  FOR EACH ROW EXECUTE FUNCTION protect_scene_storyboard_operation();

ALTER TABLE custom_film_scene_storyboard_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE custom_film_scene_storyboard_operations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON custom_film_scene_storyboard_runs FROM anon, authenticated;
REVOKE ALL ON custom_film_scene_storyboard_operations FROM anon, authenticated;

COMMIT;
