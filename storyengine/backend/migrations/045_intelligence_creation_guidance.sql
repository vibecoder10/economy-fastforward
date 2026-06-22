-- Store concrete "how to make this video" guidance from onboarding intelligence.

ALTER TABLE intelligence_reports
  ADD COLUMN IF NOT EXISTS creation_guidance JSONB;
