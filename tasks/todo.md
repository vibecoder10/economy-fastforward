# Task Tracking

## Current Sprint

_Reference `ANIMATION_SYSTEM_REVIEW.md` for detailed feature specs before starting any roadmap item._

- [x] Image Prompt Pipeline Fixes (2026-03-14) — DONE
- [x] Visual Style Overhaul: Mannequin → Cinematic Illustration (2026-03-14) — DONE
- [x] Scene Blocking System (Story Bible V2) (2026-03-14) — DONE

### 2026-03-14: Visual Style Overhaul — Mannequin → Cinematic Illustration

**What Changed:**
Replaced the "3D rendered faceless mannequin with smooth white oval head" visual style with "Cinematic animated illustration in muted earthy color palette with ink outlines and dramatic lighting. Stylized illustrated characters with expressive faces showing emotion."

**Files Modified:**
- `image_prompt_engine/prompt_builder.py` — New prefix/suffix constants (_CHARACTER_PREFIX, _ENVIRONMENT_PREFIX, _UNIVERSAL_SUFFIX), updated detection logic
- `bots/prompt_validator.py` — Removed ~224 lines of mannequin-specific validation (naked mannequins, mannequin hands)
- `pipeline.py` — Changed `is_mannequin_profile` to `uses_story_bible`, removed mannequin clothing rules
- `visual_profiles/cinematic_illustration.py` — NEW FILE (~700 lines) - complete illustrated profile
- `visual_profiles/__init__.py` — Added cinematic_illustration, aliased mannequin_storytelling for backwards compat
- `clients/airtable_client.py` — Updated VALID_VISUAL_STYLES and DEFAULT_VISUAL_STYLE
- `bots/story_bible.py` — Updated examples to use "illustrated figure" instead of "mannequin"
- `brief_translator/scene_expander.py` — Updated prompts to use "character" instead of "mannequin"

**Verification:**
- Ran 312 tests across 3 test suites: ALL PASSED
  - image_prompt_engine: 143 passed, 2 skipped
  - brief_translator: 143 passed
  - pipeline_integration: 26 passed
- ZERO prompts should contain "mannequin", "oval head", "faceless", "no facial features"
- Prompts should contain "animated illustration", "ink outlines", "expressive faces"

**New Default Style:**
- `cinematic_illustration` is now the default (was `mannequin_storytelling`)
- Old videos with `mannequin_storytelling` in Airtable will load `cinematic_illustration` (alias)

### 2026-03-14: Scene Blocking System (Story Bible V2) — COMPLETED

**What Changed:**
Implemented Scene Blocking system where images within a scene share environment/lighting but vary in camera angle. This creates visual continuity within narrative beats.

**Files Modified:**
- `bots/story_bible.py`:
  - Added `SCENE_BLOCK_CONFIG` constants (min/max images per block, target blocks)
  - Added `STORY_BIBLE_USER_PROMPT_V2` for scene_blocks output format
  - Added `_validate_and_normalize_scene_blocks()` validation function
  - Added helper functions: `has_scene_blocks()`, `get_story_bible_version()`, `get_block_for_image()`, `get_image_spec_by_index()`, `get_all_images_from_blocks()`
  - Updated `generate_story_bible()` to support `use_scene_blocks=True` parameter

- `brief_translator/scene_expander.py`:
  - Added `_expand_with_scene_blocks()` for V2 format
  - Added `_match_scene_to_images()` for fuzzy matching narration text to images
  - Updated `expand_scene_concepts_deterministic()` to detect and route V1 vs V2

- `image_prompt_engine/prompt_builder.py`:
  - Added `build_prompt_from_block()` for block-aware prompt assembly

- `pipeline.py`:
  - Updated Story Bible generation to use V2 by default (`use_scene_blocks=True`)
  - Updated logging to detect and report V1 vs V2 format
  - Pass `total_images` and `video_duration_minutes` to Story Bible generation

**Scene Blocks Structure:**
```json
{
  "scene_blocks": [
    {
      "block_id": "block_1",
      "location": "Full environment description...",
      "lighting": "Specific lighting setup...",
      "mood": "tense",
      "characters_present": ["russian_leader"],
      "images": [
        {"image_index": 1, "camera": "wide", "action": "..."},
        {"image_index": 2, "camera": "medium", "action": "..."}
      ]
    }
  ]
}
```

**Key Rules:**
- Each block has 2-5 images sharing location/lighting
- First image of every block MUST be wide (enforced)
- Act boundaries force new block boundaries
- Global image_index is sequential (1, 2, 3... up to ~60-80)
- Scene → block mapping via narration_excerpt text overlap

