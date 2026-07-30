"""D9-6/D9-7: the second "Custom Film harvest" chunk (bundled with D9-6 —
transitions — and D9-7 — causality) — every planned coverage shot records
HOW it cuts in from what came before, and WHAT earlier shot caused it to
exist.

WHY THIS EXISTS: same 22-point film-studio audit as D9-1 (see
test_d9_1_shot_purpose.py). The dormant Custom Film director's ShotDraft
HARD-requires transition_from_previous + continuity_bridge
(backend/custom_film_director.py:288-291, :895-898) and caused_by (:280,
:882-884) on every shot; the flagship coverage pipeline planned shots with
neither signal at all. Ryan's ruling: harvest both, warn-only per the
standing D6 Ruling 1.

GRAMMAR CHOICE: TWO separate trailing rows — `TRANSITION: <kind> | <bridge>`
(rule 25) and `CAUSED_BY: <label>` (rule 26) — not one combined row. They are
independently optional, independently gated (four separate check_* functions
below), and Custom Film itself keeps them as separate ShotDraft fields;
folding them into one row would conflate two different warn conditions
behind one piece of text and complicate both the prompt and the parser for
no reduction in grammar surface (each is still its own "LABEL: part | part"
line, same as PURPOSE).

This file proves, in order:
  1. parse_coverage extracts transition_kind/continuity_bridge from a shot's
     own trailing "TRANSITION: <kind> | <bridge>" row (bridge optional), and
     caused_by from its own trailing "CAUSED_BY: <label>" row — regardless
     of what order the planner wrote the PURPOSE/TRANSITION/CAUSED_BY rows
     in, and regardless of which subset is present. None of the three rows
     ever survive into the stored description.
  2. BACKWARD COMPATIBILITY: the legacy SAMPLE fixture (zero metadata rows,
     predates D9-1) and a D9-1-era fixture (PURPOSE only, predates this
     chunk) both parse BYTE-IDENTICAL on shot_type/description; the new
     transition_kind/continuity_bridge/caused_by fields are simply absent
     (None), no crash.
  3. check_shot_transition_present / check_shot_transition_bridge_present /
     check_shot_causality_present / check_shot_causality_valid (the four new
     WARN-only gates) fire on the right shots and stay silent otherwise.
  4. generate_coverage_frames threads all three new fields into the frame
     dicts store_scene persists — and the row text never rides into the
     actual image-generation prompt.
  5. enforce_setup_variety's content swap carries transition_kind/
     continuity_bridge/caused_by along with shot_type/description/
     purpose_kind/shot_purpose.
  6. plan_moments_deterministic (the ONE shared sheet-preview + real-pictures
     pipeline) preserves all fields end to end, including a floor-added
     filler shot correctly landing with none.

Run:
    cd skills/video-pipeline && python -m pytest tests/test_d9_6_7_transition_causality.py -q
"""
import asyncio
import os
import sys

_PIPELINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PIPELINE_ROOT)
sys.path.insert(0, os.path.join(_PIPELINE_ROOT, "storyboard"))
sys.path.append(os.path.join(_PIPELINE_ROOT, "image_prompts"))

from storyboard.coverage import (  # noqa: E402
    parse_coverage, check_shot_transition_present, check_shot_transition_bridge_present,
    check_shot_causality_present, check_shot_causality_valid, generate_coverage_frames,
    enforce_setup_variety, plan_moments_deterministic,
)

# =============================================================================
# The exact pre-existing fixture from tests/test_coverage.py / test_d9_1_
# shot_purpose.py — no metadata rows of ANY kind.
# =============================================================================
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

# A D9-1-era fixture: PURPOSE rows present, no TRANSITION/CAUSED_BY at all —
# exactly what every real plan generated between D9-1 landing and this
# chunk landing looks like.
D9_1_ERA = (
    "[MOMENT 1 | Nyla pushes through the hatch]\n"
    "- MASTER [WS]: Ryan pushes through the pod's hatch into the corridor.\n"
    "PURPOSE: spatial | shows how Ryan gets from the pod to the corridor\n"
    "- ANGLE [MCU]: Close on Ryan's face as the door seals behind him.\n"
    "PURPOSE: emotion | the audience needs to see relief break through the tension\n"
)


