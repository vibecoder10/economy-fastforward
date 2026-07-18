"""Functional tests for C14's two write endpoints (checklist §1.2):

1. PATCH /api/assets/{id}/model-override — the per-scene override sheet's
   write path (routes/assets.py). Validates against MODEL_REGISTRY the same
   way pipeline_executor.run_clip_generation's own gate does (a wired model
   id, or null/"" to clear back to the router's own recommendation).
2. PATCH /api/videos/{id} render_style — the "Channel look" control
   (Animated/Realistic/Auto), reusing the existing generic video-update
   route (routes/videos.py's update_video) rather than forking a new one.

TestClient + monkeypatched database module-level names (same pattern as
tests/functional/test_model_registry.py) — no live DB.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c14_model_override_and_render_style.py -q
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import get_tenant_id
import routes.assets as assets_route  # noqa: E402
import routes.videos as videos_route  # noqa: E402

TENANT = "00000000-0000-0000-0000-000000000000"
ASSET_ID = "asset-1"
VIDEO_ID = "video-1"


def _assets_client() -> TestClient:
    app = FastAPI()
    app.include_router(assets_route.router)
    app.dependency_overrides[get_tenant_id] = lambda: TENANT
    return TestClient(app)


def _videos_client() -> TestClient:
    app = FastAPI()
    app.include_router(videos_route.router)
    app.dependency_overrides[get_tenant_id] = lambda: TENANT
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. PATCH /api/assets/{id}/model-override
# ---------------------------------------------------------------------------

def test_model_override_404_for_unknown_or_other_tenant_asset(monkeypatch):
    """Tenant-scoping: the ownership SELECT is WHERE id=$1 AND tenant_id=$2 —
    a miss (unknown asset, or one belonging to a different tenant) is a 404,
    never a silent write."""
    seen_queries = []

    async def fake_fetch_one(query, *args):
        seen_queries.append((query, args))
        return None

    monkeypatch.setattr(assets_route, "fetch_one", fake_fetch_one)
    client = _assets_client()
    resp = client.patch(f"/api/assets/{ASSET_ID}/model-override", json={"model_override": "veo-3.1-quality"})
    assert resp.status_code == 404
    assert seen_queries[0][1] == (ASSET_ID, TENANT)
    assert "tenant_id" in seen_queries[0][0]


def test_model_override_rejects_unwired_model(monkeypatch):
    async def fake_fetch_one(query, *args):
        return {"id": ASSET_ID}

    monkeypatch.setattr(assets_route, "fetch_one", fake_fetch_one)
    client = _assets_client()
    # kling-3.0-pro is a real registry entry but wired=False (checklist §0.2).
    resp = client.patch(f"/api/assets/{ASSET_ID}/model-override", json={"model_override": "kling-3.0-pro"})
    assert resp.status_code == 400


def test_model_override_rejects_unknown_model_id(monkeypatch):
    async def fake_fetch_one(query, *args):
        return {"id": ASSET_ID}

    monkeypatch.setattr(assets_route, "fetch_one", fake_fetch_one)
    client = _assets_client()
    resp = client.patch(f"/api/assets/{ASSET_ID}/model-override", json={"model_override": "not-a-real-model"})
    assert resp.status_code == 400


def test_model_override_writes_wired_model(monkeypatch):
    writes = []

    async def fake_fetch_one(query, *args):
        return {"id": ASSET_ID}

    async def fake_execute(query, *args):
        writes.append(args)
        return "UPDATE 1"

    monkeypatch.setattr(assets_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(assets_route, "execute", fake_execute)
    client = _assets_client()
    resp = client.patch(f"/api/assets/{ASSET_ID}/model-override", json={"model_override": "veo-3.1-quality"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "saved", "model_override": "veo-3.1-quality"}
    assert writes == [("veo-3.1-quality", ASSET_ID, TENANT)]


def test_model_override_null_or_empty_clears_it(monkeypatch):
    """The sheet's "Use recommendation" button sends null; an empty string
    is treated the same way — both must write NULL, not the literal ''."""
    async def fake_fetch_one(query, *args):
        return {"id": ASSET_ID}

    for payload in (None, ""):
        writes = []

        async def fake_execute(query, *args):
            writes.append(args)
            return "UPDATE 1"

        monkeypatch.setattr(assets_route, "fetch_one", fake_fetch_one)
        monkeypatch.setattr(assets_route, "execute", fake_execute)
        client = _assets_client()
        resp = client.patch(f"/api/assets/{ASSET_ID}/model-override", json={"model_override": payload})
        assert resp.status_code == 200, resp.text
        assert resp.json()["model_override"] is None
        assert writes[0][0] is None, f"payload {payload!r} must write NULL, got {writes[0][0]!r}"


# ---------------------------------------------------------------------------
# 2. PATCH /api/videos/{id} — render_style ("Channel look")
# ---------------------------------------------------------------------------

def test_render_style_rejects_invalid_value(monkeypatch):
    async def fake_fetch_one(query, *args):
        return {"id": VIDEO_ID}

    monkeypatch.setattr(videos_route, "fetch_one", fake_fetch_one)
    client = _videos_client()
    resp = client.patch(f"/api/videos/{VIDEO_ID}", json={"render_style": "cartoonish"})
    assert resp.status_code == 400


def test_render_style_accepts_animated_and_realistic(monkeypatch):
    async def fake_fetch_one(query, *args):
        return {"id": VIDEO_ID}

    async def fake_execute(query, *args):
        return "UPDATE 1"

    monkeypatch.setattr(videos_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(videos_route, "execute", fake_execute)
    client = _videos_client()
    for value in ("animated", "realistic"):
        resp = client.patch(f"/api/videos/{VIDEO_ID}", json={"render_style": value})
        assert resp.status_code == 200, resp.text


def test_render_style_null_clears_it_back_to_auto(monkeypatch):
    """None is a valid write here (not a no-op) — it's how the "Auto" option
    clears a previously-declared channel look back to the router's
    money-safe undeclared default (shared.model_router.route_shot_model)."""
    writes = []

    async def fake_fetch_one(query, *args):
        return {"id": VIDEO_ID}

    async def fake_execute(query, *args):
        writes.append(args)
        return "UPDATE 1"

    monkeypatch.setattr(videos_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(videos_route, "execute", fake_execute)
    client = _videos_client()
    resp = client.patch(f"/api/videos/{VIDEO_ID}", json={"render_style": None})
    assert resp.status_code == 200
    assert writes[0][0] is None


if __name__ == "__main__":
    import inspect
    mod = sys.modules[__name__]
    test_fns = [obj for name, obj in vars(mod).items()
                if name.startswith("test_") and inspect.isfunction(obj)]
    print(f"{len(test_fns)} test functions found — run via pytest for monkeypatch support")
