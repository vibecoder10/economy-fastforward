"""Tests for C26 (checklist P2.4a — StoryEngine MCP endpoint + agent_tokens
migration + auth, tasks/storyengine-copilot-ux-map.md §7, docs/reports/
2026-07-17-storyengine-agent-audit-findings.md §S5-2/S5-3/S5-4).

Covers:
  1. agent_tokens.py: mint stores only a hash (never plaintext), authenticate
     round-trips a fresh token, a revoked token is rejected immediately
     (S5-3 — no caching, checked on every call), last_used_at update is
     fail-soft, revoke()/list() never leak the hash.
  2. auth_agent.py: the distinct dependency accepts a valid agent token,
     401s on everything else (missing header, wrong scheme, wrong prefix,
     revoked token).
  3. Structural separation (S5-4): auth.py contains no trace of agent-token
     logic — grep-proof. And the cross-acceptance tests, in BOTH directions:
     an agent token is rejected by the shared auth.verify_token (proving
     `/api/settings/keys/{name}/reveal` and every other ordinary route is
     structurally unreachable with an agent token), and a session JWT is
     rejected by auth_agent.get_agent_tenant_id.
  4. routes/mcp.py: tools/list only ever contains list_videos/get_video (no
     write/paid/memory tool can silently appear), tools/call is tenant-scoped
     for both tools, and get_video's payload carries no media URL keys.
  5. main.py: the MCP router is absent (404-shaped — no route at all) when
     MCP_ENABLED is unset/false, and present when it's "true". Proven via a
     real reload of main.py under each env state (not just reading the
     source), so a regression that flips the polarity or drops the `if`
     would fail this test even if the source still "looks right".

No live DB, no network — agent_tokens.py's execute/fetch_one/fetch_all are
patched directly (same style as test_c16a_generation_claims.py's module-stub
pattern) with a small in-memory fake table.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c26_mcp_agent_tokens.py -q
"""
import asyncio
import importlib
import os
import re
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _BACKEND)


def _backend() -> Path:
    return Path(_BACKEND)


import agent_tokens  # noqa: E402


# =============================================================================
# Fake DB — a tiny in-memory table keyed by id, faithful enough for the
# exact 4 query shapes agent_tokens.py issues (insert, select-by-hash,
# update-last-used, update-revoke, select-by-tenant).
# =============================================================================

class _FakeStore:
    def __init__(self):
        self.rows: dict[uuid.UUID, dict] = {}

    def insert(self, tenant_id, name, token_hash):
        row_id = uuid.uuid4()
        row = {
            "id": row_id, "tenant_id": tenant_id, "name": name,
            "token_hash": token_hash, "created_at": "2026-07-19T00:00:00Z",
            "last_used_at": None, "revoked_at": None,
        }
        self.rows[row_id] = row
        return row


def _patched(store: _FakeStore):
    async def _fetch_one(query, *args):
        if "INSERT INTO agent_tokens" in query:
            tenant_id, name, token_hash = args
            row = store.insert(tenant_id, name, token_hash)
            return {"id": row["id"], "name": row["name"], "created_at": row["created_at"],
                     "last_used_at": row["last_used_at"], "revoked_at": row["revoked_at"]}
        if "WHERE token_hash = $1 AND revoked_at IS NULL" in query:
            (token_hash,) = args
            for row in store.rows.values():
                if row["token_hash"] == token_hash and row["revoked_at"] is None:
                    return {"id": row["id"], "tenant_id": row["tenant_id"]}
            return None
        raise AssertionError(f"unexpected fetch_one query: {query!r}")

    async def _fetch_all(query, *args):
        if "FROM agent_tokens" in query and "WHERE tenant_id = $1" in query:
            (tenant_id,) = args
            return [
                {"id": r["id"], "name": r["name"], "created_at": r["created_at"],
                 "last_used_at": r["last_used_at"], "revoked_at": r["revoked_at"]}
                for r in store.rows.values() if r["tenant_id"] == tenant_id
            ]
        raise AssertionError(f"unexpected fetch_all query: {query!r}")

    async def _execute(query, *args):
        if "SET last_used_at = now()" in query:
            (row_id,) = args
            if row_id in store.rows:
                store.rows[row_id]["last_used_at"] = "now"
            return "UPDATE 1"
        if "SET revoked_at = now()" in query:
            token_id, tenant_id = args
            row = store.rows.get(token_id)
            if row and row["tenant_id"] == tenant_id and row["revoked_at"] is None:
                row["revoked_at"] = "now"
                return "UPDATE 1"
            return "UPDATE 0"
        raise AssertionError(f"unexpected execute query: {query!r}")

    return patch.object(agent_tokens, "fetch_one", _fetch_one), \
        patch.object(agent_tokens, "fetch_all", _fetch_all), \
        patch.object(agent_tokens, "execute", _execute)


