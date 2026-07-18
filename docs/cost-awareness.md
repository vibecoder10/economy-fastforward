# Cost Awareness

Every API call costs money. Be aware of these costs when building features:

| Operation | Cost | Volume per Video |
|-----------|------|-----------------|
| Image generation (nano-banana-2 — the "Seed Dream 4.5" row this replaced) | $0.025/image | 120 images = $3.00 |
| Video clip (Veo 3.1 Fast) | $0.30/clip | 20-40 clips = $6-12 |
| Thumbnail (Nano Banana Pro) | $0.075/image | 1-3 = $0.075-0.225 |
| Voice synthesis (ElevenLabs) | ~$0.30/1000 chars | ~$1-2 per video |
| Claude API (Sonnet) | ~$0.01-0.05/call | ~20-30 calls = $0.30-1.50 |
| Whisper transcription | ~$0.006/min | ~$0.15 per video |
| Vision QA (Kie Gemini 2.5 Flash via vision_client) | ~$0.0005/call | storyboard QA + cast rewrite + thumbnail pass = < $0.05 |
| Vision-drift canary (3 calls/run, hourly) | ~$0.002/run | ~$1.50/month total, not per-video |
| **Total per video** | | **~$11-19** |

**StoryEngine's default image engine is GPT Image 2, not nano-banana-2**
(nano-banana-2/z-image are explicit overrides — see storyengine/CLAUDE.md
"Image gen policy" and `shared.clients.image_model_router`). GPT Image 2 is
quality/resolution-tiered and Kie.ai doesn't publish one flat per-image
rate for it; `IMAGE_PRICE_BY_MODEL["gpt-image-2"] = 0.08` (below) is an
**unconfirmed estimate**, not sourced from this table's $0.025 (that number
is nano-banana-2's real rate, a different model). Flagged for Ryan to
confirm against the Kie dashboard — see `tasks/live-verification-queue.md`
§C09.

**Single price source (storyengine-wiring-fix-checklist.md §0.3c / C09):**
every StoryEngine generation price above now lives in
`skills/video-pipeline/shared/channel_profile.py` — `MODEL_REGISTRY[*]
.cost_per_clip` for clips, `IMAGE_PRICE_BY_MODEL` / `THUMBNAIL_PRICE` /
`VOICE_PRICE_PER_1K_CHARS` / `SOUND_PRICE_ESTIMATE` for everything else.
`storyengine/backend/actions.py` re-exports these constants; update prices
THERE, not in actions.py or the frontend.

## Rules

- Never add unnecessary API calls in loops. Batch where possible.
- When testing, use `--dry-run` flags or mock API responses. Don't burn $15 on a test run.
- Log costs when introducing new API integrations. Add to this table.
- Budget alerts exist at 80% threshold (animation pipeline).
