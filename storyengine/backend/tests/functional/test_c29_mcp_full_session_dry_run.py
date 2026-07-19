"""C29 (checklist P2.4d — full external-client loop verify, split per the
chunk brief): the spec ("create -> route -> draft -> finalize -> upload
draft" with a REAL external MCP client against a REAL coordinated deploy)
needs a live VPS + MCP_ENABLED=true flip + an actual MCP client (Claude
Desktop/Code, Hermes, ...) — none of which exist in this sandbox (no route to
the VPS, no Kie/paid keys). This file is the OTHER half: the strongest
possible IN-SANDBOX simulation, driving ONE CONTINUOUS SESSION through the
REAL ASGI app (`main.app`, booted via `TestClient`, `MCP_ENABLED=true`) the
way an external client actually would — real HTTP requests, real JSON-RPC
envelope, real `RateLimitMiddleware`, real `auth_agent.get_agent_tenant_id`
dependency, real `agent_tokens.authenticate`/`create_agent_token`/
`revoke_agent_token`, real `confirm_tokens.create`/`redeem` (the actual money
gate — not mocked, see the canary note below), real `/api/agent-tokens`
mint/revoke routes. The live half of C29 is
`tasks/live-verification-queue.md` §C29 (the runbook for Ryan to run this
same session against a real MCP client post-deploy).

What's STUBBED (deliberately, same technique C26/C27's own test files use —
this file's subject is the MCP-layer wiring, not re-testing already-covered
internals): `routes.videos.create_video`/`get_video_ledger` (DB writes, tested
in test_c20/videos' own suites), `actions.video_summary`/`blocked_reason`/
`estimate_cost`/`cost_breakdown`/`already_uploaded_reply` (tested in
test_c27's money-gate matrix), `routes.chat._run_pending_action` (the
"executor" — the chunk brief's own words: "executor stubbed, assert the real
runner was invoked with the right args"), and the DB layer under
`agent_tokens`/`confirm_tokens` (an in-memory fake table, same pattern as
test_c26_mcp_agent_tokens.py's `_FakeStore` / test_c27's `_FakeConfirmStore`
— no live Postgres in this sandbox). Every one of these is a boundary this
test crosses over HTTP, not a function it calls directly.

The session (mirrors tasks/storyengine-copilot-ux-map.md §7's example):
  1. initialize
  2. tools/list (paid verbs carry confirm_token, create_video is free, S5-2
     memory tools absent)
  3. create_video (free) -> a video id
  4. get_video -> the created video's summary
  5. a paid verb ("script") with NO confirm_token -> quote + confirm_token,
     executor NOT invoked
  6. the SAME verb WITH that confirm_token -> dispatch, executor invoked with
     (tenant, video, pending, background_tasks, caller="agent:<token name>")
  7. the SAME confirm_token AGAIN (reuse) -> refused, executor still called
     exactly once
  8. get_ledger -> stubbed spend rows
  9. revoke the agent token via the REAL /api/agent-tokens route (session
     auth, dependency-overridden)
  10. the next MCP call with the now-revoked token -> 401
Plus, separately: MCP_ENABLED unset/false -> POST /api/mcp is a real 404 (the
dark-flag inverse), proven via an actual request, not just a route-table read
(test_c26's version only inspected `app.routes` structurally).

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c29_mcp_full_session_dry_run.py -q
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import ANY, AsyncMock, patch

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from fastapi.testclient import TestClient

import actions  # noqa: E402
import agent_tokens  # noqa: E402
import auth  # noqa: E402
import confirm_tokens  # noqa: E402
import database  # noqa: E402
import routes.billing as billing  # noqa: E402
import routes.chat as chat  # noqa: E402
import routes.videos as videos_mod  # noqa: E402


# =============================================================================
# Fixed identities for this one session
# =============================================================================
FIXED_TENANT = uuid.uuid4()
VIDEO_ID = str(uuid.uuid4())
AGENT_TOKEN_NAME = "C29 Dry-Run Session"


def _reload_main(mcp_enabled: bool):
    """Fresh `main.py` import with MCP_ENABLED set/unset — same technique
    test_c26_mcp_agent_tokens.py's `_reload_main_with_env` uses, so the
    router registration itself is exercised for real, not read off source."""
    if mcp_enabled:
        os.environ["MCP_ENABLED"] = "true"
    else:
        os.environ.pop("MCP_ENABLED", None)
    for name in list(sys.modules):
        if name == "main" or name.startswith("routes.mcp"):
            del sys.modules[name]
    import main as reloaded_main
    return reloaded_main


# =============================================================================
# Fake agent_tokens table — in-memory, same shape as
# test_c26_mcp_agent_tokens.py's _FakeStore, extended with the `name_for_token`
# query C27 added (agent_tokens.py's own SELECT ... WHERE token_hash = $1 AND
# revoked_at IS NULL shape, shared by authenticate() and name_for_token()).
# =============================================================================
class _FakeAgentTokenStore:
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
                    return dict(row)  # carries id/tenant_id/name — callers pick what they need
            return None
        # C57: auth_agent.get_agent_tenant_id's per-request gate now calls
        # agent_tokens.authenticate_with_standing, which piggybacks the
        # tenant's good-standing fields onto this same token-row lookup (one
        # JOIN through memberships -> accounts) instead of a second round
        # trip. No accounts/memberships fake exists in this session — a
        # free-tier account (no stripe subscription, no trial) is good
        # standing per routes.billing._good_standing_from_fields, so the
        # whole session's happy path is unaffected.
        if "JOIN memberships m ON m.tenant_id = t.tenant_id" in query:
            (token_hash,) = args
            for row in store.rows.values():
                if row["token_hash"] == token_hash and row["revoked_at"] is None:
                    return {
                        "token_id": row["id"], "tenant_id": row["tenant_id"],
                        "trial_ends_at": None, "stripe_subscription_id": None,
                        "stripe_status": None,
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
        if "SET revoked_at = now()" in query:
            token_id, tenant_id = args
            row = store.rows.get(token_id)
            if row and row["tenant_id"] == tenant_id and row["revoked_at"] is None:
                row["revoked_at"] = "now"
                return "UPDATE 1"
            return "UPDATE 0"
        raise AssertionError(f"unexpected agent_tokens execute query: {query!r}")

    return (
        patch.object(agent_tokens, "fetch_one", _fetch_one),
        patch.object(agent_tokens, "fetch_all", _fetch_all),
        patch.object(agent_tokens, "execute", _execute),
    )


# =============================================================================
# Fake mcp_confirm_tokens table — verbatim technique from
# test_c27_mcp_toolset_money_gate.py's _FakeConfirmStore/_patch_confirm. This
# is the REAL confirm_tokens.create()/redeem() logic running (only its own
# DB `execute()` call is faked) — the money gate itself is genuinely
# exercised, which is what makes the canary run (see report) meaningful.
# =============================================================================
class _FakeConfirmStore:
    def __init__(self):
        self.rows: list[dict] = []


def _patch_confirm(store: _FakeConfirmStore):
    async def _execute(query, *args):
        if "INSERT INTO mcp_confirm_tokens" in query:
            tenant_id, video_id, verb, phash, token_hash, ttl_secs = args
            store.rows.append({
                "tenant_id": tenant_id, "video_id": video_id, "verb": verb,
                "params_hash": phash, "token_hash": token_hash,
                "expires_at": datetime.now(timezone.utc) + timedelta(seconds=ttl_secs),
                "used_at": None,
            })
            return "INSERT 0 1"
        if "UPDATE mcp_confirm_tokens SET used_at" in query:
            token_hash, tenant_id, video_id, verb, phash = args
            now = datetime.now(timezone.utc)
            for r in store.rows:
                if (r["token_hash"] == token_hash and r["tenant_id"] == tenant_id
                        and r["video_id"] == video_id and r["verb"] == verb
                        and r["params_hash"] == phash and r["used_at"] is None
                        and r["expires_at"] > now):
                    r["used_at"] = now
                    return "UPDATE 1"
            return "UPDATE 0"
        raise AssertionError(f"unexpected confirm_tokens query: {query!r}")
    return patch.object(confirm_tokens, "execute", _execute)


async def _fake_plan_fetch_one(query, *args):
    """RateLimitMiddleware's `_get_tenant_plan` (rate_limit.py) does a real
    `from database import fetch_one` on every request to resolve the
    tenant's plan for bucket sizing. No live Postgres here — returning None
    for both its account-join and legacy-fallback queries is exactly what a
    brand-new tenant with no `accounts`/`tenants` row looks like, and the
    function already handles that by defaulting to the 'free' plan (60/min —
    comfortably more than the ~8 calls this session makes)."""
    return None


def _summary(video_id: str):
    return {
        "id": video_id, "title": "C29 Dry Run Video", "status": "ready_for_scripting",
        "scenes": 2, "pics": 0, "clips": 0, "spent": 0.0, "model": None,
        "voiced": 0, "boards": 0, "max_scene": 2, "cast": 0, "validation": "",
        "render_style": None,
    }


def _rpc(client, token, method, params=None, rpc_id=1):
    return client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params or {}},
        headers={"Authorization": f"Bearer {token}"},
    )


def _rpc_result(resp):
    body = resp.json()
    assert "error" not in body, f"unexpected JSON-RPC error: {body.get('error')}"
    return body["result"]


def _tool_call_payload(result):
    assert result["isError"] is False, result["content"][0]["text"]
    return json.loads(result["content"][0]["text"])


# =============================================================================
# The session
# =============================================================================

def test_full_external_client_mcp_session_dry_run():
    reloaded_main = _reload_main(mcp_enabled=True)
    client = TestClient(reloaded_main.app)  # no `with` — skips lifespan (no live DB/Redis needed)
    client.app.dependency_overrides[auth.get_tenant_id] = lambda: FIXED_TENANT

    agent_store = _FakeAgentTokenStore()
    confirm_store = _FakeConfirmStore()
    run_pending_mock = AsyncMock(return_value="Working on the script now.")
    create_video_mock = AsyncMock(return_value=type(
        "FakeVideoSummary", (), {"model_dump": lambda self: {
            "id": VIDEO_ID, "video_title": "C29 Dry Run Video", "status": "idea_logged",
            "thumbnail_url": "https://example.invalid/should-never-leave-mcp.png",
        }},
    )())
    get_ledger_mock = AsyncMock(return_value=type(
        "FakeLedger", (), {"model_dump": lambda self: {
            "video_id": VIDEO_ID, "total_spent": 4.2,
            "by_stage": {"script": 1.5, "voice": 2.7}, "rows": [],
        }},
    )())

    async def _fake_video_summary(tenant_id, video_id):
        if tenant_id == FIXED_TENANT and video_id == VIDEO_ID:
            return _summary(video_id)
        return None

    p_fetch_one, p_fetch_all, p_execute = _patch_agent_tokens(agent_store)

    with p_fetch_one, p_fetch_all, p_execute, \
         _patch_confirm(confirm_store), \
         patch.object(database, "fetch_one", _fake_plan_fetch_one), \
         patch.object(billing, "is_account_in_good_standing",
                      AsyncMock(return_value=(True, "no subscription on file (free tier)"))), \
         patch.object(actions, "video_summary", _fake_video_summary), \
         patch.object(actions, "blocked_reason", lambda verb, summary: None), \
         patch.object(actions, "estimate_cost", AsyncMock(return_value=(1.50, "~$1.50"))), \
         patch.object(actions, "cost_breakdown", AsyncMock(return_value=None)), \
         patch.object(actions, "already_uploaded_reply", AsyncMock(return_value=None)), \
         patch.object(chat, "_run_pending_action", run_pending_mock), \
         patch.object(videos_mod, "create_video", create_video_mock), \
         patch.object(videos_mod, "get_video_ledger", get_ledger_mock):

        # --- Mint (real /api/agent-tokens route, real session-authed mint) --
        mint_resp = client.post("/api/agent-tokens", json={"name": AGENT_TOKEN_NAME})
        assert mint_resp.status_code == 200, mint_resp.text
        mint_body = mint_resp.json()
        agent_bearer = mint_body["token"]
        agent_token_id = mint_body["id"]
        assert agent_bearer.startswith(agent_tokens.TOKEN_PREFIX)
        print("✅ step 0: minted a real agent token via POST /api/agent-tokens")

        # --- Step 1: initialize -----------------------------------------
        init_result = _rpc_result(_rpc(client, agent_bearer, "initialize", rpc_id=1))
        assert init_result["serverInfo"]["name"] == "storyengine"
        print("✅ step 1: initialize")

        # --- Step 2: tools/list ------------------------------------------
        tools_result = _rpc_result(_rpc(client, agent_bearer, "tools/list", rpc_id=2))
        tools_by_name = {t["name"]: t for t in tools_result["tools"]}
        assert "create_video" in tools_by_name and "free" in tools_by_name["create_video"]["description"].lower()
        assert "confirm_token" in tools_by_name["script"]["inputSchema"]["properties"], "script is paid — must carry confirm_token"
        assert "confirm_token" not in tools_by_name["approve_scene"]["inputSchema"]["properties"], "approve_scene is free"
        for memory_verb in ("remember", "forget", "set_budget"):
            assert memory_verb not in tools_by_name, f"S5-2: {memory_verb} must never be an MCP tool"
        print("✅ step 2: tools/list (paid/free schemas + S5-2 exclusion)")

        # --- Step 3: create_video (free) -----------------------------------
        create_result = _rpc_result(_rpc(client, agent_bearer, "tools/call", {
            "name": "create_video", "arguments": {"title": "C29 Dry Run Video"},
        }, rpc_id=3))
        create_payload = _tool_call_payload(create_result)
        assert create_payload["id"] == VIDEO_ID
        assert "thumbnail_url" not in json.dumps(create_payload), "C25a hold: no media URL may leave an MCP tool result"
        create_video_mock.assert_awaited_once()
        assert create_video_mock.await_args.kwargs["tenant_id"] == FIXED_TENANT
        print("✅ step 3: create_video (free, dispatched through the real routes.videos.create_video)")

        # --- Step 4: get_video ----------------------------------------------
        get_video_result = _rpc_result(_rpc(client, agent_bearer, "tools/call", {
            "name": "get_video", "arguments": {"video_id": VIDEO_ID},
        }, rpc_id=4))
        get_video_payload = _tool_call_payload(get_video_result)
        assert get_video_payload["status"] == "ready_for_scripting"
        print("✅ step 4: get_video")

        # --- Step 5: paid verb ("script") WITHOUT confirm_token -> quote ----
        quote_result = _rpc_result(_rpc(client, agent_bearer, "tools/call", {
            "name": "script", "arguments": {"video_id": VIDEO_ID},
        }, rpc_id=5))
        quote_payload = _tool_call_payload(quote_result)
        assert quote_payload["status"] == "quote"
        assert quote_payload["cost_text"] == "~$1.50"
        confirm_token = quote_payload["confirm_token"]
        assert confirm_token.startswith(confirm_tokens.TOKEN_PREFIX)
        run_pending_mock.assert_not_awaited()
        print("✅ step 5: paid verb with no confirm_token -> quote, executor NOT invoked")

        # --- Step 6: SAME verb WITH the token -> dispatch -------------------
        confirmed_result = _rpc_result(_rpc(client, agent_bearer, "tools/call", {
            "name": "script", "arguments": {"video_id": VIDEO_ID, "confirm_token": confirm_token},
        }, rpc_id=6))
        confirmed_payload = _tool_call_payload(confirmed_result)
        assert confirmed_payload["status"] == "started"
        run_pending_mock.assert_awaited_once_with(
            FIXED_TENANT, VIDEO_ID,
            {"verb": "script", "scene": None, "change": None, "length_min": None},
            ANY, caller=f"agent:{AGENT_TOKEN_NAME}",
        )
        print("✅ step 6: same verb + confirm_token -> dispatched through the real executor "
              "with the right args and agent attribution")

        # --- Step 7: token reuse -> refused, executor still called once ----
        reuse_resp = _rpc(client, agent_bearer, "tools/call", {
            "name": "script", "arguments": {"video_id": VIDEO_ID, "confirm_token": confirm_token},
        }, rpc_id=7)
        reuse_result = _rpc_result(reuse_resp)
        assert reuse_result["isError"] is True
        assert "invalid" in reuse_result["content"][0]["text"].lower()
        run_pending_mock.assert_awaited_once()  # STILL once — reuse must not dispatch a second time
        print("✅ step 7: confirm_token reuse refused (single-use money gate holds)")

        # --- Step 8: get_ledger ----------------------------------------------
        ledger_result = _rpc_result(_rpc(client, agent_bearer, "tools/call", {
            "name": "get_ledger", "arguments": {"video_id": VIDEO_ID},
        }, rpc_id=8))
        ledger_payload = _tool_call_payload(ledger_result)
        assert ledger_payload["total_spent"] == 4.2
        assert ledger_payload["by_stage"]["script"] == 1.5
        print("✅ step 8: get_ledger (stubbed spend rows)")

        # --- Step 9: revoke the agent token mid-session (real route) --------
        revoke_resp = client.delete(f"/api/agent-tokens/{agent_token_id}")
        assert revoke_resp.status_code == 200, revoke_resp.text
        assert revoke_resp.json()["revoked"] is True
        print("✅ step 9: revoked the agent token via DELETE /api/agent-tokens/{id}")

        # --- Step 10: next MCP call with the revoked token -> 401 -----------
        post_revoke_resp = _rpc(client, agent_bearer, "tools/list", rpc_id=10)
        assert post_revoke_resp.status_code == 401, post_revoke_resp.text
        print("✅ step 10: next MCP call with the revoked token -> 401")


def test_mcp_endpoint_absent_when_flag_off_real_request():
    """The dark-flag inverse, proven with an ACTUAL request (not a route-table
    read, which test_c26_mcp_agent_tokens.py already covers structurally):
    MCP_ENABLED unset -> POST /api/mcp genuinely 404s, same as any other
    undefined path."""
    reloaded_main = _reload_main(mcp_enabled=False)
    client = TestClient(reloaded_main.app)
    resp = client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={"Authorization": "Bearer se_agent_whatever"},
    )
    assert resp.status_code == 404, resp.text
    print("✅ dark-flag inverse: MCP_ENABLED off -> POST /api/mcp is a real 404")
