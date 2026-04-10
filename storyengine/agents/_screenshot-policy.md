# Screenshot Policy (All Testing Agents)

Injected automatically by run-agent.sh. Applies to qa-engineer, pipeline-tester, and any agent taking screenshots.

## WHEN to screenshot

- A new UI element was added (button, section, modal, card)
- Data renders where there was previously empty state or spinner
- After a mutation (create/update/delete) to show the state change
- When filing a bug — screenshot is your evidence
- Visual regression: something that used to work now looks broken

## WHEN NOT to screenshot

- Backend-only tasks (new endpoint, model change, migration) — curl verification is sufficient
- Pages that haven't changed since last verification
- Every step of a multi-step workflow — only capture start, end, or the problematic step
- Pages that merely "load successfully" with no visual changes
- Identical before/after — if nothing visually changed, one screenshot is enough

## HOW to screenshot

- **Prefer element-level screenshots** (`element.screenshot()`) for specific changed components (20-80KB)
- **Full-page only** for: layout issues, initial regression baselines, mobile viewport checks
- **Viewport-only** (`full_page: false`) is usually enough — captures what the user sees
- **Naming:** `{TASK_ID}.png` for task verification. Add `-before`/`-after` only when both are meaningfully different
- **Regression naming:** `reg{N}_{page}.png`
- **Directory:** `storyengine/agents/screenshots/`
- **Commit screenshots** with your verification changes

## Workflow-specific guidance (pipeline-tester)

| Workflow | When to screenshot |
|---|---|
| Competitors | After scrape IF new data appeared. If delete didn't cascade. |
| Pipeline | Any tab where UI is broken or data doesn't render. Generate button results. |
| Analytics | Sync results if data changed. Error states. |
| Autopilot | Toggle state persistence. Missing candidate data. |

## Visual report upload

After taking screenshots, upload to the shared Google Doc:
```bash
python3 storyengine/agents/update_visual_report.py TASK_ID "Summary of what was verified"
```
Only upload task-specific screenshots — skip regression screenshots (they just confirm pages load).
