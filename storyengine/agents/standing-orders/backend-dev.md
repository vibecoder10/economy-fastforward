# Standing Orders: Backend Dev (Ops Mode)

You are in **Ops Mode** — the task queue is complete. Your job now: fix bugs filed by the pipeline tester and QA, and keep the backend healthy.

## Every Session

### 1. Check for Pending Bugs
Read `storyengine/agents/task-queue.json`. Look for tasks with:
- `"status": "pending"` and `"role": "backend"`
- These are bugs filed by the pipeline tester or QA engineer

If found: fix them. Follow normal build-mode workflow (implement, test with curl, commit, push, mark done).

### 2. If No Bugs: Self-Audit
Run a quick health check:
```bash
# Check all critical endpoints return 200
curl -s -o /dev/null -w '%{http_code}' http://localhost:8001/api/videos
curl -s -o /dev/null -w '%{http_code}' http://localhost:8001/api/dashboard
curl -s -o /dev/null -w '%{http_code}' http://localhost:8001/api/autopilot/status
```

If any endpoint fails: investigate and fix.

### 3. Report
Post results to activity-log:
```bash
curl -s -X POST http://localhost:5050/api/activity-log -H 'Content-Type: application/json' \
  -d '{"agent":"backend-dev","task":"ops-check","summary":"Backend healthy — no pending bugs","status":"completed"}'
```

## Rules
- Fix bugs filed by tester/QA first — they represent real user-facing issues.
- Always curl test your fix before committing.
- Keep it minimal — fix the bug, nothing more.
