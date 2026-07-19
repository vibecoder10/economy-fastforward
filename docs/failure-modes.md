# Common Failure Modes & Fixes

| Failure | Symptoms | Root Cause | Fix |
|---------|----------|-----------|-----|
| Images don't match script | Visual disconnect from narration | Prompt didn't capture scene intent | Check `image_prompt_engine/prompt_builder.py`, improve scene-to-prompt mapping |
| Audio alignment fails | Scenes have wrong timing, 3s uniform durations | Whisper transcription error or fuzzy match below 60% | Check `audio_sync/aligner.py`, lower threshold or improve anchor-word matching |
| Airtable record stuck | Status never advances | Bot crashed mid-processing, status not updated | Manually set status to correct value in Airtable, check bot logs |
| Image generation returns None | Empty images in Airtable | Kie.ai API timeout or rate limit | Check `clients/image_client.py` retry logic, verify API key |
| Remotion OOM | Render crashes silently | Not enough RAM | Run `setup_swap.sh`, verify 4GB swap exists |
| Slack bot unresponsive | Commands get no response | Process died, healthcheck hasn't run yet | Check `/tmp/pipeline-bot.pid`, restart `pipeline_control.py` |
| Google Drive upload fails | Assets missing from Drive | OAuth token expired | Refresh token in `.env`, check `clients/google_client.py` |
| Thumbnail field not updating | Thumbnail appears generated but not linked | Field name/format mismatch in Airtable | Known issue - code tries 3 fallback formats. Check `airtable_client.py` |
| Style clustering | Multiple consecutive scenes look identical | Sequencer anti-clustering not triggering | Check `image_prompt_engine/sequencer.py`, verify max 4 consecutive same-style rule |
| Airtable field mismatch | `UnknownField` error on create | New field added to code but not to Airtable UI | Add the field in Airtable first, then update code. The graceful degradation pattern will drop unknown fields. |
| YouTube quota exceeded | 403 on upload | >6 uploads/day (10,000 units/day, ~1,600 per upload) | Wait until next day. Quota resets at midnight Pacific. |
| Veo 3.1 still processing | `upgrade_veo_to_1080p()` returns None | HD upscale takes longer than expected | Retry after 90 seconds. The API returns the URL once processing finishes. |
| ElevenLabs timeout | Voice generation poll hits 30 attempts | Audio too long or API backlogged | Increase `max_attempts` in `elevenlabs_client.py` or split text into smaller chunks |
| Google Docs unavailable | 503 on document creation | Google Docs API intermittent outage | Code returns `GoogleDocsUnavailableError` gracefully. Non-blocking - pipeline continues without Docs backup. |
| Worker not executing queued jobs | Stages stuck at `pending`, no progress | `storyengine-worker` service stopped | `systemctl status storyengine-worker`; restart if stopped. Run `bash infra/setup_worker.sh` after fresh deploy. |
| Queue silently bypassed (no Redis) | Pipeline runs in-process, no `job_id` in `background_tasks` rows | Redis unreachable or `REDIS_URL` wrong | Check backend logs for "Redis/arq pool not available" warning, or `GET /api/health` → `queue: "degraded-inprocess"` (C16d, S7-7). Verify `REDIS_URL` env var. |

## Per-Stage Resumability (checklist C16d, S7-9 — docs/reports/2026-07-17-storyengine-agent-audit-findings.md §S7)

Whether re-invoking a pipeline stage on a video that already has that stage's
output skips the work (cheap, safe to retry/resume) or fully redoes it
(re-spends money, or in upload's case, re-publishes). "Guard" is the file:line
that actually implements the skip — not just a status-machine gate.

| Stage | Resumable (skip-if-done)? | Guard |
|-------|---------------------------|-------|
| voice | Yes | `skills/video-pipeline/voice/run.py:86-96` ("voice already done, skipping" per scene) |
| sound prompts (design) | Yes | `skills/video-pipeline/sound/sound_prompt_bot.py:301-320` (per-scene "already have prompts") |
| sound effects | Yes | `skills/video-pipeline/sound/sound_bot.py:73-79` (`already_done` count) |
| clips (video generation) | Yes | `storyengine/backend/supabase_adapter.py:756,765` (`video_url IS NULL`); `storyengine/backend/pipeline_executor.py::run_clip_generation` ~L11841 (`force or not r.get("video_clip_url")`) — `force=True` (routes/pipeline.py `POST /clip/{id}?force=true`) is the explicit redo |
| images / coverage | Yes (since C16b, 2026-07-18) | `storyengine/backend/scripts/coverage_to_app.py::generate_coverage_for_video` (completeness rule: directive hash match + drawn-frame count vs. expected; `only_scenes` allowlist forces named scenes) |
| thumbnail | Yes (since C16d, 2026-07-18) | `storyengine/backend/pipeline_executor.py::run_thumbnail` ~L14574 (skip when `videos.thumbnail_url` set and `force` is not True; `force=True` from the ACTIONS["thumbnail"] verb, the prompt-studio "Apply & redo" path, or `POST /thumbnail/{id}?force=true`) |
| research | No — full restart every call | `storyengine/backend/pipeline_executor.py::run_research` ~L7532 (no existence check; relatively cheap — one Claude/web-research call) |
| script | No — full restart every call | `storyengine/backend/pipeline_executor.py::run_script` ~L11333 (always overwrites; relatively cheap — one Claude call) |
| render | No — full restart every call | `storyengine/backend/pipeline_executor.py::run_render` ~L14963 (always re-renders; compute-only, no external per-call billing) |
| upload | Yes (since C16e, 2026-07-xx — this row was stale, found during C55/P4.2-f's audit) | `storyengine/backend/pipeline_executor.py::run_upload` ~L15731 (skip-if-done: default `force=False` returns the existing `youtube_url`/`youtube_video_id` without re-uploading when either is already set; `force=True` is the only bypass, and no caller sets it by default). The re-upload gap this row used to describe (a re-invoke minting a SECOND YouTube draft) is fixed for EVERY caller, not just a specific one — including the C55 full-auto continuation path, which calls the exact same `run_upload`. |
