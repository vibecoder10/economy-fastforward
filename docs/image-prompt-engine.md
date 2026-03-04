# Image Prompt Engine (3-Style System)

The visual system uses 3 cinematic styles distributed across 6 narrative acts:

| Style | Weight | Look | When Used |
|-------|--------|------|-----------|
| **Dossier** | 60% | Photorealistic, Rembrandt lighting, accent colors | Investigation, corporate, power |
| **Schema** | 22% | Data overlay, glowing nodes, HUD aesthetics | Systems, networks, data |
| **Echo** | 18% | Painterly, historical, candlelit | Backstory, historical context |

## Prompt Architecture (Nano Banana 2 Structure)

Prompts follow the Nano Banana 2 optimum: `[Subject] + [Environment] + [Camera]`

1. **Scene description** (Subject + Action) — narrative content FIRST (~30-50 words)
2. `STYLE_ENVIRONMENTS` — per-style mood/lighting (~14 words)
3. `STYLE_CAMERAS` — per-composition art style/framing (~10 words)

## Two Style Systems (YouTube vs Animation)

- **YouTube pipeline** (`image_prompt_engine/`): Photorealistic cinematic (Dossier/Schema/Echo)
- **Animation pipeline** (`clients/style_engine.py`): 3D clay render mannequin style (faceless, matte gray, golden chest glow)
- The style engine has 9 SceneTypes: WIDE_ESTABLISHING, ISOMETRIC_DIORAMA, MEDIUM_HUMAN_STORY, CLOSE_UP_VIGNETTE, DATA_LANDSCAPE, SPLIT_SCREEN, PULL_BACK_REVEAL, OVERHEAD_MAP, JOURNEY_SHOT
- `get_documentary_pattern()` returns camera rotation for N images
- Image prompt word count: 62-84 words per prompt (~20 word prefix + 30-50 word description + ~10 word composition + ~10 word suffix). Optimized for Nano Banana 2's 30-75 word sweet spot.

## Rules

- Max 4 consecutive scenes with the same style (anti-clustering)
- 7 composition types cycle: wide, medium, closeup, environmental, portrait, overhead, low_angle
- Ken Burns motion is assigned based on composition type
- 6 images per scene, 20 scenes = 120 images per video
