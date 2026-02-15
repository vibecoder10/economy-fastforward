# PIPELINE AUDIT REPORT

**Date:** 2026-02-15
**Auditor:** Claude Code (Opus 4.6)
**Scope:** Economy FastForward video production pipeline

---

## Summary

```
Modules Found:        8
Modules Operational:  7
Breaks Found:         6
Breaks Fixed:         5
Breaks Remaining:     1 (Research Agent — not built, requires separate implementation)
```

---

## Data Flow Status

| Handoff                       | Status   | Notes                                                    |
|-------------------------------|----------|----------------------------------------------------------|
| Research -> Ideas Bank        | Partial  | No research agent module exists yet. IdeaBot/TrendingBot fill this role for URL-based ideas. |
| Ideas Bank -> Translator      | Connected | `run_brief_translator()` maps idea fields to brief dict, calls translator chain. |
| Translator -> Pipeline Table  | Connected | `pipeline_writer.graduate_to_pipeline()` writes all fields including Script, Scene File Path, Accent Color, Video ID. |
| Pipeline -> Image Engine      | Connected | `run_styled_image_prompts()` reads scene JSON, runs through `image_prompt_engine.generate_prompts()`, writes styled prompts to Airtable. |
| Image Engine -> NanoBanana    | Connected | Styled prompts are plain strings ending with `16:9`, stored in Airtable `Image Prompt` field. NanoBanana reads them directly. |
| NanoBanana -> Remotion        | Connected | Images stored in Google Drive. `package_for_remotion()` reads from Airtable, downloads to `public/` folder. |
| Script -> TTS -> Remotion     | Connected | `run_voice_bot()` generates ElevenLabs audio per scene. `run_render_bot()` downloads audio to `public/Scene N.mp3`. |
| Remotion -> YouTube           | Partial  | Renders to Drive. No YouTube upload automation (manual step). |
| Status tracking (Airtable)    | Connected | Full progression: Idea Logged -> Ready For Scripting -> Ready For Voice -> Ready For Image Prompts -> Ready For Images -> Ready For Thumbnail -> Ready To Render -> Done |
| Notifications (Slack)         | Connected | Each bot sends start/complete notifications. |

---

## Breaks Found & Fixed

### Fixed

1. **Status mismatch in run_image_bot / run_visuals_pipeline** (Category C)
   - **Problem:** Status set to `READY_THUMBNAIL` but log printed `READY_VIDEO_SCRIPTS`
   - **Fix:** Aligned both the status update and log message to `READY_THUMBNAIL`
   - **File:** `pipeline.py` lines ~1065 and ~1113

2. **Scene output directory hardcoded to VPS path** (Category D)
   - **Problem:** `DEFAULT_SCENE_DIR = "/home/bot/pipeline/scenes"` — doesn't exist
   - **Fix:** Changed to project-relative `Path(__file__).parent.parent / "scenes"`
   - **File:** `brief_translator/pipeline_writer.py`

3. **brief_translator disconnected from pipeline** (Category A)
   - **Problem:** Module existed with full validation/script/scene capabilities but was never called
   - **Fix:** Added `run_brief_translator()` method to `VideoPipeline` class + `--translate` CLI command
   - **File:** `pipeline.py` (new method added)

4. **image_prompt_engine disconnected from pipeline** (Category A)
   - **Problem:** Visual identity system (Dossier/Schema/Echo, Ken Burns, compositions) existed with 77 passing tests but was never wired into the production pipeline
   - **Fix:** Added `run_styled_image_prompts()` method that reads scene JSON, generates styled prompts, writes to Airtable + `--styled-prompts` CLI command
   - **File:** `pipeline.py` (new method added)

5. **No orchestrator execution modes** (Category B)
   - **Problem:** Pipeline only supported status-driven step execution or URL-based idea generation
   - **Fix:** Added three execution modes:
     - `--full "URL"` — End-to-end: Idea -> Script -> Voice -> Images -> Render
     - `--produce [id]` — Pick queued idea and produce to completion
     - `--from-stage X` — Resume from any stage (scripting, voice, images, etc.)
   - **File:** `pipeline.py` (new methods + CLI commands)

### Remaining

6. **No Research Agent** (Category B)
   - **Problem:** The playbook references a 7-prompt research cycle agent that produces structured briefs with 11 fields (headline, thesis, executive_hook, fact_sheet, historical_parallels, etc.). No such module exists.
   - **Impact:** The brief_translator can accept these briefs, but nothing produces them. Current workaround: IdeaBot/TrendingBot produce simpler idea records that map to brief fields with some gaps.
   - **Recommendation:** Build the research agent as a separate module. The brief_translator integration is ready to consume its output.

