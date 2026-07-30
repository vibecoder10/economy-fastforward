"""Self-check for the coverage directive parser.

Run: python skills/video-pipeline/tests/test_coverage.py   (or via pytest)
"""
import asyncio
import os
import sys
import tempfile
from unittest.mock import AsyncMock, patch

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
    enforce_setup_variety, assign_setup_anchors, enforce_shot_budget,
    _shot_tag, _setup_id, enforce_reaction_insert_floors, stamp_shot_durations,
    _flatten_shots, _shot_family, _is_wide, parse_set_dressing,
    plan_moments_deterministic, run_coverage, parse_setups_line,
    _parse_setup_kit, _facing_family, _no_people_families,
    _insert_subject_hint, _insert_desc_violation, _INSERT_FRAMING_CLAUSE,
    _INSERT_FALLBACK_SUBJECT, _carries_facing_law, check_facing_law_compliance,
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


def test_keeps_moment_with_no_angles():
    # A lone master with no angles is KEPT, angles simply empty.
    #
    # This test used to assert the opposite (parse_coverage(...) == [], "a
    # lone master is not coverage — it must be dropped") and had been failing
    # for a long time: still red at D3-53c, D3-62/63 and the D6 close-out,
    # i.e. it predates the D6-6a/D6-6b work entirely. The test was the stale
    # side, not the code. Dropping a master silently deletes a story beat,
    # and the master is also the lip-sync unit a spoken line lands on
    # (enforce_shot_budget's own rule: "masters are never sacrificed for an
    # angle" — it strips ANGLES to meet a frame ceiling and never masters).
    # A plan that legitimately gives one beat a single shot must survive.
    # Flipped 2026-07-30 to pin the behavior the pipeline actually relies on.
    only_master = "[MOMENT 1 | x]\n- MASTER [WS]: just a master, no angles here.\n"
    moments = parse_coverage(only_master)
    assert len(moments) == 1
    assert moments[0]["master"]["shot_type"] == "WS"
    assert moments[0]["angles"] == []


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


def test_approval_bound_coverage_calls_only_approved_still_draws(tmp_path):
    """Two approved frames means exactly two provider image calls and no cast call."""
    directive = (
        "[MOMENT 1 | the relay fails]\n"
        "- MASTER [WS]: Wide view of the dark relay room.\n"
        "- ANGLE [INSERT]: Tight detail of the failed indicator.\n"
    )
    client = _FakeImageClientForFrames()
    cast_resolver = AsyncMock(return_value="https://unexpected-cast.png")

    with patch("storyboard.coverage.resolve_cast_url", cast_resolver), \
         patch("storyboard.coverage._download", lambda url, path: None):
        out = asyncio.run(run_coverage(
            beat_text="The relay fails.",
            image_client=client,
            outdir=str(tmp_path),
            cast_url=None,
            directive_text=directive,
            max_moments=1,
            angles_max=1,
            max_frames=2,
            model_override="z-image",
            allow_auto_cast_generation=False,
        ))

    assert not out.get("error"), out
    assert out["frame_count"] == 2
    assert len(client.calls) == 2
    cast_resolver.assert_not_awaited()
    assert out["cast_url"] is None


def test_legacy_coverage_still_auto_resolves_cast(tmp_path):
    directive = (
        "[MOMENT 1 | the relay fails]\n"
        "- MASTER [WS]: Wide view of the dark relay room.\n"
        "- ANGLE [INSERT]: Tight detail of the failed indicator.\n"
    )
    client = _FakeImageClientForFrames()
    cast_resolver = AsyncMock(return_value="https://cast.png")

    with patch("storyboard.coverage.resolve_cast_url", cast_resolver), \
         patch("storyboard.coverage._download", lambda url, path: None):
        out = asyncio.run(run_coverage(
            beat_text="The relay fails.",
            image_client=client,
            outdir=str(tmp_path),
            cast_url=None,
            directive_text=directive,
            max_moments=1,
            angles_max=1,
            max_frames=2,
            model_override="z-image",
        ))

    assert not out.get("error"), out
    assert out["frame_count"] == 2
    assert len(client.calls) == 2
    cast_resolver.assert_awaited_once()
    assert out["cast_url"] == "https://cast.png"


class _FakeImageClientForFrames:
    """Records every frame-draw call; only the z-image path is exercised (no GPT
    fallback expected when it succeeds every time)."""
    SCENE_MODEL = "nano-banana-2"

    def __init__(self):
        self.calls = []

    async def generate_scene_image_zimage(self, prompt, aspect_ratio="16:9", **_kwargs):
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


def test_generate_coverage_frames_reports_real_image_count_progress():
    moment = {
        "moment_number": 1,
        "master": {"shot_type": "WS", "description": "wide shot of the rider at dawn"},
        "angles": [{"shot_type": "MCU", "description": "close on the rider's face"}],
    }
    progress = []
    frames = asyncio.run(generate_coverage_frames(
        moment,
        "https://cast.png",
        _FakeImageClientForFrames(),
        None,
        aspect="16:9",
        resolution="1K",
        model_override="z-image",
        progress_callback=progress.append,
        progress_state={"done": 0, "total": 2, "prefix": "Scene 3: "},
    ))
    assert frames is not None and len(frames) == 2
    assert progress == [
        "Scene 3: drawing image 1/2…",
        "Scene 3: drawing image 2/2…",
    ]


# ---- D6-6d: BOARD-LAWS L28 — never assert an input that is not attached ----
def test_style_lock_no_refs_wording_when_nothing_attached():
    """With no cast reference and no environment reference genuinely
    attached (cast_url=None, env_url=None — the allow_auto_cast_
    generation=False shape, called before any character is locked and with
    no matched environment), the MASTER shot's prompt must NOT claim to
    match "the attached reference image(s)" — nothing is attached for that
    call. The ANGLE's prompt legitimately keeps the claim: it always
    carries the just-drawn MASTER frame as a genuine attached reference
    (angle_base always includes master_url), so the gap is master-shots-
    only, exactly as the evidence found."""
    moment = {
        "moment_number": 1,
        "master": {"shot_type": "WS", "description": "wide shot of the rider at dawn"},
        "angles": [{"shot_type": "MCU", "description": "close on the rider's face"}],
    }
    ic = _FakeImageClientForFrames()
    frames = asyncio.run(generate_coverage_frames(
        moment, None, ic, None, env_url=None,
        aspect="16:9", resolution="1K", model_override="z-image"))
    assert frames is not None and len(frames) == 2
    master_prompt, angle_prompt = [c[1] for c in ic.calls]
    assert "attached reference image" not in master_prompt, master_prompt
    assert "STYLE LOCK" in master_prompt, "must still hold a style-consistency instruction"
    assert "attached reference image" in angle_prompt, angle_prompt


def test_style_lock_claims_refs_only_when_genuinely_attached():
    """Control: when a real cast reference IS attached (the overwhelmingly
    common real-world call shape), behavior is unchanged from before D6-6d —
    both master and angle prompts keep the original "attached reference
    image(s)" wording."""
    moment = {
        "moment_number": 1,
        "master": {"shot_type": "WS", "description": "wide shot of the rider at dawn"},
        "angles": [{"shot_type": "MCU", "description": "close on the rider's face"}],
    }
    ic = _FakeImageClientForFrames()
    frames = asyncio.run(generate_coverage_frames(
        moment, "https://cast.png", ic, None,
        aspect="16:9", resolution="1K", model_override="z-image"))
    assert frames is not None and len(frames) == 2
    master_prompt, angle_prompt = [c[1] for c in ic.calls]
    assert "attached reference image" in master_prompt, master_prompt
    assert "attached reference image" in angle_prompt, angle_prompt


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
    """Build a minimal flat_shots list from (family, role) pairs, (family,
    role, moment_index) triples, or (family, role, moment_index, tag)
    quadruples (tag: "REACTION"/"INSERT"/None) e.g. _flat(('A', 'master'),
    ('B', 'angle', 2), ('C', 'angle', 2, 'REACTION'), ...) — each shot gets a
    synthetic "(SETUP <family>)[(TAG)] ..." description so enforce_setup_variety's
    real description-tag parsing is exercised, matching production. A pair's
    moment index defaults to 0 (single-beat scene); the tag defaults to none."""
    out = []
    for i, spec in enumerate(shots):
        fam, role = spec[0], spec[1]
        mi = spec[2] if len(spec) > 2 else 0
        tag = spec[3] if len(spec) > 3 else None
        tag_str = f"({tag})" if tag else ""
        out.append({"shot_type": "MS", "role": role, "_mi": mi,
                    "description": f"(SETUP {fam}){tag_str} placeholder shot {i}."})
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


