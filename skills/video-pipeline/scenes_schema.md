# Unified Scene JSON Schema

## Overview

The Economy FastForward video pipeline uses a nested scene structure:

```
6 Acts (creative architecture)
  └─ 20-30 Scenes (production units, 3-5 per act)
       └─ ~100-200 Images (derived downstream, 4-7 per scene)
```

## JSON Structure

```json
{
  "total_acts": 6,
  "total_scenes": 25,
  "acts": [
    {
      "act_number": 1,
      "act_title": "The Hook",
      "time_range": "0:00-1:30",
      "word_target": 225,
      "scenes": [
        {
          "scene_number": 1,
          "parent_act": 1,
          "act_marker": "[ACT 1 — The Hook | 0:00-1:30]",
          "narration_text": "Exact text from script for this segment...",
          "duration_seconds": 36,
          "visual_style": "dossier",
          "composition": "wide",
          "ken_burns": "slow zoom in",
          "mood": "tension",
          "description": "A lone figure in a dark suit stands before floor-to-ceiling windows overlooking a city at night, cold teal city lights reflecting on the glass"
        }
      ]
    }
  ]
}
```

## Field Reference

### Act Fields

| Field | Type | Description |
|-------|------|-------------|
| `act_number` | int (1-6) | Sequential act number |
| `act_title` | string | Act name (Hook, Setup, Framework, History, Implications, Lesson) |
| `time_range` | string | Approximate timestamp range |
| `word_target` | int | Target word count for this act |

### Scene Fields

| Field | Type | Description |
|-------|------|-------------|
| `scene_number` | int (1-30) | Sequential scene number across all acts |
| `parent_act` | int (1-6) | Which act this scene belongs to |
| `act_marker` | string | Full act marker string |
| `narration_text` | string | Exact verbatim text from the script |
| `duration_seconds` | int | Duration calculated from word count (÷ 2.5 wps) |
| `visual_style` | enum | `"dossier"` \| `"schema"` \| `"echo"` |
| `composition` | enum | `"wide"` \| `"medium"` \| `"closeup"` \| `"environmental"` \| `"portrait"` \| `"overhead"` \| `"low_angle"` |
| `ken_burns` | enum | `"slow zoom in"` \| `"slow zoom out"` \| `"slow pan left"` \| `"slow pan right"` \| `"slow drift up"` \| `"slow drift down"` |
| `mood` | string | 1-2 word mood descriptor |
| `description` | string | Primary visual concept for AI image generation |

### Backward-Compatibility Aliases

When scenes are flattened (via `flatten_scenes()`), these aliases are added:

| Alias | Maps To |
|-------|---------|
| `act` | `parent_act` |
| `style` | `visual_style` |
| `script_excerpt` | `narration_text` |
| `composition_hint` | `composition` |
| `scene_description` | `description` |

## Visual Style Rules

| Act | Dossier | Schema | Echo |
|-----|---------|--------|------|
| 1 (Hook) | 90% | 10% | 0% |
| 2 (Setup) | 70% | 30% | 0% |
| 3 (Framework) | 45% | 20% | 35% |
| 4 (History) | 35% | 20% | 45% |
| 5 (Implications) | 50% | 35% | 15% |
| 6 (Lesson) | 65% | 35% | 0% |

### Style Constraints

- First scene and last scene: always Dossier
- Echo: only in Acts 3-5, always in clusters of 2-3 (never isolated)
- No more than 4 consecutive scenes of same style
- Ken Burns direction alternates (never same direction twice in a row)

## Downstream Usage

1. **Voice Bot**: Reads `narration_text` from each scene for TTS generation
2. **Image Prompt Engine**: Generates 4-7 styled image prompts per scene based on `duration_seconds`, `visual_style`, `composition`, and `description`
3. **Video Renderer**: Uses scene ordering, `ken_burns` directives, and `duration_seconds` for final composition
