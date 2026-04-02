---
name: scaffold-setup
description: Set up RUBRIC Scaffold — configure agents, tabs, status hooks, and the dashboard. Use when installing or configuring the Scaffold template.
---

**Note:** This skill is written for Claude Code. If the user runs a different agent framework, adapt these instructions to their setup.

## Configure Agents

Edit `config.json` in the scaffold folder. Each agent needs: id, name, color (hex), icon (pixel art name).

```json
{
  "brandName": "My Console",
  "agents": [
    { "id": "dev", "name": "Dev", "color": "#58abf5", "icon": "Crown" },
    { "id": "ops", "name": "Ops", "color": "#50e3c2", "icon": "Spark" }
  ]
}
```

## Set Up Status Hooks

In your Claude Code `settings.json`, add hooks so agents report status on session start/end:

```json
{
  "hooks": {
    "on_session_start": "curl -s -X POST http://localhost:5050/api/agent-status -H 'Content-Type: application/json' -d '{\"agent\":\"dev\",\"status\":\"active\"}'",
    "on_session_end": "curl -s -X POST http://localhost:5050/api/agent-status -H 'Content-Type: application/json' -d '{\"agent\":\"dev\",\"status\":\"idle\"}'"
  }
}
```

Replace `dev` with the agent's `id` from config.json. Repeat for each agent.

## How Templates Work

All RUBRIC templates run as native tabs inside Scaffold on a single port (5050). No separate ports, no iframes.

The server auto-detects sibling template folders. If `flows/` exists next to `scaffold/`, the Flows tab appears. If `crons/` exists, the Crons tab appears. Just drop the folder and restart the server.

## Browse Icons

The **Icons** tab is built into the dashboard — it shows all 50 pixel art icons with click-to-copy names. Use the exact name string in your config.json `icon` field.

## Start the Server

```bash
cd /path/to/scaffold && node server.js
# Default port: 5050 (override with PORT env var)
# Optional: npm install ws (for Flows live WebSocket mode)
```
