# PRD 3: Infrastructure — Security, Rate Limiting, Task Persistence, Storage

**Priority:** HIGH — blocks multi-tenant production use
**Platform:** StoryEngine (Next.js 16 + React 19 + FastAPI + asyncpg + Supabase PostgreSQL)
**VPS:** 8GB RAM

---

## Context

StoryEngine's core pipeline works end-to-end. Auth, billing backend, onboarding, and 23 pages are built. But the infrastructure underneath is not production-ready for multi-tenant use:

- **6 known security issues** (SEC-1 through SEC-6) documented but unfixed
- **Background tasks are in-memory only** — server restart = lost jobs, no retry, no visibility
- **Single shared Google Drive** for assets — no tenant isolation
- **No structured logging** — errors go to console, no monitoring
- **No rate limiting** — any tenant can hammer the API
- **Health check returns 200 with no actual checks**

This PRD hardens the infrastructure for production multi-tenant operation.

---

## Task 1: Security — Fix SEC-1 through SEC-3 (Critical/High)

**Role:** security-auditor + backend-dev
**Priority:** CRITICAL

Fix the three highest-severity security issues.

### SEC-1: Dev-token bypass (CRITICAL) — VERIFY ONLY
Already gated behind `DEV_MODE=true` in code. Verify that the production `.env` on VPS does NOT have `DEV_MODE=true`. If it does, remove it. Also verify `get_scene_audio()` in `routes/videos.py` properly rejects requests when DEV_MODE is not set.

### SEC-2: get_scene_audio tenant isolation (HIGH)
`get_scene_audio` in `routes/videos.py:486` accepts a JWT token and extracts `tenant_id` from it. However, it then queries `scripts` with `video_id` and `scene` without verifying the video belongs to the extracted `tenant_id`. A valid user could access another tenant's audio by guessing video IDs.

**Fix:** After extracting `tenant_id` from the token, add a verification query:
```python
video = await fetch_one(
    "SELECT id FROM videos WHERE id = $1 AND tenant_id = $2",
    video_id, tenant_id
)
if not video:
    raise HTTPException(status_code=404, detail="Video not found")
```

### SEC-3: API key reveal rate limiting (HIGH)
`GET /api/settings/keys` and `GET /api/settings/keys/{key_name}` return masked API key values. The rate limiting code exists in `settings.py` (lines 16-18: `_reveal_timestamps`, `REVEAL_RATE_LIMIT = 5`, `REVEAL_WINDOW_SECONDS = 60`) but is never enforced in the endpoint handlers.

**Fix:** Add rate limit check at the top of `list_api_keys()` and `get_api_key_status()`:
```python
now = time.time()
timestamps = _reveal_timestamps[tenant_id]
timestamps[:] = [t for t in timestamps if now - t < REVEAL_WINDOW_SECONDS]
if len(timestamps) >= REVEAL_RATE_LIMIT:
    raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")
timestamps.append(now)
```

**Files to modify:**
- `storyengine/backend/routes/videos.py` (SEC-2: add tenant ownership check in `get_scene_audio`)
- `storyengine/backend/routes/settings.py` (SEC-3: enforce existing rate limit variables)

**Acceptance criteria:**
- [ ] Production .env verified: no `DEV_MODE=true`
- [ ] `get_scene_audio` rejects requests where video doesn't belong to the token's tenant
- [ ] `GET /api/settings/keys` returns 429 after 5 requests within 60 seconds
- [ ] All 3 fixes have no regressions — existing functionality still works

---

## Task 2: Security — Fix SEC-4 through SEC-6 (Medium)

**Role:** security-auditor + backend-dev
**Priority:** MEDIUM

### SEC-4: CORS from environment variable (HIGH)
The CORS config in `main.py:284-298` currently uses `ALLOWED_ORIGINS` env var (partially implemented) but also hardcodes `localhost` origins. This is acceptable for dev but production needs explicit control.

**Fix:** Replace the CORS block with:
```python
_default_origins = "http://localhost:3001,http://localhost:3000"
_origins = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", _default_origins).split(",")
    if o.strip()
]
frontend_url = os.getenv("FRONTEND_URL")
if frontend_url and frontend_url not in _origins:
    _origins.append(frontend_url)
```

Remove any hardcoded IP addresses. The production `.env` should set `ALLOWED_ORIGINS` to the actual domain.

