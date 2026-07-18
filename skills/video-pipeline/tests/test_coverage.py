"""Self-check for the coverage directive parser.

Run: python skills/video-pipeline/tests/test_coverage.py   (or via pytest)
"""
import asyncio
import os
import sys

_PIPELINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PIPELINE_ROOT)
sys.path.insert(0, os.path.join(_PIPELINE_ROOT, "storyboard"))
# plan_camera_moves() -> camera_selector.resolve_purpose() does a bare
# `import animation_prompt_engine` (image_prompts/animation_prompt_engine.py) —
# in production this resolves because pipeline_executor.py has already added
# every bot subdir (including image_prompts) to sys.path by the time
# coverage.py runs in-process. A standalone test needs the same subdir added.
sys.path.append(os.path.join(_PIPELINE_ROOT, "image_prompts"))

from storyboard.coverage import (  # noqa: E402
    parse_coverage, cast_prompt_from_story_bible, generate_coverage_frames,
    plan_camera_moves,
)

SAMPLE = """\
Here is the coverage plan.

[MOMENT 1 | the rider mounts the dragon at dawn]
- MASTER [WS]: Wide shot, the young rider in a leather flight harness stands beside the bronze dragon on a cliff ledge, dawn light raking from screen-left.
- ANGLE [MCU]: Medium close-up on the rider's face, jaw set, eyes on the horizon — same dawn light, same harness.
- ANGLE [INSERT]: Insert of gloved hands gripping the saddle horn, scales catching the amber light.

[MOMENT 2 | the dragon launches off the cliff]
- MASTER [ELS]: Extreme long shot, the dragon drops off the ledge into the valley, wings snapping open.
- ANGLE [OTS]: Over-the-shoulder from behind the rider, the valley rushing up to meet them.
"""


def test_parses_two_moments():
    moments = parse_coverage(SAMPLE)
    assert len(moments) == 2, f"expected 2 moments, got {len(moments)}"

    m1 = moments[0]
    assert m1["moment_number"] == 1
    assert m1["master"]["shot_type"] == "WS"
    assert "flight harness" in m1["master"]["description"]
    assert len(m1["angles"]) == 2
    assert [a["shot_type"] for a in m1["angles"]] == ["MCU", "INSERT"]

    m2 = moments[1]
    assert m2["master"]["shot_type"] == "ELS"
    assert [a["shot_type"] for a in m2["angles"]] == ["OTS"]


def test_parses_no_bracket_and_multiword_shot_types():
    # The LLM often writes shot types without brackets, sometimes two words.
    sample = (
        "[MOMENT 1 | the launch]\n"
        "- MASTER WS: wide of the launch off the ledge.\n"
        "- ANGLE MCU: closer on the rider, same instant.\n"
        "- ANGLE INSERT ECU: extreme close on the wingtip.\n"
    )
    moments = parse_coverage(sample)
    assert len(moments) == 1
    assert moments[0]["master"]["shot_type"] == "WS"
    assert [a["shot_type"] for a in moments[0]["angles"]] == ["MCU", "INSERT ECU"]


def test_drops_moment_with_no_angles():
    # A lone master with no angles is not coverage — it must be dropped.
    only_master = "[MOMENT 1 | x]\n- MASTER [WS]: just a master, no angles here.\n"
    assert parse_coverage(only_master) == []


class _Profile:
    visual_style_directive = "Photoreal cinematic CG."


def test_cast_prompt_from_bible():
    bible = {"characters": [
        {"id": "the_rider", "costume": "tan leather flight harness, crimson sash"},
        {"id": "bronze_dragon", "description": "horse-sized bronze dragon, tattered left wingtip"},
    ]}
    p = cast_prompt_from_story_bible(bible, _Profile())
    assert p and "THE RIDER" in p and "BRONZE DRAGON" in p
    assert "crimson sash" in p and "tattered left wingtip" in p
    # nothing to build from -> None (caller must supply a cast_url/cast_prompt)
    assert cast_prompt_from_story_bible(None, _Profile()) is None
    assert cast_prompt_from_story_bible({"characters": []}, _Profile()) is None


class _FakeImageClientForFrames:
    """Records every frame-draw call; only the z-image path is exercised (no GPT
    fallback expected when it succeeds every time)."""
    SCENE_MODEL = "nano-banana-2"

    def __init__(self):
        self.calls = []

    async def generate_scene_image_zimage(self, prompt, aspect_ratio="16:9"):
        self.calls.append(("generate_scene_image_zimage", prompt, aspect_ratio))
        return {"url": f"https://img/{len(self.calls)}.png"}


