-- Structured creator identity extracted from a channel's OWN top videos (via
-- Firecrawl transcripts + LLM distillation — see identity_builder.py). The prose
-- voice guidance still lives in channel_profiles.style_description (what the
-- producer already reads); this JSONB holds the full structured profile
-- (voice/cadence/hook/research/structure/format/signature phrases + provenance)
-- so it's queryable and re-buildable. Source of truth = the videos, not operator input.
ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS channel_identity JSONB DEFAULT '{}'::jsonb;
