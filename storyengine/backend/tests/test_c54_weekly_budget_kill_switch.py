"""Tests for checklist C54 (P4.2-e) — per-tenant weekly budget ceiling +
kill-switch writers + closing the kill-switch queue-drain gap.

Covers:
  1. autopilot_dial.py: get_weekly_spend (rolling window + ledger sum, NOT
     videos.total_cost), check_weekly_budget (NULL cap always ok,
     exact-boundary breach, ok below cap), trip_kill_switch (idempotent —
     a second trip never overwrites the first reason, and never double-
     notifies), clear_kill_switch.
  2. main.py::_produce_for_tenant — the extracted per-tenant tick: disabled
     tenant short-circuits before any dial read; a tripped kill switch skips
     BOTH the queue drain and the candidate fallback; a budget breach trips
     the switch and skips both paths too; budget-ok lets the queue drain run
     first, falling back to the candidate path only when the queue has
     nothing.
  3. routes/autopilot.py: POST /config validates dial_level/weekly_budget_cap
     and round-trips the real written dial state (not the model defaults);
     POST /kill-switch/reset clears the switch and attributes who cleared it.
  4. routes/mcp.py: set_autopilot_dial / reset_autopilot_kill_switch are
     registered, carry no confirm_token, and dispatch through the SAME
     routes.autopilot.update_config / reset_kill_switch functions the HTTP
     doors use.

No live DB: fetch_one/execute are monkeypatched at module scope, same
convention as tests/test_autopilot_dial.py and tests/test_c51_candidate_
auto_launch.py.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/test_c54_weekly_budget_kill_switch.py -q
"""
from __future__ import annotations

import asyncio
import os

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import autopilot_dial as ad
import main as main_mod
import routes.autopilot as autopilot_route
import routes.mcp as mcp_mod
from auth import AuthUser, get_tenant_id, verify_token
from autopilot_dial import AutopilotDial

TENANT = "tenant-c54"


# =============================================================================
# 1. autopilot_dial.py
# =============================================================================

def test_rows_affected_parses_command_tags():
    assert ad._rows_affected("INSERT 0 1") == 1
    assert ad._rows_affected("INSERT 0 0") == 0
    assert ad._rows_affected("UPDATE 1") == 1
    assert ad._rows_affected("UPDATE 0") == 0
    assert ad._rows_affected(None) == 0
    assert ad._rows_affected("") == 0


def test_get_weekly_spend_rolls_window_then_sums_the_ledger_not_total_cost(monkeypatch):
    """Must sum generation_ledger.actual_cost — never videos.total_cost (a
    cumulative lifetime rollup with no 'since when' axis, see the module
    docstring)."""
    execute_calls = []

    async def fake_execute(query, *args):
        execute_calls.append((query, args))
        return "INSERT 0 1"

    async def fake_fetch_one(query, *args):
        assert "generation_ledger" in query
        assert "total_cost" not in query
        return {"spent": 12.34}

    monkeypatch.setattr(ad, "execute", fake_execute)
    monkeypatch.setattr(ad, "fetch_one", fake_fetch_one)

    spent = asyncio.run(ad.get_weekly_spend(TENANT))
    assert spent == 12.34
    # the rolling-window upsert ran before the sum query
    assert len(execute_calls) == 1
    assert "weekly_spend_reset_at" in execute_calls[0][0]
    assert "ON CONFLICT" in execute_calls[0][0]


def test_ensure_reset_window_upsert_has_the_atomic_where_guard(monkeypatch):
    captured = {}

    async def fake_execute(query, *args):
        captured["query"] = query
        captured["args"] = args
        return "INSERT 0 1"

    monkeypatch.setattr(ad, "execute", fake_execute)
    asyncio.run(ad._ensure_reset_window(TENANT))
    q = captured["query"]
    assert "ON CONFLICT (tenant_id) DO UPDATE" in q
    assert "IS NULL" in q
    assert "interval '7 days'" in q
    assert captured["args"] == (TENANT,)


