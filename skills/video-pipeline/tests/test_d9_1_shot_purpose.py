"""D9-1: the first "Custom Film harvest" chunk — every planned coverage shot
records WHY it exists.

WHY THIS EXISTS: the 22-point film-studio audit found the flagship coverage
pipeline's shots carry no motivation at all ({shot_type, description} only),
while the dormant Custom Film director hard-requires narrative_purpose +
progression_kinds per shot (backend/custom_film_director.py's ShotDraft,
~line 279-284). Ryan's ruling: harvest that schema into the flagship,
enforcement per the standing D6 Ruling 1 — a gate may only be HARD when it
compares against something CANONICAL; a missing prose field WARNS, never
blocks.

This file proves, in order:
  1. parse_coverage extracts purpose_kind/shot_purpose from a shot's own
     trailing "PURPOSE: <kind> | <text>" row, and the row never survives
     into the stored description.
  2. BACKWARD COMPATIBILITY: SAMPLE — the exact pre-existing fixture
     test_coverage.py has used since before this chunk existed — parses
     BYTE-IDENTICAL on shot_type/description; purpose fields are simply
     absent (None), no crash.
  3. check_shot_purpose_present (the new WARN-only gate) fires on shots with
     no purpose and stays silent when every shot has one.
  4. generate_coverage_frames threads purpose_kind/shot_purpose into the
     frame dicts store_scene persists — and the PURPOSE row text never
     rides into the actual image-generation prompt (the whole reason this
     tag lives on its own line instead of inside the shot's description
     sentence — rule 23/L27, INSTRUCTIONS ARE NOT CAPTIONS).
  5. enforce_setup_variety's content swap carries purpose_kind/shot_purpose
     along with shot_type/description, so a swap never leaves a shot's
     stated purpose describing a framing that no longer lives there.

Run:
    cd skills/video-pipeline && python -m pytest tests/test_d9_1_shot_purpose.py -q
"""
import asyncio
import os
import sys

_PIPELINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PIPELINE_ROOT)
sys.path.insert(0, os.path.join(_PIPELINE_ROOT, "storyboard"))
sys.path.append(os.path.join(_PIPELINE_ROOT, "image_prompts"))

from storyboard.coverage import (  # noqa: E402
    parse_coverage, check_shot_purpose_present, generate_coverage_frames,
    enforce_setup_variety, plan_moments_deterministic,
)

# =============================================================================
# The exact pre-existing fixture from tests/test_coverage.py (predates this
# chunk) — a REAL directive shape already relied on elsewhere, not something
# synthesized for this PR. No "PURPOSE:" row anywhere in it.
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


# =============================================================================
# 1. Parsing: PURPOSE present
# =============================================================================

def test_parse_purpose_present_extracts_kind_and_text():
    directive = (
        "[MOMENT 1 | Nyla pushes through the hatch]\n"
        "- MASTER [WS]: (SETUP F)(BRIDGE) Ryan pushes through the pod's hatch into the corridor, "
        "harsh fluorescent light replacing the pod's blue glow.\n"
        "PURPOSE: spatial | shows the audience exactly how Ryan gets from the pod to the corridor\n"
        "- ANGLE [MCU]: (SETUP F) Close on Ryan's face as the door seals behind him.\n"
        "PURPOSE: emotion | the audience needs to see relief break through the tension\n"
    )
    moments = parse_coverage(directive)
    assert len(moments) == 1
    master = moments[0]["master"]
    angle = moments[0]["angles"][0]

    assert master["purpose_kind"] == "spatial"
    assert master["shot_purpose"] == "shows the audience exactly how Ryan gets from the pod to the corridor"
    assert angle["purpose_kind"] == "emotion"
    assert angle["shot_purpose"] == "the audience needs to see relief break through the tension"

    # The PURPOSE row must NEVER survive into the stored description — it is
    # metadata for the edit, not prose for the drawer (rule 23/L27).
    assert "PURPOSE" not in master["description"]
    assert "PURPOSE" not in angle["description"]
    assert master["description"] == (
        "(SETUP F)(BRIDGE) Ryan pushes through the pod's hatch into the corridor, "
        "harsh fluorescent light replacing the pod's blue glow.")
    assert angle["description"] == "(SETUP F) Close on Ryan's face as the door seals behind him."


