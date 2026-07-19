"""Per-plan rate limiting middleware using in-memory token bucket.

No Redis needed for v1 — state resets on server restart, which is acceptable
since rate limits are protective (not billing-critical).
"""

import hashlib
import os
import time
from collections import defaultdict
from typing import Optional

import jwt as pyjwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# Requests per minute by plan. Includes BOTH naming generations (starter/
# creator/studio here, starter/pro/agency in routes/billing.py) so whichever
# string the account carries resolves to a real limit instead of free.
# free floor is 60/min: the dashboard fires ~6 queries per page plus a 3s task
# poller (20/min alone) — 15/min made the app unusable for free users.
PLAN_LIMITS: dict[str, int] = {
    "free": 60,
    "starter": 100,
    "creator": 200,
    "pro": 200,
    "studio": 400,
    "agency": 400,
    "unlimited": 10_000,  # comped / owner tier — effectively no per-minute cap
}

# Concurrent pipeline job limits per plan
PLAN_JOB_LIMITS: dict[str, int] = {
    "free": 1,
    "starter": 1,
    "creator": 3,
    "pro": 3,
    "studio": 5,
    "agency": 5,
    "unlimited": 50,
}

# Paths that skip rate limiting entirely
_SKIP_PATHS = frozenset({"/api/health", "/api/health/detailed"})
_SKIP_PREFIXES = ("/api/auth/", "/api/media/")  # media: public cacheable proxy, 74 imgs/page

# Control-plane POSTs under /api/pipeline that don't START a job — exempt from
# the concurrent-job check. Stop/cancel is only ever called WHILE a job is
# running; counting it against the job limit made the Stop button physically
# unreachable for plans with job limit 1 (found in adversarial review).
_JOB_LIMIT_EXEMPT_PREFIXES = ("/api/pipeline/cancel/",)

# In-memory state
_request_timestamps: dict[str, list[float]] = defaultdict(list)
_plan_cache: dict[str, tuple[str, float]] = {}
_PLAN_CACHE_TTL = 60.0
_WINDOW = 60.0  # 1-minute sliding window


_AGENT_TOKEN_PREFIX = "se_agent_"
# Short-lived resolution cache, keyed by a hash of the token (never the
# plaintext secret itself — same "don't hold the credential verbatim in
# memory longer than it has to be" instinct as agent_tokens.py's own
# hash-not-plaintext storage). This is a RATE-LIMITING bucket key, not an
# auth decision — auth_agent.get_agent_tenant_id re-checks the DB (including
# revocation) on every single request regardless of what this cache returns;
# a stale entry here only means a request briefly gets bucketed under a
# tenant that just revoked the token, never that it's accepted as authed.
_agent_tenant_cache: dict[str, tuple[str, float]] = {}
_AGENT_CACHE_TTL = 30.0


async def _extract_tenant_from_jwt(request: Request) -> Optional[str]:
    """Resolve the tenant_id a request should be rate-limited under, from
    either a session JWT or an MCP agent token (checklist P2.4b, chunk C27 —
    C26 shipped `/api/mcp` auth'd by `se_agent_` bearer tokens, but this
    function only ever tried pyjwt.decode() on them, which always raises ->
    None -> the middleware's `if not tenant_id: return await call_next(...)`
    skip branch let every MCP request through completely unmetered. An
    agent token is recognized by its `se_agent_` prefix BEFORE the JWT
    decode is even attempted (a JWT is never confused for one, and vice
    versa), then resolved via agent_tokens.authenticate() — the SAME
    DB-backed, individually-revocable lookup auth_agent.py uses for the real
    auth decision, so the tenant this bucket counts against is always the
    token's actual owner, never guessed.
    """
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    if token.startswith(_AGENT_TOKEN_PREFIX):
        cache_key = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = time.time()
        cached = _agent_tenant_cache.get(cache_key)
        if cached and now - cached[1] < _AGENT_CACHE_TTL:
            return cached[0]
        try:
            import agent_tokens
            tenant_id = await agent_tokens.authenticate(token)
        except Exception:
            return None
        if tenant_id is None:
            return None
        tenant_str = str(tenant_id)
        _agent_tenant_cache[cache_key] = (tenant_str, now)
        return tenant_str
    secret = os.getenv("SESSION_SECRET")
    if not secret:
        return None
    try:
        payload = pyjwt.decode(token, secret, algorithms=["HS256"])
        return payload.get("tenant_id")
    except Exception:
        return None


async def _get_tenant_plan(tenant_id: str) -> str:
    """Get tenant plan with lightweight caching (60s TTL).

    Mirrors routes.billing._get_tenant_plan: the plan lives on accounts (via
    membership), and an active trial upgrades free -> pro. This middleware
    previously read tenants.plan, which is 'free' for trial users — every
    dashboard poll then counted against the free bucket and 429-stormed
    their whole session.
    """
    now = time.time()
    cached = _plan_cache.get(tenant_id)
    if cached and now - cached[1] < _PLAN_CACHE_TTL:
        return cached[0]

    from database import fetch_one
    import uuid as _uuid
    try:
        tenant_uuid = _uuid.UUID(str(tenant_id))
    except ValueError:
        return "free"

    plan = "free"
    row = await fetch_one(
        """SELECT a.plan, a.trial_ends_at FROM accounts a
           JOIN memberships m ON m.user_id = a.id
           WHERE m.tenant_id = $1 LIMIT 1""",
        tenant_uuid,
    )
    if row:
        plan = row.get("plan") or "free"
        if plan == "free" and row.get("trial_ends_at"):
            from datetime import datetime, timezone
            if row["trial_ends_at"] > datetime.now(timezone.utc):
                plan = "pro"  # Active trial gets pro limits
    else:
        legacy = await fetch_one("SELECT plan FROM tenants WHERE id = $1", tenant_uuid)
        plan = (legacy or {}).get("plan") or "free"
    _plan_cache[tenant_id] = (plan, now)
    return plan


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token bucket rate limiter keyed by tenant_id."""

    async def dispatch(self, request: Request, call_next):
        # Skip public / health paths
        path = request.url.path
        if path in _SKIP_PATHS or any(path.startswith(p) for p in _SKIP_PREFIXES):
            return await call_next(request)

        tenant_id = await _extract_tenant_from_jwt(request)
        if not tenant_id:
            return await call_next(request)

        plan = await _get_tenant_plan(tenant_id)
        limit = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])

        # Sliding window check
        now = time.time()
        timestamps = _request_timestamps[tenant_id]
        _request_timestamps[tenant_id] = fresh = [
            t for t in timestamps if now - t < _WINDOW
        ]

        if len(fresh) >= limit:
            oldest = min(fresh) if fresh else now
            retry_after = int(_WINDOW - (now - oldest)) + 1
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."},
                headers={"Retry-After": str(retry_after)},
            )

        fresh.append(now)

        # Pipeline concurrent job check (POST only; control-plane paths exempt)
        if (path.startswith("/api/pipeline/") and request.method == "POST"
                and not any(path.startswith(p) for p in _JOB_LIMIT_EXEMPT_PREFIXES)):
            job_limit = PLAN_JOB_LIMITS.get(plan, 1)
            from database import fetch_one

            row = await fetch_one(
                "SELECT count(*) as cnt FROM background_tasks "
                "WHERE tenant_id = $1 AND status = 'running'",
                tenant_id,
            )
            running = (row or {}).get("cnt", 0)
            if running >= job_limit:
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": (
                            f"Concurrent job limit reached ({job_limit} for {plan} plan). "
                            "Wait for current tasks to finish."
                        )
                    },
                )

        return await call_next(request)