def test_check_weekly_budget_no_cap_is_always_ok(monkeypatch):
    async def fake_get_dial(tenant_id):
        return AutopilotDial(weekly_budget_cap=None)

    async def fake_get_spend(tenant_id):
        return 999999.0

    monkeypatch.setattr(ad, "get_autopilot_dial", fake_get_dial)
    monkeypatch.setattr(ad, "get_weekly_spend", fake_get_spend)

    ok, spent, cap = asyncio.run(ad.check_weekly_budget(TENANT))
    assert ok is True
    assert cap is None
    assert spent == 999999.0


def test_check_weekly_budget_below_cap_is_ok(monkeypatch):
    async def fake_get_dial(tenant_id):
        return AutopilotDial(weekly_budget_cap=100.0)

    async def fake_get_spend(tenant_id):
        return 50.0

    monkeypatch.setattr(ad, "get_autopilot_dial", fake_get_dial)
    monkeypatch.setattr(ad, "get_weekly_spend", fake_get_spend)

    ok, spent, cap = asyncio.run(ad.check_weekly_budget(TENANT))
    assert ok is True
    assert spent == 50.0
    assert cap == 100.0


def test_check_weekly_budget_exact_boundary_is_a_breach(monkeypatch):
    """spent == cap must breach (>=), not just spent > cap — reaching the
    cap trips it."""
    async def fake_get_dial(tenant_id):
        return AutopilotDial(weekly_budget_cap=100.0)

    async def fake_get_spend(tenant_id):
        return 100.0

    monkeypatch.setattr(ad, "get_autopilot_dial", fake_get_dial)
    monkeypatch.setattr(ad, "get_weekly_spend", fake_get_spend)

    ok, spent, cap = asyncio.run(ad.check_weekly_budget(TENANT))
    assert ok is False
    assert spent == cap == 100.0


def test_check_weekly_budget_above_cap_is_a_breach(monkeypatch):
    async def fake_get_dial(tenant_id):
        return AutopilotDial(weekly_budget_cap=100.0)

    async def fake_get_spend(tenant_id):
        return 150.0

    monkeypatch.setattr(ad, "get_autopilot_dial", fake_get_dial)
    monkeypatch.setattr(ad, "get_weekly_spend", fake_get_spend)

    ok, spent, cap = asyncio.run(ad.check_weekly_budget(TENANT))
    assert ok is False


# ---------------------------------------------------------------------------
# C54b (orchestrator hardening pass): validate_dial_change — the ONE shared
# "no autonomy without a ceiling" invariant both writers call.
# ---------------------------------------------------------------------------

def test_validate_dial_change_raise_with_no_cap_anywhere_is_rejected():
    current = AutopilotDial(dial_level="propose_only", weekly_budget_cap=None)
    err = ad.validate_dial_change(current, new_dial_level="auto_draft", cap_provided=False, new_cap=None)
    assert err is not None
    assert "weekly_budget_cap" in err


def test_validate_dial_change_raise_with_cap_supplied_in_same_call_is_ok():
    current = AutopilotDial(dial_level="propose_only", weekly_budget_cap=None)
    err = ad.validate_dial_change(current, new_dial_level="auto_draft", cap_provided=True, new_cap=50.0)
    assert err is None


def test_validate_dial_change_raise_with_cap_already_on_row_is_ok():
    current = AutopilotDial(dial_level="propose_only", weekly_budget_cap=25.0)
    err = ad.validate_dial_change(current, new_dial_level="auto_draft", cap_provided=False, new_cap=None)
    assert err is None


def test_validate_dial_change_clearing_cap_while_elevated_is_rejected():
    current = AutopilotDial(dial_level="auto_draft", weekly_budget_cap=100.0)
    err = ad.validate_dial_change(current, new_dial_level=None, cap_provided=True, new_cap=None)
    assert err is not None


def test_validate_dial_change_clearing_cap_with_simultaneous_lower_is_ok():
    current = AutopilotDial(dial_level="auto_draft", weekly_budget_cap=100.0)
    err = ad.validate_dial_change(
        current, new_dial_level="propose_only", cap_provided=True, new_cap=None,
    )
    assert err is None


def test_validate_dial_change_no_op_change_when_already_elevated_and_capped():
    """Touching an unrelated field (neither dial_level nor cap) on an
    already-valid elevated+capped row must stay a no-op pass-through."""
    current = AutopilotDial(dial_level="auto_draft", weekly_budget_cap=100.0)
    err = ad.validate_dial_change(current, new_dial_level=None, cap_provided=False, new_cap=None)
    assert err is None


