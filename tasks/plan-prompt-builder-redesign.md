# Prompt Builder Redesign: From Mechanical to Intelligent

## Problem Statement

The V2 prompt builder (`build_prompt_from_block`) is mechanical string concatenation.
It ignores 90% of the profile intelligence that exists in `cinematic_illustration.py`.
The result: every prompt follows the same rigid 7-section template regardless of
content type, and visual descriptions are raw narration excerpts instead of
cinematically-directed image descriptions.

## What Exists But Is Ignored

| Profile Data | Lines | Currently Used? |
|---|---|---|
| 5 substyle suffixes (power_move, lone_figure, etc.) | 100-169 | NO — only sequencer uses them for analytics |
| Scene description system prompt (300+ lines) | 329-430 | NO — only V1 path uses it |
| Metaphor translation table (11 patterns) | 431-444 | NO |
| Character archetypes with expressions | 248-304 | NO — costume comes from Story Bible instead |
| Composition affinity per substyle | 745-751 | NO |
| Lighting vocabulary (5 moods) | 723-729 | NO |
| Material vocabulary (5 categories) | 694-716 | NO |
| Camera angle meanings | 761-767 | NO |
| Negative prompt suffix | 315-318 | NO |
| Text-in-image rules | 446-449 | NO |

## Architecture: What Changes

### Current Flow (Dumb)
```
Story Bible image → scene_expander (pass-through) → prompt_builder (string concat)
                                                      ↓
                                              [PREFIX] Setting: X. Lighting: Y.
                                              Scene: {narration_excerpt}. Characters: {costume dump}.
                                              Camera: {angle}. Mood: {mood}. [SUFFIX]
```

### New Flow (Smart)
```
Story Bible image → scene_expander (pass-through + scene type detection) →
                    prompt_builder (profile-driven assembly)
                      ↓
                    1. Detect scene type from content (power_move/lone_figure/etc.)
                    2. Get substyle suffix from profile
                    3. Merge Story Bible action into Scene content (not Camera)
                    4. Integrate character costume + expression + action
                    5. Apply composition affinity from profile
                    6. Check metaphor table for abstract language
                    7. Apply negative prompt suffix from profile
                    8. Respect prompt word budget from profile
```

## Files Changed

1. `image_prompt_engine/prompt_builder.py` — `build_prompt_from_block()` rewrite
2. `brief_translator/scene_expander.py` — pass scene_type from sequencer to concept

## Detailed Changes

### 1. prompt_builder.py: `build_prompt_from_block()`

**Scene Type Detection**: Use the already-existing `_detect_scene_type()` to classify
the concept. This function already detects power_move, lone_figure, environment,
data_hud, object_closeup from content keywords. Currently its result is only logged.
Now it drives prompt assembly.

**Substyle Suffix**: Each scene type has a specific suffix in the profile:
- `power_move`: "two or more illustrated characters in tension, one dominant..."
- `lone_figure`: "single illustrated character in a moment of weight..."
- `environment`: "cinematic wide shot, no/tiny characters..."
- `data_hud`: "dark operations room, projected display with data..."
- `object_closeup`: "cinematic close-up of physical object, shallow depth of field..."

These REPLACE the current one-size-fits-all approach.

**Action Integration**: The Story Bible `action` field describes what happens in this
specific image ("Three aircraft carriers in formation crossing the strait"). This is
SCENE CONTENT, not camera direction. Merge it into the Scene section alongside
narration_excerpt, not into Camera.

**Character Integration**: For each character present:
1. Look up costume from Story Bible (already done)
2. Look up expression from profile archetypes (NEW — match character_id to archetype)
3. Integrate with action: "iranian leader in dark robes, intense gaze, addressing parliament"

**Metaphor Check**: Scan visual_description for metaphor keywords from profile's
`metaphor_translation_table`. If found, append the translation hint to guide
the image generator away from literal interpretation.

**Negative Prompt**: Append profile's `negative_prompt_suffix` to prevent style drift.

**Word Budget**: Check final prompt length against profile's `prompt_min_words` (62)
and `prompt_max_words` (120). Trim or pad if needed.

### 2. scene_expander.py: Pass scene_type to concept

The sequencer already assigns a `display_format` (= scene type) to each image index.
This gets passed from `run_styled_image_prompts()` in pipeline.py but is NOT included
in the concept dict from scene_expander. Need to pass it through so prompt_builder
can use it as a hint (not override — content detection takes priority).

## Example: Before vs After

### Before (current output)
```
Cinematic animated illustration in muted earthy color palette with ink outlines
and dramatic lighting. Setting: Vast expanse of dark blue Persian Gulf waters
under harsh midday sun, distant hazy coastline visible on horizon. Lighting:
intense overhead sunlight creating sharp highlights on water surface. Scene:
three American aircraft carriers representing over $30 billion in assets.
Camera: Wide establishing shot. Mood: tense., stylized 2D animation aesthetic
with visible ink outlines, muted film grain texture, 16:9 cinematic composition
```

### After (redesigned)
```
Cinematic animated illustration in muted earthy color palette with ink outlines
and dramatic lighting. Vast dark blue Persian Gulf waters under harsh midday sun,
distant hazy coastline on horizon, three American aircraft carriers in formation
cutting through calm sea, massive gray hulls with deck crews as tiny specks,
$30 billion in floating steel. Intense overhead sunlight, sharp highlights on
water surface, deep shadows on wave troughs. Wide establishing shot, cinematic
wide shot, no characters or tiny distant figures only, dramatic natural lighting,
geography and atmosphere establish context, muted earthy palette, stylized 2D
animation aesthetic with visible ink outlines, muted film grain texture, 16:9
cinematic composition. No 3D render, no mannequin, no photorealistic skin.
```

Key differences:
- No rigid "Setting: / Lighting: / Scene: / Camera:" labels
- Story Bible action merged into scene content (carriers in formation)
- Substyle suffix applied (environment: "cinematic wide shot, no characters...")
- Negative prompt appended
- Reads as a cinematic image description, not a form

## Cost Impact
Zero. No new API calls. All intelligence comes from profile data already loaded.

## Risk
- Tests may need updating for new prompt format (no more "Scene:" label assertions)
- Must verify prompt word count stays in 62-120 range
- Must verify all 5 scene types produce distinct prompts
