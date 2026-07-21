"""C25a-fix11 (Streamable HTTP compliance for routes/mcp.py): C26 shipped a
bare single-POST JSON-RPC endpoint on purpose, with the module docstring
explicitly deferring "whether a real external MCP client needs the fuller
transport" to a live-client loop test. That test came back negative: `claude
mcp add --transport http` + `claude mcp list` on Ryan's Mac reported the
storyengine connector as unreachable, while raw curl (POST-only, no session
mechanics) against the SAME prod endpoint kept working fine. Reproduced live
against prod pre-fix (see the chunk report for the exact curl transcript):

    curl -X POST https://storyengine.dev/api/mcp -H "Authorization: Bearer
    <token>" -H "Accept: application/json, text/event-stream" -d
    '{"jsonrpc":"2.0","method":"notifications/initialized"}'

    -> HTTP 200, body {"jsonrpc":"2.0","id":null,"error":{"code":-32601,
       "message":"Unknown method: notifications/initialized"}}

The Streamable HTTP spec (2025-03-26, "Sending Messages to the Server",
point 4) requires HTTP 202 Accepted with NO body for a POST containing only
JSON-RPC notifications. The official MCP TypeScript SDK (what Claude Code's
client is built on) sends `notifications/initialized` immediately after
`initialize` succeeds, as a required lifecycle step, not an optional
courtesy call — a client that gets back a JSON-RPC error envelope where it
expected a bare 202 has grounds to treat the connection as broken, which
lines up with tools never actually populating in a live session even though
the shallow `claude mcp list` health probe (which likely only exercises
`initialize`) reported "Connected".

This file pins the fix, plus the other Streamable HTTP requirements C25a-
fix11 added alongside it (Mcp-Session-Id issuance, the GET listen stream,
protocolVersion negotiation) — driving the REAL ASGI app via TestClient, the
same technique test_c29_mcp_full_session_dry_run.py uses, so the auth gate,
JSON-RPC envelope, and route wiring are all genuinely exercised end to end,
not mocked at the dispatch layer.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c25a_fix11_streamable_http_compliance.py -q
"""
from __future__ import annotations

import os
import sys
import uuid
from unittest.mock import patch

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from fastapi.testclient import TestClient
from unittest.mock import AsyncMock

import agent_tokens  # noqa: E402
import database  # noqa: E402
import routes.billing as billing  # noqa: E402


FIXED_TENANT = uuid.uuid4()
AGENT_TOKEN_NAME = "C25a-fix11 Streamable HTTP Test"


# =============================================================================
# Same fake agent_tokens table technique as test_c26/test_c29 — a real mint
# + a real auth_agent.get_agent_tenant_id gate on every request, no live DB.
# =============================================================================
class _FakeAgentTokenStore:
    def __init__(self):
        self.rows: dict[uuid.UUID, dict] = {}

    def insert(self, tenant_id, name, token_hash):
        row_id = uuid.uuid4()
        row = {
            "id": row_id, "tenant_id": tenant_id, "name": name,
            "token_hash": token_hash, "created_at": "2026-07-20T00:00:00Z",
            "last_used_at": None, "revoked_at": None,
        }
        self.rows[row_id] = row
        return row


def _patch_agent_tokens(store: _FakeAgentTokenStore):
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
                    return dict(row)
            return None
        if "JOIN memberships m ON m.tenant_id = t.tenant_id" in query:
            (token_hash,) = args
            for row in store.rows.values():
                if row["token_hash"] == token_hash and row["revoked_at"] is None:
                    return {
                        "token_id": row["id"], "tenant_id": row["tenant_id"],
                        "trial_ends_at": None, "stripe_subscription_id": None,
                        "stripe_status": None, "plan": "pro", "is_operator": False,
                    }
            return None
        raise AssertionError(f"unexpected agent_tokens fetch_one query: {query!r}")

    async def _fetch_all(query, *args):
        raise AssertionError(f"unexpected agent_tokens fetch_all query: {query!r}")

    async def _execute(query, *args):
        if "SET last_used_at = now()" in query:
            (row_id,) = args
            if row_id in store.rows:
                store.rows[row_id]["last_used_at"] = "now"
            return "UPDATE 1"
        raise AssertionError(f"unexpected agent_tokens execute query: {query!r}")

    return (
        patch.object(agent_tokens, "fetch_one", _fetch_one),
        patch.object(agent_tokens, "fetch_all", _fetch_all),
        patch.object(agent_tokens, "execute", _execute),
    )


