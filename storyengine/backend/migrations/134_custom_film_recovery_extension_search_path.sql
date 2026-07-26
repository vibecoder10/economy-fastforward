-- Migration 133's recovery function hashes exact failure evidence with
-- pgcrypto.digest(). Production installs pgcrypto in the locked extensions
-- schema, so include that exact schema in the SECURITY DEFINER search path.
BEGIN;

ALTER FUNCTION recover_custom_film_assembly_misclassification(
  UUID, UUID, TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER, INTEGER, INTEGER,
  INTEGER, INTEGER, INTEGER, NUMERIC, NUMERIC, NUMERIC, TEXT, TEXT, TEXT,
  TEXT, TEXT
) SET search_path = pg_catalog, public, extensions;

COMMIT;