def test_enforce_setup_variety_never_swaps_a_reaction_tagged_offender():
    """(c) C7 fix: a REACTION-tagged shot names a specific listener/speaker
    tied to one exact instant ("CU on X, listening to Y's line") — relocating
    it via the variety swap (even to an adjacent beat) can land it where Y
    isn't speaking. The 3rd-consecutive-B offender here is angle-role AND
    REACTION-tagged, with an otherwise-perfect same-moment C candidate
    available — pre-fix this would swap; post-fix it must be left in place
    and merely flagged, same as a master would be."""
    flat = _flat(
        ("B", "master", 0),
        ("B", "angle", 0),
        ("B", "angle", 0, "REACTION"),   # offender: angle, but REACTION-tagged
        ("C", "angle", 0),               # otherwise a perfect same-moment candidate
    )
    before = [s["description"] for s in flat]
    n = enforce_setup_variety(flat)
    assert n == 1, "the 3-long run is still counted as a violation"
    assert [s["description"] for s in flat] == before, \
        "a REACTION-tagged offender must never be swapped, even with a safe candidate available"


def test_enforce_setup_variety_never_uses_an_insert_tagged_shot_as_a_candidate():
    """(c) C7 fix: the OTHER side of the exclusion — an INSERT-tagged shot
    must never be chosen as the swap TARGET either (it carries its own
    punctuation-beat content that would get dragged to the wrong position).
    The offender (plain angle, family B) has only one different-family
    candidate available, and it's INSERT-tagged — so no safe swap exists and
    the violation is flagged instead."""
    flat = _flat(
        ("B", "master", 0),
        ("B", "angle", 0),
        ("B", "angle", 0),               # offender: plain angle, no tag
        ("C", "angle", 0, "INSERT"),     # only candidate, but INSERT-tagged
    )
    before = [s["description"] for s in flat]
    n = enforce_setup_variety(flat)
    assert n == 1
    assert [s["description"] for s in flat] == before, \
        "an INSERT-tagged shot must never be used as a swap candidate"


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


# =============================================================================
# D3-53c: rule 4b's BRIDGE requirement must be structural (output contract),
# additive (exempt from the moment budget, no narration sentence needed), and
# present for BOTH a dialogue-shaped scene and a silent one (the profile/
# max_moments knobs the system prompt is built from don't vary by scene
# content, so one system-prompt build covers both call shapes).
# =============================================================================

def test_bridge_contract_line_present_and_structural():
    """The output contract (not just rule 4b's prose) states the BRIDGE
    requirement as a MUST, tied to the pattern 'adjacent moments in different
    locations', independent of whether the scene has dialogue or is silent —
    _coverage_system_prompt() takes no beat_text, so this is the ONE prompt
    build both call shapes share."""
    from shared.channel_profile import load_profile
    profile = load_profile({})
    prompt = _coverage_system_prompt(profile, max_moments=8, angles_min=2, angles_max=4)

    # rule 4b still carries the rationale + tag convention.
    assert "4b)" in prompt
    assert '"(BRIDGE)"' in prompt
    assert "ADDITIVE" in prompt

    # the output contract section states it as a MUST, not prose guidance.
    tail_start = prompt.index("shot_type is one of")
    contract_tail = prompt[tail_start:prompt.index("Describe every person", tail_start)]
    assert "MUST" in contract_tail and "(BRIDGE)" in contract_tail, \
        "FAIL: output contract doesn't structurally require a (BRIDGE) moment"
    assert "adjacent" in contract_tail.lower() and "different locations" in contract_tail.lower()
    assert "INCOMPLETE" in contract_tail, "FAIL: contract doesn't say a plan without it is invalid"


def test_bridge_is_exempt_from_the_moment_budget():
    """A bridge moment must not be presented as competing with max_moments —
    the contract line must say it doesn't count against the cap."""
    from shared.channel_profile import load_profile
    profile = load_profile({})
    prompt = _coverage_system_prompt(profile, max_moments=8, angles_min=2, angles_max=4)
    tail_start = prompt.index("shot_type is one of")
    contract_tail = prompt[tail_start:prompt.index("Describe every person", tail_start)]
    assert "does NOT count against the" in contract_tail
    assert "{max_moments}" not in contract_tail  # sanity: f-string substituted, no stray braces
    assert "8" in contract_tail  # the formatted max_moments cap appears, restated


def test_bridge_needs_no_narration_sentence_of_its_own():
    """Rule 4b must explicitly say a bridge shot doesn't need its own
    narration sentence — this is the exact conflict D3-53c diagnosed: literal
    narration-order compliance was starving the bridge shot of a reason to
    exist. Also confirm rule 4b no longer frames BRIDGE as competing with
    'follow the narration's own event order' for silent moments — that clause
    must stay (silent-moment ordering is unchanged) but the BRIDGE clause is
    now a separate, additive paragraph."""
    from shared.channel_profile import load_profile
    profile = load_profile({})
    prompt = _coverage_system_prompt(profile, max_moments=8, angles_min=2, angles_max=4)
    rule_4b_start = prompt.index("4b)")
    rule_4b_text = prompt[rule_4b_start: prompt.index("\n5)", rule_4b_start)]
    assert "follow the scene narration's OWN event order" in rule_4b_text, \
        "FAIL: silent-moment narration-order law regressed"
    assert "NO narration sentence" in rule_4b_text or "NO narration sentence".lower() in rule_4b_text.lower()
    assert "NEVER displaces" in rule_4b_text or "never displaces" in rule_4b_text.lower()


def test_bridge_contract_present_for_both_dialogue_and_silent_call_shape():
    """_coverage_user_prompt diverges by scene content (dialogue turns block
    vs none, per the existing D3-53b evidence script) but the BRIDGE contract
    lives entirely in the system prompt, so it applies uniformly to both."""
    from shared.channel_profile import load_profile
    from storyboard.coverage import _coverage_user_prompt, _scene_turns

    system_prompt = _coverage_system_prompt(load_profile({}), max_moments=8, angles_min=2, angles_max=4)
    assert "(BRIDGE)" in system_prompt

    dialogue_scene = "Ryan: I sealed the hatch.\nVanessa: Then why is it open?\n"
    silent_scene = ("Inside the sealed pod, Ryan checks the gauge. He pushes the hatch open "
                     "and steps into the exterior hallway, scanning both directions.")

    dialogue_user_prompt = _coverage_user_prompt(dialogue_scene, "Test", None, None, None)
    silent_user_prompt = _coverage_user_prompt(silent_scene, "Test", None, None, None)
    assert _scene_turns(dialogue_scene), "sanity: dialogue fixture should parse turns"
    assert not _scene_turns(silent_scene), "sanity: silent fixture should parse zero turns"
    assert "DIALOGUE TURNS" in dialogue_user_prompt
    assert "DIALOGUE TURNS" not in silent_user_prompt
    # both share the SAME system prompt in a real call, so the contract line
    # doesn't need to be re-derived per scene type — proven by construction
    # above (one system_prompt build, used for both).


# ---- D6-6a: the BUDGET leg must honor the PROMPT leg's additive promise ----
# Rule 4b tells the planner a bridge moment doesn't count against max_moments.
# enforce_shot_budget used to slice the tail off anyway, so on a scene that
# CLOSES on a location change (rule 4b's own example placement) the promised-
# free moment was the one deleted. Found live on a 3-moment "escape" scene
# whose 4th moment WAS the escape.


def _budget_moment(n: int, desc: str, angles: int = 0, location=None,
                   summary=None) -> dict:
    """One parsed-shape moment for enforce_shot_budget: a master plus `angles`
    plain angles. desc goes on the MASTER's description, which is where rule
    4b puts the "(BRIDGE)" tag. location/summary (D6-6c) default to the
    pre-D6-6c shape (no "location" key at all, summary=f"m{n}") so every
    existing call site of this helper is completely unaffected."""
    return {
        "moment_number": n,
        "summary": summary if summary is not None else f"m{n}",
        "location": location,
        "master": {"shot_type": "MS", "description": desc},
        "angles": [{"shot_type": "CU", "description": f"angle {i} of m{n}"}
                   for i in range(angles)],
    }