# =============================================================================
# 1. Parsing: TRANSITION and CAUSED_BY present
# =============================================================================

def test_parse_transition_with_bridge_extracts_kind_and_bridge():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "TRANSITION: time_cut | the same dragon-scale pattern, now sun-bleached\n"
    )
    moments = parse_coverage(directive)
    master = moments[0]["master"]
    assert master["transition_kind"] == "time_cut"
    assert master["continuity_bridge"] == "the same dragon-scale pattern, now sun-bleached"
    assert "TRANSITION" not in master["description"]
    assert master["description"] == "wide of the launch."


def test_parse_transition_continuous_needs_no_bridge():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "TRANSITION: continuous\n"
    )
    moments = parse_coverage(directive)
    master = moments[0]["master"]
    assert master["transition_kind"] == "continuous"
    assert master["continuity_bridge"] is None


def test_parse_transition_kind_lowercased_and_tolerant_of_bold():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "**TRANSITION**: LOCATION_CUT | the same red door, different building\n"
    )
    moments = parse_coverage(directive)
    master = moments[0]["master"]
    assert master["transition_kind"] == "location_cut"
    assert master["continuity_bridge"] == "the same red door, different building"


def test_parse_caused_by_extracts_label():
    directive = (
        "[MOMENT 2 | x]\n"
        "- MASTER [MCU]: close on the door handle turning.\n"
        "CAUSED_BY: M1-MASTER\n"
    )
    moments = parse_coverage(directive)
    master = moments[0]["master"]
    assert master["caused_by"] == "M1-MASTER"
    assert "CAUSED_BY" not in master["description"]


def test_parse_caused_by_references_an_angle():
    directive = (
        "[MOMENT 2 | x]\n"
        "- MASTER [MCU]: close on the door handle turning.\n"
        "CAUSED_BY: M1-ANGLE2\n"
    )
    moments = parse_coverage(directive)
    assert moments[0]["master"]["caused_by"] == "M1-ANGLE2"


def test_parse_all_three_rows_together_any_order_never_cross_contaminate():
    """PURPOSE, TRANSITION, and CAUSED_BY stacked together (the taught
    order) must each extract independently, and the description must have
    all three peeled off, leaving only the original sentence."""
    directive = (
        "[MOMENT 2 | x]\n"
        "- MASTER [MCU]: close on the door handle turning.\n"
        "PURPOSE: story | opens the beat\n"
        "TRANSITION: continuous\n"
        "CAUSED_BY: M1-MASTER\n"
        "- ANGLE [CU]: reaction shot from behind.\n"
        "PURPOSE: emotion | shows tension\n"
        "TRANSITION: time_cut | the same door handle, now rusted\n"
        "CAUSED_BY: M2-MASTER\n"
    )
    moments = parse_coverage(directive)
    master, angle = moments[0]["master"], moments[0]["angles"][0]

    assert master["description"] == "close on the door handle turning."
    assert master["purpose_kind"] == "story" and master["shot_purpose"] == "opens the beat"
    assert master["transition_kind"] == "continuous" and master["continuity_bridge"] is None
    assert master["caused_by"] == "M1-MASTER"

    assert angle["description"] == "reaction shot from behind."
    assert angle["purpose_kind"] == "emotion" and angle["shot_purpose"] == "shows tension"
    assert angle["transition_kind"] == "time_cut"
    assert angle["continuity_bridge"] == "the same door handle, now rusted"
    assert angle["caused_by"] == "M2-MASTER"


