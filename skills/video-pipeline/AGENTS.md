# Economy FastForward - Agent Documentation

## Visual Style — Cinematic Photorealistic Documentary (Mar 2026)

### Overview

The Documentary Prompt System generates visually specific, cinematic prompts optimized for AI image generation using **Seed Dream 4.5** for scene images and **Nano Banana Pro** for thumbnails.

**Key principle:** Style engine prefix goes at BEGINNING of prompts (models weight early tokens more heavily).

### Architecture

Prompts use a **7-layer architecture**:

```
[STYLE_ENGINE_PREFIX] + [SHOT TYPE] + [SCENE COMPOSITION] + [FOCAL SUBJECT] + [ENVIRONMENTAL STORYTELLING] + [STYLE_ENGINE_SUFFIX + LIGHTING] + [TEXT RULE]
```

#### Layer Breakdown

| Layer | Words | Description |
|-------|-------|-------------|
| Style Engine Prefix | 35 | ALWAYS FIRST - Cinematic photorealistic documentary declaration |
| Shot Type | 6 | Camera framing (e.g., "Overhead establishing shot of") |
| Scene Composition | 25 | Real-world environment with cinematic lighting |
| Focal Subject | 30 | Anonymous figures, faces obscured by shadow/silhouette/backlighting |
| Environmental Storytelling | 40 | Objects that tell the story |
| Style Engine Suffix + Lighting | 45 | Film grain/halation constant + warm vs cool contrast |
| Text Rule | 10 | No text, or specify max 3 elements |

### Style Engine (Locked Constants)

**STYLE_ENGINE_PREFIX (always first):**
```
Cinematic photorealistic editorial photograph, dark moody atmosphere,
desaturated color palette with cold teal accent lighting, Rembrandt lighting,
deep shadows, shallow depth of field, subtle film grain, documentary photography
style, shot on Arri Alexa 65 with 35mm Master Prime lens, 16:9 cinematic
composition, epic scale.
```

**STYLE_ENGINE_SUFFIX (near end):**
```
Real Kodak Vision3 500T 35mm film grain, silver halide noise, high contrast,
crushed blacks, organic halation effects around light sources, visible
atmospheric particulate, cinematic color grade.
```

### Material Vocabulary

Cinematic environments with real-world textures:

| Category | Materials |
|----------|-----------|
| Premium/Power | polished mahogany, leather chairs, crystal decanters, gold-framed documents, warm tungsten light |
| Institutional/Cold | concrete bunkers, fluorescent corridors, steel doors, security cameras, industrial ventilation |
| Decay/Danger | peeling paint, water stains, rusted infrastructure, flickering lights, abandoned equipment |
| Data/Information | Bloomberg terminals, holographic displays, translucent teal data overlays, glowing monitors in dark rooms |

### Figure Rules — Anonymous Human Figures

**ALWAYS specify:**
- Face obscured: "face in deep shadow", "silhouetted against light", "turned away from camera"
- Real clothing and body: "in a tailored suit", "weathered hands"
- Scale: "a lone figure" or "three silhouettes"
- Body language (CRITICAL since face is hidden):
  - DEFEAT: "shoulders slumped, head bowed, arms hanging"
  - CONFIDENCE: "striding forward, chin raised, briefcase in hand"
  - REACHING: "arms extended upward, on tiptoes"
  - OVERWHELMED: "hunched over desk, hands gripping edges"
  - TRAPPED: "pressed against glass wall, hands flat on surface"

**NEVER:**
- Show clear facial features (faces ALWAYS obscured)
- Use illustration, 2D, or stylized references
- "crowd" or "people" (too vague — specify count and pose)

### Text Rules for Scene Images

Text on real surfaces:

| Text Type | Example |
|-----------|---------|
| Dates | "2030" as weathered ink on aged parchment |
| Currency | "$250K" as embossed numbers on a worn banknote |
| Labels | "DENIED" stamped on classified document |
| Data points | "36T" as glowing numbers on dark monitor |

**Rules:**
- Max 3 text elements per image
- Max 3 words each
- End prompt with: "no additional text beyond the specified elements" or "no text, no words, no labels"

### Scene Types (6 Types - Rotate for Variety)

| Type | Shot Prefix | Use When |
|------|-------------|----------|
| Isometric Diorama | "Overhead establishing shot of" | Systems, flows, economies |
| Split Screen | "Split composition showing" | Comparing two realities, before/after |
| Journey Shot | "Wide tracking shot of" | Progression, decline, timelines |
| Close-Up Vignette | "Extreme close-up of" | Emotional details, critical moments |
| Data Landscape | "Environmental detail, no human figure, objects telling the story" | Making statistics feel physical |
| Overhead Map | "Top-down surveillance shot of" | Geographic or systemic views |

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