### SEC-5: Audit dynamic SQL for injection risks (MEDIUM)
Several route files use f-strings to build SQL queries. After investigation, these are **mostly safe** — they build SET clauses with hardcoded column names and use `$N` parameterized placeholders for values. However, two patterns need review:

1. `routes/niche.py:196` — `ORDER BY {order}` where `order` comes from `_SORT_MAP.get(sort, "vph DESC")`. This is safe because `_SORT_MAP` is a whitelist. Add a comment documenting this.
2. `routes/videos.py:926` — `f"UPDATE scripts SET {col} = $1"` where `col = f"storyboard_{beat}_url"` and `beat` comes from a validated integer. Safe, but add assertion: `assert beat in (1, 2, 3)`.

**For all dynamic SQL:** Add `# SECURITY: column names are hardcoded/validated, values are parameterized` comments where f-strings build queries. This makes future audits faster.

### SEC-6: Audit logging for key management (MEDIUM)
When API keys are created, updated, or deleted via `/api/settings/keys/{key_name}`, there is no audit trail.

**Fix:** Add audit log entries to the `bot_activity` table (already exists) when keys are modified:
```python
await execute(
    """INSERT INTO bot_activity (id, tenant_id, video_id, bot_name, action, details, created_at)
       VALUES (gen_random_uuid(), $1, NULL, 'settings', $2, $3, now())""",
    tenant_id, f"api_key_{action}", json.dumps({"key_name": key_name})
)
```

Actions: `api_key_created`, `api_key_updated`, `api_key_deleted`.

**Files to modify:**
- `storyengine/backend/main.py` (SEC-4: CORS cleanup)
- `storyengine/backend/routes/niche.py` (SEC-5: add safety comments)
- `storyengine/backend/routes/videos.py` (SEC-5: add beat assertion + safety comments)
- `storyengine/backend/routes/settings.py` (SEC-6: audit log on key changes)
- `storyengine/backend/routes/channel_profile.py` (SEC-5: safety comments)
- `storyengine/backend/routes/projects.py` (SEC-5: safety comments)
- `storyengine/backend/routes/profile.py` (SEC-5: safety comments)
- `storyengine/backend/routes/autopilot.py` (SEC-5: safety comments)
- `storyengine/backend/routes/youtube_sync.py` (SEC-5: safety comments)

**Acceptance criteria:**
- [ ] CORS origins come entirely from `ALLOWED_ORIGINS` env var (no hardcoded IPs)
- [ ] All f-string SQL queries have security audit comments
- [ ] `storyboard_{beat}_url` has assertion that beat is 1, 2, or 3
- [ ] API key create/update/delete writes audit entry to `bot_activity`
- [ ] `bot_activity` table shows key management events after test

---

## Task 3: Rate Limiting Per Plan

**Role:** backend-dev
**Priority:** HIGH

Add in-memory token bucket rate limiting. No Redis needed for v1.

**Implementation:**

Create `storyengine/backend/rate_limit.py`:
```python
import time
from collections import defaultdict
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

# Limits per plan (requests per minute)
PLAN_LIMITS = {
    "free": 15,
    "starter": 30,
    "pro": 100,
    "agency": 300,
}

# Concurrent pipeline job limits per plan
PLAN_JOB_LIMITS = {
    "free": 1,
    "starter": 1,
    "pro": 3,
    "agency": 5,
}

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token bucket rate limiter keyed by tenant_id."""
    ...
```

The middleware should:
1. Extract `tenant_id` from the JWT in the Authorization header (skip if no auth — public routes)
2. Look up the tenant's plan from a lightweight cache (refresh every 60s)
3. Check token bucket: if empty, return `429 Too Many Requests` with `Retry-After` header
4. Skip rate limiting for health check endpoints (`/api/health`)
5. For pipeline execution endpoints (`/api/pipeline/*`), also check concurrent job limits

Wire into `main.py` as middleware, added AFTER CORS middleware.

**Files to modify:**
- `storyengine/backend/rate_limit.py` (NEW)
- `storyengine/backend/main.py` (add middleware)

**Acceptance criteria:**
- [ ] Requests return 429 when rate limit exceeded
- [ ] `Retry-After` header is present on 429 responses
- [ ] Different plans have different limits
- [ ] Health check endpoints are not rate limited
- [ ] Pipeline endpoints check concurrent job limits
- [ ] Rate limit state resets correctly per minute window

---

## Task 4: Persistent Background Tasks

**Role:** backend-dev
**Priority:** HIGH

