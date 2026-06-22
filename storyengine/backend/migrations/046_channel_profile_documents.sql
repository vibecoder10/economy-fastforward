-- Transparent channel profile documents and transcript coverage.

ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS profile_drive_folder_id TEXT;
ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS profile_drive_folder_link TEXT;
ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS channel_dna_updated_at TIMESTAMPTZ;

ALTER TABLE channel_videos ADD COLUMN IF NOT EXISTS transcript TEXT;
ALTER TABLE channel_videos ADD COLUMN IF NOT EXISTS transcript_source TEXT;
ALTER TABLE channel_videos ADD COLUMN IF NOT EXISTS transcript_fetched_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS channel_profile_documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  doc_type TEXT NOT NULL,
  title TEXT NOT NULL,
  drive_file_id TEXT NOT NULL,
  drive_url TEXT NOT NULL,
  drive_folder_id TEXT,
  source_counts JSONB DEFAULT '{}'::jsonb,
  metadata JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (tenant_id, doc_type)
);

CREATE INDEX IF NOT EXISTS idx_channel_profile_documents_tenant
  ON channel_profile_documents(tenant_id);

ALTER TABLE channel_profile_documents ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE tablename = 'channel_profile_documents'
      AND policyname = 'channel_profile_documents_tenant_isolation'
  ) THEN
    CREATE POLICY channel_profile_documents_tenant_isolation ON channel_profile_documents
      FOR ALL USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
  END IF;
END $$;
