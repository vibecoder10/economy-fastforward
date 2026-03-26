# Lessons Learned

> Review this file at the start of every session. These are hard-won patterns.

## Patterns & Anti-Patterns

### Airtable
- **NEVER** join tables by string matching if you can use record IDs. The current schema uses `Title` = `Video Title` string joins. This is fragile. Don't make it worse.
- **ALWAYS** update ALL relevant status fields on the Images table (`Status`, `Video Status`, `Animation Status`). Missing one causes records to get stuck.
- Thumbnail attachment format is inconsistent. The code tries 3 fallback formats. If adding new attachment fields, use `[{"url": "..."}]` format consistently.
- **Graceful error handling can be TOO graceful.** The `update_idea_fields()` function silently drops unknown fields to avoid breaking writes. This means if a field doesn't exist in Airtable, the write "succeeds" but nothing is saved. ALWAYS verify critical writes by checking if the field appears in the returned record.
- **Schema documentation ≠ actual Airtable fields.** A field listed in `docs/airtable-schema.md` might not actually exist in Airtable. When adding code that writes to a new field, verify the field exists in Airtable FIRST.
- **REQUIRED before scripting**: `Video Length (min)` and `Script` fields must exist in Idea Concepts table. Without them, script generation fails silently or produces wrong word counts.

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
- **Captions use character-based chunking, not word-count.** At 72px Inter Bold, the 92% width container fits ~38 chars. Chunking by 6 words caused overflow when words were long (e.g., "manufacturing—Bangladesh"). The fix: CaptionsOverlay.tsx chunks by total character count, creating adaptive chunks (short words → more per chunk, long words → fewer). This guarantees no overflow regardless of sentence content.

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
- **"Already working" claims need REAL verification.** Reading code that SHOULD work is not proof it DOES work. Add debug print statements, run the actual code, check Airtable. The `update_idea_fields()` graceful degradation silently drops unknown fields — a "successful" write might have dropped your field entirely.

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

### Prompt Builder Data Paths (4 separate concerns)
- **`visual_description` = narration_excerpt** (Story Bible visual content — what to SHOW). NEVER use verbatim script text here. The 9f0093d commit accidentally set `visual_description` to `verbatim_text`, which put raw narrator dialogue into the Scene field of prompts.
- **`sentence_text` = verbatim script text** (exact words from Script table). Used for Airtable Sentence Text field and duration calculation.
- **Characters = costume + action, integrated.** Don't dump raw costume descriptions. Integrate: "figure in [costume], [action]". The `camera_direction` (Story Bible `action` field) tells you what the character is doing.
- **Duration = word_count / WPS** from sentence_text. The V2 scene blocks path must calculate this the same way deterministic_splitter does (DEFAULT_WPS = 2.5, or voice_duration-based). Missing duration causes downstream clip duration decisions to use wrong defaults.
- **These are FOUR separate data paths. Don't cross them.** A fix to one (e.g., making sentence_text verbatim) must not accidentally change another (e.g., visual_description).

### Scene Blocking System (Story Bible V2)
- **Two Story Bible formats exist**: V1 (`visual_arc`) and V2 (`scene_blocks`). Use `has_scene_blocks()` to detect version.
- **Scene blocks group 2-5 images** sharing location + lighting. Only camera angle, action, expression change within a block.
- **First image of every block MUST be wide.** Enforced by validation; auto-fixed if violated.
- **Act boundaries force new blocks.** When narration transitions to a new act, start a new scene block.
- **Global image_index is sequential.** Images numbered 1, 2, 3... across entire video (60-80 total). No per-scene arithmetic.
- **NEVER use Story Bible narration_excerpt for sentence_text.** The deterministic splitter (`segment_scene_deterministic()`) produces verbatim script segments. Story Bible images provide VISUAL CONTEXT only (location, lighting, characters). The V2 path was rewritten 2026-03-15 to fix cross-scene contamination caused by fuzzy-matching narration_excerpts across all scenes.
- **Story Bible ≠ text splitter.** The Story Bible tells you WHERE and WHO. The deterministic splitter tells you WHAT TEXT each image covers. These are separate concerns. `_find_block_context()` maps segments to blocks by text overlap, but `sentence_text` always comes from the splitter.
- **Pre-filter images to the current scene.** `get_all_images_from_blocks()` returns images from ALL scenes. ALWAYS filter by narration_excerpt text overlap before mapping. Without filtering, fuzzy matching leaks images from neighbouring scenes.
- **Total images must match VideoConfig.** If VideoConfig says 60 clips, Story Bible must output exactly 60 images distributed across 12-20 blocks.
- **Block context flows to prompt builder.** Concepts include `block_location`, `block_lighting`, `block_characters` for consistent prompts.
- **Backward compatibility automatic.** Existing V1 Story Bibles (visual_arc) continue to work. New videos use V2 (scene_blocks) by default.

