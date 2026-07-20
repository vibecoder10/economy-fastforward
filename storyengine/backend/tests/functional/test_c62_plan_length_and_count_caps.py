"""Behavioral (non-AST) tests for C62 — wiring the ratified 2026-07-20
pricing decision (tasks/decisions.md "PRICING RATIFIED") into the real
plan-limits numbers and a new length cap.

Locked: Starter = max video LENGTH 10 minutes + max 12 video generations/
month. Pro + Agency = unlimited video generation quantity + unlimited
uploads. MCP = Pro + Agency (covered separately in
test_c57_mcp_billing_gate.py, which already has the tier-gate tests for
create_token/get_agent_tenant_id).

test_plan_limits_enforcement_lock.py already pins (via AST/regex) that every
create-entry point still CALLS check_plan_limits(..., "video") — it does not
exercise the actual numbers. This file is the numeric/behavioral
counterpart: real (monkeypatched) DB rows, real calls into
routes.billing.check_plan_limits / enforce_video_length_cap, asserting the
12-video/10-minute Starter caps and the Pro/Agency "unlimited" sentinel.

No live DB — routes.billing's own fetch_one/execute (imported from
`database` at module scope) are monkeypatched directly, same convention as
test_c57_mcp_billing_gate.py's `_patch_billing_fetch_one`.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c62_plan_length_and_count_caps.py -q
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi import HTTPException

import routes.billing as billing


def _run(coro):
    return asyncio.run(coro)


def _patch_db(monkeypatch, *, plan: str, videos_created: int = 0, render_minutes: float = 0):
    """Fakes the two queries check_plan_limits/enforce_video_length_cap need:
    the membership->account plan lookup (_get_tenant_plan) and the current
    month's usage row (_get_or_create_usage). No trial_ends_at override —
    plan is used as given, matching a real paying (or free) tenant."""
    async def _fetch_one(query, *args):
        if "FROM accounts a" in query and "JOIN memberships m" in query:
            return {"plan": plan, "trial_ends_at": None}
        if "FROM tenant_usage" in query:
            return {"videos_created": videos_created, "render_minutes": render_minutes,
                     "api_calls": 0, "storage_bytes": 0}
        raise AssertionError(f"unexpected query: {query!r}")

    async def _execute(query, *args):
        return "OK"

    monkeypatch.setattr(billing, "fetch_one", _fetch_one)
    monkeypatch.setattr(billing, "execute", _execute)


# =============================================================================
# check_plan_limits — the per-month COUNT cap
# =============================================================================

def test_starter_12th_video_allowed(monkeypatch):
    """11 used so far -> the 12th create (usage still 11 at check time,
    since increment_usage runs AFTER a successful create) must be allowed."""
    _patch_db(monkeypatch, plan="starter", videos_created=11)
    _run(billing.check_plan_limits(uuid.uuid4(), "video"))  # must not raise
    print("✅ test_starter_12th_video_allowed")


def test_starter_13th_video_rejected(monkeypatch):
    """12 already used -> the 13th create is over the Starter cap."""
    _patch_db(monkeypatch, plan="starter", videos_created=12)
    with pytest.raises(HTTPException) as exc:
        _run(billing.check_plan_limits(uuid.uuid4(), "video"))
    assert exc.value.status_code == 402
    assert exc.value.detail["limit"] == 12
    print("✅ test_starter_13th_video_rejected")


def test_pro_and_agency_video_count_unlimited(monkeypatch):
    """Pro/Agency: even a very high monthly count must not trip the cap —
    the ratified 'unlimited video generation quantity' promise."""
    for plan in ("pro", "agency"):
        _patch_db(monkeypatch, plan=plan, videos_created=10_000)
        _run(billing.check_plan_limits(uuid.uuid4(), "video"))  # must not raise
    print("✅ test_pro_and_agency_video_count_unlimited")


def test_plan_limits_map_values():
    """Pin the exact numbers this chunk changed/preserved, so a future edit
    that silently reintroduces a pro/agency count cap (or drifts the
    Starter number away from 12) fails loudly here rather than only in
    production."""
    assert billing.PLAN_LIMITS["starter"]["videos_per_month"] == 12
    assert billing.PLAN_LIMITS["pro"]["videos_per_month"] >= 1_000_000
    assert billing.PLAN_LIMITS["agency"]["videos_per_month"] >= 1_000_000
    print("✅ test_plan_limits_map_values")


# =============================================================================
# enforce_video_length_cap — the per-video LENGTH cap (Starter only)
# =============================================================================

def test_starter_10_minute_video_allowed(monkeypatch):
    _patch_db(monkeypatch, plan="starter")
    _run(billing.enforce_video_length_cap(uuid.uuid4(), 10))  # must not raise
    print("✅ test_starter_10_minute_video_allowed")


def test_starter_11_minute_video_rejected(monkeypatch):
    _patch_db(monkeypatch, plan="starter")
    with pytest.raises(HTTPException) as exc:
        _run(billing.enforce_video_length_cap(uuid.uuid4(), 11))
    assert exc.value.status_code == 402
    assert "10" in exc.value.detail["message"]
    assert "upgrade" in exc.value.detail["message"].lower()
    print("✅ test_starter_11_minute_video_rejected")


def test_pro_and_agency_no_length_cap(monkeypatch):
    for plan in ("pro", "agency"):
        _patch_db(monkeypatch, plan=plan)
        _run(billing.enforce_video_length_cap(uuid.uuid4(), 60))  # must not raise
    print("✅ test_pro_and_agency_no_length_cap")


def test_free_plan_no_length_cap():
    """The ratification is explicitly Starter-only for the length axis; free
    (not part of the ratified ladder) must not be newly capped as a side
    effect of this chunk."""
    async def _fetch_one(query, *args):
        if "FROM accounts a" in query and "JOIN memberships m" in query:
            return {"plan": "free", "trial_ends_at": None}
        raise AssertionError(f"unexpected query: {query!r}")

    import unittest.mock as mock
    with mock.patch.object(billing, "fetch_one", _fetch_one):
        _run(billing.enforce_video_length_cap(uuid.uuid4(), 60))  # must not raise
    print("✅ test_free_plan_no_length_cap")


def test_none_length_never_checked(monkeypatch):
    """A caller with no length picked yet (None) must short-circuit before
    even querying the plan — never a spurious DB call or a false reject."""
    async def _fetch_one(query, *args):
        raise AssertionError("enforce_video_length_cap must not query the DB for a None length")
    monkeypatch.setattr(billing, "fetch_one", _fetch_one)
    _run(billing.enforce_video_length_cap(uuid.uuid4(), None))  # must not raise
    print("✅ test_none_length_never_checked")
