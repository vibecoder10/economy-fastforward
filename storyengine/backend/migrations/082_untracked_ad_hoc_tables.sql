-- Backfill two tables that were created via in-process `CREATE TABLE IF NOT
-- EXISTS` calls at runtime, bypassing the tracked migrations/`_migrations`
-- lineage entirely — see docs/reports/2026-07-17-storyengine-agent-audit-
-- findings.md S6 finding #2 (checklist C01a).
--
--   - secrets                 : vault.py::_ensure_secrets_table()
--   - static_reference_cache  : static_docu.py (~L383)
--
-- Both `CREATE TABLE IF NOT EXISTS` statements below match the live shape
-- exactly (introspected 2026-07-17 via information_schema.columns), so on
-- a real deploy — where both tables already exist — this is a pure no-op.
-- It only matters for a from-scratch rebuild, where it now creates them in
-- the correct migration order instead of relying on the in-process guard
-- alone.
--
-- Decision: the in-process `CREATE TABLE IF NOT EXISTS` calls in vault.py
-- and static_docu.py are NOT being removed. They still run first on a fresh
-- setup (whichever code path touches the table first), so removing them
-- would leave a window where the table doesn't exist yet if this migration
-- hasn't run before that code path fires. Both guards coexisting is
-- deliberate belt-and-suspenders, not duplication to clean up.
--
-- RLS is handled separately in migrations/083_enable_rls_ad_hoc_tables.sql.

CREATE TABLE IF NOT EXISTS secrets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT UNIQUE NOT NULL,
  value TEXT NOT NULL,
  description TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS static_reference_cache (
  tenant_id UUID NOT NULL,
  machine_key TEXT NOT NULL,
  machine TEXT,
  hosted_url TEXT NOT NULL,
  source_url TEXT,
  verified_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (tenant_id, machine_key)
);
