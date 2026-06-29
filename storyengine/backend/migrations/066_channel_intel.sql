-- Phase 2 (director chat intelligence): a cached "channel intelligence" brief
-- mined from competitor_videos — top winning titles, the recurring title/hook
-- pattern, thumbnail motifs, and upload cadence. Computed lazily on chat open
-- and refreshed when stale, then fed into every producer turn so the chat's
-- script/style/hook/thumbnail suggestions are genuinely modeled on real data.
-- Kept separate from creator_brief (which holds the conversation's own facts).
ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS channel_intel JSONB DEFAULT '{}'::jsonb;
