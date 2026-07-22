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
    plan_camera_moves, _coverage_system_prompt, _setup_base_id,
    enforce_setup_variety, assign_setup_anchors,
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
    route_shot_model() would return for that shot's resolved purpose.

    CHANGED for C13b (checklist §C13b): plan_camera_moves() is called with
    an explicit render_style/video_model_id here — with neither passed
    (the old call shape), route_shot_model()'s new opt-out default would
    make every shot's routed_model equal DEFAULT_VIDEO_MODEL regardless of
    purpose, making the cross-check below vacuous. Passing render_style
    keeps this test proving what it always proved: coverage.py holds no
    second, drifting copy of the routing logic."""
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
    planned = plan_camera_moves(moments, render_style="realistic", video_model_id="veo-3.1-fast")
    shot = moments[0]["master"]
    assert "routed_model" in shot, "routing must be stamped at shot-plan time"
    assert "routing_reason" in shot
    assert shot["routed_model"] in ("veo-3.1-quality", "veo-3.1-fast", "grok-imagine", "seedance-2-fast")
    # Whatever purpose the camera engine actually resolved for this shot,
    # the router's own decision for that purpose must match exactly — no
    # second, drifting copy of the routing logic lives in coverage.py.
    resolved_purpose = shot["camera_move"].split("|")[1] if shot["camera_move"] != "static" else "STATIC"
    expected = route_shot_model(resolved_purpose, render_style="realistic", video_model_id="veo-3.1-fast")
    assert shot["routed_model"] == expected.model_id
    assert shot["routing_reason"] == expected.routing_reason


def test_plan_camera_moves_no_style_stamps_video_level_model_unchanged():
    """NEW for C13b: the default call shape (no render_style/video_model_id
    — every existing caller besides generate_coverage_for_video) must stamp
    the opt-out reason, never a tier-upgraded pick, on every shot."""
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
    assert shot["routed_model"] == "grok-imagine"  # DEFAULT_VIDEO_MODEL floor, no video_model_id given
    assert shot["routing_reason"] == "channel style not set — using channel default"


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


# ---------------------------------------------------------------------------
# C1: scene move budget (plan_camera_moves is the only place that sees a
# scene's WHOLE ordered shot list, so it's the only place a per-scene cap can
# be enforced — see its docstring for the full rationale).
# ---------------------------------------------------------------------------

def _reveal_scene(n=5, final_reveals=True):
    """n single-master moments, each earning a REVEAL move via GENUINE
    narrative language (never boilerplate) — this exercises the budget logic
    in isolation from the C1 classifier-diet fix. Mirrors the real shape of
    the bug: the per-shot selector knows nothing about its siblings, so left
    unchecked it rotates through the REVEAL move family (pull-back/
    lateral-pan/tilt-up/tilt-down/static/push-in/orbital legacy keys) on
    every shot in the scene.

    final_reveals=False makes the LAST shot's narrative calm (no reveal
    language) — used to prove the budget's "otherwise the first earned"
    tie-break branch (no scene-final shot earned a move)."""
    moments = []
    for i in range(1, n + 1):
        calm_final = (not final_reveals) and i == n
        beat = "talks quietly about the weather" if calm_final else (
            f"reveals what's hidden behind panel {i}")
        moments.append({
            "moment_number": i,
            "summary": f"Marcus {beat}",
            "master": {
                "shot_type": "MS",
                "description": f"Marcus {beat}, in the kitchen with Vanessa nearby.",
            },
            "angles": [],
            "speaker": None, "line": None,
        })
    return moments


def _camera_moves(moments):
    return [m["master"]["camera_move"] for m in moments]


def test_scene_move_budget_defaults_to_one_earned_move():
    """5 shots that would each individually earn a REVEAL move must end with
    exactly 1 non-static camera_move — the default SE_SCENE_MOVE_BUDGET.
    Downgraded shots restore their ORIGINAL (un-composed) description — no
    leaked 'Composed for a ... camera move' tail on a shot that ships static."""
    moments = _reveal_scene(5)
    originals = [m["master"]["description"] for m in moments]
    os.environ.pop("SE_SCENE_MOVE_BUDGET", None)
    planned = plan_camera_moves(moments)
    moves = _camera_moves(moments)
    non_static = [mv for mv in moves if mv != "static"]
    assert len(non_static) == 1, f"expected 1 earned move, got {moves}"
    assert planned == 1
    for m, orig in zip(moments, originals):
        if m["master"]["camera_move"] == "static":
            assert m["master"]["description"] == orig


def test_scene_move_budget_env_var_tunable():
    """SE_SCENE_MOVE_BUDGET=2 raises the cap to 2 earned moves for the same
    scene, read at CALL time so this override needs no reload/import dance."""
    moments = _reveal_scene(5)
    os.environ["SE_SCENE_MOVE_BUDGET"] = "2"
    try:
        planned = plan_camera_moves(moments)
    finally:
        os.environ.pop("SE_SCENE_MOVE_BUDGET", None)
    moves = _camera_moves(moments)
    non_static = [mv for mv in moves if mv != "static"]
    assert len(non_static) == 2, f"expected 2 earned moves, got {moves}"
    assert planned == 2


def test_scene_move_budget_prefers_scene_final_shot():
    """Tie-break (documented in plan_camera_moves): when more shots earn a
    move than the budget allows, the scene's FINAL shot (the climactic/
    PAYOFF-tier beat) keeps the move over every earlier earned shot."""
    moments = _reveal_scene(5)
    os.environ.pop("SE_SCENE_MOVE_BUDGET", None)
    plan_camera_moves(moments)
    moves = _camera_moves(moments)
    assert moves[-1] != "static", "the scene-final shot should keep the budget's one move"
    assert all(mv == "static" for mv in moves[:-1]), moves


def test_scene_move_budget_falls_back_to_first_earned_when_none_scene_final():
    """When the scene's FINAL shot doesn't earn a move, the budget keeps the
    FIRST earned shot instead (the tie-break's documented 'otherwise' branch)."""
    moments = _reveal_scene(5, final_reveals=False)  # last shot: calm, no reveal language
    os.environ.pop("SE_SCENE_MOVE_BUDGET", None)
    plan_camera_moves(moments)
    moves = _camera_moves(moments)
    assert moves[-1] == "static", "final shot has no reveal language — must not earn a move"
    earned = [i for i, mv in enumerate(moves) if mv != "static"]
    assert earned == [0], f"expected only the first earned shot to keep the move, got {earned} ({moves})"


# ---------------------------------------------------------------------------
# C2: shot-size grammar — setup-kit scaling, size-variant compound setups,
# consecutive-repeat cap, tension-driven sizing.
# ---------------------------------------------------------------------------

def test_setup_base_id_derivation():
    """(a) base-letter derivation: a size-variant compound id like 'B-CU'
    resolves to its BASE family 'B' for anchor purposes; a plain id and a
    hyphen-free 'weird' id pass through unchanged; None is None-safe."""
    assert _setup_base_id("B-CU") == "B"
    assert _setup_base_id("D-B") == "D"  # multi-token compound: keep only the first token
    assert _setup_base_id("B") == "B"
    assert _setup_base_id("WEIRD123") == "WEIRD123"
    assert _setup_base_id(None) is None


class _FakeImageClientRecordingRefs:
    """Records prompt+refs for every reference-aware (nano-banana-2) draw
    call so a test can assert exactly which reference URLs a shot attached —
    used to prove a setup-anchor frame actually reaches a size-variant
    shot's draw call (C2 item 2), not just that the bookkeeping dict holds
    the right key."""

    def __init__(self):
        self.calls = []  # [(prompt, refs)]

    async def generate_with_reference(self, prompt, refs, aspect_ratio="16:9",
                                       task_id_out=None, fail_info_out=None):
        self.calls.append((prompt, list(refs)))
        return {"url": f"https://img/{len(self.calls)}.png"}


def test_setup_anchor_ownership_and_size_variant_sharing():
    """(b) anchor ownership: the FIRST-planned shot of a base setup family
    owns that family's anchor future; a later size-variant shot (B-CU)
    never owns its own — it awaits and attaches the family owner's landed
    frame as an extra reference, proving B-CU shares SETUP B's background
    anchor instead of starting an unmatched room."""
    moments = [
        {"moment_number": 1,
         "master": {"shot_type": "WS",
                    "description": "(SETUP B) wide two-shot establishing the kitchen."},
         "angles": []},
        {"moment_number": 2,
         "master": {"shot_type": "CU",
                    "description": "(SETUP B-CU) tighter on the same axis, punching in."},
         "angles": []},
    ]

    async def _run():
        setup_anchors = assign_setup_anchors(moments)
        # Ownership: plan-order-first shot of family B owns it, whatever its variant.
        assert moments[0]["master"]["setup_base_id"] == "B"
        assert moments[1]["master"]["setup_base_id"] == "B"
        assert moments[0]["master"].get("setup_anchor_owner") is True
        assert not moments[1]["master"].get("setup_anchor_owner")
        assert list(setup_anchors.keys()) == ["B"]  # one shared future for the whole family

        ic = _FakeImageClientRecordingRefs()
        owner_frames = await generate_coverage_frames(
            moments[0], "https://cast.png", ic, None, aspect="16:9", resolution="1K",
            model_override="nano-banana-2", setup_anchors=setup_anchors)
        variant_frames = await generate_coverage_frames(
            moments[1], "https://cast.png", ic, None, aspect="16:9", resolution="1K",
            model_override="nano-banana-2", setup_anchors=setup_anchors)

        assert owner_frames and variant_frames
        owner_url = owner_frames[0]["url"]
        # The owner's draw call carries no setup-anchor ref (it's the first of its family).
        owner_prompt, owner_refs = ic.calls[0]
        assert owner_url not in owner_refs
        # The future resolved to the owner's landed frame.
        assert setup_anchors["B"].result() == owner_url
        # The B-CU variant's draw call attached the OWNER's landed frame as a ref.
        variant_prompt, variant_refs = ic.calls[1]
        assert owner_url in variant_refs
    asyncio.run(_run())


def _flat(*families_and_roles):
    """Build a minimal flat_shots list from (family, role) pairs, e.g.
    _flat(('A', 'master'), ('B', 'angle'), ...) — each shot gets a synthetic
    "(SETUP <family>) ..." description so enforce_setup_variety's real
    description-tag parsing is exercised, matching production."""
    return [{"shot_type": "MS", "role": role,
             "description": f"(SETUP {fam}) placeholder shot {i}."}
            for i, (fam, role) in enumerate(families_and_roles)]


def test_enforce_setup_variety_flags_three_in_a_row():
    """(c) consecutive cap: 3 same-family shots in a row (all masters, so no
    safe angle swap exists) is a violation that gets FLAGGED — left in place
    since masters are never swap candidates — and the count reflects exactly
    the 1 shot beyond the cap of 2."""
    flat = _flat(("B", "master"), ("B", "master"), ("B", "master"))
    n = enforce_setup_variety(flat)
    assert n == 1
    # Nothing swappable existed (all masters) — content is untouched.
    assert [s["description"] for s in flat] == [
        "(SETUP B) placeholder shot 0.", "(SETUP B) placeholder shot 1.",
        "(SETUP B) placeholder shot 2."]


def test_enforce_setup_variety_size_variant_counts_as_same_family():
    """(c) B, B-CU, B counts as 3 consecutive shots of the SAME family (a
    same-axis size change still reads as one setup) — exactly like B,B,B."""
    flat = _flat(("B", "master"), ("B-CU", "angle"), ("B", "master"))
    n = enforce_setup_variety(flat)
    assert n == 1, "the size-variant middle shot must not reset the run"


def test_enforce_setup_variety_fixes_with_a_safe_angle_swap():
    """(c) when the offending 3rd shot is an ANGLE and a different-family
    angle exists elsewhere, enforce_setup_variety swaps their content in
    place (never touching either MASTER), actually breaking the run."""
    flat = _flat(("B", "master"), ("B", "angle"), ("B", "angle"), ("C", "angle"))
    n = enforce_setup_variety(flat)
    assert n == 1
    # Position 2 (the 3rd same-family shot, an angle) swapped with position 3
    # (the nearest different-family angle) — content moved, not the master.
    assert flat[2]["description"] == "(SETUP C) placeholder shot 3."
    assert flat[3]["description"] == "(SETUP B) placeholder shot 2."
    assert flat[0]["description"] == "(SETUP B) placeholder shot 0."  # master untouched


def test_setup_target_scales_with_max_moments():
    """(d) the [SETUPS | ...] prompt guidance carries a setup-count target
    that scales with the scene-size knobs (roughly one setup per 6-8 shots),
    floored at 3 for a tiny scene, and grows for a bigger one."""
    from shared.channel_profile import load_profile
    profile = load_profile({})
    small = _coverage_system_prompt(profile, max_moments=3, angles_min=0, angles_max=2)
    big = _coverage_system_prompt(profile, max_moments=20, angles_min=2, angles_max=4)

    import re
    small_target = int(re.search(r"aim for about (\d+) setups", small).group(1))
    big_target = int(re.search(r"aim for about (\d+) setups", big).group(1))
    assert small_target == 3, "tiny scene must hit the floor of 3"
    assert big_target > small_target, "a longer scene must earn a bigger kit"
    # The output_format line restates the SAME number, not an independent guess.
    assert f"aim for roughly {big_target} setups" in big


def test_tension_sizing_guidance_present_in_user_prompt():
    """(d)-adjacent: the dialogue-turn block teaches tighter framing/size-
    variant setups as turns progress, using the turn index as the signal."""
    from storyboard.coverage import _coverage_user_prompt
    beat = "Dad: Hello there.\nMom: Hi honey.\nDad: How was your day?\n"
    prompt = _coverage_user_prompt(beat, "Test", None, [], [])
    assert "SIZE WITH THE TENSION" in prompt
    assert "T1" in prompt and "T3" in prompt
    assert "B-CU" in prompt


if __name__ == "__main__":
    test_parses_two_moments()
    test_parses_no_bracket_and_multiword_shot_types()
    test_drops_moment_with_no_angles()
    test_cast_prompt_from_bible()
    test_generate_coverage_frames_honors_model_override()
    test_generate_coverage_frames_propagates_routed_model_and_routing_reason()
    test_plan_camera_moves_stamps_routed_model_on_shots()
    test_plan_camera_moves_no_style_stamps_video_level_model_unchanged()
    test_plan_camera_moves_camera_move_unaffected_when_routing_fails()
    test_scene_move_budget_defaults_to_one_earned_move()
    test_scene_move_budget_env_var_tunable()
    test_scene_move_budget_prefers_scene_final_shot()
    test_scene_move_budget_falls_back_to_first_earned_when_none_scene_final()
    test_setup_base_id_derivation()
    test_setup_anchor_ownership_and_size_variant_sharing()
    test_enforce_setup_variety_flags_three_in_a_row()
    test_enforce_setup_variety_size_variant_counts_as_same_family()
    test_enforce_setup_variety_fixes_with_a_safe_angle_swap()
    test_setup_target_scales_with_max_moments()
    test_tension_sizing_guidance_present_in_user_prompt()
    print("ok — coverage parser + cast-builder self-checks passed")
