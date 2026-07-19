"""Tests for C27's rate-limit fix (checklist P2.4b, the gap C26 flagged):
`rate_limit.py::_extract_tenant_from_jwt` only ever tried `pyjwt.decode()`
on the Authorization bearer value — an MCP agent token (`se_agent_...`) is
not a JWT, so that decode always raised, `_extract_tenant_from_jwt` always
returned None for it, and `RateLimitMiddleware.dispatch`'s
`if not tenant_id: return await call_next(request)` fast path let every
single MCP request through completely unmetered, independent of how much
load an external agent threw at it.

Fix (rate_limit.py, not routes/mcp.py): `_extract_tenant_from_jwt` now
recognizes the `se_agent_` prefix BEFORE attempting a JWT decode, and
resolves the tenant via `agent_tokens.authenticate()` — the SAME DB-backed,
revocation-aware lookup auth_agent.py uses for the real auth decision — so
every MCP request now lands in the SAME per-tenant PLAN_LIMITS bucket an
ordinary session request would.

No live DB, no network — `agent_tokens.authenticate` is patched directly.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c27_rate_limit_agent_tokens.py -q
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import time
import uuid
from unittest.mock import AsyncMock, patch

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _BACKEND)

import agent_tokens  # noqa: E402
import rate_limit  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _fake_request(auth_header: str, path: str = "/api/mcp"):
    from starlette.requests import Request as StarletteRequest
    headers = [(b"authorization", auth_header.encode())] if auth_header else []
    scope = {"type": "http", "headers": headers, "method": "POST", "path": path, "query_string": b""}
    return StarletteRequest(scope)


def setup_function(_fn=None):
    # Every test gets a clean slate — this cache/window state is module-level.
    rate_limit._agent_tenant_cache.clear()
    rate_limit._request_timestamps.clear()
    rate_limit._plan_cache.clear()


# =============================================================================
# 1. _extract_tenant_from_jwt — the extractor fix itself
# =============================================================================

async def test_agent_token_resolves_to_its_owning_tenant():
    tenant = uuid.uuid4()
    request = _fake_request("Bearer se_agent_realsecret")
    with patch.object(agent_tokens, "authenticate", AsyncMock(return_value=tenant)):
        resolved = await rate_limit._extract_tenant_from_jwt(request)
    assert resolved == str(tenant)
    print("✅ test_agent_token_resolves_to_its_owning_tenant")


async def test_invalid_agent_token_resolves_to_none_not_a_crash():
    """An unknown/revoked agent token returns None from authenticate() —
    the rate limiter just treats it as anonymous (same as a garbage JWT
    always has); the real 401 still comes from auth_agent.py's own check,
    completely independent of this middleware."""
    request = _fake_request("Bearer se_agent_revoked")
    with patch.object(agent_tokens, "authenticate", AsyncMock(return_value=None)):
        resolved = await rate_limit._extract_tenant_from_jwt(request)
    assert resolved is None
    print("✅ test_invalid_agent_token_resolves_to_none_not_a_crash")


async def test_session_jwt_path_is_unaffected():
    """A real session JWT never reaches the agent-token branch at all (no
    se_agent_ prefix) — proves the fix is additive, not a rewrite of the
    existing JWT path."""
    import jwt as pyjwt
    os.environ["SESSION_SECRET"] = "test-secret-c27"
    tenant = str(uuid.uuid4())
    token = pyjwt.encode({"tenant_id": tenant}, "test-secret-c27", algorithm="HS256")
    request = _fake_request(f"Bearer {token}")
    with patch.object(agent_tokens, "authenticate", AsyncMock(side_effect=AssertionError("must not be called for a JWT"))):
        resolved = await rate_limit._extract_tenant_from_jwt(request)
    assert resolved == tenant
    print("✅ test_session_jwt_path_is_unaffected")


async def test_agent_token_resolution_is_cached_hashed_not_plaintext():
    tenant = uuid.uuid4()
    auth_mock = AsyncMock(return_value=tenant)
    request = _fake_request("Bearer se_agent_cachedsecret")
    with patch.object(agent_tokens, "authenticate", auth_mock):
        first = await rate_limit._extract_tenant_from_jwt(request)
        second = await rate_limit._extract_tenant_from_jwt(request)
    assert first == second == str(tenant)
    auth_mock.assert_awaited_once(), "the second call within the TTL must hit the cache, not the DB again"
    # The cache key must be a hash, never the plaintext secret.
    assert "se_agent_cachedsecret" not in rate_limit._agent_tenant_cache
    expected_key = hashlib.sha256(b"se_agent_cachedsecret").hexdigest()
    assert expected_key in rate_limit._agent_tenant_cache
    print("✅ test_agent_token_resolution_is_cached_hashed_not_plaintext")


# =============================================================================
# 2. End-to-end: RateLimitMiddleware actually meters an agent-token request
# =============================================================================

async def _call_next_ok(request):
    class _Resp:
        status_code = 200
    return _Resp()


async def test_agent_token_request_is_rate_limited_per_tenant():
    """Before C27: this request would have sailed through unmetered (tenant_id
    always None for an se_agent_ bearer -> the middleware's early-return
    skip). After: it's bucketed under its OWNER tenant's plan limit exactly
    like a session request, and 429s once that bucket is full."""
    tenant = uuid.uuid4()
    middleware = rate_limit.RateLimitMiddleware(app=None)
    request = _fake_request("Bearer se_agent_heavyuser")

    # Fill this tenant's free-plan bucket (60/min) to the brim.
    now = time.time()
    rate_limit._request_timestamps[str(tenant)] = [now] * 60

    with patch.object(agent_tokens, "authenticate", AsyncMock(return_value=tenant)), \
         patch.object(rate_limit, "_get_tenant_plan", AsyncMock(return_value="free")):
        response = await middleware.dispatch(request, _call_next_ok)

    assert response.status_code == 429
    print("✅ test_agent_token_request_is_rate_limited_per_tenant")


async def test_agent_token_request_passes_through_under_the_limit():
    tenant = uuid.uuid4()
    middleware = rate_limit.RateLimitMiddleware(app=None)
    request = _fake_request("Bearer se_agent_lightuser")

    with patch.object(agent_tokens, "authenticate", AsyncMock(return_value=tenant)), \
         patch.object(rate_limit, "_get_tenant_plan", AsyncMock(return_value="free")):
        response = await middleware.dispatch(request, _call_next_ok)

    assert response.status_code == 200
    print("✅ test_agent_token_request_passes_through_under_the_limit")


TESTS_ASYNC = [
    test_agent_token_resolves_to_its_owning_tenant,
    test_invalid_agent_token_resolves_to_none_not_a_crash,
    test_session_jwt_path_is_unaffected,
    test_agent_token_resolution_is_cached_hashed_not_plaintext,
    test_agent_token_request_is_rate_limited_per_tenant,
    test_agent_token_request_passes_through_under_the_limit,
]


def main() -> int:
    failed = 0
    for t in TESTS_ASYNC:
        setup_function()
        try:
            asyncio.run(t())
        except AssertionError as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
    total = len(TESTS_ASYNC)
    print(f"\n{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
