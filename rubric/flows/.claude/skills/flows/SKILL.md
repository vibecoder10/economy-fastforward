---
name: flows-setup
description: Set up RUBRIC Flows — create workflow visualizations, configure pipeline steps, connect to live execution. Use when installing or configuring the Flows template.
---

**Note:** This skill is written for Claude Code. If the user runs a different agent framework, adapt these instructions to their setup.

## Create a Workflow

Add an entry to `data/workflows.json`. Each workflow needs: id, name, description, agent, and a skills array defining steps.

```json
{
  "id": "my-workflow",
  "name": "My Workflow",
  "description": "What this workflow does",
  "agent": "agent-id",
  "agentName": "Agent Name",
  "skills": [
    {
      "id": "step-1",
      "name": "Step One",
      "description": "What this step does",
      "icon": "extract",
      "skillPath": "workflows/my-workflow/skills/step-1/SKILL.md"
    }
  ]
}
```

## Create SKILL.md for Each Step

Each step references a `skillPath`. Create that file with instructions the agent follows when executing that step. Place them under `workflows/{workflow-id}/skills/{step-id}/SKILL.md`.

## Connect to Live Execution

Agents report progress via HTTP POST to `/api/workflow-events`:

```bash
# Start workflow → start step → log actions → complete step → complete workflow
curl -X POST http://localhost:5050/api/workflow-events \
  -H 'Content-Type: application/json' \
  -d '{"event":"workflow:start","workflowId":"my-workflow"}'

curl -X POST http://localhost:5050/api/workflow-events \
  -H 'Content-Type: application/json' \
  -d '{"event":"step:start","stepIndex":0,"skillId":"step-1"}'

curl -X POST http://localhost:5050/api/workflow-events \
  -H 'Content-Type: application/json' \
  -d '{"event":"step:complete","stepIndex":0}'

curl -X POST http://localhost:5050/api/workflow-events \
  -H 'Content-Type: application/json' \
  -d '{"event":"workflow:complete","workflowId":"my-workflow"}'
```

## Event Types

| Event | Fields | Purpose |
|---|---|---|
| `workflow:start` | workflowId | Begin a run, lights up the UI |
| `step:start` | stepIndex, skillId | Highlights the active step |
| `step:action` | stepIndex, text | Streams live action text |
| `step:complete` | stepIndex | Marks step done (green) |
| `step:error` | stepIndex, error | Marks step failed (red) |
| `workflow:complete` | workflowId | Ends the run |

The dashboard also accepts events over WebSocket at `ws://localhost:5050` for real-time updates.

## Start the Server

```bash
cd /path/to/flows && npm install && node server.js
```