def test_validate_dial_change_full_auto_also_requires_a_cap():
    current = AutopilotDial(dial_level="propose_only", weekly_budget_cap=None)
    err = ad.validate_dial_change(current, new_dial_level="full_auto", cap_provided=False, new_cap=None)
    assert err is not None


def test_trip_kill_switch_first_call_trips_and_notifies(monkeypatch):
    execute_calls = []

    async def fake_execute(query, *args):
        execute_calls.append((query, args))
        if "kill_switch_tripped_at" in query and "generation_ledger" not in query and "bot_activity" not in query:
            return "INSERT 0 1"
        return "INSERT 0 1"

    monkeypatch.setattr(ad, "execute", fake_execute)
    tripped = asyncio.run(ad.trip_kill_switch(TENANT, "over budget"))
    assert tripped is True
    # one UPSERT for the trip + one INSERT for the bot_activity notify
    assert len(execute_calls) == 2
    assert "bot_activity" in execute_calls[1][0]
    assert any("over budget" in str(a) for a in execute_calls[1][1])


def test_trip_kill_switch_second_call_is_a_noop_no_duplicate_notify(monkeypatch):
    """A second trip (e.g. the loop-level check and autopilot_launch's own
    defense-in-depth check both firing in the same tick) must not overwrite
    the FIRST recorded reason, and must not send a second notify."""
    execute_calls = []

    async def fake_execute(query, *args):
        execute_calls.append((query, args))
        if "kill_switch_tripped_at" in query and "bot_activity" not in query:
            return "INSERT 0 0"  # WHERE guard failed — already tripped
        return "INSERT 0 1"

    monkeypatch.setattr(ad, "execute", fake_execute)
    tripped = asyncio.run(ad.trip_kill_switch(TENANT, "second reason"))
    assert tripped is False
    # only the upsert attempt ran — no bot_activity notify for a no-op trip
    assert len(execute_calls) == 1


def test_clear_kill_switch_writes_both_columns_null(monkeypatch):
    captured = {}

    async def fake_execute(query, *args):
        captured["query"] = query
        captured["args"] = args
        return "INSERT 0 1"

    monkeypatch.setattr(ad, "execute", fake_execute)
    asyncio.run(ad.clear_kill_switch(TENANT))
    assert "kill_switch_tripped_at = NULL" in captured["query"]
    assert "kill_switch_reason = NULL" in captured["query"]
    assert captured["args"] == (TENANT,)


# =============================================================================
# 2. main.py::_produce_for_tenant
# =============================================================================

def _patch_enabled(monkeypatch, enabled=True):
    async def fake(tenant_id):
        return enabled
    monkeypatch.setattr(main_mod, "_is_autopilot_enabled", fake)


def _patch_dial(monkeypatch, dial):
    async def fake(tenant_id):
        return dial
    monkeypatch.setattr(ad, "get_autopilot_dial", fake)


def _patch_budget(monkeypatch, *, ok=True, spent=0.0, cap=None):
    async def fake(tenant_id):
        return ok, spent, cap
    monkeypatch.setattr(ad, "check_weekly_budget", fake)


def _patch_trip(monkeypatch):
    calls = []

    async def fake(tenant_id, reason):
        calls.append((tenant_id, reason))
        return True
    monkeypatch.setattr(ad, "trip_kill_switch", fake)
    return calls


def _patch_queue_and_candidate(monkeypatch, *, queue_result=None, candidate_result=None):
    import autopilot_launch
    import routes.queue as queue_mod

    queue_calls = []
    candidate_calls = []

    async def fake_auto_produce_next(tenant_id):
        queue_calls.append(tenant_id)
        return queue_result

    async def fake_auto_launch_best_candidate(tenant_id):
        candidate_calls.append(tenant_id)
        return candidate_result

    monkeypatch.setattr(queue_mod, "auto_produce_next", fake_auto_produce_next)
    monkeypatch.setattr(autopilot_launch, "auto_launch_best_candidate", fake_auto_launch_best_candidate)
    return queue_calls, candidate_calls


