-- Repair Custom Film immutability triggers so every trigger references only
-- columns that exist on its own table. This preserves the established recipe,
-- plan, and section contracts while allowing plan approval fields to change.
BEGIN;

CREATE OR REPLACE FUNCTION protect_custom_film_recipe_contract()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF (
    NEW.id,
    NEW.tenant_id,
    NEW.recipe_family_id,
    NEW.version,
    NEW.compatibility_version,
    NEW.recipe,
    NEW.signature,
    NEW.created_at
  ) IS DISTINCT FROM (
    OLD.id,
    OLD.tenant_id,
    OLD.recipe_family_id,
    OLD.version,
    OLD.compatibility_version,
    OLD.recipe,
    OLD.signature,
    OLD.created_at
  ) THEN
    RAISE EXCEPTION 'Custom Film recipe versions are immutable';
  END IF;

  IF (NEW.name, NEW.name_key, NEW.archived_at)
     IS DISTINCT FROM (OLD.name, OLD.name_key, OLD.archived_at) THEN
    IF NEW.updated_at <= OLD.updated_at THEN
      RAISE EXCEPTION 'Custom Film recipe metadata timestamps must advance';
    END IF;
    IF OLD.archived_at IS NULL AND NEW.archived_at IS NOT NULL
       AND NEW.archived_at IS DISTINCT FROM NEW.updated_at THEN
      RAISE EXCEPTION 'Custom Film recipe archive timestamp must be truthful';
    END IF;
  ELSIF NEW.updated_at IS DISTINCT FROM OLD.updated_at THEN
    RAISE EXCEPTION 'Custom Film recipe updated_at cannot change alone';
  END IF;

  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION protect_custom_film_plan_contract()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF (
    NEW.id,
    NEW.tenant_id,
    NEW.video_id,
    NEW.revision,
    NEW.compatibility_version,
    NEW.plan,
    NEW.plan_hash,
    NEW.quote_inputs,
    NEW.quote_inputs_hash,
    NEW.created_at
  ) IS DISTINCT FROM (
    OLD.id,
    OLD.tenant_id,
    OLD.video_id,
    OLD.revision,
    OLD.compatibility_version,
    OLD.plan,
    OLD.plan_hash,
    OLD.quote_inputs,
    OLD.quote_inputs_hash,
    OLD.created_at
  ) THEN
    RAISE EXCEPTION 'Custom Film plan revisions are immutable';
  END IF;

  -- approval_hash and approved_at are deliberately omitted. Their table CHECK
  -- constraint still requires both fields to be set or cleared together.
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION protect_custom_film_section_contract()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Custom Film section contracts are immutable';
END;
$$;

DROP TRIGGER IF EXISTS custom_film_recipes_immutable
  ON custom_film_recipes;
CREATE TRIGGER custom_film_recipes_immutable
  BEFORE UPDATE ON custom_film_recipes
  FOR EACH ROW EXECUTE FUNCTION protect_custom_film_recipe_contract();

DROP TRIGGER IF EXISTS custom_film_plans_immutable
  ON custom_film_plans;
CREATE TRIGGER custom_film_plans_immutable
  BEFORE UPDATE ON custom_film_plans
  FOR EACH ROW EXECUTE FUNCTION protect_custom_film_plan_contract();

DROP TRIGGER IF EXISTS custom_film_sections_immutable
  ON custom_film_sections;
CREATE TRIGGER custom_film_sections_immutable
  BEFORE UPDATE ON custom_film_sections
  FOR EACH ROW EXECUTE FUNCTION protect_custom_film_section_contract();

-- No trigger depends on the unsafe shared function after the three replacements.
DROP FUNCTION IF EXISTS protect_custom_film_immutable_contract();

COMMIT;