def test_parse_purpose_kind_is_lowercased_and_tolerant_of_bold():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: **wide of the launch.**\n"
        "**PURPOSE**: INFORMATION | establishes the location before anything else happens\n"
    )
    moments = parse_coverage(directive)
    master = moments[0]["master"]
    assert master["purpose_kind"] == "information"
    assert master["shot_purpose"] == "establishes the location before anything else happens"


def test_parse_purpose_absent_on_one_shot_present_on_another_same_moment():
    """Per-shot independence: a MASTER with no PURPOSE row and an ANGLE with
    one, in the SAME moment, must not cross-contaminate."""
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "- ANGLE [MCU]: closer on the rider.\n"
        "PURPOSE: action | shows the rider's grip tighten before the jump\n"
    )
    moments = parse_coverage(directive)
    master, angle = moments[0]["master"], moments[0]["angles"][0]
    assert master["purpose_kind"] is None
    assert master["shot_purpose"] is None
    assert angle["purpose_kind"] == "action"
    assert angle["shot_purpose"] == "shows the rider's grip tighten before the jump"


# =============================================================================
# 2. BACKWARD COMPATIBILITY — the decisive test
# =============================================================================

def test_legacy_directive_parses_byte_identical_purpose_fields_absent():
    """SAMPLE predates this chunk (it's the fixture test_coverage.py already
    used for test_parses_two_moments). Parsing it after this chunk must
    reproduce EXACTLY the same shot_type/description output as before, with
    purpose_kind/shot_purpose simply present-but-None — never a crash, never
    a changed description."""
    moments = parse_coverage(SAMPLE)
    assert len(moments) == 2

    m1 = moments[0]
    assert m1["moment_number"] == 1
    assert m1["master"]["shot_type"] == "WS"
    assert "flight harness" in m1["master"]["description"]
    assert m1["master"]["description"] == (
        "Wide shot, the young rider in a leather flight harness stands beside the bronze "
        "dragon on a cliff ledge, dawn light raking from screen-left.")
    assert len(m1["angles"]) == 2
    assert [a["shot_type"] for a in m1["angles"]] == ["MCU", "INSERT"]

    m2 = moments[1]
    assert m2["master"]["shot_type"] == "ELS"
    assert [a["shot_type"] for a in m2["angles"]] == ["OTS"]

    # Every shot in this legacy plan carries the two new fields, both None —
    # present, never absent as a KeyError risk, but unset.
    for m in moments:
        for shot in [m["master"], *m["angles"]]:
            assert shot["purpose_kind"] is None
            assert shot["shot_purpose"] is None


def test_legacy_directive_check_gate_does_not_crash_and_flags_every_shot():
    """The WARN gate must run cleanly over a plan with zero PURPOSE rows
    (every plan generated before this chunk) — no crash, and it flags every
    shot (5 total: 2 masters + 3 angles), since none carries a stated
    purpose. That is the intended signal on legacy data, not a bug."""
    moments = parse_coverage(SAMPLE)
    n = check_shot_purpose_present(moments)
    assert n == 5


# =============================================================================
# 3. The WARN gate
# =============================================================================

def test_check_shot_purpose_present_silent_when_every_shot_tagged():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "PURPOSE: story | opens the scene on the launch itself\n"
        "- ANGLE [MCU]: closer on the rider.\n"
        "PURPOSE: emotion | shows fear breaking through resolve\n"
    )
    moments = parse_coverage(directive)
    assert check_shot_purpose_present(moments) == 0


def test_check_shot_purpose_present_flags_only_the_untagged_shot():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "PURPOSE: story | opens the scene on the launch itself\n"
        "- ANGLE [MCU]: closer on the rider, no purpose row here.\n"
    )
    moments = parse_coverage(directive)
    assert check_shot_purpose_present(moments) == 1


# =============================================================================
# 4. generate_coverage_frames threads the fields — and the PURPOSE text never
#    rides into the actual draw prompt.
# =============================================================================

