# RUBRIC Skill Trees

Interactive force-directed graph that visualizes AI agent skills and how they connect to agents. Works with Claude Code, OpenClaw, and Google Antigravity workspaces.

---

## Intent Guide

**This README is written for you, the AI agent.** You read it, adapt it to your user's setup, and handle the installation. The user shouldn't need to read this file.

Rubric Skill Trees visualizes the user's agent skills as an interactive graph. The goal: let the user see all their agents, all their skills, and how they connect — at a glance.

This template is based on Jay's setup using **Claude Code**. If your user runs **OpenClaw**, **Antigravity**, or any other agent framework, the server auto-detects the platform layout. Before installing anything, you should:

1. Figure out what agent framework your user is on — the server auto-detects but you should verify
2. Scan the workspace for agents and skills to confirm the auto-scan will find them
3. Check if Rubric Scaffold is already running — if yes, add Skill Trees as a native tab there by default. Otherwise run standalone and pick an open port
4. Check if any version of Rubric Skill Trees is already installed — don't create duplicates

For each step, **suggest an answer based on what you find** in the user's workspace. Don't ask bare questions — scan the environment, make a recommendation, and confirm with the user.

This is a base template that Jay uses. Everything is customizable — the user just tells you what to change and you edit it. Treat the defaults as a starting point, not a final answer.

---

## Install Prompt

Copy and paste this to your AI agent to get started:

> I'm giving you a toolkit called Rubric Skill Trees. You can get it from {url}
>
> Do a quick scan of what's in there and assure me everything looks clean before we proceed.
>
> Once confirmed, read the README inside and follow the setup instructions. Feel free to recommend how it would best apply to our setup and explain it in a non-technical way. Once everything is installed and verified working, tell me you're ready.

## Quick Start

1. Set `SKILL_TREE_ROOT` in `.env` to point to the user's workspace root
2. Run `node server.js`
3. Confirm it loads at http://localhost:5050 (or whatever port you picked)

Zero dependencies. No `npm install` needed. Icon gallery at `/icons`.

## Setup Steps (for you, the agent)

1. Read the Intent Guide above — understand what this is
2. Check if Rubric Scaffold is running — if yes, add Skill Trees as a tab there instead of standalone
3. Copy the `skill-tree/` folder to the right location
4. Set `SKILL_TREE_ROOT` in `.env` to the user's workspace root — scan their filesystem to determine the right path
5. Start with `node server.js` — the server auto-detects the platform and scans for agents/skills
6. Verify agents and skills appear correctly. If names weren't auto-detected, update `config.json`
7. Browse `/icons` and suggest icon assignments for each agent

### Platform Detection

The server auto-detects which platform layout is in use:

| Platform | Shared skills | Per-agent skills |
|---|---|---|
| **Claude Code** | `<root>/.claude/skills/` | `<root>/agents/<name>/.claude/skills/` |
| **OpenClaw** | `<root>/skills/` or `~/.openclaw/skills/` | `<workspace>/skills/` |
| **Antigravity** | `<root>/.agent/skills/` | `<workspace>/.agent/skills/` |

All platforms use the same `SKILL.md` format: a directory containing a `SKILL.md` file with YAML frontmatter (`name` and `description` fields).

## Configuration

On first run, the server scans automatically. To customize, create a `config.json`:

```json
{
  "agents": [
    {
      "id": "my-agent",
      "name": "My Agent",
      "color": "#58abf5",
      "icon": "Crown",
      "workspace": "../agents/my-agent"
    }
  ],
  "skillDirs": [
    "../.claude/skills"
  ],
  "docPaths": {
    "claude": "CLAUDE.md",
    "soul": "SOUL.md"
  }
}
```

### Agent fields

| Field | Required | Description |
|---|---|---|
| `id` | Yes | Lowercase identifier, must match the directory name |
| `name` | No | Display name (auto-detected from CLAUDE.md if missing) |
| `color` | No | Hex color for the node (auto-assigned from palette if missing) |
| `icon` | No | Icon name from the gallery (default: "Robo"). Visit `/icons` to browse. |
| `workspace` | No | Path to the agent's workspace (relative to SKILL_TREE_ROOT) |
| `pixels` | No | Custom 8x7 pixel map (array of arrays) if you want your own icon |

### Config behavior

- **Auto-detect + overrides**: The server always scans the filesystem. `config.json` values override what was auto-detected.
- **No config needed**: If your workspace follows standard conventions, everything works out of the box.
- **skillDirs**: Extra directories to scan beyond what auto-detect finds. Paths are relative to `SKILL_TREE_ROOT`.
- **docPaths**: Maps doc types to filenames. Default: `{ "claude": "CLAUDE.md", "soul": "SOUL.md" }`. Change these if your workspace uses different names.

