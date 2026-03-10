# Visual Profiles

Pluggable visual identity system for Economy FastForward. Each profile
is a self-contained config that captures every aspect of the channel's
visual identity. Think of each profile as a "theme" a customer picks
during onboarding on StoryEngine.

## Quick Start — Swap the Channel Aesthetic

```bash
# Option 1: Environment variable (per-channel default)
export VISUAL_PROFILE=holographic_hud

# Option 2: Airtable field (per-video override)
# Set "Visual Profile" field on an Idea Concepts record
```

## Available Profiles

| Profile | Status | Aesthetic | Cost Tier | Model |
|---------|--------|-----------|-----------|-------|
| `holographic_hud` | **Active (production)** | Dark ops center, holographic projections, zero humans | Low ($2-10) | Z Image |
| `cinematic_dossier` | Standalone template | Prestige documentary, Rembrandt lighting, anonymous figures, 3-substyle system | Mid ($8-20) | Seed Dream 4.0 |
| `clay_mannequin` | Standalone template | 3D clay mannequin dioramas, golden chest glow protagonist | Mid ($8-15) | Seed Dream 4.0 |

### Holographic Intelligence Display
- **3-variable system**: 8 content types x 5 display formats x 6 color moods
- **Figures**: Zero human figures — only data displays and projections
- **Animation**: Full 24-template motion system (low/medium/high x 8 content types)
- **Best for**: Geopolitics, military analysis, economic data, investigative journalism

### Cinematic Photorealistic Dossier
- **3-substyle system**: Dossier (60%), Schema (22%), Echo (18%)
- **Figures**: Anonymous humans with faces obscured by shadow/silhouette/backlighting
- **Animation**: Disabled (static stills only)
- **Rotation**: Echo only in acts 3-5, clusters of 2-3, post-echo returns to Dossier
- **Best for**: Geopolitics, finance, corporate power, historical analysis

### 3D Clay Mannequin Render
- **Single style**: Composition cycling only, no substyles
- **Figures**: Faceless ceramic mannequins, protagonist has golden amber chest glow
- **Animation**: Selective (hero shots), glow intensity tracks narrative arc
- **Best for**: Explainers, personal finance, social commentary, philosophy

## Creating a New Profile (< 5 minutes)

1. Copy `holographic_hud.py` as a starting template
2. Change the `profile_id`, `profile_name`, and `description`
3. Update each section to match your new aesthetic:
   - `image_gen` — model selection and costs
   - `style_system` — prefix/suffix/accent colors/substyles
   - `rotation` — composition constraints and act weights
   - `figure_rules` — human presence rules, people word filters
   - `scene_description` — system prompt + metaphor translation table
   - `animation` — motion templates and intensity levels (or set to disabled)
   - `thumbnail` — thumbnail visual identity
   - `ken_burns` — camera motion defaults
   - `template_metadata` — StoryEngine display info, costs, preview prompts
   - `raw` — enum-based configs, material vocabulary, valid models
4. Register in `__init__.py`:
   ```python
   _PROFILE_MODULES["my_new_style"] = "visual_profiles.my_new_style"
   ```
5. Test: `VISUAL_PROFILE=my_new_style python -m pytest image_prompt_engine/tests/`

### Completeness Checklist

Every section must be explicitly populated — no `None` values that cause
fallback to another profile's defaults. If a section doesn't apply
(e.g., animation disabled), set it explicitly:

```python
animation=AnimationConfig(
    animation_model="disabled",
    animation_cost_per_clip=0.0,
    motion_templates={},
    ...
)
```

## Schema Sections

| Section | Dataclass | What It Controls |
|---------|-----------|------------------|
| `image_gen` | `ImageGenConfig` | Scene/thumbnail model, resolution, cost |
| `style_system` | `StyleSystemConfig` | Prefix, suffix, substyles, accent colors |
| `rotation` | `RotationConfig` | Compositions, max consecutive rules, act weights |
| `figure_rules` | `FigureRulesConfig` | Human/mannequin rules, people word filters |
| `scene_description` | `SceneDescriptionConfig` | LLM system prompt, metaphor table |
| `animation` | `AnimationConfig` | Motion templates, intensity levels, rules |
| `thumbnail` | `ThumbnailConfig` | Thumbnail style, text rules, color presets |
| `ken_burns` | `KenBurnsConfig` | Direction map, presets, base duration |
| `template_metadata` | `TemplateMetadata` | StoryEngine display name, tags, costs |
| `raw` | `dict` | Enum configs, material vocabulary, valid models |

## Architecture

```
visual_profiles/
├── __init__.py              # Profile loader, registry, caching
├── schema.py                # VisualProfile + section dataclasses
├── holographic_hud.py       # Current production profile (750+ lines)
├── cinematic_dossier.py     # Standalone: Dossier/Schema/Echo system
├── clay_mannequin.py        # Standalone: 3D mannequin dioramas
└── README.md                # This file
```

## Profile Selection Order

1. **Explicit argument** — `load_profile("cinematic_dossier")`
2. **Airtable field** — `Visual Profile` on Idea Concepts record
3. **Environment variable** — `VISUAL_PROFILE=holographic_hud`
4. **Default** — `holographic_hud`

## How Existing Code Uses Profiles

Each existing file has a thin adapter that reads from the profile with
hardcoded fallbacks for backward compatibility:

| File | Reads From Profile |
|------|--------------------|
| `style_config.py` | `profile.style_system`, `profile.raw` |
| `sequencer.py` | `profile.rotation` |
| `prompt_builder.py` | `profile.style_system`, `profile.figure_rules` |
| `style_engine.py` | `profile.raw` (legacy re-exports) |
| `anthropic_client.py` | `profile.scene_description`, `profile.figure_rules` |
| `image_client.py` | `profile.image_gen` |
| `ken_burns_calculator.py` | `profile.ken_burns` |
| `animation_prompt_engine.py` | `profile.animation` |

**Backward compatibility**: If `load_profile()` returns `None`, every
consumer falls back to its current hardcoded values. Zero risk to production.

## Isolation Guarantee

Each profile is 100% self-contained. Loading `cinematic_dossier` produces
completely different visual output with zero references to holographic or
clay styles leaking through. Verified by automated isolation tests.
