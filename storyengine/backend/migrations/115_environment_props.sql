-- 115: canonical prop manifest per approved environment — kills the
-- cross-scene prop drift a fresh LLM call re-paraphrasing the location's
-- prose every scene proved to cause (stove/fridge swapped within one setup,
-- whole kitchen swapped by shot 125 despite env refs + anchors, 2026-07-2x).
--
-- props is a structured list of 6-8 {name, position} objects — e.g.
--   [{"name": "red kettle", "position": "on the rear left burner"}, ...]
-- authored ONCE at env-approval time (routes/environments.py's
-- approve_environments, a one-time vision-extraction pass over the
-- approved reference image) and from then on injected VERBATIM, code-
-- rendered (storyboard.bot.render_prop_manifest), into every scene's
-- planning prompt (_format_story_bible_for_beat), every real draw prompt
-- (storyboard.coverage.run_coverage's PICTURES path), and every repair/
-- redraw prompt (coverage_to_app.redraw_asset_image) — never re-stated by
-- a fresh LLM call, which was the drift source.
--
-- Nullable, no default. NULL or '[]' both mean "no manifest for this
-- environment" — every downstream consumer falls back to today's
-- behavior (prose-only description, no manifest tail), byte-identical to
-- before this column existed. Extraction is fail-soft: a failure logs
-- loudly and approval still succeeds with props left NULL.
--
-- Creator-editable via PATCH /api/videos/{id}/environments/{env_id}
-- (routes/environments.py's update_environment) and the MCP edit_environment
-- verb — validated shape (list of {name, position}, max ~10 items).
--
-- Idempotent (ADD COLUMN IF NOT EXISTS).

ALTER TABLE video_environments ADD COLUMN IF NOT EXISTS props JSONB;

COMMENT ON COLUMN video_environments.props IS
  'canonical 6-8 {name, position} prop manifest, authored once at approval, injected verbatim into every scene''s planning + draw + repair prompts (C4) — NULL/empty falls back to prior prose-only behavior';