def test_parse_rows_in_reversed_order_still_extract_correctly():
    """The prompt teaches PURPOSE-then-TRANSITION-then-CAUSED_BY, but a real
    LLM won't always follow row order exactly — extraction must not depend
    on it (this is the whole reason _strip_shot_metadata_rows picks the
    latest-starting candidate each pass instead of a fixed priority order)."""
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide shot.\n"
        "CAUSED_BY: M0-MASTER\n"
        "TRANSITION: montage | quick cuts\n"
        "PURPOSE: action | shows movement\n"
    )
    moments = parse_coverage(directive)
    master = moments[0]["master"]
    assert master["description"] == "wide shot."
    assert master["purpose_kind"] == "action" and master["shot_purpose"] == "shows movement"
    assert master["transition_kind"] == "montage" and master["continuity_bridge"] == "quick cuts"
    assert master["caused_by"] == "M0-MASTER"


def test_parse_partial_subset_transition_and_caused_by_no_purpose():
    """Only TWO of the three optional rows present (no PURPOSE at all) must
    still extract cleanly — proves the loop doesn't require all three."""
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide shot.\n"
        "TRANSITION: location_cut | new room\n"
        "CAUSED_BY: M0-ANGLE1\n"
    )
    moments = parse_coverage(directive)
    master = moments[0]["master"]
    assert master["description"] == "wide shot."
    assert master["purpose_kind"] is None and master["shot_purpose"] is None
    assert master["transition_kind"] == "location_cut" and master["continuity_bridge"] == "new room"
    assert master["caused_by"] == "M0-ANGLE1"


def test_parse_absent_on_one_shot_present_on_another_same_moment():
    """Per-shot independence, same discipline as D9-1's equivalent test."""
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "- ANGLE [MCU]: closer on the rider.\n"
        "TRANSITION: memory | the same lullaby hums under both\n"
        "CAUSED_BY: M1-MASTER\n"
    )
    moments = parse_coverage(directive)
    master, angle = moments[0]["master"], moments[0]["angles"][0]
    assert master["transition_kind"] is None and master["caused_by"] is None
    assert angle["transition_kind"] == "memory" and angle["caused_by"] == "M1-MASTER"


# =============================================================================
# 2. BACKWARD COMPATIBILITY
# =============================================================================

def test_legacy_directive_parses_byte_identical_new_fields_absent():
    """SAMPLE (zero metadata rows of ANY kind) parses EXACTLY as before —
    same assertions as D9-1's own legacy test, plus the three new fields
    all None."""
    moments = parse_coverage(SAMPLE)
    assert len(moments) == 2
    m1 = moments[0]
    assert m1["master"]["shot_type"] == "WS"
    assert m1["master"]["description"] == (
        "Wide shot, the young rider in a leather flight harness stands beside the bronze "
        "dragon on a cliff ledge, dawn light raking from screen-left.")
    assert len(m1["angles"]) == 2
    assert [a["shot_type"] for a in m1["angles"]] == ["MCU", "INSERT"]
    m2 = moments[1]
    assert m2["master"]["shot_type"] == "ELS"
    assert [a["shot_type"] for a in m2["angles"]] == ["OTS"]

    for m in moments:
        for shot in [m["master"], *m["angles"]]:
            assert shot["purpose_kind"] is None and shot["shot_purpose"] is None
            assert shot["transition_kind"] is None and shot["continuity_bridge"] is None
            assert shot["caused_by"] is None


def test_d9_1_era_directive_parses_byte_identical_new_fields_absent():
    """A plan generated AFTER D9-1 landed but BEFORE this chunk did (PURPOSE
    rows present, no TRANSITION/CAUSED_BY) must keep its purpose fields
    exactly as D9-1 parsed them, with the two NEW field pairs simply None —
    the real-world upgrade path this chunk has to not break."""
    moments = parse_coverage(D9_1_ERA)
    assert len(moments) == 1
    master, angle = moments[0]["master"], moments[0]["angles"][0]
    assert master["description"] == "Ryan pushes through the pod's hatch into the corridor."
    assert master["purpose_kind"] == "spatial"
    assert master["shot_purpose"] == "shows how Ryan gets from the pod to the corridor"
    assert master["transition_kind"] is None and master["continuity_bridge"] is None
    assert master["caused_by"] is None
    assert angle["purpose_kind"] == "emotion"
    assert angle["transition_kind"] is None and angle["caused_by"] is None


