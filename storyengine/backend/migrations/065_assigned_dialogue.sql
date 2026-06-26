-- 065: coverage assigns each spoken line as it plans the shot.
--
-- A clip lip-syncs ONE character, so dialogue placement must be exact. The
-- coverage planner now emits the verbatim line per speaking moment (one speaker
-- per shot, in script order) and we store it here on that moment's master frame.
-- The motion-writer then only writes CAMERA MOTION and we append this line
-- deterministically — no separate LLM re-mapping step that dropped/duplicated/
-- reordered lines. NULL for silent shots (establishing / insert / cutaway).
ALTER TABLE assets
  ADD COLUMN IF NOT EXISTS assigned_dialogue TEXT;
