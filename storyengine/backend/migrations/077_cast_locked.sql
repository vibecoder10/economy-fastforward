-- 077: locked channel cast ("these character sheets ARE our identity").
-- When cast_locked is true, every new video auto-imports the project's saved
-- character_references, auto-approves them (characters_approved_at), builds the
-- cast sheet, and SKIPS character generation entirely — the creator's own
-- designed sheets are brand assets, not drafts to redesign. Also what lets a
-- queued/autopilot video run through the cast gate without parking.
ALTER TABLE projects ADD COLUMN IF NOT EXISTS cast_locked BOOLEAN NOT NULL DEFAULT false;