Replace in-memory task tracking with database-backed persistence.

**Current problem:** `pipeline.py` uses `_running_tasks: dict[str, dict] = {}` (line 49). Server restart = all task state lost. Users see "running" tasks that are actually dead.

**Implementation:**

### 4a. Create migration: `029_background_tasks.sql`
```sql
CREATE TABLE IF NOT EXISTS background_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,
    video_id UUID REFERENCES videos(id) ON DELETE SET NULL,
    task_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    progress_json JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_background_tasks_tenant ON background_tasks(tenant_id);
CREATE INDEX idx_background_tasks_status ON background_tasks(status) WHERE status IN ('pending', 'running');
ALTER TABLE background_tasks ENABLE ROW LEVEL SECURITY;
```

### 4b. On server startup (in `lifespan()`):
Mark any tasks stuck in `running` status as `failed` with error `"Server restarted — task interrupted"`.

### 4c. Modify pipeline task tracking:
Replace `_running_tasks` dict with DB read/writes:
- `_set_task_status()` → INSERT/UPDATE `background_tasks`
- `_get_task_status()` → SELECT from `background_tasks`
- `_is_task_running()` → SELECT WHERE status = 'running' AND video_id = $1

### 4d. Add cleanup:
Cron or startup job that marks tasks older than 1 hour in `running` state as `failed`.

**Files to modify:**
- `storyengine/backend/migrations/029_background_tasks.sql` (NEW)
- `storyengine/backend/routes/pipeline.py` (replace in-memory `_running_tasks` with DB calls)
- `storyengine/backend/main.py` (add startup recovery in `lifespan()`)
- `storyengine/schema.sql` (add `background_tasks` table definition)

**Acceptance criteria:**
- [ ] `background_tasks` table created via migration
- [ ] Pipeline stages write status to DB, not in-memory dict
- [ ] Server restart marks interrupted tasks as failed
- [ ] `GET /api/pipeline/{video_id}/status` reads from DB
- [ ] Task history survives server restarts
- [ ] Tasks older than 1 hour in running state are auto-failed

---

## Task 5: Per-Tenant Asset Storage (Supabase Storage)

**Role:** backend-dev
**Priority:** HIGH

Extend the existing `storage.py` (currently Google Drive) to support per-tenant isolation via Supabase Storage.

**Current state:** `storage.py` (169 lines) uses Google Drive with a shared "StoryEngine Assets" root folder. Supabase Storage was partially wired for storyboard grids in a previous PRD but the main storage module still uses Google Drive.

**Implementation:**

### 5a. Add Supabase Storage backend
Add a Supabase Storage client alongside the existing Google Drive client. Use env var `STORAGE_BACKEND=supabase|gdrive` to switch (default: `gdrive` for backward compatibility).

### 5b. Per-tenant folder structure
```
storyengine-assets/          # Supabase Storage bucket
  {tenant_id}/
    {video_id}/
      images/                # Scene images
      grids/                 # Storyboard grids
      voice/                 # Voice-over audio
      thumbnails/            # Thumbnail images
      video-clips/           # Generated video clips
      render/                # Final rendered video
```

### 5c. Signed URLs
Generate short-lived signed URLs (1 hour expiry) for frontend access. Never expose raw storage paths.

### 5d. Update asset writes
When `pipeline_executor.py` generates assets, upload to `{tenant_id}/{video_id}/` path. Store the Supabase Storage path (not URL) in the `assets` table. Generate signed URL on read.

**Files to modify:**
- `storyengine/backend/storage.py` (add Supabase Storage backend, keep Google Drive as fallback)
- `storyengine/backend/pipeline_executor.py` (use tenant-scoped upload paths)
- `storyengine/backend/routes/assets.py` or `routes/videos.py` (generate signed URLs on read)

**Acceptance criteria:**
- [ ] `STORAGE_BACKEND=supabase` routes uploads to Supabase Storage
- [ ] Assets organized by `{tenant_id}/{video_id}/` path
- [ ] Signed URLs generated for frontend access (not public URLs)
- [ ] Google Drive still works when `STORAGE_BACKEND=gdrive` (backward compat)
- [ ] New uploads go to correct tenant folder
- [ ] URLs survive indefinitely (not temp URLs that expire in hours)

---

## Task 6: Structured Logging

**Role:** backend-dev
**Priority:** MEDIUM

Replace `print()` statements with structured JSON logging.

**Implementation:**

