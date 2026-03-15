# Lessons Learned

> Review this file at the start of every session. These are hard-won patterns.

## Patterns & Anti-Patterns

### Airtable
- **NEVER** join tables by string matching if you can use record IDs. The current schema uses `Title` = `Video Title` string joins. This is fragile. Don't make it worse.
- **ALWAYS** update ALL relevant status fields on the Images table (`Status`, `Video Status`, `Animation Status`). Missing one causes records to get stuck.
- Thumbnail attachment format is inconsistent. The code tries 3 fallback formats. If adding new attachment fields, use `[{"url": "..."}]` format consistently.

### Pipeline
- **NEVER** skip a status in the pipeline flow. Each status gates the next stage's data.
- **ALWAYS** test changes on a single Airtable record before running against the full queue.
- The pipeline runs on cron (8 AM Pacific). Code pushed to `main` auto-deploys via `git pull --ff-only`. Don't push broken code.
- Whisper transcription is imperfect. The audio alignment system has 3 fallback strategies for a reason. Don't remove fallbacks thinking they're dead code.

### API Costs
- Image generation: $0.025/image, 120 per video = $3.00
- Video clips: $0.30/clip, 20-40 per video = $6-12
- A careless loop without guards can burn $50+ in minutes
- Always add `--dry-run` support when building new bot stages

### Remotion
- Scene.tsx is ~450 lines and handles audio sync, karaoke, Ken Burns, crossfades. Be surgical.
- The 4GB swap file is required on the 8GB VPS. Without it, rendering OOMs silently.
- `segmentData.ts` is generated and gitignored. Don't try to commit it.

### Infrastructure
- The Slack bot process dies occasionally. Healthcheck restarts it every 15 min.
- All VPS logs go to `/tmp/pipeline-*.log`. Reference these when debugging production.
- `cleanup_whisper.sh` removed local PyTorch/Whisper (saved 2GB). We use the Whisper API now. Don't re-add `openai-whisper` to requirements.txt.

