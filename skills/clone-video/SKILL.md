---
name: clone-video
description: Drop a YouTube link, get a modeled clone - not a copy. Fetches the video locally, converts the thumbnail and sample frames to JSON blueprints, deep-analyzes the script (hook, payoff, micro-payoffs, cadence) and title, pitches 3 ranked new ideas modeled from the original, then builds the winner into a finished video (GPT Image 2 storyboards, grok-imagine clips, FFmpeg stitch) with a modeled thumbnail. Triggers on "clone this video", "clone-video", "/clone-video", "model this video", or a YouTube link with clone/remake/model intent.
---

# clone-video

YouTube link in, modeled video out. We never copy - we extract what makes the
source work and build something new that works the same way.

```
fetch (local, free) -> analyze to JSON incl. FORMAT (free) -> 3 ranked ideas  [Ryan picks]
-> ONE upfront cost quote  [yes]
-> script (+ narration TTS if the format uses one)  [checkpoint 1: approve]
-> storyboards (GPT Image 2)  [checkpoint 2: approve]
-> animate (grok, or free ffmpeg Ken Burns, per format) + stitch + modeled thumbnail -> done
```

`fetch.py` grabs the source. `engine.py` does the paid build in two stages
(storyboard, then animate) so checkpoint 2 happens before animation money is
spent. Same spec.json shape and coverage/beat rules as the content-engine skill -
read `~/.claude/skills/content-engine/SKILL.md` for the beat-writing craft
(beats = one moment from several angles; masters anchor the angle shots).

This skill is **StoryEngine-as-a-standalone**: the platform's proven rules are
duplicated here so features can be dialed in fast and ported both ways.
`PARITY.md` maps every shared rule to its source on both sides - when a rule
changes on either side, update the other side and PARITY.md in the same turn.

## Hard rules

- **One upfront cost quote, one yes.** After Ryan picks an idea, quote the whole
  build (cast + thumbnail + all shots) via `engine.py estimate` and WAIT. After
  the yes, no more money questions - the two remaining checkpoints are about
  quality, not cost.
- **Match the source's true style.** Classify what the frames actually are -
  live-action realistic, 3D animated, 2D cartoon, stylized - and clone into that
  same style. Never default to animated. Realistic stays realistic.
- **Never auto-open images or videos.** Report paths and stop.
- **Version-label every delivered cut.** Players and Finder cache by filename,
  so overwriting final_captioned.mp4 makes Ryan replay the OLD version. Each
  revision ships as a NEW file: <Project>_v2-<what-changed>.mp4 (v2-voicelock,
  v3-recut, ...). final.mp4 / final_captioned.mp4 stay as working files only.
- **Analysis is free and local.** yt-dlp + ffmpeg run on this Mac (the VPS is
  bot-blocked by YouTube; the laptop is not). Vision analysis is you reading the
  images - no API calls.

## Output folder

`~/Desktop/content-engineSkill/<short-slug>/` - one folder per clone, sitting
next to the content-engine projects. Inside: `source/` (fetched original),
`analysis/` (the JSON blueprints), and the build assets at the top level
(cast sheet, keyframes, clips, `final.mp4`, `thumbnail_new.png`).

## Phase 1: Fetch + analyze (free)

1. `python3 fetch.py <url> <outdir>` - downloads video (720p cap), thumbnail,
   transcript, metadata, and 6 sample frames.
2. **Thumbnail -> JSON.** Read `source/thumbnail.png` and write
   `analysis/thumbnail.json`:
   ```json
   {"subject": "who/what dominates and where", "expression_emotion": "...",
    "composition": "rule-of-thirds placement, depth, negative space",
    "text": {"content": "...", "style": "font weight, color, stroke", "position": "..."},
    "palette": ["dominant hex-ish colors"], "lighting": "...",
    "click_psychology": "why this earns the click (curiosity gap, stakes, contrast)"}
   ```
