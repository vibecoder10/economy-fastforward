-- Per-scene/shot video-model routing (checklist §1.2, C12: router module +
-- these columns + routing written at shot-plan time; C13 will make clip
-- generation actually READ routed_model, this migration only stores it).
--
-- routed_model:   the model shared.model_router.route_shot_model() picked
--                 for this shot, computed at shot-plan time in
--                 storyboard/coverage.py's plan_camera_moves() (BEFORE
--                 frames are drawn) and persisted by
--                 scripts/coverage_to_app.py's store_scene(). One of
--                 shared.channel_profile.MODEL_REGISTRY's WIRED model ids
--                 (e.g. 'grok-imagine', 'veo-3.1-quality'), or NULL when
--                 the shot predates this column or routing failed
--                 (fail-soft — the shot plan still succeeds either way).
-- routing_reason: a short human-readable string explaining the pick (e.g.
--                 "reveal scene -> hero tier (premium)") — surfaced later
--                 by the C14 UI as the per-scene model badge's "why"
--                 tooltip. NULL alongside routed_model when unset.
-- model_used:     WHICH model actually generated this shot's clip. Stays
--                 NULL until C13 wires clip generation to read
--                 routed_model and record the model that really ran (may
--                 differ from routed_model if a scene-level override or a
--                 fallback fired, mirroring how assets.image_model can
--                 differ from videos.image_model_override).
--
-- All three nullable, no defaults — existing rows and any write path that
-- doesn't compute routing (every INSERT INTO assets site other than
-- store_scene()) are unaffected.
--
-- Idempotent (ADD COLUMN IF NOT EXISTS) — safe to run when already applied.
-- Necessary here specifically: this migration is applied LIVE via the
-- Supabase MCP tools rather than through the app's own startup runner
-- (main.py::_run_pending_migrations), so it will NOT be recorded in the
-- app's `_migrations` tracking table — the runner will attempt to re-run
-- this exact file on the next backend restart, and IF NOT EXISTS is what
-- makes that a no-op instead of an error.

ALTER TABLE assets ADD COLUMN IF NOT EXISTS routed_model TEXT;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS routing_reason TEXT;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS model_used TEXT;
