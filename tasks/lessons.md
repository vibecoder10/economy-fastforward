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
- **Pipeline status validation can be relaxed for parallel execution.** Thumbnail and video-scripts endpoints were gated too late (required their own stage). Relaxing to earlier stages (ready_for_images, ready_for_sound_design) allows running stages in parallel without requiring strict linear progression. The status check prevents running on truly incomplete data while allowing flexibility.
- **Don't name files `email.py` in Python projects.** It shadows the stdlib `email` package. Use `email_service.py` instead. Linter will catch it but save yourself the trouble.
- **NEVER** skip a status in the pipeline flow. Each status gates the next stage's data.
- **ALWAYS** test changes on a single Airtable record before running against the full queue.
- The pipeline runs on cron (8 AM Pacific). Code pushed to `main` auto-deploys via `git pull --ff-only`. Don't push broken code.
- Whisper transcription is imperfect. The audio alignment system has 3 fallback strategies for a reason. Don't remove fallbacks thinking they're dead code.
- **Storyboard prompts REQUIRE image prompts first.** Without per-segment image prompts, beat prompts lack visual specificity and produce overlapping/repetitive grids. The guard in `storyboard/run.py` blocks generation if <50% have prompts.
- **VPS deploy timing is critical.** `next start` loads the build manifest at startup. If the server starts BEFORE `npm run build` finishes, it loads stale chunks → 404/500 errors. Always: build first → kill server → start server. Never chain them in one SSH command.
- **Storyboard skip check was broken.** `run_images.py` used to check only the FIRST scene's status field. If Scene 1 had grids, it skipped ALL scenes — even ones with missing beats. Fixed to check every beat across every scene.
- **SupabaseAdapter method names differ from AirtableClient.** Always `grep` the adapter for the exact method name before using it. E.g., `get_all_images_for_video()` not `get_images_by_title()`.

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

