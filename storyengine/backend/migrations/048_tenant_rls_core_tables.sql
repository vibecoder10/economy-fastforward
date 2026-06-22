-- Enable tenant isolation policies for legacy tenant-owned tables.
-- The backend still enforces tenant_id in route queries; this hardens direct
-- authenticated database access for tables created before RLS was standardized.

DO $$
DECLARE
  tenant_table text;
  tenant_tables text[] := ARRAY[
    'assets',
    'bot_activity',
    'competitor_channels',
    'content_intelligence',
    'discovery_ideas',
    'intelligence_reports',
    'notification_preferences',
    'scripts',
    'stage_transitions',
    'tenant_prompt_defaults',
    'tenant_usage',
    'videos'
  ];
  tenant_check text := $policy$
    tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
    OR tenant_id IN (
      SELECT m.tenant_id
      FROM public.memberships m
      WHERE m.user_id = (SELECT auth.uid())
    )
  $policy$;
BEGIN
  FOREACH tenant_table IN ARRAY tenant_tables LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', tenant_table);
    EXECUTE format('DROP POLICY IF EXISTS tenant_id_isolation ON public.%I', tenant_table);
    EXECUTE format(
      'CREATE POLICY tenant_id_isolation ON public.%I FOR ALL TO authenticated USING (%s) WITH CHECK (%s)',
      tenant_table,
      tenant_check,
      tenant_check
    );
  END LOOP;
END $$;