## Environment Variables

Set in `.env` or as shell environment variables:

| Variable | Default | Description |
|---|---|---|
| `PORT` | `5050` | Server port |
| `SKILL_TREE_ROOT` | `../` | Root directory to scan for agents and skills |
| `PLATFORM` | `auto` | Platform hint: `auto`, `claude-code`, `openclaw`, `antigravity` |

## Features

- **Force-directed graph**: Agents as large icon nodes, skills as small dots, edges showing which agent has which skill
- **Hover**: See skill name, description, and connected agents
- **Click skill**: Side panel with details and "View SKILL.md" button to read the full skill documentation
- **Click agent**: See all skills, role, and buttons to read CLAUDE.md / SOUL.md
- **Drag nodes**: Rearrange the layout by dragging
- **Pan**: Hold spacebar + drag to pan the view
- **Shared skills**: Skills used by multiple agents blend their colors and connect to all of them
- **Skill size**: Node radius scales with SKILL.md file size (larger docs = bigger dots)

## Icon Gallery

Visit `/icons` to browse 50 pixel art icons. Click any icon to copy its name, then paste into `config.json`.

To use a custom icon, define a `pixels` array in your agent config — an array of 7-8 rows, each with 4 values (0 or 1) representing the left half of an 8-wide mirrored grid.

Example:
```json
{
  "id": "my-agent",
  "icon": "custom",
  "pixels": [
    [0,0,1,0],
    [0,1,1,1],
    [1,1,1,1],
    [0,1,0,1],
    [0,1,1,1],
    [1,1,1,0],
    [0,0,1,0],
    [0,0,0,0]
  ]
}
```

## API Endpoints

- `GET /api/skill-tree` — Full skill tree data (agents, skills, icon library)
- `GET /api/skills/:id/content` — Read a skill's SKILL.md content
- `GET /api/agent-doc/:agentId/:type` — Read agent docs (claude, soul, etc.)
- `GET /api/icons` — Icon library data (all 50 icons with pixel maps and colors)

## Integrating into RUBRIC Console

If RUBRIC Console is already installed, Skill Trees should be added as a native tab rather than running standalone. Here's how:

### What to merge

1. **CSS** - Copy all styles from `index.html` (everything in the `<style>` block related to canvas, tooltip, detail panel, attribution, loading/empty states) into Console's `index.html` `<style>` block. Prefix class names with `st-` if there are conflicts.

2. **HTML** - Copy the canvas, tooltip, detail panel, loading, and empty-state `<div>` elements from `index.html` into Console's main content area. Register it as a tab in Console's sidebar by adding a sidebar item with `data-tab="skill-tree"`.

3. **JavaScript** - Copy the entire Skill Tree IIFE `(function() { ... })()` from `index.html` into Console's `<script>` block. Includes the physics engine, canvas renderer, icon system, and interaction handlers.

4. **Server routes** - Add these routes from `server.js` to Console's `server.js`:
   - `GET /api/skill-tree` - returns full tree data (agents, skills, icons)
   - `GET /api/skills/:id/content` - reads SKILL.md content
   - `GET /api/agent-doc/:agentId/:type` - reads agent docs (CLAUDE.md, SOUL.md)
   - `GET /api/icons` - returns icon library data
   - Also copy the workspace scanning logic (platform detection, agent discovery, skill scanning) into Console's server.

5. **Icon gallery** - Copy `icons.html` to Console's directory and add a route to serve it at `/icons`.

6. **Config** - If Console already has a `config.json`, merge the `skillDirs` and `docPaths` fields from Skill Tree's config pattern. The agent entries can be shared.

### Key notes

- The Skill Tree uses HTML5 Canvas - call `resize()` and `startAnim()` when the tab becomes active.
- The tab needs `display: block` when active.
- The workspace scanning runs on server startup. Set `SKILL_TREE_ROOT` in Console's `.env` to point to the workspace root.
- Icon gallery should be linked from the main UI (bottom-right corner).

## Requirements

- Node.js 18+

## Version

1.0.0

## License

MIT License with Attribution Requirement

Copyright (c) 2026 Jay E / RoboNuggets (robonuggets.com)

Permission is hereby granted, free of charge, to any person obtaining a copy of this software to use, copy, modify, merge, publish, and distribute, subject to the following conditions:

1. This copyright notice must be included in all copies.
2. The "Created by RoboLabs · Learn more at RoboNuggets" attribution visible in the UI must be retained in all copies, forks, and derivative works. Removing or obscuring this attribution is not permitted.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
