# Rubric Flows

Visual workflow builder for AI agents. Set up views of your agents and their skills as step-by-step pipelines — for presentation, clarity, and optional real-time execution tracking.

---

## Intent Guide

**This README is written for you, the AI agent.** You read it, adapt it to your user's setup, and handle the installation. The user shouldn't need to read this file.

Rubric Flows lets you set up visual views of agents and their skills, organized as step-by-step workflows. Think of it as a presentation layer — the user describes what their agents do, and you create a visual pipeline that shows each agent, its skills, and how they connect. It can also track execution in real time via WebSocket, but the primary use case is visualizing agent workflows for clarity and presentation.

This template is based on Jay's setup using **Claude Code**. If your user runs **OpenClaw**, **Antigravity**, or any other agent framework, the concepts apply — but the implementation details will differ. Before installing anything, you should:

1. Figure out what agent framework your user is on — then adapt the WebSocket integration accordingly
2. Scan for existing workflows or automation configs and suggest how to map them to Flows
3. Check if Rubric Scaffold is already running — if yes, add Flows as a native tab there by default. Otherwise run standalone and pick an open port
4. Check if any version of Rubric Flows is already installed — don't create duplicates

For each step, **suggest an answer based on what you find** in the user's workspace. Don't ask bare questions — scan the environment, make a recommendation, and confirm with the user.

This is a base template that Jay uses. Everything is customizable — the user just tells you what to change and you edit it. Treat the defaults as a starting point, not a final answer.

---

## Install Prompt

Copy and paste this to your AI agent to get started:

> I'm giving you a toolkit called Rubric Flows. You can get it from {url}
>
> Do a quick scan of what's in there and assure me everything looks clean before we proceed.
>
> Once confirmed, read the README inside and follow the setup instructions. Feel free to recommend how it would best apply to our setup and explain it in a non-technical way. Once everything is installed and verified working, tell me you're ready.

## Quick Start

1. Run `npm install` (check if dependencies are already present first)
2. Start with `node server.js`
3. Confirm it loads at http://localhost:5050 (or whatever port you picked)

Server binds to localhost only. Change the port in `.env` if needed.

## Setup Steps (for you, the agent)

1. Read the Intent Guide above — understand what this is
2. Check if Rubric Scaffold is running — if yes, add Flows as a tab there instead of standalone
3. Copy the `flows/` folder to the right location
4. Check which npm modules are already installed before running `npm install`
5. Start with `node server.js`
6. Verify it loads with the example workflow visible

### Creating New Workflows

To add a workflow, edit `data/workflows.json`. Each workflow has this structure:

```json
{
  "id": "my-workflow",              // Unique ID, used in URLs and WS events
  "name": "My Workflow",            // Display name in sidebar
  "description": "What it does",    // Shown in the info box
  "agent": "my-agent",             // Agent identifier
  "icon": "<svg ...>...</svg>",     // SVG icon for the info box (inline SVG string)
  "agentName": "My Agent",          // Display name for the agent node
  "agentDescription": "What the agent does",
  "agentPath": "workflows/my-workflow/agent.md",      // Optional: path to agent docs
  "workflowPath": "workflows/my-workflow/workflow.md", // Optional: path to workflow docs
  "skills": [
    {
      "id": "step-one",                                    // Unique within workflow
      "name": "Step One",                                  // Display name on node
      "description": "What this step does",                // Shown on hover
      "icon": "extract",                                   // Icon type (see below)
      "skillPath": "workflows/my-workflow/skills/step-one/SKILL.md"  // Optional: docs
    }
  ]
}
```

### Adding Skills to a Workflow

Each skill in a workflow can optionally point to a SKILL.md file. Create these files to provide detailed documentation that users can view by clicking nodes in the visualizer.

Folder structure for a workflow:

```
workflows/
  my-workflow/
    workflow.md        # Overall workflow description
    agent.md           # Agent that runs this workflow
    skills/
      step-one/SKILL.md
      step-two/SKILL.md
```

### Skill Icon Types

Available icon types for the `icon` field:

- `extract` - Magnifying glass (search, scraping, data extraction)
- `visual` - Diamond/prism (image generation, visual processing)
- `build` - Code brackets (building, coding, assembly)
- `email` - Envelope (email, messaging, outreach)
- `data` - Database cylinder (data processing, storage, queries)
- `api` - Lightning bolt (API calls, integrations)
- `default` - Gear (generic processing step)