async def _fake_plan_fetch_one(query, *args):
    """RateLimitMiddleware's per-request plan lookup — same fake test_c29
    uses. A brand-new tenant with no accounts/tenants row defaults to the
    free-tier bucket, comfortably more than this test's handful of calls."""
    return None


def _reload_main(mcp_enabled: bool):
    if mcp_enabled:
        os.environ["MCP_ENABLED"] = "true"
    else:
        os.environ.pop("MCP_ENABLED", None)
    for name in list(sys.modules):
        if name == "main" or name.startswith("routes.mcp"):
            del sys.modules[name]
    import main as reloaded_main
    return reloaded_main


def _client_with_token():
    """Boots a fresh app + mints a real agent token through the real
    /api/agent-tokens route. Returns (client, bearer_token, patches) — the
    caller is responsible for entering the patches as a context manager
    around every request it makes."""
    import auth  # local import: only exists once app modules are loaded fresh

    reloaded_main = _reload_main(mcp_enabled=True)
    client = TestClient(reloaded_main.app)
    client.app.dependency_overrides[auth.get_tenant_id] = lambda: FIXED_TENANT

    store = _FakeAgentTokenStore()
    p1, p2, p3 = _patch_agent_tokens(store)
    with p1, p2, p3, patch.object(database, "fetch_one", _fake_plan_fetch_one), \
         patch.object(billing, "is_account_in_good_standing",
                      AsyncMock(return_value=(True, "no subscription on file (free tier)"))), \
         patch.object(billing, "_get_tenant_plan_and_operator",
                      AsyncMock(return_value=("pro", False))):
        mint_resp = client.post("/api/agent-tokens", json={"name": AGENT_TOKEN_NAME})
    assert mint_resp.status_code == 200, mint_resp.text
    bearer = mint_resp.json()["token"]
    return client, bearer, (p1, p2, p3)


# =============================================================================
# 1. initialize: combined Accept header -> 200 + Mcp-Session-Id, protocolVersion
#    negotiation (echo a supported request, fall back on an unsupported one).
# =============================================================================

def test_initialize_with_combined_accept_header_returns_session_id():
    client, bearer, (p1, p2, p3) = _client_with_token()
    with p1, p2, p3, patch.object(database, "fetch_one", _fake_plan_fetch_one):
        resp = client.post(
            "/api/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                             "clientInfo": {"name": "test", "version": "1.0"}}},
            headers={"Authorization": f"Bearer {bearer}",
                     "Accept": "application/json, text/event-stream"},
        )
    assert resp.status_code == 200, resp.text
    assert "Mcp-Session-Id" in resp.headers, "initialize must issue a session id per spec §Session Management"
    session_id = resp.headers["Mcp-Session-Id"]
    assert session_id and all(0x21 <= ord(c) <= 0x7E for c in session_id), (
        "session id must be visible ASCII only (spec point: 0x21-0x7E)"
    )
    body = resp.json()
    assert body["result"]["protocolVersion"] == "2025-03-26", (
        "a supported requested protocolVersion must be echoed back, not silently overridden"
    )
    print("✅ test_initialize_with_combined_accept_header_returns_session_id")


def test_initialize_falls_back_on_unsupported_protocol_version():
    client, bearer, (p1, p2, p3) = _client_with_token()
    with p1, p2, p3, patch.object(database, "fetch_one", _fake_plan_fetch_one):
        resp = client.post(
            "/api/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "1999-01-01"}},
            headers={"Authorization": f"Bearer {bearer}",
                     "Accept": "application/json, text/event-stream"},
        )
    import routes.mcp as mcp_mod
    assert resp.json()["result"]["protocolVersion"] == mcp_mod.PROTOCOL_VERSION
    print("✅ test_initialize_falls_back_on_unsupported_protocol_version")


# =============================================================================
# 2. notifications/initialized -> 202, no body, NOT a JSON-RPC envelope.
#    This is the exact break the client hit (see module docstring).
# =============================================================================

def test_notifications_initialized_returns_202_with_no_body():
    client, bearer, (p1, p2, p3) = _client_with_token()
    with p1, p2, p3, patch.object(database, "fetch_one", _fake_plan_fetch_one):
        resp = client.post(
            "/api/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers={"Authorization": f"Bearer {bearer}",
                     "Accept": "application/json, text/event-stream"},
        )
    assert resp.status_code == 202, (
        f"expected 202 Accepted for a notification (no id), got {resp.status_code}: {resp.text!r}"
    )
    assert resp.content == b"", f"a notification response must have NO body, got {resp.content!r}"
    print("✅ test_notifications_initialized_returns_202_with_no_body")


