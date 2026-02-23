# Development Patterns & Testing

## When Adding a New Bot Stage

1. Create bot in `bots/` following existing patterns (async, Airtable status read/write)
2. Add status transition to `pipeline.py` router
3. Add `run_*_bot.py` script for standalone execution
4. Add Slack command in `pipeline_control.py` if user-triggerable
5. Update this document's status flow

## When Modifying Airtable Schema

1. Update field in Airtable UI first
2. Update `clients/airtable_client.py` field references
3. Update any bots that read/write the changed field
4. Test with a single record before running full pipeline
5. Document the change in `ANIMATION_SYSTEM_REVIEW.md`

## When Adding a New API Integration

1. Create client in `clients/` with async methods and retry logic
2. Add API key to `.env.example` with description
3. Add cost per call to the Cost Awareness table above
4. Add error handling for rate limits (429) and timeouts
5. Test with a single call before integrating into pipeline

## When Editing Remotion Components

1. Run `npm run studio` first to see current state
2. Make changes and verify in studio preview
3. Test with `npm run render` on a short clip before full render
4. Scene.tsx is the most critical file - be surgical, don't refactor unless asked

## Python Code Style

- Async/await everywhere. Don't introduce sync blocking calls.
- Use `httpx` for HTTP (async), not `requests`.
- Use `pydantic` for data models where structured data is involved.
- Use `python-dotenv` for env vars. Load at module level.
- Use `rich` for console output in CLI tools.
- Follow existing error handling: log error, update Airtable status to failed, continue to next record.

---

# Testing Strategy

## Before Declaring Any Pipeline Change "Done"

1. **Unit test**: Does the function produce correct output for known input?
2. **Integration test**: Does it correctly read from and write to Airtable?
3. **Single-record test**: Run the bot against ONE real Airtable record
4. **Dry run**: Process a full video with `--dry-run` if available
5. **Cost check**: Will this change increase per-video cost? By how much?

## Test Locations & Coverage (170 tests passing as of Feb 2026)

```
image_prompt_engine/tests/    77 tests  (style system, prompt building, sequencing)
brief_translator/tests/       67 tests  (validation, scene expansion, pipeline writing)
tests/test_pipeline_integration.py  26 tests  (end-to-end integration)
audio_sync/tests/             —         (alignment, timing, Ken Burns)
thumbnail_generator/          —         (generation tests)
```

## Running Tests

```bash
cd skills/video-pipeline && python -m pytest image_prompt_engine/tests/
cd skills/video-pipeline && python -m pytest brief_translator/tests/
cd skills/video-pipeline && python -m pytest tests/test_pipeline_integration.py
cd skills/video-pipeline && python -m pytest audio_sync/tests/
```

## Key Integration Tests Verify

- Research output has all validator fields
- Brief has all script generator fields
- Scenes have required fields + visual identity markers
- All prompts end with "16:9"
- Ken Burns has 3+ unique directions, pan directions alternate
- Visual identity distribution matches targets (60D/22S/18E)
- Status chain is valid, no mismatches
- Scene dir is project-relative (not hardcoded VPS path)
