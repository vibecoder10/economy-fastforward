-- Add per-video system prompt override columns
ALTER TABLE videos ADD COLUMN IF NOT EXISTS script_system_prompt TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS thumbnail_system_prompt TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS sound_system_prompt TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS video_motion_system_prompt TEXT;

-- Tenant-level prompt defaults (profile-level overrides)
CREATE TABLE IF NOT EXISTS tenant_prompt_defaults (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  prompt_key TEXT NOT NULL,
  prompt_text TEXT NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(tenant_id, prompt_key)
);
CREATE INDEX IF NOT EXISTS idx_tenant_prompt_defaults_tenant ON tenant_prompt_defaults(tenant_id);