def test_legacy_directive_check_gates_do_not_crash_and_flag_every_shot():
    """All four new WARN gates must run cleanly over a plan with zero
    TRANSITION/CAUSED_BY rows — no crash. transition_present flags all 5
    shots (none tagged). causality_present flags 4 of 5 (every shot except
    the scene's true first, moment 1's master, is exempt-free of that
    exemption). Neither bridge nor validity check has anything to flag
    (bridge check only fires on a shot that HAS a kind; validity check only
    fires on a shot that HAS a caused_by — legacy has neither)."""
    moments = parse_coverage(SAMPLE)
    assert check_shot_transition_present(moments) == 5
    assert check_shot_transition_bridge_present(moments) == 0
    assert check_shot_causality_present(moments) == 4
    assert check_shot_causality_valid(moments) == 0


# =============================================================================
# 3. The four WARN gates
# =============================================================================

def test_check_shot_transition_present_silent_when_every_shot_tagged():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "TRANSITION: opening\n"
        "- ANGLE [MCU]: closer on the rider.\n"
        "TRANSITION: continuous\n"
    )
    moments = parse_coverage(directive)
    assert check_shot_transition_present(moments) == 0


def test_check_shot_transition_present_flags_only_the_untagged_shot():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "TRANSITION: opening\n"
        "- ANGLE [MCU]: closer on the rider, no transition row here.\n"
    )
    moments = parse_coverage(directive)
    assert check_shot_transition_present(moments) == 1


def test_check_shot_transition_bridge_present_silent_for_continuous():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "TRANSITION: continuous\n"
    )
    moments = parse_coverage(directive)
    assert check_shot_transition_bridge_present(moments) == 0


def test_check_shot_transition_bridge_present_flags_missing_bridge():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "TRANSITION: time_cut\n"
    )
    moments = parse_coverage(directive)
    assert check_shot_transition_bridge_present(moments) == 1


def test_check_shot_transition_bridge_present_silent_when_bridge_stated():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "TRANSITION: montage | the same drumbeat under every cut\n"
    )
    moments = parse_coverage(directive)
    assert check_shot_transition_bridge_present(moments) == 0


def test_check_shot_transition_bridge_present_silent_for_opening():
    """"opening" is exempt from needing a bridge, same as "continuous" — in
    Custom Film's own model an opening shot is structurally always the
    scene's first, so it never has anything to bridge from."""
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "TRANSITION: opening\n"
    )
    moments = parse_coverage(directive)
    assert check_shot_transition_bridge_present(moments) == 0


def test_check_shot_transition_bridge_present_does_not_double_count_untagged():
    """A shot with NO transition_kind at all is check_shot_transition_
    present's problem, not this check's — must not also flag it here."""
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch, no transition row at all.\n"
    )
    moments = parse_coverage(directive)
    assert check_shot_transition_present(moments) == 1
    assert check_shot_transition_bridge_present(moments) == 0


def test_check_shot_causality_present_exempts_only_the_true_first_shot():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "- ANGLE [MCU]: closer on the rider.\n"
        "CAUSED_BY: M1-MASTER\n"
        "[MOMENT 2 | y]\n"
        "- MASTER [MCU]: door opens.\n"
        "CAUSED_BY: M1-MASTER\n"
    )
    moments = parse_coverage(directive)
    # Only the moment-1 master (the scene's true first shot) is exempt.
    assert check_shot_causality_present(moments) == 0


def test_check_shot_causality_present_flags_uncaused_non_first_shot():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "- ANGLE [MCU]: closer on the rider, no caused_by here.\n"
    )
    moments = parse_coverage(directive)
    assert check_shot_causality_present(moments) == 1


