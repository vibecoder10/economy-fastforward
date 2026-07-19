"""Tests for C20 (checklist §2.1 [D]+[B] — "5 rich Python visual profiles
invisible to users; UI shows only 6 shallow hardcoded presets").

Three layers pinned here, no live DB / no network:

  1. GET /api/style-presets (routes/style_presets.py) — returns the seeded
     catalog shape, ordered by sort, JSONB tags/best_for parsed to lists.
     Same TestClient + dependency-override pattern as
     tests/functional/test_model_registry.py.

  2. routes/videos.py's `_resolve_style_preset_id` — the create_video
     validation gate: a real active style_presets row passes through
     unchanged, an unknown/inactive id 400s, blank/None is a silent no-op
     (most videos never pick one).

  3. pipeline_executor.py's `_resolve_visual_profile_id` — the VISUAL_PROFILE
     executor seam (checklist "the existing seam at pipeline_executor.py
     L6358"): style_preset_id wins over the legacy free-text `visual_style`
     field, which wins over the "neutral_v1" default. Fail-soft: a missing
     style_preset_id reproduces the EXACT pre-C20 resolution, unchanged.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c20_style_presets.py -q
"""
import os
import sys
import asyncio

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from auth import get_tenant_id
import routes.style_presets as style_presets_route
import routes.videos as videos_route
from pipeline_executor import _resolve_visual_profile_id
from orchestrator.pipeline_constants import IdeaFields


# =============================================================================
# Part 1 — GET /api/style-presets
# =============================================================================

_SEEDED_ROWS = [
    {"id": "neutral_v1", "display_name": "Neutral Documentary (default)",
     "description": "style-agnostic default", "tags": ["neutral", "documentary"],
     "best_for": ["any niche"], "cost_tier": "low", "preview_url": None,
     "source": "python_profile", "sort": 0},
    {"id": "holographic_hud", "display_name": "Holographic Intelligence Display",
     "description": "war room aesthetic", "tags": ["dark", "holographic"],
     "best_for": ["geopolitics"], "cost_tier": "low", "preview_url": None,
     "source": "python_profile", "sort": 1},
    {"id": "cinematic_dossier", "display_name": "Cinematic Intelligence Briefing",
     "description": "Rembrandt lighting", "tags": ["dark", "cinematic"],
     "best_for": ["finance"], "cost_tier": "mid", "preview_url": None,
     "source": "python_profile", "sort": 2},
    {"id": "clay_mannequin", "display_name": "Clay Mannequin Dioramas",
     "description": "3D diorama renders", "tags": ["3D", "clay"],
     "best_for": ["explainers"], "cost_tier": "mid", "preview_url": None,
     "source": "python_profile", "sort": 3},
    {"id": "cinematic_illustration", "display_name": "Cinematic Animated Illustration",
     "description": "2D ink illustration", "tags": ["illustration", "animated"],
     "best_for": ["geopolitics"], "cost_tier": "low", "preview_url": None,
     "source": "python_profile", "sort": 4},
]


def _make_client(monkeypatch, rows=None):
    async def fake_fetch_all(query, *args):
        assert "style_presets" in query
        assert "active = true" in query
        return rows if rows is not None else list(_SEEDED_ROWS)

    monkeypatch.setattr(style_presets_route, "fetch_all", fake_fetch_all)

    app = FastAPI()
    app.include_router(style_presets_route.router)
    app.dependency_overrides[get_tenant_id] = lambda: "00000000-0000-0000-0000-000000000000"
    return TestClient(app)


def test_returns_seeded_catalog_shape_and_count(monkeypatch):
    client = _make_client(monkeypatch)
    resp = client.get("/api/style-presets")
    assert resp.status_code == 200
    body = resp.json()
    presets = body["presets"]
    assert len(presets) == 5
    ids = [p["id"] for p in presets]
    assert ids == [
        "neutral_v1", "holographic_hud", "cinematic_dossier",
        "clay_mannequin", "cinematic_illustration",
    ], "must preserve seeded sort order"
    first = presets[0]
    assert first["display_name"] == "Neutral Documentary (default)"
    assert first["tags"] == ["neutral", "documentary"]
    assert first["best_for"] == ["any niche"]
    assert first["cost_tier"] == "low"
    assert first["source"] == "python_profile"


