# Cost Awareness

Every API call costs money. Be aware of these costs when building features:

| Operation | Cost | Volume per Video |
|-----------|------|-----------------|
| Image generation, GPT Image 2 (StoryEngine's default engine, 2K tier) | $0.05/image | 120 images = $6.00 |
| Image generation, nano-banana-2 (explicit override, 1K tier) | $0.04/image | 120 images = $4.80 |
| Image generation, z-image (explicit override, flat) | $0.004/image | 120 images = $0.48 |
| Video clip, Grok Imagine (StoryEngine's default clip model, 720p, variable 6-15s duration) | $0.09-$0.225/clip | 20-40 clips = $1.80-9.00 |
| Video clip, Seedance 2.0 (720p, always with image input, 6-10s) | $0.60-$1.00/clip | 20-40 clips = $12-40 |
| Video clip, Veo 3.1 Fast (8s) — price UNCONFIRMED, see note below | $0.30/clip | 20-40 clips = $6-12 |
| Video clip, Veo 3.1 Quality (8s) — price UNCONFIRMED, see note below | $1.25/clip | 20-40 clips = $25-50 |
| Thumbnail (GPT Image 2, 2K tier — see note below) | $0.05/image | 1-3 = $0.05-0.15 |
| Voice synthesis (ElevenLabs) | ~$0.30/1000 chars | ~$1-2 per video |
| Claude API (Sonnet) | ~$0.01-0.05/call | ~20-30 calls = $0.30-1.50 |
| Whisper transcription | ~$0.006/min | ~$0.15 per video |
| Vision QA (Kie Gemini 2.5 Flash via vision_client) | ~$0.0005/call | storyboard QA + cast rewrite + thumbnail pass = < $0.05 |
| Vision-drift canary (3 calls/run, hourly) | ~$0.002/run | ~$1.50/month total, not per-video |
| **Total per video** | | **~$11-19** (mix of image/clip models varies this) |

**C09a price basis (2026-07-18):** the image and Grok/Seedance clip prices
above come from Kie's PUBLISHED per-model pricing pages (`kie.ai/<model>`)
at a confirmed **$0.005/credit** rate — real published pricing, not a guess,
though still not a per-task "Kie actually charged $X for this exact
generation" read (Kie's job-status API never returns that — see
`shared/channel_profile.py`'s header comment). Each price is pinned to the
resolution/duration tier StoryEngine's code actually requests, confirmed by
reading the call sites (quoted in `shared/channel_profile.py`):
- **GPT Image 2** (default engine, `storyengine/CLAUDE.md` "Image gen
  policy"): `shared.clients.image_model_router.generate_scene_image_for_model`
  — the one resolver every image-generating call site uses — defaults
  `resolution="2K"` and no caller overrides it. 2K = $0.05/image (1K=$0.03,
  4K=$0.08 also published, unused here). Thumbnails route through the SAME
  GPT Image 2 2K path (`PipelineExecutor.run_thumbnail` /
  `_run_channel_formula_thumbnail` call `generate_thumbnail_gpt2`/
  `generate_scene_image_gpt` as PRIMARY, not nano-banana-pro as the old
  "Nano Banana Pro flat rate" label assumed) — so thumbnails price the same
  $0.05, not a separate number.
- **nano-banana-2** (explicit override only): the live call path defaults to
  the 1K tier ($0.04/image; 2K=$0.06, 4K=$0.09 also published, unused here).
- **z-image** (explicit override only): flat $0.004/image (0.8 credits), no
  resolution tiers — unchanged from the prior figure, now confirmed.
- **Grok Imagine** (default clip model): $0.015/s at 720p (StoryEngine's
  default clip resolution) — clip duration is VARIABLE (6/10/15s, sized to
  the spoken line), so the price is a per-tier range, not one number.
- **Seedance 2.0**: `ImageClient.generate_video_seedance` hardcodes 720p and
  always passes an image input, landing on the $0.100/s "720p with input"
  tier every time (a 4-tier model; the other 3 tiers are unreachable from
  this code path).

**Still dashboard-pending (NOT resolved by this pass — see
`tasks/live-verification-queue.md` §C09):**
- **Veo 3.1 Fast / Quality** — Kie's page lists $0.40/$2.00 per 8s, but a
  later Kie post claims a cut to $0.30/$1.25; unclear whether the cut is
  3.0-vs-3.1 specific. The registry already carries the lower (cut) figures
  — left unchanged, not re-verified.
- **Kling 3.0 Pro**, **Runway Gen-4 Turbo** — low-confidence/secondary
  sources only (a "Turbo" tier price for Kling, not confirmed as the same
  SKU as "Pro"; a non-primary source for Runway). Both are UNWIRED (no live
  generation path) so this doesn't affect any real spend today.
- **Grok's image-generation price** (distinct from Grok Imagine's video
  price above) — not found published anywhere.
- **ElevenLabs voice** ($0.30/1000 chars) — ElevenLabs doesn't route through
  Kie, so this $0.005/credit research pass doesn't touch it; still needs
  confirming against ElevenLabs' own dashboard/invoice.

**Single price source (storyengine-wiring-fix-checklist.md §0.3c / C09,
accuracy pass §C09a):** every StoryEngine generation price above lives in
`skills/video-pipeline/shared/channel_profile.py` — `MODEL_REGISTRY[*]
.cost_per_clip` for clips, `IMAGE_PRICE_BY_MODEL` / `THUMBNAIL_PRICE` /
`VOICE_PRICE_PER_1K_CHARS` / `SOUND_PRICE_ESTIMATE` for everything else.
`storyengine/backend/actions.py` re-exports these constants — update prices
in `channel_profile.py`, never in `actions.py` or the frontend.

## Rules

- Never add unnecessary API calls in loops. Batch where possible.
- When testing, use `--dry-run` flags or mock API responses. Don't burn $15 on a test run.
- Log costs when introducing new API integrations. Add to this table.
- Budget alerts exist at 80% threshold (animation pipeline).