3. **Frames -> JSON.** Read ALL 6 of `source/frame_*.png` (not 2-3; you need the
   spread to judge motion) and write `analysis/style.json`:
   ```json
   {"true_style": "live-action realistic | 3D animated | 2D cartoon | stylized ...",
    "format": "one of the 12 types in FORMATS.md (kenburns_slideshow, animated_series, documentary, explainer, listicle, talking_head, tutorial_hands, tutorial_screen, shorts, music_led, footage_dependent, cinematic_film)",
    "camera": "lens feel, movement, framing habits", "lighting": "...",
    "palette": ["..."], "grain_texture": "...", "pacing_visual": "cuts, motion energy",
    "world": "settings, wardrobe, props that define the look"}
   ```
   **`format` is the production grammar and it decides the whole build - judge it
   deliberately.** Style is what the frames look like; format is how the video
   moves. Signals: frames that look like polished stills with no motion blur and
   compositions that repeat with slight scale/offset shifts = a Ken Burns
   slideshow. Consistent rendered characters mid-action = animated series.
   Real footage, real locations = live action / documentary. If unsure after the
   6 frames, scrub `source/video.mp4` for a few more (`ffmpeg -ss <sec> -i
   video.mp4 -frames:v 1 x.png` is free) or watch a short segment.
4. **Script -> JSON.** Read `source/transcript.txt` and write
   `analysis/script.json` - everything that makes the script work:
   ```json
   {"hook": {"text": "...", "mechanism": "why it grabs in the first seconds"},
    "structure": ["act/section beats with timestamps"],
    "payoff": "the promise kept and when",
    "micro_payoffs": ["small wins along the way, with rough timing"],
    "cadence": {"words_per_minute": 0, "avg_sentence_words": 0,
                "rhythm": "short-short-long? questions? repetition?"},
    "formatting": ["devices used: direct address, open loops, callbacks, lists"],
    "tone": "...", "cta": "..."}
   ```
5. **Captions -> JSON.** Look at every frame for BURNED-IN captions (ESL and
   shorts almost always have them; often only on spoken lines). Write
   `analysis/captions.json` in the capstyle shape `captions.py` consumes:
   ```json
   {"present": true, "coverage": "every_spoken_line | narration_only | none",
    "type": "karaoke_word | phrase_pop | box_phrase | static",
    "font": {"family": "closest mac font", "size_frac": 0.06, "case": "as_is", "bold": true},
    "colors": {"base": "#111111", "highlight": "#FFD700", "stroke": "#000000", "box": "#FFD52E"},
    "position": "bottom_center", "words_per_screen": 5}
   ```
   Judge the type carefully: word-by-word color fill = karaoke_word; phrase on
   a filled rounded pill = box_phrase (the ESL yellow-pill look); plain
   outlined phrase = phrase_pop. Sample exact colors from the frame pixels
   (size_frac = caption text height / frame height). If no captions, write
   `{"present": false}` and skip the caption burn in Phase 5.
6. **Title -> JSON.** Write `analysis/title.json`:
   ```json
   {"title": "...", "pattern": "the template underneath (e.g. number + outcome + tension)",
    "power_words": ["..."], "curiosity_gap": "what it withholds",
    "promise": "what it commits to deliver"}
   ```
7. **Pitch 3 ranked ideas.** New ideas MODELED from the title pattern and script
   mechanics - not copies. For each: the new title, a 1-2 line concept, and the
   reasons it should work (which proven mechanics from the analysis it inherits,
   why it is unique enough to stand on its own, why it fits what is already
   pulling views). Rank them 1-3 and say which one you would pick. WAIT for
   Ryan's pick.

## Format routing - the build changes with the source

The detected `format` picks the recipe. Say which route you are on when quoting.
The four rows below are the core routes; **`FORMATS.md` holds the full 12-type
map** (listicles, explainers, tutorials, shorts, music-led, footage-dependent,
cinematic short film) with fit ratings and per-type recipes - read it when the
source does not obviously match a row here. Route per SHOT, not per video:
mixed sources are normal.

