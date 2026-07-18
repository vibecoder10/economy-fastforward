"""Tests for the per-shot video-model router (checklist §1.2/C12,
tasks/storyengine-wiring-fix-checklist.md).

Two layers:

1. shared.model_router.route_shot_model() — pure unit tests over the C11
   decision-table fields (MODEL_REGISTRY.best_for/tier/wired). No network,
   no DB.
2. scripts.coverage_to_app.store_scene() — the shot-plan write path: proves
   routed_model/routing_reason from a frame dict actually land in the
   `assets` INSERT (migration 088 columns), and that model_used is never
   written by this path (stays NULL for C13 to fill in later). DB is a
   stub that captures INSERT args (module-stub pattern, mirrors
   tests/functional/test_dialogue_alignment.py and
   tests/functional/test_generation_ledger.py).

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_scene_model_routing.py -q
"""
import asyncio
import os
import sys
import types

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))

from shared.model_router import route_shot_model, RoutingDecision  # noqa: E402
from shared.channel_profile import MODEL_REGISTRY  # noqa: E402


# ---------------------------------------------------------------------------
# 1. route_shot_model() unit tests
# ---------------------------------------------------------------------------

def test_reveal_purpose_routes_to_hero_tier_model():
    decision = route_shot_model("REVEAL")
    assert isinstance(decision, RoutingDecision)
    assert decision.model_id == "veo-3.1-quality"
    assert MODEL_REGISTRY[decision.model_id].wired is True
    assert "hero" in MODEL_REGISTRY[decision.model_id].best_for
    assert "reveal" in decision.routing_reason.lower()
    assert "hero" in decision.routing_reason.lower()


def test_payoff_purpose_routes_to_hero_tier_model():
    decision = route_shot_model("PAYOFF")
    assert decision.model_id == "veo-3.1-quality"
    assert "payoff" in decision.routing_reason.lower()
    assert "hero" in decision.routing_reason.lower()


def test_establish_purpose_routes_to_atmospheric_tier_model():
    decision = route_shot_model("ESTABLISH")
    assert decision.model_id == "veo-3.1-fast"
    assert MODEL_REGISTRY[decision.model_id].wired is True
    assert "establish" in decision.routing_reason.lower()


def test_ordinary_static_shot_routes_to_cheap_draft_model():
    """An "ordinary" shot (STATIC — no camera-move purpose earned) must NOT
    get the premium/hero model — it routes to the draft/cheap tier, same
    model the pipeline already defaults to."""
    decision = route_shot_model("STATIC")
    assert decision.model_id == "grok-imagine"
    assert MODEL_REGISTRY[decision.model_id].tier == "draft"
    assert "draft" in decision.routing_reason.lower()


def test_none_or_unrecognized_purpose_treated_as_static():
    for purpose in (None, "", "SOME_UNKNOWN_PURPOSE"):
        decision = route_shot_model(purpose)
        assert decision.model_id == "grok-imagine", f"purpose={purpose!r}"


def test_only_ever_returns_a_wired_model():
    """Every purpose in the vocabulary (plus the multi-shot hint) must
    resolve to a model with wired=True — never one of the 3 dead registry
    entries (kling-3.0-pro, runway-gen4-turbo, hailuo-2.3-standard)."""
    for purpose in ("REVEAL", "PAYOFF", "ESTABLISH", "SCALE", "ISOLATION", "STATIC", None):
        decision = route_shot_model(purpose)
        assert MODEL_REGISTRY[decision.model_id].wired is True, (
            f"purpose={purpose!r} routed to unwired model {decision.model_id}")


def test_multi_shot_hint_routes_to_multi_shot_tier_model():
    decision = route_shot_model("STATIC", is_multi_shot=True)
    assert decision.model_id == "seedance-2-fast"
    assert "multi_shot" in MODEL_REGISTRY[decision.model_id].best_for
    assert "multi-shot" in decision.routing_reason.lower()


def test_fallback_path_never_raises_and_always_returns_a_reason():
    """Even a deliberately broken lookup (a tag with no wired match) must
    fall back to DEFAULT_VIDEO_MODEL with a readable reason, never raise."""
    import shared.model_router as model_router

    original = dict(model_router._PURPOSE_TAG)
    model_router._PURPOSE_TAG["REVEAL"] = "no_such_tag_in_any_profile"
    try:
        decision = route_shot_model("REVEAL")
        assert decision.model_id in MODEL_REGISTRY  # still a real, wired model (falls to draft)
        assert MODEL_REGISTRY[decision.model_id].wired is True
        assert decision.routing_reason  # never empty
    finally:
        model_router._PURPOSE_TAG.clear()
        model_router._PURPOSE_TAG.update(original)


# ---------------------------------------------------------------------------
# 2. store_scene() shot-plan write-path persistence
# ---------------------------------------------------------------------------

CAPTURED_ASSET_INSERTS: list[tuple] = []
CAPTURED_ASSET_INSERT_QUERIES: list[str] = []


