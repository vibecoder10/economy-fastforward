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
    _shot_tag, _setup_id, enforce_reaction_insert_floors, stamp_shot_durations,
    _flatten_shots, _shot_family, _is_wide,
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


def _flat(*shots):
    """Build a minimal flat_shots list from (family, role) pairs or
    (family, role, moment_index) triples, e.g. _flat(('A', 'master'),
    ('B', 'angle', 2), ...) — each shot gets a synthetic
    "(SETUP <family>) ..." description so enforce_setup_variety's real
    description-tag parsing is exercised, matching production. A pair's
    moment index defaults to 0 (single-beat scene)."""
    out = []
    for i, spec in enumerate(shots):
        fam, role = spec[0], spec[1]
        mi = spec[2] if len(spec) > 2 else 0
        out.append({"shot_type": "MS", "role": role, "_mi": mi,
                    "description": f"(SETUP {fam}) placeholder shot {i}."})
    return out


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


def test_enforce_setup_variety_never_swaps_across_distant_moments():
    """(c)+C2.1: a different-family angle at moment distance >= 2 is NOT a
    swap candidate — an angle's description carries its BEAT's action, so
    dragging it across the scene lands narratively wrong. The run must be
    flagged (counted) but every shot left untouched."""
    flat = _flat(("B", "master", 0), ("B", "angle", 0), ("B", "angle", 1),
                 ("C", "angle", 3))  # only candidate is 2 moments away from the offender
    before = [s["description"] for s in flat]
    n = enforce_setup_variety(flat)
    assert n == 1, "the 3-long run is still a violation"
    assert [s["description"] for s in flat] == before, \
        "no swap may occur when the only candidate is >= 2 moments away"


def test_enforce_setup_variety_same_moment_candidate_beats_adjacent():
    """(c)+C2.1: candidate ordering — a different-family angle in the SAME
    moment as the offender wins over one in an ADJACENT moment, even when
    the adjacent one appears earlier in flat order (the old earliest-first
    scan would have picked it)."""
    flat = _flat(
        ("D", "angle", 0),   # 0: adjacent-moment candidate, earliest in flat order
        ("B", "master", 0),  # 1: run starts
        ("B", "angle", 0),   # 2
        ("B", "angle", 1),   # 3: offender (3rd consecutive B), moment 1
        ("C", "angle", 1),   # 4: SAME-moment candidate — must win
    )
    n = enforce_setup_variety(flat)
    assert n == 1
    # The offender's slot now holds the SAME-moment C content, not the
    # adjacent-moment D content.
    assert flat[3]["description"] == "(SETUP C) placeholder shot 4."
    assert flat[4]["description"] == "(SETUP B) placeholder shot 3."
    assert flat[0]["description"] == "(SETUP D) placeholder shot 0.", \
        "the adjacent-moment candidate must be left alone when a same-moment one exists"


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


# =============================================================================
# C3 item 1: inline (REACTION)/(INSERT) tags — own regex, disjoint from setup tags
# =============================================================================

def test_inline_tag_regex_parses_reaction_and_insert():
    """(e) the new tag regex parses both tags, case-insensitively, wherever
    they sit in the description (right after the setup tag, per rule 5f)."""
    assert _shot_tag({"description": "(SETUP C)(REACTION) CU on Vanessa listening."}) == "REACTION"
    assert _shot_tag({"description": "(SETUP E)(INSERT) Insert on the bowl of eggs."}) == "INSERT"
    assert _shot_tag({"description": "(setup c)(reaction) lower-case tag still parses."}) == "REACTION"
    assert _shot_tag({"description": "(SETUP B-CU) MCU on Ryan, speaking."}) is None
    assert _shot_tag({"description": ""}) is None
    assert _shot_tag({}) is None


def test_inline_tag_regex_never_matches_inside_a_setup_tag():
    """(e) the new regex and _SETUP_TAG_RE (via _setup_id) are disjoint: a
    setup id is only ever letters/digits/hyphens, so it can never itself
    read as "(REACTION)"/"(INSERT)", and the inline-tag regex never mistakes
    a "(SETUP X)" token for one of its own tags."""
    desc = "(SETUP C)(REACTION) CU on Vanessa listening."
    assert _setup_id({"description": desc}) == "C"  # setup parse ignores the trailing tag
    assert _shot_tag({"description": "(SETUP REACTION)"}) is None  # a weird id, still no false match


# =============================================================================
# C3 item 2: reaction/insert/re-establish FLOORS
# =============================================================================

def _moment(n, shot_type, description, speaker=None, line=None, angles=None):
    return {"moment_number": n, "summary": f"moment {n}",
            "master": {"shot_type": shot_type, "description": description},
            "angles": angles or [], "speaker": speaker, "line": line}


