-- Custom Film contract and persistence foundation.
--
-- Custom Film remains chat-hidden and BYOK.  This migration stores only
-- deterministic, validated contracts; it adds no planner, generation path,
-- provider credential, or approval action.
BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS videos_tenant_id_id_uidx
  ON videos (tenant_id, id);
CREATE UNIQUE INDEX IF NOT EXISTS scripts_tenant_video_id_uidx
  ON scripts (tenant_id, video_id, id);

CREATE TABLE IF NOT EXISTS custom_film_recipes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  recipe_family_id UUID NOT NULL,
  version INTEGER NOT NULL CHECK (version > 0),
  name TEXT NOT NULL CHECK (btrim(name) <> ''),
  compatibility_version TEXT NOT NULL CHECK (btrim(compatibility_version) <> ''),
  recipe JSONB NOT NULL CHECK (jsonb_typeof(recipe) = 'object'),
  signature TEXT NOT NULL CHECK (signature ~ '^[0-9a-f]{64}$'),
  archived_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, recipe_family_id, version)
);

CREATE UNIQUE INDEX IF NOT EXISTS custom_film_recipes_active_signature_uidx
  ON custom_film_recipes (tenant_id, signature)
  WHERE archived_at IS NULL;

CREATE INDEX IF NOT EXISTS custom_film_recipes_family_idx
  ON custom_film_recipes (tenant_id, recipe_family_id, version DESC);

CREATE TABLE IF NOT EXISTS custom_film_plans (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  video_id UUID NOT NULL,
  revision INTEGER NOT NULL CHECK (revision > 0),
  compatibility_version TEXT NOT NULL CHECK (btrim(compatibility_version) <> ''),
  plan JSONB NOT NULL CHECK (jsonb_typeof(plan) = 'object'),
  plan_hash TEXT NOT NULL CHECK (plan_hash ~ '^[0-9a-f]{64}$'),
  quote_inputs JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(quote_inputs) = 'object'),
  quote_inputs_hash TEXT NOT NULL CHECK (quote_inputs_hash ~ '^[0-9a-f]{64}$'),
  approval_hash TEXT CHECK (
    approval_hash IS NULL OR approval_hash ~ '^[0-9a-f]{64}$'
  ),
  approved_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, video_id, revision),
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, id, video_id),
  FOREIGN KEY (tenant_id, video_id)
    REFERENCES videos(tenant_id, id) ON DELETE CASCADE,
  CHECK (
    (approval_hash IS NULL AND approved_at IS NULL)
    OR (approval_hash IS NOT NULL AND approved_at IS NOT NULL)
  )
);

CREATE INDEX IF NOT EXISTS custom_film_plans_video_revision_idx
  ON custom_film_plans (tenant_id, video_id, revision DESC);

