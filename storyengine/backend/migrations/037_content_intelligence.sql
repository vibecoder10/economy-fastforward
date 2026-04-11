-- Migration 037: Content intelligence table for distilled data + vector embeddings
--
-- Architecture: Raw data (transcripts, research, scripts) gets distilled into:
--   1. A structured JSON summary (queryable metadata — hook types, topics, etc.)
--   2. A vector embedding (semantic similarity search)
-- Raw data is then archivable to cheap storage while intelligence stays hot.

CREATE TABLE IF NOT EXISTS content_intelligence (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,

  -- Source reference (what was distilled)
  source_type TEXT NOT NULL,  -- 'competitor_transcript', 'video_script', 'research_payload', 'agent_trail'
  source_id UUID NOT NULL,    -- FK to the source table row
  source_table TEXT NOT NULL,  -- 'competitor_videos', 'videos', etc.

  -- Distilled intelligence
  summary TEXT NOT NULL,                    -- LLM-generated summary (concise)
  structured_metadata JSONB NOT NULL,       -- Extracted intelligence (hook, structure, topics, etc.)

  -- Vector embedding (OpenAI text-embedding-3-small = 1536 dimensions)
  embedding vector(1536),

  -- Provenance
  model_used TEXT,           -- e.g. 'claude-haiku-4-5-20251001'
  embedding_model TEXT,      -- e.g. 'text-embedding-3-small'
  raw_char_count INTEGER,    -- Size of original content before distillation

  created_at TIMESTAMPTZ DEFAULT now()
);

-- Lookup by source
CREATE INDEX idx_ci_tenant_source_type ON content_intelligence(tenant_id, source_type);
CREATE INDEX idx_ci_source_id ON content_intelligence(source_id);
CREATE UNIQUE INDEX idx_ci_unique_source ON content_intelligence(tenant_id, source_type, source_id);

-- Structured metadata queries (e.g. WHERE structured_metadata->>'hook_type' = 'mystery_question')
CREATE INDEX idx_ci_metadata ON content_intelligence USING gin (structured_metadata);

-- Vector similarity search (HNSW — better for small-to-medium datasets, no training needed)
CREATE INDEX idx_ci_embedding ON content_intelligence USING hnsw (embedding vector_cosine_ops);

-- Track which competitor_videos have been distilled (avoids re-processing)
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS distilled_at TIMESTAMPTZ;
CREATE INDEX idx_cv_not_distilled ON competitor_videos(tenant_id)
  WHERE distilled_at IS NULL AND transcript IS NOT NULL AND transcript != '';