class _FailingExecute:
    """A DB call that always raises — proves authenticate()'s last_used_at
    update is fail-soft (never blocks a successful auth)."""
    async def __call__(self, *a, **k):
        raise RuntimeError("simulated DB outage")


# =============================================================================
# 1. agent_tokens.py — mint / authenticate / revoke / list
# =============================================================================

async def test_create_agent_token_stores_hash_not_plaintext():
    store = _FakeStore()
    p1, p2, p3 = _patched(store)
    with p1, p2, p3:
        plaintext, row = await agent_tokens.create_agent_token("tenant-1", "Claude Desktop")

    assert plaintext.startswith(agent_tokens.TOKEN_PREFIX)
    stored = store.rows[row["id"]]
    assert stored["token_hash"] != plaintext, "plaintext must never be stored verbatim"
    assert stored["token_hash"] == agent_tokens._hash_token(plaintext)
    # The plaintext string itself never appears anywhere in the fake DB row.
    assert plaintext not in str(stored)
    print("✅ test_create_agent_token_stores_hash_not_plaintext")


async def test_authenticate_roundtrip_returns_tenant_id():
    store = _FakeStore()
    tenant = uuid.uuid4()
    p1, p2, p3 = _patched(store)
    with p1, p2, p3:
        plaintext, _row = await agent_tokens.create_agent_token(tenant, "CI bot")
        result = await agent_tokens.authenticate(plaintext)
    assert result == tenant
    print("✅ test_authenticate_roundtrip_returns_tenant_id")


async def test_authenticate_rejects_wrong_prefix():
    store = _FakeStore()
    p1, p2, p3 = _patched(store)
    with p1, p2, p3:
        result = await agent_tokens.authenticate("not-a-real-token")
    assert result is None
    print("✅ test_authenticate_rejects_wrong_prefix")


async def test_authenticate_rejects_unknown_token():
    store = _FakeStore()
    p1, p2, p3 = _patched(store)
    with p1, p2, p3:
        result = await agent_tokens.authenticate(agent_tokens.TOKEN_PREFIX + "unknown-secret")
    assert result is None
    print("✅ test_authenticate_rejects_unknown_token")


async def test_revoked_token_is_rejected_immediately():
    """S5-3: revocation takes effect on the very next authenticate() call —
    no caching, re-checked every time."""
    store = _FakeStore()
    tenant = uuid.uuid4()
    p1, p2, p3 = _patched(store)
    with p1, p2, p3:
        plaintext, row = await agent_tokens.create_agent_token(tenant, "to-revoke")
        assert await agent_tokens.authenticate(plaintext) == tenant

        revoked = await agent_tokens.revoke_agent_token(tenant, row["id"])
        assert revoked is True

        result = await agent_tokens.authenticate(plaintext)
    assert result is None, "a revoked token must be rejected on the very next request"
    print("✅ test_revoked_token_is_rejected_immediately")


async def test_revoke_is_idempotent_and_tenant_scoped():
    store = _FakeStore()
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    p1, p2, p3 = _patched(store)
    with p1, p2, p3:
        _plain, row = await agent_tokens.create_agent_token(tenant_a, "a-token")
        # Wrong tenant can't revoke someone else's token.
        cross = await agent_tokens.revoke_agent_token(tenant_b, row["id"])
        assert cross is False
        first = await agent_tokens.revoke_agent_token(tenant_a, row["id"])
        assert first is True
        second = await agent_tokens.revoke_agent_token(tenant_a, row["id"])
        assert second is False, "revoking an already-revoked token returns False, not an error"
    print("✅ test_revoke_is_idempotent_and_tenant_scoped")


