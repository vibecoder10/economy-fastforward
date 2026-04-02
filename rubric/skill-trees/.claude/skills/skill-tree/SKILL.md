---
name: skill-tree-setup
description: Set up RUBRIC Skill Trees — configure workspace scanning, agent icons, and skill visualization. Use when installing or configuring the Skill Tree template.
---

**Note:** This skill is written for Claude Code. If the user runs a different agent framework, adapt these instructions to their setup.

## Set the Workspace Root

The skill tree scans `.claude/skills/` directories to discover skills. Configure the root path in `data/example-config.json` (rename to `config.json`):

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
    "../.claude/skills",
    "../agents/my-agent/.claude/skills"
  ]
}
```

Set `workspace` paths relative to the template directory. Add entries to `skillDirs` for every directory containing SKILL.md files.

## Platform Auto-Detection

The scanner recognizes common layouts:
- **Claude Code:** `.claude/skills/{name}/SKILL.md`
- **OpenClaw:** `skills/{name}/SKILL.md`
- **Custom:** Any path listed in `skillDirs`

No extra config needed if your workspace follows one of these conventions.

## Customize Agent Icons

1. Open `/icons` in the running server (or `icons.html`) to browse all pixel art icons
2. Set the icon name in config.json per agent: `"icon": "Crown"`
3. Available icons include: Crown, Spark, Fortress, Drift, and more

## Add Custom Pixel Art Icons

To add your own icon, create a 16x16 or 22x22 SVG and add it to the icons collection. Reference it by name in config.json. Icons render at the agent node in the tree visualization.

## Override Agent Names and Colors

The tree auto-detects agent names from directory structure. To override:

```json
{
  "id": "agent-folder-name",
  "name": "Display Name Override",
  "color": "#ff6b6b",
  "icon": "Fortress"
}
```

Colors accept any hex value. They tint the agent's branch in the tree.

## Doc Paths (Optional)

Add `"docPaths": { "claude": "CLAUDE.md", "soul": "SOUL.md" }` to config.json to display docs alongside skills.

## Start the Server

```bash
cd /path/to/skill-tree && npm install && node server.js
```