| Source format | Build recipe | Per-shot cost |
|---|---|---|
| **Ken Burns slideshow** (stills, slow zoom/pan, narrator) | `settings.format: "kenburns"`. Shots are GPT Image 2 stills; ffmpeg does the zoom_in / zoom_out / pan_left / pan_right moves for FREE. The narrator is the backbone: generate the voiceover with the **elevenlabs-tts skill** (one consistent voice), set `settings.narration_audio` to the MP3, and time the shot `cut`s to the narration (get its length with `ffprobe`). Beats can be single shots; coverage matters less than image quality. | ~$0.05 (still only) + TTS |
| **Animated series** (Pixar/cartoon look, characters acting) | Full content-engine pipeline. Cast sheet is everything - character consistency lives or dies there. grok clips with lip-synced `dialogue` for character lines. Note: GPT Image 2 hard-refuses kid character sheets; fall back to nano-banana style prompting or adjust the cast. | ~$0.14 (grok) |
| **True crime / doc TV** (real look, moody, narrator over b-roll) | Hybrid. `true_style` stays realistic. Most shots are Ken Burns stills (evidence photos, locations, reenactment stills) via per-shot `"kenburns": "zoom_in"` etc.; sprinkle 2-4 grok clips where real motion sells it (a door opening, headlights passing). Narrator via **elevenlabs-tts** + `narration_audio`; grok clip audio gets auto-ducked to 25% under the voice. | mix: ~$0.05 stills, ~$0.14 motion |
| **Talking head / vlog** | Weakest fit for cloning a person talking to camera - grok's voice is random per clip, so a consistent on-camera narrator is not reproducible yet. Say so, and offer the hybrid route (narrated b-roll carrying the same script mechanics) instead. | - |

Per-shot `"kenburns"` works in any format; `settings.format: "kenburns"` just
makes it the default for every shot.

## Phase 2: Quote (one yes)

Propose a target length and shot count (default: 30-60s, ~9-15 shots; for long
sources, model the structure condensed - keep hook, payoffs, cadence, not the
runtime). Draft the spec with the format routing above, then:

```
python3 engine.py estimate spec.json
```

The estimate splits Ken Burns shots (free to animate) from grok shots. Quote the
total plus TTS if the route uses a narrator (a 12-shot Ken Burns video runs about
$0.70; a 12-shot grok video about $1.80-$2.50). WAIT for the yes.

## Phase 3: Script (checkpoint 1)

Write the new script for the picked idea using `analysis/script.json` as the
recipe: same hook mechanism, same cadence numbers, same micro-payoff spacing,
same formatting devices - new content. Show it with a short note on how it maps
to the source's mechanics. WAIT for approval; revise until approved.

## Smart shot timing (the auto selector - StoryEngine parity)

The engine sizes every clip automatically; you author the `cut`s with these
rules and `estimate` prints the resulting timing table (gen_sec / cut_sec per
shot) so the plan is visible before any spend.

- **Cinematic storytelling = grok's strength exploited.** Grok animates one
  image in ONE direction well (an expressive smile, a cast of a fishing line,
  talking). So: several short cutscenes, one action each. Never ask a clip for
  two actions - split it into two shots.
- **Dialogue shots size themselves.** The engine computes words / 2.7 per sec
  + 0.3s buffer + 0.5s lead, generates exactly that (whole seconds, 6s floor,
  15s cap) and keeps the whole take - the clip ends when the line ends, because
  an over-long clip makes grok ad-lib garbage past the line. A line longer than
  ~38 words must be SPLIT across two shots, never stretched into one long clip.
  You can leave `cut` small on a dialogue shot; the engine raises it to fit.
- **Narrated shots follow the narration.** Split the voiceover across shots at
  2.5 words per second: target ~7s per shot (documentary pacing), minimum 4s
  (merge orphans), hard cap 10s (split mid-sentence at a comma or conjunction
  if needed). That is how "this image is 4 seconds, that image is 8" decides
  itself: the words each image covers set its cut.
- **Silent action shots**: wides ~3-4s, mediums ~2-2.5s, inserts ~1.4-1.8s
  (coverage rhythm). The engine generates cut + lead-in and trims.
- **People rules are baked into the engine** (build_motion): every silent shot
  gets a no-new-people guard, `"cutaway": true` on a shot makes it absolute
  NO-PEOPLE (use for props/scenery inserts), and dialogue shots carry the
  off-screen-speaker rule. Write motion prompts as concrete single actions -
  "gentle", "soft", "subtle" are banned words (they read as screensaver motion).

## Phase 4: Storyboard SHEET first, then keyframes (checkpoint 2)

