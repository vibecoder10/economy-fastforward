-- Remotion-aware Custom Film assembly identity without rewriting legacy v1.
BEGIN;

ALTER TABLE custom_film_assemblies
  DROP CONSTRAINT IF EXISTS custom_film_assemblies_manifest_version_check;
ALTER TABLE custom_film_assemblies
  ADD CONSTRAINT custom_film_assemblies_manifest_version_check
  CHECK (
    manifest_version IN (
      'custom-film-assembly-v1',
      'custom-film-assembly-v2'
    )
  );

ALTER TABLE custom_film_assemblies
  DROP CONSTRAINT IF EXISTS custom_film_assemblies_render_engine_check;
ALTER TABLE custom_film_assemblies
  ADD CONSTRAINT custom_film_assemblies_render_engine_check
  CHECK (
    (
      manifest_version = 'custom-film-assembly-v1'
      AND NOT (manifest ? 'render_engine')
    )
    OR (
      manifest_version = 'custom-film-assembly-v2'
      AND manifest->>'render_engine' IN ('ffmpeg', 'remotion')
      AND (manifest->>'plan_hash') ~ '^[0-9a-f]{64}$'
      AND (manifest->>'quote_inputs_hash') ~ '^[0-9a-f]{64}$'
      AND (manifest->>'approval_hash') ~ '^[0-9a-f]{64}$'
      AND jsonb_typeof(manifest->'max_spend') = 'number'
    )
  );

COMMIT;
