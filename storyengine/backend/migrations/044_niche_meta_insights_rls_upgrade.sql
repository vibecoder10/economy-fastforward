-- Migration 044: upgrade niche_meta_insights RLS to the combined pattern
-- Stage 2.2 follow-up to Cycle 39. Migration 040 shipped a GUC-only policy:
--   USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
-- Every other tenant-scoped table (autopilot_config, competitor_videos,
-- learnings, discovery_ideas, title_insights, tenant_usage, etc.) uses the
-- combined (memberships OR GUC) pattern. GUC-only means any authenticated
-- client session (where app.tenant_id isn't set) sees nothing — fine today
-- because the backend uses service_role, but defense-in-depth is the point.
--
-- Fix: drop the old policy, recreate with the combined pattern + explicit
-- FOR ALL TO authenticated target role.
--
-- Idempotent.

DROP POLICY IF EXISTS niche_meta_insights_tenant_isolation ON niche_meta_insights;

CREATE POLICY niche_meta_insights_tenant_isolation ON niche_meta_insights
  FOR ALL TO authenticated
  USING (
    tenant_id IN (
      SELECT m.tenant_id FROM memberships m
      WHERE m.user_id = (SELECT auth.uid())
    )
    OR tenant_id = current_setting('app.tenant_id', true)::uuid
  );