StoryEngine order: ONE storyboard-sheet image -> analyze it -> only then spend
on full-res generation. Never generate individual keyframes before the sheet
has passed review.

1. Build `spec.json` (content-engine shape): cast sheet prompt anchored in
   `analysis/style.json` (the true style, world, palette), beats broken from the
   approved script per the coverage rules, per-shot `image`/`motion`/`dialogue`.
   Extra per-shot fields here: `"kenburns": "zoom_in|zoom_out|pan_left|pan_right"`
   (free still move) and `"cutaway": true` (absolute no-people guard).
2. **Storyboard sheet** (~$0.05, one call). Write `sheet_prompt.txt`: a
   production storyboard page in the film's exact art style - a clean grid,
   one numbered panel per shot, and under each panel a white caption strip
   with: panel number badge, timestamp, SHOT TYPE in caps, and the script
   line or action description (THE SCRIPT RIDES ON THE SHEET - the reviewer
   must be able to read the whole film). Keep captions short so the text
   renders legibly; panels drawn with the reference characters. Then:
   `python3 engine.py sheet sheet_prompt.txt <outdir>` (anchors on the cast
   sheet if urls.json has one; generate the cast sheet first when characters
   matter: run storyboard with a beats-empty spec, or engine sheet before).
3. **Analyze the sheet yourself** (vision, free): every shot present and
   readable? staging clear in one glance? characters consistent panel to
   panel? captions legible and matching the script? If a panel fails, fix the
   spec/prompt and regenerate the SHEET (cheap), not the keyframes.
4. Show Ryan the sheet. WAIT - this is checkpoint 2. Redos happen at sheet
   price until it is right.
5. **Only after the sheet passes**: `python3 engine.py storyboard spec.json
   <outdir>` - generates the cast sheet (if not already) and every full-res
   keyframe. Keyframe URLs persist in `urls.json`. Give the keyframes a quick
   defect pass (duplicated characters, wrong actor in shot); to redo one,
   delete its `_kf.png` and `urls.json` entry, rerun storyboard (redoing a
   beat's master means also deleting that beat's angle keyframes).

## Phase 5: Animate + deliver

1. `python3 engine.py animate spec.json <outdir>` - grok clip per shot, trim to
   cuts, stitch `final.mp4`, best-effort copy to Drive (`gdrive:clone-video/`).
2. Modeled thumbnail: write a GPT Image 2 prompt from `analysis/thumbnail.json`
   (same composition, psychology, and text treatment - new subject and words for
   the new idea) to `thumb_prompt.txt`, then
   `python3 engine.py thumbnail thumb_prompt.txt <outdir>`.
3. **Captions** (when `analysis/captions.json` has `present: true`) - clone the
   source's caption look onto the finished video:
   ```
   python3 captions.py align final.mp4 words.json      # whisper word timing (free, local)
   python3 captions.py render words.json ../analysis/captions.json caps/ <W> <H>
   python3 captions.py burn final.mp4 caps/ final_captioned.mp4
   ```
   Pillow renders the exact look (pill, colors, karaoke fill); ffmpeg overlays
   with word timing. `final_captioned.mp4` becomes the deliverable. Free.
4. Report paths: `final.mp4` (or `final_captioned.mp4`), `thumbnail_new.png`, the chosen title. Do NOT
   auto-open. Ask which shots to regenerate, if any.

## Notes

- Both stages resume: existing keyframes and clips are skipped, so a failed run
  reruns cheap.
- `animator: "seedance"` in settings swaps grok for seedance-2-fast
  (~$0.40/shot) when the source looks premium and Ryan asks for it.
- grok picks a random voice per clip - fine for one-off character lines, never
  for a recurring narrator. Any narrator role = elevenlabs-tts skill +
  `settings.narration_audio` (the mix ducks clip audio to 25% underneath).
- Narration timing: generate the voiceover from the approved script FIRST, read
  its length with `ffprobe -show_entries format=duration`, then set the shot
  `cut`s to sum to it (plus ~0.5s tail).
- If yt-dlp fails on a video (age gate, region lock), try
  `--cookies-from-browser chrome` before declaring it blocked.
