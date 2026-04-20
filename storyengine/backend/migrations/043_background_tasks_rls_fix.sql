-- Migration 043: fix broken RLS policy on background_tasks
-- Stage 2.2. Migration 032 shipped a policy comparing tenant_id to auth.uid()
-- which never matches — tenants can't see their own tasks via RLS. The app
-- works today only because the backend uses service_role and bypasses RLS
-- entirely, but RLS is defense-in-depth: if any future code path queries
-- background_tasks with an authenticated client, it'll either get empty
-- results or (worse, if tenant_id and user_id ever collide) wrong rows.
--
-- Fix: drop the broken policy and install the standard memberships-based
-- "Tenant isolation" policy that every other multi-tenant table uses.
--
-- Idempotent — safe to re-run.

DROP POLICY IF EXISTS bg_tasks_tenant_read ON background_tasks;
DROP POLICY IF EXISTS "Tenant isolation" ON background_tasks;

CREATE POLICY "Tenant isolation" ON background_tasks FOR ALL TO authenticated
  USING (tenant_id IN (
    SELECT m.tenant_id FROM memberships m
    WHERE m.user_id = (SELECT auth.uid())
  ));
