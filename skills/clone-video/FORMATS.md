# FORMATS.md - the video-type map and how to build each one

Every source video is three choices stacked: VISUALS (what the eyes see),
AUDIO SPINE (what carries the sound), STRUCTURE (how it is organized). Detect
all three in Phase 1, then build from this map. When a video mixes types
(most do), mix the recipes shot by shot - the engine already supports per-shot
routing ("kenburns", "dialogue", "cutaway").

## Detection: three questions about the source

1. **Visuals** - compare the 6 frames: no motion blur + repeating compositions
   = stills. Rendered characters mid-action = animation. Real places/people =
   footage. UI/code/slides = screen capture.
2. **Audio spine** - read the transcript shape: one voice wall-to-wall =
   narrator. Multiple speakers in exchanges = character dialogue. First-person
   rambling with ums = on-camera talker. Sparse/no words = music or ambience.
3. **Structure** - hook then story arc? numbered items? argument with
   evidence? repeated segment template? under 60s loop?

## The type map

| # | Type (what you'll see) | Fit | Recipe | ~Cost/shot |
|---|---|---|---|---|
| 1 | **Story narration / slideshow** - Reddit stories, history, sleep stories, AI story channels. Stills, slow moves, one narrator. | STRONG | `format: "kenburns"`. GPT Image 2 stills in the true style, ffmpeg moves (free), elevenlabs-tts narrator, cuts from the 2.5wps/7s-target rule. Cheapest and most reliable clone. | $0.05 |
| 2 | **Animated story / series** - Pixar-look kids content, animated shorts, character-driven episodes. | STRONG | Full coverage pipeline. Cast sheet is everything; beats of 2-4 angles per moment; grok dialogue lip-synced, auto-sized (2.7wps). GPT Image 2 refuses KID character sheets - nano-banana fallback. | $0.14 |
| 3 | **True crime / documentary** - CSI look, mysteries, moody narration over evidence and places. | STRONG | Hybrid: realistic kenburns stills (locations, documents, objects) + 2-4 grok motion clips where movement sells it. ElevenLabs narrator; silent b-roll auto-ducked to 0.06. Style stays TRUE realistic. | mix |
| 4 | **Explainer / video essay** - Kurzgesagt-style flat design, diagrams, icons + VO. | GOOD | Hybrid kenburns-heavy. style.json must capture the DESIGN SYSTEM (shapes, palette, stroke style), not just "animated". Keep on-screen text MINIMAL - generated text garbles; big labels can be added in post (ffmpeg drawtext) if needed. | $0.05-0.14 |
| 5 | **Listicle / top-N** - "10 places...", countdowns. Segment-per-item, b-roll + narrator. | STRONG | Hybrid like #3, but the STRUCTURE is the clone: repeated per-item template (intro shot, detail shot, payoff line), countdown as micro-payoffs. Easy to model, scales with N. | mix |
| 6 | **Talking head / commentary** - one person to camera the whole video. | WEAK | Say so honestly. Grok cannot hold one consistent on-camera voice across clips. Offer: (a) narrated-b-roll remake carrying the same script mechanics, or (b) a recurring animated host character with SHORT grok-spoken bursts. Never promise a human-clone talker. | - |
| 7 | **Tutorial / how-to (hands & things)** - cooking, crafts, repairs. POV hands, inserts. | GOOD | Coverage pipeline; insert shots (a hand, a tool, a pour) are grok's sweet spot. One action per clip, tight cuts. Narrator or grok dialogue. | $0.14 |
| 8 | **Tutorial (screen capture)** - software, coding, slides. | NO | Cannot generate believable UI screen recordings. Offer to model the STRUCTURE only (hook, pacing, chapters) as a brief for a real recording, or decline. | - |
| 9 | **Shorts / vertical viral** - 9:16, under 60s, hook-loop. | STRONG | Any recipe above compressed: `aspect_ratio: "9:16"`, hook lands inside 2s, cuts 1.4-2.5s, last shot loops back to the first. Usually 6-10 shots total. | route's cost |
| 10 | **Ambient / lofi / music-led** - mood visuals under a music track. | PARTIAL | Visuals easy (kenburns loops or grok mood clips). We do NOT generate music - Ryan supplies a track (set narration_audio to it) or we ship visuals-only. Say this at quote time. | $0.05 |
| 11 | **Footage-dependent** - news, sports recaps, drama channels built on real clips of real people/events. | NO (as-is) | The value IS the real footage; we cannot and should not fake it. Offer the format-clone: same structure/hook/cadence over generated or owned visuals. Real named people = extra care, avoid depicting them. | - |
| 12 | **Cinematic short film** - dialogue-driven drama, the "cinematic storytelling" case. | STRONG | The flagship recipe: several SHORT cutscenes exploiting grok's one-direction strength (a smile, a cast of a line, a door opening), coverage within beats, auto-sized dialogue takes that end when the line ends. | $0.14 |

## Cross-cutting rules (apply to every type)

- **One action per clip.** Grok animates one direction well. Two actions = two shots.
- **The structure is always clonable** even when the visuals are not (#8, #11):
  hook mechanism, payoff spacing, cadence, and title pattern transfer to any
  visual route. That is the fallback offer for every weak/no fit.
- **Mixed sources are normal.** A true-crime video with one animated reenactment
  scene = type 3 shots + a type 2 beat. Route per shot, not per video.
- **Say the route at quote time.** The quote names the detected type, the
  recipe, and the honest fit rating - weak fits get the alternative offered
  BEFORE money is discussed.
- **When detection is uncertain**, scrub more frames from source/video.mp4
  (free) before guessing. A wrong format route wastes the whole build.
