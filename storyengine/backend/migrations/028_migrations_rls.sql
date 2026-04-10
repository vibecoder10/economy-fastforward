-- Enable RLS on _migrations table (Supabase lint 0013_rls_disabled_in_public)
-- This table is server-only (used by migration runner with service_role).
-- No client (anon/authenticated) should ever access it.

ALTER TABLE public._migrations ENABLE ROW LEVEL SECURITY;

-- Revoke all access from client-facing roles (defense-in-depth)
REVOKE ALL ON public._migrations FROM anon;
REVOKE ALL ON public._migrations FROM authenticated;