def test_produce_for_tenant_disabled_short_circuits_before_dial_read(monkeypatch):
    _patch_enabled(monkeypatch, enabled=False)

    async def fake_dial(tenant_id):
        raise AssertionError("dial must not be read for a disabled tenant")
    monkeypatch.setattr(ad, "get_autopilot_dial", fake_dial)

    result = asyncio.run(main_mod._produce_for_tenant(TENANT))
    assert result is None


def test_produce_for_tenant_kill_switch_tripped_skips_queue_and_candidate(monkeypatch):
    """The C51-found gap this chunk closes: a tripped kill switch must skip
    the QUEUE DRAIN too, not just the candidate fallback."""
    import datetime as dt
    _patch_enabled(monkeypatch, enabled=True)
    _patch_dial(monkeypatch, AutopilotDial(kill_switch_tripped_at=dt.datetime.now(dt.timezone.utc)))
    queue_calls, candidate_calls = _patch_queue_and_candidate(monkeypatch)

    result = asyncio.run(main_mod._produce_for_tenant(TENANT))
    assert result is None
    assert queue_calls == []
    assert candidate_calls == []


def test_produce_for_tenant_budget_breach_trips_and_skips_both_paths(monkeypatch):
    _patch_enabled(monkeypatch, enabled=True)
    _patch_dial(monkeypatch, AutopilotDial())
    _patch_budget(monkeypatch, ok=False, spent=120.0, cap=100.0)
    trip_calls = _patch_trip(monkeypatch)
    queue_calls, candidate_calls = _patch_queue_and_candidate(monkeypatch)

    result = asyncio.run(main_mod._produce_for_tenant(TENANT))
    assert result is None
    assert queue_calls == []
    assert candidate_calls == []
    assert len(trip_calls) == 1
    assert trip_calls[0][0] == TENANT
    assert "100.00" in trip_calls[0][1] and "120.00" in trip_calls[0][1]


def test_produce_for_tenant_budget_ok_queue_drain_wins_candidate_not_tried(monkeypatch):
    _patch_enabled(monkeypatch, enabled=True)
    _patch_dial(monkeypatch, AutopilotDial())
    _patch_budget(monkeypatch, ok=True)
    queue_calls, candidate_calls = _patch_queue_and_candidate(
        monkeypatch, queue_result={"video_id": "v1", "video_title": "t1"},
    )

    result = asyncio.run(main_mod._produce_for_tenant(TENANT))
    assert result == {"video_id": "v1", "video_title": "t1"}
    assert queue_calls == [TENANT]
    assert candidate_calls == []


def test_produce_for_tenant_budget_ok_queue_empty_falls_back_to_candidate(monkeypatch):
    _patch_enabled(monkeypatch, enabled=True)
    _patch_dial(monkeypatch, AutopilotDial())
    _patch_budget(monkeypatch, ok=True)
    queue_calls, candidate_calls = _patch_queue_and_candidate(
        monkeypatch, queue_result=None, candidate_result={"status": "proposed", "candidate_id": "c1"},
    )

    result = asyncio.run(main_mod._produce_for_tenant(TENANT))
    assert result == {"status": "proposed", "candidate_id": "c1"}
    assert queue_calls == [TENANT]
    assert candidate_calls == [TENANT]


def test_produce_for_tenant_logs_warning_for_elevated_dial_with_no_cap(monkeypatch, caplog):
    """C54b (orchestrator hardening pass): the loop-level belt-and-
    suspenders is a LOG ONLY at this site — neither the queue drain nor the
    candidate-call decision here branches on dial_level itself (autopilot_
    launch.py does its own demotion internally) — so this just proves the
    warning fires and the tick still proceeds normally."""
    import logging

    _patch_enabled(monkeypatch, enabled=True)
    _patch_dial(monkeypatch, AutopilotDial(dial_level="auto_draft", weekly_budget_cap=None))
    _patch_budget(monkeypatch, ok=True)
    queue_calls, candidate_calls = _patch_queue_and_candidate(
        monkeypatch, queue_result={"video_id": "v1", "video_title": "t1"},
    )

    with caplog.at_level(logging.WARNING, logger="storyengine"):
        result = asyncio.run(main_mod._produce_for_tenant(TENANT))

    assert result == {"video_id": "v1", "video_title": "t1"}
    assert queue_calls == [TENANT]
    assert any("config anomaly" in r.message for r in caplog.records)