def test_reaction_floor_adds_shot_on_the_listener_for_a_key_line():
    """(a) a clean 2-speaker scene with no REACTION shot anywhere gets one
    added, framed on the LISTENER (the speaker who did NOT say the line the
    floor attached to), never the speaker themselves."""
    moments = [
        _moment(1, "WS", "(SETUP A) wide two-shot establishing the kitchen."),
        _moment(2, "MCU", "(SETUP B) Ryan speaks.", speaker="Ryan", line="Hello there."),
        _moment(3, "MCU", "(SETUP C) Vanessa speaks.", speaker="Vanessa", line="Hi Ryan."),
        _moment(4, "MCU", "(SETUP B) Ryan speaks again.", speaker="Ryan", line="How are you?"),
    ]
    before = sum(1 for s in _flatten_shots(moments) if _shot_tag(s) == "REACTION")
    assert before == 0
    n = enforce_reaction_insert_floors(moments)
    assert n >= 1
    reactions = [s for s in _flatten_shots(moments) if _shot_tag(s) == "REACTION"]
    assert len(reactions) >= 1
    # The floor attached to the LAST speaking moment (Ryan) — its listener is Vanessa.
    assert any("Vanessa" in s["description"] for s in reactions)
    assert not any("listening to Vanessa" in s["description"] for s in reactions), \
        "the reaction shot must show the LISTENER, never re-frame the speaker"


def test_reaction_floor_skipped_for_a_single_speaker_or_three_plus():
    """(a)-adjacent: with 1 speaker (monologue) or 3+ distinct speakers,
    "the listener" has no single well-defined answer, so the floor is
    skipped rather than guessed."""
    mono = [
        _moment(1, "WS", "(SETUP A) wide establishing."),
        _moment(2, "MCU", "(SETUP B) Dad speaks.", speaker="Dad", line="Line one."),
        _moment(3, "MCU", "(SETUP B) Dad speaks again.", speaker="Dad", line="Line two."),
    ]
    enforce_reaction_insert_floors(mono)
    assert not any(_shot_tag(s) == "REACTION" for s in _flatten_shots(mono))

    three_way = [
        _moment(1, "WS", "(SETUP A) wide establishing."),
        _moment(2, "MCU", "(SETUP B) A speaks.", speaker="A", line="One."),
        _moment(3, "MCU", "(SETUP C) B speaks.", speaker="B", line="Two."),
        _moment(4, "MCU", "(SETUP D) C speaks.", speaker="C", line="Three."),
    ]
    enforce_reaction_insert_floors(three_way)
    assert not any(_shot_tag(s) == "REACTION" for s in _flatten_shots(three_way))


def _silent_scene(n_moments, families):
    """n_moments moments, each a master + 1 angle (2 shots/moment), no
    speakers — isolates the INSERT/RE-ESTABLISH floors from the REACTION
    floor (which requires a clean 2-speaker dialogue)."""
    moments = []
    for i in range(n_moments):
        fam_m = families[(2 * i) % len(families)]
        fam_a = families[(2 * i + 1) % len(families)]
        shot_type = "WS" if i == 0 else "MS"
        moments.append(_moment(i + 1, shot_type, f"(SETUP {fam_m}) master beat {i}.",
                               angles=[{"shot_type": "MCU", "description": f"(SETUP {fam_a}) angle beat {i}."}]))
    return moments


def test_insert_floor_is_roughly_one_per_six_to_eight_shots():
    """(b) a 14-shot silent scene (7 moments x 2 shots) with zero INSERT
    shots gets exactly 2 added (14 // 7, the midpoint of the prompt's "1 per
    6-8" guidance) — none pre-existing, none over-added."""
    moments = _silent_scene(7, ["A", "B", "C", "D"])
    assert len(_flatten_shots(moments)) == 14
    enforce_reaction_insert_floors(moments)
    inserts = [s for s in _flatten_shots(moments) if _shot_tag(s) == "INSERT"]
    assert len(inserts) == 2, [s["description"] for s in inserts]


def test_re_establish_floor_is_roughly_one_per_ten_shots():
    """(c) a 22-shot silent scene (11 moments x 2 shots) needs 2 total
    re-establish wides of the scene's ESTABLISHING family (22 // 10); the
    opening master already provides 1, so exactly 1 more gets added."""
    moments = _silent_scene(11, ["A", "B", "C", "D"])
    assert len(_flatten_shots(moments)) == 22
    establish_family = _shot_family(moments[0]["master"])
    assert establish_family == "A"

    def _wide_a_count():
        return sum(1 for s in _flatten_shots(moments)
                   if _shot_family(s) == establish_family and _is_wide(s))

    assert _wide_a_count() == 1  # just the opening master, before the floor runs
    enforce_reaction_insert_floors(moments)
    assert _wide_a_count() == 2


