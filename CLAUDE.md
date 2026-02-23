# Economy FastForward — AI Video Production Pipeline
"Topic in, 25-minute video out"

## Stack
Python 3.11+ (async) · TypeScript · Remotion · Airtable (orchestration DB) Claude (scripts) · Kie.ai (images/video) · ElevenLabs (voice) · Whisper (transcription) Google Drive (storage) · Slack (control) · Next.js (frontend)

## Repo Structure
* skills/video-pipeline/ — Core pipeline code (bots, clients, content gen, animation, audio sync)
* remotion-video/ — TypeScript/Remotion video rendering (src/, scripts/)
* storyengine/ — Research UI (backend/, frontend/, shared/, config/)
* animation/ — Animation assets and code
* tasks/ — Task scripts

## Architecture
Status-driven pipeline where Airtable Status fields gate each stage: Research → Script → Voice → Image Prompts → Images → Video Scripts → Video Generation → Thumbnail → Render → Upload

CRITICAL: Never skip a status. Always update via Airtable client. Check status before processing.

## Execution Protocol
1. UNDERSTAND: Read relevant files. If requirements are ambiguous, ASK.
2. SEARCH: grep/glob for similar existing functionality before creating anything new.
3. PLAN: Before writing code, outline:
   * Files to modify and why
   * Whether this should be a refactor rather than a patch
   * Impact on existing pipeline stages
4. Wait for approval on changes touching >3 files.
5. IMPLEMENT: One logical change at a time.
6. VERIFY: Run tests after every change.

## Anti-Bandaid Rules
* If a fix requires modifying >3 files, STOP. Question the architecture first.
* Never patch around a design flaw — propose refactoring the design instead.
* If you find yourself working around the same issue twice, the root cause needs fixing.
* When touching legacy code, assess: should this module be rewritten? Present the tradeoff.
* Remove dead code. No commented-out blocks. No unused imports.
* Challenge my approach if it adds unnecessary complexity. I expect pushback.
* Do not affirm my statements blindly. Question assumptions, offer counterpoints.

## Commands
```
python -m pytest tests/ -x
cd remotion-video && npm run typecheck
python -m ruff check .
```

## Key Reference Docs (read ONLY when relevant)
* Airtable schema & field maps → @docs/airtable-schema.md
* API integration patterns (retry, polling, JSON parsing) → @docs/api-patterns.md
* Image Prompt Engine (3-style system, 4-layer architecture) → @docs/image-prompt-engine.md
* Remotion rendering system → @docs/remotion-rendering.md
* Common failure modes & fixes (13 scenarios) → @docs/failure-modes.md
* Data architecture (Video DNA, Research Payload, Scene JSON) → @docs/data-architecture.md
* Cost breakdown per video → @docs/cost-awareness.md
* Environment variables reference → @docs/env-vars.md
* Infrastructure & deployment (VPS, cron, Slack bot) → @docs/infrastructure.md
* Critical file map → @docs/file-map.md
* Development patterns → @docs/development-patterns.md

## Core Principles
1. Simplicity first — prefer the simplest solution that works
2. No laziness — implement complete solutions, not shortcuts
3. Minimal impact — change only what needs changing
4. Ship incrementally — small, tested commits over big bangs

## Testing
170+ tests across 4 test suites. Run the relevant suite after every change. Never mark a task done until tests pass.

## Session Startup
1. Check current branch and recent commits
2. Review any open TODO items
3. Understand what pipeline stage we're working on before touching code
