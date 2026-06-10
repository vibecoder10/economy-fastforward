-- Migration 047: mandatory storyboard gate (Creator Control Run, phase 3)
-- Spec: docs/superpowers/specs/2026-06-10-creator-control-run.md
--
-- Boards are now the only path to image spend: grids generate first ($0.075
-- each), the creator reviews/redoes them, then explicitly locks the story.
-- videos.story_locked_at is the gate the images + extraction stages check.
-- storyboard_on_off defaults On so every new video boards first.
--
-- Idempotent.

ALTER TABLE videos ADD COLUMN IF NOT EXISTS story_locked_at TIMESTAMPTZ;

ALTER TABLE scripts ALTER COLUMN storyboard_on_off SET DEFAULT 'On';
UPDATE scripts SET storyboard_on_off = 'On' WHERE storyboard_on_off IS NULL;
