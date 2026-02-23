# API Integration Patterns

## Async Pattern (Standard)

All bots use async Python. Follow this pattern:
```python
async def process_record(record_id: str):
    record = await airtable.get_record(record_id)
    # ... do work ...
    await airtable.update_record(record_id, {"Status": "Next Status"})
```

## Retry Pattern

Use `tenacity` for API retries. All external APIs (Kie.ai, ElevenLabs, Google Drive) are flaky:
```python
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=30))
async def call_external_api(...):
```

## Image Generation (Kie.ai)

- Task-based: create task → poll for completion → download result
- Poll status codes: 0=Queue, 1=Running, 2=Success, 3=Failed
- Retry up to 3 times on failure with different seeds
- Models: `seedream/4.5-edit` (scene images with reference), `nano-banana-pro` (thumbnails/text), `grok-imagine/image-to-video` (animation), `veo3_fast`/`veo3` (advanced video)
- **Proxy fallback**: On 500 errors for image URLs, the client downloads the image, re-uploads to Google Drive, makes it public, and retries with the Drive URL. Follow this pattern for resilience.
- Veo 3.1 supports 1080p upgrade via `upgrade_veo_to_1080p()` (polls separately, 90s retry if still processing)

## Voice Synthesis (ElevenLabs via Wavespeed)

- Voice ID: `G17SuINrv2H9FC6nvetn` (configured in .env)
- Uses Wavespeed v3 API endpoint (ElevenLabs turbo), not direct ElevenLabs API
- Polling: create task → poll up to 30 times at 5s intervals → return audio URL
- Upload to Google Drive after generation

## Audio Alignment (Whisper → Fuzzy Match)

- Whisper API returns word-level timestamps
- 3-strategy alignment: full-excerpt fuzzy match → anchor-word fallback → proportional estimate
- Minimum 60% similarity threshold for fuzzy matching
- Timing constraints: MIN_DISPLAY 3s, MAX_DISPLAY 18s, CROSSFADE 0.4s, ACT_TRANSITION_BLACK 1.5s

## Google APIs (Drive & Docs)

- Exponential backoff on 503 (MAX_RETRIES=3, INITIAL_BACKOFF=1.0s)
- Docs API can be unavailable - code returns `GoogleDocsUnavailableError` gracefully
- Drive URLs must be converted to direct download format for Airtable attachments
- Airtable attachment URLs expire in 2 hours, but Drive URLs are permanent

## YouTube Upload

- YouTube API quota: 10,000 units/day, ~1,600 units per upload (max ~6 uploads/day)
- Always upload as **unlisted** draft, never public
- Thumbnail upload failures are warnings (non-blocking) - the video still uploads

## JSON Response Parsing (Universal Pattern)

All Claude/Gemini responses use this fallback chain:
```
Try: json.loads(response) directly
Catch: Remove markdown fences (```json ... ```), try again
Catch: Extract JSON substring, try again
Catch: Fix common issues (trailing commas, unescaped quotes), try again
Catch: Regex extraction from raw text
Catch: Return defaults/fallback
```
**Follow this pattern** when parsing any AI-generated JSON. Never assume clean JSON output.

## Polling Pattern (Universal)

All async operations (voice, images, videos) use:
```python
# Wait before first poll (API needs processing time)
await asyncio.sleep(initial_wait)  # 5s for images, varies by service
for attempt in range(max_attempts):
    status = await check_status(task_id)
    if status == SUCCESS: return result
    if status == FAILURE: return None
    await asyncio.sleep(poll_interval)
return None  # Timeout
```