async def _fake_execute(query: str, *args):
    if query.strip().startswith("DELETE FROM assets"):
        return "DELETE 0"
    if "INSERT INTO assets" in query:
        CAPTURED_ASSET_INSERTS.append(args)
        CAPTURED_ASSET_INSERT_QUERIES.append(query)
        return "INSERT 0 1"
    if "INSERT INTO generation_ledger" in query:
        return "INSERT 0 1"
    if "UPDATE videos SET total_cost" in query:
        return "UPDATE 1"
    raise AssertionError(f"unexpected query in fake db: {query}")


async def _fake_fetch_one(query: str, *args):
    return None


async def _fake_fetch_all(query: str, *args):
    return []


async def _fake_upload_bytes(data, path, content_type, tenant):
    return f"https://fake-storage.example/{path}"


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


async def _boom(*a, **k):
    raise AssertionError("pure tests must not touch runtime services")


_stub("database", execute=_fake_execute, fetch_one=_fake_fetch_one, fetch_all=_fake_fetch_all)
_stub("storage", upload_bytes=_fake_upload_bytes)
_stub("vault", get_secret=_boom)
_stub("kie_unified", get_text_client_for_tenant=_boom)

from scripts.coverage_to_app import store_scene  # noqa: E402

_ASSET_COLUMNS = [
    "id", "tenant_id", "video_id", "scene", "image_index", "sentence_index",
    "sentence_text", "image_prompt", "shot_type", "video_title", "aspect_ratio",
    "image_url", "drive_image_url", "hero_shot", "assigned_dialogue",
    "location_id", "camera_movement", "image_model", "routed_model", "routing_reason",
]


def _row_as_dict(args: tuple) -> dict:
    return dict(zip(_ASSET_COLUMNS, args))


def _reset():
    CAPTURED_ASSET_INSERTS.clear()
    CAPTURED_ASSET_INSERT_QUERIES.clear()


def _write_temp_frame_file(scratch_dir: str, name: str) -> str:
    path = os.path.join(scratch_dir, name)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\nfake-frame-bytes-for-test")
    return path


def test_store_scene_persists_routed_model_and_routing_reason(tmp_path):
    """The shot-plan write path: a frame dict carrying routed_model/
    routing_reason (as generate_coverage_frames() now sets them, mirroring
    camera_move) must land on the INSERTed assets row exactly, and
    model_used must NOT be set by this path (C13's job)."""
    _reset()
    master_path = _write_temp_frame_file(str(tmp_path), "master.png")
    frames = [
        {
            "role": "master", "shot_type": "MS", "description": "A reveal shot",
            "camera_move": "slow_zoom_in|REVEAL",
            "routed_model": "veo-3.1-quality",
            "routing_reason": "reveal scene → hero tier (premium)",
            "image_model": "gpt-image-2",
            "_path": master_path,
        },
    ]
    frames_by_moment = [("A dramatic reveal", frames, None, None)]

    n = asyncio.run(store_scene(
        vid="video-1", tenant="tenant-1", title="Test Video", aspect="16:9",
        scene=1, frames_by_moment=frames_by_moment, location_id=None,
    ))

    assert n == 1
    assert len(CAPTURED_ASSET_INSERTS) == 1
    row = _row_as_dict(CAPTURED_ASSET_INSERTS[0])
    assert row["routed_model"] == "veo-3.1-quality"
    assert row["routing_reason"] == "reveal scene → hero tier (premium)"
    # model_used (C13's column) is never written by this path — confirmed
    # against the actual query text, not just the row dict's key set.
    assert "model_used" not in CAPTURED_ASSET_INSERT_QUERIES[0]
    print("✅ test_store_scene_persists_routed_model_and_routing_reason")


def test_store_scene_leaves_routing_columns_null_when_frame_has_no_routing(tmp_path):
    """A frame with no routed_model/routing_reason (e.g. routing failed
    fail-soft at shot-plan time, or an older pre-C12 code path) inserts
    NULL for both — never a crash, never a fabricated value."""
    _reset()
    master_path = _write_temp_frame_file(str(tmp_path), "master2.png")
    frames = [
        {
            "role": "master", "shot_type": "WS", "description": "Static shot",
            "camera_move": "static",
            "image_model": "gpt-image-2",
            "_path": master_path,
            # no routed_model / routing_reason key at all
        },
    ]
    frames_by_moment = [("A static establishing beat", frames, None, None)]

    n = asyncio.run(store_scene(
        vid="video-2", tenant="tenant-1", title="Test Video 2", aspect="16:9",
        scene=1, frames_by_moment=frames_by_moment, location_id=None,
    ))

    assert n == 1
    row = _row_as_dict(CAPTURED_ASSET_INSERTS[0])
    assert row["routed_model"] is None
    assert row["routing_reason"] is None
    print("✅ test_store_scene_leaves_routing_columns_null_when_frame_has_no_routing")
