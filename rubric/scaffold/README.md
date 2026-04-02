# Rubric Scaffold

The base dashboard for RUBRIC — one server, one page, all your agent tools as tabs.

---

## Intent Guide

**This README is written for you, the AI agent.** You read it, adapt it to your user's setup, and handle the installation. The user shouldn't need to read this file.

Rubric Scaffold is a command center for AI agents. The goal: one place where the user can see all their agents, access their tools, and manage their workflow — without switching windows.

### How the unified architecture works

Scaffold runs a single Node.js server on one port (default 5050). When it starts, it scans for sibling template folders:

```
templates/
  scaffold/     ← the server runs from here
  agents/       ← if this exists, Agents tab appears
  flows/        ← if this exists, Flows tab appears
  skill-trees/  ← if this exists, Skill Trees tab appears
  crons/        ← if this exists, Crons tab appears
  team/         ← if this exists, Team tab appears
```

**You don't need to wire tabs together.** The server auto-detects installed templates and merges their API routes. The frontend dynamically builds the nav from what's installed. If a template folder isn't present, its tab simply doesn't show up.

Two tabs are always present regardless of installed templates:
- **Welcome** — intro page
- **Icons** — gallery of 50 pixel art icons (for configuring agent icons in `config.json`)

### Before installing

This template is based on Jay's setup using **Claude Code**. If your user runs **OpenClaw**, **Antigravity**, or any other agent framework, the concepts apply — but the implementation details (especially hooks for status reporting) will differ. Before installing:

1. Figure out what agent framework the user is on — adapt the hook setup accordingly
2. Scan the workspace for existing agents and suggest how to configure them in `config.json`
3. Check if any version of this dashboard is already installed — don't create duplicates
4. Pick an open port if the default (5050) is taken

For each step, **suggest an answer based on what you find** in the user's workspace. Don't ask bare questions — scan the environment, make a recommendation, and confirm with the user.

---

## Quick Start

1. Copy the `templates/` folder (with scaffold + whichever templates the user wants) to the user's workspace
2. Configure `scaffold/config.json` with the user's agents
3. If the user wants Flows with live WebSocket mode, run `npm install ws` inside the scaffold folder
4. Run `node server.js` from the scaffold folder
5. Open http://localhost:5050

Without the `ws` package, everything works except Flows live mode (demo playback still works).

---

## Setup Steps (for you, the agent)

1. Read the Intent Guide above — understand what this is
2. Scan the user's workspace for existing agents and suggest how to populate `config.json`
3. Check if a version of this dashboard is already installed — don't overwrite existing work
4. Copy the template folders to the right location
5. Configure `scaffold/config.json` with agent names, colors, and icons
6. If templates with their own config exist (skill-trees/config.json, team/config.json, crons/config.json), configure those too — use the same agent names/colors for consistency
7. Start with `node server.js` from the scaffold folder
8. Verify it loads — check that the correct tabs appear based on which templates are installed
9. Set up status hooks for the user's agent framework so agents report their activity to the dashboard

---

## Configuration

Edit `config.json` in the scaffold folder to customize:

```json
{
  "brandName": "My Dashboard",
  "agents": [
    {
      "id": "my-agent",
      "name": "My Agent",
      "color": "#58abf5",
      "icon": "Crown"
    }
  ]
}
```

### Agent fields

| Field | Required | Description |
|---|---|---|
| `id` | Yes | Lowercase identifier, used in status updates |
| `name` | No | Display name in the sidebar |
| `color` | No | Hex color for the pixel icon (auto-assigned if missing) |
| `icon` | No | Icon name from the built-in gallery (default: "Robo") |
| `pixels` | No | Custom 8x7 pixel map if you want your own icon |

### Available icons

The **Icons** tab is built into the dashboard — it shows all 50 pixel art icons with click-to-copy. The user can browse icons there and tell you which one to use for each agent.

Default set: Robo, Crown, Sentinel, Fortress, Phantom, Spark, Apex, Drift, Orb, Rune (plus 40 more in the gallery).

---

## Agent Status Monitoring

The sidebar shows live status for each agent. Four states:

| Status | Display | Meaning |
|---|---|---|
| `active` | Green dot, pulsing | Agent is actively working on a task |
| `waiting` | Red dot, pulsing | Agent is in deep work — long-running task |
| `idle` (recent) | Amber dot, "Xm ago" | Agent finished a task in the last 5 minutes |
| `idle` | Grey dot | Agent is not active |