class _FakeImageClientForFrames:
    SCENE_MODEL = "nano-banana-2"

    def __init__(self):
        self.calls = []

    async def generate_scene_image_zimage(self, prompt, aspect_ratio="16:9", **_kwargs):
        self.calls.append(("generate_scene_image_zimage", prompt, aspect_ratio))
        return {"url": f"https://img/{len(self.calls)}.png"}


def test_generate_coverage_frames_threads_purpose_fields_onto_frame_dicts():
    moment = {
        "moment_number": 1,
        "master": {
            "shot_type": "WS", "description": "wide shot of the rider at dawn",
            "purpose_kind": "spatial", "shot_purpose": "establishes where the rider stands",
        },
        "angles": [{
            "shot_type": "MCU", "description": "close on the rider's face",
            "purpose_kind": "emotion", "shot_purpose": "the audience needs to see her resolve",
        }],
    }
    ic = _FakeImageClientForFrames()
    frames = asyncio.run(generate_coverage_frames(
        moment, "https://cast.png", ic, None, aspect="16:9", resolution="1K",
        model_override="z-image"))
    assert frames is not None and len(frames) == 2
    master, angle = frames
    assert master["purpose_kind"] == "spatial"
    assert master["shot_purpose"] == "establishes where the rider stands"
    assert angle["purpose_kind"] == "emotion"
    assert angle["shot_purpose"] == "the audience needs to see her resolve"


def test_generate_coverage_frames_purpose_text_never_reaches_the_draw_prompt():
    """The whole reason PURPOSE lives on its own line (never inside the
    shot's description sentence): it must not leak into what the image
    model actually sees. Prove it end to end — a shot dict whose
    shot_purpose text is present must not appear anywhere in the prompt
    string generate_coverage_frames sends to the provider."""
    moment = {
        "moment_number": 1,
        "master": {
            "shot_type": "WS", "description": "wide shot of the rider at dawn",
            "purpose_kind": "spatial",
            "shot_purpose": "UNMISTAKABLE_PURPOSE_MARKER_TEXT_9f3a",
        },
        "angles": [],
    }
    ic = _FakeImageClientForFrames()
    frames = asyncio.run(generate_coverage_frames(
        moment, "https://cast.png", ic, None, aspect="16:9", resolution="1K",
        model_override="z-image"))
    assert frames is not None and len(frames) == 1
    prompt = ic.calls[0][1]
    assert "UNMISTAKABLE_PURPOSE_MARKER_TEXT_9f3a" not in prompt
    assert "PURPOSE" not in prompt


# =============================================================================
# 5. Purpose fields travel WITH content through a variety-swap
# =============================================================================

def _flat(*shots):
    """Minimal flat_shots builder (mirrors test_coverage.py's own _flat, kept
    local so this file has no cross-file test dependency)."""
    out = []
    for i, spec in enumerate(shots):
        fam, role = spec[0], spec[1]
        mi = spec[2] if len(spec) > 2 else 0
        purpose_kind = spec[3] if len(spec) > 3 else None
        shot_purpose = spec[4] if len(spec) > 4 else None
        out.append({"shot_type": "MS", "role": role, "_mi": mi,
                    "description": f"(SETUP {fam}) placeholder shot {i}.",
                    "purpose_kind": purpose_kind, "shot_purpose": shot_purpose})
    return out


def test_enforce_setup_variety_swaps_purpose_fields_with_content():
    """Mirrors test_coverage.py's test_enforce_setup_variety_fixes_with_a_
    safe_angle_swap (same fixture shape), but proves purpose_kind/
    shot_purpose move WITH shot_type/description — a swap that left them
    behind would make position 2 claim a purpose about content that no
    longer lives there."""
    flat = _flat(
        ("B", "master", 0, "story", "opens on the two-shot"),
        ("B", "angle", 0, "action", "purpose for offending shot 1"),
        ("B", "angle", 0, "emotion", "purpose for offending shot 2 (will move)"),
        ("C", "angle", 0, "information", "purpose for the swap candidate (will move)"),
    )
    n = enforce_setup_variety(flat)
    assert n == 1
    # Content swapped (same assertion shape as the upstream test)...
    assert flat[2]["description"] == "(SETUP C) placeholder shot 3."
    assert flat[3]["description"] == "(SETUP B) placeholder shot 2."
    # ...and purpose fields swapped RIGHT ALONG WITH IT.
    assert flat[2]["purpose_kind"] == "information"
    assert flat[2]["shot_purpose"] == "purpose for the swap candidate (will move)"
    assert flat[3]["purpose_kind"] == "emotion"
    assert flat[3]["shot_purpose"] == "purpose for offending shot 2 (will move)"
    # The untouched master keeps its own purpose.
    assert flat[0]["purpose_kind"] == "story"
    assert flat[0]["shot_purpose"] == "opens on the two-shot"


