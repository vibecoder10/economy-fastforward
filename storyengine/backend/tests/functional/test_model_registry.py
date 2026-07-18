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


def test_cost_per_clip_matches_single_price_source():
    """C09 (checklist §0.3c): cost_per_clip is pulled forward from C11 so the
    Scenes tab's model dropdown can price itself straight off THIS endpoint
    instead of depending on a sibling component syncing a shared cache
    first. Must match shared.channel_profile.CLIP_PRICE_BY_MODEL exactly —
    the single source, not a second copy — and be null for an unwired model
    (no live price to quote)."""
    import shared.channel_profile as channel_profile

    client = _make_client()
    body = client.get("/api/models").json()
    by_id = {m["id"]: m for m in body["models"]}

    for model_id, price in channel_profile.CLIP_PRICE_BY_MODEL.items():
        assert by_id[model_id]["cost_per_clip"] == price, (
            f"{model_id}: endpoint price {by_id[model_id]['cost_per_clip']} != "
            f"registry price {price}")

    for dead_id in ("kling-3.0-pro", "runway-gen4-turbo", "hailuo-2.3-standard"):
        assert by_id[dead_id]["cost_per_clip"] is None, (
            f"{dead_id} is unwired — must not quote a live price")


# C11 (checklist §1.1): decision-table fields (best_for/tier) so a later
# per-scene router (C12) can pick models from data instead of hardcoding
# capabilities. Fixed vocabulary, mirrors ModelProfile's docstring in
# shared/channel_profile.py.
ALLOWED_TIERS = {"draft", "standard", "premium"}
ALLOWED_BEST_FOR_TAGS = {
    "draft", "hero", "broll", "multi_shot", "character", "atmospheric",
}


def test_every_model_has_tier_and_best_for_from_allowed_vocabulary():
    client = _make_client()
    body = client.get("/api/models").json()
    for model in body["models"]:
        assert model["tier"] in ALLOWED_TIERS, (
            f"{model['id']}: tier {model['tier']!r} not in {ALLOWED_TIERS}")
        assert model["best_for"], f"{model['id']}: best_for must not be empty"
        unknown = set(model["best_for"]) - ALLOWED_BEST_FOR_TAGS
        assert not unknown, (
            f"{model['id']}: best_for has unknown tags {unknown}, "
            f"allowed vocabulary is {ALLOWED_BEST_FOR_TAGS}")


def test_best_for_and_tier_match_registry_and_gap_analysis_routing():
    """Spot-checks the 4 WIRED models against the gap-analysis routing table
    (docs/reports/2026-07-17-higgsfield-vs-storyengine-gap-analysis.md,
    line ~85): Grok = draft, Seedance = multi_shot, Veo Fast = atmospheric/
    broll, Veo Quality = hero. Also proves the endpoint reads straight off
    ModelProfile — not a second hand-copied table — by comparing 1:1."""
    import shared.channel_profile as channel_profile

    client = _make_client()
    body = client.get("/api/models").json()
    by_id = {m["id"]: m for m in body["models"]}

    for model_id, profile in channel_profile.MODEL_REGISTRY.items():
        assert by_id[model_id]["best_for"] == profile.best_for, (
            f"{model_id}: endpoint best_for {by_id[model_id]['best_for']} != "
            f"registry {profile.best_for}")
        assert by_id[model_id]["tier"] == profile.tier, (
            f"{model_id}: endpoint tier {by_id[model_id]['tier']!r} != "
            f"registry {profile.tier!r}")

    assert by_id["grok-imagine"]["tier"] == "draft"
    assert "draft" in by_id["grok-imagine"]["best_for"]
    assert by_id["seedance-2-fast"]["tier"] == "standard"
    assert "multi_shot" in by_id["seedance-2-fast"]["best_for"]
    assert "atmospheric" in by_id["veo-3.1-fast"]["best_for"] or \
        "broll" in by_id["veo-3.1-fast"]["best_for"]
    assert by_id["veo-3.1-quality"]["tier"] == "premium"
    assert "hero" in by_id["veo-3.1-quality"]["best_for"]


if __name__ == "__main__":
    test_models_endpoint_returns_all_registry_entries()
    test_dead_models_are_wired_false()
    test_live_models_are_wired_true()
    test_cost_per_clip_matches_single_price_source()
    test_every_model_has_tier_and_best_for_from_allowed_vocabulary()
    test_best_for_and_tier_match_registry_and_gap_analysis_routing()
    print("OK")
