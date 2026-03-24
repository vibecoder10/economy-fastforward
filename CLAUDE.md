# Economy FastForward — AI Video Production Pipeline
"Topic in, video out — length configured per-idea in Airtable"

---

## Structural Change Rule
**MANDATORY:** Any session that moves, renames, creates, or deletes files/folders MUST update `SYSTEM_STATE.md` before committing. This includes:
- New bots, steps, or modules
- Renamed or moved files
- Changed import paths
- New cron jobs or Slack commands
- New Airtable tables or fields

---

## 🦸 Superpowers Skill Integration

**Skills are NOT optional. Invoke them BEFORE acting.** Use the `Skill` tool.

### Skill → Scenario Mapping

| Scenario | Skill to Invoke FIRST | Why |
|----------|----------------------|-----|
| **Bug report / test failure** | `systematic-debugging` | Diagnose before fixing. No guessing. |
| **New feature request** | `brainstorming` | Clarify intent and requirements before coding |
| **Multi-step task (3+ steps)** | `writing-plans` | Plan THEN implement. No improvising. |
| **Implementing a plan** | `subagent-driven-development` | Parallel execution with checkpoints |
| **About to say "done" or "fixed"** | `verification-before-completion` | Prove it works. Run commands. Show output. |
| **Major feature complete** | `requesting-code-review` | Validate against requirements |
| **Received code review feedback** | `receiving-code-review` | Don't blindly agree. Verify technically. |
| **Ready to merge/PR** | `finishing-a-development-branch` | Structured completion options |
| **2+ independent tasks** | `dispatching-parallel-agents` | Parallelize for speed |
| **Need feature isolation** | `using-git-worktrees` | Safe experimentation |

### The 1% Rule

If there's even a **1% chance** a skill applies → **invoke it**.

---

## Stack
Python 3.11+ (async) · TypeScript · Remotion · Airtable (orchestration DB) · Claude (scripts) · Kie.ai (images/video) · ElevenLabs (voice) · Whisper (transcription) · Google Drive (storage) · Slack (control) · Next.js (frontend)

## Repo Structure

```
skills/video-pipeline/           # Core pipeline (each tool = standalone folder)
├── orchestrator/                # Pipeline brain — status router, Slack bot
│   ├── pipeline.py              # Main status-driven router
│   ├── pipeline_control.py      # Slack bot commands
│   ├── pipeline_constants.py    # Field names, status enums, table IDs
│   ├── pipeline_config.py       # Env/config loading
│   ├── approval_watcher.py      # Slack approval monitoring
│   ├── webhook_server.py        # External webhook receiver
│   └── handlers/                # Slack command handlers (admin, style, delete)
│
├── autopilot/                   # Autonomous intelligence (CTR/VPH driven)
│   ├── autopilot.py             # Main loop (--status, --check-cycle, --force)
│   ├── autopilot_program.md     # Human-editable config
│   ├── core/                    # Config, state, cadence, scorer, notifier
│   ├── analysis/                # Thumbnail analyzer, adapter, title selector
│   ├── monitoring/              # CTR monitor, early warning, perf comparator
│   ├── learning/                # Pattern library, learning extractor, memory writer
│   ├── memory/                  # LEARNINGS.md, patterns (git-tracked)
│   └── tests/                   # 102 tests
│
├── competitor_scraper/          # Pull competitor YouTube data
├── discovery/                   # Headline + trending topic scanning
├── title_idea/                  # Title creation from data-backed research
│   ├── idea_bot.py, trending_idea_bot.py, idea_modeling.py
│   └── curiosity_gap/           # Gap-based title generation (6 tests)
├── research/                    # Deep-dive factual research (agent.py)
│
├── script/                      # 6-scene script writing
│   ├── run.py                   # Script generation step
│   ├── story_bible.py           # Character/location bibles
│   └── brief_translator/        # Research → script pipeline (11 files, 7 tests)
├── voice/                       # Voice synthesis (ElevenLabs)
├── image_prompts/               # Image prompt generation
│   ├── run.py                   # Prompt generation step
│   └── engine/                  # 3-style system: Dossier 60%, Schema 22%, Echo 18%
├── storyboard/                  # Storyboard grid generation
├── images/                      # Image creation (Seed Dream 4.5)
├── video_motion/                # Video scripts + clip generation (Veo 3.1)
│   └── animation/               # 3D animation pipeline
├── sound/                       # Sound FX + Music selection
├── thumbnail/                   # Thumbnail generation (templates, Gemini director)
├── render/                      # Audio sync + Remotion rendering
│   ├── render_video.py          # Calls Remotion CLI
│   └── audio_sync/              # Whisper alignment (7 files, 4 tests)
├── upload/                      # YouTube upload + SEO
│
├── analytics/                   # Performance tracking
│   ├── performance_tracker.py   # Daily YouTube metrics sync
│   └── osiris/                  # Learning system (48h/7d analysis, title patterns)
│
├── shared/                      # Cross-bot infrastructure
│   ├── clients/                 # API wrappers (airtable, anthropic, image, google, etc.)
│   ├── profiles/visual/         # Visual styles (cinematic_illustration, dossier, hud, mannequin)
│   ├── profiles/script/         # Script voice profiles (power_doctrine_v1, v2)
│   ├── json_utils.py            # JSON parsing with fallback chain
│   └── channel_profile.py       # Channel-specific settings
│
├── infra/                       # Setup scripts, cron, healthcheck, auth
│   ├── setup_cron.sh            # VPS cron job definitions
│   ├── bot_healthcheck.sh       # Auto-restart Slack bot
│   └── setup_*.py               # Airtable/YouTube field setup scripts
│
├── tests/                       # Integration tests
└── requirements.txt

remotion-video/                  # TypeScript/Remotion video renderer
storyengine/                     # Research UI (backend + frontend)
tasks/                           # Task tracking, lessons learned
docs/                            # Reference documentation
```