# =============================================================================
# 3. routes/autopilot.py — config route validation + kill-switch reset route
# =============================================================================

def _empty_fetch_one_factory(config_row=None):
    async def fake(query, *args):
        if "FROM autopilot_config" in query:
            return config_row
        return None
    return fake


def _build_client(monkeypatch, *, config_row=None, dial=None, weekly_spent=0.0):
    execute_calls = []

    async def fake_execute(query, *args):
        execute_calls.append((query, args))
        return "INSERT 0 1"

    monkeypatch.setattr(autopilot_route, "fetch_one", _empty_fetch_one_factory(config_row))
    monkeypatch.setattr(autopilot_route, "execute", fake_execute)

    async def fake_get_dial(tenant_id):
        return dial if dial is not None else AutopilotDial()
    monkeypatch.setattr(autopilot_route, "get_autopilot_dial", fake_get_dial)

    async def fake_get_weekly_spend(tenant_id):
        return weekly_spent
    monkeypatch.setattr(autopilot_route, "get_weekly_spend", fake_get_weekly_spend)

    app = FastAPI()
    app.include_router(autopilot_route.router)
    app.dependency_overrides[get_tenant_id] = lambda: TENANT
    app.dependency_overrides[verify_token] = lambda: AuthUser(id="user-1", email="ryan@example.com")
    return TestClient(app), execute_calls


def test_config_route_rejects_bad_dial_level(monkeypatch):
    client, _ = _build_client(monkeypatch)
    resp = client.post("/api/autopilot/config", json={"dial_level": "yolo_mode"})
    assert resp.status_code == 400


def test_config_route_rejects_non_positive_budget_cap(monkeypatch):
    client, _ = _build_client(monkeypatch)
    resp = client.post("/api/autopilot/config", json={"weekly_budget_cap": 0})
    assert resp.status_code == 400
    resp = client.post("/api/autopilot/config", json={"weekly_budget_cap": -5})
    assert resp.status_code == 400


def test_config_route_accepts_valid_dial_level_and_cap_and_writes_them(monkeypatch):
    client, execute_calls = _build_client(
        monkeypatch, dial=AutopilotDial(dial_level="auto_draft", weekly_budget_cap=50.0), weekly_spent=12.5,
    )
    resp = client.post("/api/autopilot/config", json={"dial_level": "auto_draft", "weekly_budget_cap": 50.0})
    assert resp.status_code == 200
    config = resp.json()["config"]
    # the response reflects the ACTUAL written dial state (via get_autopilot_dial),
    # not the model's hardcoded defaults
    assert config["dial_level"] == "auto_draft"
    assert config["weekly_budget_cap"] == 50.0
    assert config["weekly_spent"] == 12.5
    # an INSERT/UPDATE actually referencing dial_level/weekly_budget_cap ran
    assert any("dial_level" in q for q, _ in execute_calls)


def test_config_route_null_cap_is_accepted_as_a_clear(monkeypatch):
    client, execute_calls = _build_client(monkeypatch, dial=AutopilotDial(weekly_budget_cap=None))
    resp = client.post("/api/autopilot/config", json={"weekly_budget_cap": None})
    assert resp.status_code == 200
    assert any("weekly_budget_cap" in q for q, _ in execute_calls)


# ---------------------------------------------------------------------------
# C54b (orchestrator hardening pass): the config route enforces the "no
# autonomy without a ceiling" invariant against the CURRENT row state.
# ---------------------------------------------------------------------------

def test_config_route_rejects_raising_dial_with_no_cap_anywhere(monkeypatch):
    client, execute_calls = _build_client(
        monkeypatch, dial=AutopilotDial(dial_level="propose_only", weekly_budget_cap=None),
    )
    resp = client.post("/api/autopilot/config", json={"dial_level": "auto_draft"})
    assert resp.status_code == 400
    assert "weekly_budget_cap" in resp.json()["detail"]
    assert not any("dial_level" in q for q, _ in execute_calls)


