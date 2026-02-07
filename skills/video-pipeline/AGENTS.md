# Economy FastForward - Agent Documentation

## Image Prompt System v2 (Feb 2026)

### Overview

The Documentary Animation Prompt System generates visually specific, cinematic prompts optimized for AI image generation (Nano Banana). All images are designed for animation.

### Architecture

Prompts use a **5-layer architecture**:

```
[SHOT TYPE] + [SCENE COMPOSITION] + [FOCAL SUBJECT] + [ENVIRONMENTAL STORYTELLING] + [STYLE_ENGINE + LIGHTING]
```

#### Layer Breakdown

| Layer | Words | Description |
|-------|-------|-------------|
| Shot Type | 5 | Camera framing (e.g., "Overhead isometric diorama of") |
| Scene Composition | 15 | Physical scene/environment - CONCRETE places, not abstractions |
| Focal Subject | 20 | Main character/object with action and emotion |
| Environmental Storytelling | 30 | Symbolic objects, visual metaphors, data made physical |
| Style Engine + Lighting | 50 | Locked constant + scene-specific warm vs cool contrast |

### Style Engine (Locked Constant)

```
Lo-fi 2D digital illustration, paper-cut collage diorama with layered depth,
visible brushstroke textures, subtle film grain, muted earth tones with selective
neon accent lighting, tilt-shift miniature depth of field, Studio Ghibli background
painting meets editorial infographic, 16:9 cinematic composition
```

### Scene Types (6 Types - Rotate for Variety)

| Type | Shot Prefix | Use When |
|------|-------------|----------|
| Isometric Diorama | "Overhead isometric diorama of" | Systems, flows, economies |
| Split Screen | "Split-screen diorama showing" | Comparing two realities, before/after |
| Journey Shot | "Wide journey shot of" | Progression, decline, timelines |
| Close-Up Vignette | "Close-up of" | Emotional human moments |
| Data Landscape | "Data landscape showing" | Making statistics feel physical |
| Overhead Map | "Overhead map view of" | Geographic or systemic views |

**Rule: Never use the same scene type for consecutive images.**

### Documentary Camera Pattern (Per Scene)

The 4-shot pattern creates narrative rhythm:

```
1. WIDE ESTABLISHING  — Set the scene at macro level
   → Scene types: Isometric Diorama, Overhead Map, Journey Shot

2-3. MEDIUM HUMAN STORY — Zoom into person experiencing the topic
   → Scene types: Close-Up Vignette, Side View

4-5. DATA/METAPHOR — Visualize the mechanism or data
   → Scene types: Data Landscape, Split Screen, Journey Shot

6. PULL BACK REVEAL — Wide shot showing scale/consequence
   → Scene types: Journey Shot (extreme wide), Overhead Map
```

For scenes with fewer images:
- 4 images: Wide → Human → Data → Reveal
- 3 images: Wide → Human → Reveal
- 2 images: Human → Reveal

### Word Budget

**Hard limit: 80-120 words per prompt**

Every word must describe something VISUAL.

### DO / DO NOT Rules

#### DO:
- State each visual concept ONCE with specific imagery
- Use concrete nouns: "dollar sign barriers", "crumbling bridge", "glowing neon skyline"
- Include specific colors: "warm amber", "cold blue-white", "muted earth tones with red warning accents"
- Describe spatial relationships: "left side dim, right side glowing"
- Include texture words: "paper-cut", "layered", "brushstroke", "film grain"