## Architecture

### System Layers
1. **Autopilot** — Top-level intelligence. Fed by CTR, VPH, AVD data. Auto-enhancing. Decides WHAT to make.
2. **Orchestrator** — Calls each bot at the right time. Status-driven via Airtable. Decides WHEN to run each step.
3. **Bot Folders** — Each tool is standalone. Does ONE thing. Called by orchestrator or CLI.
4. **Shared** — API clients, visual profiles, utilities. Used by all bots.

### Pipeline Flow (Status-Driven)
```
Idea Logged → (approval) → Ready For Scripting → script/
→ Ready For Voice → voice/ → Ready For Image Prompts → image_prompts/
→ Ready For Images → images/ → Ready For Video Scripts → video_motion/
→ Ready For Video Generation → video_motion/ → Ready For Thumbnail → thumbnail/
→ Ready To Render → render/ → Rendered → upload/ → Done
```

CRITICAL: Never skip a status. Always update via Airtable client. Check status before processing.

### Autopilot Brain
Autonomous orchestration layer above the pipeline:
1. Reads config from `autopilot_program.md` (weights, cadence, thresholds)
2. Scores candidate ideas from Competitor Videos table
3. Picks best idea, notifies Slack with reasoning
4. Writes style overrides to Airtable
5. Triggers pipeline execution → YouTube draft
6. Monitors CTR at 6h/24h/48h → extracts learnings to memory files

```bash
cd skills/video-pipeline
python -m autopilot.autopilot --status       # Show state
python -m autopilot.autopilot --check-cycle  # Run one cycle
python -m autopilot.autopilot --force        # Skip cadence
```

### Import Conventions
All imports use canonical paths:
```python
from orchestrator.pipeline_constants import IdeaFields, Statuses
from shared.clients.airtable_client import AirtableClient
from shared.clients.anthropic_client import AnthropicClient
from shared.profiles.visual import load_profile
from shared.profiles.script.schema import ScriptProfile
from shared.json_utils import parse_json_response
from image_prompts.engine.prompt_builder import build_prompt
from render.audio_sync.aligner import align_words
from script.brief_translator.script_generator import generate_script
from title_idea.curiosity_gap.gap_title_engine import generate_titles
from analytics.osiris.learnings_engine import inject_learnings
```

---

## Session Protocol

### Session Start (EVERY session, no exceptions)
1. Check current branch and recent commits: `git log --oneline -5`
2. Read `tasks/lessons.md` — hard-won patterns that prevent repeat mistakes
3. Read `tasks/todo.md` — pick up where the last session left off
4. Understand what bot folder we're working on before touching code

### Session End (EVERY session, no exceptions)
Claude Code has NO memory between sessions. Before ending ANY session:
1. Update `tasks/todo.md` with current progress and what's next
2. Update `tasks/lessons.md` if ANY corrections were made
3. Commit all changes with a descriptive message
4. If work is incomplete, leave a clear `## Handoff` section in `tasks/todo.md`

