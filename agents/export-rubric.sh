#!/usr/bin/env bash
# export-rubric.sh — Export the RUBRIC agent system as a reusable template
#
# Usage:
#   ./agents/export-rubric.sh /path/to/output    # Export to a directory
#   ./agents/export-rubric.sh --tar               # Export as rubric-system.tar.gz
#
# This exports the FRAMEWORK (agent coordination, dashboard, swarm, Telegram)
# without any project-specific code, data, or secrets.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT="${1:-$PROJECT_ROOT/rubric-export}"
TAR_MODE=false

if [ "$OUTPUT" = "--tar" ]; then
  TAR_MODE=true
  OUTPUT=$(mktemp -d)/rubric-system
fi

echo "=== RUBRIC Agent System Export ==="
echo "Source: $PROJECT_ROOT"
echo "Output: $OUTPUT"
echo ""

mkdir -p "$OUTPUT"

# ─── 1. Dashboard (rubric/scaffold) ──────────────────────────────────────────
echo "Exporting dashboard..."
mkdir -p "$OUTPUT/rubric/scaffold/data"

# Framework files (copy as-is)
for f in server.js package.json package-lock.json index.html icons.html .env.example README.md INSTALL_PROMPT.md LICENSE; do
  [ -f "$PROJECT_ROOT/rubric/scaffold/$f" ] && cp "$PROJECT_ROOT/rubric/scaffold/$f" "$OUTPUT/rubric/scaffold/"
done

# Telegram setup scripts
for f in telegram-channels-setup.sh telegram-healthcheck.sh telegram-system-prompt.md; do
  [ -f "$PROJECT_ROOT/rubric/scaffold/$f" ] && cp "$PROJECT_ROOT/rubric/scaffold/$f" "$OUTPUT/rubric/scaffold/"
done

# Template config (with placeholder values)
cat > "$OUTPUT/rubric/scaffold/config.json" << 'CONFIGEOF'
{
  "brandName": "My Agent Team",
  "agents": [
    {
      "id": "orchestrator",
      "name": "Orchestrator",
      "color": "#D4A844",
      "icon": "Crown"
    },
    {
      "id": "backend-dev",
      "name": "Backend Dev",
      "color": "#1A8A7A",
      "icon": "Fortress"
    },
    {
      "id": "frontend-dev",
      "name": "Frontend Dev",
      "color": "#58abf5",
      "icon": "Spark"
    },
    {
      "id": "qa-engineer",
      "name": "QA Engineer",
      "color": "#e35050",
      "icon": "Sentinel"
    },
    {
      "id": "pipeline-tester",
      "name": "Pipeline Tester",
      "color": "#c084fc",
      "icon": "Phantom"
    }
  ]
}
CONFIGEOF

# Empty data files (clean slate)
echo '[]' > "$OUTPUT/rubric/scaffold/data/activity-log.json"
echo '{}' > "$OUTPUT/rubric/scaffold/data/agent-status.json"
echo '{"team_enabled":true,"paused_agents":[],"skipped_tasks":[],"priority_overrides":{},"focus":""}' > "$OUTPUT/rubric/scaffold/data/controls.json"
echo '[]' > "$OUTPUT/rubric/scaffold/data/handoffs.json"
echo '{"agents":{}}' > "$OUTPUT/rubric/scaffold/data/agent-skills.json"

# Skills directory
mkdir -p "$OUTPUT/rubric/scaffold/.claude/skills"

# ─── 2. Flows (rubric/flows) ─────────────────────────────────────────────────
echo "Exporting flows..."
mkdir -p "$OUTPUT/rubric/flows/data"

for f in server.js package.json package-lock.json index.html README.md INSTALL_PROMPT.md .env.example LICENSE; do
  [ -f "$PROJECT_ROOT/rubric/flows/$f" ] && cp "$PROJECT_ROOT/rubric/flows/$f" "$OUTPUT/rubric/flows/"
done

# Example workflow (not project-specific)
if [ -d "$PROJECT_ROOT/rubric/flows/workflows/market-research-brief" ]; then
  cp -r "$PROJECT_ROOT/rubric/flows/workflows" "$OUTPUT/rubric/flows/"
fi