7. **No YouTube upload automation** (Category B)
   - **Problem:** Pipeline renders video and uploads to Google Drive, but YouTube upload is manual.
   - **Impact:** Low — final step can remain manual for now.

---

## API Status

| API                     | Status             | Provider     |
|-------------------------|--------------------|--------------|
| Anthropic (Claude)      | Configured         | Claude 3.5   |
| Airtable                | Configured         | pyairtable   |
| Web Search              | Not configured     | —            |
| Image Generation        | Configured         | Kie.ai (Seed Dream 4.0) |
| TTS                     | Configured         | ElevenLabs   |
| YouTube                 | Not automated      | —            |
| Slack                   | Configured         | slack_sdk    |
| Google Drive            | Configured         | Google API   |
| Gemini Vision           | Configured         | Gemini 2.0   |

---

## Test Results

```
image_prompt_engine:      77 tests passing
brief_translator:         67 tests passing
integration (new):        26 tests passing
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TOTAL:                   170 / 170 passing
```

---

## New Integration Tests Added

| Test | Verifies |
|------|----------|
| `test_brief_has_required_validation_fields` | Research output has all fields validator expects |
| `test_brief_has_required_script_generator_fields` | Brief has fields script generator reads |
| `test_idea_record_maps_to_brief` | Airtable idea fields map correctly to brief format |
| `test_validator_accepts_idea_mapped_brief` | Validation prompt builder works with mapped brief |
| `test_pipeline_record_has_core_fields` | Pipeline record has all required fields |
| `test_original_dna_is_traceable` | DNA links back to source idea |
| `test_scene_list_has_required_fields` | Scenes have scene_description for engine |
| `test_generate_prompts_accepts_scene_list` | Engine processes 136-scene list |
| `test_generated_prompts_have_required_keys` | Prompts have all keys pipeline writes to Airtable |
| `test_styled_prompts_contain_identity_markers` | Dossier=Arri Alexa, Schema=Bloomberg, Echo=candlelight |
| `test_accent_color_applied_to_dossier_and_schema` | Accent color in D/S prompts |
| `test_scene_list_roundtrip_through_file` | Save -> Load -> Generate cycle works |
| `test_prompts_are_strings` | NanoBanana gets plain strings |
| `test_prompts_end_with_aspect_ratio` | All prompts include 16:9 |
| `test_ken_burns_not_all_same` | 3+ unique Ken Burns directions |
| `test_pan_directions_alternate` | Pan left/right alternate |
| `test_valid_status_chain` | All status values form valid progression |
| `test_run_image_bot_sets_thumbnail_not_video_scripts` | Status/log mismatch fix verified |
| `test_default_scene_dir_is_project_relative` | No VPS path in default |
| `test_save_scene_list_creates_dir` | Dir auto-created |
| `test_first_and_last_images_are_dossier` | Visual identity rule enforced |
| `test_no_echo_in_acts_1_2_6` | Echo restriction enforced |
| `test_distribution_roughly_matches_targets` | ~60/22/18 D/S/E distribution |
| `test_from_stage_valid_stages` | All stage names registered |
| `test_cli_commands_exist` | New CLI commands present |
| `test_help_documents_new_commands` | Help text updated |

---

## Files Modified

| File | Change |
|------|--------|
| `pipeline.py` | Fixed status mismatch bugs. Added `run_brief_translator()`, `run_styled_image_prompts()`, `run_full_pipeline()`, `run_produce_pipeline()`, `run_from_stage()`. Added CLI commands: `--translate`, `--styled-prompts`, `--full`, `--produce`, `--from-stage`. Updated help text. |
| `brief_translator/pipeline_writer.py` | Fixed `DEFAULT_SCENE_DIR` from `/home/bot/pipeline/scenes` to project-relative path. |
| `tests/__init__.py` | Created (new test package). |
| `tests/test_pipeline_integration.py` | Created (26 integration tests). |

---

## Ready for Daily Cron: NO

**Blockers:**
1. Research agent not yet built — pipeline starts from URL-based ideas (IdeaBot) rather than automated research
2. YouTube upload not automated — final step is manual
3. API keys need to be configured in `.env` (not `.env.example`)

**Workaround:** Use `--run-queue` mode which processes all videos from "Ready For Scripting" onward. Ideas must be manually created/approved first.
