# PARITY.md - skill vs StoryEngine platform

The goal: this skill is StoryEngine-as-a-standalone, so features get built and
dialed in here fast, then ported to the platform (or vice versa). This file maps
every duplicated rule to its source of truth on both sides. **When you change a
rule on either side, update the other side and this table in the same turn.**
Later this skill can become an API endpoint or MCP server; this map is the spec.

Platform root: `~/economy-fastforward/storyengine/backend/`
Skill root: `~/economy-fastforward/skills/clone-video/` - **one main folder**:
the standalone skills live INSIDE the StoryEngine repo (siblings of
`skills/video-pipeline/`), so every capability added here is versioned with
the platform and ports in the same repo. `~/.claude/skills/clone-video` and
`~/.claude/skills/content-engine` are symlinks into here (that is how Claude
discovers them - do not replace them with real folders).

## Where the platform's video skills live (architecture map)

StoryEngine is literally built as skill pipelines - two layers:

**Layer 1: `~/economy-fastforward/skills/video-pipeline/` - the original skill
registry** (the Power Doctrine bot system StoryEngine grew out of). 15 skills,
each a folder with a `manifest.json` (skill_id, type, entry_point, cost
estimate, required/output status forming a status-chain pipeline).
`shared/skill_registry.py` discovers them for the Claude orchestrator.
- pipeline_stage skills: research, script, voice (ElevenLabs), image_prompts,
  images, storyboard (3x3 grids), video_motion, sound, render (Whisper align +
  KEN BURNS + transitions via Remotion), thumbnail, title_idea (3 ranked
  title/concept variations), upload (SEO + YouTube)
- data_gathering skills: discovery (news + competitor scan), competitor_scraper
- quality_agent: agents/ (hook, body, CTA agents with blocking quality gates)

**Layer 2: `storyengine/backend/` - the live multi-tenant app**, which mounts
Layer 1 onto sys.path (pipeline_executor.py:23) and wraps it with:
- `pipeline_executor.py` - the per-video stage runner
- `actions.py` - the shared verb registry (chat + buttons call the same verbs)
- `agent_brain.py` - the chat tool loop driving those verbs
- capability modules: clip_dialogue.py (speaking clips), asset_intake.py,
  originality.py, extraction.py, dialogue_intelligence.py, thumbnail modeling
- **render tracks = the platform's format routing** (mirrors FORMATS.md):
  - `render_stitch.py` - grok_native FFmpeg concat (our cinematic/animated route)
  - `render_perform.py` - performance track for character_dialogue + voice_over
  - `render_static.py` + `static_docu.py` - static-image documentary, one image
    per narration segment with Ken Burns (our kenburns route; the original
    Power Doctrine format)

Skill phase -> platform skill: fetch/analysis = discovery + competitor_scraper
+ extraction + agent_brain analyze-URL; 3 ideas = title_idea; script = script
skill + user_script.py; narration = voice; storyboards = storyboard +
coverage; animate = video_motion + executor clips stage; kenburns = render
(audio_sync) + render_static; stitch = render_stitch; thumbnail = thumbnail
skill; upload = upload skill + youtube_publish.py.

## Duplicated rules

| Rule | Platform source | Skill source | Value |
|---|---|---|---|
| Grok speech rate | `clip_dialogue.py` SPEAKING_WORDS_PER_SEC | `engine.py` WORDS_PER_SEC_SPOKEN | 2.7 words/sec (measured) |
| Speech buffer | `clip_dialogue.py` SPEECH_BUFFER_SECONDS | `engine.py` SPEECH_BUFFER | 0.3s |
| Dialogue voice lead | `clip_dialogue.py` DIALOGUE_VOICE_LEAD_SECONDS | `engine.py` DIALOGUE_LEAD | 0.5s |
| Clip duration picker | `clip_dialogue.py` pick_clip_duration() | `engine.py` shot_timing() | ceil(need), clamp [floor, cap], whole seconds; silent = floor; long lines split across shots, never stretched |
| Grok duration tiers | `skills/video-pipeline/shared/channel_profile.py` GROK_IMAGINE durations/cost | `engine.py` GROK_FLOOR/GROK_CAP/GROK_TIER_CREDITS | 6/10/15s at $0.10/$0.15/$0.20; between = next tier up |
| Over-long clip danger | `clip_dialogue.py` module comment | `engine.py` comment + shot_timing | clip ENDS when speech ends or grok ad-libs garbage |
| Narration segment pacing | `skills/video-pipeline/shared/clients/deterministic_splitter.py` | `SKILL.md` "Smart shot timing" | 2.5 words/sec, target 7s, min 4s, hard cap 10s |
| Cutaway people rule | `clip_dialogue.py` CUTAWAY_PREFIX | `engine.py` CUTAWAY | absolute NO PEOPLE |
| No-new-people rule | `clip_dialogue.py` NO_NEW_PEOPLE_PREFIX | `engine.py` NO_NEW_PEOPLE | nobody who is not already visible |
| Off-screen speaker rule | `clip_dialogue.py` OFF_SCREEN_SPEAKER_RULE | `engine.py` OFF_SCREEN_SPEAKER | voice from off-screen, never summon the speaker |
| Default motion prompt | `pipeline_executor.py` ~line 2062 | `engine.py` DEFAULT_MOTION | slow push-in + fidelity lock; gentle/soft/subtle banned (screensaver motion) |
| Speaking prompt shape | `clip_dialogue.py` speaking_prompt() / native_speaking_prompt() | `engine.py` build_motion() | "speaks with clear natural mouth movement, saying exactly: ..." + starts right away + others react subtly |
| Silent b-roll duck | `pipeline_executor.py` SILENT_CLIP_GAIN env (0.06) | `engine.py` SILENT_CLIP_GAIN | 0.06 - faint room tone, invented speech inaudible; speaking shots keep full volume |
| Narration mix | `clip_dialogue.py` mux_voice (normalize=0, duration guards) | `engine.py` animate() final amix | amix normalize=0; video length wins |
| Coverage/beat grammar | platform storyboard coverage stage | `~/.claude/skills/content-engine/SKILL.md` (referenced by SKILL.md) | one moment, several angles; masters anchor angle keyframes |
| Style truth rule | style classifier (bulletproof memory) | `SKILL.md` hard rules | clone into the source's TRUE style; realistic never becomes animated |
| Thumbnail modeling | platform thumbnail blueprint pipeline (vision -> transform -> image) | `SKILL.md` Phase 1 step 2 + Phase 5 step 2 | JSON blueprint, same psychology, new subject/words |
| Analyze -> DNA -> recreate | `agent_brain.py` / actions.py analyze-any-URL flow | `SKILL.md` Phases 1-2 | source analysis to JSON, then modeled (never copied) rebuild |
| Storyboard-sheet-first | platform storyboard skill (3x3 grid manifests: run -> run_images -> run_extract; review grids before production) | `engine.py sheet` + SKILL.md Phase 4 | ONE sheet image with numbered panels + caption strips carrying the script; analyze before any per-shot spend |
| Caption cloning | render skill audio_sync (Whisper align + Remotion karaoke captions) | `captions.py` (whisper align -> Pillow PNGs -> ffmpeg overlay) + `analysis/captions.json` | detect burned-in caption style (karaoke_word / phrase_pop / box_phrase), clone colors/font/position; skill adds STYLE DETECTION - port candidate to platform |

