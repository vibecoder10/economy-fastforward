"""Tests for C30 (checklist §3.1 [D]+[B] — "preset/model choices queryable
next to CTR/retention snapshots + aggregation query", the P3.1a opener of the
learning-loop phase).

Three things pinned here, no live DB / no network:

  1. analytics_by_style.get_style_performance() — the ONE aggregation both
     callers use. Stubs `fetch_all` (routed by inspecting the query text,
     since the real GROUP BY runs in Postgres, not Python) with rows spanning
     TWO style-preset groups — one with real synced analytics, one with none
     ("no data yet") — plus render_style/script_profile/clip_model groups, to
     pin: correct tenant scoping, NULL/None preserved (never coerced to 0),
     spend joined from the ledger, and per-dimension fail-soft (one broken
     query doesn't sink the other three).

  2. routes/analytics.py's GET /api/analytics/by-style — same stub, hit via
     TestClient, proves the endpoint returns exactly what the aggregation
     returns (no separate re-implementation) and is tenant-scoped via the
     normal get_tenant_id dependency.

  3. channel_briefs._style_performance_brief — the copilot's read tool
     (C15d pattern). Same stub, proves it cites the SAME numbers the
     endpoint returns (one source, not a re-derived answer) and skips the
     "no data yet" group (below MIN_SAMPLE synced videos) rather than
     inventing a trend out of it.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c30_style_performance.py -q
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
import channel_briefs
import routes.analytics as analytics_route

TENANT = "tenant-30"

# --- canned per-dimension rows, as if Postgres already ran the GROUP BY ------

STYLE_PRESET_ROWS = [
    {"choice": "pixar_3d", "video_count": 3, "synced_count": 2,
     "avg_ctr": 6.5, "avg_retention": 55.0, "total_views": 15000, "total_spend": 42.10},
    {"choice": "dossier", "video_count": 1, "synced_count": 0,
     "avg_ctr": None, "avg_retention": None, "total_views": 0, "total_spend": 5.00},
]
RENDER_STYLE_ROWS = [
    {"choice": "animated", "video_count": 2, "synced_count": 2,
     "avg_ctr": 5.1, "avg_retention": 48.0, "total_views": 9000, "total_spend": 20.00},
]
SCRIPT_PROFILE_ROWS = [
    {"choice": "neutral_v1", "video_count": 4, "synced_count": 2,
     "avg_ctr": 4.4, "avg_retention": 50.0, "total_views": 11000, "total_spend": 30.00},
]
CLIP_MODEL_ROWS = [
    {"choice": "grok-imagine", "video_count": 2, "synced_count": 2,
     "avg_ctr": 7.2, "avg_retention": 60.0, "total_views": 20000, "total_spend": 12.60},
    {"choice": "seedance-2", "video_count": 1, "synced_count": 1,
     "avg_ctr": 3.0, "avg_retention": 40.0, "total_views": 1000, "total_spend": 18.00},
]

_CALLS: list[tuple[str, tuple]] = []


def _routed_fetch_all(*, fail_dimension: str | None = None):
    """A fake fetch_all that returns the right canned rows based on which
    dimension's query text it's given — mirrors how the real code builds 4
    distinct SQL strings, without needing a live Postgres GROUP BY."""
    async def fake_fetch_all(query, *args):
        _CALLS.append((query, args))
        assert args and args[0] == TENANT, "tenant_id must be the first bound param on every query"
        if "style_preset_id AS choice" in query:
            if fail_dimension == "by_style_preset":
                raise RuntimeError("simulated DB outage")
            return STYLE_PRESET_ROWS
        if "render_style AS choice" in query:
            if fail_dimension == "by_render_style":
                raise RuntimeError("simulated DB outage")
            return RENDER_STYLE_ROWS
        if "script_profile AS choice" in query:
            if fail_dimension == "by_script_profile":
                raise RuntimeError("simulated DB outage")
            return SCRIPT_PROFILE_ROWS
        if "d.model AS choice" in query:
            if fail_dimension == "by_clip_model":
                raise RuntimeError("simulated DB outage")
            return CLIP_MODEL_ROWS
        raise AssertionError(f"unrecognized query shape: {query[:80]!r}")
    return fake_fetch_all


# =============================================================================
# Part 1 — analytics_by_style.get_style_performance()
# =============================================================================

def test_groups_correctly_across_all_four_dimensions(monkeypatch):
    _CALLS.clear()
    monkeypatch.setattr(analytics_by_style, "fetch_all", _routed_fetch_all())
    result = asyncio.run(analytics_by_style.get_style_performance(TENANT))

    assert set(result.keys()) == {"by_style_preset", "by_render_style", "by_script_profile", "by_clip_model"}
    assert len(result["by_style_preset"]) == 2
    assert len(result["by_render_style"]) == 1
    assert len(result["by_script_profile"]) == 1
    assert len(result["by_clip_model"]) == 2
    # 4 dimensions, one query each — proves nothing is queried twice or skipped.
    assert len(_CALLS) == 4


def test_null_analytics_preserved_not_coerced_to_zero(monkeypatch):
    monkeypatch.setattr(analytics_by_style, "fetch_all", _routed_fetch_all())
    result = asyncio.run(analytics_by_style.get_style_performance(TENANT))
    by_choice = {r["choice"]: r for r in result["by_style_preset"]}

    pixar = by_choice["pixar_3d"]
    assert pixar["dimension"] == "by_style_preset"
    assert pixar["video_count"] == 3 and pixar["synced_count"] == 2
    assert pixar["avg_ctr"] == 6.5 and pixar["avg_retention"] == 55.0
    assert pixar["total_views"] == 15000
    assert pixar["total_spend"] == 42.10

    dossier = by_choice["dossier"]
    assert dossier["video_count"] == 1 and dossier["synced_count"] == 0
    # The "no data yet" honest-NULL case: never silently becomes 0.0/0%.
    assert dossier["avg_ctr"] is None
    assert dossier["avg_retention"] is None
    # Spend still counted even with zero synced analytics — a video costs
    # money the moment it's built, whether or not YouTube has synced back yet.
    assert dossier["total_spend"] == 5.00


def test_clip_model_dimension_uses_dominant_model_per_video(monkeypatch):
    monkeypatch.setattr(analytics_by_style, "fetch_all", _routed_fetch_all())
    result = asyncio.run(analytics_by_style.get_style_performance(TENANT))
    choices = {r["choice"] for r in result["by_clip_model"]}
    assert choices == {"grok-imagine", "seedance-2"}


def test_one_dimension_failing_does_not_sink_the_others(monkeypatch):
    monkeypatch.setattr(analytics_by_style, "fetch_all", _routed_fetch_all(fail_dimension="by_render_style"))
    result = asyncio.run(analytics_by_style.get_style_performance(TENANT))
    assert result["by_render_style"] == []  # fail-soft: empty, not a raised exception
    assert len(result["by_style_preset"]) == 2
    assert len(result["by_script_profile"]) == 1
    assert len(result["by_clip_model"]) == 2


# =============================================================================
# Part 2 — GET /api/analytics/by-style
# =============================================================================

def _analytics_client() -> TestClient:
    app = FastAPI()
    app.include_router(analytics_route.router)
    app.dependency_overrides[get_tenant_id] = lambda: TENANT
    return TestClient(app)


def test_endpoint_returns_the_same_aggregation_shape(monkeypatch):
    monkeypatch.setattr(analytics_by_style, "fetch_all", _routed_fetch_all())
    client = _analytics_client()
    resp = client.get("/api/analytics/by-style")
    assert resp.status_code == 200
    body = resp.json()
    assert {r["choice"] for r in body["by_style_preset"]} == {"pixar_3d", "dossier"}
    pixar = next(r for r in body["by_style_preset"] if r["choice"] == "pixar_3d")
    assert pixar["avg_ctr"] == 6.5
    dossier = next(r for r in body["by_style_preset"] if r["choice"] == "dossier")
    assert dossier["avg_ctr"] is None
    assert {r["choice"] for r in body["by_clip_model"]} == {"grok-imagine", "seedance-2"}


def test_endpoint_empty_when_no_data_never_crashes(monkeypatch):
    async def fake_fetch_all(query, *args):
        return []
    monkeypatch.setattr(analytics_by_style, "fetch_all", fake_fetch_all)
    client = _analytics_client()
    resp = client.get("/api/analytics/by-style")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "by_style_preset": [], "by_render_style": [],
        "by_script_profile": [], "by_clip_model": [],
    }


# =============================================================================
# Part 3 — channel_briefs._style_performance_brief (the copilot read tool)
# =============================================================================

def test_brief_cites_the_same_numbers_as_the_endpoint(monkeypatch):
    monkeypatch.setattr(analytics_by_style, "fetch_all", _routed_fetch_all())
    brief = asyncio.run(channel_briefs._style_performance_brief(TENANT))
    # Same numbers the endpoint returned in Part 2 — one source, not re-derived.
    assert "pixar_3d: 6.5% CTR, 55% retention (2 videos, $42.10 spent)" in brief
    assert "grok-imagine: 7.2% CTR" in brief
    # The "no data yet" dossier group (0 synced < MIN_SAMPLE) must not be cited
    # — inventing a trend from a single un-synced video would be dishonest.
    assert "dossier" not in brief


def test_brief_fail_soft_returns_empty_string_on_error(monkeypatch):
    async def fake_fetch_all(query, *args):
        raise RuntimeError("simulated DB outage")
    monkeypatch.setattr(analytics_by_style, "fetch_all", fake_fetch_all)
    brief = asyncio.run(channel_briefs._style_performance_brief(TENANT))
    assert brief == ""


def test_brief_empty_when_every_group_below_min_sample(monkeypatch):
    async def fake_fetch_all(query, *args):
        return [{"choice": "only_one", "video_count": 1, "synced_count": 1,
                  "avg_ctr": 9.0, "avg_retention": 60.0, "total_views": 500, "total_spend": 2.0}]
    monkeypatch.setattr(analytics_by_style, "fetch_all", fake_fetch_all)
    brief = asyncio.run(channel_briefs._style_performance_brief(TENANT))
    assert brief == ""


def test_channel_data_tool_includes_style_performance_section(monkeypatch):
    """agent_brain._tool_channel_data (C15d) must reach the new brief too —
    not just the home producer's _loop_brief."""
    import agent_brain

    async def fake_next(tenant_id):
        return ""

    async def fake_own(tenant_id):
        return ""

    async def fake_learnings(tenant_id):
        return ""

    monkeypatch.setattr(analytics_by_style, "fetch_all", _routed_fetch_all())
    monkeypatch.setattr(channel_briefs, "_next_to_make_brief", fake_next)
    monkeypatch.setattr(channel_briefs, "_own_performance_brief", fake_own)
    monkeypatch.setattr(channel_briefs, "_learnings_brief", fake_learnings)

    result = asyncio.run(agent_brain._run_tool("channel_data", {}, TENANT, "video-1", {}))
    assert "grok-imagine: 7.2% CTR" in result
