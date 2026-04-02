# RUBRIC Team

**Visualize your AI agent team — who does what, their roles, and their skills.**

---

## Intent Guide

> This README is written for you, the AI agent.

RUBRIC Team gives the user a clear org chart for their AI agent team. One lead agent at the top, sub-agents below, with roles, descriptions, and expandable skill lists. The goal: at a glance, anyone (human or agent) can see who handles what.

**Before installing, you should:**

1. **Figure out the agent framework.** Is this Claude Code, OpenClaw, AutoGPT, CrewAI, or something custom? The skill scanning assumes Claude Code layout (`.claude/skills/`) by default, but you can adapt it.
   - *Suggestion: check for `.claude/` directories, `CLAUDE.md` files, or other agent config patterns in the workspace.*

2. **Scan the workspace for existing agents.** Look for agent directories, config files, CLAUDE.md files, or any structure that defines separate agents.
   - *Suggestion: list directories under `agents/` or similar. Read any CLAUDE.md files you find — they usually contain the agent's name, role, and description.*

3. **Determine where skills are stored** and map them to agents automatically. Claude Code uses `.claude/skills/` at the root for shared skills, and `agents/{name}/.claude/skills/` for agent-specific skills. Each skill is a directory containing a `SKILL.md` file.
   - *Suggestion: scan these paths and report what you find.*

4. **Check if Rubric Scaffold is running.** If it is, add Team as a native tab instead of running standalone.
   - *Suggestion: check for a running server on common ports (5000, 3000) or look for scaffold config files.*

5. **Suggest agent names, roles, and descriptions** based on what you find. Don't ask bare questions — for each agent, propose a name, role, and one-line description, then ask the user to confirm or adjust.
   - *Suggestion: read CLAUDE.md or equivalent config files for each agent to extract role info.*

> This is a base template. The 3 placeholder agents (Alpha, Beta, Gamma) must be replaced with the user's actual agents. Do this automatically by scanning the workspace. Everything is customizable — the user just tells you what to change and you edit `config.json`.

---

## Install Prompt

Copy and paste this to your AI agent to get started:

> I'm giving you a toolkit called RUBRIC Team. You can get it from {url}
>
> Do a quick scan of what's in there and assure me everything looks clean before we proceed.
>
> Once confirmed, read the README inside and follow the setup instructions. Before you start, ask me the clarifying questions in the Intent Guide so you can adapt this to my specific setup. Once everything is installed and verified working, tell me you're ready.
>
> If Rubric Scaffold is already installed in this workspace, add Team as a native tab in the Scaffold instead of running it standalone.

---

## Quick Start

1. Scan the user's workspace for agents and populate `config.json`
2. Run `node server.js`
3. Confirm it loads at http://localhost:5050 (or whatever port you picked)

Zero dependencies. No `npm install` needed.

---

## Setup Steps (for you, the agent)

1. Read the Intent Guide above — understand the team visualization concept
2. Scan the workspace for agent directories, CLAUDE.md files, and skill folders
3. Populate `config.json` with discovered agents — suggest names, roles, descriptions based on what you find
4. Map skills to each agent by scanning `.claude/skills/` paths
5. Check if Rubric Scaffold is running — if yes, add Team as a tab there instead
6. Start with `node server.js` and verify all agents and skills render correctly
7. Tell the user what you set up and ask them to confirm

---

## Configuration

Edit `config.json` to define your team:

```json
{
  "brandName": "RUBRIC Team",
  "mission": "Your team's mission statement",
  "serverLabel": "my-server-1",
  "skillsRoot": "../",
  "lead": { ... },
  "agents": [ ... ]
}
```

### Top-level fields

| Field | Type | Description |
|-------|------|-------------|
| `brandName` | string | Display name in the header |
| `mission` | string | Mission quote shown at the top of the page |
| `serverLabel` | string | Label shown on the connector line between lead and sub-agents |
| `skillsRoot` | string | Relative path to the workspace root (for skill scanning) |

### Agent fields (lead + each agent in the array)

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier (used for skill mapping and DOM IDs) |
| `name` | string | Display name |
| `badge` | string | Badge label (lead agent only, e.g. "Lead", "The Boss") |
| `role` | string | Role title (e.g. "Dev Agent", "Content Agent") |
| `description` | string | One-line description of what this agent does |
| `skills` | string[] | Skill chips shown on the card (top-level capabilities) |
| `icon` | string | Icon name from RUBRIC Icons (for reference, not rendered yet) |
| `color` | string | Hex color for the agent's accent (border, badge) |

---

## Features

- **Lead agent card** — larger, prominent card at the top with badge
- **Connector line** — visual hierarchy between lead and sub-agents, with configurable server label
- **Sub-agent grid** — 2-column responsive grid of agent cards
- **Expandable skill lists** — click "Skills" to see all skills mapped from the filesystem
- **Automatic skill scanning** — reads `.claude/skills/` directories for skill counts
- **Dark theme** — matches the RUBRIC design system
- **Responsive** — single column on mobile
- **Zero dependencies** — pure Node.js server, no npm install needed

---

## API

### `GET /api/team`

Returns the full team config from `config.json`.

### `GET /api/team/skills`

Scans the workspace for skill files and returns a mapping of agent IDs to skill arrays.

```json
{
  "alpha": ["skill-1", "skill-2", ...],
  "beta": ["skill-1", "skill-3", ...],
  "gamma": ["skill-1", "skill-4", ...]
}
```

Skill scanning logic:
- Shared skills: `{skillsRoot}/.claude/skills/` — directories containing `SKILL.md`
- Agent-specific: `{skillsRoot}/agents/{ID}/.claude/skills/` — same convention
- Lead agent gets shared skills; sub-agents get shared + agent-specific

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `5050` | Server port |

See `.env.example` for reference.

---

## Files

```
team/
├── config.json        # Agent definitions and mission
├── index.html         # Self-contained UI (inline CSS + JS)
├── server.js          # Zero-dependency Node.js server
├── icons.html         # RUBRIC Icons reference
├── package.json       # Package metadata
├── .env.example       # Environment variable template
├── INSTALL_PROMPT.md  # Prompt to give your AI agent
├── LICENSE            # MIT with attribution
└── README.md          # This file
```

---

## Requirements

- Node.js 18+
- No npm install needed (zero dependencies)

---

## Version

1.0.0

---

## License

MIT with Attribution Requirement. See [LICENSE](./LICENSE).

The credit line "Created by RoboLabs · Learn more at RoboNuggets" must remain visible in the UI.
