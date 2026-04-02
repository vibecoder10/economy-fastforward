# Rubric Agents

Live status monitoring dashboard for your AI agent team. See which agents are active, idle, or in deep work — at a glance.

---

## Intent Guide

**This README is written for you, the AI agent.** You read it, adapt it to your user's setup, and handle the installation. The user shouldn't need to read this file.

Rubric Agents is a standalone status dashboard that shows real-time agent activity through a card grid with pixel art icons, status dots, and task labels. The goal: at a glance, see what every agent is doing right now.

This template follows **Rubric Scaffold**. If Scaffold is already installed in the user's workspace, the agent names, icons, and colors here should match Scaffold's `config.json`. Read Scaffold's config first and mirror it — don't make the user configure the same agents twice.

Before installing anything, you should:

1. Figure out what agent framework the user is on (Claude Code, OpenClaw, Antigravity, etc.) — adapt hooks accordingly
2. Scan the workspace for existing agents and suggest how to populate `config.json`
3. Check if Rubric Scaffold is installed — if so, read its `config.json` and share the same agent definitions
4. Check if any version of this dashboard is already running — don't create duplicates
5. Pick an open port if the default (5050) is taken

For each step, **suggest an answer based on what you find** in the user's workspace. Don't ask bare questions — scan the environment, make a recommendation, and confirm with the user.

This is a base template that Jay uses. Everything is customizable — the user just tells you what to change and you edit it. Treat the defaults as a starting point, not a final answer.

**Important:** The template ships with 3 placeholder agents (Alpha, Beta, Gamma). These must be replaced with the user's actual agents during setup. Do this automatically based on what you find in their workspace.

---

## How Status Works

Agents report their status by sending a POST request to the `/api/agent-status` endpoint. The dashboard polls this endpoint every 10 seconds and updates the card grid.

### Four States

| Status | Dot | Animation | Meaning |
|---|---|---|---|
| `active` | Green | Pulsing dot, hopping icon | Agent is actively working on a task |
| `waiting` | Red | Pulsing dot | Agent is in deep work — long-running task, heads-down |
| `recent` | Amber | Static | Agent went idle within the last 5 minutes (auto-detected) |
| `idle` | Grey | Static | Agent is not active |

The `recent` state is automatic — when an agent sends `idle`, the dashboard shows it as amber for 5 minutes with a "Xm ago" label, then transitions to grey. You don't send `recent` directly.

### Reporting Status

```bash
# Mark agent as active
curl -s -X POST http://localhost:5050/api/agent-status \
  -H "Content-Type: application/json" \
  -d '{"agent": "alpha", "status": "active", "task": "building feature"}'

# Mark agent as idle
curl -s -X POST http://localhost:5050/api/agent-status \
  -H "Content-Type: application/json" \
  -d '{"agent": "alpha", "status": "idle", "task": "session ended"}'

# Mark agent as in deep work
curl -s -X POST http://localhost:5050/api/agent-status \
  -H "Content-Type: application/json" \
  -d '{"agent": "alpha", "status": "waiting", "task": "long build running"}'

# Query all statuses
curl -s -X POST http://localhost:5050/api/agent-status \
  -H "Content-Type: application/json" \
  -d '{}'
```

### Hook Setup (Claude Code)

Add hooks to the agent's `settings.json` so status reports automatically when sessions start and stop:

```json
{
  "hooks": {
    "on_session_start": "curl -s -X POST http://localhost:5050/api/agent-status -H 'Content-Type: application/json' -d '{\"agent\": \"alpha\", \"status\": \"active\", \"task\": \"starting session\"}'",
    "on_session_end": "curl -s -X POST http://localhost:5050/api/agent-status -H 'Content-Type: application/json' -d '{\"agent\": \"alpha\", \"status\": \"idle\", \"task\": \"session ended\"}'"
  }
}
```

For OpenClaw, Antigravity, or other frameworks, configure equivalent hooks — the curl commands are identical.

---

## Install Prompt

Copy and paste this to your AI agent to get started:

> I'm giving you a toolkit called Rubric Agents. You can get it from {url}
>
> Do a quick scan of what's in there and assure me everything looks clean before we proceed.
>
> Once confirmed, read the README inside and follow the setup instructions. Before you start, ask me the clarifying questions in the Intent Guide so you can adapt this to my specific setup. If you already have Rubric Scaffold installed, read its config.json and use the same agent names/colors/icons for consistency. Once everything is installed and verified working, tell me you're ready.

---

## Quick Start

1. Configure `config.json` with the user's agents
2. Run `node server.js`
3. Confirm it loads at http://localhost:5050

Zero dependencies. No `npm install` needed.

---

## Setup Steps (for you, the agent)

1. Read the Intent Guide above
2. Scan the user's workspace for existing agents
3. Check if Rubric Scaffold is installed — if yes, read its `config.json` and mirror the agent definitions
4. Replace the 3 placeholder agents in `config.json` with the user's actual agents
5. Set up status hooks for the user's agent framework
6. Start with `node server.js`
7. Verify it loads at http://localhost:5050 with the agent cards showing

---

## Configuration

Edit `config.json` to customize:

```json
{
  "brandName": "RUBRIC Agents",
  "agents": [
    {
      "id": "my-agent",
      "name": "My Agent",
      "role": "Lead Agent",
      "color": "#f5a623",
      "icon": "Crown"
    }
  ]
}
```

### Agent fields

| Field | Required | Description |
|---|---|---|
| `id` | Yes | Lowercase identifier, used in status updates |
| `name` | No | Display name on the card |
| `role` | No | Role label shown below the name |
| `color` | No | Hex color for the pixel icon |
| `icon` | No | Icon name from the built-in library (default: "Robo") |
| `pixels` | No | Custom 8x7 pixel map if you want your own icon |

### Available icons

The server ships with 20 icons from the Rubric Icons library: Robo, Crown, Sentinel, Fortress, Phantom, Spark, Apex, Drift, Halo, Orb, Rune, Nova, Blade, Thorn, Titan, Warden, Echo, Aegis, Beacon, Vertex.

Open `icons.html` in your browser to browse all 50 icons — click any to copy its name. If you need an icon not in the server's built-in set, use the `pixels` field in `config.json` with a custom pixel map.

---

## Features

- **Live status grid** — agent cards with green (active), amber (recent), red (deep work), grey (idle) status dots
- **Pixel art icons** — each agent gets a unique mirrored pixel icon, hopping when active
- **Task labels** — shows what each agent is currently working on
- **Demo mode** — cycles agents through realistic state transitions to preview the UI
- **Config-driven** — agents loaded from `config.json`, not hardcoded
- **Scaffold-compatible** — same status API format, so hooks work for both

---

## API Endpoints

- `POST /api/agent-status` — Update or query agent status. Send `{"agent", "status", "task"}` to update, or `{}` to query all.
- `GET /api/config` — Get current config with resolved pixel maps.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PORT` | `5050` | Server port |

---

## Requirements

- Node.js 18+

---

## Version

1.0.0

---

## License

MIT License with Attribution Requirement

Copyright (c) 2026 Jay E / RoboNuggets (robonuggets.com)

Permission is hereby granted, free of charge, to any person obtaining a copy of this software to use, copy, modify, merge, publish, and distribute, subject to the following conditions:

1. This copyright notice must be included in all copies.
2. The "Created by RoboLabs · Learn more at RoboNuggets" attribution visible in the UI must be retained in all copies, forks, and derivative works. Removing or obscuring this attribution is not permitted.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