def test_jsonb_string_encoded_tags_are_parsed(monkeypatch):
    """asyncpg may hand back JSONB as a raw JSON string depending on codec
    setup (same defensive reason routes/visual_styles.py's _parse_jsonb
    exists) — must still parse to a real list, not leak a string."""
    import json
    row = dict(_SEEDED_ROWS[0])
    row["tags"] = json.dumps(["neutral", "documentary"])
    row["best_for"] = json.dumps(["any niche"])
    client = _make_client(monkeypatch, rows=[row])
    body = client.get("/api/style-presets").json()
    assert body["presets"][0]["tags"] == ["neutral", "documentary"]
    assert body["presets"][0]["best_for"] == ["any niche"]


def test_requires_tenant_auth():
    """No dependency override — mirrors GET /api/models's auth posture
    (a global catalog still requires an authenticated tenant, matching
    every other route in this app)."""
    app = FastAPI()
    app.include_router(style_presets_route.router)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/style-presets")
    assert resp.status_code in (401, 403, 422), (
        f"expected an auth failure without get_tenant_id override, got {resp.status_code}")


# =============================================================================
# Part 2 — routes/videos.py::_resolve_style_preset_id (create_video gate)
# =============================================================================

def test_resolve_blank_or_none_is_noop(monkeypatch):
    async def fail_fetch_one(*a, **k):
        raise AssertionError("must not query the DB for a blank id")
    monkeypatch.setattr(videos_route, "fetch_one", fail_fetch_one)
    assert asyncio.run(videos_route._resolve_style_preset_id(None)) is None
    assert asyncio.run(videos_route._resolve_style_preset_id("   ")) is None


def test_resolve_valid_active_preset_passes_through(monkeypatch):
    async def fake_fetch_one(query, *args):
        assert "style_presets" in query
        assert args == ("holographic_hud",)
        return {"id": "holographic_hud"}
    monkeypatch.setattr(videos_route, "fetch_one", fake_fetch_one)
    result = asyncio.run(videos_route._resolve_style_preset_id("holographic_hud"))
    assert result == "holographic_hud"


def test_resolve_unknown_preset_raises_400(monkeypatch):
    async def fake_fetch_one(query, *args):
        return None  # not found / inactive
    monkeypatch.setattr(videos_route, "fetch_one", fake_fetch_one)
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(videos_route._resolve_style_preset_id("not_a_real_preset"))
    assert exc_info.value.status_code == 400


# =============================================================================
# Part 3 — pipeline_executor.py::_resolve_visual_profile_id (VISUAL_PROFILE seam)
# =============================================================================

def test_style_preset_id_wins_when_present():
    idea = {
        IdeaFields.STYLE_PRESET_ID: "holographic_hud",
        IdeaFields.VISUAL_STYLE: "Pixar 3D",  # legacy shallow-preset text, should lose
    }
    assert _resolve_visual_profile_id(idea) == "holographic_hud"


def test_fails_soft_to_legacy_visual_style_when_preset_missing():
    """Fail-soft requirement: NO style_preset_id (every pre-C20 video, and
    any video where the creator never picked one) reproduces the exact
    pre-C20 behavior — falls through to the legacy visual_style field."""
    idea = {IdeaFields.VISUAL_STYLE: "cinematic_illustration"}
    assert _resolve_visual_profile_id(idea) == "cinematic_illustration"


def test_fails_soft_to_default_when_both_missing():
    assert _resolve_visual_profile_id({}) == "neutral_v1"


def test_blank_style_preset_id_falls_through_not_treated_as_set():
    """A blank string (empty column value, not NULL) must not win over a
    real visual_style value — same 'blank is missing' rule the rest of this
    file already follows (_nonblank helper above)."""
    idea = {
        IdeaFields.STYLE_PRESET_ID: "   ",
        IdeaFields.VISUAL_STYLE: "cinematic_dossier",
    }
    assert _resolve_visual_profile_id(idea) == "cinematic_dossier"


