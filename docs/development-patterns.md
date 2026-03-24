# Development Patterns & Testing

## When Adding a New Bot

1. Create a new folder under `skills/video-pipeline/` (e.g., `new_bot/`)
2. Add `__init__.py`, `run.py` (step logic), and optionally `cli.py` (standalone entry point)
3. Add status transition to `orchestrator/pipeline.py` router
4. Add Slack command in `orchestrator/pipeline_control.py` if user-triggerable
5. Import from `shared/clients/` for API access, `orchestrator/pipeline_constants.py` for field names
6. Update `SYSTEM_STATE.md` and this document

## When Modifying Airtable Schema

1. Update field in Airtable UI first
2. Update `shared/clients/airtable_client.py` field references
3. Update any bot that reads/writes the changed field
4. Test with a single record before running full pipeline

## When Adding a New API Integration

1. Create client in `shared/clients/` with async methods and retry logic
2. Add API key to `.env.example` with description
3. Add cost per call to `docs/cost-awareness.md`
4. Add error handling for rate limits (429) and timeouts
5. Test with a single call before integrating into pipeline

## When Editing Remotion Components

1. Run `npm run studio` first to see current state
2. Make changes and verify in studio preview
3. Test with `npm run render` on a short clip before full render
4. Scene.tsx is the most critical file — be surgical

## Python Code Style

- Async/await everywhere. Don't introduce sync blocking calls.
- Use `httpx` for HTTP (async), not `requests`.
- Use `pydantic` for data models where structured data is involved.
- Use `python-dotenv` for env vars. Load at module level.
- Follow existing error handling: log error, update Airtable status to failed, continue.

## Import Conventions

```python
# Orchestrator
from orchestrator.pipeline_constants import IdeaFields, Statuses, Models
from orchestrator.pipeline_config import VideoConfig

# Shared clients
from shared.clients.airtable_client import AirtableClient
from shared.clients.anthropic_client import AnthropicClient
from shared.clients.image_client import ImageClient

# Shared profiles
from shared.profiles.visual import load_profile
from shared.profiles.script.schema import ScriptProfile

# Shared utilities
from shared.json_utils import parse_json_response
from shared.channel_profile import ChannelProfile

# Cross-bot references (when needed)
from image_prompts.engine.prompt_builder import build_prompt
from render.audio_sync.aligner import align_words
from script.brief_translator.script_generator import generate_script
from title_idea.curiosity_gap.gap_title_engine import generate_titles
from analytics.osiris.learnings_engine import inject_learnings
```

---

# Testing Strategy

## Before Declaring Any Pipeline Change "Done"

1. **Unit test**: Does the function produce correct output for known input?
2. **Integration test**: Does it correctly read from and write to Airtable?
3. **Single-record test**: Run the bot against ONE real Airtable record
4. **Cost check**: Will this change increase per-video cost?

## Test Locations & Coverage (780+ tests as of March 2026)

```
tests/                                   ~30 integration tests
script/brief_translator/tests/           ~67 tests (validation, scene expansion)
image_prompts/engine/tests/              ~77 tests (style system, prompt building)
autopilot/tests/                         ~102 tests (all autopilot components)
title_idea/curiosity_gap/tests/          ~57 tests (gap titles, competitor analysis)
render/audio_sync/tests/                 ~20 tests (alignment, timing, Ken Burns)
```

## Running Tests

```bash
cd skills/video-pipeline

# Individual suites
python -m pytest tests/ -x
python -m pytest script/brief_translator/tests/ -x
python -m pytest image_prompts/engine/tests/ -x
python -m pytest autopilot/tests/ -x
python -m pytest title_idea/curiosity_gap/tests/ -x
python -m pytest render/audio_sync/tests/ -x

# All at once
python -m pytest tests/ script/brief_translator/tests/ image_prompts/engine/tests/ autopilot/tests/ title_idea/curiosity_gap/tests/ render/audio_sync/tests/ -x
```

## Key Integration Tests Verify

- Research output has all validator fields
- Brief has all script generator fields
- Scenes have required fields + visual identity markers
- All prompts end with "16:9"
- Ken Burns has 3+ unique directions, pan directions alternate
- Visual identity distribution matches targets (60D/22S/18E)
- Status chain is valid, no mismatches
