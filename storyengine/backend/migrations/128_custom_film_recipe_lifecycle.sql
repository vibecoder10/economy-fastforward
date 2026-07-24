-- Tenant-safe reusable Custom Film recipe names and atomic lifecycle support.
BEGIN;

ALTER TABLE custom_film_recipes
  ADD COLUMN IF NOT EXISTS name_key TEXT;

UPDATE custom_film_recipes
SET name_key = lower(regexp_replace(btrim(name), '\s+', ' ', 'g'))
WHERE name_key IS NULL;

ALTER TABLE custom_film_recipes
  ALTER COLUMN name_key SET NOT NULL;

ALTER TABLE custom_film_recipes
  DROP CONSTRAINT IF EXISTS custom_film_recipes_name_key_check;
ALTER TABLE custom_film_recipes
  ADD CONSTRAINT custom_film_recipes_name_key_check
  CHECK (btrim(name_key) <> '');

CREATE UNIQUE INDEX IF NOT EXISTS custom_film_recipes_active_name_uidx
  ON custom_film_recipes (tenant_id, name_key)
  WHERE archived_at IS NULL;

-- Recipe JSON/signature/version remain immutable. These two fields are
-- creator-facing metadata and may change together during a tenant-scoped rename.
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

COMMIT;