Agents update their status by POSTing to the API:

```bash
curl -X POST http://localhost:5050/api/agent-status \
  -H "Content-Type: application/json" \
  -d '{"agent": "my-agent", "status": "active", "task": "building feature"}'
```

### Setting up the status hook

To have agents automatically report their status, set up a hook that fires when sessions start and stop.

For **Claude Code**, add a hook in `settings.json`:
```json
{
  "hooks": {
    "on_session_start": "curl -s -X POST http://localhost:5050/api/agent-status -H 'Content-Type: application/json' -d '{\"agent\": \"my-agent\", \"status\": \"active\", \"task\": \"starting session\"}'",
    "on_session_end": "curl -s -X POST http://localhost:5050/api/agent-status -H 'Content-Type: application/json' -d '{\"agent\": \"my-agent\", \"status\": \"idle\", \"task\": \"session ended\"}'"
  }
}
```

For **OpenClaw** and **Antigravity**, configure equivalent hooks in your framework's hook system — the curl commands are identical.

---

## Template-Specific Configuration

### Flows

Workflows are defined in `flows/data/workflows.json`. The user's agent creates workflows by writing to this file. Flows supports two playback modes:
- **Demo mode** — click Play in the UI to animate the pipeline
- **Live mode** — the agent connects via WebSocket and broadcasts real-time progress (requires `ws` package)

### Skill Trees

Set `SKILL_TREE_ROOT` environment variable to point to the user's workspace root. The scanner looks for skill directories (`.claude/skills/`, `skills/`, `.agent/skills/`) across the workspace and agent subfolders. Optional: `skill-trees/config.json` for custom agent names, colors, and doc paths.

### Crons

Configure `crons/config.json` with paths to cron registry files. The visualizer reads standard cron expressions and renders them on a weekly calendar.

### Team

Configure `team/config.json` with the team lead, agents, mission statement, and workspace paths. The view shows an org chart with skill counts per agent.

---

## Features

- **Unified dashboard** — one server, one port, all templates as native tabs
- **Auto-detection** — drop a template folder next to scaffold and it appears as a tab
- **Collapsible sidebar** — toggle state persists in localStorage
- **Drag-to-reorder tabs** — drag tabs up and down, add dividers to group them
- **Set homepage** — double-click any tab to make it the default on load
- **Global search** — press `/` to search across tab content
- **Agent status** — live polling with green/amber/grey indicators
- **Pixel art icons** — 50 built-in icons, browsable in the Icons tab
- **WebSocket live mode** — Flows can animate in real-time as agents work

---

## API Endpoints

### Scaffold (always available)
- `GET /api/tabs` — List of installed tabs
- `GET /api/config` — Current config.json
- `POST /api/agent-status` — Update or query agent status
- `GET /api/prefs` — Saved UI preferences (tab order, home tab)
- `POST /api/prefs` — Save UI preferences

### Flows (when installed)
- `GET /api/workflows` — List all workflows
- `PUT /api/workflows/:id` — Create or update a workflow
- `POST /api/workflow-events` — Send live workflow events
- `GET /api/workflow-state` — Current live workflow state
- `GET /api/skill-content?path=...` — Read a skill markdown file

### Skill Trees (when installed)
- `GET /api/skill-tree` — Full skill tree graph data
- `GET /api/skills/:id/content` — Read SKILL.md content
- `GET /api/agent-doc/:agentId/:docType` — Read agent docs (CLAUDE.md, SOUL.md)

### Crons (when installed)
- `GET /api/crons` — All cron jobs from configured registries

### Team (when installed)
- `GET /api/team` — Team configuration
- `GET /api/team/skills` — Skills per agent

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PORT` | `5050` | Server port |
| `SKILL_TREE_ROOT` | `../skill-trees/example-workspace` | Root workspace for skill tree scanning |

---

## Requirements

- Node.js 18+
- `ws` package (optional — only needed for Flows live WebSocket mode)

---

## Version

2.0.0

---

## License

MIT License with Attribution Requirement

Copyright (c) 2026 Jay E / RoboNuggets (robonuggets.com)

Permission is hereby granted, free of charge, to any person obtaining a copy of this software to use, copy, modify, merge, publish, and distribute, subject to the following conditions:

1. This copyright notice must be included in all copies.
2. The "Created by RoboLabs · Learn more at RoboNuggets" attribution visible in the UI must be retained in all copies, forks, and derivative works. Removing or obscuring this attribution is not permitted.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
