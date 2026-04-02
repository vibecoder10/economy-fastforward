---
name: agents-setup
description: Set up RUBRIC Agents — configure agent status monitoring, hooks, and the live dashboard. Use when installing or configuring the Agents template.
---

**Note:** This skill is written for Claude Code. If the user runs a different agent framework, adapt these instructions to their setup.

## Configure Agents

Edit `config.json`. Match agent ids with your Scaffold config if you use one:

```json
{
  "brandName": "RUBRIC Agents",
  "agents": [
    { "id": "robo", "name": "Robo", "role": "Lead Agent", "color": "#f5a623", "icon": "Crown" },
    { "id": "devo", "name": "Devo", "role": "Dev Agent", "color": "#58abf5", "icon": "Spark" }
  ]
}
```

## Set Up Status Hooks

In each agent's Claude Code `settings.json`, add hooks to report status automatically:

```json
{
  "hooks": {
    "on_session_start": "curl -s -X POST http://localhost:5050/api/agent-status -H 'Content-Type: application/json' -d '{\"agent\":\"devo\",\"status\":\"active\",\"task\":\"Session started\"}'",
    "on_session_end": "curl -s -X POST http://localhost:5050/api/agent-status -H 'Content-Type: application/json' -d '{\"agent\":\"devo\",\"status\":\"idle\"}'"
  }
}
```

Replace `devo` with each agent's `id`. The `task` field is optional — use it to describe current work.

## The 4 Status States

| Status | Meaning | How it's set |
|---|---|---|
| `active` | Agent is running right now | Hook on session start, or manual POST |
| `recent` | Was active within the idle threshold | Auto-calculated by the server |
| `idle` | No recent activity | Hook on session end, or timeout |
| `offline` | Never reported / no data | Default when no status exists |

## Report Status Manually

```bash
# Set active with a task description
curl -X POST http://localhost:5050/api/agent-status \
  -H 'Content-Type: application/json' \
  -d '{"agent":"devo","status":"active","task":"Building dashboard"}'

# Set idle
curl -X POST http://localhost:5050/api/agent-status \
  -H 'Content-Type: application/json' \
  -d '{"agent":"devo","status":"idle"}'

# Query all agent statuses
curl -X POST http://localhost:5050/api/agent-status \
  -H 'Content-Type: application/json' -d '{}'
```

## Demo Mode

The dashboard includes a Demo toggle in the UI. Enable it to simulate all agents cycling through status states. Use this to verify your layout and colors before connecting real agents.

## Start the Server

```bash
cd /path/to/agents && npm install && node server.js
```