CREATE TABLE IF NOT EXISTS custom_film_sections (
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  plan_id UUID NOT NULL,
  video_id UUID NOT NULL,
  section_id UUID NOT NULL,
  order_index INTEGER NOT NULL CHECK (order_index >= 0),
  role TEXT NOT NULL CHECK (btrim(role) <> ''),
  purpose TEXT NOT NULL CHECK (btrim(purpose) <> ''),
  duration_units INTEGER NOT NULL CHECK (
    duration_units > 0 AND duration_units <= 1000000
  ),
  knobs JSONB NOT NULL CHECK (jsonb_typeof(knobs) = 'object'),
  provenance JSONB NOT NULL CHECK (jsonb_typeof(provenance) = 'object'),
  estimated_media JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(estimated_media) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, plan_id, section_id),
  UNIQUE (tenant_id, plan_id, video_id, section_id),
  UNIQUE (tenant_id, plan_id, order_index),
  FOREIGN KEY (tenant_id, plan_id, video_id)
    REFERENCES custom_film_plans(tenant_id, id, video_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS custom_film_sections_order_idx
  ON custom_film_sections (tenant_id, plan_id, order_index);

-- Scene assignment is intentionally separate from the immutable section
-- contract. A later compiler/runtime may attach one or more script scenes,
-- then remap them after script replanning without changing section identity.
CREATE TABLE IF NOT EXISTS custom_film_section_scenes (
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  plan_id UUID NOT NULL,
  video_id UUID NOT NULL,
  section_id UUID NOT NULL,
  script_id UUID NOT NULL,
  scene_order INTEGER NOT NULL CHECK (scene_order >= 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, plan_id, section_id, script_id),
  UNIQUE (tenant_id, plan_id, script_id),
  UNIQUE (tenant_id, plan_id, section_id, scene_order),
  FOREIGN KEY (tenant_id, plan_id, video_id, section_id)
    REFERENCES custom_film_sections(tenant_id, plan_id, video_id, section_id)
    ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, video_id, script_id)
    REFERENCES scripts(tenant_id, video_id, id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS custom_film_section_scenes_order_idx
  ON custom_film_section_scenes
    (tenant_id, plan_id, section_id, scene_order);

ALTER TABLE videos
  ADD COLUMN IF NOT EXISTS custom_film_plan_id UUID,
  ADD COLUMN IF NOT EXISTS custom_film_plan_revision INTEGER,
  ADD COLUMN IF NOT EXISTS custom_film_plan_hash TEXT,
  ADD COLUMN IF NOT EXISTS custom_film_quote_inputs_hash TEXT,
  ADD COLUMN IF NOT EXISTS custom_film_approval_hash TEXT,
  ADD COLUMN IF NOT EXISTS custom_film_approved_at TIMESTAMPTZ;

DO $constraint$
BEGIN
  ALTER TABLE videos
    ADD CONSTRAINT videos_custom_film_plan_fkey
    FOREIGN KEY (tenant_id, custom_film_plan_id)
    REFERENCES custom_film_plans(tenant_id, id)
    DEFERRABLE INITIALLY DEFERRED;
EXCEPTION WHEN duplicate_object THEN NULL;
END
$constraint$;

DO $constraint$
BEGIN
  ALTER TABLE videos
    ADD CONSTRAINT videos_custom_film_plan_revision_check
    CHECK (
      (custom_film_plan_id IS NULL
       AND custom_film_plan_revision IS NULL
       AND custom_film_plan_hash IS NULL
       AND custom_film_quote_inputs_hash IS NULL
       AND custom_film_approval_hash IS NULL
       AND custom_film_approved_at IS NULL)
      OR
      (custom_film_plan_id IS NOT NULL
       AND custom_film_plan_revision > 0
       AND custom_film_plan_hash ~ '^[0-9a-f]{64}$'
       AND custom_film_quote_inputs_hash ~ '^[0-9a-f]{64}$'
       AND (
         (custom_film_approval_hash IS NULL AND custom_film_approved_at IS NULL)
         OR
         (custom_film_approval_hash ~ '^[0-9a-f]{64}$'
          AND custom_film_approved_at IS NOT NULL)
       ))
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END
$constraint$;

CREATE OR REPLACE FUNCTION protect_custom_film_immutable_contract()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_TABLE_NAME = 'custom_film_sections' THEN
    RAISE EXCEPTION 'Custom Film section contracts are immutable';
  END IF;
  IF TG_TABLE_NAME = 'custom_film_recipes'
     AND (
       NEW.tenant_id,
       NEW.recipe_family_id,
       NEW.version,
       NEW.compatibility_version,
       NEW.recipe,
       NEW.signature
     ) IS DISTINCT FROM (
       OLD.tenant_id,
       OLD.recipe_family_id,
       OLD.version,
       OLD.compatibility_version,
       OLD.recipe,
       OLD.signature
     ) THEN
    RAISE EXCEPTION 'Custom Film recipe versions are immutable';
  END IF;
  IF TG_TABLE_NAME = 'custom_film_plans'
     AND (
       NEW.tenant_id,
       NEW.video_id,
       NEW.revision,
       NEW.compatibility_version,
       NEW.plan,
       NEW.plan_hash,
       NEW.quote_inputs,
       NEW.quote_inputs_hash
     ) IS DISTINCT FROM (
       OLD.tenant_id,
       OLD.video_id,
       OLD.revision,
       OLD.compatibility_version,
       OLD.plan,
       OLD.plan_hash,
       OLD.quote_inputs,
       OLD.quote_inputs_hash
     ) THEN
    RAISE EXCEPTION 'Custom Film plan revisions are immutable';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS custom_film_recipes_immutable
  ON custom_film_recipes;
CREATE TRIGGER custom_film_recipes_immutable
  BEFORE UPDATE ON custom_film_recipes
  FOR EACH ROW EXECUTE FUNCTION protect_custom_film_immutable_contract();

DROP TRIGGER IF EXISTS custom_film_plans_immutable
  ON custom_film_plans;
CREATE TRIGGER custom_film_plans_immutable
  BEFORE UPDATE ON custom_film_plans
  FOR EACH ROW EXECUTE FUNCTION protect_custom_film_immutable_contract();

DROP TRIGGER IF EXISTS custom_film_sections_immutable
  ON custom_film_sections;
CREATE TRIGGER custom_film_sections_immutable
  BEFORE UPDATE ON custom_film_sections
  FOR EACH ROW EXECUTE FUNCTION protect_custom_film_immutable_contract();

ALTER TABLE custom_film_recipes ENABLE ROW LEVEL SECURITY;
ALTER TABLE custom_film_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE custom_film_sections ENABLE ROW LEVEL SECURITY;
ALTER TABLE custom_film_section_scenes ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON custom_film_recipes FROM anon;
REVOKE ALL ON custom_film_plans FROM anon;
REVOKE ALL ON custom_film_sections FROM anon;
REVOKE ALL ON custom_film_section_scenes FROM anon;
-- These are backend-owned validated contracts. Direct authenticated writes
-- could bypass allowlists/hashes/provenance, so API clients receive no table
-- grants; RLS remains defense-in-depth if grants are ever reviewed later.
REVOKE ALL ON custom_film_recipes FROM authenticated;
REVOKE ALL ON custom_film_plans FROM authenticated;
REVOKE ALL ON custom_film_sections FROM authenticated;
REVOKE ALL ON custom_film_section_scenes FROM authenticated;

DO $policy$
BEGIN
  CREATE POLICY "Tenant isolation" ON custom_film_recipes
    FOR ALL TO authenticated
    USING (
      tenant_id IN (
        SELECT m.tenant_id FROM memberships m
        WHERE m.user_id = (SELECT auth.uid())
      )
    )
    WITH CHECK (
      tenant_id IN (
        SELECT m.tenant_id FROM memberships m
        WHERE m.user_id = (SELECT auth.uid())
      )
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END
$policy$;

DO $policy$
BEGIN
  CREATE POLICY "Tenant isolation" ON custom_film_plans
    FOR ALL TO authenticated
    USING (
      tenant_id IN (
        SELECT m.tenant_id FROM memberships m
        WHERE m.user_id = (SELECT auth.uid())
      )
    )
    WITH CHECK (
      tenant_id IN (
        SELECT m.tenant_id FROM memberships m
        WHERE m.user_id = (SELECT auth.uid())
      )
      AND EXISTS (
        SELECT 1 FROM videos v
        WHERE v.id = custom_film_plans.video_id
          AND v.tenant_id = custom_film_plans.tenant_id
      )
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END
$policy$;

DO $policy$
BEGIN
  CREATE POLICY "Tenant isolation" ON custom_film_sections
    FOR ALL TO authenticated
    USING (
      tenant_id IN (
        SELECT m.tenant_id FROM memberships m
        WHERE m.user_id = (SELECT auth.uid())
      )
    )
    WITH CHECK (
      tenant_id IN (
        SELECT m.tenant_id FROM memberships m
        WHERE m.user_id = (SELECT auth.uid())
      )
      AND EXISTS (
        SELECT 1 FROM custom_film_plans p
        WHERE p.id = custom_film_sections.plan_id
          AND p.tenant_id = custom_film_sections.tenant_id
      )
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END
$policy$;

DO $policy$
BEGIN
  CREATE POLICY "Tenant isolation" ON custom_film_section_scenes
    FOR ALL TO authenticated
    USING (
      tenant_id IN (
        SELECT m.tenant_id FROM memberships m
        WHERE m.user_id = (SELECT auth.uid())
      )
    )
    WITH CHECK (
      tenant_id IN (
        SELECT m.tenant_id FROM memberships m
        WHERE m.user_id = (SELECT auth.uid())
      )
      AND EXISTS (
        SELECT 1 FROM custom_film_sections s
        WHERE s.plan_id = custom_film_section_scenes.plan_id
          AND s.video_id = custom_film_section_scenes.video_id
          AND s.section_id = custom_film_section_scenes.section_id
          AND s.tenant_id = custom_film_section_scenes.tenant_id
      )
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END
$policy$;

COMMIT;
