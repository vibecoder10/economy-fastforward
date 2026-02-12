# Economy FastForward - Agent Documentation

## Visual Style — 3D Editorial Mannequin Render (Feb 2026)

### Overview

The Documentary Animation Prompt System generates visually specific, cinematic prompts optimized for AI image generation using **Seed Dream 4.5** for scene images and **Nano Banana Pro** for thumbnails.

**Key change in v2:** Style engine prefix goes at BEGINNING of prompts (models weight early tokens more heavily).

### Architecture

Prompts use a **7-layer architecture**:

```
[STYLE_ENGINE_PREFIX] + [SHOT TYPE] + [SCENE COMPOSITION] + [FOCAL SUBJECT] + [ENVIRONMENTAL STORYTELLING] + [STYLE_ENGINE_SUFFIX + LIGHTING] + [TEXT RULE]
```

#### Layer Breakdown

| Layer | Words | Description |
|-------|-------|-------------|
| Style Engine Prefix | 18 | ALWAYS FIRST - 3D editorial style declaration |
| Shot Type | 6 | Camera framing (e.g., "Isometric overhead view of") |
| Scene Composition | 20 | Physical environment with MATERIALS (concrete, chrome, glass) |
| Focal Subject | 25 | Matte gray mannequin with BODY LANGUAGE (no faces) |
| Environmental Storytelling | 35 | Symbolic objects in appropriate materials |
| Style Engine Suffix + Lighting | 30 | Locked constant + warm vs cool contrast |
| Text Rule | 10 | No text, or specify max 3 elements with material surfaces |

### Style Engine (Locked Constants)

**STYLE_ENGINE_PREFIX (always first):**
```
3D editorial conceptual render, monochromatic smooth matte gray mannequin figures with no facial
features, photorealistic materials and studio lighting.
```

**STYLE_ENGINE_SUFFIX (near end):**
```
Clean studio lighting, shallow depth of field, matte and metallic material
contrast, cinematic 16:9 composition
```

### Material Vocabulary

The 3D style's power comes from contrasting material textures:

| Category | Materials |
|----------|-----------|
| Premium/Aspirational | polished chrome, brushed gold, glass dome, velvet lining, warm spotlight, copper accents, leather with gold foil |
| Institutional/Cold | brushed steel, concrete, frosted glass, iron chains, cold fluorescent tubes, matte black, industrial pipes |
| Decay/Danger | rusted iron, cracked concrete, leaking dark fluid, corroded metal, flickering warning lights, oxidized copper |
| Data/Information | frosted glass panels with etched lines, chrome clipboards, backlit displays, embossed metal numerals |

### Figure Rules — The Mannequin

**ALWAYS specify:**
- Exact count: "one mannequin", "three mannequin figures"
- Material: "matte gray" (consistent across all scenes)
- Scale: "at medium scale" or "large in foreground"
- Clothing: "in a suit" for professionals
- Body language (CRITICAL since no face):
  - DEFEAT: "shoulders slumped, head bowed, arms hanging"
  - CONFIDENCE: "striding forward, chin raised, briefcase in hand"
  - REACHING: "arms extended upward, on tiptoes"
  - OVERWHELMED: "hunched over desk, hands gripping edges"
  - TRAPPED: "pressed against glass wall, hands flat on surface"

**NEVER:**
- "figures" without "mannequin" (model might generate realistic humans)
- Any facial expressions (mannequins are faceless)
- "crowd" or "people" (too vague)

### Text Rules for Scene Images

Text renders BETTER in 3D style — use material surfaces:

| Text Type | Example |
|-----------|---------|
| Dates | "2030" as embossed chrome numerals on frosted glass |
| Currency | "$250K" as stamped chrome price tag |
| Labels | "DENIED" stamped on matte document |
| Data points | "36T" on brushed steel plate |

**Rules:**
- Max 3 text elements per image
- Max 3 words each
- Every text element needs a material surface specified
- End prompt with: "no additional text beyond the specified elements" or "no text, no words, no labels"

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

**Hard limit: 120-150 words per prompt** (increased from 80-120 for 3D style detail)

Every word must describe something VISUAL.

### DO / DO NOT Rules

#### DO:
- Describe MATERIALS: chrome, steel, concrete, glass, leather, velvet
- Specify mannequin BODY LANGUAGE for emotion
- Use spatial relationships: "left side dark concrete, right side warm polished marble"
- Include material contrasts: matte vs metallic, warm vs cold
- Start every prompt with STYLE_ENGINE_PREFIX

#### DO NOT:
- Use paper-cut, illustration, lo-fi, or 2D style references
- Include facial expressions (mannequins are faceless)
- Explain economics abstractly
- Use double quotes (use single quotes)
- Exceed 150 words per prompt

### Example Prompts (3D Editorial Mannequin Render)

#### WIDE ESTABLISHING (Isometric Diorama)
```
3D editorial conceptual render, monochromatic smooth matte gray mannequin figures with no facial
features, photorealistic materials and studio lighting. Isometric overhead view
of a miniature America as a brushed steel diorama, glowing amber clusters marking
tech hubs, dim concrete zones elsewhere, small matte gray mannequin figures
crowded in the dim zones arms reaching toward the glow, chrome price tag barriers
ringing each bright cluster, migration flow lines etched into frosted glass floor.
Clean studio lighting, shallow depth of field, matte and metallic material contrast,
cinematic 16:9 composition, warm amber vs cold steel blue lighting contrast,
no text beyond the etched flow lines
```

