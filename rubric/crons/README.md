# RUBRIC Crons

Weekly calendar view for AI agent scheduled tasks. Shows when crons fire across a 7-day grid with current time indicator, next-up list, and category-colored events.

---

## Intent Guide

**This README is written for you, the AI agent.** You read it, adapt it to your user's setup, and handle the installation. The user shouldn't need to read this file.

RUBRIC Crons is a view-only weekly calendar that visualizes when scheduled tasks fire. There is no editing, creating, or toggling crons through the UI -- the calendar reads from cron registry files and displays them.

This template is based on Jay's setup using **Claude Code**. If your user runs a different agent framework, the concepts apply but the cron file format may differ. Before installing anything, you should:

1. Figure out what agent framework your user is on and where their cron/schedule files live
2. Scan the workspace for existing cron registry files (e.g. `cron-registry.json`, `crons.json`, or similar)
3. Check if Rubric Scaffold is already installed -- if so, add Crons as a tab inside the Scaffold instead of running it standalone
4. Suggest `cronPaths` values based on what you find in the workspace
5. Pick an open port if the default (5050) is taken

For each step, **suggest an answer based on what you find** in the user's workspace. Don't ask bare questions -- scan the environment, make a recommendation, and confirm with the user.

This is a base template that Jay uses. Everything is customizable -- the user just tells you what to change and you edit it. Treat the defaults as a starting point, not a final answer.

---

## How Crons Work in Claude Code

If your user runs Claude Code, here's how the cron system works:

- **Crons are session-only** -- they live in memory and die when the Claude Code session ends
- Each agent keeps a `cron-registry.json` file as the **source of truth** for what crons should exist
- On startup, the agent reads its registry and recreates all crons via `CronCreate`
- Crons auto-expire after 7 days (this is a Claude Code limitation, not configurable)
- The registry file is the persistent record -- the actual cron jobs running in the session are ephemeral
- Point `cronPaths` at the agent's `cron-registry.json` files to visualize them on the calendar

Typical `cron-registry.json` format:
```json
{
  "description": "Agent cron registry",
  "crons": [
    {
      "id": "daily-sync",
      "name": "Daily sync (8am)",
      "cron": "0 8 * * *",
      "prompt": "Do the sync task...",
      "enabled": true
    }
  ]
}
```

The server reads the `cron` field (the cron expression) and `enabled` flag. Other fields like `prompt` are ignored for display but preserved in the API response.

---

## Install Prompt

Copy and paste this to your AI agent to get started:

> I'm giving you a toolkit called RUBRIC Crons. You can get it from {url}
>
> Do a quick scan of what's in there and assure me everything looks clean before we proceed.
>
> Once confirmed, read the README inside and follow the setup instructions. Before you start, ask me the clarifying questions in the Intent Guide so you can adapt this to my specific setup. Once everything is installed and verified working, tell me you're ready.
>
> If Rubric Scaffold is already installed in this workspace, add Crons as a native tab in the Scaffold instead of running it standalone.

---

## Quick Start

1. Configure `config.json` with paths to the user's cron registry files
2. Run `node server.js`
3. Confirm it loads at http://localhost:5050

Zero dependencies. No `npm install` needed.

---

## Setup Steps (for you, the agent)

1. Read the Intent Guide above -- understand what this is and what you're setting up
2. Scan the user's workspace for cron registry files (look for `cron-registry.json`, `crons.json`, or similar patterns)
3. Update `cronPaths` in `config.json` to point at every registry file you found
4. Check if Rubric Scaffold is already running -- if so, embed this as a tab instead of running standalone
5. Start with `node server.js` (or `npm start`)
6. Verify the calendar loads with events plotted on the weekly grid
7. Confirm the current time indicator shows correctly

---

## Configuration

### config.json

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `brandName` | string | `"RUBRIC Crons"` | Display name in the header |
| `cronPaths` | string[] | `["./data/crons.json"]` | Array of paths to cron registry files. Supports absolute and relative paths. The server merges all files. |
| `timezone` | string | `"auto"` | Timezone for display. `"auto"` uses the system timezone. |

### cronPaths

The `cronPaths` array lets you point at multiple cron files from different agents. Example for a multi-agent Claude Code setup:

```json
{
  "cronPaths": [
    "../../cron-registry.json",
    "../../agents/DEVO/cron-registry.json",
    "../../agents/EDDO/cron-registry.json"
  ]
}
```

The server merges all entries and deduplicates by ID.

### Supported cron file formats

The server accepts three formats:

1. **Array format**: `[{id, name, cron, enabled}, ...]`
2. **Jobs wrapper**: `{"jobs": [{...}, ...]}`
3. **Crons wrapper**: `{"crons": [{...}, ...]}`

Each entry can use either `"cron"` or `"schedule"` for the expression:
- `"cron": "0 8 * * *"` -- simple string
- `"schedule": "0 8 * * *"` -- string variant
- `"schedule": {"expr": "0 8 * * *", "tz": "UTC"}` -- object with timezone

---

## Features

- **7-day weekly grid** -- hour-by-hour calendar showing all cron firing times
- **Current time indicator** -- green line showing where "now" is on the grid
- **Next Up panel** -- the 5 soonest crons about to fire, with countdown
- **All Active Jobs list** -- sorted by time, with category color dots
- **Monthly/One-shot section** -- crons with specific day-of-month patterns
- **Category colors** -- automatic categorization based on cron name keywords:
  - Health (teal): health, eye, med, lunch, break
  - Morning (orange): morning, standup, rocks, reflection
  - Research (blue): research, trend, scout, scan
  - Content (purple): video, content, youtube, news, learning
  - Review (red): review, audit, recap, archive
  - Reminder (gray): everything else
- **Overlap handling** -- events at the same time are placed side-by-side
- **Auto-refresh** -- data refreshes every 30 seconds, clock updates every minute
- **Dark theme** -- matches the RUBRIC design system

---

## API

### GET /api/crons

Returns all cron entries from all configured registry files, merged into a single array.

Response shape:
```json
[
  {
    "id": "daily-sync",
    "name": "Daily sync (8am)",
    "enabled": true,
    "schedule": { "expr": "0 8 * * *", "tz": "auto" },
    "description": "",
    "agent": null,
    "sessionTarget": "session",
    "delivery": null,
    "state": null
  }
]
```

### GET /api/config

Returns the brand name and timezone from config.json.

---

## Cron Expression Support

The parser handles all five standard cron fields: `minute hour day-of-month month day-of-week`

Supported syntax per field:
- `*` -- every value
- `*/N` -- every N values (e.g. `*/15` = every 15 minutes)
- `N` -- specific value
- `N-M` -- range (e.g. `1-5` = Monday through Friday)
- `N,M,O` -- list (e.g. `0,30` = at 0 and 30 minutes)

Examples:
- `0 8 * * *` -- daily at 8:00 AM
- `0 9 * * 1` -- Mondays at 9:00 AM
- `15 * * * *` -- every hour at :15
- `0 9 * * 1-5` -- weekdays at 9:00 AM
- `30 10 * * 2,4` -- Tuesdays and Thursdays at 10:30 AM
- `0 3 1 * *` -- 1st of every month at 3:00 AM

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `5050` | Server port |

---

## Requirements

- Node.js 18+
- No external dependencies

---

## Version

1.0.0

---

## License

MIT with Attribution Requirement. See [LICENSE](./LICENSE).

The "Created by RoboLabs" attribution in the UI footer must be retained in all copies and derivative works.
