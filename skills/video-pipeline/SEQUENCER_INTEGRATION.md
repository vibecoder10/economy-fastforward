# Sequencer Integration Fix

**Date:** 2026-03-11
**Issue:** All image prompts were identical - "Overhead angled view of a holographic war table..."
**Root Cause:** Parameter mismatch between scene_expander.py output and build_prompt() expectations
**Fix:** Wired image_prompt_engine/sequencer.py into run_styled_image_prompts() for proper rotation

---

## What Changed

### Before (Broken)
```python
# scene_expander.py generated:
visual_style = "dossier"/"schema"/"echo"
composition = "wide"/"medium"/"closeup"

# But build_prompt() expected:
content_type = "geographic_map"/"data_terminal"/etc.
display_format = "war_table"/"wall_display"/etc.

# Result: Everything defaulted to WAR_TABLE
```

### After (Fixed)
```python
# sequencer.py now generates proper style assignments:
style_assignments = assign_styles(total_images=estimated_total_images)

# Each assignment has:
{
    "content_type": "geographic_map",  # 8 types rotate
    "display_format": "war_table",     # 5 formats rotate
    "color_mood": "strategic",         # 6 moods rotate
    "ken_burns": "slow_zoom_in",
}

# build_prompt() gets correct parameters:
prompt = build_prompt(
    scene_description=visual_desc,
    content_type=style["content_type"],
    display_format=style["display_format"],
    color_mood=style["color_mood"],
)
```

---

## Code Changes

**File:** `skills/video-pipeline/pipeline.py`

### 1. Import sequencer (line ~2017)
```python
from image_prompt_engine.sequencer import assign_styles
```

### 2. Generate style assignments BEFORE scene loop (line ~2065)
```python
# Estimate total images: ~7 images per scene average
estimated_total_images = total_scripts * 7
print(f"  Generating style assignments for ~{estimated_total_images} images...")

style_assignments = assign_styles(
    total_images=estimated_total_images,
    seed=hash(self.video_title) % (2**32),  # Deterministic per video
)
```

### 3. Track global image_index (line ~2094)
```python
image_index = 0  # Global counter across all scenes
```

### 4. Use sequencer assignments in prompt generation (line ~2150)
```python
for concept in concepts:
    visual_desc = concept["visual_description"]

    # Get style from sequencer (with bounds check)
    if image_index < len(style_assignments):
        style = style_assignments[image_index]
        content_type = style["content_type"]
        display_format = style["display_format"]
        color_mood = style["color_mood"]
    else:
        # Fallback if we exceed estimate
        content_type = "geographic_map"
        display_format = "war_table"
        color_mood = "strategic"

    # Build styled prompt using sequencer-assigned styles
    prompt = build_prompt(
        scene_description=visual_desc,
        content_type=content_type,
        display_format=display_format,
        color_mood=color_mood,
        image_style_override=image_style_override,
    )

    image_index += 1  # Increment global counter
```

### 5. Updated reporting (line ~2190)
```python
# Report display format distribution instead of old dossier/schema/echo
if style_counts:
    total_styled = sum(style_counts.values())
    print(f"  Display format variety:")
    for fmt, count in sorted(style_counts.items(), key=lambda x: -x[1]):
        pct = count / total_styled * 100
        print(f"    {fmt}: {count} ({pct:.0f}%)")
```

---

## Rotation Rules (Enforced by Sequencer)

| Style Dimension | Rotation Rule | Purpose |
|----------------|---------------|---------|
| **Content Type** (8 types) | Max 2 consecutive same type | Prevents repetitive subject matter |
| **Display Format** (5 formats) | Max 2 consecutive same format | Varies camera angles and framing |
| **Close-Up Detail** | Max 1 consecutive | Prevents tunnel vision - punctuation only |
| **Color Mood** (6 moods) | Max 3 consecutive same palette | Emotional pacing across acts |
| **Ken Burns Motion** | Alternates pans (L↔R) | Prevents directional monotony |

---

## Expected Results

### Display Format Distribution (Typical)
- **War Table** (overhead angled): 30-40% - Geographic maps, networks, satellite
- **Wall Display** (front-facing): 30-40% - Charts, documents, timelines
- **Floating Projection** (mid-air): 10-20% - Object comparisons, concepts
- **Multi-Panel** (split screen): 5-10% - Before/after, parallels
- **Close-Up Detail** (macro focus): 5-10% - Key stats, critical text

### Content Type Variety
All 8 types should appear across a full video:
- Geographic Map, Data Terminal, Object Comparison, Document Display,
- Network Diagram, Timeline, Satellite Recon, Concept Visualization

### Color Mood Pacing
Act-weighted rotation:
- Act 1 (Hook): Strategic (teal/cyan)
- Act 2-4: Alert (red/amber), Archive (gold/sepia), Contagion (green/yellow)
- Act 5-6: Power (purple/magenta), Personal (warm amber)

---

## Testing

### Quick Test (Run on one video)
```bash
cd skills/video-pipeline
python test_prompt_variety.py "Your Video Title Here"
```

Tests verify:
1. ✅ Not all prompts are war_table (variety exists)
2. ✅ At least 3 different display formats appear
3. ✅ Max consecutive same format ≤ 2 (rotation enforced)
4. ✅ At least 3 different content types detected

### Manual Test (Visual inspection)
```bash
# Generate prompts for a new video
python run_image_pipeline.py "Video Title"

# Check Airtable Images table - Image Prompt field should show variety:
# - "Overhead angled view of a holographic war table..." (30-40%)
# - "Front-facing view of a massive holographic wall display..." (30-40%)
# - "Eye-level view of holographic objects floating..." (10-20%)
# - "Wide angle view of multiple holographic display panels..." (5-10%)
# - "Extreme close-up of a holographic display detail..." (5-10%)
```

---

## Commit Message

```
Wire sequencer.py rotation into prompt generation — fix all-war-table repetition bug

Root cause: pipeline.py was passing visual_style ("dossier"/"schema"/"echo")
and composition ("wide"/"medium"/"closeup") to build_prompt(), but build_prompt()
expects content_type ("geographic_map"/etc.) and display_format ("war_table"/etc.).
Everything fell back to WAR_TABLE default.

Fix: Use sequencer.assign_styles() to pre-generate proper ContentType +
DisplayFormat + ColorMood assignments with rotation enforcement. Each image
now gets a unique style combo respecting max consecutive constraints.

Changes:
- Import sequencer.assign_styles() in run_styled_image_prompts()
- Pre-generate style assignments for estimated total images
- Track global image_index counter across all scenes
- Pass content_type, display_format, color_mood to build_prompt()
- Update reporting to show display format distribution

Tests: test_prompt_variety.py verifies 4 rotation rules are enforced.
```

---

## What Was NOT Changed

- ❌ build_prompt() internals (unchanged)
- ❌ style_config.py constants (unchanged)
- ❌ sequencer.py rotation logic (unchanged)
- ❌ Legacy path in anthropic_client.py (deprecated, untouched)
- ❌ Old visual_style/composition code (still exists, just not used)

Clean-up can happen later - this fix is surgical and minimal.

---

## Rollback Instructions

If this breaks something:

```bash
git diff HEAD pipeline.py  # Review changes
git checkout HEAD -- pipeline.py  # Restore previous version
```

The old path still exists in run_image_prompt_bot_legacy() if needed.