async def test_authenticate_fail_soft_on_last_used_update_error():
    store = _FakeStore()
    tenant = uuid.uuid4()
    p1, p2, p3 = _patched(store)
    with p1, p2, p3:
        plaintext, _row = await agent_tokens.create_agent_token(tenant, "flaky")

    # Now authenticate again, but this time execute() (the last_used_at
    # update) always raises -- authenticate() must still succeed.
    p1b, p2b, _p3b = _patched(store)
    with p1b, p2b, patch.object(agent_tokens, "execute", _FailingExecute()):
        result = await agent_tokens.authenticate(plaintext)
    assert result == tenant, "a failing last_used_at UPDATE must not block a valid auth"
    print("✅ test_authenticate_fail_soft_on_last_used_update_error")


async def test_list_agent_tokens_never_returns_hash():
    store = _FakeStore()
    tenant = uuid.uuid4()
    p1, p2, p3 = _patched(store)
    with p1, p2, p3:
        await agent_tokens.create_agent_token(tenant, "one")
        await agent_tokens.create_agent_token(tenant, "two")
        rows = await agent_tokens.list_agent_tokens(tenant)
    assert len(rows) == 2
    for r in rows:
        assert "token_hash" not in r
        assert "token" not in r
    print("✅ test_list_agent_tokens_never_returns_hash")


# =============================================================================
# 2. auth_agent.py — the distinct dependency
# =============================================================================

import auth_agent  # noqa: E402
from fastapi import HTTPException  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


async def test_get_agent_tenant_id_missing_header_401():
    try:
        await auth_agent.get_agent_tenant_id(authorization=None)
        raised = None
    except HTTPException as e:
        raised = e
    assert raised is not None and raised.status_code == 401
    print("✅ test_get_agent_tenant_id_missing_header_401")


async def test_get_agent_tenant_id_wrong_scheme_401():
    try:
        await auth_agent.get_agent_tenant_id(authorization="Basic dXNlcjpwYXNz")
        raised = None
    except HTTPException as e:
        raised = e
    assert raised is not None and raised.status_code == 401
    print("✅ test_get_agent_tenant_id_wrong_scheme_401")


async def test_get_agent_tenant_id_wrong_prefix_401():
    try:
        await auth_agent.get_agent_tenant_id(authorization="Bearer some-random-string")
        raised = None
    except HTTPException as e:
        raised = e
    assert raised is not None and raised.status_code == 401
    print("✅ test_get_agent_tenant_id_wrong_prefix_401")


async def test_get_agent_tenant_id_valid_token_returns_tenant():
    tenant = uuid.uuid4()
    store = _FakeStore()
    p1, p2, p3 = _patched(store)
    with p1, p2, p3:
        plaintext, _row = await agent_tokens.create_agent_token(tenant, "valid")
        result = await auth_agent.get_agent_tenant_id(authorization=f"Bearer {plaintext}")
    assert result == tenant
    print("✅ test_get_agent_tenant_id_valid_token_returns_tenant")


async def test_get_agent_tenant_id_revoked_token_401():
    tenant = uuid.uuid4()
    store = _FakeStore()
    p1, p2, p3 = _patched(store)
    with p1, p2, p3:
        plaintext, row = await agent_tokens.create_agent_token(tenant, "will-revoke")
        await agent_tokens.revoke_agent_token(tenant, row["id"])
        try:
            await auth_agent.get_agent_tenant_id(authorization=f"Bearer {plaintext}")
            raised = None
        except HTTPException as e:
            raised = e
    assert raised is not None and raised.status_code == 401
    print("✅ test_get_agent_tenant_id_revoked_token_401")


# =============================================================================
# 3. Structural separation (S5-4) + cross-acceptance rejection (both dirs)
# =============================================================================