Create `storyengine/backend/logging_config.py`:
```python
import logging
import json
from datetime import datetime, timezone

class StructuredFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "tenant_id": getattr(record, "tenant_id", None),
            "video_id": getattr(record, "video_id", None),
            "stage": getattr(record, "stage", None),
            "duration_ms": getattr(record, "duration_ms", None),
        }
        # Remove None values
        log_entry = {k: v for k, v in log_entry.items() if v is not None}
        return json.dumps(log_entry)
```

### 6a. Configure logging in main.py
Set up root logger with StructuredFormatter. Write to both console and `/tmp/storyengine-structured.log`.

### 6b. Add request logging middleware
Log every request: method, path, status_code, duration_ms, tenant_id. Skip health checks.

### 6c. Add error rate tracking
Count errors per 5-minute window. Log WARNING if error rate exceeds 10 errors/5min.

### 6d. Replace print() in main.py background tasks
The 4 background tasks (`_auto_extract_learnings`, `_auto_sync_youtube`, `_auto_analyze_competitor_titles`, `_auto_scrape_competitors`) use `print()` extensively. Replace with `logger.info()` / `logger.error()`.

**Files to modify:**
- `storyengine/backend/logging_config.py` (NEW)
- `storyengine/backend/main.py` (configure logging, replace prints, add request middleware)
- `storyengine/backend/pipeline_executor.py` (use logger instead of print)

**Acceptance criteria:**
- [ ] All log output is structured JSON
- [ ] Logs written to `/tmp/storyengine-structured.log`
- [ ] Each log entry includes timestamp, level, module
- [ ] Request logs include tenant_id, method, path, status_code, duration_ms
- [ ] Error rate warning fires when threshold exceeded
- [ ] No remaining `print()` calls in main.py (all replaced with logger)

---

## Task 7: Health Check Expansion

**Role:** backend-dev
**Priority:** MEDIUM

Expand the health check endpoint from a simple 200 to a meaningful system status.

**Implementation:**

### 7a. Expand `GET /api/health`
```python
@router.get("/health")
async def health_check():
    checks = {}

    # DB connectivity
    try:
        await fetch_one("SELECT 1 as ok")
        checks["database"] = True
    except Exception:
        checks["database"] = False

    # Active background tasks
    try:
        row = await fetch_one(
            "SELECT count(*) as cnt FROM background_tasks WHERE status = 'running'"
        )
        checks["active_tasks"] = row["cnt"] if row else 0
    except Exception:
        checks["active_tasks"] = -1

    # Storage availability
    try:
        # Ping Supabase Storage or Google Drive
        checks["storage"] = True  # Implement actual check
    except Exception:
        checks["storage"] = False

    # Overall status
    if all(v is True for k, v in checks.items() if k != "active_tasks"):
        status = "healthy"
    elif checks.get("database") is True:
        status = "degraded"
    else:
        status = "unhealthy"

    return {"status": status, **checks}
```

### 7b. Add `GET /api/health/detailed` (internal only)
Returns extended info: task queue depth by status, error rate (last 5 min), uptime, memory usage. Protected by a simple bearer token from env var `HEALTH_TOKEN` (not tenant auth).

**Files to modify:**
- `storyengine/backend/routes/dashboard.py` (expand existing health endpoint)
- OR create `storyengine/backend/routes/health.py` if cleaner (register in main.py)

**Acceptance criteria:**
- [ ] `GET /api/health` returns `{ status, database, active_tasks, storage }`
- [ ] Status is "healthy", "degraded", or "unhealthy" based on checks
- [ ] DB down = "unhealthy", storage down = "degraded"
- [ ] `GET /api/health/detailed` returns task queue depth and error rate
- [ ] Detailed endpoint requires HEALTH_TOKEN auth
- [ ] Health endpoints are not rate limited

---

## Task 8: QA — Security Verification

**Role:** qa-engineer
**Priority:** HIGH
**Depends on:** Tasks 1, 2

Verify all security fixes work correctly and don't break existing functionality.

**Test plan:**

### 8a. SEC-1 verification
- SSH into VPS, verify `.env` does not contain `DEV_MODE=true`
- Attempt to call `get_scene_audio` with a fake dev token — must return 401

### 8b. SEC-2 verification (tenant isolation)
- Create audio token for tenant A's video
- Attempt to access tenant B's video audio with tenant A's token — must return 404
- Access tenant A's own video audio — must succeed

