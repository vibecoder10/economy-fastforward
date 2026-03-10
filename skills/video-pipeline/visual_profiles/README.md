# Visual Profiles

Pluggable visual identity system for Economy FastForward. Each profile
is a self-contained config that captures every aspect of the channel's
visual identity.

## Quick Start — Swap the Channel Aesthetic

```bash
# Option 1: Environment variable (per-channel default)
export VISUAL_PROFILE=holographic_hud

# Option 2: Airtable field (per-video override)
# Set "Visual Profile" field on an Idea Concepts record
```

## Available Profiles

| Profile | Status | Aesthetic |
|---------|--------|-----------|
| `holographic_hud` | **Active (production)** | Dark ops center, holographic projections, zero humans |
| `cinematic_dossier` | Reference | Prestige documentary, Rembrandt lighting, anonymous figures |
| `clay_mannequin` | Reference | 3D clay mannequin dioramas, golden chest glow protagonist |

## Creating a New Profile (< 5 minutes)

1. Copy `holographic_hud.py` as a starting template
2. Change the `profile_id`, `profile_name`, and `description`
3. Update each section to match your new aesthetic:
   - `image_gen` — model selection and costs
   - `style_system` — prefix/suffix/accent colors
   - `rotation` — composition constraints and act weights
   - `figure_rules` — human presence rules
   - `scene_description` — system prompt for LLM image descriptions
   - `animation` — motion templates and intensity levels
   - `thumbnail` — thumbnail visual identity
   - `ken_burns` — camera motion defaults
   - `raw` — enum-based configs (content types, display formats, color moods)
4. Register in `__init__.py`:
   ```python
   _PROFILE_MODULES["my_new_style"] = "visual_profiles.my_new_style"
   ```
5. Test: `VISUAL_PROFILE=my_new_style python -m pytest image_prompt_engine/tests/`

## Architecture

```
visual_profiles/
├── __init__.py              # Profile loader, registry, caching
├── schema.py                # VisualProfile dataclass definition
├── holographic_hud.py       # Current production profile
├── cinematic_dossier.py     # Legacy: Dossier/Schema/Echo system
├── clay_mannequin.py        # Legacy: 3D mannequin style
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