def test_check_shot_causality_valid_flags_nonexistent_reference():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "- ANGLE [MCU]: closer on the rider.\n"
        "CAUSED_BY: M9-MASTER\n"
    )
    moments = parse_coverage(directive)
    assert check_shot_causality_valid(moments) == 1


def test_check_shot_causality_valid_flags_forward_reference():
    """A shot claiming to be caused by a LATER shot — deterministically
    wrong, still warn-only."""
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "CAUSED_BY: M2-MASTER\n"
        "[MOMENT 2 | y]\n"
        "- MASTER [MCU]: door opens.\n"
        "CAUSED_BY: M1-MASTER\n"
    )
    moments = parse_coverage(directive)
    assert check_shot_causality_valid(moments) == 1


def test_check_shot_causality_valid_flags_self_reference():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "- ANGLE [MCU]: closer on the rider.\n"
        "CAUSED_BY: M1-ANGLE1\n"
    )
    moments = parse_coverage(directive)
    assert check_shot_causality_valid(moments) == 1


def test_check_shot_causality_valid_silent_for_correct_earlier_reference():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "- ANGLE [MCU]: closer on the rider.\n"
        "CAUSED_BY: M1-MASTER\n"
        "[MOMENT 2 | y]\n"
        "- MASTER [MCU]: door opens.\n"
        "CAUSED_BY: M1-ANGLE1\n"
    )
    moments = parse_coverage(directive)
    assert check_shot_causality_valid(moments) == 0


# =============================================================================
# 4. generate_coverage_frames threads the fields — and the row text never
#    rides into the actual draw prompt.
# =============================================================================

class _FakeImageClientForFrames:
    SCENE_MODEL = "nano-banana-2"

    def __init__(self):
        self.calls = []

    async def generate_scene_image_zimage(self, prompt, aspect_ratio="16:9", **_kwargs):
        self.calls.append(("generate_scene_image_zimage", prompt, aspect_ratio))
        return {"url": f"https://img/{len(self.calls)}.png"}


def test_generate_coverage_frames_threads_transition_and_causality_fields():
    moment = {
        "moment_number": 2,
        "master": {
            "shot_type": "WS", "description": "wide shot of the rider at dawn",
            "purpose_kind": "spatial", "shot_purpose": "establishes where the rider stands",
            "transition_kind": "time_cut", "continuity_bridge": "the same harness buckle",
            "caused_by": "M1-MASTER",
        },
        "angles": [{
            "shot_type": "MCU", "description": "close on the rider's face",
            "purpose_kind": "emotion", "shot_purpose": "the audience needs to see her resolve",
            "transition_kind": "continuous", "continuity_bridge": None,
            "caused_by": "M2-MASTER",
        }],
    }
    ic = _FakeImageClientForFrames()
    frames = asyncio.run(generate_coverage_frames(
        moment, "https://cast.png", ic, None, aspect="16:9", resolution="1K",
        model_override="z-image"))
    assert frames is not None and len(frames) == 2
    master, angle = frames
    assert master["transition_kind"] == "time_cut"
    assert master["continuity_bridge"] == "the same harness buckle"
    assert master["caused_by"] == "M1-MASTER"
    assert angle["transition_kind"] == "continuous"
    assert angle["continuity_bridge"] is None
    assert angle["caused_by"] == "M2-MASTER"


def test_generate_coverage_frames_transition_and_causality_text_never_reaches_the_draw_prompt():
    """Same proof as D9-1's marker test, extended to the two new free-text
    fields — continuity_bridge is prose, and even caused_by's label
    shouldn't leak (it's edit bookkeeping, not a drawing instruction)."""
    moment = {
        "moment_number": 1,
        "master": {
            "shot_type": "WS", "description": "wide shot of the rider at dawn",
            "purpose_kind": None, "shot_purpose": None,
            "transition_kind": "time_cut",
            "continuity_bridge": "UNMISTAKABLE_BRIDGE_MARKER_TEXT_7c2e",
            "caused_by": "UNMISTAKABLE_CAUSEDBY_MARKER_M1-MASTER",
        },
        "angles": [],
    }
    ic = _FakeImageClientForFrames()
    frames = asyncio.run(generate_coverage_frames(
        moment, "https://cast.png", ic, None, aspect="16:9", resolution="1K",
        model_override="z-image"))
    assert frames is not None and len(frames) == 1
    prompt = ic.calls[0][1]
    assert "UNMISTAKABLE_BRIDGE_MARKER_TEXT_7c2e" not in prompt
    assert "UNMISTAKABLE_CAUSEDBY_MARKER_M1-MASTER" not in prompt
    assert "TRANSITION" not in prompt
    assert "CAUSED_BY" not in prompt