def test_floors_convert_an_excess_shot_instead_of_adding_at_the_frame_cap():
    """(d) at the scene's frame cap, a missing REACTION floor is satisfied by
    CONVERTING an existing excess same-family angle in place — the total
    shot count never grows past the cap."""
    moments = [
        _moment(1, "WS", "(SETUP A) wide two-shot establishing."),
        _moment(2, "MCU", "(SETUP B) Ryan speaks.", speaker="Ryan", line="Hello there.",
               angles=[{"shot_type": "MCU", "description": "(SETUP B) untagged excess angle."}]),
        _moment(3, "MCU", "(SETUP C) Vanessa speaks.", speaker="Vanessa", line="Hi Ryan."),
    ]
    total_before = len(_flatten_shots(moments))
    assert total_before == 4  # 1 + 2 + 1
    n = enforce_reaction_insert_floors(moments, max_frames=total_before)
    assert n >= 1
    assert len(_flatten_shots(moments)) == total_before, \
        "at the frame cap, the floor must CONVERT, never grow the total"
    # The excess SETUP B angle (the only convertible candidate) now carries
    # the REACTION content instead of a brand-new shot being appended.
    excess = moments[1]["angles"][0]
    assert _shot_tag(excess) == "REACTION"
    assert "Ryan" in excess["description"]  # the listener of Vanessa's line


def test_floors_leave_violation_logged_when_no_safe_conversion_exists():
    """(d)-adjacent: at the cap with NO convertible angle available (every
    shot is a master, or every angle's family is unique), the floor is left
    unmet rather than blowing the budget — matches enforce_setup_variety's
    own flag-don't-force fallback."""
    moments = [
        _moment(1, "WS", "(SETUP A) wide two-shot establishing."),
        _moment(2, "MCU", "(SETUP B) Ryan speaks.", speaker="Ryan", line="Hello there."),
        _moment(3, "MCU", "(SETUP C) Vanessa speaks.", speaker="Vanessa", line="Hi Ryan."),
    ]
    total_before = len(_flatten_shots(moments))  # 3, all masters — nothing convertible
    enforce_reaction_insert_floors(moments, max_frames=total_before)
    assert len(_flatten_shots(moments)) == total_before
    assert not any(_shot_tag(s) == "REACTION" for s in _flatten_shots(moments))


# =============================================================================
# C3 item 4: per-shot target durations (SILENT shots only)
# =============================================================================

def test_stamp_shot_durations_by_shot_size_and_skips_speaking_master():
    """(f) wide -> 3.5s, medium/OTS -> 2.5s, close/insert/reaction -> 1.6s,
    stamped on every silent shot; a speaking moment's MASTER is left alone
    (its length comes from measured speech at assemble time, never this
    table) — its angles (never the line-carrying shot) still get stamped."""
    moments = [
        {"master": {"shot_type": "WS", "description": "wide establishing"},
         "angles": [
             {"shot_type": "OTS", "description": "medium OTS"},
             {"shot_type": "CU", "description": "close"},
             {"shot_type": "INSERT", "description": "insert"},
         ], "speaker": None, "line": None},
        {"master": {"shot_type": "MCU", "description": "Ryan speaks"},
         "angles": [{"shot_type": "CU", "description": "reaction on the listener"}],
         "speaker": "Ryan", "line": "Hello there."},
    ]
    n = stamp_shot_durations(moments)
    assert moments[0]["master"]["duration_seconds"] == 3.5
    assert moments[0]["angles"][0]["duration_seconds"] == 2.5   # OTS -> medium
    assert moments[0]["angles"][1]["duration_seconds"] == 1.6   # CU -> closeup
    assert moments[0]["angles"][2]["duration_seconds"] == 1.6   # INSERT -> closeup
    assert "duration_seconds" not in moments[1]["master"], \
        "a speaking master must NEVER get a stamped target — measured speech owns its length"
    assert moments[1]["angles"][0]["duration_seconds"] == 1.6   # its angle is still silent
    assert n == 5  # 4 silent shots in moment 1 + 1 silent angle in moment 2


def test_stamp_shot_durations_is_idempotent():
    """(f)-adjacent: calling it twice yields the same values (deterministic,
    no accumulation/drift)."""
    moments = [{"master": {"shot_type": "WS", "description": "wide"}, "angles": [],
               "speaker": None, "line": None}]
    stamp_shot_durations(moments)
    first = moments[0]["master"]["duration_seconds"]
    stamp_shot_durations(moments)
    assert moments[0]["master"]["duration_seconds"] == first == 3.5


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
    test_enforce_setup_variety_never_swaps_across_distant_moments()
    test_enforce_setup_variety_same_moment_candidate_beats_adjacent()
    test_setup_target_scales_with_max_moments()
    test_tension_sizing_guidance_present_in_user_prompt()
    test_inline_tag_regex_parses_reaction_and_insert()
    test_inline_tag_regex_never_matches_inside_a_setup_tag()
    test_reaction_floor_adds_shot_on_the_listener_for_a_key_line()
    test_reaction_floor_skipped_for_a_single_speaker_or_three_plus()
    test_insert_floor_is_roughly_one_per_six_to_eight_shots()
    test_re_establish_floor_is_roughly_one_per_ten_shots()
    test_floors_convert_an_excess_shot_instead_of_adding_at_the_frame_cap()
    test_floors_leave_violation_logged_when_no_safe_conversion_exists()
    test_stamp_shot_durations_by_shot_size_and_skips_speaking_master()
    test_stamp_shot_durations_is_idempotent()
    print("ok — coverage parser + cast-builder self-checks passed")
