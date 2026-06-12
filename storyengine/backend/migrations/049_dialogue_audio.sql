-- Per-video dialogue audio mode (Ryan, 2026-06-12): the ElevenLabs
-- voice-over overlay is OPTIONAL. 'grok_native' lets Grok voice the lines
-- itself (no voice lock across clips, but no overlay artifacts either) —
-- chosen for the bird video after the overlay "fucked it up".
--   'voice_over' (default when NULL) — character ElevenLabs lines overlaid
--   'grok_native'                    — Grok's own audio kept, line fed
--                                      verbatim into the speaking prompt
ALTER TABLE videos ADD COLUMN IF NOT EXISTS dialogue_audio TEXT;