**Hard limit: 120-200 words per prompt.**

Every word must describe something VISUAL.

### DO / DO NOT Rules

#### DO:
- Describe real cinematic environments with dramatic lighting
- Body language for emotion: shoulders slumped, arms crossed, leaning forward
- Use spatial relationships: "left side dark decay, right side warm polished mahogany"
- Include atmospheric details: dust, haze, lens flare, film grain
- Start every prompt with STYLE_ENGINE_PREFIX
- Accent colors: teal=tech/geopolitical, amber=power/money, red=military/conflict

#### DO NOT:
- Show clear facial features (faces always obscured)
- Use illustration, 2D, or stylized references
- Explain economics abstractly
- Use double quotes (use single quotes)
- Exceed 200 words per prompt

### Example Prompts (Cinematic Photorealistic Documentary)

#### WIDE ESTABLISHING (Overhead)
```
Cinematic photorealistic editorial photograph, dark moody atmosphere, desaturated
color palette with cold teal accent lighting, Rembrandt lighting, deep shadows,
shallow depth of field, subtle film grain, documentary photography style, shot on
Arri Alexa 65 with 35mm Master Prime lens, 16:9 cinematic composition, epic scale.
Overhead establishing shot of a darkened military command center, banks of glowing
monitors casting cold teal light across silhouetted figures at their stations,
classified documents scattered across a central briefing table, a single red phone
illuminated by a cone of warm tungsten light. Real Kodak Vision3 500T 35mm film
grain, silver halide noise, high contrast, crushed blacks, organic halation effects
around the monitor screens, visible atmospheric particulate, cinematic color grade,
cold teal monitors vs warm tungsten desk lamp, no text no words no labels
```

#### MEDIUM HUMAN STORY
```
Cinematic photorealistic editorial photograph, dark moody atmosphere, desaturated
color palette with cold teal accent lighting, Rembrandt lighting, deep shadows,
shallow depth of field, subtle film grain, documentary photography style, shot on
Arri Alexa 65 with 35mm Master Prime lens, 16:9 cinematic composition, epic scale.
Medium shot of an anonymous figure in a tailored suit seated at a mahogany desk,
face completely in shadow from Rembrandt side lighting, warm desk lamp casting amber
glow on scattered financial reports, through a rain-streaked window behind him a cold
blue cityscape of distant towers. Real Kodak Vision3 500T 35mm film grain, silver
halide noise, high contrast, crushed blacks, organic halation effects around the desk
lamp, visible atmospheric particulate, cinematic color grade, warm amber desk lamp vs
cold blue window light, no text no words no labels
```

#### DATA LANDSCAPE
```
Cinematic photorealistic editorial photograph, dark moody atmosphere, desaturated
color palette with cold teal accent lighting, Rembrandt lighting, deep shadows,
shallow depth of field, subtle film grain, documentary photography style, shot on
Arri Alexa 65 with 35mm Master Prime lens, 16:9 cinematic composition, epic scale.
Environmental detail, no human figure, objects telling the story, a Wall Street
trading terminal in a darkened room, Bloomberg screens displaying green spikes and
red crashes, the glow of six monitors illuminating an empty leather chair, coffee
cup still steaming, papers scattered mid-sentence. Real Kodak Vision3 500T 35mm
film grain, silver halide noise, high contrast, crushed blacks, organic halation
effects around the glowing monitors, visible atmospheric particulate, cinematic
color grade, cold teal monitor glow vs warm ambient room light, no text no words
no labels
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
| **Seed Dream 4.5** | All scene images | $0.025/image | Best cinematic photorealistic quality |
| **Nano Banana Pro** | Thumbnails ONLY | $0.03/image | Proven text rendering, comic style |

### Seed Dream 4.0 Parameters

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

Thumbnails use a cinematic photorealistic movie poster style via Nano Banana Pro. The house style is locked and works without a reference URL.

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

### Motion Vocabulary (Cinematic Documentary Style)

All motion should feel subtle and cinematic, matching the documentary photography aesthetic.

**Human Figures:**
- "figure subtly shifts weight"
- "silhouette slowly turns"
- "figure's arm gradually lifts"
- "figure's head gently tilts down"
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
- "light slowly sweeps across surface"
- "reflections shift on wet pavement"

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