#### MEDIUM HUMAN STORY
```
3D editorial conceptual render, monochromatic smooth matte gray mannequin figures with no facial
features, photorealistic materials and studio lighting. Medium shot of one matte
gray mannequin in a wrinkled suit sitting at a brushed steel desk, shoulders
slumped head bowed, laptop screen glowing with job listings, beside it a stack
of documents on cracked concrete surface, through frosted glass window a dim
cityscape. Clean studio lighting, shallow depth of field, matte and metallic
material contrast, cinematic 16:9 composition, warm desk lamp amber vs cold
window blue-gray lighting, no text no words no labels
```

#### DATA LANDSCAPE
```
3D editorial conceptual render, monochromatic smooth matte gray mannequin figures with no facial
features, photorealistic materials and studio lighting. Wide shot of a broken
chrome bridge spanning a dark void, left cliff of cracked concrete with matte
gray mannequin figures shoulders slumped looking across, right cliff of polished
marble with gleaming glass buildings and copper cranes, bridge fractured in the
middle with chrome price tags falling into darkness, embossed metal numerals
'36T' on a steel plate at the fracture point. Clean studio lighting, shallow
depth of field, matte and metallic material contrast, cinematic 16:9 composition,
cold concrete gray on left vs warm golden glow on right, no additional text
beyond the specified numerals
```

### Implementation

The prompt system is implemented in:
- `clients/style_engine.py` - Constants, scene types, camera patterns, material vocabulary
- `clients/anthropic_client.py` - Prompt generation methods

Key methods:
- `segment_scene_into_concepts()` - Main prompt generation with 7-layer architecture
- `get_documentary_pattern()` - Returns camera role sequence for segment count
- `get_scene_type_for_segment()` - Returns scene type with rotation logic

---

## Image Model Routing (Feb 2026)

### Model Configuration

| Model | Use Case | Cost | Notes |
|-------|----------|------|-------|
| **Seed Dream 4.5** | All scene images | $0.025/image | Best 3D editorial render quality |
| **Nano Banana Pro** | Thumbnails ONLY | $0.03/image | Proven text rendering, comic style |

### Seed Dream 4.5 Parameters

```python
SCENE_PARAMS = {
    "image_size": "landscape_16_9",  # NOT aspect_ratio
    "image_resolution": "2K",
    "max_images": 1,
    "seed": optional_int,  # Store in Airtable for reproducibility
}
```

### Key Methods

- `image_client.generate_scene_image(prompt, seed=None)` → Returns `{"url": str, "seed": int}`
- `image_client.generate_thumbnail(prompt)` → Returns `[url, ...]`

---

## Thumbnail System v2 (Feb 2026)

### Overview

Thumbnails use a DIFFERENT style than scene images — comic/editorial illustration via Nano Banana Pro, NOT 3D mannequin render. The house style is locked and works without a reference URL.

### House Style

**Composition — "Problem → Payoff" Split:**
- Left 60%: THE TENSION (dramatic scene, emotional figure, dark mood)
- Right 40%: THE PAYOFF (answer, protection, brightest element)
- Separator: diagonal divide line and/or bold red arrow

**Color System — 2+1 Rule:**
- BACKGROUND: One dominant mood color (deep navy, dark red, dark green)
- POP ACCENT: One bright contrast (golden glow, electric green)
- TEXT: White with black outline (ALWAYS)

**Figure Rules:**
- ONE central figure, comic/editorial illustration style
- Thick bold black outlines, expressive face
- Upper body minimum, professional clothing
- Body language matches topic emotion

### Thumbnail Text

Text IS included in thumbnails (Nano Banana Pro handles it well):

- Position: Upper 20% of frame, two lines stacked
- Line 1 (larger): Hook — year, number, dramatic claim (max 5 words)
- Line 2 (smaller): Question/tension (max 5 words)
- ONE word highlighted in bright red (curiosity trigger)
- Style: Bold white condensed sans-serif, ALL CAPS, black outline + shadow

### Function Signature (CHANGED in v2)

```python
# NEW signature - video_title and video_summary required, spec optional
async def generate_thumbnail_prompt(
    video_title: str,
    video_summary: str,
    thumbnail_spec_json: dict = None,  # Optional Gemini analysis
    thumbnail_concept: str = "",        # Optional Airtable direction
) -> str
```

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

### Motion Vocabulary (3D Clay Render Style)

All motion should feel subtle and mechanical, matching the 3D render aesthetic.

**Mannequin Figures:**
- "mannequin subtly shifts weight"
- "mannequin slowly turns body"
- "mannequin's arm gradually lifts"
- "mannequin's head gently tilts down"
- "fingers slowly close around handle"

**Mechanical/Industrial:**
- "gears slowly rotate"
- "pipes subtly vibrate"
- "gauge needles drift toward red zone"
- "lever gradually pulls down"
- "cracks slowly spread through concrete"

**Environmental:**
- "dust particles float through light beams"
- "fog wisps curl between objects"
- "light slowly sweeps across chrome surface"
- "reflections shift on metallic surfaces"

**Atmospheric (include at least one):**
- "warm spotlight slowly brightens"
- "shadows gradually lengthen"
- "ambient light subtly shifts from cool to warm"
- "lens flare drifts across frame"

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