# Template workflows.json with generic example
cat > "$OUTPUT/rubric/flows/data/workflows.json" << 'WFEOF'
[
  {
    "id": "build-relay",
    "name": "Build Relay",
    "description": "Orchestrator plans → Backend builds → Frontend wires → QA verifies. Tab-by-tab until feature-complete.",
    "agent": "orchestrator",
    "agentName": "Orchestrator",
    "agentDescription": "Plans work, assigns tasks, reviews completed code.",
    "skills": [
      {"id": "plan", "name": "Plan", "description": "Audit what exists, create tasks for what's missing."},
      {"id": "backend", "name": "Backend", "description": "Build API endpoints, database, business logic."},
      {"id": "frontend", "name": "Frontend", "description": "Wire UI components to backend endpoints."},
      {"id": "qa", "name": "QA Verify", "description": "Test everything, file bugs, verify fixes."}
    ]
  },
  {
    "id": "directive-swarm",
    "name": "Directive Swarm",
    "description": "Human directive → observe → plan → build → verify",
    "agent": "pipeline-tester",
    "agentName": "Swarm",
    "agentDescription": "Observe-first loop. Tester scouts, Orchestrator plans, dev agents build, Tester verifies.",
    "skills": [
      {"id": "observe", "name": "Observe", "description": "Open the live app, screenshot state, report findings."},
      {"id": "plan", "name": "Plan", "description": "Synthesize observations into a tactical PRD."},
      {"id": "execute", "name": "Execute", "description": "Dev agents swarm on tasks in parallel."},
      {"id": "verify", "name": "Verify", "description": "Test every acceptance criterion. Retry on failures."}
    ]
  }
]
WFEOF

# ─── 3. Agent Runner (storyengine/agents → agents/) ──────────────────────────
echo "Exporting agent runner..."
mkdir -p "$OUTPUT/agents/roles"
mkdir -p "$OUTPUT/agents/templates"
mkdir -p "$OUTPUT/agents/standing-orders"
mkdir -p "$OUTPUT/agents/blueprints"
mkdir -p "$OUTPUT/agents/memory"
mkdir -p "$OUTPUT/agents/reports"

# Core runner (the engine)
cp "$PROJECT_ROOT/storyengine/agents/run-agent.sh" "$OUTPUT/agents/"
cp "$PROJECT_ROOT/storyengine/agents/notify-telegram.sh" "$OUTPUT/agents/"

# Role files (agent personalities — generic enough to reuse)
for f in "$PROJECT_ROOT/storyengine/agents/"*.md; do
  [ -f "$f" ] && cp "$f" "$OUTPUT/agents/"
done

# Standing orders
for f in "$PROJECT_ROOT/storyengine/agents/standing-orders/"*.md; do
  [ -f "$f" ] && cp "$f" "$OUTPUT/agents/standing-orders/"
done

# ─── 4. Team System (agents/) ────────────────────────────────────────────────
echo "Exporting team system..."
mkdir -p "$OUTPUT/team/roles"
mkdir -p "$OUTPUT/team/templates"

# Core scripts
for f in swarm.sh run-team.sh decompose.sh dispatch.sh verify.sh generate-prd.sh prd-watcher.sh; do
  [ -f "$PROJECT_ROOT/agents/$f" ] && cp "$PROJECT_ROOT/agents/$f" "$OUTPUT/team/"
done

# Roles (observer, synthesizer, verifier, lead, backend, frontend, qa, security)
for f in "$PROJECT_ROOT/agents/roles/"*.md; do
  [ -f "$f" ] && cp "$f" "$OUTPUT/team/roles/"
done

# Templates
for f in "$PROJECT_ROOT/agents/templates/"*; do
  [ -f "$f" ] && cp "$f" "$OUTPUT/team/templates/"
done

# Team config template
cat > "$OUTPUT/team/TEAM.md" << 'TEAMEOF'
# Dev Team Configuration

## Project
- Name: (your project name)
- Stack: (your tech stack — e.g., "Next.js, FastAPI, PostgreSQL")
- Frontend dev: `cd frontend && npm run dev`
- Backend dev: `cd backend && python -m uvicorn main:app --reload --port 8001`
- Test command: `npm test` / `python -m pytest`
- Type check: `cd frontend && npx tsc --noEmit`
- Build: `cd frontend && npm run build`

## Roles
- **lead**: Decomposes PRDs into tasks. Reviews completed work.
- **backend**: API endpoints, database, business logic.
- **frontend**: Components, pages, client wiring.
- **qa**: Playwright testing, acceptance criteria verification.
- **security**: Auth flows, input validation, dependency audits.

## Rules

### Task Rules
- Every task MUST have machine-verifiable acceptance criteria
- Acceptance criteria are shell commands that exit 0 on success
- No task can be marked done without ALL criteria passing
- Each task addresses exactly ONE concern

### Quality Gates
- TypeScript must compile: `npx tsc --noEmit`
- Tests must pass: `npm test` / `pytest`

### Git Rules
- Every completed task gets its own commit
- Pull before starting, push after each commit
- Never force push

### Coordination Rules
- Agents read `progress.md` to know what's done and what's next
- After completing a task, update `progress.md` immediately
- If blocked, mark the task and move on
TEAMEOF