#### DO NOT:
- Repeat concepts in different words (no "innovation slows" 5 ways)
- Explain economics (AI models don't understand "geographic mobility hit record lows")
- Use vague abstractions: "innovation", "mobility paralysis", "economic stagnation"
- Include keyword spam sections
- Exceed 120 words per prompt

### Example Prompts

#### WIDE ESTABLISHING (Overhead Map)
```
Overhead isometric map of America as a paper-cut diorama, glowing orange
clusters marking tech hubs in SF Austin NYC Boston, dim blue-gray everywhere
else, tiny paper figures crowded in the dim zones reaching toward the glow,
red price tag barriers ringing each bright cluster, migration flow arrows
drawn in pencil fading to nothing, warm neon vs cool shadow contrast,
lo-fi 2D digital illustration with layered paper depth and visible brushstroke
textures, subtle film grain, tilt-shift miniature depth of field, Studio Ghibli
background painting meets editorial infographic, 16:9 cinematic wide shot,
soft volumetric lighting through paper layers
```

#### MEDIUM HUMAN STORY (Side View)
```
Side view of a young engineer at a desk in a small dim apartment, laptop screen
showing job offers from San Francisco, beside her a stack of apartment listings
with crossed-out prices, through the window a quiet small-town street with bare
trees, her expression determined but trapped, split warm desk lamp light vs cold
blue window light, paper-cut collage style with layered depth, muted earth tones
with selective amber and blue accents, visible hand-drawn linework, lo-fi 2D
digital illustration with film grain, 16:9 cinematic frame
```

#### DATA LANDSCAPE
```
A broken bridge made of dollar bills spanning a deep canyon, left cliff edge
labeled TALENT with crowds of paper-cut workers looking across, right cliff
labeled OPPORTUNITY with gleaming miniature city skyline and cranes, bridge
crumbling in the middle with price tags falling into the void, equation fragments
floating in dusty air, isometric perspective with tilt-shift blur at edges, muted
palette with red warning accents on the fracture point, lo-fi 2D digital
illustration with film grain and brushstroke overlay, 16:9 cinematic composition
```

### Implementation

The prompt system is implemented in:
- `clients/style_engine.py` - Constants, scene types, camera patterns
- `clients/anthropic_client.py` - Prompt generation methods

Key methods:
- `segment_scene_into_concepts()` - Main prompt generation with 5-layer architecture
- `get_documentary_pattern()` - Returns camera role sequence for segment count
- `get_scene_type_for_segment()` - Returns scene type with rotation logic

---

## Pipeline Bots

### Idea Bot
Generates 3 video concepts from YouTube URL or topic description.

### Script Bot
Generates 20-scene beat sheet and voiceover narration.

### Voice Bot
Generates ElevenLabs voiceovers for all scenes.

### Image Prompt Bot
Segments scenes by duration (6-10s per image) and generates prompts.

### Image Bot
Generates images from prompts via Kie.ai (Nano Banana).

### Thumbnail Bot
Generates thumbnail using reference image analysis.

### Render Bot
Exports to Remotion for video rendering.

---

## Image-to-Video Animation System (Feb 2026)

### Overview

The animation system transforms static AI-generated images into animated video clips using Grok Imagine (via Kie.ai). It uses shot-type-aware motion vocabulary to create contextually appropriate camera movements.

### Hero Shot System

Hero shots are high-impact moments that receive longer (10s) video treatment vs 6s standard.

**Rules:**
1. Maximum 3 hero shots per video (if everything is special, nothing is)
2. Never consecutive (minimum 2 images gap for pacing contrast)
3. Automatically selected based on:
   - Scene 1 opener (hook moment)
   - Key data reveals (keywords: collapse, crash, billion, prediction)
   - Final scene reveal (ending with impact)

**Duration:**
- Standard shots: 6 seconds
- Hero shots: 10 seconds

### Camera Movement Vocabulary

Motion prompts are generated based on shot type:

| Scene Type | Standard Motion (6s) | Hero Motion (10s) |
|------------|---------------------|-------------------|
| Isometric Diorama | Slow push-in with slight rotation | + gradually revealing full depth |
| Split Screen | Slow lateral pan left to right | + crossing the divide |
| Journey Shot | Slow tracking along the path | + with depth reveal |
| Close-Up Vignette | Very slow drift to the right | + subtle rack focus |
| Data Landscape | Slow crane upward | + revealing the scale |
| Overhead Map | Slow push-in | + with rotation surveying landscape |

### Motion Vocabulary (Paper-Cut Style)

All motion should feel like animated illustrations, not live action.

**Figures/People:**
- "figure gently turns head toward..."
- "silhouette slowly reaches hand forward"
- "paper-cut figures subtly sway in place"
- "character's hair and clothes drift as if underwater"

**Environmental:**
- "paper layers shift with gentle parallax depth"
- "leaves and particles drift slowly across frame"
- "smoke or fog wisps curl through the scene"
- "light beams slowly sweep across the surface"

**Atmospheric (include at least one):**
- "warm light gently pulses like breathing"
- "dust particles float through light beams"
- "subtle film grain flickers"
- "shadows slowly shift as if clouds passing overhead"

**Speed Words:**
- ALWAYS use: slow, subtle, gentle, soft, gradual, drifting, easing
- NEVER use: fast, sudden, dramatic, explosive, rapid, intense, quick

### Cost Control

Video generation costs $0.10 per clip via Kie.ai.

**MANUAL_ONLY Mode (default: true):**
- Video generation requires explicit `--animate` command
- Cost estimate shown before generation
- Confirmation required for costs over $5

**CLI Commands:**
```bash
# Estimate cost only
python pipeline.py --animate "Video Title" --estimate

# Generate all videos
python pipeline.py --animate "Video Title"

# Generate hero shots only (max 3, cost-effective testing)
python pipeline.py --animate "Video Title" --heroes-only

# Generate specific scene
python pipeline.py --animate "Video Title" --scene 3
```

### Airtable Fields (Images Table)

Animation-related fields:
- `Shot Type` - Single Select (ISOMETRIC_DIORAMA, SPLIT_SCREEN, etc.)
- `Hero Shot` - Checkbox for hero status
- `Video Clip URL` - Direct Drive URL for video clip
- `Animation Status` - Single Select (Pending, Processing, Done, Failed)
- `Video Duration` - Number (6 or 10 seconds)

### Integration with Remotion

The `package_for_remotion()` method now includes:
- `type`: "image" or "video" for each segment
- `isHeroShot`: boolean for render priority
- `videoDuration`: actual video duration (6 or 10)

Remotion should:
1. Play video clips when available (preferred)
2. Fall back to Ken Burns effect on static images
3. Use `videoDuration` for timing instead of calculated duration

### CRITICAL: Image Source

**Always source images from Google Drive permanent URLs, NEVER Airtable attachments.**

Airtable attachment URLs expire after ~2 hours. This has caused multiple pipeline failures.

Direct Drive URL format:
```
https://drive.google.com/uc?export=download&id=FILE_ID
```

The `get_direct_drive_url()` helper in `google_client.py` handles the conversion.

### Implementation Files

- `clients/google_client.py` - `get_direct_drive_url()` helper
- `clients/style_engine.py` - Camera movement vocabulary
- `clients/anthropic_client.py` - `generate_video_prompt()` with shot type awareness
- `clients/airtable_client.py` - `update_image_animation_fields()` method
- `pipeline.py` - `run_video_animation_pipeline()`, hero detection, CLI commands
