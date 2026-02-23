# Image Prompt Engine (3-Style System)

The visual system uses 3 cinematic styles distributed across 6 narrative acts:

| Style | Weight | Look | When Used |
|-------|--------|------|-----------|
| **Dossier** | 60% | Photorealistic, Rembrandt lighting, accent colors | Investigation, corporate, power |
| **Schema** | 22% | Data overlay, glowing nodes, HUD aesthetics | Systems, networks, data |
| **Echo** | 18% | Painterly, historical, candlelit | Backstory, historical context |

## Prompt Architecture (4 Layers)

1. `YOUTUBE_STYLE_PREFIX` - Cinematic photorealism foundation
2. Scene description - Narrative content from script
3. `COMPOSITION_DIRECTIVES` - Camera angles (7 types cycle for variety)
4. `STYLE_SUFFIXES` - Style-specific atmosphere

## Two Style Systems (YouTube vs Animation)

- **YouTube pipeline** (`image_prompt_engine/`): Photorealistic cinematic (Dossier/Schema/Echo)
- **Animation pipeline** (`clients/style_engine.py`): 3D clay render mannequin style (faceless, matte gray, golden chest glow)
- The style engine has 9 SceneTypes: WIDE_ESTABLISHING, ISOMETRIC_DIORAMA, MEDIUM_HUMAN_STORY, CLOSE_UP_VIGNETTE, DATA_LANDSCAPE, SPLIT_SCREEN, PULL_BACK_REVEAL, OVERHEAD_MAP, JOURNEY_SHOT
- `get_documentary_pattern()` returns camera rotation for N images
- Image prompt word count: 75-110 words per prompt (validated)

## Rules

- Max 4 consecutive scenes with the same style (anti-clustering)
- 7 composition types cycle: wide, medium, closeup, environmental, portrait, overhead, low_angle
- Ken Burns motion is assigned based on composition type
- 6 images per scene, 20 scenes = 120 images per video
