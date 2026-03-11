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
- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- Minimal impact — change only what needs changing
- Ship incrementally — small, tested commits over big bangs

## Testing
170+ tests across 4 test suites. Run the relevant suite after every change. Never mark a task done until tests pass.

## Session Startup
1. Check current branch and recent commits
2. Review any open TODO items
3. Understand what pipeline stage we're working on before touching code

---

## Working Patterns

### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately — don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes — don't over-engineer
- Challenge your own work before presenting it

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests — then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how

## Task Management

1. **Plan First**: Write plan to `tasks/todo.md` with checkable items
2. **Verify Plan**: Check in before starting implementation
3. **Track Progress**: Mark items complete as you go
4. **Explain Changes**: High-level summary at each step
5. **Document Results**: Add review section to `tasks/todo.md`
6. **Capture Lessons**: Update `tasks/lessons.md` after corrections
