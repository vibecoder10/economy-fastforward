-- 071: per-video render mode.
-- NULL = existing behavior (grok_native stitch / legacy Remotion narrator path).
-- 'static_docu' = static-image documentary render: one generated image per
-- narration segment, held with a slow Ken Burns pan over the voiceover, no
-- animated clips (the original Power Doctrine format; first client: Designed
-- vs Used). Set at creation when the channel's identity says the format is
-- static (channel_identity.visual_format), or manually.
ALTER TABLE videos ADD COLUMN IF NOT EXISTS render_mode TEXT;
