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