def test_generate_coverage_frames_honors_model_override():
    """Bulk-path integration proof (checklist §0.1): generate_coverage_for_video ->
    run_coverage -> generate_coverage_frames -> _gen_ref must reach the SAME
    shared.clients.image_model_router resolver as coverage_to_app.py's other 3 call
    sites, given the video's image_model_override — this was the gap the first C02
    pass left open (the bulk 'Generate all pictures' button still hardcoded GPT)."""
    moment = {
        "moment_number": 1,
        "master": {"shot_type": "WS", "description": "wide shot of the rider at dawn"},
        "angles": [{"shot_type": "MCU", "description": "close on the rider's face"}],
    }
    ic = _FakeImageClientForFrames()
    frames = asyncio.run(generate_coverage_frames(
        moment, "https://cast.png", ic, None,
        aspect="16:9", resolution="1K", model_override="z-image"))
    assert frames is not None
    assert len(frames) == 2, "expected master + 1 angle"
    # Every frame recorded the model that ACTUALLY drew it — the truth store_scene
    # persists onto assets.image_model for the badge.
    assert [fr["image_model"] for fr in frames] == ["z-image", "z-image"]
    # Both draws went through z-image, never fell back to GPT.
    assert [c[0] for c in ic.calls] == ["generate_scene_image_zimage", "generate_scene_image_zimage"]


def test_generate_coverage_frames_propagates_routed_model_and_routing_reason():
    """C12 (checklist §1.2): plan_camera_moves() stamps routed_model/
    routing_reason onto the shot dict alongside camera_move; this proves
    generate_coverage_frames carries BOTH through to the output frame dict
    exactly like it already does for camera_move — the same path
    store_scene() later reads to persist them onto the assets row."""
    moment = {
        "moment_number": 1,
        "master": {
            "shot_type": "WS", "description": "wide shot of the rider at dawn",
            "camera_move": "arc_in|REVEAL",
            "routed_model": "veo-3.1-quality",
            "routing_reason": "reveal scene → hero tier (premium)",
        },
        "angles": [{
            "shot_type": "MCU", "description": "close on the rider's face",
            "camera_move": "static",
            "routed_model": "grok-imagine",
            "routing_reason": "ordinary scene → draft tier (draft)",
        }],
    }
    ic = _FakeImageClientForFrames()
    frames = asyncio.run(generate_coverage_frames(
        moment, "https://cast.png", ic, None, aspect="16:9", resolution="1K",
        model_override="z-image"))
    assert frames is not None and len(frames) == 2
    master, angle = frames
    assert master["routed_model"] == "veo-3.1-quality"
    assert master["routing_reason"] == "reveal scene → hero tier (premium)"
    assert angle["routed_model"] == "grok-imagine"
    assert angle["routing_reason"] == "ordinary scene → draft tier (draft)"


def test_plan_camera_moves_stamps_routed_model_on_shots():
    """The actual shot-plan-time integration point: plan_camera_moves()
    (called BEFORE any frame is drawn) must stamp routed_model/
    routing_reason on every shot, matching what shared.model_router.
    route_shot_model() would return for that shot's resolved purpose."""
    from shared.model_router import route_shot_model

    moments = [{
        "summary": "The detective pulls back the curtain to reveal the truth",
        "master": {
            "shot_type": "MS",
            "description": "The detective pulls back the curtain to reveal the truth",
        },
        "angles": [],
        "speaker": None, "line": None,
    }]
    planned = plan_camera_moves(moments)
    shot = moments[0]["master"]
    assert "routed_model" in shot, "routing must be stamped at shot-plan time"
    assert "routing_reason" in shot
    assert shot["routed_model"] in ("veo-3.1-quality", "veo-3.1-fast", "grok-imagine", "seedance-2-fast")
    # Whatever purpose the camera engine actually resolved for this shot,
    # the router's own decision for that purpose must match exactly — no
    # second, drifting copy of the routing logic lives in coverage.py.
    resolved_purpose = shot["camera_move"].split("|")[1] if shot["camera_move"] != "static" else "STATIC"
    expected = route_shot_model(resolved_purpose)
    assert shot["routed_model"] == expected.model_id
    assert shot["routing_reason"] == expected.routing_reason


def test_plan_camera_moves_camera_move_unaffected_when_routing_fails():
    """Fail-soft guarantee (checklist §1.2/C12): if route_shot_model() throws,
    the shot plan must still succeed EXACTLY as before this feature existed —
    camera_move still gets assigned normally, only routed_model/routing_reason
    stay unset for that shot."""
    import shared.model_router as model_router

    moments = [{
        "summary": "The detective pulls back the curtain to reveal the truth",
        "master": {
            "shot_type": "MS",
            "description": "The detective pulls back the curtain to reveal the truth",
        },
        "angles": [],
        "speaker": None, "line": None,
    }]

    original = model_router.route_shot_model

    def _boom(*a, **k):
        raise RuntimeError("simulated router failure")

    model_router.route_shot_model = _boom
    try:
        planned = plan_camera_moves(moments)
    finally:
        model_router.route_shot_model = original

    shot = moments[0]["master"]
    # Camera plan unaffected: still gets a real move (or "static"), same as
    # it would with no routing feature at all.
    assert shot.get("camera_move"), "camera_move must still be set when routing fails"
    assert "routed_model" not in shot
    assert "routing_reason" not in shot


if __name__ == "__main__":
    test_parses_two_moments()
    test_parses_no_bracket_and_multiword_shot_types()
    test_drops_moment_with_no_angles()
    test_cast_prompt_from_bible()
    test_generate_coverage_frames_honors_model_override()
    test_generate_coverage_frames_propagates_routed_model_and_routing_reason()
    test_plan_camera_moves_stamps_routed_model_on_shots()
    test_plan_camera_moves_camera_move_unaffected_when_routing_fails()
    print("ok — coverage parser + cast-builder self-checks passed")