---

## Execution Protocol
1. UNDERSTAND: Read relevant files. If requirements are ambiguous, ASK.
2. SEARCH: grep/glob for similar existing functionality before creating anything new.
3. PLAN: Before writing code, outline files to modify and why.
4. Wait for approval on changes touching >3 files.
5. IMPLEMENT: One logical change at a time.
6. VERIFY: Run tests after every change.

## Anti-Bandaid Rules
* If a fix requires modifying >3 files, STOP. Question the architecture first.
* Never patch around a design flaw — propose refactoring the design instead.
* Remove dead code. No commented-out blocks. No unused imports.
* Challenge my approach if it adds unnecessary complexity. I expect pushback.
* Do not affirm my statements blindly. Question assumptions, offer counterpoints.

## Commands
```bash
cd skills/video-pipeline
python -m pytest tests/ -x                                    # Integration tests
python -m pytest script/brief_translator/tests/ -x            # Script tests
python -m pytest image_prompts/engine/tests/ -x               # Prompt engine tests
python -m pytest autopilot/tests/ -x                          # Autopilot tests
python -m pytest title_idea/curiosity_gap/tests/ -x           # Curiosity gap tests
python -m pytest render/audio_sync/tests/ -x                  # Audio sync tests
cd remotion-video && npm run typecheck                        # TypeScript check
```

## Key Reference Docs (read ONLY when relevant)
* Autopilot Brain design spec → @docs/superpowers/specs/2026-03-18-autopilot-brain-design.md
* Airtable schema & field maps → @docs/airtable-schema.md
* API integration patterns → @docs/api-patterns.md
* Image Prompt Engine → @docs/image-prompt-engine.md
* Remotion rendering → @docs/remotion-rendering.md
* Common failure modes → @docs/failure-modes.md
* Data architecture → @docs/data-architecture.md
* Cost breakdown → @docs/cost-awareness.md
* Environment variables → @docs/env-vars.md
* Infrastructure & deployment → @docs/infrastructure.md

## Core Principles
- **Simplicity First**: Make every change as simple as possible.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- Minimal impact — change only what needs changing
- Ship incrementally — small, tested commits over big bangs

## Testing
780+ tests across 6 test suites. Run the relevant suite after every change. Never mark a task done until tests pass.

---

## Working Patterns

### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- One task per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- **This is not optional.** Every correction not captured will be repeated.

### 4. Verification Before Done
- Never mark a task complete without proving it works
- **Trace the full execution path.** A function that exists but is never called is dead code.

### 5. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding.
- Zero context switching required from the user.

### 6. Trace Before Touch (Complex Tasks)
- For ANY audit, fix, or multi-file change: run ALL diagnostic commands FIRST
- **Do NOT jump to fixing when given a multi-phase task.** Diagnose first.

## Task Management
1. **Plan First**: Write plan to `tasks/todo.md`
2. **Track Progress**: Mark items complete as you go
3. **Capture Lessons**: Update `tasks/lessons.md` after corrections
4. **Handoff**: Before session ends, write what's next

---

## ⚠️ MANDATORY WIRING AUDIT PROTOCOL

**This applies to EVERY task. No exceptions.**

### Before marking ANY task as complete, verify ALL of these:

**Entry Points:**
- How does this code get triggered? (orchestrator/pipeline.py flag? cron? Slack command?)
- Is the trigger ACTUALLY wired? (not just the module existing, but the caller invoking it)

**Data Flow:**
- Do Airtable field names in code EXACTLY match the real Airtable fields?
- Test one real Airtable read AND one real write — not mocks

**Integration:**
- Are new imports added to all files that call the new code?
- Do Slack notifications actually fire? Test live, don't assume.

**Smoke Test:**
- Run the actual command on VPS with real data
- Check Airtable for expected records
- Check Slack for expected messages

**Documentation:**
- Update CLAUDE.md if new CLI flags or Slack commands were added
- Update infra/setup_cron.sh if new cron jobs were added (AND run it to install)

### Common Failure Modes to Watch For:
- `Image Model Override` is a Multiple Select (returns list, not string)
- `Visual Style` is a Single Select (returns string)
- Airtable UNKNOWN_FIELD_NAME errors are silent — the write appears to succeed but drops the field
- Cron jobs written to setup_cron.sh are NOT automatically installed — must run `bash infra/setup_cron.sh`
- Slack commands in orchestrator/pipeline_control.py require both the command handler AND the import