def test_bridge_moment_past_the_cap_survives_the_budget():
    """THE regression: a 4-moment escape scene against max_moments=3 whose
    4th moment is the BRIDGE. Today's blunt moments[:3] dropped it, so the
    scene never showed the character get out."""
    moments = [_budget_moment(1, "(SETUP A) Nyla wakes in her pod."),
               _budget_moment(2, "(SETUP B) She whispers to herself."),
               _budget_moment(3, "(SETUP C) She presses the hatch release."),
               _budget_moment(4, "(SETUP F)(BRIDGE) Nyla climbs out into the corridor.")]
    out = enforce_shot_budget(moments, 3, 3, max_frames=None)
    descs = [m["master"]["description"] for m in out]
    assert len(out) == 4, f"BRIDGE moment was trimmed away: {descs}"
    assert "(BRIDGE)" in descs[-1], descs
    # every narrated moment survives too — the bridge is ADDITIVE, it does not
    # buy its slot by evicting one of them
    assert "wakes in her pod" in descs[0] and "hatch release" in descs[2], descs
    # renumbering still runs over the kept sequence
    assert [m["moment_number"] for m in out] == [1, 2, 3, 4]


def test_non_bridge_overshoot_still_trims_exactly_as_before():
    """The exemption must not become a general amnesty: an ordinary overshoot
    with no BRIDGE tag anywhere trims to the cap and renumbers, unchanged."""
    moments = [_budget_moment(i, f"(SETUP A) plain beat {i}") for i in range(1, 8)]
    out = enforce_shot_budget(moments, 3, 3, max_frames=None)
    assert len(out) == 3
    assert [m["moment_number"] for m in out] == [1, 2, 3]
    assert "plain beat 3" in out[-1]["master"]["description"]


def test_bridge_exemption_does_not_pierce_the_max_frames_ceiling():
    """max_frames is a hard provider ceiling (the Custom Film BOM path passes
    max_frames == the approved image count). An additive bridge may exceed the
    MOMENT cap but never the FRAME ceiling — the ceiling pass still trims it
    back, exactly as today."""
    moments = [_budget_moment(1, "(SETUP A) beat one"),
               _budget_moment(2, "(SETUP B) beat two"),
               _budget_moment(3, "(SETUP C) beat three"),
               _budget_moment(4, "(SETUP F)(BRIDGE) out into the corridor.")]
    out = enforce_shot_budget(moments, 3, 0, max_frames=3)
    frames = sum(1 + len(m.get("angles") or []) for m in out)
    assert frames == 3, f"bridge pierced the paid frame ceiling: {frames}"


def test_bridge_exemption_caps_a_runaway_tagger():
    """A planner that tags EVERY moment "(BRIDGE)" must not buy an unbounded
    scene — each exempt moment is real image spend. Past _MAX_EXEMPT_BRIDGES
    the extras compete for cap slots like any other moment."""
    from storyboard.coverage import _MAX_EXEMPT_BRIDGES
    moments = [_budget_moment(i, f"(SETUP A)(BRIDGE) bridge {i}") for i in range(1, 10)]
    out = enforce_shot_budget(moments, 3, 3, max_frames=None)
    assert len(out) == 3 + _MAX_EXEMPT_BRIDGES, len(out)


def test_bridge_orphaned_by_the_trim_is_not_exempt():
    """Rule 4b defines a bridge as sitting BETWEEN the last moment at the old
    location and the first at the new one. A bridge whose predecessor was
    already trimmed away bridges out of a location the cut never reaches, so
    it stops being additive and needs a slot like anything else."""
    moments = [_budget_moment(1, "(SETUP A) beat one"),
               _budget_moment(2, "(SETUP B) beat two"),
               _budget_moment(3, "(SETUP C) beat three"),
               _budget_moment(4, "(SETUP D) beat four"),
               _budget_moment(5, "(SETUP E) beat five"),
               _budget_moment(6, "(SETUP F)(BRIDGE) orphaned bridge")]
    out = enforce_shot_budget(moments, 3, 3, max_frames=None)
    assert len(out) == 3, [m["master"]["description"] for m in out]
    assert all("(BRIDGE)" not in m["master"]["description"] for m in out)


def test_bridge_exemption_reaches_both_draw_paths():
    """Both the $0.05 sheet PREVIEW path and the real per-shot PICTURES path
    plan through plan_moments_deterministic -> enforce_shot_budget, so proving
    it on the shared pipeline proves it for both doors at once (that is the
    whole point of C7 fix (a)'s single pipeline)."""
    directive = (
        "[SETUPS | A: wide of the pod; C: MCU on the release; F: corridor wide]\n"
        "[MOMENT 1 | Nyla wakes]\n"
        "- MASTER [WS]: (SETUP A) Nyla wakes in her pod.\n"
        "- ANGLE [MCU]: (SETUP C) MCU on her open eyes.\n"
        "[MOMENT 2 | she whispers]\n"
        "- MASTER [MS]: (SETUP A) She whispers to herself.\n"
        "- ANGLE [CU]: (SETUP C) CU on her mouth.\n"
        "[MOMENT 3 | the release]\n"
        "- MASTER [MS]: (SETUP C) She presses the hatch release.\n"
        "- ANGLE [ECU]: (SETUP A) ECU on the latch turning.\n"
        "[MOMENT 4 | out into the corridor]\n"
        "- MASTER [WS]: (SETUP F)(BRIDGE) Nyla climbs out into the corridor.\n"
        "- ANGLE [MS]: (SETUP F) She looks back at the open hatch.\n"
    )
    moments = plan_moments_deterministic(directive, 3, 3, max_frames=None)
    assert moments is not None
    descs = [m["master"]["description"] for m in moments]
    assert any("(BRIDGE)" in d for d in descs), descs
    # and the scene-level motion detector agrees the escape is still in the plan
    from storyboard.coverage import scene_has_motion
    assert scene_has_motion(moments)


# ---- D6-6c: bridge-ness must be DERIVABLE FROM STRUCTURE, not just the tag ----
# Live finding (D6-6a dry run): the SAME escape scene's exit beat got the
# "(BRIDGE)" tag on only 1 of 3 real planner calls — a text-generation coin
# flip a hard shot-budget cut should never hinge on. Two structural signals
# (both gated on location_sets — rule 8's multi-location LOCSET blocks) now
# OR in alongside the tag, so the moment survives even when the LLM never
# writes it.


def test_bridge_deterministic_without_the_llm_tag():
    """The exact live failure mode, reproduced without any "(BRIDGE)" tag at
    all: a genuine multi-location scene (location_sets has Pod + Corridor)
    whose exit moment's own LOCATION tag matches its predecessor's ("Pod" —
    mirroring the REAL evidence transcript, where the LLM tagged the exit
    moment "Pod", the same as the moment before it), so ONLY the transit-
    language signal (the moment's one-line summary — "out into the
    corridor" — matching S1 transit vocabulary), not the location-diff
    signal, can be doing the work here."""
    location_sets = {"Pod": "the sealed glass pod", "Corridor": "the metal catwalk"}
    moments = [
        _budget_moment(1, "(SETUP A) Nyla wakes in her pod.", location="Pod", summary="Nyla wakes"),
        _budget_moment(2, "(SETUP B) She whispers to herself.", location="Pod", summary="she whispers"),
        _budget_moment(3, "(SETUP C) She presses the hatch release.", location="Pod", summary="the release"),
        _budget_moment(4, "(SETUP F) Nyla climbs out into the corridor.", location="Pod",
                       summary="out into the corridor"),
    ]
    out = enforce_shot_budget(moments, 3, 3, max_frames=None, location_sets=location_sets)
    descs = [m["master"]["description"] for m in out]
    assert len(out) == 4, f"untagged transit moment was trimmed away: {descs}"
    assert "(BRIDGE)" not in descs[-1], "this moment must survive with NO tag at all"
    assert "corridor" in descs[-1]


def test_bridge_location_change_signal_without_tag_or_transit_words():
    """The OTHER new structural signal, isolated: a multi-location scene
    whose exit moment's own LOCATION tag genuinely differs from its
    predecessor's ("Corridor" vs "Pod") survives even with neither a
    "(BRIDGE)" tag nor any transit-sounding vocabulary in its summary or
    description."""
    location_sets = {"Pod": "the sealed glass pod", "Corridor": "the metal catwalk"}
    moments = [
        _budget_moment(1, "(SETUP A) beat one.", location="Pod", summary="beat one"),
        _budget_moment(2, "(SETUP B) beat two.", location="Pod", summary="beat two"),
        _budget_moment(3, "(SETUP C) beat three.", location="Pod", summary="beat three"),
        _budget_moment(4, "(SETUP F) Nyla stands there.", location="Corridor", summary="she stands there"),
    ]
    out = enforce_shot_budget(moments, 3, 3, max_frames=None, location_sets=location_sets)
    assert len(out) == 4, [m["master"]["description"] for m in out]
    assert out[-1]["location"] == "Corridor"


