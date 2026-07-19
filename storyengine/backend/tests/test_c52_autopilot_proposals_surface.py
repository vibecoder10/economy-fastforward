"""Tests for checklist C52 (P4.2-c) — the autopilot proposals read/decide
surface built on top of C51's propose_only dry-run loop
(autopilot_proposals.py / autopilot_launch.py).

Covers:
  1. autopilot_proposals.py CRUD additions: list_proposals (status filter +
     tenant scoping), count_pending, get_proposal (tenant-scoped, None on
     miss), mark_decided (atomic WHERE status='proposed' guard — returns
     None, doesn't raise, when the row is already decided).
  2. HTTP routes (routes/autopilot.py): GET /proposals is tenant-scoped;
     POST .../accept calls the EXISTING launch_candidate exactly once and
     only THEN marks the proposal 'accepted' with the launched video_id;
     a tripped kill switch refuses accept WITHOUT consuming the proposal;
     a launch failure (launch_candidate raises) does NOT consume the
     proposal either; POST .../dismiss marks 'dismissed'; a proposal_id
     that doesn't resolve for this tenant (get_proposal returns None) is a
     404 — this is exactly what tenant isolation looks like given
     get_proposal's own tenant_id AND id WHERE clause.
  3. MCP tools (routes/mcp.py): list_autopilot_proposals / accept_autopilot_
     proposal / dismiss_autopilot_proposal are registered, carry no
     confirm_token (free), and dispatch through the SAME routes.autopilot.
     accept_proposal/dismiss_proposal functions the HTTP door uses —
     attributed decided_by='mcp_agent'.
  4. Notify: autopilot_proposals.create_proposal drops one bot_activity row
     per new proposal (best-effort; a notify failure must not fail
     proposal creation).

No live DB — every DB boundary (fetch_one/fetch_all/execute) is patched at
the module level, same convention as tests/test_c51_candidate_auto_launch.py
and tests/functional/test_c47_mcp_setup_and_ingest.py.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/test_c52_autopilot_proposals_surface.py -q
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import autopilot_proposals
import routes.autopilot as autopilot_route
import routes.mcp as mcp_mod
from auth import AuthUser, get_tenant_id, verify_token
from autopilot_dial import AutopilotDial

TENANT = "tenant-c52"
OTHER_TENANT = "tenant-other"


def _proposal_row(**overrides):
    row = {
        "id": "prop-1",
        "tenant_id": TENANT,
        "candidate_id": "cand-1",
        "video_title": "How X Broke the Internet",
        "confidence_score": 82.0,
        "confidence_breakdown": {"total_score": 82.0},
        "status": "proposed",
        "decided_at": None,
        "decided_by": None,
        "video_id": None,
        "created_at": None,
    }
    row.update(overrides)
    return row


# =============================================================================
# 1. autopilot_proposals.py CRUD additions
# =============================================================================

def test_list_proposals_filters_by_status_and_tenant(monkeypatch):
    captured = {}

    async def fake_fetch_all(query, *args):
        captured["query"] = query
        captured["args"] = args
        return [_proposal_row()]

    monkeypatch.setattr(autopilot_proposals, "fetch_all", fake_fetch_all)
    rows = asyncio.run(autopilot_proposals.list_proposals(TENANT, status="proposed", limit=50))
    assert len(rows) == 1
    assert captured["args"] == (TENANT, "proposed", 50)
    assert "WHERE tenant_id = $1 AND status = $2" in captured["query"]


def test_list_proposals_no_status_filter_returns_all():
    async def fake_fetch_all(query, *args):
        assert args == (TENANT, 50)
        assert "status" not in query.split("ORDER BY")[0].split("WHERE")[1]
        return []

    import unittest.mock as _um
    with _um.patch.object(autopilot_proposals, "fetch_all", fake_fetch_all):
        rows = asyncio.run(autopilot_proposals.list_proposals(TENANT, status=None, limit=50))
    assert rows == []


def test_count_pending_counts_proposed_only(monkeypatch):
    async def fake_fetch_one(query, *args):
        assert "status = 'proposed'" in query
        assert args == (TENANT,)
        return {"c": 3}

    monkeypatch.setattr(autopilot_proposals, "fetch_one", fake_fetch_one)
    assert asyncio.run(autopilot_proposals.count_pending(TENANT)) == 3


def test_get_proposal_tenant_scoped_none_on_miss(monkeypatch):
    async def fake_fetch_one(query, *args):
        assert "tenant_id = $1 AND id = $2" in query
        assert args == (TENANT, "prop-1")
        return None

    monkeypatch.setattr(autopilot_proposals, "fetch_one", fake_fetch_one)
    assert asyncio.run(autopilot_proposals.get_proposal(TENANT, "prop-1")) is None


def test_mark_decided_returns_row_on_success(monkeypatch):
    async def fake_fetch_one(query, *args):
        assert "status = 'proposed'" in query
        assert args == ("accepted", "user@x.com", "vid-1", TENANT, "prop-1")
        return _proposal_row(status="accepted", decided_by="user@x.com", video_id="vid-1")

    monkeypatch.setattr(autopilot_proposals, "fetch_one", fake_fetch_one)
    row = asyncio.run(autopilot_proposals.mark_decided(
        TENANT, "prop-1", status="accepted", decided_by="user@x.com", video_id="vid-1",
    ))
    assert row["status"] == "accepted"


def test_mark_decided_returns_none_when_already_decided(monkeypatch):
    """The atomic WHERE status='proposed' guard: a row that's already
    decided just doesn't match the UPDATE, so RETURNING yields nothing —
    no exception, the caller treats None as 'already decided'."""
    async def fake_fetch_one(query, *args):
        return None

    monkeypatch.setattr(autopilot_proposals, "fetch_one", fake_fetch_one)
    row = asyncio.run(autopilot_proposals.mark_decided(
        TENANT, "prop-1", status="dismissed", decided_by="user@x.com",
    ))
    assert row is None


def test_create_proposal_drops_a_bot_activity_notify_row(monkeypatch):
    """C52 item 3 — notify mechanism: reuse bot_activity (the existing
    activity feed table), not a new one. Best-effort: must not raise even
    if the fetch_one insert-returning call succeeds but the notify INSERT
    would fail (simulated separately below)."""
    async def fake_fetch_one(query, *args):
        return _proposal_row(video_title="Title", confidence_score=80.0)

    executed = []

    async def fake_execute(query, *args):
        executed.append((query, args))

    monkeypatch.setattr(autopilot_proposals, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(autopilot_proposals, "execute", fake_execute)

    asyncio.run(autopilot_proposals.create_proposal(
        TENANT, candidate_id="cand-1", video_title="Title", confidence_score=80.0,
    ))
    assert len(executed) == 1
    query, args = executed[0]
    assert "INSERT INTO bot_activity" in query
    assert args[0] == TENANT
    assert args[1] == "autopilot_proposal"


def test_create_proposal_notify_failure_does_not_raise(monkeypatch):
    async def fake_fetch_one(query, *args):
        return _proposal_row()

    async def fake_execute(query, *args):
        raise RuntimeError("db hiccup")

    monkeypatch.setattr(autopilot_proposals, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(autopilot_proposals, "execute", fake_execute)

    # Must not raise even though the notify INSERT blows up.
    row = asyncio.run(autopilot_proposals.create_proposal(
        TENANT, candidate_id="cand-1", video_title="Title", confidence_score=80.0,
    ))
    assert row["status"] == "proposed"


# =============================================================================
# 2. HTTP routes
# =============================================================================

def _build_client(monkeypatch, *, user=None):
    app = FastAPI()
    app.include_router(autopilot_route.router)
    app.dependency_overrides[get_tenant_id] = lambda: TENANT
    app.dependency_overrides[verify_token] = lambda: user or AuthUser(id="u1", email="user@x.com")
    return TestClient(app)


def test_list_proposals_route_tenant_scoped(monkeypatch):
    captured = {}

    async def fake_list_proposals(tenant_id, *, status=None, limit=50):
        captured["tenant_id"] = tenant_id
        captured["status"] = status
        return [_proposal_row()]

    monkeypatch.setattr(autopilot_proposals, "list_proposals", fake_list_proposals)
    client = _build_client(monkeypatch)
    resp = client.get("/api/autopilot/proposals")
    assert resp.status_code == 200
    assert captured["tenant_id"] == TENANT
    assert captured["status"] == "proposed"
    body = resp.json()
    assert len(body) == 1
    assert body[0]["candidate_id"] == "cand-1"


def test_list_proposals_route_all_status(monkeypatch):
    captured = {}

    async def fake_list_proposals(tenant_id, *, status=None, limit=50):
        captured["status"] = status
        return []

    monkeypatch.setattr(autopilot_proposals, "list_proposals", fake_list_proposals)
    client = _build_client(monkeypatch)
    resp = client.get("/api/autopilot/proposals?status=all")
    assert resp.status_code == 200
    assert captured["status"] is None


def test_accept_marks_and_calls_launch_once_and_writes_video_id(monkeypatch):
    async def fake_get_proposal(tenant_id, proposal_id):
        assert tenant_id == TENANT
        return _proposal_row()

    async def fake_get_dial(tenant_id):
        return AutopilotDial(dial_level="propose_only")

    launch_calls = []

    async def fake_launch_candidate(candidate_id, background_tasks, tenant_id):
        launch_calls.append((candidate_id, tenant_id))
        return {"status": "launched", "candidate_id": candidate_id, "video_id": "vid-42",
                "video_title": "x", "message": "Video created and pipeline started"}

    mark_calls = []

    async def fake_mark_decided(tenant_id, proposal_id, *, status, decided_by, video_id=None):
        mark_calls.append((tenant_id, proposal_id, status, decided_by, video_id))
        return _proposal_row(status="accepted", decided_by=decided_by, video_id=video_id)

    monkeypatch.setattr(autopilot_proposals, "get_proposal", fake_get_proposal)
    monkeypatch.setattr(autopilot_route, "get_autopilot_dial", fake_get_dial)
    monkeypatch.setattr(autopilot_route, "launch_candidate", fake_launch_candidate)
    monkeypatch.setattr(autopilot_proposals, "mark_decided", fake_mark_decided)

    client = _build_client(monkeypatch, user=AuthUser(id="u1", email="ryan@x.com"))
    resp = client.post("/api/autopilot/proposals/prop-1/accept")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["video_id"] == "vid-42"
    assert launch_calls == [("cand-1", TENANT)]
    assert len(mark_calls) == 1
    assert mark_calls[0] == (TENANT, "prop-1", "accepted", "ryan@x.com", "vid-42")


def test_accept_with_tripped_kill_switch_refuses_and_does_not_consume(monkeypatch):
    async def fake_get_proposal(tenant_id, proposal_id):
        return _proposal_row()

    async def fake_get_dial(tenant_id):
        return AutopilotDial(
            dial_level="propose_only",
            kill_switch_tripped_at=dt.datetime.now(dt.timezone.utc),
            kill_switch_reason="weekly budget cap breached",
        )

    async def fake_launch_candidate(*a, **k):
        raise AssertionError("launch_candidate must NOT be called when the kill switch is tripped")

    async def fake_mark_decided(*a, **k):
        raise AssertionError("mark_decided must NOT be called when the kill switch is tripped")

    monkeypatch.setattr(autopilot_proposals, "get_proposal", fake_get_proposal)
    monkeypatch.setattr(autopilot_route, "get_autopilot_dial", fake_get_dial)
    monkeypatch.setattr(autopilot_route, "launch_candidate", fake_launch_candidate)
    monkeypatch.setattr(autopilot_proposals, "mark_decided", fake_mark_decided)

    client = _build_client(monkeypatch)
    resp = client.post("/api/autopilot/proposals/prop-1/accept")

    assert resp.status_code == 409
    assert "kill switch" in resp.json()["detail"].lower()


def test_accept_launch_failure_does_not_consume_proposal(monkeypatch):
    async def fake_get_proposal(tenant_id, proposal_id):
        return _proposal_row()

    async def fake_get_dial(tenant_id):
        return AutopilotDial(dial_level="propose_only")

    async def fake_launch_candidate(candidate_id, background_tasks, tenant_id):
        raise HTTPException(status_code=400, detail="Candidate already launched")

    async def fake_mark_decided(*a, **k):
        raise AssertionError("mark_decided must NOT be called when launch_candidate fails")

    monkeypatch.setattr(autopilot_proposals, "get_proposal", fake_get_proposal)
    monkeypatch.setattr(autopilot_route, "get_autopilot_dial", fake_get_dial)
    monkeypatch.setattr(autopilot_route, "launch_candidate", fake_launch_candidate)
    monkeypatch.setattr(autopilot_proposals, "mark_decided", fake_mark_decided)

    client = _build_client(monkeypatch)
    resp = client.post("/api/autopilot/proposals/prop-1/accept")

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Candidate already launched"


def test_accept_already_decided_proposal_is_rejected_before_any_launch(monkeypatch):
    async def fake_get_proposal(tenant_id, proposal_id):
        return _proposal_row(status="accepted")

    async def fake_launch_candidate(*a, **k):
        raise AssertionError("must not launch an already-decided proposal")

    monkeypatch.setattr(autopilot_proposals, "get_proposal", fake_get_proposal)
    monkeypatch.setattr(autopilot_route, "launch_candidate", fake_launch_candidate)

    client = _build_client(monkeypatch)
    resp = client.post("/api/autopilot/proposals/prop-1/accept")
    assert resp.status_code == 400


def test_accept_unknown_proposal_is_404_tenant_isolation(monkeypatch):
    """get_proposal's own tenant_id AND id WHERE means a proposal belonging
    to a different tenant (or one that doesn't exist) is indistinguishable
    from 'not found' — this IS the tenant-isolation guarantee."""
    async def fake_get_proposal(tenant_id, proposal_id):
        assert tenant_id == TENANT
        return None

    monkeypatch.setattr(autopilot_proposals, "get_proposal", fake_get_proposal)
    client = _build_client(monkeypatch)
    resp = client.post("/api/autopilot/proposals/someone-elses-proposal/accept")
    assert resp.status_code == 404


def test_dismiss_marks(monkeypatch):
    async def fake_get_proposal(tenant_id, proposal_id):
        return _proposal_row()

    mark_calls = []

    async def fake_mark_decided(tenant_id, proposal_id, *, status, decided_by, video_id=None):
        mark_calls.append((tenant_id, proposal_id, status, decided_by, video_id))
        return _proposal_row(status="dismissed", decided_by=decided_by)

    monkeypatch.setattr(autopilot_proposals, "get_proposal", fake_get_proposal)
    monkeypatch.setattr(autopilot_proposals, "mark_decided", fake_mark_decided)

    client = _build_client(monkeypatch, user=AuthUser(id="u1", email="ryan@x.com"))
    resp = client.post("/api/autopilot/proposals/prop-1/dismiss")

    assert resp.status_code == 200
    assert resp.json()["status"] == "dismissed"
    assert mark_calls == [(TENANT, "prop-1", "dismissed", "ryan@x.com", None)]


def test_dismiss_unknown_proposal_is_404(monkeypatch):
    async def fake_get_proposal(tenant_id, proposal_id):
        return None

    monkeypatch.setattr(autopilot_proposals, "get_proposal", fake_get_proposal)
    client = _build_client(monkeypatch)
    resp = client.post("/api/autopilot/proposals/nope/dismiss")
    assert resp.status_code == 404


def test_dismiss_race_already_decided_returns_409(monkeypatch):
    async def fake_get_proposal(tenant_id, proposal_id):
        return _proposal_row()

    async def fake_mark_decided(*a, **k):
        return None  # simulates the race: someone else decided it first

    monkeypatch.setattr(autopilot_proposals, "get_proposal", fake_get_proposal)
    monkeypatch.setattr(autopilot_proposals, "mark_decided", fake_mark_decided)

    client = _build_client(monkeypatch)
    resp = client.post("/api/autopilot/proposals/prop-1/dismiss")
    assert resp.status_code == 409


def test_summary_surfaces_pending_proposals_count(monkeypatch):
    async def fake_fetch_one(query, *args):
        if "COUNT(*)" in query and "videos" in query:
            return {"count": 0}
        if "AVG(ctr)" in query:
            return {"avg": None}
        if "FROM autopilot_config" in query:
            return None
        return None

    async def fake_fetch_all(query, *args):
        return []

    async def fake_count_pending(tenant_id):
        assert tenant_id == TENANT
        return 4

    async def fake_get_dial(tenant_id):
        return AutopilotDial()

    monkeypatch.setattr(autopilot_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(autopilot_route, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(autopilot_route, "get_autopilot_dial", fake_get_dial)
    monkeypatch.setattr(autopilot_proposals, "count_pending", fake_count_pending)

    client = _build_client(monkeypatch)
    resp = client.get("/api/autopilot/summary")
    assert resp.status_code == 200
    assert resp.json()["state"]["pending_proposals_count"] == 4


# =============================================================================
# 3. MCP tools
# =============================================================================

def test_new_autopilot_proposal_tools_present():
    names = mcp_mod.TOOL_NAMES
    for name in ("list_autopilot_proposals", "accept_autopilot_proposal", "dismiss_autopilot_proposal"):
        assert name in names, f"missing C52 tool: {name}"


def test_none_of_the_new_tools_carry_a_confirm_token():
    for tool in mcp_mod._AUTOPILOT_PROPOSAL_TOOLS:
        props = tool["inputSchema"].get("properties", {})
        assert "confirm_token" not in props, f"{tool['name']} must be free (no confirm_token)"


async def test_list_autopilot_proposals_tool_calls_same_store_function():
    import unittest.mock as _um
    list_mock = _um.AsyncMock(return_value=[_proposal_row()])
    with _um.patch.object(autopilot_proposals, "list_proposals", list_mock):
        result = await mcp_mod._call_list_autopilot_proposals(TENANT, {}, "agent")
    list_mock.assert_awaited_once_with(TENANT, status="proposed", limit=50)
    payload = json.loads(result["content"][0]["text"])
    assert len(payload["proposals"]) == 1
    assert result["isError"] is False


async def test_accept_autopilot_proposal_tool_calls_same_route_function_with_mcp_attribution():
    import unittest.mock as _um

    class _FakeBackgroundTasks:
        def add_task(self, fn, *a, **k):
            pass

    accept_mock = _um.AsyncMock(
        return_value=autopilot_route.ProposalDecisionResult(
            status="accepted", proposal_id="prop-1", video_id="vid-1", message="Launched",
        )
    )
    with _um.patch.object(autopilot_route, "accept_proposal", accept_mock):
        result = await mcp_mod._call_accept_autopilot_proposal(
            TENANT, {"proposal_id": "prop-1"}, "agent:Claude Desktop", _FakeBackgroundTasks(),
        )
    accept_mock.assert_awaited_once()
    args, kwargs = accept_mock.call_args
    assert args[0] == TENANT
    assert args[1] == "prop-1"
    assert kwargs["decided_by"] == "mcp_agent"
    assert result["isError"] is False


async def test_accept_autopilot_proposal_tool_missing_id_errors_without_a_call():
    import unittest.mock as _um
    accept_mock = _um.AsyncMock(side_effect=AssertionError("must not call without a proposal_id"))
    with _um.patch.object(autopilot_route, "accept_proposal", accept_mock):
        result = await mcp_mod._call_accept_autopilot_proposal(TENANT, {}, "agent", object())
    assert result["isError"] is True


async def test_accept_autopilot_proposal_tool_surfaces_route_error_not_a_500():
    import unittest.mock as _um

    class _FakeBackgroundTasks:
        def add_task(self, fn, *a, **k):
            pass

    accept_mock = _um.AsyncMock(side_effect=HTTPException(status_code=409, detail="Autopilot kill switch is tripped"))
    with _um.patch.object(autopilot_route, "accept_proposal", accept_mock):
        result = await mcp_mod._call_accept_autopilot_proposal(
            TENANT, {"proposal_id": "prop-1"}, "agent", _FakeBackgroundTasks(),
        )
    assert result["isError"] is True
    assert "kill switch" in result["content"][0]["text"].lower()


async def test_dismiss_autopilot_proposal_tool_calls_same_route_function_with_mcp_attribution():
    import unittest.mock as _um
    dismiss_mock = _um.AsyncMock(
        return_value=autopilot_route.ProposalDecisionResult(
            status="dismissed", proposal_id="prop-1", video_id=None, message="Dismissed",
        )
    )
    with _um.patch.object(autopilot_route, "dismiss_proposal", dismiss_mock):
        result = await mcp_mod._call_dismiss_autopilot_proposal(TENANT, {"proposal_id": "prop-1"}, "agent")
    dismiss_mock.assert_awaited_once_with(TENANT, "prop-1", decided_by="mcp_agent")
    assert result["isError"] is False


def test_dispatch_routes_all_three_tool_names():
    """Wiring proof: _dispatch's tools/call branch actually reaches each new
    handler (not just that the handler function exists somewhere)."""
    import unittest.mock as _um

    async def _run():
        list_mock = _um.AsyncMock(return_value=[])
        with _um.patch.object(autopilot_proposals, "list_proposals", list_mock):
            await mcp_mod._dispatch(
                "tools/call", {"name": "list_autopilot_proposals", "arguments": {}}, TENANT,
            )
        list_mock.assert_awaited_once()

        class _FakeBackgroundTasks:
            def add_task(self, fn, *a, **k):
                pass

        accept_mock = _um.AsyncMock(
            return_value=autopilot_route.ProposalDecisionResult(
                status="accepted", proposal_id="p1", video_id="v1", message="ok",
            )
        )
        with _um.patch.object(autopilot_route, "accept_proposal", accept_mock):
            await mcp_mod._dispatch(
                "tools/call", {"name": "accept_autopilot_proposal", "arguments": {"proposal_id": "p1"}},
                TENANT, _FakeBackgroundTasks(),
            )
        accept_mock.assert_awaited_once()

        dismiss_mock = _um.AsyncMock(
            return_value=autopilot_route.ProposalDecisionResult(
                status="dismissed", proposal_id="p1", video_id=None, message="ok",
            )
        )
        with _um.patch.object(autopilot_route, "dismiss_proposal", dismiss_mock):
            await mcp_mod._dispatch(
                "tools/call", {"name": "dismiss_autopilot_proposal", "arguments": {"proposal_id": "p1"}}, TENANT,
            )
        dismiss_mock.assert_awaited_once()

    asyncio.run(_run())
