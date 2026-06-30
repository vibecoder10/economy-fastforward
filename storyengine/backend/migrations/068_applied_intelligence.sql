-- G3: capture what the engine APPLIED to each video's script (the hook/retention
-- feedback loop), so it can be surfaced to the creator instead of being a black box.
-- Holds: learnings used (USE/AVOID patterns), and whether the retention grader
-- regenerated the script + why (failing gates). Powers the autopilot scorecard cards
-- and the chat's "here's what I changed" transparency.
ALTER TABLE videos ADD COLUMN IF NOT EXISTS applied_intelligence JSONB DEFAULT '{}'::jsonb;