def test_transit_language_never_exempts_a_single_location_scene():
    """Both new signals are gated on location_sets (rule 8) — a
    single-location scene (location_sets=None, the default and every call
    site before D6-6c) must trim an untagged tail moment exactly as before,
    even when its summary happens to use transit-sounding words. Otherwise
    an ordinary scene where someone merely "leaves the room" would earn an
    unbounded free exemption — the amnesty test_non_bridge_overshoot_
    still_trims_exactly_as_before already guards against for the tag."""
    moments = [
        _budget_moment(1, "(SETUP A) beat one", summary="beat one"),
        _budget_moment(2, "(SETUP B) beat two", summary="beat two"),
        _budget_moment(3, "(SETUP C) beat three", summary="beat three"),
        _budget_moment(4, "(SETUP D) she leaves through the door.", summary="leaves through the door"),
    ]
    out = enforce_shot_budget(moments, 3, 3, max_frames=None)  # location_sets defaults to None
    assert len(out) == 3, [m["master"]["description"] for m in out]
    assert [m["moment_number"] for m in out] == [1, 2, 3]


def test_rule5_dialogue_order_unchanged_by_bridge_restructure():
    """Guard against the restructure bleeding into rule 5 (dialogue speaker
    order) — must stay byte-identical in substance."""
    from shared.channel_profile import load_profile
    profile = load_profile({})
    prompt = _coverage_system_prompt(profile, max_moments=8, angles_min=2, angles_max=4)
    assert "DIALOGUE = ONE SPEAKER PER MOMENT" in prompt
    assert "IN SCRIPT ORDER" in prompt
    assert "5b) BLOCKING IS FIXED" in prompt
    assert "5d) THE 180-DEGREE RULE" in prompt


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


# ---- insert-framing fix (verified bug: INSERT shots drew as wide two-shots
# instead of tight detail close-ups) ----------------------------------------

def test_insert_floor_desc_contains_close_up_framing_clause():
    """The generated INSERT desc must lead with an explicit close-up/tight
    framing clause — the whole point of the fix, since before it nothing in
    the prompt ever asked for tight framing at all."""
    moments = _silent_scene(7, ["A", "B", "C", "D"])
    enforce_reaction_insert_floors(moments)
    inserts = [s for s in _flatten_shots(moments) if _shot_tag(s) == "INSERT"]
    assert inserts, "expected at least one INSERT floor shot"
    for s in inserts:
        desc = s["description"]
        assert "extreme close-up" in desc.lower() or "close-up" in desc.lower(), desc
        assert "no faces visible" in desc.lower(), desc


def test_insert_floor_never_quotes_the_whole_room_set_line():
    """Regression pin for the exact bug: the old code did
    `(prop_hint[:80])` where prop_hint fell back to the raw [SET|] line —
    a whole-room summary truncated to 80 chars, never an actual detail. With
    no prop manifest, the desc must use the generic hands+prop fallback
    instead of ever echoing set_line."""
    moments = _silent_scene(7, ["A", "B", "C", "D"])
    set_line = ("A cramped kitchen with a butcher-block island, hanging copper pots, a six-burner "
                "range, and open shelving stacked with ceramic bowls")
    enforce_reaction_insert_floors(moments, set_line=set_line)
    inserts = [s for s in _flatten_shots(moments) if _shot_tag(s) == "INSERT"]
    assert inserts
    for s in inserts:
        assert set_line[:40] not in s["description"], \
            f"INSERT desc must never quote the whole-room [SET|] line verbatim: {s['description']!r}"
        assert _INSERT_FALLBACK_SUBJECT in s["description"]


def test_insert_floor_uses_a_manifest_prop_when_provided():
    """(1) real detail hint: with an environment prop manifest available,
    the INSERT floor's subject is a real prop name from that manifest
    (deterministic rotation by insert index), not the generic fallback."""
    moments = _silent_scene(7, ["A", "B", "C", "D"])
    props = [{"name": "copper stockpot", "position": "stovetop"},
             {"name": "wooden cutting board", "position": "island"}]
    enforce_reaction_insert_floors(moments, props=props)
    inserts = [s for s in _flatten_shots(moments) if _shot_tag(s) == "INSERT"]
    assert len(inserts) == 2, [s["description"] for s in inserts]
    # Deterministic rotation: insert 0 -> prop 0, insert 1 -> prop 1.
    assert "copper stockpot" in inserts[0]["description"]
    assert "wooden cutting board" in inserts[1]["description"]
    for s in inserts:
        assert _INSERT_FALLBACK_SUBJECT not in s["description"]


def test_insert_subject_hint_rotates_through_manifest_and_falls_back():
    props = [{"name": "brass compass"}, {"name": "leather journal"}]
    assert _insert_subject_hint(props, 0) == "brass compass"
    assert _insert_subject_hint(props, 1) == "leather journal"
    assert _insert_subject_hint(props, 2) == "brass compass"  # wraps around
    assert _insert_subject_hint(None, 0) == _INSERT_FALLBACK_SUBJECT
    assert _insert_subject_hint([], 0) == _INSERT_FALLBACK_SUBJECT


def test_insert_desc_violation_rejects_missing_framing_term():
    desc = "(SETUP A)(INSERT) Insert punctuating the beat — a coffee mug."
    reason = _insert_desc_violation(desc, {"Ryan", "Vanessa"})
    assert reason is not None
    assert "framing" in reason


def test_insert_desc_violation_rejects_both_character_names_present():
    desc = ("(SETUP A)(INSERT) Extreme close-up, tight detail shot, shallow depth of field, "
            "no faces visible — Ryan hands Vanessa the mug.")
    reason = _insert_desc_violation(desc, {"Ryan", "Vanessa"})
    assert reason is not None
    assert "Ryan" in reason and "Vanessa" in reason


def test_insert_desc_violation_passes_a_clean_desc():
    desc = (f"(SETUP A)(INSERT) {_INSERT_FRAMING_CLAUSE} — a copper stockpot, "
            f"punctuating the beat.")
    assert _insert_desc_violation(desc, {"Ryan", "Vanessa"}) is None
    # Naming ONE character (e.g. whose hands are shown) is fine — only BOTH
    # names present is a violation.
    desc_one_name = (f"(SETUP A)(INSERT) {_INSERT_FRAMING_CLAUSE} — Ryan's hands gripping "
                     f"the stockpot.")
    assert _insert_desc_violation(desc_one_name, {"Ryan", "Vanessa"}) is None


def test_insert_floor_regenerates_when_a_manifest_prop_name_collides_with_both_speakers():
    """(3) guard: if a (contrived) prop manifest entry happened to smuggle
    both character names into the subject text, the floor's own guard
    rejects it and regenerates with the safe generic fallback instead of
    shipping the bad desc — proves the guard is actually wired into the
    generation path, not just a standalone function."""
    moments = [
        _moment(1, "WS", "(SETUP A) wide establishing.",
               angles=[{"shot_type": "MCU", "description": "(SETUP B) angle."}]),
        _moment(2, "MCU", "(SETUP B) Ryan speaks.", speaker="Ryan", line="Hello there.",
               angles=[{"shot_type": "MCU", "description": "(SETUP C) angle."}]),
        _moment(3, "MCU", "(SETUP C) Vanessa speaks.", speaker="Vanessa", line="Hi Ryan.",
               angles=[{"shot_type": "MCU", "description": "(SETUP D) angle."}]),
        _moment(4, "MCU", "(SETUP D) Ryan speaks again.", speaker="Ryan", line="How are you?",
               angles=[{"shot_type": "MCU", "description": "(SETUP A) angle."}]),
    ]
    # A pathological manifest entry naming both speakers — the kind of prop
    # text this generator never emits itself, but the guard exists precisely
    # so a bad upstream value can never reach the image model unfiltered.
    props = [{"name": "the note Ryan wrote to Vanessa", "position": "counter"}]
    enforce_reaction_insert_floors(moments, props=props)
    inserts = [s for s in _flatten_shots(moments) if _shot_tag(s) == "INSERT"]
    assert inserts, "expected at least one INSERT floor shot"
    for s in inserts:
        assert not ("Ryan" in s["description"] and "Vanessa" in s["description"]), \
            f"guard should have regenerated a both-names desc: {s['description']!r}"
        assert _INSERT_FALLBACK_SUBJECT in s["description"]