# =============================================================================
# 5. Fields travel WITH content through a variety-swap
# =============================================================================

def _flat(*shots):
    """Mirrors test_d9_1_shot_purpose.py's local _flat helper, extended with
    transition_kind/continuity_bridge/caused_by."""
    out = []
    for i, spec in enumerate(shots):
        fam, role = spec[0], spec[1]
        mi = spec[2] if len(spec) > 2 else 0
        transition_kind = spec[3] if len(spec) > 3 else None
        continuity_bridge = spec[4] if len(spec) > 4 else None
        caused_by = spec[5] if len(spec) > 5 else None
        out.append({"shot_type": "MS", "role": role, "_mi": mi,
                    "description": f"(SETUP {fam}) placeholder shot {i}.",
                    "purpose_kind": None, "shot_purpose": None,
                    "transition_kind": transition_kind, "continuity_bridge": continuity_bridge,
                    "caused_by": caused_by})
    return out


def test_enforce_setup_variety_swaps_transition_and_causality_fields_with_content():
    flat = _flat(
        ("B", "master", 0, "opening"),
        ("B", "angle", 0, "continuous", None, "M0-MASTER"),
        ("B", "angle", 0, "time_cut", "offending shot's own bridge (will move)", "M0-ANGLE1"),
        ("C", "angle", 0, "location_cut", "swap candidate's own bridge (will move)", "M0-MASTER"),
    )
    n = enforce_setup_variety(flat)
    assert n == 1
    # Content swapped (same assertion shape as D9-1's equivalent test)...
    assert flat[2]["description"] == "(SETUP C) placeholder shot 3."
    assert flat[3]["description"] == "(SETUP B) placeholder shot 2."
    # ...and transition/causality fields swapped RIGHT ALONG WITH IT.
    assert flat[2]["transition_kind"] == "location_cut"
    assert flat[2]["continuity_bridge"] == "swap candidate's own bridge (will move)"
    assert flat[2]["caused_by"] == "M0-MASTER"
    assert flat[3]["transition_kind"] == "time_cut"
    assert flat[3]["continuity_bridge"] == "offending shot's own bridge (will move)"
    assert flat[3]["caused_by"] == "M0-ANGLE1"
    # The untouched master keeps its own fields.
    assert flat[0]["transition_kind"] == "opening"
    assert flat[0]["caused_by"] is None


# =============================================================================
# 6. plan_moments_deterministic preserves all fields end to end, including
#    when a floor adds a code-synthesized shot with none.
# =============================================================================

