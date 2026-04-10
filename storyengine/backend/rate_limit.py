"""Per-plan rate limiting middleware using in-memory token bucket.

No Redis needed for v1 — state resets on server restart, which is acceptable
since rate limits are protective (not billing-critical).
"""

import os
import time
from collections import defaultdict
from typing import Optional

import jwt as pyjwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# Requests per minute by plan
PLAN_LIMITS: dict[str, int] = {
    "free": 15,
    "starter": 30,
    "creator": 100,
    "studio": 300,
}

# Concurrent pipeline job limits per plan
PLAN_JOB_LIMITS: dict[str, int] = {
    "free": 1,
    "starter": 1,
    "creator": 3,
    "studio": 5,
}

# Paths that skip rate limiting entirely
_SKIP_PATHS = frozenset({"/api/health", "/api/health/detailed"})
_SKIP_PREFIXES = ("/api/auth/",)

# In-memory state
_request_timestamps: dict[str, list[float]] = defaultdict(list)
_plan_cache: dict[str, tuple[str, float]] = {}
_PLAN_CACHE_TTL = 60.0
_WINDOW = 60.0  # 1-minute sliding window


def _extract_tenant_from_jwt(request: Request) -> Optional[str]:
    """Extract tenant_id from JWT in Authorization header."""
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return None
    secret = os.getenv("SESSION_SECRET")
    if not secret:
        return None
    try:
        payload = pyjwt.decode(auth[7:], secret, algorithms=["HS256"])
        return payload.get("tenant_id")
    except Exception:
        return None


async def _get_tenant_plan(tenant_id: str) -> str:
    """Get tenant plan with lightweight caching (60s TTL)."""
    now = time.time()
    cached = _plan_cache.get(tenant_id)
    if cached and now - cached[1] < _PLAN_CACHE_TTL:
        return cached[0]

    from database import fetch_one

    row = await fetch_one("SELECT plan FROM tenants WHERE id = $1", tenant_id)
    plan = (row or {}).get("plan", "free")
    _plan_cache[tenant_id] = (plan, now)
    return plan


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token bucket rate limiter keyed by tenant_id."""

    async def dispatch(self, request: Request, call_next):
        # Skip public / health paths
        path = request.url.path
        if path in _SKIP_PATHS or any(path.startswith(p) for p in _SKIP_PREFIXES):
            return await call_next(request)

        tenant_id = _extract_tenant_from_jwt(request)
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

        # Pipeline concurrent job check (POST only)
        if path.startswith("/api/pipeline/") and request.method == "POST":
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
