"""Tests for the per-shot video-model router (checklist §1.2/C12, §C13b,
tasks/storyengine-wiring-fix-checklist.md).

Two layers:

1. shared.model_router.route_shot_model() — pure unit tests over the C11
   decision-table fields (MODEL_REGISTRY.best_for/tier/wired) AND C13b's
   channel-style guardrail (MODEL_REGISTRY.styles + videos.render_style).
   No network, no DB.
2. scripts.coverage_to_app.store_scene() — the shot-plan write path: proves
   routed_model/routing_reason from a frame dict actually land in the
   `assets` INSERT (migration 088 columns), and that model_used is never
   written by this path (stays NULL for C13 to fill in later). DB is a
   stub that captures INSERT args (module-stub pattern, mirrors
   tests/functional/test_dialogue_alignment.py and
   tests/functional/test_generation_ledger.py).

C13b (Ryan, 2026-07-18) changed route_shot_model()'s DEFAULT behavior on
purpose: with no render_style passed, it now returns the video-level model
UNCHANGED (opt-out) instead of running the C12 purpose→tier cascade. Every
C12 test below that called route_shot_model()/plan_camera_moves() with no
style now explicitly passes render_style="realistic" to keep exercising
the tiered cascade — each such change is called out at the test.

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

from shared.model_router import route_shot_model, RoutingDecision, resolve_clip_model  # noqa: E402
from shared.channel_profile import MODEL_REGISTRY, DEFAULT_VIDEO_MODEL  # noqa: E402


# ---------------------------------------------------------------------------
# 1. route_shot_model() unit tests
#
# C13b CHANGED THE DEFAULT (checklist §C13b): route_shot_model() with no
# render_style now returns the video-level model UNCHANGED (see section 1c
# below), instead of running the C12 purpose→tier cascade. Every test below
# that exercises the cascade itself now explicitly passes render_style=
# "realistic" or "animated" — noted per-test.
# ---------------------------------------------------------------------------

def test_reveal_purpose_routes_to_hero_tier_model():
    """CHANGED for C13b: without a declared style this would now hit the
    opt-out default (section 1c) — render_style="realistic" is added so
    this still exercises the C12 purpose→tier cascade."""
    decision = route_shot_model("REVEAL", render_style="realistic")
    assert isinstance(decision, RoutingDecision)
    assert decision.model_id == "veo-3.1-quality"
    assert MODEL_REGISTRY[decision.model_id].wired is True
    assert "hero" in MODEL_REGISTRY[decision.model_id].best_for
    assert "reveal" in decision.routing_reason.lower()
    assert "hero" in decision.routing_reason.lower()


def test_payoff_purpose_routes_to_hero_tier_model():
    """CHANGED for C13b: render_style="realistic" added, same reason as
    test_reveal_purpose_routes_to_hero_tier_model above."""
    decision = route_shot_model("PAYOFF", render_style="realistic")
    assert decision.model_id == "veo-3.1-quality"
    assert "payoff" in decision.routing_reason.lower()
    assert "hero" in decision.routing_reason.lower()


def test_establish_purpose_routes_to_atmospheric_tier_model():
    """CHANGED for C13b: render_style="realistic" added, same reason."""
    decision = route_shot_model("ESTABLISH", render_style="realistic")
    assert decision.model_id == "veo-3.1-fast"
    assert MODEL_REGISTRY[decision.model_id].wired is True
    assert "establish" in decision.routing_reason.lower()


def test_ordinary_static_shot_routes_to_cheap_draft_model():
    """CHANGED for C13b: render_style="animated" added — Grok is the only
    wired model in the animated palette AND the only one tagged "draft", so
    this is now the render_style that actually exercises the draft-tier
    fallback (the realistic palette has no draft-tagged model at all: every
    realistic-tagged wired entry is standard/premium tier — see section 1c's
    test_realistic_style_static_has_no_draft_tier_match for that case).

    An "ordinary" shot (STATIC — no camera-move purpose earned) on an
    animated channel must NOT get bumped to a premium/hero pick — it still
    routes to the draft/cheap tier, same model the pipeline already
    defaults to."""
    decision = route_shot_model("STATIC", render_style="animated")
    assert decision.model_id == "grok-imagine"
    assert MODEL_REGISTRY[decision.model_id].tier == "draft"
    assert "draft" in decision.routing_reason.lower()


def test_none_or_unrecognized_purpose_treated_as_static():
    """CHANGED for C13b: render_style="animated" added so this still
    exercises "unrecognized purpose falls through like STATIC" instead of
    trivially hitting the no-style opt-out default for an unrelated reason."""
    for purpose in (None, "", "SOME_UNKNOWN_PURPOSE"):
        decision = route_shot_model(purpose, render_style="animated")
        assert decision.model_id == "grok-imagine", f"purpose={purpose!r}"


def test_only_ever_returns_a_wired_model():
    """CHANGED for C13b: render_style="realistic" added. Every purpose in
    the vocabulary (plus the multi-shot hint) must resolve to a model with
    wired=True — never one of the 3 dead registry entries (kling-3.0-pro,
    runway-gen4-turbo, hailuo-2.3-standard)."""
    for purpose in ("REVEAL", "PAYOFF", "ESTABLISH", "SCALE", "ISOLATION", "STATIC", None):
        decision = route_shot_model(purpose, render_style="realistic")
        assert MODEL_REGISTRY[decision.model_id].wired is True, (
            f"purpose={purpose!r} routed to unwired model {decision.model_id}")


def test_multi_shot_hint_routes_to_multi_shot_tier_model():
    """CHANGED for C13b: render_style="realistic" added (Seedance's
    multi_shot tag only fires within the realistic palette now)."""
    decision = route_shot_model("STATIC", is_multi_shot=True, render_style="realistic")
    assert decision.model_id == "seedance-2-fast"
    assert "multi_shot" in MODEL_REGISTRY[decision.model_id].best_for
    assert "multi-shot" in decision.routing_reason.lower()


def test_fallback_path_never_raises_and_always_returns_a_reason():
    """CHANGED for C13b: render_style="realistic" added so the corrupted
    _PURPOSE_TAG lookup actually gets exercised (with no style at all this
    would hit the opt-out default before ever consulting _PURPOSE_TAG).
    Even a deliberately broken lookup (a tag with no wired+styled match)
    must fall back to a real model with a readable reason, never raise."""
    import shared.model_router as model_router

    original = dict(model_router._PURPOSE_TAG)
    model_router._PURPOSE_TAG["REVEAL"] = "no_such_tag_in_any_profile"
    try:
        decision = route_shot_model("REVEAL", render_style="realistic")
        assert decision.model_id in MODEL_REGISTRY  # still a real, wired model
        assert MODEL_REGISTRY[decision.model_id].wired is True
        assert decision.routing_reason  # never empty
    finally:
        model_router._PURPOSE_TAG.clear()
        model_router._PURPOSE_TAG.update(original)


# ---------------------------------------------------------------------------
# 1c. C13b channel-style routing guardrail — Ryan's 2026-07-18 product rule:
# the video's LOOK gates model choice BEFORE scene importance does. See
# shared/model_router.py::route_shot_model's docstring for the full cascade.
# ---------------------------------------------------------------------------

def test_render_style_none_returns_video_level_model_unchanged():
    """The money-safe default: EVERY video today has render_style=NULL. The
    router must not upgrade a scene's tier just because it earned "hero" —
    it hands back the video's own model, verbatim, with an opt-out reason."""
    for purpose in ("REVEAL", "PAYOFF", "ESTABLISH", "STATIC", None):
        decision = route_shot_model(purpose, video_model_id="veo-3.1-fast")
        assert decision.model_id == "veo-3.1-fast", f"purpose={purpose!r}"
        assert decision.routing_reason == "channel style not set — using channel default"


