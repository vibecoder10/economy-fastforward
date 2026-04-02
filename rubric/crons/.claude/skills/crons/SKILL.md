---
name: crons-setup
description: Set up RUBRIC Crons — configure cron registry paths and visualize scheduled tasks. Use when installing or configuring the Crons template.
---

**Note:** This skill is written for Claude Code. If the user runs a different agent framework, adapt these instructions to their setup.

## Configure Cron Paths

Edit `config.json` to point at one or more cron registry files:

```json
{
  "brandName": "RUBRIC Crons",
  "cronPaths": [
    "./data/crons.json",
    "../../cron-registry.json",
    "../../agents/DEVO/cron-registry.json"
  ],
  "timezone": "auto"
}
```

Each path is relative to the template directory. The dashboard reads all files and merges them into one view. Set `timezone` to `"auto"` (uses browser timezone) or a specific IANA zone like `"America/New_York"`.

## How Claude Code Crons Work

Claude Code crons are **session-only** — they run as long as the Claude Code session is active. Key properties:
- Rebuilt on every session restart (from cron-registry.json)
- Auto-expire after 7 days if not refreshed
- Not system-level crontab entries; they run inside the agent process

## cron-registry.json Format

```json
[
  {
    "id": "daily-standup",
    "name": "Daily Standup",
    "schedule": "0 9 * * *",
    "enabled": true,
    "command": "Send standup summary to Telegram",
    "lastRun": null,
    "createdAt": "2026-03-27T00:00:00Z"
  }
]
```

Required fields: `id`, `name`, `schedule`, `enabled`. The `command` field describes what the cron does (for agent and dashboard display).

## Add Multiple Cron Files

To visualize crons from multiple agents, add each agent's `cron-registry.json` path to the `cronPaths` array. The dashboard labels each cron with its source file.

## Cron Expression Syntax

```
┌───────────── minute (0-59)
│ ┌─────────── hour (0-23)
│ │ ┌───────── day of month (1-31)
│ │ │ ┌─────── month (1-12)
│ │ │ │ ┌───── day of week (0-6, Sun=0)
│ │ │ │ │
* * * * *
```

Examples:
- `0 9 * * *` — daily at 9 AM
- `*/15 * * * *` — every 15 minutes
- `0 9 * * 1-5` — weekdays at 9 AM
- `30 8,17 * * *` — 8:30 AM and 5:30 PM daily

## Start the Server

```bash
cd /path/to/crons && npm install && node server.js
```