### 8c. SEC-3 verification (rate limiting)
- Call `GET /api/settings/keys` 6 times rapidly — 6th call must return 429
- Wait 60 seconds — next call must succeed

### 8d. SEC-4 verification (CORS)
- Set `ALLOWED_ORIGINS=http://example.com` in env
- Verify CORS header reflects only allowed origins
- Verify requests from non-allowed origins are rejected

### 8e. SEC-5 verification (SQL injection)
- Search all route files for f-string SQL — verify all have safety comments
- Attempt SQL injection via sort parameters, filter parameters — must be rejected or ignored

### 8f. SEC-6 verification (audit logging)
- Create an API key via `POST /api/settings/keys/{key_name}`
- Verify `bot_activity` table has an `api_key_created` entry
- Delete the key — verify `api_key_deleted` entry

**Files to check:**
- All files modified in Tasks 1 and 2
- `storyengine/backend/.env` (production)

**Acceptance criteria:**
- [ ] All 6 SEC issues verified as fixed
- [ ] No regressions in existing auth flow
- [ ] No regressions in settings page functionality
- [ ] No regressions in audio playback
- [ ] Audit log entries confirmed in database

---

## Task 9: QA — Infrastructure Verification

**Role:** qa-engineer
**Priority:** HIGH
**Depends on:** Tasks 3, 4, 5, 6, 7

End-to-end verification of rate limiting, task persistence, storage, logging, and health checks.

**Test plan:**

### 9a. Rate limiting
- Send 35 requests in 60 seconds from a Starter plan tenant — verify 429 after 30th
- Send 105 requests from a Pro plan tenant — verify 429 after 100th
- Verify pipeline concurrent job limit: start 2 pipeline jobs on Starter plan — second must be rejected
- Verify `Retry-After` header is present on 429 responses

### 9b. Task persistence
- Start a pipeline stage (e.g., research)
- Query `background_tasks` table — verify row exists with status `running`
- Restart the server (`kill` and re-launch uvicorn)
- Query `background_tasks` — verify the interrupted task is now status `failed` with "Server restarted" message
- Start a new pipeline stage — verify it completes and task status becomes `completed`

### 9c. Storage
- Set `STORAGE_BACKEND=supabase`
- Run a pipeline stage that generates an asset (e.g., image generation)
- Verify asset uploaded to `{tenant_id}/{video_id}/images/` path in Supabase Storage
- Verify frontend can load the asset via signed URL
- Switch to `STORAGE_BACKEND=gdrive` — verify Google Drive still works

### 9d. Structured logging
- Tail `/tmp/storyengine-structured.log`
- Make several API requests
- Verify each line is valid JSON with timestamp, level, module fields
- Trigger an error — verify error entry includes full context
- Verify no raw `print()` output mixed with structured logs (in main.py)

### 9e. Health check
- Call `GET /api/health` — verify JSON response with database, storage, active_tasks fields
- Stop the database — call health check again — verify status is "unhealthy"
- Call `GET /api/health/detailed` without token — verify 401
- Call with correct HEALTH_TOKEN — verify extended response

**Acceptance criteria:**
- [ ] Rate limiting enforced correctly per plan
- [ ] Tasks survive server restart (state in DB)
- [ ] Assets uploaded to correct tenant-scoped paths
- [ ] Structured logs are valid JSON with all required fields
- [ ] Health check accurately reports system status
- [ ] No regressions in pipeline execution

---

## Task 10: Frontend — Health Status Indicator

**Role:** frontend-dev
**Priority:** LOW
**Depends on:** Task 7

Add a small system health indicator to the dashboard.

**Implementation:**
- Poll `GET /api/health` every 60 seconds
- Show a green/yellow/red dot in the sidebar or header
- Green = healthy, Yellow = degraded, Red = unhealthy
- Tooltip shows details: DB status, active tasks count, storage status
- If unhealthy, show a subtle banner: "System experiencing issues. Some features may be slow."

**Files to modify:**
- `storyengine/frontend/src/components/nav/` or `storyengine/frontend/src/app/layout.tsx` (add health indicator)
- `storyengine/frontend/src/lib/api.ts` (add `fetchHealth()` call)
- `storyengine/frontend/src/hooks/` (add `useHealthCheck()` hook)