def test_unknown_notification_method_is_also_202_not_an_error():
    """Any notification (no `id`) gets 202 — the point of a notification is
    the sender doesn't want a reply, known method or not. Pins that this
    isn't special-cased to JUST notifications/initialized."""
    client, bearer, (p1, p2, p3) = _client_with_token()
    with p1, p2, p3, patch.object(database, "fetch_one", _fake_plan_fetch_one):
        resp = client.post(
            "/api/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/some_future_thing"},
            headers={"Authorization": f"Bearer {bearer}",
                     "Accept": "application/json, text/event-stream"},
        )
    assert resp.status_code == 202
    assert resp.content == b""
    print("✅ test_unknown_notification_method_is_also_202_not_an_error")


# =============================================================================
# 3. tools/list with the echoed session id -> the full 91-tool result.
# (86 as of C65 + C48's 5 new media tools: get_scene_boards,
# get_character_sheets, get_environment_images, get_thumbnail_image,
# quick_demo_video.)
# =============================================================================

def test_tools_list_with_echoed_session_id_returns_full_toolset():
    import routes.mcp as mcp_mod

    client, bearer, (p1, p2, p3) = _client_with_token()
    with p1, p2, p3, patch.object(database, "fetch_one", _fake_plan_fetch_one):
        init_resp = client.post(
            "/api/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            headers={"Authorization": f"Bearer {bearer}",
                     "Accept": "application/json, text/event-stream"},
        )
        session_id = init_resp.headers["Mcp-Session-Id"]

        notif_resp = client.post(
            "/api/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers={"Authorization": f"Bearer {bearer}", "Mcp-Session-Id": session_id,
                     "Accept": "application/json, text/event-stream"},
        )
        assert notif_resp.status_code == 202

        list_resp = client.post(
            "/api/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            headers={"Authorization": f"Bearer {bearer}", "Mcp-Session-Id": session_id,
                     "Accept": "application/json, text/event-stream"},
        )
    assert list_resp.status_code == 200, list_resp.text
    tools = list_resp.json()["result"]["tools"]
    # C66: +5 (get_production_guide, design_environments, redo_environment,
    # edit_environment, delete_environment) — 91 -> 96. Legitimate surface
    # growth, not a regression; see tasks/decisions.md 2026-07-21.
    assert len(tools) == len(mcp_mod.TOOLS) == 96, (
        f"expected the full {len(mcp_mod.TOOLS)}-tool surface, got {len(tools)}"
    )
    print(f"✅ test_tools_list_with_echoed_session_id_returns_full_toolset ({len(tools)} tools)")


# =============================================================================
# 4. GET listen stream: SSE content-type + auth still enforced.
# =============================================================================

def test_get_returns_sse_stream_when_authorized():
    client, bearer, (p1, p2, p3) = _client_with_token()
    with p1, p2, p3, patch.object(database, "fetch_one", _fake_plan_fetch_one):
        resp = client.get(
            "/api/mcp",
            headers={"Authorization": f"Bearer {bearer}", "Accept": "text/event-stream"},
        )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream"), resp.headers["content-type"]
    print("✅ test_get_returns_sse_stream_when_authorized")


def test_unauthorized_get_is_401_not_a_stream():
    client, _bearer, _patches = _client_with_token()
    resp = client.get("/api/mcp", headers={"Accept": "text/event-stream"})
    assert resp.status_code == 401, resp.text
    assert not resp.headers.get("content-type", "").startswith("text/event-stream"), (
        "an unauthorized GET must never open the SSE stream"
    )
    print("✅ test_unauthorized_get_is_401_not_a_stream")


def test_unauthorized_post_is_still_401():
    """Pins that the notification fast-path doesn't accidentally bypass
    auth_agent — the FastAPI Depends(get_agent_tenant_id) still runs before
    request.json() ever gets dispatched, notification or not."""
    client, _bearer, _patches = _client_with_token()
    resp = client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert resp.status_code == 401, resp.text
    print("✅ test_unauthorized_post_is_still_401")


TESTS = [
    test_initialize_with_combined_accept_header_returns_session_id,
    test_initialize_falls_back_on_unsupported_protocol_version,
    test_notifications_initialized_returns_202_with_no_body,
    test_unknown_notification_method_is_also_202_not_an_error,
    test_tools_list_with_echoed_session_id_returns_full_toolset,
    test_get_returns_sse_stream_when_authorized,
    test_unauthorized_get_is_401_not_a_stream,
    test_unauthorized_post_is_still_401,
]


def main() -> int:
    failed = 0
    for t in TESTS:
        try:
            t()
        except AssertionError as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