def test_auth_py_has_no_agent_token_logic():
    """Grep-proof that auth.py was never touched to add agent-token support:
    no reference to the agent-token prefix, the agent_tokens module, or the
    auth_agent module anywhere in auth.py's source."""
    src = (_backend() / "auth.py").read_text()
    for marker in ("se_agent_", "agent_tokens", "auth_agent", "get_agent_tenant_id"):
        assert marker not in src, f"auth.py must not reference {marker!r} — S5-4 violation"
    # verify_token/get_tenant_id must still be exactly the 2 auth entry
    # points (a 3rd/4th branch recognizing agent tokens would be the bug).
    assert src.count("def verify_token(") == 1
    assert src.count("def get_tenant_id(") == 1
    print("✅ test_auth_py_has_no_agent_token_logic")


def test_auth_agent_module_never_imports_auth_module():
    """auth_agent.py must not import auth.py at all — proves it can't
    delegate to (or accidentally widen) the session-JWT verifier."""
    src = (_backend() / "auth_agent.py").read_text()
    assert "import auth" not in re.sub(r"import auth_agent", "", src)
    assert "from auth " not in src and "from auth import" not in src
    print("✅ test_auth_agent_module_never_imports_auth_module")


async def test_agent_token_rejected_by_shared_verify_token():
    """Cross-acceptance, direction 1: an agent token must NOT satisfy
    auth.verify_token — this is what keeps /api/settings/keys/{name}/reveal
    (and every other ordinary route) structurally unreachable with an agent
    token. auth.verify_token tries the session-JWT secret then the Supabase
    JWT secret; an se_agent_ string is valid for neither, so it 401s."""
    import auth as se_auth
    from starlette.requests import Request as StarletteRequest
    from fastapi.security import HTTPAuthorizationCredentials

    store = _FakeStore()
    tenant = uuid.uuid4()
    p1, p2, p3 = _patched(store)
    with p1, p2, p3:
        plaintext, _row = await agent_tokens.create_agent_token(tenant, "cross-check")

    scope = {"type": "http", "headers": [], "query_string": b""}
    fake_request = StarletteRequest(scope)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=plaintext)

    os.environ.pop("DEV_TOKEN", None)
    try:
        se_auth.verify_token(fake_request, credentials=creds)
        raised = None
    except HTTPException as e:
        raised = e
    assert raised is not None and raised.status_code == 401, (
        "an agent token must be rejected by the shared verify_token — if it "
        "were accepted, every ordinary route (including key-reveal) would be "
        "reachable with an agent token"
    )
    print("✅ test_agent_token_rejected_by_shared_verify_token")


async def test_session_jwt_rejected_by_agent_dependency():
    """Cross-acceptance, direction 2: a real StoryEngine session JWT must
    NOT satisfy get_agent_tenant_id — it doesn't start with se_agent_, so
    it's rejected before the DB is even consulted."""
    import jwt as pyjwt

    os.environ["SESSION_SECRET"] = "test-secret-for-c26"
    session_jwt = pyjwt.encode(
        {"sub": "user-1", "iss": "storyengine", "tenant_id": str(uuid.uuid4())},
        "test-secret-for-c26", algorithm="HS256",
    )
    try:
        await auth_agent.get_agent_tenant_id(authorization=f"Bearer {session_jwt}")
        raised = None
    except HTTPException as e:
        raised = e
    assert raised is not None and raised.status_code == 401
    print("✅ test_session_jwt_rejected_by_agent_dependency")


# =============================================================================
# 4. routes/mcp.py — tool surface + tenant scoping
# =============================================================================

import routes.mcp as mcp_mod  # noqa: E402


