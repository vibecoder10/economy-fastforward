# POCOAPOCO-RECIPE.md - the locked production method (2026-07-04)

The complete, proven recipe for PocoAPoco episodes, from the standalone-skill
lab run of "La Lavandería" (41 shots, 3:11, ~$6.35 video + pennies of TTS).
Platform status: couple format + Option A voice lock are LIVE on prod (see
HANDOFF.md UPDATE 3, prod @ d92c4a2d). This doc is the canonical WHY and HOW
so any agent or UI surface can reproduce the method. Skill-side source of
truth: `skills/clone-video/` (engine.py, revoice.py, captions.py, PARITY.md).

## The channel

- Tenant: PocoAPoco's Workspace `44ecc95a-80f3-4261-8294-f963c03af2bd`
- Series: **Ryan y Vanessa** - a couple; Ryan attempts everyday life in
  Spanish, Vanessa (native, patient) teaches. Comedy-warm, A1-A2.
- Audience: English speakers learning Spanish. Spanish/English split ~50/50 -
  every Spanish phrase is paired with its English meaning IN THE AUDIO.

## Script format (locked by Ryan, exemplar = La Cena)

1. **Echo-guess-confirm-use loop** on every vocabulary word:
   Vanessa instructs in Spanish -> Ryan echoes the keyword + guesses the
   meaning -> Vanessa confirms with the translation -> Ryan immediately USES
   the word in Spanglish ("I'm calentando the sartén right now").
2. **5-6 words per episode**, each drilled 3+ times.
3. **Mistakes are lessons**: one small lie planted early pays off later (the
   red sock -> pink shirt); one physical disaster mid-episode (all the jabón
   -> foam) whose fix teaches a phrase (un poco).
4. **"Poco a poco" name-drop** worked into the episode naturally.
5. **Quiz recap** at the end: Vanessa holds up the actual PROPS, Ryan answers
   each word with a callback joke ("The one that foamed").
6. **Next-episode hook** with one new word + a button joke that pays off this
   episode's gag ("Good. I need a new white shirt.").
7. Cadence: short lines, one speaker turn at a time; quick exchanges become
   two-speaker takes (one clip, both lines).

## Production: Option A voice lock (grok animates AND speaks, then swap)

- Grok generates each speaking shot ACTUALLY saying the line (real mouth).
- ElevenLabs speech-to-speech (`eleven_multilingual_sts_v2`) converts the
  audio to the character's pinned voice. Phoneme timing is preserved ->
  lips stay synced by construction. Grok's flubs survive (known trade-off).
- **Pinned voices**: RYAN = `zKTOd8cxZlIf5EKC5Giv` (Adam),
  VANESSA = `pmruOMcxgUotq2bYO5Ne` (Pamela). Direct ElevenLabs key required
  (kie gateway hosts NO speech-to-speech): platform = PocoAPoco vault;
  skill = ELEVENLABS_API_KEY in ~/economy-fastforward/.env.
- **NEVER mix original audio under the converted voice** - the original
  contains grok's voice saying the same words; any bed reads as an echo.
- **Two-speaker clips MUST split at the turn boundary before converting**,
  anchoring on difflib-MATCHED words against the script (whisper tokenizes
  "Supermercado" as two words - raw word counts land the boundary early and
  the line tail comes out in the wrong voice). Pause-detection fallback.
  Skill: revoice.py `_split_two_speaker`. PLATFORM GAP: clip_dialogue.
  swap_voice converts whole-clip with one voice - port the split before
  running merged-turn masters through it.
- Background handling: skill locked keep_bg=true (full mix converted, scene
  SFX survive - grok_native stitch has no other bed). Platform uses
  remove_background_noise=true (dry voice) - CORRECT there because the
  performance-track assembler lays its own narration/ambience. Intentional
  divergence, do not "fix".
- ffmpeg gotcha: grok clips carry an mjpeg attached-pic as a second video
  stream - always map `0:v:0`/`1:a:0`, never bare `0:v` (with -shortest it
  collapses the output to a one-frame jpeg).

## Timing rules

- Dialogue clip generation sized to words/2.7 wps + 0.3s buffer + 0.5s lead.
- **Trim = whisper-MEASURED end of speech + 1.0s tail** (SPEECH_TAIL). Never
  trim on the estimate alone - lines get cut off. Measurements cached.
- One action per clip; quick exchanges = two-speaker takes via the
  "says X. Then says Y" chaining.

## Captions (locked style: karaoke_box)

- Full line runs across the bottom: BLACK words on a WHITE rounded bar; the
  word being SPOKEN gets a YELLOW (#FCDB00) rounded highlight - vocabulary
  lights up exactly as it is said. One PNG per word state, ffmpeg overlay
  (local ffmpeg lacks libass; Pillow renders exact style anyway).
- **Words come from the SCRIPT, timing from whisper** (captions.py align
  with script.txt). Whisper alone GARBLES Spanish ("De maciado jabón") -
  never ship whisper's words on a language channel.

## Packaging

- Title pattern: drama tease + withheld payoff + emoji pair + level tag +
  series tag. Example: `He Did the Laundry in Spanish... Then His Shirt
  Turned PINK! 😱🧺 | Learn Spanish (A1–A2) | Ryan y Vanessa`
- Description: hook line -> "WHAT YOU'LL LEARN" word list with translations
  -> CHAPTERS with real timestamps (from caption alignment) -> comment-bait
  quiz question -> subscribe line -> next-episode tease -> hashtags.
- Thumbnail: models the episode's disaster + both characters + stacked
  white/yellow navy-outlined title text (see La Lavandería thumbnail).
- Every delivered cut ships as a NEW versioned file
  (`<Project>_v2-<what-changed>.mp4`) - players cache by filename.

## Costs (grok route)

~$0.15/shot all-in (keyframe + clip at 6s tier), cast sheet + storyboard
sheets + thumbnail ~$0.05 each, STS pennies. La Lavandería: 41 shots ≈ $6.35.

## Receipts

- Finished episode: Desktop/content-engineSkill/pocoapoco-la-lavanderia/
  LaLavanderia_v3-voicefix.mp4 (+ Drive: clone-video/pocoapoco-la-lavanderia)
- EP2 "El Desayuno" staged at the gate on prod (HANDOFF.md) - do not spend
  without Ryan's go. La Cena spec staged at
  Desktop/content-engineSkill/pocoapoco-la-cena/.
