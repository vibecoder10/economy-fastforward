# Story-to-Video Generator

Transform narrative concepts into complete video production packages combining keyframe images (Nano Banana Pro) and video bridges (Grok Imagine / Kie.ai API).

## Process

### Phase 1: Story Breakdown
Parse the story concept into:
- **Logline**: One-sentence summary
- **Tone**: Cinematic, documentary, dramatic, whimsical, etc.
- **Duration**: Total target length (determines shot count)
- **Visual style**: Art direction keywords

**Shot calculation:**
- Each keyframe pair produces one video bridge (6-30 seconds)
- For N seconds of video: `ceil(N / bridge_duration) + 1` keyframes needed
- Under 18s: 4 keyframes, 3 bridges
- 30s: 6 keyframes, 5 bridges
- 60s: 11 keyframes, 10 bridges
- 5 min: ~51 keyframes, 50 bridges

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

Every keyframe and bridge prompt MUST reference the Bible to prevent visual drift.

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

### Phase 4: Video Bridge Prompts
Generate motion prompts between consecutive keyframes:

```json
{
  "bridge_id": "BR-001",
  "from_keyframe": "KF-001",
  "to_keyframe": "KF-002",
  "duration": 6,
  "prompt": "Camera slowly pushes forward toward the figure. Ambient hum of electronics fills the space. Monitors flicker with data streams. The figure turns slightly, light catching the scar above his left eyebrow.",
  "mode": "normal",
  "resolution": "720p"
}
```

**Bridge prompt rules:**
- First 20-30 words: action verbs and camera movement
- Describe what MOVES (camera, subject, environment)
- Include atmospheric audio cues
- Reference Bible elements for consistency

### Phase 5: Production Sheet
Deliver the complete package:

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
BR-001: KF-001 -> KF-002 | {duration}s | {prompt}
BR-002: ...

ASSEMBLY ORDER:
1. KF-001 (still, 1s hold)
2. BR-001 (6s video)
3. KF-002 (still, 0.5s hold)
4. BR-002 (6s video)
...
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

The dispatch system:
1. Parses the production sheet
2. Generates keyframe images via Kie.ai text-to-image API
3. Generates video bridges via Kie.ai image-to-video API
4. Polls for completion of all tasks
5. Assembles the final clip sequence

See `skills/video-pipeline/video_dispatch/dispatch.py` for the automation entry point.