def test_tools_list_is_exactly_the_two_read_only_tools():
    """SUPERSEDED BY C27 (checklist P2.4b expands the C26 read-only-2 surface
    with the money-gated verb registry — see test_c27_mcp_toolset_money_gate.py
    for the new surface's own tests). Kept here, updated rather than deleted,
    so this file's git history stays a readable record of what C26 shipped
    and what C27 changed about it. list_videos/get_video are still present
    (C26 is a strict subset of C27's surface); remember/forget/set_budget
    are still absent (S5-2 still holds)."""
    names = {t["name"] for t in mcp_mod.TOOLS}
    assert {"list_videos", "get_video"}.issubset(names), (
        f"C26's two read-only tools must still be present, got {names}"
    )
    for verb in ("remember", "forget", "set_budget"):
        assert verb not in names, f"{verb!r} must never appear in MCP (S5-2/scope)"
    print("✅ test_tools_list_is_exactly_the_two_read_only_tools")


async def test_list_videos_tool_is_tenant_scoped():
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()

    async def _fake_fetch_all(query, *args):
        tenant_id, limit = args
        rows_by_tenant = {
            tenant_a: [{"id": uuid.uuid4(), "video_title": "A's video", "status": "done"}],
            tenant_b: [{"id": uuid.uuid4(), "video_title": "B's video", "status": "rendering"}],
        }
        return rows_by_tenant.get(tenant_id, [])

    with patch.object(mcp_mod, "fetch_all", _fake_fetch_all):
        result_a = await mcp_mod._call_list_videos(tenant_a, {})
        result_b = await mcp_mod._call_list_videos(tenant_b, {})

    assert "A's video" in result_a["content"][0]["text"]
    assert "B's video" not in result_a["content"][0]["text"]
    assert "B's video" in result_b["content"][0]["text"]
    assert "A's video" not in result_b["content"][0]["text"]
    print("✅ test_list_videos_tool_is_tenant_scoped")


async def test_get_video_tool_uses_tenant_scoped_video_summary():
    calls = []

    async def _fake_video_summary(tenant_id, video_id):
        calls.append((tenant_id, video_id))
        if tenant_id == "tenant-owns-it":
            return {"title": "My Video", "status": "rendering", "spent": 4.20}
        return None  # not found for any other tenant — proves scoping

    with patch.object(mcp_mod.actions, "video_summary", _fake_video_summary):
        owned = await mcp_mod._call_get_video("tenant-owns-it", {"video_id": "v1"})
        other = await mcp_mod._call_get_video("tenant-other", {"video_id": "v1"})

    assert owned["isError"] is False
    assert "My Video" in owned["content"][0]["text"]
    assert other["isError"] is True, "a video from another tenant must not resolve"
    assert calls == [("tenant-owns-it", "v1"), ("tenant-other", "v1")]
    print("✅ test_get_video_tool_uses_tenant_scoped_video_summary")


async def test_get_video_result_carries_no_media_url():
    """C25a's media-proxy fix isn't deployed yet -- the v1 tool surface must
    not leak an image/video URL a tool caller could hand to an external
    process/log forever. video_summary()'s shape never includes one; this
    pins that guarantee at the MCP boundary too."""
    async def _fake_video_summary(tenant_id, video_id):
        return {
            "title": "T", "status": "done", "scenes": 6, "pics": 12,
            "clips": 3, "spent": 9.0,
        }

    with patch.object(mcp_mod.actions, "video_summary", _fake_video_summary):
        result = await mcp_mod._call_get_video("t1", {"video_id": "v1"})

    text = result["content"][0]["text"].lower()
    for marker in ("http://", "https://", "drive.google", "_url\"", "media_url"):
        assert marker not in text, f"get_video result must not carry a media URL ({marker!r} found)"
    print("✅ test_get_video_result_carries_no_media_url")


async def test_tools_call_unknown_tool_is_an_error_not_a_500():
    result = await mcp_mod._dispatch("tools/call", {"name": "delete_everything"}, "t1")
    assert result["isError"] is True
    print("✅ test_tools_call_unknown_tool_is_an_error_not_a_500")


async def test_initialize_and_tools_list_dispatch():
    init = await mcp_mod._dispatch("initialize", {}, "t1")
    assert init["protocolVersion"] == mcp_mod.PROTOCOL_VERSION
    assert init["serverInfo"]["name"] == "storyengine"
    listed = await mcp_mod._dispatch("tools/list", {}, "t1")
    names = {t["name"] for t in listed["tools"]}
    assert {"list_videos", "get_video"}.issubset(names)  # C27 expands, never removes
    print("✅ test_initialize_and_tools_list_dispatch")