**Acceptance criteria:**
- [ ] Health indicator visible in dashboard nav/header
- [ ] Color reflects actual system status (green/yellow/red)
- [ ] Tooltip shows breakdown (DB, storage, tasks)
- [ ] Polling interval is 60 seconds (not aggressive)
- [ ] Unhealthy status shows user-facing banner
- [ ] TypeScript compiles: `cd storyengine/frontend && npx tsc --noEmit`

---

## Task 11: Security Audit — Final Review

**Role:** security-auditor
**Priority:** MEDIUM
**Depends on:** Tasks 1-7

Final security review after all infrastructure changes are merged.

**Checklist:**
- [ ] All 6 SEC issues verified closed (re-check after all code changes)
- [ ] Rate limiting cannot be bypassed by omitting auth header
- [ ] Background tasks table has RLS enabled
- [ ] Storage paths cannot be traversed (e.g., `../../other-tenant/` in video_id)
- [ ] Health check detailed endpoint is properly auth-gated
- [ ] No new env vars contain secrets that could leak via health endpoint
- [ ] CORS allows only explicitly configured origins
- [ ] Audit logs cannot be deleted by tenants (RLS restricts to INSERT only, or admin-only DELETE)
- [ ] Signed URLs expire correctly (test after 1 hour)
- [ ] Rate limit state doesn't leak tenant info across requests

**Deliverable:** Security audit report summarizing findings and any remaining issues.

**Acceptance criteria:**
- [ ] Written audit report with pass/fail for each check
- [ ] All critical/high issues closed
- [ ] Any remaining medium/low issues documented with timeline

---

## Execution Order

```
Phase 1 (Security — do first, highest risk):
  Task 1: Fix SEC-1, SEC-2, SEC-3 (critical/high)
  Task 2: Fix SEC-4, SEC-5, SEC-6 (medium)

Phase 2 (Core infrastructure — parallel where possible):
  Task 3: Rate limiting         ← independent, can parallel
  Task 4: Persistent tasks      ← independent, can parallel
  Task 5: Storage isolation     ← independent, can parallel
  Task 6: Structured logging    ← independent, can parallel
  Task 7: Health check          ← depends on Task 4 (needs background_tasks table)

Phase 3 (Verification — after all builds):
  Task 8: QA security verification     ← depends on Tasks 1, 2
  Task 9: QA infrastructure verification ← depends on Tasks 3-7
  Task 10: Frontend health indicator    ← depends on Task 7
  Task 11: Security final audit         ← depends on all tasks
```

---

## Files Index

| File | Tasks | Action |
|------|-------|--------|
| `storyengine/backend/main.py` | 2, 3, 4, 6 | Modify (CORS, middleware, logging, startup recovery) |
| `storyengine/backend/routes/videos.py` | 1, 2 | Modify (SEC-2 tenant check, SEC-5 comments) |
| `storyengine/backend/routes/settings.py` | 1, 2 | Modify (SEC-3 rate limit, SEC-6 audit log) |
| `storyengine/backend/routes/pipeline.py` | 4 | Modify (DB-backed task tracking) |
| `storyengine/backend/routes/niche.py` | 2 | Modify (SEC-5 safety comments) |
| `storyengine/backend/routes/channel_profile.py` | 2 | Modify (SEC-5 safety comments) |
| `storyengine/backend/routes/projects.py` | 2 | Modify (SEC-5 safety comments) |
| `storyengine/backend/routes/profile.py` | 2 | Modify (SEC-5 safety comments) |
| `storyengine/backend/routes/autopilot.py` | 2 | Modify (SEC-5 safety comments) |
| `storyengine/backend/routes/youtube_sync.py` | 2 | Modify (SEC-5 safety comments) |
| `storyengine/backend/routes/dashboard.py` | 7 | Modify (expand health check) |
| `storyengine/backend/storage.py` | 5 | Modify (add Supabase Storage backend) |
| `storyengine/backend/pipeline_executor.py` | 5, 6 | Modify (tenant-scoped uploads, logging) |
| `storyengine/backend/rate_limit.py` | 3 | NEW |
| `storyengine/backend/logging_config.py` | 6 | NEW |
| `storyengine/backend/migrations/029_background_tasks.sql` | 4 | NEW |
| `storyengine/schema.sql` | 4 | Modify (add background_tasks table) |
| `storyengine/frontend/src/components/nav/` | 10 | Modify (health indicator) |
| `storyengine/frontend/src/lib/api.ts` | 10 | Modify (health fetch) |
| `storyengine/frontend/src/hooks/` | 10 | NEW hook (useHealthCheck) |