def test_plan_moments_deterministic_preserves_transition_and_causality_through_full_pipeline():
    directive = (
        "[SETUPS | A: wide two-shot; B: MCU on Ryan; C: MCU on Vanessa]\n"
        "[MOMENT 1 | opening]\n"
        "- MASTER [WS]: (SETUP A) Wide two-shot establishing the kitchen.\n"
        "TRANSITION: opening\n"
        "[MOMENT 2 | Ryan speaks]\n"
        "LINE: Ryan | \"Hello there.\"\n"
        "- MASTER [MCU]: (SETUP B) Ryan speaks, looking at Vanessa.\n"
        "TRANSITION: continuous\n"
        "CAUSED_BY: M1-MASTER\n"
        "[MOMENT 3 | Vanessa speaks]\n"
        "LINE: Vanessa | \"Hi Ryan.\"\n"
        "- MASTER [MCU]: (SETUP C) Vanessa speaks, looking at Ryan.\n"
        "TRANSITION: continuous\n"
        "CAUSED_BY: M2-MASTER\n"
        "[MOMENT 4 | Ryan speaks again]\n"
        "LINE: Ryan | \"How are you?\"\n"
        "- MASTER [MCU]: (SETUP B) Ryan speaks again.\n"
        "TRANSITION: time_cut | the same steam rising off the same mug\n"
        "CAUSED_BY: M3-MASTER\n"
    )
    moments = plan_moments_deterministic(directive, 10, 4, max_frames=None)
    assert moments is not None
    flat = [shot for m in moments for shot in [m["master"], *(m.get("angles") or [])]]
    # 4 planned masters + exactly 1 REACTION floor shot (same shape as D9-1's
    # equivalent test — this directive is modeled on the same fixture).
    assert len(flat) == 5

    tagged = [s for s in flat if s.get("transition_kind")]
    assert len(tagged) == 4
    assert {s["transition_kind"] for s in tagged} == {"opening", "continuous", "time_cut"}

    # The floor-added REACTION shot has no LLM prose to draw a transition/
    # cause from — None, not a crash.
    untagged = [s for s in flat if not s.get("transition_kind")]
    assert len(untagged) == 1
    assert untagged[0].get("caused_by") is None

    transition_warnings = check_shot_transition_present(moments)
    assert transition_warnings == 1
    # The floor shot is also uncaused (it isn't the scene's first shot).
    causality_warnings = check_shot_causality_present(moments)
    assert causality_warnings == 1
    # Every stated caused_by in this fixture references a real, earlier shot.
    assert check_shot_causality_valid(moments) == 0
    # Every stated transition either is "continuous" or carries a bridge.
    assert check_shot_transition_bridge_present(moments) == 0


if __name__ == "__main__":
    test_parse_transition_with_bridge_extracts_kind_and_bridge()
    test_parse_transition_continuous_needs_no_bridge()
    test_parse_transition_kind_lowercased_and_tolerant_of_bold()
    test_parse_caused_by_extracts_label()
    test_parse_caused_by_references_an_angle()
    test_parse_all_three_rows_together_any_order_never_cross_contaminate()
    test_parse_rows_in_reversed_order_still_extract_correctly()
    test_parse_partial_subset_transition_and_caused_by_no_purpose()
    test_parse_absent_on_one_shot_present_on_another_same_moment()
    test_legacy_directive_parses_byte_identical_new_fields_absent()
    test_d9_1_era_directive_parses_byte_identical_new_fields_absent()
    test_legacy_directive_check_gates_do_not_crash_and_flag_every_shot()
    test_check_shot_transition_present_silent_when_every_shot_tagged()
    test_check_shot_transition_present_flags_only_the_untagged_shot()
    test_check_shot_transition_bridge_present_silent_for_continuous()
    test_check_shot_transition_bridge_present_flags_missing_bridge()
    test_check_shot_transition_bridge_present_silent_when_bridge_stated()
    test_check_shot_transition_bridge_present_silent_for_opening()
    test_check_shot_transition_bridge_present_does_not_double_count_untagged()
    test_check_shot_causality_present_exempts_only_the_true_first_shot()
    test_check_shot_causality_present_flags_uncaused_non_first_shot()
    test_check_shot_causality_valid_flags_nonexistent_reference()
    test_check_shot_causality_valid_flags_forward_reference()
    test_check_shot_causality_valid_flags_self_reference()
    test_check_shot_causality_valid_silent_for_correct_earlier_reference()
    test_generate_coverage_frames_threads_transition_and_causality_fields()
    test_generate_coverage_frames_transition_and_causality_text_never_reaches_the_draw_prompt()
    test_enforce_setup_variety_swaps_transition_and_causality_fields_with_content()
    test_plan_moments_deterministic_preserves_transition_and_causality_through_full_pipeline()
    print("ok — D9-6/D9-7 transition/causality tests passed")