# =============================================================================
# 5. main.py — dark-by-default router registration
# =============================================================================

def _reload_main_with_env(mcp_enabled_value):
    """Reload main.py fresh with MCP_ENABLED set to the given value (or
    removed if None), returning the set of route paths it registered.
    main.py imports cleanly without a live DB/Redis (every startup step is
    try/excepted) -- see test_c16d_health_queue_status.py's precedent."""
    if mcp_enabled_value is None:
        os.environ.pop("MCP_ENABLED", None)
    else:
        os.environ["MCP_ENABLED"] = mcp_enabled_value

    for name in list(sys.modules):
        if name == "main" or name.startswith("routes.mcp"):
            del sys.modules[name]

    import main as reloaded_main
    paths = {r.path for r in reloaded_main.app.routes if hasattr(r, "path")}
    return paths


def test_mcp_routes_absent_when_env_unset():
    paths = _reload_main_with_env(None)
    assert "/api/mcp" not in paths, "MCP_ENABLED unset must mean the route doesn't exist at all"
    print("✅ test_mcp_routes_absent_when_env_unset")


def test_mcp_routes_absent_when_env_false():
    paths = _reload_main_with_env("false")
    assert "/api/mcp" not in paths
    print("✅ test_mcp_routes_absent_when_env_false")


def test_mcp_routes_present_when_env_true():
    paths = _reload_main_with_env("true")
    assert "/api/mcp" in paths, "MCP_ENABLED=true must register the route"
    print("✅ test_mcp_routes_present_when_env_true")


def test_agent_access_routes_always_present_regardless_of_mcp_flag():
    """Mint/list/revoke are normal session-authed routes -- not gated by
    MCP_ENABLED at all (they're a USER-auth surface, distinct concern)."""
    paths = _reload_main_with_env(None)
    assert "/api/agent-tokens" in paths
    print("✅ test_agent_access_routes_always_present_regardless_of_mcp_flag")


TESTS_SYNC = [
    test_auth_py_has_no_agent_token_logic,
    test_auth_agent_module_never_imports_auth_module,
    test_tools_list_is_exactly_the_two_read_only_tools,
    test_mcp_routes_absent_when_env_unset,
    test_mcp_routes_absent_when_env_false,
    test_mcp_routes_present_when_env_true,
    test_agent_access_routes_always_present_regardless_of_mcp_flag,
]

TESTS_ASYNC = [
    test_create_agent_token_stores_hash_not_plaintext,
    test_authenticate_roundtrip_returns_tenant_id,
    test_authenticate_rejects_wrong_prefix,
    test_authenticate_rejects_unknown_token,
    test_revoked_token_is_rejected_immediately,
    test_revoke_is_idempotent_and_tenant_scoped,
    test_authenticate_fail_soft_on_last_used_update_error,
    test_list_agent_tokens_never_returns_hash,
    test_get_agent_tenant_id_missing_header_401,
    test_get_agent_tenant_id_wrong_scheme_401,
    test_get_agent_tenant_id_wrong_prefix_401,
    test_get_agent_tenant_id_valid_token_returns_tenant,
    test_get_agent_tenant_id_revoked_token_401,
    test_agent_token_rejected_by_shared_verify_token,
    test_session_jwt_rejected_by_agent_dependency,
    test_list_videos_tool_is_tenant_scoped,
    test_get_video_tool_uses_tenant_scoped_video_summary,
    test_get_video_result_carries_no_media_url,
    test_tools_call_unknown_tool_is_an_error_not_a_500,
    test_initialize_and_tools_list_dispatch,
]


def main() -> int:
    failed = 0
    for t in TESTS_SYNC:
        try:
            t()
        except AssertionError as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
    for t in TESTS_ASYNC:
        try:
            asyncio.run(t())
        except AssertionError as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
    total = len(TESTS_SYNC) + len(TESTS_ASYNC)
    print(f"\n{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
