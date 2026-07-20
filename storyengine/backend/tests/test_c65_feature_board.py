"""Tests for C65 (checklist "Feature board" — tasks/decisions.md 2026-07-20
entry). "Suggest a feature" + upvotes + a status ladder, the platform's
FIRST deliberately CROSS-TENANT surface.

Covers:
  1. Create: length caps (title/body), rate limit (max 5/day/account).
  2. One vote per account per idea (second vote is a no-op, not an error);
     unvote.
  3. Cross-ACCOUNT visibility: two different accounts both see the SAME
     board — the explicit pin that this route does NOT tenant/account-scope
     its reads.
  4. Operator-only status change: 403 for a non-operator, 200 + the new
     status for an operator; bad status value rejected (400).
  5. Raw text: the API returns title/body VERBATIM — no server-side HTML
     interpretation (React escapes client-side; this pins the API layer
     never does anything fancier than store-and-return).
  6. MCP tools (list_feature_requests, suggest_feature, vote_feature_request)
     registered in mcp.TOOL_NAMES and dispatch through the SAME route
     functions the HTTP door uses (no parallel logic), attributed via a
     resolved account_id.

Uses an in-memory FakeDB (same convention as tests/test_drive_workspace.py /
tests/test_autopilot_dial_route.py: monkeypatch the module-level fetch_all/
fetch_one/execute the route file imported, TestClient + dependency_overrides
for auth). No live DB, no network.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/test_c65_feature_board.py -q
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _BACKEND)

from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.feature_board as feature_board
import routes.workspaces as workspaces
from auth import AuthUser, verify_token

ACCOUNT_A = "11111111-1111-1111-1111-111111111111"
ACCOUNT_B = "22222222-2222-2222-2222-222222222222"
OPERATOR = "99999999-9999-9999-9999-999999999999"


class FakeDB:
    """Minimal in-memory feature_requests/feature_request_votes, enough to
    exercise the exact queries routes/feature_board.py issues."""

    def __init__(self):
        self.requests: dict[str, dict] = {}
        self.votes: set[tuple[str, str]] = set()
        self._next_id = 1
        self.operators: set[str] = set()

    def _new_id(self) -> str:
        rid = f"req-{self._next_id}"
        self._next_id += 1
        return rid

    def _vote_count(self, rid: str) -> int:
        return sum(1 for (r, _a) in self.votes if r == rid)

    def _voted_by(self, rid: str, account_id: str) -> bool:
        return (rid, account_id) in self.votes

    def _with_votes(self, row: dict, caller: str) -> dict:
        return {
            **row,
            "vote_count": self._vote_count(row["id"]),
            "voted_by_me": self._voted_by(row["id"], caller),
        }

    async def fetch_all(self, query: str, *args):
        if "FROM feature_requests fr" in query and "GROUP BY fr.id" in query and "WHERE fr.id = $1" not in query:
            status_filter, caller = args
            rows = [
                self._with_votes(r, caller)
                for r in self.requests.values()
                if status_filter is None or r["status"] == status_filter
            ]
            order = {"under_review": 0, "planned": 1, "building": 2, "in_beta": 3, "shipped": 4, "declined": 5}
            rows.sort(key=lambda r: (order.get(r["status"], 6), -r["vote_count"], r["created_at"]))
            return rows[:100]
        raise AssertionError(f"FakeDB.fetch_all: unhandled query: {query}")

    async def fetch_one(self, query: str, *args):
        if "INSERT INTO feature_requests" in query and "RETURNING" in query:
            account_id, title, body, archetype = args
            rid = self._new_id()
            now = datetime.now(timezone.utc)
            row = {
                "id": rid, "account_id": account_id, "title": title, "body": body,
                "channel_archetype": archetype, "status": "under_review",
                "declined_reason": None, "created_at": now, "updated_at": now,
            }
            self.requests[rid] = row
            return dict(row)
        if "SELECT COUNT(*) AS c FROM feature_requests" in query:
            (account_id,) = args
            cnt = sum(1 for r in self.requests.values() if r["account_id"] == account_id)
            return {"c": cnt}
        if "FROM feature_requests fr" in query and "WHERE fr.id = $1" in query and "GROUP BY fr.id" in query:
            rid, caller = args
            row = self.requests.get(rid)
            return self._with_votes(row, caller) if row else None
        if query.strip().startswith("SELECT id FROM feature_requests WHERE id = $1"):
            (rid,) = args
            return {"id": rid} if rid in self.requests else None
        if "FROM accounts a" in query and "is_operator" not in query and "JOIN memberships" in query:
            # account_id_for_tenant (MCP path) — not exercised via TestClient
            # in these route tests, but keep a harmless fallback.
            return None
        raise AssertionError(f"FakeDB.fetch_one: unhandled query: {query}")

    async def execute(self, query: str, *args):
        if "INSERT INTO feature_request_votes" in query:
            rid, account_id = args
            self.votes.add((rid, account_id))
            return
        if "DELETE FROM feature_request_votes" in query:
            rid, account_id = args
            self.votes.discard((rid, account_id))
            return
        if "UPDATE feature_requests" in query:
            rid, status, declined_reason = args
            row = self.requests.get(rid)
            if row:
                row["status"] = status
                row["declined_reason"] = declined_reason
                row["updated_at"] = datetime.now(timezone.utc)
            return
        raise AssertionError(f"FakeDB.execute: unhandled query: {query}")


def _build_client(monkeypatch, db: FakeDB, *, caller_id: str = ACCOUNT_A):
    monkeypatch.setattr(feature_board, "fetch_all", db.fetch_all)
    monkeypatch.setattr(feature_board, "fetch_one", db.fetch_one)
    monkeypatch.setattr(feature_board, "execute", db.execute)

    async def fake_is_operator(account_id: str) -> bool:
        return account_id in db.operators

    monkeypatch.setattr(workspaces, "_is_operator", fake_is_operator)
    monkeypatch.setattr(feature_board, "_is_operator", fake_is_operator)

    app = FastAPI()
    app.include_router(feature_board.router)
    app.dependency_overrides[verify_token] = lambda: AuthUser(id=caller_id, email="x@y.com")
    return TestClient(app)


# =============================================================================
# 1. Create: length caps + rate limit
# =============================================================================

def test_create_feature_request_happy_path(monkeypatch):
    db = FakeDB()
    client = _build_client(monkeypatch, db)
    resp = client.post("/api/feature-board", json={"title": "Per-scene voice casting", "body": "Let me pick a voice per scene."})
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Per-scene voice casting"
    assert data["status"] == "under_review"
    assert data["vote_count"] == 0
    assert data["is_mine"] is True


def test_create_rejects_title_over_120_chars(monkeypatch):
    db = FakeDB()
    client = _build_client(monkeypatch, db)
    resp = client.post("/api/feature-board", json={"title": "x" * 121})
    # Pydantic's Field(max_length=120) rejects the request shape before the
    # route body runs -> FastAPI's standard 422, not the route's own 400s.
    assert resp.status_code == 422
    assert len(db.requests) == 0


def test_create_rejects_body_over_2000_chars(monkeypatch):
    db = FakeDB()
    client = _build_client(monkeypatch, db)
    resp = client.post("/api/feature-board", json={"title": "ok", "body": "y" * 2001})
    assert resp.status_code == 422
    assert len(db.requests) == 0


def test_create_rejects_empty_title(monkeypatch):
    db = FakeDB()
    client = _build_client(monkeypatch, db)
    resp = client.post("/api/feature-board", json={"title": "   "})
    assert resp.status_code == 400


def test_rate_limit_max_5_per_day(monkeypatch):
    db = FakeDB()
    client = _build_client(monkeypatch, db)
    for i in range(5):
        resp = client.post("/api/feature-board", json={"title": f"idea {i}"})
        assert resp.status_code == 200, resp.text
    sixth = client.post("/api/feature-board", json={"title": "one too many"})
    assert sixth.status_code == 429
    assert len(db.requests) == 5


def test_rate_limit_non_vacuity_via_toggled_constant(monkeypatch):
    """Non-vacuity proof: raise the cap the route itself reads and the SAME
    6th call that returns 429 above now succeeds — proving the 429 in the
    test above is actually produced by _MAX_SUBMISSIONS_PER_DAY, not some
    unrelated failure."""
    db = FakeDB()
    client = _build_client(monkeypatch, db)
    monkeypatch.setattr(feature_board, "_MAX_SUBMISSIONS_PER_DAY", 999)
    for i in range(6):
        resp = client.post("/api/feature-board", json={"title": f"idea {i}"})
        assert resp.status_code == 200, resp.text
    assert len(db.requests) == 6


# =============================================================================
# 2. One vote per account per idea; unvote
# =============================================================================

def test_vote_then_double_vote_is_a_no_op(monkeypatch):
    db = FakeDB()
    client = _build_client(monkeypatch, db, caller_id=ACCOUNT_A)
    created = client.post("/api/feature-board", json={"title": "invite a manager"}).json()
    rid = created["id"]

    first = client.post(f"/api/feature-board/{rid}/vote")
    assert first.status_code == 200
    assert first.json()["vote_count"] == 1
    assert first.json()["voted_by_me"] is True

    second = client.post(f"/api/feature-board/{rid}/vote")
    assert second.status_code == 200
    assert second.json()["vote_count"] == 1  # unchanged — idempotent


def test_unvote_removes_the_vote(monkeypatch):
    db = FakeDB()
    client = _build_client(monkeypatch, db, caller_id=ACCOUNT_A)
    created = client.post("/api/feature-board", json={"title": "talking-head format"}).json()
    rid = created["id"]
    client.post(f"/api/feature-board/{rid}/vote")
    resp = client.delete(f"/api/feature-board/{rid}/vote")
    assert resp.status_code == 200
    assert resp.json()["vote_count"] == 0
    assert resp.json()["voted_by_me"] is False


def test_vote_on_unknown_request_404s(monkeypatch):
    db = FakeDB()
    client = _build_client(monkeypatch, db)
    resp = client.post("/api/feature-board/does-not-exist/vote")
    assert resp.status_code == 404


# =============================================================================
# 3. Cross-ACCOUNT visibility (the FIRST cross-tenant surface pin)
# =============================================================================

def test_cross_account_visibility_same_board_both_accounts(monkeypatch):
    db = FakeDB()
    client_a = _build_client(monkeypatch, db, caller_id=ACCOUNT_A)
    created = client_a.post("/api/feature-board", json={"title": "in-chat storyboard review"}).json()
    rid = created["id"]
    client_a.post(f"/api/feature-board/{rid}/vote")

    # A DIFFERENT account, with NO shared tenant/membership concept at all,
    # sees the exact same suggestion — this is the explicit non-isolation pin.
    client_b = _build_client(monkeypatch, db, caller_id=ACCOUNT_B)
    listing_b = client_b.get("/api/feature-board").json()["requests"]
    assert any(r["id"] == rid for r in listing_b)
    seen = next(r for r in listing_b if r["id"] == rid)
    assert seen["account_id"] == ACCOUNT_A  # authored by A
    assert seen["is_mine"] is False  # but B correctly sees it's not B's own
    assert seen["vote_count"] == 1
    assert seen["voted_by_me"] is False  # B hasn't voted

    # B votes too — now A's own view reflects B's vote (still shared state).
    client_b.post(f"/api/feature-board/{rid}/vote")
    listing_a_again = client_a.get("/api/feature-board").json()["requests"]
    seen_again = next(r for r in listing_a_again if r["id"] == rid)
    assert seen_again["vote_count"] == 2
    assert seen_again["voted_by_me"] is True  # A's own vote still counted


def test_status_filter(monkeypatch):
    db = FakeDB()
    client = _build_client(monkeypatch, db)
    client.post("/api/feature-board", json={"title": "a"})
    resp = client.get("/api/feature-board", params={"status": "planned"})
    assert resp.status_code == 200
    assert resp.json()["requests"] == []

    resp_bad = client.get("/api/feature-board", params={"status": "not-a-real-status"})
    assert resp_bad.status_code == 400


# =============================================================================
# 4. Operator-only status change
# =============================================================================

def test_status_change_403_for_non_operator(monkeypatch):
    db = FakeDB()
    client = _build_client(monkeypatch, db, caller_id=ACCOUNT_A)
    created = client.post("/api/feature-board", json={"title": "autopilot access for talking-head channels"}).json()
    rid = created["id"]
    resp = client.patch(f"/api/feature-board/{rid}/status", json={"status": "planned"})
    assert resp.status_code == 403
    assert db.requests[rid]["status"] == "under_review"  # untouched


def test_status_change_200_for_operator(monkeypatch):
    db = FakeDB()
    db.operators.add(OPERATOR)
    client_a = _build_client(monkeypatch, db, caller_id=ACCOUNT_A)
    created = client_a.post("/api/feature-board", json={"title": "per-scene voice casting"}).json()
    rid = created["id"]

    client_op = _build_client(monkeypatch, db, caller_id=OPERATOR)
    resp = client_op.patch(f"/api/feature-board/{rid}/status", json={"status": "planned"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "planned"
    assert db.requests[rid]["status"] == "planned"


def test_status_change_declined_sets_reason(monkeypatch):
    db = FakeDB()
    db.operators.add(OPERATOR)
    client_a = _build_client(monkeypatch, db, caller_id=ACCOUNT_A)
    created = client_a.post("/api/feature-board", json={"title": "x"}).json()
    rid = created["id"]

    client_op = _build_client(monkeypatch, db, caller_id=OPERATOR)
    resp = client_op.patch(
        f"/api/feature-board/{rid}/status",
        json={"status": "declined", "declined_reason": "out of scope"},
    )
    assert resp.status_code == 200
    assert resp.json()["declined_reason"] == "out of scope"


def test_status_change_rejects_bad_value_even_for_operator(monkeypatch):
    db = FakeDB()
    db.operators.add(OPERATOR)
    client_a = _build_client(monkeypatch, db, caller_id=ACCOUNT_A)
    created = client_a.post("/api/feature-board", json={"title": "x"}).json()
    rid = created["id"]

    client_op = _build_client(monkeypatch, db, caller_id=OPERATOR)
    resp = client_op.patch(f"/api/feature-board/{rid}/status", json={"status": "not_a_real_status"})
    assert resp.status_code == 400
    assert db.requests[rid]["status"] == "under_review"


def test_operator_gate_non_vacuity_via_toggled_flag(monkeypatch):
    """Non-vacuity: the SAME account that got 403 above gets 200 once marked
    an operator — proves the 403 is actually produced by the is_operator
    check, not some unrelated auth failure."""
    db = FakeDB()
    client = _build_client(monkeypatch, db, caller_id=ACCOUNT_A)
    created = client.post("/api/feature-board", json={"title": "x"}).json()
    rid = created["id"]
    assert client.patch(f"/api/feature-board/{rid}/status", json={"status": "planned"}).status_code == 403
    db.operators.add(ACCOUNT_A)
    assert client.patch(f"/api/feature-board/{rid}/status", json={"status": "planned"}).status_code == 200


# =============================================================================
# 5. Raw text — no server-side HTML interpretation
# =============================================================================

def test_raw_text_is_returned_verbatim_not_html_escaped(monkeypatch):
    db = FakeDB()
    client = _build_client(monkeypatch, db)
    payload_title = "<b>bold</b> & \"quoted\" 'idea'"
    payload_body = "<script>alert(1)</script>"
    created = client.post("/api/feature-board", json={"title": payload_title, "body": payload_body}).json()
    assert created["title"] == payload_title  # exactly, no &lt;/&amp;/HTML-entity re-encoding
    assert created["body"] == payload_body

    listing = client.get("/api/feature-board").json()["requests"]
    seen = next(r for r in listing if r["id"] == created["id"])
    assert seen["title"] == payload_title
    assert seen["body"] == payload_body
    # And the raw response body text contains the literal payload, not an
    # HTML-entity-encoded version of it (i.e. the server never ran it
    # through an HTML template/renderer before returning JSON).
    raw_get = client.get("/api/feature-board")
    assert payload_body in raw_get.text
    assert "&lt;script&gt;" not in raw_get.text


# =============================================================================
# 6. MCP tools: registered + attributed, dispatch through the SAME route fns
# =============================================================================

def test_mcp_feature_board_tools_registered():
    import routes.mcp as mcp_mod

    for name in ("list_feature_requests", "suggest_feature", "vote_feature_request"):
        assert name in mcp_mod.TOOL_NAMES, f"{name} missing from MCP tool surface"
    # No status-change tool — operator UI action only (checklist's explicit call).
    assert "set_feature_request_status" not in mcp_mod.TOOL_NAMES
    assert "update_feature_request_status" not in mcp_mod.TOOL_NAMES


@pytest.mark.asyncio
async def test_mcp_suggest_feature_calls_the_real_route_attributed(monkeypatch):
    import routes.feature_board as fb
    import routes.mcp as mcp_mod

    db = FakeDB()
    monkeypatch.setattr(fb, "fetch_all", db.fetch_all)
    monkeypatch.setattr(fb, "fetch_one", db.fetch_one)
    monkeypatch.setattr(fb, "execute", db.execute)

    async def fake_account_id_for_tenant(tenant_id):
        return ACCOUNT_A

    monkeypatch.setattr(fb, "account_id_for_tenant", fake_account_id_for_tenant)
    monkeypatch.setattr(mcp_mod, "_log_setup_write", lambda *a, **k: None)

    result = await mcp_mod._call_suggest_feature(
        "tenant-x", {"title": "invite a manager", "channel_archetype": "talking-head explainer"}, caller="agent:test",
    )
    assert result["isError"] is False
    import json as _json
    payload = _json.loads(result["content"][0]["text"])
    assert payload["title"] == "invite a manager"
    assert payload["account_id"] == ACCOUNT_A  # attributed to the resolved account
    assert len(db.requests) == 1
    stored = next(iter(db.requests.values()))
    assert stored["account_id"] == ACCOUNT_A
    assert stored["channel_archetype"] == "talking-head explainer"


@pytest.mark.asyncio
async def test_mcp_vote_feature_request_calls_the_real_route(monkeypatch):
    import routes.feature_board as fb
    import routes.mcp as mcp_mod

    db = FakeDB()
    now = datetime.now(timezone.utc)
    db.requests["req-1"] = {
        "id": "req-1", "account_id": ACCOUNT_B, "title": "x", "body": None,
        "channel_archetype": None, "status": "under_review", "declined_reason": None,
        "created_at": now, "updated_at": now,
    }
    monkeypatch.setattr(fb, "fetch_all", db.fetch_all)
    monkeypatch.setattr(fb, "fetch_one", db.fetch_one)
    monkeypatch.setattr(fb, "execute", db.execute)

    async def fake_account_id_for_tenant(tenant_id):
        return ACCOUNT_A

    monkeypatch.setattr(fb, "account_id_for_tenant", fake_account_id_for_tenant)
    monkeypatch.setattr(mcp_mod, "_log_setup_write", lambda *a, **k: None)

    result = await mcp_mod._call_vote_feature_request("tenant-x", {"request_id": "req-1"}, caller="agent:test")
    assert result["isError"] is False
    assert ("req-1", ACCOUNT_A) in db.votes


@pytest.mark.asyncio
async def test_mcp_list_feature_requests_calls_the_real_route(monkeypatch):
    import routes.feature_board as fb
    import routes.mcp as mcp_mod

    db = FakeDB()
    monkeypatch.setattr(fb, "fetch_all", db.fetch_all)
    monkeypatch.setattr(fb, "fetch_one", db.fetch_one)
    monkeypatch.setattr(fb, "execute", db.execute)

    async def fake_account_id_for_tenant(tenant_id):
        return ACCOUNT_A

    monkeypatch.setattr(fb, "account_id_for_tenant", fake_account_id_for_tenant)

    result = await mcp_mod._call_list_feature_requests("tenant-x", {})
    assert result["isError"] is False


@pytest.mark.asyncio
async def test_mcp_tools_error_gracefully_when_tenant_has_no_account(monkeypatch):
    import routes.feature_board as fb
    import routes.mcp as mcp_mod

    async def fake_account_id_for_tenant(tenant_id):
        return None

    monkeypatch.setattr(fb, "account_id_for_tenant", fake_account_id_for_tenant)
    result = await mcp_mod._call_suggest_feature("tenant-x", {"title": "x"}, caller="agent:test")
    assert result["isError"] is True
