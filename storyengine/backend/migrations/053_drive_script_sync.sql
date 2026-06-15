-- 053: per-video cache + sync state for the Script <-> Google Drive mirror.
--
-- The creator can edit a video's script as an editable Google Doc in their own
-- Drive and mirror those edits back to Postgres (which stays the operational
-- source of truth — the pipeline only ever queries scripts.scene_text /
-- videos.script). These three columns are the bookkeeping for that mirror:
--
--   drive_script_doc_id           the app-created Google Doc that holds the script
--   drive_script_synced_at        when we last pushed/pulled (our clock)
--   drive_script_doc_modified_at  the Doc's Drive modifiedTime as of that sync —
--                                 compared against a fresh modifiedTime on load to
--                                 detect "Drive has newer edits" without a full pull.
--
-- All nullable: a video with no Doc yet simply has them NULL (no Drive activity).
ALTER TABLE videos ADD COLUMN IF NOT EXISTS drive_script_doc_id TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS drive_script_synced_at TIMESTAMPTZ;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS drive_script_doc_modified_at TIMESTAMPTZ;
