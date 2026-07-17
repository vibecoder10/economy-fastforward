-- Close the RLS gap on the two ad-hoc tables backfilled into the migration
-- lineage by migrations/082_untracked_ad_hoc_tables.sql, plus
-- channel_video_retention (migration 080, shipped with no RLS at all) —
-- see docs/reports/2026-07-17-storyengine-agent-audit-findings.md S6
-- findings #2/#3 (checklist C01a, item D).
--
-- SAFETY PROOF (why this cannot lock the backend out of its own vault):
-- Enabling RLS on a table with NO policies denies ALL access to any role
-- subject to RLS. This is only safe if the backend's own DB connection
-- bypasses RLS. Verified live on 2026-07-17 against project
-- wrromlupsmyzrrcqlucn:
--   1. storyengine/backend/database.py reads DATABASE_URL directly into
--      asyncpg.create_pool() with no role override; storyengine/.env.example
--      shows `DATABASE_URL=postgresql://postgres:password@...` — the
--      backend connects as the `postgres` role.
--   2. `SELECT rolname, rolbypassrls FROM pg_roles WHERE rolname='postgres'`
--      -> rolbypassrls = true.
--   3. `SELECT relowner::regrole FROM pg_class WHERE relname IN
--      ('secrets','static_reference_cache','channel_video_retention')`
--      -> all three owned by `postgres` (owners also bypass RLS
--      independent of the BYPASSRLS attribute).
--   4. Operational proof already exists in prod: `secrets` (this exact
--      table) already has `relrowsecurity = true` with ZERO policies
--      today, and the app's per-tenant API-key vault works correctly —
--      i.e. this exact configuration (RLS on, no policies, backend as
--      postgres) is already running successfully for `secrets`, right now.
--
-- No policies are added here on purpose — the goal is to close the public
-- PostgREST/anon/authenticated access path, not to permit tenant-scoped
-- access through it. The backend's bypass is what keeps the app working.
--
-- ENABLE ROW LEVEL SECURITY is idempotent (safe to run when already
-- enabled, e.g. `secrets` today), so this file is a no-op on every
-- subsequent deploy.

ALTER TABLE secrets ENABLE ROW LEVEL SECURITY;
ALTER TABLE static_reference_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE channel_video_retention ENABLE ROW LEVEL SECURITY;
