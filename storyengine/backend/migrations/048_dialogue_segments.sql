-- Dialogue-aware clips: the intelligence layer that detects whether a script
-- performs character dialogue (vs narration-only channels) and stores the
-- per-scene performance timeline.
--
-- videos.dialogue_mode: 'character_dialogue' | 'narration_only' | NULL (unanalyzed)
-- scripts.dialogue_segments: ordered JSONB array of
--   {type: 'narration'|'dialogue', speaker?: str, text: str,
--    voice_name?: str, audio_url?: str, duration?: float}
-- video_characters.voice_name: the Kie/ElevenLabs roster voice cast for this character

ALTER TABLE videos ADD COLUMN IF NOT EXISTS dialogue_mode TEXT;
ALTER TABLE scripts ADD COLUMN IF NOT EXISTS dialogue_segments JSONB;
ALTER TABLE video_characters ADD COLUMN IF NOT EXISTS voice_name TEXT;
