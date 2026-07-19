"""Tests for C23 (checklist §2.2, UX map §4 — "camera moves as clickable
presets"): the 40+-move camera catalog (image_prompts.engine.camera_moves)
was auto-only; creators couldn't see or pick a shot's camera move.

Four layers, no live DB / no network (same TestClient + monkeypatch pattern
as test_model_registry.py / test_c14_model_override_and_render_style.py /
test_c15b_show_and_approve_scene.py):

1. GET /api/camera-presets (routes/camera_presets.py) — curated subset
   shape + count, auth required.
2. PATCH /api/assets/{id}/camera-preset (routes/assets.py) — tenant-scoped
   write, validates against the full catalog via get_move().
3. pipeline_executor._apply_camera_preset_override — the pure composition
   function `run_clip_generation._one`'s silent-shot branch calls. This is
   the [V] contract: a set preset's motion_prompt is CONTAINED in (in fact
   IS) the composed prompt; NULL/blank/unknown id is byte-identical to
   before C23.
4. actions.py::_runner_camera_preset — the conversational door ("use a
   crash zoom on scene 12"), same write (assets.camera_preset_id), scene-
   scoped, free (no confirm card), reversible ("auto" clears it).

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c23_camera_presets.py -q
"""
import asyncio
import os
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import get_tenant_id
import routes.camera_presets as camera_presets_route  # noqa: E402
import routes.assets as assets_route  # noqa: E402
import actions  # noqa: E402
from pipeline_executor import _apply_camera_preset_override  # noqa: E402

TENANT = "00000000-0000-0000-0000-000000000000"
OTHER_TENANT = "11111111-1111-1111-1111-111111111111"
ASSET_ID = "asset-1"
VIDEO_ID = "video-1"


def _presets_client() -> TestClient:
    app = FastAPI()
    app.include_router(camera_presets_route.router)
    app.dependency_overrides[get_tenant_id] = lambda: TENANT
    return TestClient(app)


def _assets_client() -> TestClient:
    app = FastAPI()
    app.include_router(assets_route.router)
    app.dependency_overrides[get_tenant_id] = lambda: TENANT
    return TestClient(app)


# =============================================================================
# Part 1 — GET /api/camera-presets
# =============================================================================

def test_curated_preset_count_and_shape():
    client = _presets_client()
    resp = client.get("/api/camera-presets")
    assert resp.status_code == 200
    presets = resp.json()["presets"]
    assert len(presets) == len(camera_presets_route.CURATED_PRESET_IDS)
    ids = [p["id"] for p in presets]
    assert ids == camera_presets_route.CURATED_PRESET_IDS, "must preserve curated order"
    for p in presets:
        assert p["name"]
        assert p["motion_prompt"]
        assert isinstance(p["best_for"], list)
        assert p["category"]


def test_every_curated_id_is_a_real_catalog_move():
    """The curated list is hand-maintained (module docstring says so) — pin
    that it hasn't drifted from the real catalog."""
    from image_prompts.engine.camera_moves import get_move
    for move_id in camera_presets_route.CURATED_PRESET_IDS:
        assert get_move(move_id) is not None, f"{move_id} isn't in the catalog anymore"


def test_static_locked_included_with_empty_best_for():
    """static_locked is deliberately included (the 'force no movement' pick,
    distinct from clearing back to Auto) — its best_for is empty in the
    catalog (camera_moves.py: 'never scored') and that's fine here, it's a
    valid explicit choice, not a scored auto candidate."""
    client = _presets_client()
    presets = client.get("/api/camera-presets").json()["presets"]
    by_id = {p["id"]: p for p in presets}
    assert "static_locked" in by_id
    assert by_id["static_locked"]["best_for"] == []


def test_requires_tenant_auth():
    app = FastAPI()
    app.include_router(camera_presets_route.router)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/camera-presets")
    assert resp.status_code in (401, 403, 422)


# =============================================================================
# Part 2 — PATCH /api/assets/{id}/camera-preset
# =============================================================================

