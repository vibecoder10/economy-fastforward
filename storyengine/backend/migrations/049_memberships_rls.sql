-- Protect tenant membership rows from direct authenticated access.
-- Backend account creation and membership management run through the database
-- owner connection, which bypasses RLS. Browser-authenticated clients should
-- only be able to read their own membership rows.

ALTER TABLE public.memberships ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS memberships_self_read ON public.memberships;

CREATE POLICY memberships_self_read ON public.memberships
  FOR SELECT TO authenticated
  USING (user_id = (SELECT auth.uid()));