## Format parity status (FORMATS.md strong fits vs the platform)

Where each strong-fit clone route stands on both sides. "Ready" on the skill
side means the recipe + engine support exist; no strong fit has had a real
PAID end-to-end run yet - the first live clone per route is its proof.

| Route | Skill (standalone) | Platform (StoryEngine) | Port direction |
|---|---|---|---|
| Story narration / kenburns | READY - engine kenburns (free ffmpeg zoompan) + elevenlabs narration, proven in sim | HAS IT differently: static_docu track (render_static.py, Remotion Ken Burns, one image per segment) | Equivalent by different renderers; keep timing rules in step |
| Animated story / series | READY - coverage beats + auto-sized grok dialogue | HAS IT: grok_native + coverage + clip_dialogue.py | In parity (timing/guards duplicated 2026-07-03) |
| Cinematic short film | READY - short one-action cutscenes, takes end with the line | HAS IT: grok_native stitch + performance track (render_perform.py) | In parity |
| True crime / doc hybrid | READY - per-shot kenburns/grok mix + 0.06 duck under narrator | PARTIAL: tracks are per-VIDEO (static_docu OR grok_native), no per-shot mixing | PORT skill -> platform: per-shot hybrid |
| Listicle / top-N | READY - recipe (repeated per-item template) | NO explicit template (long-form docu covers some of it) | PORT skill -> platform once dialed in |
| Shorts 9:16 | READY - aspect_ratio 9:16 + compressed cuts + loop rule | PARTIAL: aspect chosen at creation, but no shorts-specific pacing recipe | PORT skill -> platform |
| Per-video format auto-detection | READY - Phase 1 frame/transcript classification (12 types) | PARTIAL: detection is channel-level (static_docu.py reads channel identity), not per-video | PORT skill -> platform |

| Voice lock (speech-to-speech) | `clip_dialogue.py` swap_voice (Option A, prod @ d92c4a2d) | `revoice.py` | grok speaks -> ElevenLabs STS with pinned voice -> replace audio, map 0:v:0 (thumbnail trap), no bed (echo). DIVERGENCE (intentional): platform converts DRY (assembler lays its own bed); skill converts FULL MIX (stitch has no other bed). PLATFORM GAP: no two-speaker split - port revoice._split_two_speaker (matched-word anchor + pause fallback) before merged-turn masters run through swap_voice |

## Deliberate differences (not drift)

- **Fetch**: skill uses local yt-dlp (laptop IP); platform is bot-blocked on the
  VPS and uses its own ingestion. Do not port the skill's fetch to the VPS.
- **Ken Burns route**: skill-only for now (free ffmpeg zoompan + per-shot
  auto-duration). Port candidate for the platform once dialed in.
- **Voice**: skill uses grok-native dialogue or elevenlabs narration file;
  platform has the full ElevenLabs per-line mux (mux_voice with per-line
  lead-in). Skill's per-line dialogue mux is a future port FROM the platform.
- **Storage**: skill saves to Desktop + optional Drive; platform uses
  Drive-first with the /api/media/drive proxy.
- **The idea step**: the platform HAS this as the legacy `title_idea` skill
  (3 title/concept variations from a topic or competitor video) but it is not
  surfaced in the app's chat flow. The skill's version adds the deep-analysis
  reasoning. Port direction: skill -> app chat.