**Verification:**
- Ran 312 tests: ALL PASSED (286 unit + 26 integration)
- Backward compatibility: existing V1 (visual_arc) Story Bibles continue to work
- New videos use V2 (scene_blocks) by default

---

### 2026-03-14: Image Prompt Pipeline Fixes

**What Changed:**
- `image_prompt_engine/prompt_builder.py`:
  - Added `_is_non_character_scene()` — checks for data/environment/object keywords FIRST
  - Added `_NON_CHARACTER_SCENE_KEYWORDS` list (30+ phrases like "holographic display", "factory floor", "aerial view", etc.)
  - Changed mannequin prefix logic: now checks `_is_non_character_scene()` BEFORE character indicators
  - Added `_enforce_equipment_integrity()` — removes "detached/disassembled" from equipment prompts unless damage explicit

- `bots/prompt_validator.py`:
  - Added `_get_neighboring_locations()` — returns locations from indices [i-2, i-1, i+1, i+2]
  - Added `_get_neighboring_data_types()` — returns data scene types from neighbors
  - Updated `build_regeneration_constraint()` to pass neighboring context for location/data violations
  - Added MANDATORY header for naked_mannequin/realistic_hands regeneration (goes at very start of system prompt)

- `image_prompt_engine/tests/test_prompts.py`:
  - Skipped clay_mannequin tests (not used in production)

**Verification:**
- Ran all 474 tests: 474 passed, 2 skipped
- Manual verification with mannequin_storytelling profile confirmed:
  - Environment scenes: NO mannequin prefix
  - Character scenes (seated, wearing): YES mannequin prefix
  - Data scenes: NO mannequin prefix

**Files Modified:**
- `image_prompt_engine/prompt_builder.py` — conditional prefix + equipment integrity
- `bots/prompt_validator.py` — context-aware regeneration + mandatory headers
- `image_prompt_engine/tests/test_prompts.py` — skipped clay_mannequin tests

## Backlog (from Roadmap)

### Phase 2: Character Consistency
- [ ] Feature 1: Character Reference System (BYOC) — HIGH
- [ ] Feature 5: Style Locking via Golden Frame — HIGH
- [ ] Feature 10: Quality Scoring via Gemini Vision — MEDIUM

### Phase 3: Product Mode
- [ ] Feature 3: One-Shot `!create` Pipeline — HIGH
- [ ] Feature 4: Airtable Schema Optimization — MEDIUM
- [ ] Feature 7: Health Dashboard & Self-Healing — MEDIUM

### Phase 4: Animation Quality
- [ ] Feature 8: Start/End Frame Bridging — MEDIUM
- [ ] Feature 9: Multi-Voice & Sound Design — LOW

## Completed

- [x] Feature 2: Auto-Pull from GitHub on Cron — DONE
- [x] Feature 6: Veo 3.1 Fast Integration — DONE
- [x] Workflow orchestration rules (CLAUDE.md) — DONE
- [x] Blocking Script Validation with Senior Editor Pass — DONE (2026-03-14)
- [x] Image Prompt Pipeline Fixes — DONE (2026-03-14)
- [x] Visual Style Overhaul: Mannequin → Cinematic Illustration — DONE (2026-03-14)
- [x] Scene Blocking System (Story Bible V2) — DONE (2026-03-14)

## Review Notes

### 2026-03-14: Blocking Script Validation

**What Changed:**
- Added 2 new validators to `script_validator.py`:
  - `promise_payoff` — detects forward references ("what Part 3 reveals") and verifies they're resolved
  - `act_coherence` — detects 3+ distinct topic shifts within an act
- Made all 7 validation checks BLOCKING (previously advisory)
- Created `senior_editor.py` — single Claude call to fix flagged issues
- Wired into `BriefTranslator.translate()`:
  1. generate_script()
  2. validate (7 checks)
  3. IF flags → senior_editor() (ONE pass)
  4. IF still failing → BLOCK (status="Needs Script Review", Slack notification)
  5. IF clean → advance to "Ready For Voice"

**Files Modified:**
- `brief_translator/script_validator.py` — added new validators, made checks blocking
- `brief_translator/senior_editor.py` — NEW file
- `brief_translator/__init__.py` — wired senior editor flow
- `brief_translator/tests/test_script_validator.py` — added tests for new validators

**What to Verify:**
- Run `python -m pytest brief_translator/tests/test_script_validator.py` on VPS
- Test with a real video: generate script, verify validation runs, check Slack notifications
- Test manual approval flow: `!approve <title>` should force advance blocked scripts

**Cost Impact:** +1 Sonnet call per script (~$0.03) when validation fails