# Empty progress and prd templates
echo '# Progress\n\nNo tasks yet.' > "$OUTPUT/team/progress.md"

# ─── 5. Setup Guide ──────────────────────────────────────────────────────────
cat > "$OUTPUT/README.md" << 'READMEEOF'
# RUBRIC Agent System

An autonomous dev team powered by Claude Code. Give a directive, agents observe → plan → build → verify.

## Quick Start

```bash
# 1. Start the dashboard
cd rubric/scaffold && npm install && node server.js
# Open http://localhost:5050

# 2. Configure your team
# Edit rubric/scaffold/config.json — set your brand name and agent list
# Edit team/TEAM.md — set your project name, stack, and commands

# 3. Give a directive via swarm
./team/swarm.sh "Add user authentication with email/password login"

# 4. Or decompose a PRD
./team/decompose.sh path/to/your-feature.md
# Then run agents:
./team/run-team.sh all
```

## Architecture

```
Human Directive ──→ OBSERVE ──→ PLAN ──→ EXECUTE ──→ VERIFY
                  (tester)   (orchestrator) (devs)   (tester)
```

- **Dashboard**: Real-time agent status, activity feed, controls (ON/OFF, pause, focus)
- **Swarm**: Directive-driven development — observe first, then plan from what's real
- **PRD Mode**: Human writes a spec, lead decomposes into tasks, agents execute
- **Telegram**: Message your bot to control agents from your phone

## Directory Structure

```
rubric/
├── scaffold/          # Dashboard server + UI
│   ├── server.js      # API: agent status, controls, activity log, handoffs
│   ├── index.html     # Dashboard UI (command center, activity, team)
│   ├── config.json    # Agent names, colors, icons
│   └── data/          # Runtime state (controls, handoffs, activity log)
├── flows/             # Workflow visualizer
│   ├── server.js      # WebSocket workflow events
│   └── data/          # Workflow definitions
agents/                # Agent runner + role files
├── run-agent.sh       # Core engine — loads role, memory, handoffs, spawns Claude
├── *.md               # Agent role files (personality + instructions)
├── standing-orders/   # What agents do when task queue is empty
├── memory/            # Persistent lessons (built over time)
└── blueprints/        # Project architecture reference (customize for your stack)
team/                  # Team coordination
├── swarm.sh           # Directive → observe → plan → execute → verify
├── decompose.sh       # PRD → prd.json + progress.md
├── run-team.sh        # Run agents (single role or all)
├── prd-watcher.sh     # Auto-spawn agents when tasks unblock
├── TEAM.md            # Team config (project, stack, rules)
└── roles/             # Role definitions (lead, backend, frontend, qa, etc.)
```

## Customization

1. **Agents**: Edit `rubric/scaffold/config.json` to add/remove/rename agents
2. **Roles**: Edit `agents/*.md` to customize agent behavior for your stack
3. **Blueprints**: Create `agents/blueprints/` files describing your codebase architecture
4. **Workflows**: Edit `rubric/flows/data/workflows.json` to define your pipelines
5. **Telegram**: Run `rubric/scaffold/telegram-channels-setup.sh setup` to connect a bot

## How Agents Coordinate

- **Task Queue** (`task-queue.json`): Source of truth for work
- **Handoffs** (`handoffs.json`): Async messages between agents
- **Controls** (`controls.json`): ON/OFF, pause, focus directive
- **Activity Log** (`activity-log.json`): Real-time audit trail
- **Memory** (`memory/*.md`): Persistent lessons across sessions

## Requirements

- Claude Code (claude CLI) with Max/Pro subscription
- Node.js 18+ (for dashboard)
- A project to work on
READMEEOF

# ─── 6. Package ──────────────────────────────────────────────────────────────
FILE_COUNT=$(find "$OUTPUT" -type f | wc -l | tr -d ' ')
echo ""
echo "=== Export Complete ==="
echo "  Files: $FILE_COUNT"
echo "  Output: $OUTPUT"

if [ "$TAR_MODE" = true ]; then
  TARFILE="$PROJECT_ROOT/rubric-system.tar.gz"
  tar -czf "$TARFILE" -C "$(dirname "$OUTPUT")" "$(basename "$OUTPUT")"
  echo "  Archive: $TARFILE"
  rm -rf "$(dirname "$OUTPUT")"
fi

echo ""
echo "Next steps for your friend:"
echo "  1. Edit rubric/scaffold/config.json (brand name, agent list)"
echo "  2. Edit team/TEAM.md (project name, stack, commands)"
echo "  3. cd rubric/scaffold && npm install && node server.js"
echo "  4. ./team/swarm.sh \"your first directive\""