def test_config_route_allows_raising_dial_with_cap_in_same_request(monkeypatch):
    client, _execute_calls = _build_client(
        monkeypatch, dial=AutopilotDial(dial_level="propose_only", weekly_budget_cap=None),
    )
    resp = client.post("/api/autopilot/config", json={"dial_level": "auto_draft", "weekly_budget_cap": 50})
    assert resp.status_code == 200


def test_config_route_allows_raising_dial_when_cap_already_on_row(monkeypatch):
    client, _execute_calls = _build_client(
        monkeypatch, dial=AutopilotDial(dial_level="propose_only", weekly_budget_cap=25.0),
    )
    resp = client.post("/api/autopilot/config", json={"dial_level": "auto_draft"})
    assert resp.status_code == 200


def test_config_route_rejects_clearing_cap_while_dial_stays_elevated(monkeypatch):
    client, execute_calls = _build_client(
        monkeypatch, dial=AutopilotDial(dial_level="auto_draft", weekly_budget_cap=100.0),
    )
    resp = client.post("/api/autopilot/config", json={"weekly_budget_cap": None})
    assert resp.status_code == 400
    assert not any("weekly_budget_cap" in q for q, _ in execute_calls)


def test_config_route_allows_clearing_cap_with_simultaneous_lower_to_propose_only(monkeypatch):
    client, execute_calls = _build_client(
        monkeypatch, dial=AutopilotDial(dial_level="auto_draft", weekly_budget_cap=100.0),
    )
    resp = client.post("/api/autopilot/config", json={"dial_level": "propose_only", "weekly_budget_cap": None})
    assert resp.status_code == 200
    assert any("weekly_budget_cap" in q for q, _ in execute_calls)


def _build_kill_switch_reset_client(monkeypatch, *, prior_dial=None):
    clear_calls = []

    async def fake_clear(tenant_id):
        clear_calls.append(tenant_id)

    async def fake_get_dial(tenant_id):
        return prior_dial if prior_dial is not None else AutopilotDial()

    monkeypatch.setattr(autopilot_route, "clear_kill_switch", fake_clear)
    monkeypatch.setattr(autopilot_route, "get_autopilot_dial", fake_get_dial)
    execute_calls = []

    async def fake_execute(query, *args):
        execute_calls.append((query, args))
        return "INSERT 0 1"
    monkeypatch.setattr(autopilot_route, "execute", fake_execute)

    app = FastAPI()
    app.include_router(autopilot_route.router)
    app.dependency_overrides[verify_token] = lambda: AuthUser(id="user-1", email="ryan@example.com")
    app.dependency_overrides[get_tenant_id] = lambda: TENANT
    return TestClient(app), clear_calls, execute_calls


def test_kill_switch_reset_route_clears_and_attributes(monkeypatch):
    import datetime as dt

    prior = AutopilotDial(
        kill_switch_tripped_at=dt.datetime(2026, 7, 19, 12, 0, 0, tzinfo=dt.timezone.utc),
        kill_switch_reason="Weekly budget cap $10.00 reached (spent $12.00)",
    )
    client, clear_calls, execute_calls = _build_kill_switch_reset_client(monkeypatch, prior_dial=prior)

    resp = client.post("/api/autopilot/kill-switch/reset")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["kill_switch_tripped_at"] is None
    assert body["cleared_by"] == "ryan@example.com"
    # C54b: the response must surface the reason/when of the trip it just
    # cleared, not just report "ok" — this is what forces an agent to
    # surface what went wrong rather than silently waving it away.
    assert body["previous_kill_switch_reason"] == "Weekly budget cap $10.00 reached (spent $12.00)"
    assert body["previous_kill_switch_tripped_at"] is not None
    assert clear_calls == [TENANT]
    assert len(execute_calls) == 1
    assert "bot_activity" in execute_calls[0][0]
    assert any("ryan@example.com" in str(a) for a in execute_calls[0][1])
    assert any("Weekly budget cap $10.00" in str(a) for a in execute_calls[0][1])


