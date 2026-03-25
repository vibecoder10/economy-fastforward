-- Migration 008: Channel Profiles table
-- Stores per-tenant channel settings: name, niche, audience, frameworks

CREATE TABLE IF NOT EXISTS channel_profiles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE UNIQUE NOT NULL,

  channel_name TEXT DEFAULT '',
  niche TEXT DEFAULT '',
  target_audience TEXT DEFAULT '',
  frameworks JSONB DEFAULT '[]'::jsonb,

  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_channel_profiles_tenant ON channel_profiles(tenant_id);

ALTER TABLE channel_profiles ENABLE ROW LEVEL SECURITY;

-- RLS policy matching existing pattern
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'channel_profiles' AND policyname = 'Tenant isolation'
  ) THEN
    CREATE POLICY "Tenant isolation" ON channel_profiles FOR ALL TO authenticated
      USING (tenant_id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid())));
  END IF;
END $$;
