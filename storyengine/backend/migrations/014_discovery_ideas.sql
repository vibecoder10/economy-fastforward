-- Migration 014: Discovery Ideas table
-- Stores AI-generated video ideas from competitor analysis + news headlines
-- Used by the Daily Ideas UI on the /pipeline page

CREATE TABLE IF NOT EXISTS discovery_ideas (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,

  -- Source
  source_type TEXT NOT NULL,  -- 'competitor' or 'headline'
  competitor_video_id UUID REFERENCES competitor_videos(id),
  competitor_title TEXT,
  competitor_channel TEXT,
  competitor_url TEXT,
  competitor_vph NUMERIC,
  competitor_thumbnail_url TEXT,

  -- AI-generated content
  our_angle TEXT NOT NULL,
  hook TEXT,
  framework TEXT,
  estimated_appeal NUMERIC,
  appeal_breakdown JSONB,

  -- Title options (3 per idea)
  title_options JSONB NOT NULL DEFAULT '[]'::jsonb,
  -- Each element: { title, formula_id, thumbnail_text, score }

  -- State
  status TEXT DEFAULT 'fresh',  -- fresh, selected, dismissed, launched
  selected_title_index INTEGER,  -- which of 3 titles was picked
  launched_video_id UUID REFERENCES videos(id),

  -- Batch tracking
  batch_date DATE DEFAULT CURRENT_DATE,
  batch_id TEXT,

  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_discovery_ideas_tenant ON discovery_ideas(tenant_id);
CREATE INDEX IF NOT EXISTS idx_discovery_ideas_status ON discovery_ideas(tenant_id, status, batch_date DESC);