### Prompt Builder Prefix/Suffix (Profile-Driven)
- **NEVER hardcode style prefix/suffix in prompt_builder.py.** Read `profile.style_system.style_prefix`, `.character_prefix`, `.style_suffix` from the visual profile. The `_CHARACTER_PREFIX`, `_ENVIRONMENT_PREFIX`, `_UNIVERSAL_SUFFIX` module constants are legacy fallbacks ONLY.
- **`character_prefix` is optional on StyleSystemConfig.** Falls back to `style_prefix` when empty. Only cinematic_illustration needs it (adds "expressive faces" language for character scenes).
- **Every time visual system code is touched, check if hardcoded strings snuck back in.** This has happened repeatedly — a new feature uses a constant instead of reading from the profile, breaking all other visual styles.

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
| 2026-03-15 | Fix cross-scene sentence contamination: V2 path now uses deterministic splitter for text + Story Bible for visual context only. Prompt builder prefix/suffix now reads from profile instead of hardcoded constants. | Story Bible ≠ text splitter; pre-filter images to current scene; never hardcode prefix/suffix |
| 2026-03-14 | Debug Script field write + add !approve command for blocked scripts | Wiring audit failed — "already working" claims need ACTUAL verification with debug logs, not code reading |
| 2026-03-14 | Fix Script field missing from Airtable setup — field documented but never created | Documentation ≠ implementation; always check setup scripts match field audit comments |
| 2026-03-15 | Fix 3 prompt builder bugs: Scene uses narration_excerpt, duration from word count, character integration | 4 separate data paths in prompt builder — don't cross them; V2 scene blocks must match V1 deterministic_splitter capabilities |
| 2026-03-15 | Redesigned prompt builder: profile-driven assembly with substyle suffixes, archetype expressions, metaphor table, negative prompts | Profile data is the intelligence — don't hardcode what the profile already defines; action field is scene direction not camera direction |
| 2026-03-17 | Render pipeline loose wires: wired karaoke captions, Ken Burns, transitions from render_config into Scene.tsx. Removed dead EconomyVideoAnimated composition + dependency tree. Fixed test expectation, Tuning constants, removed voice_speed dead field. | Python writes data → render_config.json → TypeScript reads it. If TS ignores a field, the Python computation is wasted. Always trace data flow end-to-end across language boundaries. |
| 2026-03-18 | Wired Story Bible into storyboard bot: characters, locations, visual arc, scene blocks now injected as binding constraints into directive generation | The storyboard bot was a parallel visual system completely disconnected from Story Bible. Two visual systems generating independently = guaranteed inconsistency. Any new visual generation path must consume the Story Bible — it's the single source of truth for character/location appearance. |
| 2026-03-18 | Fixed 3 pipeline issues: (1) Duration validation halts script gen when Video Length not set, (2) Script field write verification + loud failure, (3) Interactive approval flow for blocked scripts | Silent defaults cause downstream disasters — always validate required fields and notify when missing. Graceful error handling can be TOO graceful — `update_idea_fields` silently drops unknown fields. ALWAYS verify writes succeeded. Schema docs ≠ actual Airtable fields — check both. |
| 2026-03-20 | Fixed karaoke caption overflow: replaced 6-word chunks with character-based chunking (max 38 chars). Container at 72px Inter Bold fits ~39 chars but old code allowed 56+ char chunks. | Don't chunk captions by word count — chunk by character count. Long words like "manufacturing—Bangladesh" (56 chars for 6 words) caused 40% overflow. Character-based chunking adapts: short words → more per chunk, long words → fewer. |
| 2026-03-26 | Unblocked Supabase pipeline: LightPipeline, UUID loading, bot subdir sys.path, no-op clients | LightPipeline pattern works for adapter layer. Bot run.py files have internal imports requiring parent dir on sys.path. Adapter must return written fields for verification. VideoConfig param is video_length_minutes not target_minutes. |
