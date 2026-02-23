# Cost Awareness

Every API call costs money. Be aware of these costs when building features:

| Operation | Cost | Volume per Video |
|-----------|------|-----------------|
| Image generation (Seed Dream 4.5) | $0.025/image | 120 images = $3.00 |
| Video clip (Veo 3.1 Fast) | $0.30/clip | 20-40 clips = $6-12 |
| Thumbnail (Nano Banana Pro) | $0.075/image | 1-3 = $0.075-0.225 |
| Voice synthesis (ElevenLabs) | ~$0.30/1000 chars | ~$1-2 per video |
| Claude API (Sonnet) | ~$0.01-0.05/call | ~20-30 calls = $0.30-1.50 |
| Whisper transcription | ~$0.006/min | ~$0.15 per video |
| **Total per video** | | **~$11-19** |

## Rules

- Never add unnecessary API calls in loops. Batch where possible.
- When testing, use `--dry-run` flags or mock API responses. Don't burn $15 on a test run.
- Log costs when introducing new API integrations. Add to this table.
- Budget alerts exist at 80% threshold (animation pipeline).
