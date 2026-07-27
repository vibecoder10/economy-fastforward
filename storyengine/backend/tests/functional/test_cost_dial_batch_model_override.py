"""Functional tests for POST /api/assets/batch-model-override — the Cost
Dial's bulk actions (Make all draft / Make all cinematic / Reset to
recommended). Same validation and tenant-scoping contract as PATCH
/{asset_id}/model-override (routes/assets.py, covered by
test_c14_model_override_and_render_style.py), applied to an entire video in
one UPDATE statement instead of one PATCH per shot.

TestClient + monkeypatched database module-level names (same pattern as
test_c14_model_override_and_render_style.py) — no live DB.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_cost_dial_batch_model_override.py -q
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import get_tenant_id
import routes.assets as assets_route  # noqa: E402

TENANT = "00000000-0000-0000-0000-000000000000"
VIDEO_ID = "video-1"


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(assets_route.router)
    app.dependency_overrides[get_tenant_id] = lambda: TENANT
    return TestClient(app)


def test_batch_model_override_404_for_unknown_or_other_tenant_video(monkeypatch):
    """Tenant-scoping: the ownership SELECT is WHERE id=$1 AND tenant_id=$2 —
    a miss (unknown video, or one belonging to a different tenant) is a 404,
    never a silent bulk write."""
    seen_queries = []

    async def fake_fetch_one(query, *args):
        seen_queries.append((query, args))
        return None

    monkeypatch.setattr(assets_route, "fetch_one", fake_fetch_one)
    client = _client()
    resp = client.post(
        "/api/assets/batch-model-override",
        json={"video_id": VIDEO_ID, "model_override": "grok-imagine"},
    )
    assert resp.status_code == 404
    assert seen_queries[0][1] == (VIDEO_ID, TENANT)
    assert "tenant_id" in seen_queries[0][0]


def test_batch_model_override_rejects_unwired_model(monkeypatch):
    async def fake_fetch_one(query, *args):
        return {"id": VIDEO_ID}

    monkeypatch.setattr(assets_route, "fetch_one", fake_fetch_one)
    client = _client()
    # kling-3.0-pro is a real registry entry but wired=False (checklist §0.2)
    resp = client.post(
        "/api/assets/batch-model-override",
        json={"video_id": VIDEO_ID, "model_override": "kling-3.0-pro"},
    )
    assert resp.status_code == 400


def test_batch_model_override_rejects_unknown_model_id(monkeypatch):
    async def fake_fetch_one(query, *args):
        return {"id": VIDEO_ID}

    monkeypatch.setattr(assets_route, "fetch_one", fake_fetch_one)
    client = _client()
    resp = client.post(
        "/api/assets/batch-model-override",
        json={"video_id": VIDEO_ID, "model_override": "not-a-real-model"},
    )
    assert resp.status_code == 400


def test_batch_model_override_writes_wired_model_scoped_to_video_and_tenant(monkeypatch):
    writes = []

    async def fake_fetch_one(query, *args):
        return {"id": VIDEO_ID}

    async def fake_execute(query, *args):
        writes.append(args)
        return "UPDATE 142"

    monkeypatch.setattr(assets_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(assets_route, "execute", fake_execute)
    client = _client()
    resp = client.post(
        "/api/assets/batch-model-override",
        json={"video_id": VIDEO_ID, "model_override": "veo-3.1-quality"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "saved", "model_override": "veo-3.1-quality", "updated": 142}
    assert writes == [("veo-3.1-quality", VIDEO_ID, TENANT)]


def test_batch_model_override_null_or_empty_clears_every_row(monkeypatch):
    """Reset to recommended sends null; an empty string is treated the same
    way — both must write NULL to every row in the video, not the literal
    ''."""
    async def fake_fetch_one(query, *args):
        return {"id": VIDEO_ID}

    for payload in (None, ""):
        writes = []

        async def fake_execute(query, *args):
            writes.append(args)
            return "UPDATE 32"

        monkeypatch.setattr(assets_route, "fetch_one", fake_fetch_one)
        monkeypatch.setattr(assets_route, "execute", fake_execute)
        client = _client()
        resp = client.post(
            "/api/assets/batch-model-override",
            json={"video_id": VIDEO_ID, "model_override": payload},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["model_override"] is None
        assert body["updated"] == 32
        assert writes[0][0] is None, f"payload {payload!r} must write NULL, got {writes[0][0]!r}"
