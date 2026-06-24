-- 063: cache the AI "why model this" analysis on each competitor video so the
-- home-page "Worth modeling" section stays fast (generated once, reused on load;
-- regenerated only when a video has no rationale yet).
ALTER TABLE competitor_videos
  ADD COLUMN IF NOT EXISTS model_rationale TEXT,
  ADD COLUMN IF NOT EXISTS model_rationale_at TIMESTAMPTZ;
