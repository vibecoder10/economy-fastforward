-- 116: provenance for videos.skip_voice — who set it, so the dialogue
-- auto-detector can safely un-set what IT set without ever touching a
-- creator's own choice.
--
-- Bug this closes: tag_video_dialogue only ever flipped skip_voice
-- false->true. A video tagged character_dialogue at >=0.8 dialogue share
-- auto-skips voice; if the creator then regenerates the script into
-- something narration-heavy, re-tagging reclassifies it narration_only (or
-- back under the majority threshold) but skip_voice stayed stuck true —
-- voice never runs, the character_dialogue-gated Animate auto-chain never
-- fires, render hard-fails "Missing audio: Scene N.mp3", and the frontend
-- hides all voice controls (voiceSkipped) so there's no self-serve recovery.
--
-- skip_voice_source records WHO set the current skip_voice value:
--   'auto'   — dialogue_intelligence.tag_video_dialogue's own majority-
--              dialogue detector. Fully bidirectional with the detector's
--              own conclusion: a later pass that no longer qualifies
--              (mode != character_dialogue OR dialogue_share below the
--              majority threshold) flips skip_voice back to false, but
--              ONLY when this column reads 'auto' for that row.
--   'manual' — an explicit creator/UI action: GuidedNextStep's skip-voice
--              button, PATCH dialogue_audio='grok_native' (routes/videos.py
--              update_video's own auto-fill hook — an explicit creator
--              choice of grok_native, not the dialogue detector), and the
--              create-form's reduced stage plan (pipeline_stages without
--              'voice'). Never auto-reverted by the detector.
--   NULL     — legacy rows written before this column existed. Treated the
--              same as 'manual' (never auto-flipped) — we have no evidence
--              those were the detector's doing, so silence keeps today's
--              behavior for every pre-existing row.
--
-- Nullable, no default — NULL is a real, meaningful state here (see above),
-- not "unknown pending backfill".
--
-- Idempotent (ADD COLUMN IF NOT EXISTS).

ALTER TABLE videos ADD COLUMN IF NOT EXISTS skip_voice_source TEXT
  CHECK (skip_voice_source IN ('auto', 'manual'));

COMMENT ON COLUMN videos.skip_voice_source IS
  'who set the current skip_voice value: auto (dialogue detector, bidirectional) | manual (creator action, never auto-reverted) | NULL (legacy row, treated as manual)';