def test_run_coverage_insert_tail_drops_character_blocking(tmp_path):
    """(2) framing law at the append site: run_coverage's SET-DRESSING LOCK
    tail must give an INSERT shot the shorter continuity-only tail (no
    "character blocking" language, explicit "no faces visible, detail
    only"), while non-INSERT shots keep the original full tail unchanged."""
    directive = (
        "[SET | a cramped kitchen with a butcher-block island and hanging copper pots]\n"
        "[MOMENT 1 | Ryan and Vanessa cook]\n"
        "- MASTER [WS]: (SETUP A) Wide two-shot establishing the kitchen.\n"
        "- ANGLE [INSERT]: (SETUP E)(INSERT) Extreme close-up, tight detail shot, shallow "
        "depth of field, no faces visible — a copper stockpot, punctuating the beat.\n"
    )

    async def _fake_frames(moment, cast_url, image_client, profile=None, env_url=None,
                           aspect="16:9", resolution="1K", sem=None, model_override=None,
                           setup_anchors=None):
        frames = [{"role": "master", "shot_type": moment["master"]["shot_type"],
                  "description": moment["master"]["description"], "url": "https://img/m.png"}]
        for a in moment.get("angles") or []:
            frames.append({"role": "angle", "shot_type": a["shot_type"],
                           "description": a["description"], "url": "https://img/a.png"})
        return frames

    outdir = str(tmp_path)
    with patch("storyboard.coverage.resolve_cast_url", AsyncMock(return_value="https://cast.png")), \
         patch("storyboard.coverage.generate_coverage_frames", AsyncMock(side_effect=_fake_frames)), \
         patch("storyboard.coverage._download", lambda url, path: None):
        out = asyncio.run(run_coverage(
            beat_text="two people cook in a kitchen", image_client=None, outdir=outdir,
            cast_url="https://cast.png", directive_text=directive,
            max_moments=10, angles_max=4, max_frames=None,
        ))
    assert not out.get("error"), out
    moment = out["moments"][0]
    master_desc = moment["master"]["description"]
    insert_desc = moment["angles"][0]["description"]
    assert "character blocking" in master_desc.lower()
    assert "character blocking" not in insert_desc.lower(), insert_desc
    assert "no faces visible, detail only" in insert_desc.lower(), insert_desc
    # Both still get the scene's set-dressing continuity text.
    assert "butcher-block island" in master_desc
    assert "butcher-block island" in insert_desc


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


def test_re_establish_floor_phrasing_has_no_two_shot_or_character_count_claim():
    """(b) C7 fix: the RE-ESTABLISH floor's description must never claim
    "two-shot" (or any other character-count wording) — that's false for a
    solo or 3+ character scene, and this codebase has live proof that prose
    implying extra bodies makes the image model invent people (see coverage.py
    ~555). The added shot's description must describe the framing/camera only."""
    moments = _silent_scene(11, ["A", "B", "C", "D"])
    enforce_reaction_insert_floors(moments)
    re_establish = [s for s in _flatten_shots(moments)
                   if _shot_family(s) == "A" and _is_wide(s) and s is not moments[0]["master"]]
    assert re_establish, "expected at least one added re-establish shot"
    for s in re_establish:
        desc = s["description"].lower()
        assert "two-shot" not in desc, f"re-establish phrasing must not claim a two-shot: {desc!r}"
        assert "camera unchanged" in desc


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


# C9: a realistic [SETUPS|] kit line, abbreviated from the real Spanish Class
# scene-2 planner output — same structure, same facing declarations, same
# INSERT/NEUTRAL no-people family E.
_C9_KIT_LINE = (
    "A: WS two-shot — Ryan sharp at the far-left edge of island, Vanessa sharp "
    "at the far-right edge, both facing each other; "
    "B: MCU OTS over Ryan's RIGHT shoulder onto Vanessa — Vanessa sharp "
    "right-of-center looking frame-LEFT; "
    "C: MCU OTS over Vanessa's LEFT shoulder onto Ryan — Ryan sharp "
    "left-of-center looking frame-RIGHT; "
    "B-CU: tighter CU variant of SETUP B, same axis/background, punching in on "
    "Vanessa's face filling right-of-center; "
    "C-CU: tighter CU variant of SETUP C, same axis/background, punching in on "
    "Ryan's face filling left-of-center; "
    "E: INSERT, NEUTRAL — close on island props (potato bowl, egg bowl, oil "
    "bottle, spatula), no people, camera straight down on the surface")


def test_reaction_family_faces_the_listener_from_the_kit_line():
    """C9 placement rule: a REACTION on listener L uses the CU compound
    variant of the family that FACES L, derived from the kit text's own
    'onto {name}' declaration — reaction on Vanessa → (SETUP B-CU),
    reaction on Ryan → (SETUP C-CU), sharing the facing family's anchor via
    the existing base-letter logic. Never LRU when facing is derivable."""
    kit = _parse_setup_kit(_C9_KIT_LINE)
    assert set(kit) == {"A", "B", "C", "B-CU", "C-CU", "E"}, set(kit)
    assert _facing_family(kit, "Vanessa") == "B"
    assert _facing_family(kit, "Ryan") == "C"
    assert _no_people_families(kit) == {"E"}

    moments = [
        _moment(1, "WS", "(SETUP A) wide two-shot establishing."),
        _moment(2, "MCU", "(SETUP B) Vanessa speaks.", speaker="Vanessa", line="Pelar."),
        _moment(3, "MCU", "(SETUP C) Ryan speaks.", speaker="Ryan", line="Pelar. Peel."),
        _moment(4, "MCU", "(SETUP B) Vanessa speaks.", speaker="Vanessa", line="Cuchillo."),
        _moment(5, "MCU", "(SETUP C) Ryan speaks.", speaker="Ryan", line="Cuchillo. Right."),
        _moment(6, "MCU", "(SETUP B) Vanessa speaks.", speaker="Vanessa", line="Vamos."),
        _moment(7, "MCU", "(SETUP C) Ryan speaks.", speaker="Ryan", line="Great."),
        _moment(8, "MCU", "(SETUP B) Vanessa speaks.", speaker="Vanessa", line="Sí."),
    ]
    enforce_reaction_insert_floors(moments, setups_line=_C9_KIT_LINE,
                                   max_frames=len(_flatten_shots(moments)) + 4)
    reactions = [s for s in _flatten_shots(moments) if _shot_tag(s) == "REACTION"]
    assert reactions, "expected at least one floor-added reaction"
    for s in reactions:
        if "CU on Ryan" in s["description"]:
            assert _setup_id(s) == "C-CU", s["description"]
        elif "CU on Vanessa" in s["description"]:
            assert _setup_id(s) == "B-CU", s["description"]
        else:
            raise AssertionError(f"reaction names neither listener: {s['description']!r}")


def test_reaction_never_lands_in_a_no_people_family():
    """C9 defect pin: family E is the INSERT/NEUTRAL props camera (its
    anchor frame has no people) — a face-CU REACTION must never be assigned
    there, even when E is the least-recently-used family (which is exactly
    how the live v2 shot list dealt shot 47 to E). Kit text here carries no
    facing evidence (names stripped) so the LRU fallback runs — and must
    skip E."""
    kit_no_facing = ("A: WS two-shot, both actors visible; "
                     "B: MCU over-shoulder one direction; "
                     "C: MCU over-shoulder the other direction; "
                     "E: INSERT, NEUTRAL — close on props, no people")
    moments = [
        _moment(1, "WS", "(SETUP A) wide establishing."),
        _moment(2, "MCU", "(SETUP B) Vanessa speaks.", speaker="Vanessa", line="Uno."),
        _moment(3, "MCU", "(SETUP C) Ryan speaks.", speaker="Ryan", line="Dos."),
        _moment(4, "INSERT", "(SETUP E)(INSERT) props on the island."),
        _moment(5, "MCU", "(SETUP B) Vanessa speaks.", speaker="Vanessa", line="Tres."),
        _moment(6, "MCU", "(SETUP C) Ryan speaks.", speaker="Ryan", line="Cuatro."),
    ]
    enforce_reaction_insert_floors(moments, setups_line=kit_no_facing,
                                   max_frames=len(_flatten_shots(moments)) + 3)
    reactions = [s for s in _flatten_shots(moments) if _shot_tag(s) == "REACTION"]
    assert reactions, "expected at least one floor-added reaction"
    for s in reactions:
        assert _shot_family(s) != "E", \
            f"REACTION landed in the no-people INSERT family: {s['description']!r}"
        assert _shot_family(s) != "A", \
            f"LRU fallback must also skip the establish family: {s['description']!r}"


