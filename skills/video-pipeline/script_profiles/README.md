# Script Profiles — Pluggable Editorial Voices

A script profile is a **complete editorial voice definition**. It controls
everything about how scripts are written: tone, audience, act structure,
structural laws, number density rules, retention engineering, language
constraints, framework integration, and validation thresholds.

Swapping the editorial approach = changing one field or env var.

## Quick Start

```python
from script_profiles import load_script_profile

# Load from env var or default (power_doctrine_v2)
profile = load_script_profile()

# Load a specific profile
profile = load_script_profile("power_doctrine_v1")

# Use in script generation
from brief_translator.script_generator import build_script_prompt, generate_script

prompt = build_script_prompt(brief, profile=profile)
result = await generate_script(client, brief, profile=profile)
```

## Profile Selection Order

1. **Airtable field**: `Script Profile` on the Idea Concepts record
2. **Environment variable**: `SCRIPT_PROFILE`
3. **Default**: `power_doctrine_v2`

## Creating a New Profile (< 10 minutes)

1. Copy `power_doctrine_v2.py` as your starting point
2. Update the identity section (profile_id, name, description)
3. Modify the voice (identity, tone, audience, posture)
4. Adjust structural laws to match your editorial approach
5. Define your act structure (names, purposes, word percentages)
6. Set number density requirements
7. Update language rules (use phrases, kill phrases)
8. Configure framework integration rules
9. Set validation thresholds (word count min/max)
10. Register in `__init__.py`:

```python
_PROFILE_MODULES["your_profile_id"] = "script_profiles.your_profile_id"
```

## Profile Sections

| Section | What It Controls |
|---------|-----------------|
| `voice` | Narrator identity, tone, audience definition |
| `structural_laws` | Non-negotiable narrative rules |
| `content_ratio` | Runtime allocation percentages |
| `act_structure` | Act count, names, purposes, word percentages |
| `number_density` | Minimum numbers per act, anti-words |
| `retention` | Cliffhanger rules, micro-revelation cadence |
| `language` | Approved/banned phrases, framework naming rules |
| `framework_integration` | Available frameworks, integration style |
| `incentive_chain` | Whether incentive chains are required |
| `teardown` | Multi-rationale teardown templates |
| `validation` | Word count limits, enabled checks |
| `emotional_arc` | Per-act emotional progression |
| `act_specific_rules` | Detailed per-act writing instructions |
| `micro_payoff_architecture` | Scene-level structure template |
| `framework_revelation_engine` | Framework visibility rules |
| `strict_grounding_rule` | Factual grounding constraints |

## Available Profiles

| ID | Name | Style | Status |
|----|------|-------|--------|
| `power_doctrine_v2` | Investigative Reveal | Follow-the-money, incentive chains, invisible framework | **Production** |
| `power_doctrine_v1` | Framework Explainer | Documentary teaching, explicit framework, educational | Legacy |

## Relationship to Visual Profiles

| Aspect | Visual Profile | Script Profile |
|--------|---------------|----------------|
| Controls | Image style, models, rotation | Editorial voice, act structure, tone |
| Airtable field | `Visual Profile` | `Script Profile` |
| Env var | `VISUAL_PROFILE` | `SCRIPT_PROFILE` |
| Default | `holographic_hud` | `power_doctrine_v2` |
| StoryEngine | "Pick your look" | "Pick your voice" |

## Backward Compatibility

When no profile is provided, the pipeline falls back to the hardcoded
constants in `script_generator.py` and the static `prompts/script.txt`
template. All existing behavior is preserved.
