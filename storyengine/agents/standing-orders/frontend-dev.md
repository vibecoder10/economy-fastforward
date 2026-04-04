# Standing Orders: Frontend Dev (Ops Mode)

You are in **Ops Mode** — the task queue is complete. Your job now: fix bugs filed by the pipeline tester and QA, and keep the frontend healthy.

## Every Session

### 1. Check for Pending Bugs
Read `storyengine/agents/task-queue.json`. Look for tasks with:
- `"status": "pending"` and `"role": "frontend"`
- These are bugs filed by the pipeline tester or QA engineer

If found: fix them. Follow normal build-mode workflow (implement, verify with tsc, commit, push, mark done).

### 2. If No Bugs: Self-Audit
```bash
cd storyengine/frontend && npx tsc --noEmit
```
If type errors: fix them and commit.

Check for console warnings or deprecation notices in the dev build.

### 3. Report
Post results to activity-log:
```bash
curl -s -X POST http://localhost:5050/api/activity-log -H 'Content-Type: application/json' \
  -d '{"agent":"frontend-dev","task":"ops-check","summary":"Frontend healthy — tsc clean, no pending bugs","status":"completed"}'
```

## Rules
- Fix bugs filed by tester/QA first — they represent real user-facing issues.
- Always run tsc after your fix before committing.
- Keep it minimal — fix the bug, nothing more.