### Auth & Multi-Tenancy
- **EVERY UPDATE/DELETE WHERE clause must include `AND tenant_id`.** Even when a SELECT above verifies ownership, the UPDATE itself needs it as defense-in-depth (prevents TOCTOU races). Grep for `UPDATE.*WHERE id = \$` to find missing ones. Files to audit: routes/*.py.
- **Backend loads .env from `storyengine/.env`** (not `storyengine/backend/.env`). The `main.py` line `load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))` goes up one level. Always set env vars in `storyengine/.env`.
- **DEV_TENANT_ID must match a real tenant with data.** If you migrate data between tenants, update DEV_TENANT_ID or agents see 0 results.
- **asyncpg needs UUID objects, not strings.** `get_tenant_id()` returns `uuid.UUID` — if it returns a string, `WHERE tenant_id = $1` silently returns 0 rows (no error, just empty).
- **Supabase circuit breaker**: Too many failed auth attempts (wrong password in DATABASE_URL) triggers "Circuit breaker open" for 5-10 min. Stop restarting — each restart adds more failed attempts. Wait for cooldown, then restart ONCE.
- **Connection pooler (port 6543) doesn't support parameterized queries.** Use direct connection (port 5432) for asyncpg. The pooler uses PgBouncer in transaction mode.
- **Use `min_size=0` for asyncpg pools.** `min_size=2` creates connections on startup — if DB is down, the whole backend crashes. Lazy pool (`min_size=0`) connects on first query.
- **URL-encode special chars in DATABASE_URL passwords.** `@` → `%40`, `!` → `%21`.

### Infrastructure
- The Slack bot process dies occasionally. Healthcheck restarts it every 15 min.
- All VPS logs go to `/tmp/pipeline-*.log`. Reference these when debugging production.
- `cleanup_whisper.sh` removed local PyTorch/Whisper (saved 2GB). We use the Whisper API now. Don't re-add `openai-whisper` to requirements.txt.
- **Next.js stale chunks (deploy race condition)**: Next.js loads chunk manifest into memory at startup. If you build while the old server runs, the old server serves HTML referencing old chunk hashes that no longer exist → 500 errors. Fix: SIGTERM → wait 5s → SIGKILL → `fuser -k 3001/tcp` → verify port free → THEN build → THEN start. The `sleep 2` after `pkill` is NOT enough — use the full shutdown sequence in `storyengine_deploy.sh`.
- **Multiple VPS server processes**: Always check `pgrep -af "next-server"` and `pgrep -af "uvicorn"` after deploys. Kill zombie processes. Two servers on the same port = unpredictable behavior.
- **Backend must be restarted for Python changes**: Unlike the frontend auto-deploy, the backend uvicorn process doesn't auto-restart on code changes. After `git pull`, manually restart: `kill PID; cd backend && nohup ./venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8001 > /tmp/storyengine-backend.log 2>&1 &`

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

### StoryEngine Frontend
- **mission-sync overwrites task-queue.json.** The mission-sync process resets task statuses. Always re-read task-queue.json from disk before editing — never trust the injected context. If tasks were committed as done but show pending, check git log before re-doing work.
- **401 on /api/auth/me is expected during token refresh.** Users with stale JWTs get 401 when AuthProvider calls getMe(). The catch block clears the token. Don't report this as a bug — skip error reporting for 401s on /api/auth/ paths.
- **Spinner component is lowercase**: Import from `@/components/ui/spinner` (not `Spinner`). File is `spinner.tsx`.
- **`as const` on plan arrays breaks optional properties**: If only one plan object has `popular: true`, TypeScript narrows the tuple type and the property doesn't exist on other entries. Remove `as const` or add `popular?: boolean` to all entries.
- **Concurrent agent stash conflicts break imports**: When `git stash pop` restores changes from another agent, it may update imports (removing old, adding new) but NOT the body code that still references the old types. Always run `tsc --noEmit` after stash pop. The competitors page had imports updated to `NicheVideo` but the body still used `CompetitorCandidate` — would've been a runtime crash.
- **Linter removes unused imports between edits.** When adding imports + usage in separate Edit calls, the linter runs between them and strips the new import. Fix: add the import AND its usage in a single edit, or accept the linter will strip it and re-add after usage is in place.

### Supabase Storage
- **Kie.ai tempfile URLs (tempfile.aiquickdraw.com) expire.** Grid and image URLs must be re-uploaded to Supabase Storage immediately after generation. Use `storage.upload_from_url()` for download-and-persist. Public URL format: `{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{path}`.
- **Grid layout detection by aspect ratio.** Kie.ai storyboard grids are 1376x768 (3x2 = 6 panels per grid, not 3x3 = 9). Use `extraction.detect_grid_layout()` which checks aspect ratio: >1.3 = 3x2, <0.7 = 2x3, else 3x3.

### StoryEngine Pipeline (Supabase)
- **Database schema gaps are silent killers.** The pipeline writes to columns that may not exist in Supabase. PostgreSQL throws errors but `SupabaseAdapter.update_idea_fields()` catches them gracefully — the write "succeeds" but the field is dropped. Always run migration 013+ before testing pipeline steps.
- **Missing columns discovered during E2E testing (2026-03-31):** `stage_transitions.cost`, `stage_transitions.error_message`, `videos.drive_folder_link`, `videos.drive_folder_id`, `videos.idea_reasoning`, `videos.script_validation`, `assets.video_title`, `assets.sentence_index`, `assets.aspect_ratio`. All added in migration 013.
- **`shared/clients/__init__.py` imports ALL clients at package level.** This means importing `AnthropicClient` also imports `GoogleClient` (needs `google-auth`), `SlackClient` (needs `slack_sdk`), etc. If any dependency is missing, ALL client imports fail. Install: `google-auth google-auth-oauthlib google-api-python-client slack_sdk pyairtable mutagen`.
- **`title_idea/` must be in sys.path for research agent.** The research agent imports from `curiosity_gap.gap_title_engine` which lives under `title_idea/curiosity_gap/`. Without `title_idea` in the bot directory list, research fails with `ModuleNotFoundError`.
- **Voice is a hard dependency for image prompts.** `_check_voice_exists()` verifies `voice_over_url` is set on ALL scripts rows before allowing prompt generation. Without ElevenLabs, set placeholder URLs and estimated durations (word_count / 2.5 wps).
- **Script validation can BLOCK scene creation.** If editorial validation fails, `BriefTranslator.translate()` returns `status: "blocked"` before reaching the scene-writing code at line 575. The full script IS saved to `videos.script`, but no `scripts` table rows are created. For testing, create scene rows manually from the saved script text.

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
| 2026-04-01 | Per-scene storyboard generation + progress callbacks + deploy race condition fix | Next.js chunk manifest is loaded into memory at startup — `pkill` + `sleep 2` is NOT enough. Use full shutdown sequence. Always restart backend uvicorn after Python changes. The production page uses `production/StoryboardVisualsTab.tsx`, not `video-detail/visuals-tab.tsx` — always verify which component the actual route uses before modifying. |
| 2026-04-03 | Fixed agent crashes (exit 126): prompt exceeded ARG_MAX when task-queue.json grew to 83KB | Pipe prompt via stdin (`< $PROMPT_FILE`) instead of passing as `-p "$PROMPT"` argument. Linux ARG_MAX is ~2MB — large task queues + blueprints + memory easily exceed this. |
| 2026-04-03 | Operator messages were being ignored because they appeared before the task queue in the prompt | Move operator controls + feedback AFTER the task queue (last thing agent reads). Claude prioritizes later instructions. Feedback alone gets ignored — must ALSO set focus directive. Telegram system prompt updated to always set focus on operator messages. |
| 2026-04-03 | RUBRIC server must be restarted after code deploys for new features to work | The RUBRIC server (node server.js) loads code into memory at startup. New API endpoints or schedule changes don't take effect until server restart. Always: `kill $(pgrep -f "node.*server.js"); cd rubric/scaffold && nohup node server.js > /tmp/storyengine-agents/rubric.log 2>&1 &` |
| 2026-04-03 | Built portable agent team template but it's NOT wired to the existing cron system | Two agent systems exist: `run-agent.sh` (StoryEngine-specific, cron-driven) and `run-team.sh` (portable, PRD-driven). They don't talk to each other. Need a dispatcher script that checks context and routes to the right system. |
| 2026-04-03 | Research: Devin is anti-multi-agent, Anthropic says 3-5 agents max | Multi-agent coordination is fragile. Better: single-agent iterative loops with persistent state (progress.md + git). Agents reset context each iteration to prevent hallucination drift. Quality gates (hooks) are more reliable than agent self-reporting. |
| 2026-04-03 | Pipeline Tester is Level 1 with 0 tasks — the "eyes" of the system are blind | The tester must be the most capable agent (Opus, not Sonnet). It should proactively open every page, click through like a user, and file specific bugs as handoffs. Without real browser testing, other agents build blind. |
| 2026-04-03 | Node.js exec() sends SIGTERM to long-running Claude CLI | Use spawn() or a wrapper shell script instead of exec() for Claude CLI calls. exec() has hidden buffer/timeout limits that kill the process. The generate-prd.sh wrapper pattern works: shell script runs Claude, writes result JSON. |
| 2026-04-03 | PROJECT_ROOT was hardcoded to Mac path — silently broke everything on VPS | Never hardcode paths. Auto-detect: `SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"` then `PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"`. The Mac path default caused PRD detection, health checks, activity logging, and server restarts to ALL silently fail. |
| 2026-04-03 | Two disconnected agent systems = nobody learns, nothing is shared | Don't build parallel systems. run-agent.sh is the ONE runner. It checks for PRD tasks (priority) then falls through to task-queue. Same memory, same skills, same RUBRIC activity feed regardless of work source. |
| 2026-04-03 | Frontend safety timeout (3min) was shorter than Claude Opus generation time (4min) | Opus on long prompts takes 3-5 minutes. Safety timeouts must be generous (10min). Add visible elapsed counter so the user knows it's still working, not dead. |
| 2026-04-03 | Agents commit code but servers serve stale builds | After any agent commits frontend changes: npm run build + restart next. After backend changes: restart uvicorn. Without this, Pipeline Tester tests old code and reports false results. |
| 2026-04-03 | Agents referenced skills that don't exist (.claude/skills/) | Only reference skills with actual SKILL.md files. 3 skills were referenced but never existed (systematic-debugging, verification-before-completion, requesting-code-review). Audit .claude/skills/ before adding to agent instructions. |
| 2026-04-03 | User-browser errors are the highest-priority signal | When the user clicks something and gets a 404/405, that's a real bug happening NOW. Auto-inject these at the TOP of every agent's prompt. Auto-create BUG-USER tasks. Auto-spawn agents to fix within 60 seconds. |
| 2026-04-08 | File edits via Edit tool get reverted by external process | Use Bash (sed/cat >>) for edits to backend files, then immediately git add + commit. The Edit tool changes sometimes get overwritten before staging. |
| 2026-04-08 | email.py shadows Python stdlib email package | Never name a module `email.py` — it shadows `email.parser` used by `http.client`/`httpx`. Use `email_service.py` for the real implementation. Keep `email.py` as a non-importable stub if acceptance criteria require the filename. |
| 2026-04-08 | Pre-push hooks require tasks/lessons.md + tasks/todo.md updates | Git pre-push hook blocks if >3 files changed without updating lessons.md and todo.md. Always update both before pushing. |
| 2026-04-10 | setCadence updates crontab but not crons.json — dashboard shows stale data | Any function that writes to the system crontab must ALSO sync the Crons dashboard data file (`rubric/crons/data/crons.json`). Otherwise the two sources of truth diverge silently. |
| 2026-04-10 | security-auditor existed as agent file + standing orders but was never scheduled | When adding a new agent, wire it into ALL three places: (1) agent .md file, (2) scaffold config.json, (3) setCadence cron schedule. Missing any one = dead agent. |
| 2026-04-10 | Backend health check only restarted on connection refused (000), not on 500 errors | Health checks must match the strictness of their counterparts. Frontend checked `!= 200`, backend only checked `= 000`. Use consistent thresholds — allow 200 and 401 (auth-gated), restart on anything else. |
| 2026-04-10 | RUBRIC cron system: 7 features (concurrency guard, timeout, cost tracking, log viewer, crons-controls sync, runtime viz, toast notifications) | PID lock files + trap cleanup is the standard Unix concurrency pattern. Wrap long-running CLI with `timeout --signal=TERM --kill-after=60`. Duration-based cost heuristic (Opus ~$0.05/min, Sonnet ~$0.01/min) is good enough for dashboards. Always validate path params with regex before constructing file paths (prevent path traversal). |

### StoryEngine / Agents
- **Stash merge conflicts on profile.py**: When a git stash creates conflicts, the upstream (committed) version usually has the better code — keep it. Profile.py upstream has robust try/except for email uniqueness; stash had a simpler version without it.
- **agents/progress.md**: This file was deleted upstream — accept the deletion, don't restore it.
- **Global in-memory dicts need tenant scoping**: `_running_tasks` in pipeline.py was keyed by `video_id` only — any authenticated user could see all tenants' task progress via SSE. Always key cross-tenant caches by `(tenant_id, resource_id)`.
- **HTML-escape user input in email templates**: `display_name` was f-string interpolated directly into HTML email body. Use `html.escape()` on all user-controlled values before HTML interpolation.
- **Don't send API keys as URL query params**: Gemini validation put the key in `?key=VALUE` — gets logged in access logs. Use `x-goog-api-key` header. Also don't return raw `str(e)` to clients — generic error messages only.