def test_reaction_falls_back_to_lru_when_no_kit_line_exists():
    """Legacy plan with no [SETUPS|] kit at all: no facing derivable, no
    exclusions knowable — the pre-C9 LRU behavior (minus the establish
    family) still places the reaction rather than dropping the floor."""
    moments = [
        _moment(1, "WS", "(SETUP A) wide establishing."),
        _moment(2, "MCU", "(SETUP B) Vanessa speaks.", speaker="Vanessa", line="Uno."),
        _moment(3, "MCU", "(SETUP C) Ryan speaks.", speaker="Ryan", line="Dos."),
        _moment(4, "MCU", "(SETUP B) Vanessa speaks.", speaker="Vanessa", line="Tres."),
    ]
    enforce_reaction_insert_floors(moments, setups_line=None,
                                   max_frames=len(_flatten_shots(moments)) + 2)
    reactions = [s for s in _flatten_shots(moments) if _shot_tag(s) == "REACTION"]
    assert reactions, "no kit line must not silently kill the reaction floor"
    for s in reactions:
        assert _shot_family(s) in {"B", "C"}, s["description"]


def test_floors_add_reactions_when_headroom_exists_above_masters_only_cap():
    """C8 fix (a) regression pin: the EXACT masters-only-at-cap scenario from
    test_floors_leave_violation_logged_when_no_safe_conversion_exists (every
    shot a master, angles_max=0 so nothing is ever convertible) — but now
    with max_frames carrying headroom ABOVE the master count (what
    coverage_to_app._coverage_shape's pure-dialogue branch now funds). The
    floor validator's ADD path (append a new angle to a moment) only fires
    when there's headroom; this proves it does, rather than falling into the
    "at the cap, no safe shot to convert" dead end the live dry run hit
    (Spanish Class scene 2: 8 reactions wanted, 0 placed, before this fix)."""
    moments = [
        _moment(1, "WS", "(SETUP A) wide two-shot establishing."),
        _moment(2, "MCU", "(SETUP B) Ryan speaks.", speaker="Ryan", line="Hello there."),
        _moment(3, "MCU", "(SETUP C) Vanessa speaks.", speaker="Vanessa", line="Hi Ryan."),
        _moment(4, "MCU", "(SETUP B) Ryan speaks again.", speaker="Ryan", line="How are you?"),
    ]
    total_before = len(_flatten_shots(moments))  # 4, all masters
    assert not any(_shot_tag(s) == "REACTION" for s in _flatten_shots(moments))
    n = enforce_reaction_insert_floors(moments, max_frames=total_before + 4)
    assert n >= 1
    reactions = [s for s in _flatten_shots(moments) if _shot_tag(s) == "REACTION"]
    assert len(reactions) >= 1, "headroom above the master count must let the floor ADD, not convert-or-fail"
    assert len(_flatten_shots(moments)) > total_before, \
        "with headroom, the floor grows the scene instead of leaving it unmet"


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


# =============================================================================
# C7 fix (a): sheet/pictures divergence — plan_moments_deterministic is the
# ONE shared pipeline (parse -> budget -> floors -> variety) both the sheet-
# planning path (coverage_to_app.py) and the real pictures path (run_coverage)
# must call, so a floor insertion or variety swap can never make an approved
# sheet's panel k disagree with the final picture's shot k.
# =============================================================================

def _sequence(moments):
    return [(s["shot_type"], s["description"]) for s in _flatten_shots(moments)]


_PARITY_FLOOR_DIRECTIVE = (
    "[SETUPS | A: wide two-shot; B: MCU on Ryan; C: MCU on Vanessa]\n"
    "[MOMENT 1 | opening]\n"
    "- MASTER [WS]: (SETUP A) Wide two-shot establishing the kitchen.\n"
    "[MOMENT 2 | Ryan speaks]\n"
    "LINE: Ryan | \"Hello there.\"\n"
    "- MASTER [MCU]: (SETUP B) Ryan speaks, looking at Vanessa.\n"
    "[MOMENT 3 | Vanessa speaks]\n"
    "LINE: Vanessa | \"Hi Ryan.\"\n"
    "- MASTER [MCU]: (SETUP C) Vanessa speaks, looking at Ryan.\n"
    "[MOMENT 4 | Ryan speaks again]\n"
    "LINE: Ryan | \"How are you?\"\n"
    "- MASTER [MCU]: (SETUP B) Ryan speaks again.\n"
)


def test_plan_moments_deterministic_matches_manual_pipeline_when_a_floor_fires():
    """(a) layer 1: plan_moments_deterministic must run parse -> budget ->
    floors -> variety, in that exact order, on the SAME directive_text — the
    ONE pipeline both coverage_to_app.py's sheet-planning path and
    run_coverage() now import and call, instead of each re-typing the call
    chain (the divergence that broke board-anchor panel mapping). This clean
    2-speaker, 3-turn dialogue earns exactly 1 REACTION floor shot (3 // 4,
    floored at 1) that a parse+budget-ONLY pipeline (the pre-fix sheet-
    planning behavior) would never have added — proving the shared function
    isn't just parse+budget in a trench coat."""
    moments = plan_moments_deterministic(_PARITY_FLOOR_DIRECTIVE, 10, 4, max_frames=None)
    assert moments is not None
    seq = _sequence(moments)
    assert len(seq) == 5, f"expected 4 planned masters + 1 REACTION floor shot, got {seq}"
    assert sum(1 for _, desc in seq if "(REACTION)" in desc) == 1

    # Manually chaining the SAME four calls, in the SAME order, on a FRESH
    # parse of the identical text must yield byte-identical output — pinning
    # the shared function's internal order, not merely its final count.
    manual = parse_coverage(_PARITY_FLOOR_DIRECTIVE)
    manual = enforce_shot_budget(manual, 10, 4, max_frames=None)
    enforce_reaction_insert_floors(manual, set_line=parse_set_dressing(_PARITY_FLOOR_DIRECTIVE),
                                   max_frames=None,
                                   # C9: the shared pipeline now threads the kit
                                   # line into the floors — the manual arm must
                                   # mirror it or the parity claim tests nothing.
                                   setups_line=parse_setups_line(_PARITY_FLOOR_DIRECTIVE))
    enforce_setup_variety(_flatten_shots(manual))
    assert _sequence(manual) == seq


def test_plan_moments_deterministic_matches_manual_pipeline_when_a_variety_swap_fires():
    """(a) layer 1, second fixture: a scene where enforce_setup_variety
    performs a REAL swap (not merely a flagged violation) — proves the
    shared pipeline's floors-then-variety ordering holds even when the
    LATER pass is the one that mutates content, not just the earlier one."""
    directive = (
        "[SETUPS | B: wide of the room; C: MCU on the table]\n"
        "[MOMENT 1 | beat one]\n"
        "- MASTER [WS]: (SETUP B) wide beat one.\n"
        "[MOMENT 2 | beat two]\n"
        "- MASTER [MS]: (SETUP B) medium beat two.\n"
        "- ANGLE [MS]: (SETUP B) angle beat two, same setup.\n"
        "[MOMENT 3 | beat three]\n"
        "- MASTER [MS]: (SETUP C) medium master beat three.\n"
        "- ANGLE [ECU]: (SETUP C) extreme close angle beat three.\n"
    )
    moments = plan_moments_deterministic(directive, 10, 4, max_frames=None)
    assert moments is not None
    seq = _sequence(moments)
    assert len(seq) == 5, f"no floor should fire on this silent, tiny scene, got {seq}"
    # The offending 3rd-consecutive-B shot (position 2, an angle) swapped with
    # the nearest safe different-family angle (position 4) — content moved.
    assert "extreme close angle beat three" in seq[2][1], seq
    assert "angle beat two, same setup" in seq[4][1], seq

    manual = parse_coverage(directive)
    manual = enforce_shot_budget(manual, 10, 4, max_frames=None)
    enforce_reaction_insert_floors(manual, set_line=parse_set_dressing(directive), max_frames=None)
    enforce_setup_variety(_flatten_shots(manual))
    assert _sequence(manual) == seq


