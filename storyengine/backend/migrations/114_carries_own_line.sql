-- 114: STS voice-lock marker for speaking clips (voice_over dialogue videos).
--
-- A speaking clip whose audio already contains its spoken line in the pinned
-- cast voice at the clip's own timing (ElevenLabs speech-to-speech over the
-- Grok take succeeded) sets carries_own_line = true. The performance
-- assembler (render_perform.py) must NOT overlay the TTS line mp3 for spans
-- such a shot claims — it places the clip's own audio on the scene track and
-- sizes the shot's window from the measured speech bounds below.
--
-- clip_speech_start/end are seconds into the CLIP where the spoken line
-- starts and ends (measured via silencedetect at swap time). They replace the
-- assembler's DIALOGUE_HEAD_SECONDS assumption, which only ever held for
-- audio-driven talking clips (InfiniteTalk — removed, 0 prod successes).

ALTER TABLE assets ADD COLUMN IF NOT EXISTS carries_own_line BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS clip_speech_start REAL;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS clip_speech_end REAL;

COMMENT ON COLUMN assets.carries_own_line IS
  'clip audio already carries this shot''s line in the pinned cast voice (STS voice-lock) — assembler must not overlay the TTS mp3';
COMMENT ON COLUMN assets.clip_speech_start IS
  'seconds into the clip where the spoken line starts (measured at STS time)';
COMMENT ON COLUMN assets.clip_speech_end IS
  'seconds into the clip where the spoken line ends (measured at STS time)';
