-- 075: creator-supplied scripts ("use this script for a video").
-- 'user_supplied' means videos.script holds the creator's own words verbatim:
-- run_script skips generation entirely (guard in pipeline_executor.run_script),
-- and no retention grading / factual gate second-guesses their script.
ALTER TABLE videos ADD COLUMN IF NOT EXISTS script_source TEXT NOT NULL DEFAULT 'generated';
