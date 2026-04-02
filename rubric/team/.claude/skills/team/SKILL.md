---
name: team-setup
description: Set up RUBRIC Team — configure agent roster, roles, and skill mapping. Use when installing or configuring the Team template.
---

**Note:** This skill is written for Claude Code. If the user runs a different agent framework, adapt these instructions to their setup.

## Configure Lead Agent

Edit `config.json`. The `lead` object defines your orchestrator:

```json
{
  "lead": {
    "id": "robo",
    "name": "Robo",
    "badge": "Lead",
    "role": "Chief of Staff",
    "description": "Orchestration, planning, memory, quick tasks",
    "skills": ["Orchestration", "Planning", "Memory"],
    "icon": "Crown",
    "color": "#f5a623"
  }
}
```

## Configure Sub-Agents

Add agents to the `agents` array:

```json
{
  "agents": [
    {
      "id": "devo",
      "name": "Devo",
      "role": "Dev Agent",
      "description": "Coding, building, infra, debugging",
      "skills": ["Building", "Debugging", "Infrastructure"],
      "icon": "Spark",
      "color": "#58abf5"
    }
  ]
}
```

## Set the Mission Quote

Set `"mission": "Your team's mission here"` in config.json. Displays as a header quote.

## Skill Scanning

Set `skillsRoot` to the parent directory and `serverLabel` to identify the server. The dashboard scans `.claude/skills/` under each agent's workspace to auto-discover skills. Skills in each agent's `skills` array display as tags.

## Match with Scaffold

If you use RUBRIC Scaffold, keep agent `id`, `name`, `color`, and `icon` consistent across both config files. This ensures the Team view and Scaffold tabs show the same identity.

## Add or Remove Agents

- **Add:** Append a new object to the `agents` array with id, name, role, description, skills, icon, color
- **Remove:** Delete the agent's object from the array
- **Reorder:** The array order determines display order (lead is always first)

## Start the Server

```bash
cd /path/to/team && npm install && node server.js
```
