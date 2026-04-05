# Story-to-Video Generator

Transform narrative concepts into complete video production packages combining keyframe images (Nano Banana Pro) and video bridges (Grok Imagine / Kie.ai API).

## Core Concept

Each video bridge requires TWO keyframe images — a start frame and an end frame. The Kie.ai API interpolates motion between them. The animation prompt describes ONLY the motion directions between the two images, not the static scene.

## Process

### Phase 1: Story Breakdown
Parse the story concept into:
- **Logline**: One-sentence summary
- **Tone**: Cinematic, documentary, dramatic, whimsical, etc.
- **Duration**: Total target length (determines shot count)
- **Visual style**: Art direction keywords

**Shot plan calculator:**

| Target Duration | Keyframes | Video Bridges | Bridge Duration |
|----------------|-----------|---------------|-----------------|
| 18 seconds     | 4         | 3             | 6s each         |
| 30 seconds     | 6         | 5             | 6s each         |
| 1 minute       | 10-11     | 9-10          | 6s each         |
| 2 minutes      | 17-21     | 16-20         | 6s each         |
| 5 minutes      | 41-51     | 40-50         | 6s each         |

Formula: `keyframes = (target_seconds / bridge_duration) + 1`

### Phase 2: Continuity Bible
Lock visual consistency BEFORE generating any prompts:

```json
{
  "characters": [
    {
      "name": "Agent Morrison",
      "appearance": "mid-40s Caucasian male, salt-and-pepper crew cut, sharp jawline",
      "wardrobe": "charcoal three-piece suit, burgundy tie, steel watch",
      "signature": "slight scar above left eyebrow"
    }
  ],
  "locations": [
    {
      "name": "The Situation Room",
      "description": "underground bunker, banks of glowing monitors, blue-white LED lighting",
      "palette": "navy, steel gray, cyan accents"
    }
  ],
  "lighting": "high-contrast Rembrandt lighting, deep shadows",
  "camera": "Arri Alexa Mini LF, Cooke S7/i Full Frame Plus lenses",
  "color_grade": "desaturated teal shadows, warm amber highlights",
  "aspect_ratio": "16:9"
}
```

Every keyframe prompt MUST reference the Bible to prevent visual drift.

### Phase 3: Keyframe Image Prompts
Generate structured prompts for each keyframe:

```json
{
  "keyframe_id": "KF-001",
  "shot_type": "wide establishing",
  "prompt": "[Subject from Bible] stands in [Location from Bible]. [Action]. [Lighting from Bible]. [Camera from Bible], wide establishing shot.",
  "aspect_ratio": "16:9",
  "notes": "Opening shot — establish scale and mood"
}
```

**Shot type rotation:** wide -> medium -> close-up -> over-shoulder -> wide (repeat)

### Phase 4: Video Bridge Prompts (Two-Image Bridges)

**CRITICAL:** Each bridge uses BOTH the start keyframe image and end keyframe image. The API interpolates between them.

```json
{
  "bridge_id": "BR-001",
  "from_keyframe": "KF-001",
  "to_keyframe": "KF-002",
  "duration": 6,
  "prompt": "Camera slowly dollies forward as the figure strides toward the entrance. Ambient hum of electronics swells. Fluorescent lights flicker on overhead.",
  "mode": "normal",
  "resolution": "720p"
}
```

**Kie.ai API payload for bridges:**
```json
{
  "model": "grok-imagine/image-to-video",
  "input": {
    "image_urls": [
      "<KF-N START image URL>",
      "<KF-N+1 END image URL>"
    ],
    "prompt": "<motion directions ONLY>",
    "mode": "normal",
    "duration": 6,
    "resolution": "720p",
    "aspect_ratio": "16:9"
  }
}
```

The `image_urls` array supports up to 7 images. For standard bridges, always provide exactly 2: start keyframe and end keyframe.

### Animation Prompt Rules

The animation prompt is NOT a scene description. It is motion DIRECTIONS — what changes between image 1 and image 2:

- **Lead with action** in the first 20-30 words (Grok prioritizes the beginning)
- **Strong motion verbs:** surges, crumples, slumps, whips, staggers, lunges, drifts
- **Exaggerate intensity:** "car passing" becomes "car passing quickly"
- **Camera movement:** slow dolly in, pull back, pan left, tracking shot, crane up, orbit
- **Audio direction:** dialogue in quotes, music cues, sound effects, or "dead silence"
- **One primary motion** per bridge — do not overload with simultaneous actions
- **Never contradict** what is visible in the source images

### Mode Selection

- **"normal"** — Default for most narrative scenes. Balanced, predictable motion.
- **"fun"** — Whimsical, playful, magical, or surreal transitions.
- **"spicy"** — High-energy action, dramatic reveals. ONLY works with Kie.ai-generated images, NOT uploaded images.

### Duration Guide

- **6s** — Quick cuts, action beats, reactions. Best quality. Default.
- **8-10s** — Dialogue scenes, slow reveals, atmospheric moments.
- **15-20s** — Long tracking shots, establishing sequences.
- **30s** — Maximum. Use sparingly, quality can degrade.

### Phase 5: Production Sheet

The output must follow this exact order — keyframes before their bridges:

```
KF-01 image prompt
KF-02 image prompt
BRIDGE 01→02 animation prompt (uses BOTH KF-01 and KF-02 image URLs)
KF-03 image prompt
BRIDGE 02→03 animation prompt (uses BOTH KF-02 and KF-03 image URLs)
KF-04 image prompt
BRIDGE 03→04 animation prompt (uses BOTH KF-03 and KF-04 image URLs)
...continue pattern...
```

Full production sheet format:

```
PRODUCTION SHEET: "{Title}"
Duration: {total}s | Keyframes: {n} | Bridges: {n}
Style: {visual_style} | Aspect: {aspect_ratio}

CONTINUITY BIBLE:
{bible_json}

KEYFRAMES:
KF-001: {prompt} | Shot: {type} | Aspect: {ratio}
KF-002: ...

BRIDGES:
BR-001: KF-001 + KF-002 | {duration}s | {motion_prompt}
BR-002: KF-002 + KF-003 | {duration}s | {motion_prompt}
...

ASSEMBLY ORDER:
1. BR-001 (6s video, KF-001→KF-002)
2. BR-002 (6s video, KF-002→KF-003)
3. BR-003 (6s video, KF-003→KF-004)
...stitch with 0.3s crossfade transitions
```

## Delivery Based on Length

| Duration | Delivery |
|----------|----------|
| Under 1 min | Full production sheet immediately |
| 1-2 min | Bible + scene list for approval, then batches of 5-6 keyframes |
| 3-5 min | Bible + scene list, then one Act at a time |

## Dispatch Integration

The production sheet output is consumed by the video dispatch system at:
`skills/video-pipeline/video_dispatch/`

### Dispatch Pipeline Execution Order

**Phase 1 (parallel):** Generate ALL keyframe images via Nano Banana API
**Phase 2 (parallel):** Once all image URLs are available, generate ALL bridges via Kie.ai API — each bridge sends both its start and end keyframe URLs
**Phase 3:** Download all video clips and stitch sequentially with 0.3s crossfade transitions

This two-phase parallel approach cuts total time from 21 sequential API calls to just 2 concurrent phases.

See `skills/video-pipeline/video_dispatch/dispatch.py` for the automation entry point.

```bash
cd skills/video-pipeline
python -m video_dispatch.dispatch production_sheet.json --dry-run     # validate
python -m video_dispatch.dispatch production_sheet.json --output-dir ./out  # generate
```