### Visual Profiles & Sequencing
- **Two separate visual systems exist**: The holographic sequencer (`image_prompt_engine/sequencer.py`) and profile-based substyles (`visual_profiles/*.py`) are completely independent. When adding a new profile, you must wire it into the pipeline — the profile file alone does nothing.
- **`assign_styles()` is holographic-only.** It returns `display_format` values like `war_table`, `wall_display`, `floating`. For non-holographic profiles, use `assign_profile_styles()` which reads substyles from the profile.
- **`build_prompt()` has two paths**: holographic (framing + content + mood + suffix) and profile (prefix + content + substyle suffix + global suffix). The `display_format` parameter carries the substyle key (e.g., `power_move`) for profiles — make sure it matches a key in `profile.style_system.substyles`.
- **Shot Type field in Airtable** gets written from `display_format`/`composition` in the pipeline. When mannequin_storytelling is active, values should be `power_move`, `lone_figure`, `environment`, `data_hud`, `object_closeup` — NOT holographic types.
- **Profile detection pattern**: `load_profile()` reads `VISUAL_PROFILE` env var (set by `_load_idea()` from Airtable's `Visual Style` field). Check `profile.profile_id != "holographic_hud"` to branch.

### Filtering & Partial Generation
- **`image_filter` vs `scene_filter`**: Both are set on the `VideoPipeline` instance. `scene_filter` filters which scenes to process; `image_filter` filters which image/concept index within a scene. Both must be explicitly checked — they are NOT automatically applied.
- **`_filter_by_scene()` exists but isn't universal.** It correctly handles both filters for _existing_ Airtable records (images bot uses it). But `run_styled_image_prompts()` generates new records from scratch — it doesn't have existing records to filter, so you must filter the `concepts` list directly by `concept_index`.
- **When adding filtering to any pipeline function**: Check both `scene_filter` AND `image_filter`. The pattern of only checking `scene_filter` and forgetting `image_filter` has happened before and will happen again.
- **Concept index = image index within a scene.** The `concept_index` field on expanded concepts corresponds to `image_filter`. The `Image Index` field in Airtable corresponds to `image_filter` for existing records.
- **Resume logic must be aware of targeted vs full runs.** The scene-skip logic (`if scene_num in existing_scenes: continue`) blocks targeted regeneration. For targeted runs (`image_filter` set), only skip if the SPECIFIC image index already exists — not if the scene has ANY images.
- **Audio sync should only run on full generation.** It divides scene audio across ALL images in that scene. Running it after generating 1 image assigns the entire scene duration to that single image (e.g., 108 seconds). Skip audio sync for targeted runs (`_is_targeted_run`).

### Wiring Audit Failures (Recurring Pattern)
- **Building a module ≠ wiring it in.** The mannequin_storytelling profile was a complete, beautiful 793-line file with substyles, composition affinity, Ken Burns mapping, character archetypes — and it was completely ignored by the pipeline because nobody wired the sequencer to use it.
- **The sequencer is the chokepoint.** All image prompt generation flows through `assign_styles()` → `build_prompt()`. If the sequencer doesn't know about your profile, your profile is dead code.
- **Always trace the full call chain**: Slack command → `pipeline_control.py` → `run_*.py` script → `pipeline.py` method → bot/engine. A break at any point means the feature doesn't work.

### Script Validation (Blocking Flow)
- **Validation is now BLOCKING.** Scripts must pass all 7 checks before advancing to "Ready For Voice". This is enforced in `BriefTranslator.translate()`.
- **7 validation checks**: number_density, framework_density, personal_stakes, actionable_close, cliffhanger_presence, promise_payoff, act_coherence.
- **Senior editor gets ONE pass.** If validation fails → senior_editor() fixes → re-validate. If still failing → pipeline BLOCKED, status set to "Needs Script Review", Slack notification sent.
- **Promise-payoff tracking**: Forward references like "what Part 3 reveals" must have matching content in the referenced act. Use `_extract_promises()` and `_check_promise_payoff()`.
- **Act coherence**: Each act should have max 6 distinct topic shifts (threshold raised from 3 for geopolitics content). Topic drift is detected by tracking proper nouns and domain terms across paragraphs, with geopolitical clustering (Iran/Iranian/Tehran/Hormuz = 1 topic cluster).
- **To force advance a blocked script**: Use `!approve <title>` command in Slack (requires manual review first).
- **Scripts must ALWAYS be saved before validation.** Progressive writes: save to Airtable AND Google Drive immediately after generation, BEFORE running validation. If validation blocks or crashes, the script is still accessible for review. Never lose generated content.
- **act_coherence threshold must account for geopolitics.** Multiple countries/leaders per act is normal in geopolitics content, not topic drift. Related terms (Iran, Iranian, Tehran, Persian Gulf) are normalized to a single cluster before drift detection.
- **act_coherence is ADVISORY, not blocking.** As of 2026-03-14, act_coherence failures show as WARN in validation summary but don't block the pipeline. Geopolitics scripts naturally reference many entities per act; the senior editor can't reliably fix topic drift without restructuring entire acts. The warning is still logged for manual review.
- **New validator checks need matching config flags.** When adding a new check to `validate_script_editorial()`, add a corresponding `*_check: bool = True` flag to `ScriptValidationConfig` or the "disable all checks" test will fail. Test fixtures must also be updated — cliffhangers in `_make_good_script()` must use keywords that actually appear in subsequent acts.
- **System prompt ordering matters.** Voice/tone rules (like `_CINEMATIC_VOICE_RULES`) must come EARLY in the assembled system prompt — right after role identity, BEFORE structural rules. Claude prioritizes early instructions; rules appended at the end get deprioritized. Assembly order: (1) Role identity/preamble, (2) Voice/style rules, (3) Research brief, (4) Structural rules, (5) Act-specific rules, (6) Grounding rules.

## Project-Specific Rules

1. **Async everywhere.** All bots, all clients, all pipeline code uses async Python. Don't introduce sync blocking calls.
2. **httpx, not requests.** The project uses `httpx` for async HTTP. Don't add `requests`.
3. **6 images per scene, 20 scenes per video.** This is the standard. Changes to this ratio cascade through the entire pipeline.
4. **Visual style system is profile-driven.** Holographic HUD uses Dossier/Schema/Echo. Cinematic Illustration (default) uses power_move/lone_figure/environment/data_hud/object_closeup with illustrated characters. The sequencer must match the active profile.
5. **Max consecutive same-type constraint varies by profile.** Holographic: 4 max. Mannequin: 3 max. Read from `profile.rotation.max_consecutive_same_content_type`.
6. **ElevenLabs voice ID is configured, not hardcoded.** Use `ELEVENLABS_VOICE_ID` from .env.
7. **Google Drive is the media store.** Images, audio, and video go to Drive. Don't store large files locally on the VPS.
8. **When adding CLI args to a pipeline function**, make sure EVERY code path that calls it actually passes and uses those args. The `image_filter` arg was parsed correctly in 3 places but never used in the function that mattered.

### Image Prompt Pipeline Patterns
- **Character prefix is conditional.** Only scenes with CHARACTER indicators (seated, walking, wearing, etc.) get the character prefix. Data displays, environments, objects, and maps do NOT get the prefix. Use `_is_non_character_scene()` to check first.
- **Non-character scene types**: holographic display, data visualization, charts, factory floor, military base, aerial view, satellite view, map overlays — these should NEVER have character prefix regardless of any keywords.
- **Regeneration needs context.** When regenerating a prompt for consecutive_location or consecutive_data violations, pass the SURROUNDING locations/types (indices i-2, i-1, i+1, i+2) so Claude doesn't regenerate with a conflicting neighbor.
- **Equipment integrity default.** Drones, weapons, vehicles default to "fully assembled" unless the narration explicitly mentions wreckage/damage. Remove "detached", "disassembled" language from non-damage scenes.

### Visual Style System (Cinematic Illustration)
- **Default style changed from mannequin to cinematic illustration (2026-03-14).** New style: "Cinematic animated illustration in muted earthy color palette with ink outlines and dramatic lighting. Stylized illustrated characters with expressive faces."
- **Two prefixes now exist**: `_CHARACTER_PREFIX` (for scenes with characters) and `_ENVIRONMENT_PREFIX` (for data/environment/object scenes). Both share `_UNIVERSAL_SUFFIX`.
- **Backwards compatibility via alias REMOVED (2026-03-14).** The `mannequin_storytelling` alias and profile file were deleted. Only `clay_mannequin` remains as a separate valid style.
- **Mannequin validation removed.** The prompt_validator no longer checks for naked mannequins or mannequin hands — these checks were style-specific. Style-agnostic checks remain: camera_distance, consecutive_location, consecutive_data.
- **Profile detection changed.** Pipeline uses `uses_story_bible` (any profile except holographic_hud) instead of `is_mannequin_profile`. This is more accurate now that mannequin style is deprecated.
- **Legacy code remnants cause phantom failures.** After ANY style/profile swap, do a full codebase grep to catch stragglers. Dead type hints, comments referencing removed values, and deprecated aliases will confuse validators and cause false positives. Run: `grep -rn "old_style_name" skills/video-pipeline/ --include="*.py"`

### Scene Blocking System (Story Bible V2)
- **Two Story Bible formats exist**: V1 (`visual_arc`) and V2 (`scene_blocks`). Use `has_scene_blocks()` to detect version.
- **Scene blocks group 2-5 images** sharing location + lighting. Only camera angle, action, expression change within a block.
- **First image of every block MUST be wide.** Enforced by validation; auto-fixed if violated.
- **Act boundaries force new blocks.** When narration transitions to a new act, start a new scene block.
- **Global image_index is sequential.** Images numbered 1, 2, 3... across entire video (60-80 total). No per-scene arithmetic.
- **Scene → block mapping via narration text overlap.** Use fuzzy matching on `narration_excerpt` field to find which images belong to a scene.
- **Total images must match VideoConfig.** If VideoConfig says 60 clips, Story Bible must output exactly 60 images distributed across 12-20 blocks.
- **Block context flows to prompt builder.** Concepts include `block_location`, `block_lighting`, `block_characters` for consistent prompts.
- **Backward compatibility automatic.** Existing V1 Story Bibles (visual_arc) continue to work. New videos use V2 (scene_blocks) by default.

## Session Review Log

_After each session, add a one-line summary of what was done and any new lessons discovered._

| Date | Summary | Lessons Added |
|------|---------|---------------|
| 2026-02-22 | Added CLAUDE.md workflow orchestration + project architecture | Initial lessons seeded from codebase analysis |
| 2026-03-12 | Fixed image_filter ignored in prompt gen + wired mannequin_storytelling scene types into sequencer | Visual profiles wiring, filtering gotchas, profile-aware sequencing pattern |
| 2026-03-12 | Fixed resume logic blocking targeted runs + skip audio sync for partial generation | Targeted vs full run resume logic, audio sync scope |
| 2026-03-14 | Added blocking script validation: promise-payoff tracking, act coherence, senior editor pass | Script validation blocking flow, 7 validation checks |
| 2026-03-14 | Image prompt pipeline fixes: conditional mannequin prefix, context-aware regeneration, MANDATORY rules first, equipment integrity | Image prompt pipeline patterns |
| 2026-03-14 | Visual style overhaul: replaced mannequin with cinematic illustration (312 tests passing) | Visual style system patterns, backwards compat alias |
| 2026-03-14 | Added cinematic voice rules to script writer: scene-driven openings, active framing, film-style transitions | Voice/style additions go in system prompt constants, wire into both profile and legacy paths |
| 2026-03-14 | Implemented Scene Blocking System (Story Bible V2): scene_blocks format, block-aware expansion, prompt builder | Scene blocks patterns, V1/V2 backward compat, narration text matching |
| 2026-03-14 | Removed legacy mannequin_storytelling code remnants: deleted profile file, removed alias, cleaned type hints/comments | Legacy code remnants cause phantom validation failures — always grep after style swap |
| 2026-03-14 | Hotfix: progressive writes before validation + act_coherence threshold to 6 + geopolitical clustering | Scripts must ALWAYS be saved before validation; geopolitics needs higher topic threshold |
| 2026-03-14 | Research agent narrative fields: shared extraction via narrative_extractor.py, wired into all 3 entry points | Shared utilities in clients/ folder; all entry points must use the same extraction logic |
| 2026-03-14 | Fix 3 pipeline issues: cinematic voice prompt position, act_coherence advisory, verified progressive writes | System prompt ordering matters; advisory checks for unreliable fixes; progressive writes already worked |
