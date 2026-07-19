"""Tests for C33's `avg_vph` wiring through analytics_by_style.py and the
GET /api/analytics/by-style Pydantic response model (checklist §3.4 — "the
autopilot/notifier comparisons that use competitor VPH should be able to
compare like-for-like").

Companion to test_c33_own_vph.py (the per-video compute_own_vph() unit
tests) and test_c30_style_performance.py (the pre-existing aggregation
shape this file must not break — confirmed separately by running that
suite unmodified). This file only pins the NEW field: it survives
_row()'s dict-building AND survives FastAPI's response_model filtering
(StyleChoiceAggregate in models.py), which a field only added to the SQL
string / _row() dict but not the Pydantic model would silently drop.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c33_vph_wiring.py -q
"""
import asyncio
import os
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import get_tenant_id
import analytics_by_style
import routes.analytics as analytics_route

TENANT = "tenant-33"

_ROWS = [
    {"choice": "pixar_3d", "video_count": 3, "synced_count": 2,
     "avg_ctr": 6.5, "avg_retention": 55.0, "avg_vph": 42.3,
     "total_views": 15000, "total_spend": 42.10},
    {"choice": "dossier", "video_count": 1, "synced_count": 0,
     "avg_ctr": None, "avg_retention": None, "avg_vph": None,
     "total_views": 0, "total_spend": 5.00},
]


async def _fake_fetch_all(query, *args):
    assert "avg_vph" in query, "aggregation SQL must select avg_vph (checklist §3.4)"
    return _ROWS


def test_aggregate_column_carries_avg_vph_through(monkeypatch):
    monkeypatch.setattr(analytics_by_style, "fetch_all", _fake_fetch_all)
    result = asyncio.run(analytics_by_style._aggregate_column(TENANT, "by_style_preset", "style_preset_id"))
    by_choice = {r["choice"]: r for r in result}
    assert by_choice["pixar_3d"]["avg_vph"] == 42.3
    # honest NULL: a group with zero synced videos reports None, not 0.0
    assert by_choice["dossier"]["avg_vph"] is None


def test_aggregate_clip_model_carries_avg_vph_through(monkeypatch):
    async def fake_fetch_all_clip(query, *args):
        assert "avg_vph" in query
        return _ROWS

    monkeypatch.setattr(analytics_by_style, "fetch_all", fake_fetch_all_clip)
    result = asyncio.run(analytics_by_style._aggregate_clip_model(TENANT))
    by_choice = {r["choice"]: r for r in result}
    assert by_choice["pixar_3d"]["avg_vph"] == 42.3


def test_endpoint_response_model_does_not_drop_avg_vph(monkeypatch):
    """Guards against the exact failure mode of adding a field to the SQL/
    dict but forgetting models.py's StyleChoiceAggregate — FastAPI's
    response_model would silently strip an unlisted field, so the API
    would look wired while actually serving nothing."""
    monkeypatch.setattr(analytics_by_style, "fetch_all", _fake_fetch_all)
    app = FastAPI()
    app.include_router(analytics_route.router)
    app.dependency_overrides[get_tenant_id] = lambda: TENANT
    client = TestClient(app)

    resp = client.get("/api/analytics/by-style")
    assert resp.status_code == 200
    body = resp.json()
    pixar = next(r for r in body["by_style_preset"] if r["choice"] == "pixar_3d")
    assert pixar["avg_vph"] == 42.3
    dossier = next(r for r in body["by_style_preset"] if r["choice"] == "dossier")
    assert dossier["avg_vph"] is None