# ---- board-anchor legacy-sheet guard (a, layer 2) --------------------------

_BOARD_ANCHOR_DIRECTIVE = (
    "[MOMENT 1 | opening]\n"
    "- MASTER [WS]: (SETUP A) Wide two-shot establishing the kitchen.\n"
    "- ANGLE [MCU]: (SETUP B) MCU on Dad.\n"
)


def _run_coverage_with_mocked_draw(board_urls, board_panel_total):
    """Drives run_coverage() for real through parse/budget/floors/variety,
    the tail locks, and the board-anchor block — but short-circuits the
    (real network/paid) cast resolution, per-shot draw, and download calls
    with recording fakes, so the test observes exactly what the board-anchor
    block stamped onto the shot dicts."""
    captured = []

    async def _fake_frames(moment, cast_url, image_client, profile=None, env_url=None,
                           aspect="16:9", resolution="1K", sem=None, model_override=None,
                           setup_anchors=None):
        captured.append(moment)
        frames = [{"role": "master", "shot_type": moment["master"]["shot_type"],
                  "description": moment["master"]["description"], "url": "https://img/m.png"}]
        for a in moment.get("angles") or []:
            frames.append({"role": "angle", "shot_type": a["shot_type"],
                           "description": a["description"], "url": "https://img/a.png"})
        return frames

    outdir = tempfile.mkdtemp()
    with patch("storyboard.coverage.resolve_cast_url", AsyncMock(return_value="https://cast.png")), \
         patch("storyboard.coverage.generate_coverage_frames", AsyncMock(side_effect=_fake_frames)), \
         patch("storyboard.coverage._download", lambda url, path: None):
        out = asyncio.run(run_coverage(
            beat_text="two people talk in a kitchen", image_client=None, outdir=outdir,
            cast_url="https://cast.png", directive_text=_BOARD_ANCHOR_DIRECTIVE,
            max_moments=10, angles_max=4, max_frames=None,
            board_urls=board_urls, board_panel_total=board_panel_total,
        ))
    assert not out.get("error"), out
    assert captured, "generate_coverage_frames must have been reached"
    return captured[0]


def test_board_anchor_skips_on_legacy_panel_count_mismatch():
    """(a) layer 2: board_panel_total is the TRUE panel count the approved
    sheets were planned with (read back from persisted bookkeeping by the
    caller, never re-derived from moments). When it disagrees with what THIS
    run just recomputed for the same directive (a legacy sheet planned before
    floors/variety existed, or before they ran in the sheet path too),
    anchoring must be SKIPPED for the scene — never pin a frame to the wrong
    approved panel."""
    m = _run_coverage_with_mocked_draw(["https://sheet1.png"], board_panel_total=99)
    assert "board_panel" not in m["master"], \
        "a mismatched board_panel_total must skip anchoring, not pin to the wrong panel"
    for a in m.get("angles") or []:
        assert "board_panel" not in a


def test_board_anchor_applies_normally_on_matching_panel_count():
    """(a) layer 2 counterpart: a MATCHING board_panel_total anchors exactly
    as before this fix — 2 shots (1 master + 1 angle) pinned to panels 1/2."""
    m = _run_coverage_with_mocked_draw(["https://sheet1.png"], board_panel_total=2)
    assert m["master"].get("board_panel") == 1
    assert m["master"].get("board_url") == "https://sheet1.png"
    assert m["angles"][0].get("board_panel") == 2


def test_board_anchor_applies_when_no_ground_truth_is_available():
    """(a) layer 2: board_panel_total=None (no persisted bookkeeping to
    compare against — e.g. an old row from before this fix) must preserve
    the prior anchor-unconditionally behavior, never a silent skip."""
    m = _run_coverage_with_mocked_draw(["https://sheet1.png"], board_panel_total=None)
    assert m["master"].get("board_panel") == 1
    assert m["angles"][0].get("board_panel") == 2


# =============================================================================
# D3-63: rule 5g — the face must be readable to camera on an expression/
# dialogue beat. Reproduces the live bug: video 686b4651 shot S-01.108, an
# eye-level MCU whose emotional payload IS the face ("face set and
# determined") written with the face turned away, pure profile, from the
# axis eyeline alone.
# =============================================================================

def test_facing_law_rule_present_and_structural():
    """The prompt actually states rule 5g: both legal framings (face-to-
    camera/three-quarter, and the explicit look-back geometry), and the
    explicit ban on a close 'expression' shot with the face just turned
    away — without weakening rule 5d's axis/eyeline law."""
    from shared.channel_profile import load_profile
    profile = load_profile({})
    prompt = _coverage_system_prompt(profile, max_moments=8, angles_min=2, angles_max=4)

    assert "5g)" in prompt
    rule_5g_start = prompt.index("5g)")
    rule_5g_text = prompt[rule_5g_start: prompt.index("\n7)", rule_5g_start)]

    assert "READABLE TO CAMERA" in rule_5g_text
    assert "FACE-TO-CAMERA" in rule_5g_text and "THREE-QUARTER" in rule_5g_text
    assert "LOOK-BACK" in rule_5g_text and "over the shoulder" in rule_5g_text.lower()
    assert "NEVER write a close" in rule_5g_text
    assert '"(REACTION)"' in rule_5g_text  # ties to rule 5f's tag, not a fresh vocabulary

    # must not weaken the axis/eyeline law rule 5d still owns.
    assert "rule 5d" in rule_5g_text
    assert "5d) THE 180-DEGREE RULE — THE CAMERA NEVER CROSSES THE AXIS" in prompt
    assert "frame-left/right eyeline stays exactly as the axis line" in rule_5g_text.lower() \
        or "frame-left/right eyeline stays exactly" in rule_5g_text


def test_carries_facing_law_identifies_structural_expression_shots():
    """(_carries_facing_law) the shared detector both the FACING LOCK stamp
    and check_facing_law_compliance use: REACTION angles, close sizes
    (MCU/CU/ECU), and a speaking master all carry the law; a plain WS
    establishing master and any INSERT (even a close one) never do."""
    speaking_moment = {"line": "One day, I will see the real sky."}
    silent_moment = {"line": None}

    reaction_shot = {"shot_type": "MCU", "description": "(SETUP C)(REACTION) MCU on Vanessa listening."}
    assert _carries_facing_law(silent_moment, reaction_shot, is_master=False) is True

    close_shot = {"shot_type": "CU", "description": "(SETUP C) NEUTRAL CU on Nyla's hand and face."}
    assert _carries_facing_law(silent_moment, close_shot, is_master=False) is True

    ecu_shot = {"shot_type": "ECU", "description": "(SETUP C) ECU on Nyla's eyes."}
    assert _carries_facing_law(silent_moment, ecu_shot, is_master=False) is True

    speaking_master = {"shot_type": "MCU", "description": "(SETUP B) MCU on Nyla speaking her line."}
    assert _carries_facing_law(speaking_moment, speaking_master, is_master=True) is True

    # A close size (MCU/CU/ECU) is presumed a face shot BY DEFAULT — reliably
    # detecting "this specific close shot's text happens to name an emotion"
    # from free prose isn't feasible (same reasoning check_facing_law_
    # compliance's docstring gives for not hard-gating), so any non-INSERT
    # close shot carries the law even with no LINE and no emotion word.
    silent_master_close_no_line = {"shot_type": "MCU", "description": "(SETUP B) MCU, no line here."}
    assert _carries_facing_law(silent_moment, silent_master_close_no_line, is_master=True) is True

    # A WIDE or medium (non-close) silent, non-speaking, non-REACTION shot
    # never carries it — the law is scoped to close/expression sizes only.
    wide_master = {"shot_type": "WS", "description": "(SETUP A) WS pod interior, establishing."}
    assert _carries_facing_law(silent_moment, wide_master, is_master=True) is False
    medium_angle = {"shot_type": "MS", "description": "(SETUP A) MS two-shot, both characters."}
    assert _carries_facing_law(silent_moment, medium_angle, is_master=False) is False
    # A non-close ANGLE never carries it even mid-dialogue moment — only the
    # speaking MASTER does (the LINE lives on the master, per rule 5).
    ots_angle_in_speaking_moment = {"shot_type": "OTS", "description": "(SETUP B) OTS over Ryan onto Nyla."}
    assert _carries_facing_law(speaking_moment, ots_angle_in_speaking_moment, is_master=False) is False

    # INSERT wins even on a close size — an insert has no face by definition
    # (see the INSERT tail: "no faces visible, detail only").
    insert_cu = {"shot_type": "CU", "description": "(SETUP E)(INSERT) Insert on the control panel."}
    assert _carries_facing_law(silent_moment, insert_cu, is_master=False) is False