def test_render_style_none_falls_back_to_default_video_model_when_no_video_model_given():
    decision = route_shot_model("REVEAL")  # no render_style, no video_model_id
    assert decision.model_id == DEFAULT_VIDEO_MODEL
    assert decision.routing_reason == "channel style not set — using channel default"


def test_animated_style_never_routes_to_realistic_models_even_for_hero_purposes():
    """The headline guardrail case: an animated channel (Poco a Poco —
    ElevenLabs voice-over + Grok animation) must NEVER get recommended
    veo-3.1-quality/veo-3.1-fast/seedance-2-fast — all realistic-only —
    even for a REVEAL/PAYOFF shot that would earn the "hero" tag on a
    realistic channel. It falls through to Grok, the only wired model in
    the animated palette, with a reason naming the channel's style."""
    for purpose in ("REVEAL", "PAYOFF"):
        decision = route_shot_model(purpose, render_style="animated")
        assert decision.model_id == "grok-imagine", f"purpose={purpose!r}"
        assert decision.model_id not in (
            "veo-3.1-quality", "veo-3.1-fast", "seedance-2-fast")
        assert "animated" in decision.routing_reason.lower()
        assert purpose.lower() in decision.routing_reason.lower()


def test_realistic_style_multi_shot_routes_to_seedance_palette_pick():
    """Realistic channel + a multi-shot sequence routes to Seedance (the
    only wired model both tagged multi_shot AND styled "realistic")."""
    decision = route_shot_model("STATIC", is_multi_shot=True, render_style="realistic")
    assert decision.model_id == "seedance-2-fast"
    assert "realistic" in decision.routing_reason.lower()


def test_realistic_style_reveal_routes_to_veo_quality():
    """Realistic channel + REVEAL still earns the hero-tier pick (Veo
    Quality) — the guardrail filters by style, it doesn't disable the C12
    cascade for a channel that DID declare a matching style."""
    decision = route_shot_model("REVEAL", render_style="realistic")
    assert decision.model_id == "veo-3.1-quality"
    assert "realistic" in decision.routing_reason.lower()


