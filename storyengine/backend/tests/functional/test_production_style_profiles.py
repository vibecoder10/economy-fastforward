"""Contract tests for the public production-style axis (migration 121)."""

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from auth import get_tenant_id
from models import CreateVideoRequest
import production_styles
import routes.production_styles as production_styles_route
import routes.videos as videos_route


_KNOBS = {
    "render_mode": "coverage",
    "script_profile": "neutral_v1",
    "visual_profile": "neutral_v1",
    "image_density": {"mode": "dialogue_shape"},
    "animation": {"enabled": True},
    "language": {"mode": "bilingual"},
    "dubbing": {"enabled": True},
    "segmentation": {"mode": "speaker_turn"},
    "camera": {"mode": "dialogue_coverage"},
    "quality_laws": ["character_continuity"],
    "image_source": "generate",
}

_ROWS = [
    {
        "id": style_id,
        "version": 1,
        "label": label,
        "description": f"{label} description",
        "knobs": dict(_KNOBS),
        "estimate": {"cost_tier": "medium"},
        "requires_byok": True,
        "sort": sort,
    }
    for sort, (style_id, label) in enumerate(
        [
            ("bilingual_character_animation", "Bilingual Character Animation"),
            ("simple_language_animation", "Simple-Language Animation"),
            ("photo_documentary", "Photo Documentary"),
            ("animated_investigative_documentary", "Animated Investigative Documentary"),
        ],
        start=1,
    )
]


def test_request_field_is_optional_for_legacy_callers_but_accepts_public_id():
    assert CreateVideoRequest(title="legacy").production_style_id is None
    request = CreateVideoRequest(
        title="new", production_style_id="photo_documentary"
    )
    assert request.production_style_id == "photo_documentary"


def test_normalized_profile_requires_every_named_knob_and_byok_snapshot():
    profile = production_styles.normalize_profile_row(_ROWS[0])
    assert profile is not None
    assert set(profile["knobs"]) == set(production_styles.REQUIRED_KNOB_KEYS)
    snapshot = production_styles.snapshot_profile(profile)
    assert snapshot["requires_byok"] is True
    snapshot["knobs"]["render_mode"] = "mutated"
    assert profile["knobs"]["render_mode"] == "coverage"


def test_catalog_rejects_channel_brand_names():
    labels = " ".join(row["label"].lower() for row in _ROWS)
    assert "poco" not in labels
    assert "easy english" not in labels
    assert "dvsu" not in labels
    assert "power doctrine" not in labels


def test_jsonb_strings_are_normalized():
    row = dict(_ROWS[0])
    row["knobs"] = json.dumps(_KNOBS)
    row["estimate"] = json.dumps({"cost_tier": "high"})
    profile = production_styles.normalize_profile_row(row)
    assert profile is not None
    assert profile["knobs"]["image_source"] == "generate"
    assert profile["estimate"]["cost_tier"] == "high"


def _catalog_client(monkeypatch):
    async def fake_list_public_profiles():
        return [production_styles.normalize_profile_row(row) for row in _ROWS]

    monkeypatch.setattr(
        production_styles_route,
        "list_public_profiles",
        fake_list_public_profiles,
    )
    app = FastAPI()
    app.include_router(production_styles_route.router)
    app.dependency_overrides[get_tenant_id] = lambda: "tenant-a"
    return TestClient(app)


def test_catalog_endpoint_returns_exactly_four_public_profiles(monkeypatch):
    response = _catalog_client(monkeypatch).get("/api/production-styles")
    assert response.status_code == 200
    body = response.json()
    assert [style["id"] for style in body["styles"]] == [
        row["id"] for row in _ROWS
    ]
    assert all(style["requires_byok"] for style in body["styles"])


def test_catalog_requires_authentication():
    app = FastAPI()
    app.include_router(production_styles_route.router)
    response = TestClient(app, raise_server_exceptions=False).get(
        "/api/production-styles"
    )
    assert response.status_code in (401, 403, 422)


def test_resolve_blank_preserves_legacy_without_catalog_query(monkeypatch):
    async def forbidden(_style_id):
        raise AssertionError("blank legacy requests must not query the catalog")

    monkeypatch.setattr(production_styles, "get_public_profile", forbidden)
    assert asyncio.run(videos_route._resolve_production_style(None)) == (
        None,
        None,
        None,
    )


def test_resolve_public_style_returns_versioned_snapshot(monkeypatch):
    async def fake_get(style_id):
        assert style_id == "photo_documentary"
        return production_styles.normalize_profile_row(_ROWS[2])

    monkeypatch.setattr(production_styles, "get_public_profile", fake_get)
    style_id, version, snapshot = asyncio.run(
        videos_route._resolve_production_style("photo_documentary")
    )
    assert style_id == "photo_documentary"
    assert version == 1
    assert snapshot["label"] == "Photo Documentary"
    assert snapshot["requires_byok"] is True


def test_resolve_unknown_style_is_a_400(monkeypatch):
    async def fake_get(_style_id):
        return None

    monkeypatch.setattr(production_styles, "get_public_profile", fake_get)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(videos_route._resolve_production_style("customer-channel"))
    assert exc.value.status_code == 400
    assert "Unknown production style" in str(exc.value.detail)


def test_migration_and_fresh_schema_declare_snapshot_and_public_profile():
    backend = Path(__file__).resolve().parents[2]
    migration = (
        backend / "migrations" / "121_production_style_profiles.sql"
    ).read_text()
    schema = (backend.parent / "schema.sql").read_text()
    for text in (migration, schema):
        assert "production_style_profiles" in text
        assert "production_style_snapshot" in text
        assert "requires_byok" in text
