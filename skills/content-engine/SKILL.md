---
name: content-engine
description: Turn a topic and length into a finished AI video, optionally seeded by your own images. Builds a cast sheet (character, product, or brand), then a per-beat storyboard with coverage (each moment shown from several matched angles), animates each shot with grok-imagine, and stitches an edited cut. Characters can speak (per-shot dialogue, lip-synced). Cheap: ~$0.14 per shot. Use for shorts, ads, explainers, or any visual content. Triggers on "content-engine", "/content-engine", "make a video about", "make an ad for", "turn this into a video".
---

# content-engine

Topic in, finished edited video out. Proven pipeline:

```
seed (optional) -> cast sheet -> per-beat coverage keyframes (GPT Image 2)
                -> grok-imagine clip per shot -> trim + stitch -> final.mp4
```

`engine.py` does the mechanical work. Your job: read the request, write the cast
sheet prompt and the beats, quote cost, run on approval.

## Hard rule: confirm cost before spending

Never call `engine.py run` before showing the estimate and getting a yes. Cost is
~$0.14 per shot (10-credit keyframe + 18-credit grok clip, $0.005/credit).

## The core idea: beats, not isolated shots

A jumpy video is one shot per story moment. A smooth video picks a **moment** and
shows it from several **angles** (coverage), then moves on. So structure the story
as a few **beats**, each with 2 to 4 shots covering the same continuous action.
Cuts inside a beat read as coverage; cuts between beats are normal story progress.

Within a beat, the first shot is the **master**. The engine generates the other
shots' keyframes off the master (plus the cast sheet) so they share lighting,
wardrobe, and setting. Keep screen direction consistent within a beat (the 180
rule), and use insert/cutaway shots (a prop, a detail) as bridges.

## Steps

1. **Read the request:** topic (required), duration (default ~30s), seed images
   (local paths or URLs), style (infer if unstated), aspect_ratio (16:9 default,
   9:16 for vertical), video_resolution (720p default). Restate it in one line.

2. **Seeds:** for local files run `python3 engine.py upload <path>` to get a URL.
   Collect them as `seed_urls`.

3. **Cast sheet prompt:** the consistency anchor. Person/character/mascot = 4-view
   sheet on neutral grey; product = clean multi-angle; brand = style board. If
   `seed_urls` exist say "match the attached reference exactly"; else invent from
   the topic. (See `examples/character-sheet.txt`.)

4. **Beats:** break the story into ~3 to 5 beats, each a list of shots. Each shot:
   - `name` (unique, e.g. `b2_3ots`), `cut` (seconds it appears in the final edit;
     wides ~3-4s, mediums ~2-2.5s, inserts ~1.4-1.8s),
   - `image` (GPT Image 2 prompt for a clean full-frame keyframe in the chosen
     style; the first shot of a beat fully establishes the moment, the rest say
     "same moment, camera now [angle]"),
   - `motion` (how grok animates it: smooth, in style, no text/subtitles),
   - `dialogue` (optional; if set, grok speaks it lip-synced. Note grok picks the
     voice randomly per clip, fine for one-off lines, not a consistent recurring
     voice).
   (See `examples/storyboard-sheet.txt` for a worked fishing example.)

5. **Spec + estimate:** write `spec.json`, run `python3 engine.py estimate spec.json`,
   show the cost, WAIT for a yes.

6. **Run + report:** `python3 engine.py run spec.json <outdir>`. Report the file
   paths (cast sheet, `final.mp4`). Do NOT auto-open. Tell the user to watch
   `final.mp4` and say which shots to regenerate.

Output folder: `~/Desktop/content-engine/<short-topic-slug>/`.

## spec.json shape

```json
{
  "settings": {"aspect_ratio": "16:9", "video_resolution": "720p", "ref_resolution": "2K", "start_offset": "0.8", "animator": "grok"},
  "seed_urls": ["https://..."],
  "reference": {"prompt": "<cast sheet prompt>"},
  "beats": [
    [
      {"name": "b1_wide", "cut": 3.5, "image": "<master keyframe prompt>", "motion": "<motion>", "dialogue": null},
      {"name": "b1_med",  "cut": 2.5, "image": "<same moment, medium>",   "motion": "<motion>", "dialogue": "Nice morning."}
    ]
  ]
}
```

## Notes

- Audio: grok generates native audio per clip (ambience + any dialogue); the edit
  keeps it. ponytail: no separate ambience bed, grok's per-clip lake/room sound is
  continuous enough. Add a unified bed later only if seams bother you.
- `animator`: `"grok"` (default, ~$0.14/shot) or `"seedance"` (~$0.40/shot, smoother
  motion, the expensive route). Same beats/coverage either way; only the per-shot
  animation model changes. Use seedance when the user asks for it or wants top quality.
- grok caps clips at 30s and 480p/720p; we generate 6s and trim to the `cut`.
- Self-contained; does not depend on the StoryEngine app.