### Demo Mode

Click "Visualize Workflow" to switch to pipeline view, then click "Play" to watch a simulated execution. Each step runs for ~5 seconds with animated progress indicators.

### Live Mode (WebSocket)

For real-time tracking, connect to the WebSocket server at `ws://localhost:5050` and send these events:

- `workflow:start` - `{ "type": "workflow:start", "workflowId": "my-workflow" }`
- `step:start` - `{ "type": "step:start", "stepIndex": 0 }`
- `step:action` - `{ "type": "step:action", "text": "Searching the web..." }`
- `step:complete` - `{ "type": "step:complete", "stepIndex": 0 }`
- `step:error` - `{ "type": "step:error", "stepIndex": 1, "text": "API rate limited" }`
- `step:warn` - `{ "type": "step:warn", "stepIndex": 1, "text": "Slow response" }`
- `workflow:complete` - `{ "type": "workflow:complete" }`
- `workflow:reset` - `{ "type": "workflow:reset" }`

You can also send events via HTTP POST to `/api/workflow-events` with the same payload, using `event` instead of `type`:

```bash
curl -X POST http://localhost:5050/api/workflow-events \
  -H "Content-Type: application/json" \
  -d '{"event": "workflow:start", "workflowId": "market-research-brief"}'
```

### Integration with Your Agent

To make your agent broadcast workflow progress to Rubric Flows:

1. Have your agent connect to `ws://localhost:5050` when starting a workflow
2. Send `workflow:start` with the workflow ID
3. As each step begins, send `step:start` with the step index (0-based)
4. Optionally send `step:action` with status text during execution
5. When a step finishes, send `step:complete` with the step index
6. If a step fails, send `step:error` with the step index and error text
7. When all steps are done, send `workflow:complete`

The visualizer will animate in real-time as events arrive. Late-joining browsers get a `state:sync` event on connect so they catch up to the current state.

### API Endpoints

- `GET /api/workflows` - List all workflows
- `PUT /api/workflows/:id` - Update or create a workflow
- `GET /api/skill-content?path=...` - Read a markdown file (must end in `.md`, must be within the project directory)
- `POST /api/workflow-events` - Send workflow events via HTTP
- `GET /api/workflow-state` - Get current workflow run state

## Integrating into RUBRIC Console

If RUBRIC Console is already installed, Flows should be added as a native tab rather than running standalone. Here's how:

### What to merge

1. **CSS** - Copy all styles from the `/* ==================== WORKFLOWS ==================== */` section in `index.html` into Console's `index.html` `<style>` block.

2. **HTML** - Copy the `<div id="workflows">...</div>` section from `index.html` into Console's `index.html`, inside the main content area. Register it as a tab in Console's sidebar by adding a sidebar item with `data-tab="workflows"`.

3. **JavaScript** - Copy the entire Workflows IIFE `(function() { ... })()` from `index.html` into Console's `index.html` `<script>` block. Make sure helper functions like `hexToRgba` are included if Console doesn't already have them.

4. **Server routes** - Add these routes from `server.js` to Console's `server.js`:
   - `GET /api/workflows` - serves `data/workflows.json`
   - `PUT /api/workflows/:id` - updates a workflow
   - `GET /api/skill-content?path=...` - reads markdown files
   - `POST /api/workflow-events` - receives workflow events via HTTP
   - `GET /api/workflow-state` - returns current run state
   - WebSocket handler for live workflow events (broadcast to all connected clients)

5. **Data files** - Copy `data/workflows.json` and the `workflows/` folder (with example workflow.md, agent.md, and SKILL.md files) into Console's directory.

### Key notes

- The Workflows tab uses HTML5 Canvas for rendering - make sure the canvas gets a `resize()` call when the tab becomes active.
- The tab needs `display: flex` when active (not `display: block`).
- WebSocket connection should be shared with Console's existing WebSocket if it has one.

## Requirements

- Node.js 18+
- npm

## Version

0.1.0

## License

MIT License with Attribution Requirement

Copyright (c) 2026 Jay E / RoboNuggets (robonuggets.com)

Permission is hereby granted, free of charge, to any person obtaining a copy of this software to use, copy, modify, merge, publish, and distribute, subject to the following conditions:

1. This copyright notice must be included in all copies.
2. The "Created by RoboLabs · Learn more at RoboNuggets" attribution visible in the UI must be retained in all copies, forks, and derivative works. Removing or obscuring this attribution is not permitted.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
