"""Wiring test for the autopilot dial fields on GET /api/autopilot/summary
(checklist C50, P4.2-a). Guards the exact failure mode
tests/functional/test_c33_vph_wiring.py documents: a field added to the
accessor/dict but never listed on the Pydantic response model would be
silently stripped by FastAPI's response_model filtering, so the API would
look wired while actually serving nothing.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/test_autopilot_dial_route.py -q
"""
import asyncio
import os
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import get_tenant_id
import routes.autopilot as autopilot_route
from autopilot_dial import AutopilotDial

TENANT = "tenant-c50"


def _fake_fetch_one_factory(config_row=None):
    async def fake_fetch_one(query, *args):
        if "COUNT(*)" in query:
            return {"count": 0}
        if "AVG(ctr)" in query:
            return {"avg": None}
        if "FROM autopilot_config" in query:
            return config_row
        return None
    return fake_fetch_one


async def _empty_fetch_all(query, *args):
    return []


def _build_client(monkeypatch, *, config_row=None, dial=None, weekly_spent=0.0):
    monkeypatch.setattr(autopilot_route, "fetch_one", _fake_fetch_one_factory(config_row))
    monkeypatch.setattr(autopilot_route, "fetch_all", _empty_fetch_all)

    async def fake_get_autopilot_dial(tenant_id):
        return dial if dial is not None else AutopilotDial()

    monkeypatch.setattr(autopilot_route, "get_autopilot_dial", fake_get_autopilot_dial)

    # C54 (P4.2-e) — real spend in the current weekly window, additive on
    # this same summary response.
    async def fake_get_weekly_spend(tenant_id):
        return weekly_spent

    monkeypatch.setattr(autopilot_route, "get_weekly_spend", fake_get_weekly_spend)

    app = FastAPI()
    app.include_router(autopilot_route.router)
    app.dependency_overrides[get_tenant_id] = lambda: TENANT
    return TestClient(app)


def test_summary_response_includes_dial_fields_with_defaults(monkeypatch):
    client = _build_client(monkeypatch, config_row=None, dial=None)
    resp = client.get("/api/autopilot/summary")
    assert resp.status_code == 200
    config = resp.json()["config"]
    assert config["dial_level"] == "propose_only"
    assert config["weekly_budget_cap"] is None
    assert config["weekly_spend_reset_at"] is None
    assert config["kill_switch_tripped_at"] is None
    assert config["kill_switch_reason"] is None
    assert config["weekly_spent"] == 0.0


def test_summary_response_surfaces_non_default_dial_values(monkeypatch):
    dial = AutopilotDial(
        dial_level="auto_draft",
        weekly_budget_cap=200.0,
        weekly_spend_reset_at=None,
        kill_switch_tripped_at=None,
        kill_switch_reason=None,
    )
    client = _build_client(
        monkeypatch,
        config_row={
            "videos_per_month": 15, "production_interval_days": 2,
            "videos_per_scrape": 10, "weights": {}, "thresholds": {},
            "enabled": True, "last_cycle": None,
        },
        dial=dial,
    )
    resp = client.get("/api/autopilot/summary")
    assert resp.status_code == 200
    config = resp.json()["config"]
    assert config["dial_level"] == "auto_draft"
    assert config["weekly_budget_cap"] == 200.0


def test_summary_response_surfaces_tripped_kill_switch(monkeypatch):
    import datetime as _dt

    dial = AutopilotDial(
        dial_level="propose_only",
        weekly_budget_cap=None,
        weekly_spend_reset_at=None,
        kill_switch_tripped_at=_dt.datetime(2026, 7, 18, 12, 0, 0, tzinfo=_dt.timezone.utc),
        kill_switch_reason="weekly budget cap breached",
    )
    client = _build_client(monkeypatch, config_row=None, dial=dial)
    resp = client.get("/api/autopilot/summary")
    assert resp.status_code == 200
    config = resp.json()["config"]
    assert config["kill_switch_reason"] == "weekly budget cap breached"
    assert config["kill_switch_tripped_at"] is not None