def test_realistic_style_static_has_no_draft_tier_match():
    """No wired model is BOTH styles=['realistic', ...] AND best_for
    includes 'draft' (Grok is the only draft-tagged model, and it's
    animated-only) — an ordinary/STATIC shot on a realistic channel falls
    all the way through to the true final fallback (video-level model),
    not a fabricated draft pick. Proves the cascade doesn't silently cross
    styles to find a tag match."""
    decision = route_shot_model("STATIC", render_style="realistic", video_model_id="veo-3.1-fast")
    assert decision.model_id == "veo-3.1-fast"
    assert "realistic" in decision.routing_reason.lower()


def test_style_with_no_wired_match_falls_back_to_video_level_model():
    """A render_style value nothing in the registry is tagged with (e.g. a
    future/typo'd style) must not crash or silently pick an unrelated
    model — it falls back to the video-level model with a reason naming
    the unmatched style."""
    decision = route_shot_model("REVEAL", render_style="claymation", video_model_id="grok-imagine")
    assert decision.model_id == "grok-imagine"
    assert "claymation" in decision.routing_reason.lower()
    assert "no wired model" in decision.routing_reason.lower()


def test_render_style_is_case_and_whitespace_insensitive():
    a = route_shot_model("REVEAL", render_style="Animated")
    b = route_shot_model("REVEAL", render_style="  animated  ")
    c = route_shot_model("REVEAL", render_style="animated")
    assert a.model_id == b.model_id == c.model_id == "grok-imagine"


def test_every_wired_model_declares_at_least_one_style():
    """C13b data-completeness check: every wired registry entry must carry
    a non-empty styles list, or the guardrail could silently exclude a
    real, live model from every possible recommendation."""
    for model_id, profile in MODEL_REGISTRY.items():
        if profile.wired:
            assert profile.styles, f"{model_id}: wired model has no styles tagged"


# ---------------------------------------------------------------------------
# 1b. resolve_clip_model() — the C13 READ side of C12's write-only column.
# Pure, no DB — the precedence a real clip-generation call makes per row.
# ---------------------------------------------------------------------------

def test_resolve_clip_model_prefers_wired_routed_model_over_video_level():
    """A wired routed_model wins over the video-level model — a scene
    routed to Veo Quality animates via Veo even on a Grok-default video."""
    picked = resolve_clip_model("veo-3.1-quality", "grok-imagine")
    assert picked == "veo-3.1-quality"


def test_resolve_clip_model_null_routed_falls_back_to_video_level_unchanged():
    """The core C13 money invariant: a NULL routed_model (every asset row
    that predates C12, or any row whose shot-plan-time routing try/except
    tripped) must return the video-level model UNCHANGED — byte-identical
    to what clip generation did before this function existed."""
    assert resolve_clip_model(None, "grok-imagine") == "grok-imagine"
    assert resolve_clip_model(None, "veo-3.1-fast") == "veo-3.1-fast"


def test_resolve_clip_model_unknown_or_unwired_routed_falls_back():
    """An unrecognized model id, or a REGISTRY entry that exists but is
    wired=False (kling-3.0-pro has no live generation path), must fall
    back exactly like NULL — never attempt a dead generation path."""
    assert MODEL_REGISTRY["kling-3.0-pro"].wired is False  # pin the fixture's premise
    assert resolve_clip_model("kling-3.0-pro", "grok-imagine") == "grok-imagine"
    assert resolve_clip_model("some-made-up-model-id", "grok-imagine") == "grok-imagine"


def test_resolve_clip_model_scene_override_wins_over_routed_model():
    """The C14 seam: an explicit per-scene override (no column writes it
    yet, but the parameter exists) outranks routed_model when both are
    wired."""
    picked = resolve_clip_model("veo-3.1-fast", "grok-imagine", scene_override="veo-3.1-quality")
    assert picked == "veo-3.1-quality"


def test_resolve_clip_model_unwired_scene_override_falls_through_to_routed():
    """An override that names an unwired/unknown model must not win just
    because it's an override — it falls through to the next candidate
    exactly like an unwired routed_model would."""
    picked = resolve_clip_model("veo-3.1-fast", "grok-imagine", scene_override="kling-3.0-pro")
    assert picked == "veo-3.1-fast"


def test_resolve_clip_model_falls_back_to_default_when_video_level_empty():
    """Belt-and-braces floor: an empty/falsy video_model_id (shouldn't
    happen — callers already resolve DEFAULT_VIDEO_MODEL upstream — but
    resolve_clip_model must not hand back an empty string)."""
    assert resolve_clip_model(None, "") == DEFAULT_VIDEO_MODEL
    assert resolve_clip_model(None, None) == DEFAULT_VIDEO_MODEL  # type: ignore[arg-type]


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