def test_camera_preset_404_for_unknown_or_other_tenant_asset(monkeypatch):
    seen_queries = []

    async def fake_fetch_one(query, *args):
        seen_queries.append((query, args))
        return None

    monkeypatch.setattr(assets_route, "fetch_one", fake_fetch_one)
    client = _assets_client()
    resp = client.patch(f"/api/assets/{ASSET_ID}/camera-preset", json={"camera_preset_id": "crash_zoom_in"})
    assert resp.status_code == 404
    assert seen_queries[0][1] == (ASSET_ID, TENANT)
    assert "tenant_id" in seen_queries[0][0]


def test_camera_preset_rejects_unknown_id(monkeypatch):
    async def fake_fetch_one(query, *args):
        return {"id": ASSET_ID}

    monkeypatch.setattr(assets_route, "fetch_one", fake_fetch_one)
    client = _assets_client()
    resp = client.patch(f"/api/assets/{ASSET_ID}/camera-preset", json={"camera_preset_id": "not-a-real-move"})
    assert resp.status_code == 400


def test_camera_preset_writes_valid_catalog_id(monkeypatch):
    writes = []

    async def fake_fetch_one(query, *args):
        return {"id": ASSET_ID}

    async def fake_execute(query, *args):
        writes.append(args)
        return "UPDATE 1"

    monkeypatch.setattr(assets_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(assets_route, "execute", fake_execute)
    client = _assets_client()
    resp = client.patch(f"/api/assets/{ASSET_ID}/camera-preset", json={"camera_preset_id": "crash_zoom_in"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "saved", "camera_preset_id": "crash_zoom_in"}
    assert writes[0] == ("crash_zoom_in", ASSET_ID, TENANT)


def test_camera_preset_blank_clears_override(monkeypatch):
    """Empty string / omitted -> NULL, same 'Use recommendation' shape as
    model_override — the chip's 'Auto' pick clears back to earn-the-move."""
    writes = []

    async def fake_fetch_one(query, *args):
        return {"id": ASSET_ID}

    async def fake_execute(query, *args):
        writes.append(args)
        return "UPDATE 1"

    monkeypatch.setattr(assets_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(assets_route, "execute", fake_execute)
    client = _assets_client()
    resp = client.patch(f"/api/assets/{ASSET_ID}/camera-preset", json={"camera_preset_id": ""})
    assert resp.status_code == 200
    assert resp.json() == {"status": "saved", "camera_preset_id": None}
    assert writes[0] == (None, ASSET_ID, TENANT)


# =============================================================================
# Part 3 — pipeline_executor._apply_camera_preset_override (the [V] contract)
# =============================================================================

_BASE_PROMPT = ("Slow push-in on the main subject. Keep the characters, art "
                "style, and composition exactly as shown, and animate only "
                "what is already in the frame.")


def test_null_camera_preset_is_byte_identical():
    """The core stash-proof contract: no camera_preset_id (every row before
    C23, and every row nobody has touched) must not change the prompt AT
    ALL — not even whitespace."""
    assert _apply_camera_preset_override(_BASE_PROMPT, None) == _BASE_PROMPT
    assert _apply_camera_preset_override(_BASE_PROMPT, "") == _BASE_PROMPT


def test_unknown_camera_preset_id_is_also_a_noop():
    assert _apply_camera_preset_override(_BASE_PROMPT, "totally-made-up") == _BASE_PROMPT


def test_set_camera_preset_contains_the_moves_motion_prompt():
    """picked 'crash zoom' -> the generated motion prompt CONTAINS (in fact
    equals, since this branch replaces rather than appends) the preset's
    own motion_prompt text — the exact [V] contract from checklist §2.2."""
    from image_prompts.engine.camera_moves import get_move
    result = _apply_camera_preset_override(_BASE_PROMPT, "crash_zoom_in")
    expected = get_move("crash_zoom_in").motion_prompt
    assert expected in result
    assert result == expected
    assert result != _BASE_PROMPT


def test_static_locked_preset_forces_the_no_movement_line():
    from image_prompts.engine.camera_moves import get_move
    result = _apply_camera_preset_override(_BASE_PROMPT, "static_locked")
    assert result == get_move("static_locked").motion_prompt
    assert "no camera movement" in result.lower()


# =============================================================================
# Part 4 — actions.py::_runner_camera_preset (the conversational door)
# =============================================================================

def test_camera_preset_wired_into_actions_table_and_runners():
    assert actions.ACTIONS["camera_preset"]["paid"] is False, "must run without a confirm card"
    assert actions.RUNNERS["camera_preset"] is actions._runner_camera_preset


def test_camera_preset_runner_requires_a_scene(monkeypatch):
    async def fail_execute(*a, **k):
        raise AssertionError("must not write without a scene")
    monkeypatch.setattr(actions, "execute", fail_execute)
    result = asyncio.run(actions._runner_camera_preset(
        TENANT, VIDEO_ID, None, {"scene": None, "change": "crash zoom"}))
    assert "which scene" in result.lower()


def test_camera_preset_runner_resolves_alias_and_writes_scene_scoped(monkeypatch):
    writes = []

    async def fake_execute(query, *args):
        writes.append((query, args))
        return "UPDATE 3"

    monkeypatch.setattr(actions, "execute", fake_execute)
    result = asyncio.run(actions._runner_camera_preset(
        TENANT, VIDEO_ID, None, {"scene": 12, "change": "use a crash zoom"}))
    query, args = writes[0]
    assert "camera_preset_id" in query
    assert "scene = $4" in query
    assert args == ("crash_zoom_in", VIDEO_ID, TENANT, 12)
    assert "scene 12" in result
    assert "Crash Zoom In" in result
    assert "3 shot" in result


def test_camera_preset_runner_direct_catalog_id_also_resolves(monkeypatch):
    """If the classifier already learned a real id (e.g. from the presets
    endpoint), get_move() resolves it directly — the alias map is a
    fallback, not the only path."""
    writes = []

    async def fake_execute(query, *args):
        writes.append(args)
        return "UPDATE 1"

    monkeypatch.setattr(actions, "execute", fake_execute)
    asyncio.run(actions._runner_camera_preset(
        TENANT, VIDEO_ID, None, {"scene": 5, "change": "drone_orbit"}))
    assert writes[0][0] == "drone_orbit"


def test_camera_preset_runner_clears_back_to_auto(monkeypatch):
    writes = []

    async def fake_execute(query, *args):
        writes.append(args)
        return "UPDATE 2"

    monkeypatch.setattr(actions, "execute", fake_execute)
    result = asyncio.run(actions._runner_camera_preset(
        TENANT, VIDEO_ID, None, {"scene": 4, "change": "auto"}))
    assert writes[0] == (None, VIDEO_ID, TENANT, 4)
    assert "auto" in result.lower()


def test_camera_preset_runner_unrecognized_text_writes_nothing(monkeypatch):
    async def fail_execute(*a, **k):
        raise AssertionError("must not write an unrecognized move")
    monkeypatch.setattr(actions, "execute", fail_execute)
    result = asyncio.run(actions._runner_camera_preset(
        TENANT, VIDEO_ID, None, {"scene": 4, "change": "make it sparkle"}))
    assert "didn't recognize" in result.lower()


def test_camera_preset_runner_zero_rows_touched(monkeypatch):
    async def fake_execute(query, *args):
        return "UPDATE 0"
    monkeypatch.setattr(actions, "execute", fake_execute)
    result = asyncio.run(actions._runner_camera_preset(
        TENANT, VIDEO_ID, None, {"scene": 99, "change": "crash zoom"}))
    assert "doesn't have any shots" in result


def test_camera_preset_runner_is_tenant_scoped(monkeypatch):
    writes = []

    async def fake_execute(query, *args):
        writes.append(args)
        return "UPDATE 1"

    monkeypatch.setattr(actions, "execute", fake_execute)
    asyncio.run(actions._runner_camera_preset(
        OTHER_TENANT, VIDEO_ID, None, {"scene": 2, "change": "push in"}))
    assert writes[0][2] == OTHER_TENANT
