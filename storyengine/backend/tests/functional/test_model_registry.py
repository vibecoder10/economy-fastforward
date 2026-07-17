"""Functional test for GET /api/models (routes/model_registry.py).

Runs without a DB: the route only reads shared.channel_profile.MODEL_REGISTRY
(skills/video-pipeline) and the get_tenant_id auth dependency is overridden.

Proves the fix for storyengine-wiring-fix-checklist.md §0.2: the endpoint's
`wired` flags must match pipeline_executor.run_clip_generation's gate exactly
(same registry entry, same flag) — Kling 3.0 Pro / Runway Gen-4 Turbo /
Hailuo 2.3 Standard must come back wired=false so the frontend never renders
them as selectable.

Run:  ./venv/bin/python -m pytest tests/functional/test_model_registry.py -q
      (from storyengine/backend)
"""
import os
import sys

# abspath (not a relative ".." join) — routes/model_registry.py resolves its own
# pipeline-root sys.path entry via Path(__file__).parent chaining, which needs
# __file__ to be absolute or the ".." segments compound instead of collapsing.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import get_tenant_id
import routes.model_registry as model_registry_route


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(model_registry_route.router)
    app.dependency_overrides[get_tenant_id] = lambda: "00000000-0000-0000-0000-000000000000"
    return TestClient(app)


def test_models_endpoint_returns_all_registry_entries():
    client = _make_client()
    resp = client.get("/api/models")
    assert resp.status_code == 200
    body = resp.json()
    assert body["default_video_model"] == "grok-imagine"
    ids = {m["id"] for m in body["models"]}
    assert ids == {
        "grok-imagine", "seedance-2-fast", "veo-3.1-fast", "veo-3.1-quality",
        "kling-3.0-pro", "runway-gen4-turbo", "hailuo-2.3-standard",
    }


def test_dead_models_are_wired_false():
    client = _make_client()
    body = client.get("/api/models").json()
    by_id = {m["id"]: m for m in body["models"]}
    for dead_id in ("kling-3.0-pro", "runway-gen4-turbo", "hailuo-2.3-standard"):
        assert by_id[dead_id]["wired"] is False, f"{dead_id} should not be selectable yet"
        assert by_id[dead_id]["kind"] == "video"


def test_live_models_are_wired_true():
    client = _make_client()
    body = client.get("/api/models").json()
    by_id = {m["id"]: m for m in body["models"]}
    for live_id in ("grok-imagine", "seedance-2-fast", "veo-3.1-fast", "veo-3.1-quality"):
        assert by_id[live_id]["wired"] is True, f"{live_id} should be selectable"


if __name__ == "__main__":
    test_models_endpoint_returns_all_registry_entries()
    test_dead_models_are_wired_false()
    test_live_models_are_wired_true()
    print("OK")
