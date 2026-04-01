-- Migration 015: Create title_insights table + add learnings_extracted_at to videos
-- The title_insights table was defined in schema.sql but never had a migration.
-- The learnings_extracted_at column tracks which videos have been analyzed,
-- preventing redundant re-processing in the learning extraction loop.

-- Title Insights table (competitor title pattern analysis)
CREATE TABLE IF NOT EXISTS title_insights (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,
  airtable_record_id TEXT UNIQUE,

  name TEXT,
  pattern_name TEXT,
  description TEXT,
  example_titles TEXT,
  analysis_date DATE,
  pattern_type TEXT,
  avg_vph NUMERIC,
  count INTEGER,
  confidence NUMERIC,
  videos_analyzed INTEGER,
  vph_threshold NUMERIC,

  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_title_insights_tenant ON title_insights(tenant_id);
CREATE INDEX IF NOT EXISTS idx_title_insights_pattern ON title_insights(tenant_id, pattern_type, confidence);

ALTER TABLE title_insights ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS title_insights_tenant_isolation ON title_insights;
CREATE POLICY title_insights_tenant_isolation ON title_insights
  USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- Add learnings_extracted_at column to videos table
ALTER TABLE videos ADD COLUMN IF NOT EXISTS learnings_extracted_at TIMESTAMPTZ;