def test_kill_switch_reset_route_no_prior_trip_is_a_harmless_noop(monkeypatch):
    client, clear_calls, _execute_calls = _build_kill_switch_reset_client(monkeypatch, prior_dial=AutopilotDial())

    resp = client.post("/api/autopilot/kill-switch/reset")
    assert resp.status_code == 200
    body = resp.json()
    assert body["previous_kill_switch_reason"] is None
    assert body["previous_kill_switch_tripped_at"] is None
    assert clear_calls == [TENANT]


# =============================================================================
# 4. routes/mcp.py — set_autopilot_dial / reset_autopilot_kill_switch
# =============================================================================

def test_new_dial_tools_are_registered():
    names = mcp_mod.TOOL_NAMES
    assert "set_autopilot_dial" in names
    assert "reset_autopilot_kill_switch" in names


def test_new_dial_tools_carry_no_confirm_token():
    for tool in mcp_mod._AUTOPILOT_DIAL_TOOLS:
        props = tool["inputSchema"].get("properties", {})
        assert "confirm_token" not in props, f"{tool['name']} must be free (no confirm_token)"


async def test_set_autopilot_dial_tool_calls_update_config_with_dial_level():
    import unittest.mock as _um

    update_mock = _um.AsyncMock(return_value={"status": "ok", "config": {"dial_level": "auto_draft"}})
    with _um.patch.object(autopilot_route, "update_config", update_mock):
        result = await mcp_mod._call_set_autopilot_dial(TENANT, {"dial_level": "auto_draft"}, "agent")
    update_mock.assert_awaited_once()
    args, kwargs = update_mock.call_args
    assert args[0].dial_level == "auto_draft"
    assert args[0].weekly_budget_cap is None
    assert kwargs["tenant_id"] == TENANT
    assert result["isError"] is False


async def test_set_autopilot_dial_tool_calls_update_config_with_null_cap_to_clear():
    import unittest.mock as _um

    update_mock = _um.AsyncMock(return_value={"status": "ok", "config": {}})
    with _um.patch.object(autopilot_route, "update_config", update_mock):
        result = await mcp_mod._call_set_autopilot_dial(TENANT, {"weekly_budget_cap": None}, "agent")
    update_mock.assert_awaited_once()
    args, _kwargs = update_mock.call_args
    assert "weekly_budget_cap" in args[0].model_fields_set
    assert args[0].weekly_budget_cap is None
    assert result["isError"] is False


async def test_set_autopilot_dial_tool_rejects_bad_dial_level_without_calling_update_config():
    import unittest.mock as _um

    update_mock = _um.AsyncMock(side_effect=AssertionError("must not be called"))
    with _um.patch.object(autopilot_route, "update_config", update_mock):
        result = await mcp_mod._call_set_autopilot_dial(TENANT, {"dial_level": "nonsense"}, "agent")
    assert result["isError"] is True
    update_mock.assert_not_awaited()


async def test_set_autopilot_dial_tool_rejects_non_positive_cap():
    import unittest.mock as _um

    update_mock = _um.AsyncMock(side_effect=AssertionError("must not be called"))
    with _um.patch.object(autopilot_route, "update_config", update_mock):
        result = await mcp_mod._call_set_autopilot_dial(TENANT, {"weekly_budget_cap": 0}, "agent")
    assert result["isError"] is True
    update_mock.assert_not_awaited()


async def test_set_autopilot_dial_tool_requires_at_least_one_field():
    result = await mcp_mod._call_set_autopilot_dial(TENANT, {}, "agent")
    assert result["isError"] is True


# ---------------------------------------------------------------------------
# C54b (orchestrator hardening pass): set_autopilot_dial dispatches through
# the REAL routes.autopilot.update_config (NOT mocked here, unlike the
# tests above) so these prove the invariant is enforced end-to-end through
# the MCP door too — not just that the HTTP door validates it. Same
# monkeypatch-the-DB convention as _build_client, applied directly against
# autopilot_route without going through TestClient.
# ---------------------------------------------------------------------------