# =============================================================================
# 6. plan_moments_deterministic (the SHARED sheet-preview + real-pictures
#    pipeline, C7 fix (a)) preserves purpose fields end to end, including
#    when a floor adds a code-synthesized shot with none.
# =============================================================================

def test_plan_moments_deterministic_preserves_purpose_through_full_pipeline():
    directive = (
        "[SETUPS | A: wide two-shot; B: MCU on Ryan; C: MCU on Vanessa]\n"
        "[MOMENT 1 | opening]\n"
        "- MASTER [WS]: (SETUP A) Wide two-shot establishing the kitchen.\n"
        "PURPOSE: spatial | establishes the geography before dialogue starts\n"
        "[MOMENT 2 | Ryan speaks]\n"
        "LINE: Ryan | \"Hello there.\"\n"
        "- MASTER [MCU]: (SETUP B) Ryan speaks, looking at Vanessa.\n"
        "PURPOSE: story | opens the conversation\n"
        "[MOMENT 3 | Vanessa speaks]\n"
        "LINE: Vanessa | \"Hi Ryan.\"\n"
        "- MASTER [MCU]: (SETUP C) Vanessa speaks, looking at Ryan.\n"
        "PURPOSE: story | Vanessa's reply advances the beat\n"
        "[MOMENT 4 | Ryan speaks again]\n"
        "LINE: Ryan | \"How are you?\"\n"
        "- MASTER [MCU]: (SETUP B) Ryan speaks again.\n"
        "PURPOSE: emotion | shows Ryan's genuine interest\n"
    )
    moments = plan_moments_deterministic(directive, 10, 4, max_frames=None)
    assert moments is not None
    flat = [shot for m in moments for shot in [m["master"], *(m.get("angles") or [])]]
    # 4 planned masters + exactly 1 REACTION floor shot (same shape as the
    # upstream C7 fix (a) parity test this directive is modeled on).
    assert len(flat) == 5

    # Every LLM-authored master kept its own purpose_kind/shot_purpose.
    tagged = [s for s in flat if s.get("shot_purpose")]
    assert len(tagged) == 4
    assert {s["purpose_kind"] for s in tagged} == {"spatial", "story", "emotion"}

    # The floor-added REACTION shot has no LLM prose to draw a purpose from —
    # None, not a crash, and the WARN gate is expected to flag exactly it.
    untagged = [s for s in flat if not s.get("shot_purpose")]
    assert len(untagged) == 1
    warnings = check_shot_purpose_present(moments)
    assert warnings == 1


if __name__ == "__main__":
    test_parse_purpose_present_extracts_kind_and_text()
    test_parse_purpose_kind_is_lowercased_and_tolerant_of_bold()
    test_parse_purpose_absent_on_one_shot_present_on_another_same_moment()
    test_legacy_directive_parses_byte_identical_purpose_fields_absent()
    test_legacy_directive_check_gate_does_not_crash_and_flags_every_shot()
    test_check_shot_purpose_present_silent_when_every_shot_tagged()
    test_check_shot_purpose_present_flags_only_the_untagged_shot()
    test_generate_coverage_frames_threads_purpose_fields_onto_frame_dicts()
    test_generate_coverage_frames_purpose_text_never_reaches_the_draw_prompt()
    test_enforce_setup_variety_swaps_purpose_fields_with_content()
    test_plan_moments_deterministic_preserves_purpose_through_full_pipeline()
    print("ok — D9-1 shot-purpose tests passed")
