-- Migration 009: Account → Project → Video hierarchy
-- Replaces channel_profiles with a richer projects table
-- Adds accounts table for user identity

-- =============================================
-- ACCOUNTS (the human who logs in)
-- =============================================

CREATE TABLE IF NOT EXISTS accounts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT,
  display_name TEXT,
  plan TEXT DEFAULT 'free',
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_accounts_email ON accounts(email);

ALTER TABLE accounts ENABLE ROW LEVEL SECURITY;

-- RLS: users can only access their own account
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'accounts' AND policyname = 'Own account only'
  ) THEN
    CREATE POLICY "Own account only" ON accounts FOR ALL TO authenticated
      USING (id = (SELECT auth.uid()));
  END IF;
END $$;

-- =============================================
-- PROJECTS (a channel — e.g., "Power Doctrine")
-- =============================================

CREATE TABLE IF NOT EXISTS projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id UUID REFERENCES accounts(id) ON DELETE CASCADE NOT NULL,
  tenant_id UUID REFERENCES tenants(id),  -- backward compat with existing tables

  -- Channel identity
  name TEXT NOT NULL DEFAULT '',
  niche TEXT,
  target_audience TEXT,

  -- Visual system
  visual_style TEXT DEFAULT 'cinematic_illustration',
  visual_profile_json JSONB,
  accent_color TEXT DEFAULT '#00D4AA',
  custom_accent_color TEXT,

  -- Frameworks
  frameworks JSONB DEFAULT '[]'::jsonb,

  -- Character consistency
  character_references JSONB DEFAULT '[]'::jsonb,

  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_projects_account ON projects(account_id);
CREATE INDEX IF NOT EXISTS idx_projects_tenant ON projects(tenant_id);

ALTER TABLE projects ENABLE ROW LEVEL SECURITY;

-- RLS: users can access projects where account_id matches their auth.uid()
-- Also allow access via tenant membership (backward compat)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'projects' AND policyname = 'Owner or tenant member'
  ) THEN
    CREATE POLICY "Owner or tenant member" ON projects FOR ALL TO authenticated
      USING (
        account_id = (SELECT auth.uid())
        OR tenant_id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid()))
      );
  END IF;
END $$;

-- =============================================
-- ADD project_id TO VIDEOS (nullable, backward compat)
-- =============================================

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'videos' AND column_name = 'project_id'
  ) THEN
    ALTER TABLE videos ADD COLUMN project_id UUID REFERENCES projects(id);
    CREATE INDEX idx_videos_project ON videos(project_id);
  END IF;
END $$;

-- =============================================
-- SEED: Default account + project from existing data
-- =============================================

-- Create default account (for dev mode)
INSERT INTO accounts (id, email, display_name, plan)
VALUES (
  '00000000-0000-0000-0000-000000000001',
  'dev@local',
  'Dev User',
  'free'
)
ON CONFLICT (id) DO NOTHING;

-- Migrate channel_profiles data into projects (if channel_profiles exists and has data)
DO $$
DECLARE
  _tenant_id UUID;
  _channel_name TEXT;
  _niche TEXT;
  _target_audience TEXT;
  _frameworks JSONB;
  _project_exists BOOLEAN;
BEGIN
  -- Check if channel_profiles table exists
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'channel_profiles') THEN
    -- Get the first channel profile
    SELECT tenant_id, channel_name, niche, target_audience, frameworks
    INTO _tenant_id, _channel_name, _niche, _target_audience, _frameworks
    FROM channel_profiles
    LIMIT 1;

    IF _tenant_id IS NOT NULL THEN
      -- Check if project already exists for this account+tenant
      SELECT EXISTS(
        SELECT 1 FROM projects
        WHERE account_id = '00000000-0000-0000-0000-000000000001'
        AND tenant_id = _tenant_id
      ) INTO _project_exists;

      IF NOT _project_exists THEN
        INSERT INTO projects (account_id, tenant_id, name, niche, target_audience, frameworks)
        VALUES (
          '00000000-0000-0000-0000-000000000001',
          _tenant_id,
          COALESCE(NULLIF(_channel_name, ''), 'My Channel'),
          _niche,
          _target_audience,
          COALESCE(_frameworks, '[]'::jsonb)
        );
      END IF;
    END IF;
  END IF;

  -- If no project was created from migration, create a default one
  IF NOT EXISTS (SELECT 1 FROM projects WHERE account_id = '00000000-0000-0000-0000-000000000001') THEN
    SELECT id INTO _tenant_id FROM tenants LIMIT 1;
    INSERT INTO projects (account_id, tenant_id, name)
    VALUES (
      '00000000-0000-0000-0000-000000000001',
      _tenant_id,
      'My Channel'
    );
  END IF;
END $$;