def _patch_autopilot_route_db(monkeypatch, *, dial=None, weekly_spent=0.0):
    execute_calls = []

    async def fake_execute(query, *args):
        execute_calls.append((query, args))
        return "INSERT 0 1"

    async def fake_fetch_one(query, *args):
        return None  # no existing row -> insert branch

    async def fake_get_dial(tenant_id):
        return dial if dial is not None else AutopilotDial()

    async def fake_get_weekly_spend(tenant_id):
        return weekly_spent

    monkeypatch.setattr(autopilot_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(autopilot_route, "execute", fake_execute)
    monkeypatch.setattr(autopilot_route, "get_autopilot_dial", fake_get_dial)
    monkeypatch.setattr(autopilot_route, "get_weekly_spend", fake_get_weekly_spend)
    return execute_calls


async def test_set_autopilot_dial_tool_rejects_raise_with_no_cap_end_to_end(monkeypatch):
    execute_calls = _patch_autopilot_route_db(
        monkeypatch, dial=AutopilotDial(dial_level="propose_only", weekly_budget_cap=None),
    )
    result = await mcp_mod._call_set_autopilot_dial(TENANT, {"dial_level": "auto_draft"}, "agent")
    assert result["isError"] is True
    assert "weekly_budget_cap" in result["content"][0]["text"]
    assert not any("dial_level" in q for q, _ in execute_calls)


async def test_set_autopilot_dial_tool_allows_raise_with_cap_end_to_end(monkeypatch):
    _patch_autopilot_route_db(monkeypatch, dial=AutopilotDial(dial_level="propose_only", weekly_budget_cap=None))
    result = await mcp_mod._call_set_autopilot_dial(
        TENANT, {"dial_level": "auto_draft", "weekly_budget_cap": 50}, "agent",
    )
    assert result["isError"] is False


async def test_set_autopilot_dial_tool_rejects_clearing_cap_while_elevated_end_to_end(monkeypatch):
    _patch_autopilot_route_db(monkeypatch, dial=AutopilotDial(dial_level="auto_draft", weekly_budget_cap=100.0))
    result = await mcp_mod._call_set_autopilot_dial(TENANT, {"weekly_budget_cap": None}, "agent")
    assert result["isError"] is True


async def test_set_autopilot_dial_tool_allows_clearing_cap_with_simultaneous_lower_end_to_end(monkeypatch):
    _patch_autopilot_route_db(monkeypatch, dial=AutopilotDial(dial_level="auto_draft", weekly_budget_cap=100.0))
    result = await mcp_mod._call_set_autopilot_dial(
        TENANT, {"dial_level": "propose_only", "weekly_budget_cap": None}, "agent",
    )
    assert result["isError"] is False


async def test_reset_autopilot_kill_switch_tool_calls_route_with_attribution():
    import unittest.mock as _um

    reset_mock = _um.AsyncMock(
        return_value=autopilot_route.KillSwitchResetResult(
            status="ok", kill_switch_tripped_at=None, kill_switch_reason=None, cleared_by="agent:Claude Desktop",
        )
    )
    with _um.patch.object(autopilot_route, "reset_kill_switch", reset_mock):
        result = await mcp_mod._call_reset_autopilot_kill_switch(TENANT, {}, "agent:Claude Desktop")
    reset_mock.assert_awaited_once()
    _args, kwargs = reset_mock.call_args
    assert kwargs["tenant_id"] == TENANT
    assert kwargs["user"].email == "agent:Claude Desktop"
    assert result["isError"] is False


def test_dispatch_routes_both_dial_tool_names():
    import unittest.mock as _um

    async def _run():
        update_mock = _um.AsyncMock(return_value={"status": "ok", "config": {}})
        with _um.patch.object(autopilot_route, "update_config", update_mock):
            await mcp_mod._dispatch(
                "tools/call", {"name": "set_autopilot_dial", "arguments": {"dial_level": "auto_draft"}}, TENANT,
            )
        update_mock.assert_awaited_once()

        reset_mock = _um.AsyncMock(
            return_value=autopilot_route.KillSwitchResetResult(
                status="ok", kill_switch_tripped_at=None, kill_switch_reason=None, cleared_by="agent",
            )
        )
        with _um.patch.object(autopilot_route, "reset_kill_switch", reset_mock):
            await mcp_mod._dispatch(
                "tools/call", {"name": "reset_autopilot_kill_switch", "arguments": {}}, TENANT,
            )
        reset_mock.assert_awaited_once()

    asyncio.run(_run())