def test_facing_law_compliance_flags_the_live_bug_pattern():
    """check_facing_law_compliance must flag the EXACT live pattern (video
    686b4651 shot S-01.108, quoted verbatim from the plan's own directive):
    an MCU whose text reads an emotion off the face ("face set and
    determined") but whose only orientation cue is a bare axis eyeline
    ("looking frame-right as she runs") — no face-to-camera or look-back
    language anywhere."""
    moments = [_moment(
        1, "MCU",
        "(SETUP E) MCU tracking at Nyla's eye level — Nyla (shoulder-length black shaggy hair, "
        "charcoal gray zip-up bodysuit) fills frame-left, face set and determined, looking "
        "frame-right as she runs; the pod columns blur into streaks of blue-white light behind "
        "her right shoulder, metal railings strobing past, her breath coming fast.",
    )]
    assert check_facing_law_compliance(moments) == 1


def test_facing_law_compliance_passes_an_explicit_look_back():
    """The SAME running beat, rewritten to satisfy rule 5g's look-back
    option, must NOT be flagged."""
    moments = [_moment(
        1, "MCU",
        "(SETUP E) MCU tracking at Nyla's eye level — Nyla fills frame-left, sprinting frame-"
        "RIGHT, glancing back over her shoulder at the camera, face square to the lens, jaw set "
        "and determined; the pod columns blur into streaks of blue-white light behind her.",
    )]
    assert check_facing_law_compliance(moments) == 0


def test_facing_law_compliance_passes_face_to_camera_framing():
    """A dialogue master phrased as face-to-camera/three-quarter (rule 5g
    option a) must not be flagged even though the axis tail elsewhere in a
    real prompt would also mention a frame-left/right eyeline."""
    moments = [_moment(
        1, "MCU", "(SETUP B) MCU, Nyla three-quarter to camera at the glass wall, her palm flat "
        "against the surface, lips moving with the whispered line.",
        speaker="Nyla", line="One day, I will see the real sky.",
    )]
    assert check_facing_law_compliance(moments) == 0


def test_facing_law_compliance_ignores_insert_and_wide_shots():
    """An INSERT (no faces by definition) and a plain WS establishing master
    with no line are never carriers, even when their prose happens to say
    'looking away' or 'looking frame-right' — the law doesn't apply to them
    at all, so this must never false-positive on set/prop/establishing
    prose."""
    moments = [_moment(
        1, "WS", "(SETUP A) WS pod interior, Nyla lying on the bed, eyes closed, facing away "
        "from the door.",
        angles=[{"shot_type": "INSERT",
                 "description": "(SETUP E)(INSERT) Insert on the control panel, looking frame-"
                                 "right toward the corridor, no faces visible, detail only."}],
    )]
    assert check_facing_law_compliance(moments) == 0


def test_facing_law_compliance_never_raises_on_empty_or_missing_fields():
    """Warning-only ALARM, same contract as check_prop_manifest_consistency
    — must be safe to call on minimal/legacy shot dicts, never raise."""
    assert check_facing_law_compliance([]) == 0
    minimal = [{"moment_number": 1, "summary": "x", "master": {"shot_type": None, "description": None},
                "angles": [], "speaker": None, "line": None}]
    assert check_facing_law_compliance(minimal) == 0


def test_run_coverage_facing_lock_applied_to_expression_shots(tmp_path):
    """(D3-63 repair leg) run_coverage's FACING LOCK tail — the SEQUENCE
    LOCK-pattern stamp that carries rule 5g into the shot's OWN stored draw
    prompt, so a later manual redraw inherits it too: a speaking MCU master
    and a (REACTION) angle both get the 'Facing lock:' tail; a plain WS
    establishing master and an (INSERT) angle never do."""
    directive = (
        "[MOMENT 1 | Nyla wakes]\n"
        "- MASTER [WS]: (SETUP A) WS pod interior establishing shot, Nyla asleep on the bed.\n"
        "\n"
        "[MOMENT 2 | Nyla whispers her wish]\n"
        'LINE: Nyla | "One day, I will see the real sky."\n'
        "- MASTER [MCU]: (SETUP B) MCU on Nyla at the glass wall, delivering her line.\n"
        "- ANGLE [MCU]: (SETUP C)(REACTION) MCU reaction, listening.\n"
        "- ANGLE [INSERT]: (SETUP E)(INSERT) Insert on the control panel, no faces visible.\n"
    )

    async def _fake_frames(moment, cast_url, image_client, profile=None, env_url=None,
                           aspect="16:9", resolution="1K", sem=None, model_override=None,
                           setup_anchors=None):
        frames = [{"role": "master", "shot_type": moment["master"]["shot_type"],
                  "description": moment["master"]["description"], "url": "https://img/m.png"}]
        for a in moment.get("angles") or []:
            frames.append({"role": "angle", "shot_type": a["shot_type"],
                           "description": a["description"], "url": "https://img/a.png"})
        return frames

    outdir = str(tmp_path)
    with patch("storyboard.coverage.resolve_cast_url", AsyncMock(return_value="https://cast.png")), \
         patch("storyboard.coverage.generate_coverage_frames", AsyncMock(side_effect=_fake_frames)), \
         patch("storyboard.coverage._download", lambda url, path: None):
        out = asyncio.run(run_coverage(
            beat_text="Nyla wakes and whispers her wish", image_client=None, outdir=outdir,
            cast_url="https://cast.png", directive_text=directive,
            max_moments=10, angles_max=4, max_frames=None,
        ))
    assert not out.get("error"), out
    m1, m2 = out["moments"][0], out["moments"][1]
    assert "Facing lock:" not in m1["master"]["description"]  # plain WS establishing, no facing law
    assert "Facing lock:" in m2["master"]["description"]  # speaking MCU master
    assert "Facing lock:" in m2["angles"][0]["description"]  # (REACTION) angle
    assert "Facing lock:" not in m2["angles"][1]["description"]  # (INSERT) angle, exempt


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
    test_enforce_setup_variety_never_swaps_a_reaction_tagged_offender()
    test_enforce_setup_variety_never_uses_an_insert_tagged_shot_as_a_candidate()
    test_setup_target_scales_with_max_moments()
    test_tension_sizing_guidance_present_in_user_prompt()
    test_inline_tag_regex_parses_reaction_and_insert()
    test_inline_tag_regex_never_matches_inside_a_setup_tag()
    test_reaction_floor_adds_shot_on_the_listener_for_a_key_line()
    test_reaction_floor_skipped_for_a_single_speaker_or_three_plus()
    test_insert_floor_is_roughly_one_per_six_to_eight_shots()
    test_re_establish_floor_is_roughly_one_per_ten_shots()
    test_re_establish_floor_phrasing_has_no_two_shot_or_character_count_claim()
    test_floors_convert_an_excess_shot_instead_of_adding_at_the_frame_cap()
    test_floors_leave_violation_logged_when_no_safe_conversion_exists()
    test_stamp_shot_durations_by_shot_size_and_skips_speaking_master()
    test_stamp_shot_durations_is_idempotent()
    test_plan_moments_deterministic_matches_manual_pipeline_when_a_floor_fires()
    test_plan_moments_deterministic_matches_manual_pipeline_when_a_variety_swap_fires()
    test_board_anchor_skips_on_legacy_panel_count_mismatch()
    test_board_anchor_applies_normally_on_matching_panel_count()
    test_board_anchor_applies_when_no_ground_truth_is_available()
    test_facing_law_rule_present_and_structural()
    test_carries_facing_law_identifies_structural_expression_shots()
    test_facing_law_compliance_flags_the_live_bug_pattern()
    test_facing_law_compliance_passes_an_explicit_look_back()
    test_facing_law_compliance_passes_face_to_camera_framing()
    test_facing_law_compliance_ignores_insert_and_wide_shots()
    test_facing_law_compliance_never_raises_on_empty_or_missing_fields()
    test_run_coverage_facing_lock_applied_to_expression_shots()
    print("ok — coverage parser + cast-builder self-checks passed")
