-- Reconstruction of a migration that ran against prod on 2026-06-12 23:04:19
-- but was never committed to git — see docs/reports/2026-07-17-storyengine-
-- agent-audit-findings.md S6 finding #1. `_migrations` (the app's own
-- tracking table) has a row with filename EXACTLY "050_enable_rls_auth_tables.sql"
-- (applied_at 2026-06-12 23:04:19.579801+00, confirmed via a live query on
-- 2026-07-17). storyengine/backend/main.py::_run_pending_migrations() skips
-- any migrations/*.sql file whose filename already exists in `_migrations`,
-- so committing this file under its EXACT original name makes it a permanent
-- no-op on the running deploy: it restores git reproducibility without ever
-- re-executing against prod. (The parent checklist entry — C01a in
-- tasks/storyengine-wiring-fix-checklist.md — suggested a fresh number to
-- avoid reusing "050"; this uses the confirmed-already-applied exact
-- filename instead, which is the more precise reconstruction and carries
-- zero re-execution risk given the filename-match skip logic above.)
--
-- Reconstructed by introspecting live state on 2026-07-17
-- (pg_policies, pg_class.relrowsecurity) for what "enable RLS on auth
-- tables" produced:
--   - accounts: RLS enabled + "Own account only" policy (self-access only)
--   - users, tenants, password_reset_tokens: RLS enabled, ZERO policies
--     (deny-all to anon/authenticated/PostgREST; the backend connects as
--     the table-owning `postgres` role, which has BYPASSRLS, so app access
--     is unaffected — see migrations/083_enable_rls_ad_hoc_tables.sql for
--     the same proof applied to the ad-hoc tables)
--
-- Every statement below is guarded so this is ALSO a safe no-op in the
-- (currently unreached) case where it ever did run for real: ENABLE ROW
-- LEVEL SECURITY is idempotent, and the policy is dropped before recreated.

ALTER TABLE accounts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Own account only" ON accounts;
CREATE POLICY "Own account only" ON accounts FOR ALL TO authenticated
  USING (id = (SELECT auth.uid()));

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE password_reset_tokens ENABLE ROW LEVEL SECURITY;
