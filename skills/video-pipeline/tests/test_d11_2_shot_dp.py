"""D11-2: per-shot DP (director of photography) fields as structured data —
a follow-on to D11-1's professional shot-archetype library (migration 149).

WHY THIS EXISTS: the film-studio audit found the remaining camera vocabulary
— lens, camera height, depth of field — still living ONLY as prose: the
channel-wide LensProfile (injected once into the coverage system prompt's
<channel_style> block) and rule 11's per-panel FOUR CAMERA FACTS, whose own
check_camera_facts_present docstring admits facts (b) camera height and
(c) frame-fraction are "free prose with no fixed vocabulary to scan for...
NOT mechanically checkable today". This chunk gives each shot a trailing,
OPTIONAL, structured `DP: <lens_mm> | <camera_height> | <dof>` row (rule 28)
— additional to, never a replacement for, rule 11's own prose.

This file proves, in order:
  1. Vocabulary constants (CAMERA_HEIGHT_KINDS, DOF_KINDS, DP_LENS_MIN_MM/
     MAX_MM) exist and match what the checker enforces.
  2. parse_coverage extracts lens_mm/camera_height/dof from a shot's own
     trailing "DP: <lens_mm> | <camera_height> | <dof>" row — each of the
     three slots independently optional, position-fixed — and the row never
     survives into the stored description, same grammar/extraction
     discipline as D9-1/D9-6/D9-7/D11-1.
  3. BACKWARD COMPATIBILITY across all FOUR prior directive eras: zero
     metadata rows (predates D9-1), PURPOSE-only (D9-1 era),
     PURPOSE+TRANSITION+CAUSED_BY (D9-6/D9-7 era), and
     PURPOSE+TRANSITION+CAUSED_BY+ARCHETYPE (D11-1 era, predates this
     chunk) — all four parse BYTE-IDENTICAL on shot_type/description, with
     lens_mm/camera_height/dof simply absent (None), no crash.
  4. check_shot_dp_valid (the new WARN-only gate) fires only on an
     out-of-vocabulary camera_height/dof, an out-of-range or malformed lens
     value — never on an absent field, since the row is entirely optional
     (unlike D9-1/D9-6/D9-7's "present" checks).
  5. generate_coverage_frames threads lens_mm/camera_height/dof into the
     frame dicts store_scene persists — and the DP row text never rides into
     the actual image-generation prompt.
  6. enforce_setup_variety's content swap carries lens_mm/camera_height/dof
     along with shot_type/description/shot_archetype/etc.
  7. plan_moments_deterministic (the ONE shared sheet-preview + real-pictures
     pipeline) preserves the three DP fields end to end, including a
     floor-added filler shot correctly landing with none.

Run:
    cd skills/video-pipeline && python -m pytest tests/test_d11_2_shot_dp.py -q
"""
import asyncio
import os
import sys

_PIPELINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PIPELINE_ROOT)
sys.path.insert(0, os.path.join(_PIPELINE_ROOT, "storyboard"))
sys.path.append(os.path.join(_PIPELINE_ROOT, "image_prompts"))

from storyboard.coverage import (  # noqa: E402
    parse_coverage, check_shot_dp_valid, generate_coverage_frames,
    enforce_setup_variety, plan_moments_deterministic,
    CAMERA_HEIGHT_KINDS, DOF_KINDS, DP_LENS_MIN_MM, DP_LENS_MAX_MM,
)

# =============================================================================
# The four prior directive eras — SAMPLE/D9_1_ERA/D9_6_7_ERA mirror the exact
# fixtures test_d9_1_shot_purpose.py / test_d9_6_7_transition_causality.py /
# test_d11_1_shot_archetype.py already use; D11_1_ERA mirrors their same
# directive shape extended with ARCHETYPE (predates this chunk, since DP
# didn't exist yet).
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

D9_1_ERA = (
    "[MOMENT 1 | Nyla pushes through the hatch]\n"
    "- MASTER [WS]: Ryan pushes through the pod's hatch into the corridor.\n"
    "PURPOSE: spatial | shows how Ryan gets from the pod to the corridor\n"
    "- ANGLE [MCU]: Close on Ryan's face as the door seals behind him.\n"
    "PURPOSE: emotion | the audience needs to see relief break through the tension\n"
)

D9_6_7_ERA = (
    "[MOMENT 1 | Nyla pushes through the hatch]\n"
    "- MASTER [WS]: Ryan pushes through the pod's hatch into the corridor.\n"
    "PURPOSE: spatial | shows how Ryan gets from the pod to the corridor\n"
    "TRANSITION: opening\n"
    "- ANGLE [MCU]: Close on Ryan's face as the door seals behind him.\n"
    "PURPOSE: emotion | the audience needs to see relief break through the tension\n"
    "TRANSITION: continuous\n"
    "CAUSED_BY: M1-MASTER\n"
)

D11_1_ERA = (
    "[MOMENT 1 | Nyla pushes through the hatch]\n"
    "- MASTER [WS]: Ryan pushes through the pod's hatch into the corridor.\n"
    "PURPOSE: spatial | shows how Ryan gets from the pod to the corridor\n"
    "TRANSITION: opening\n"
    "ARCHETYPE: establishing_wide\n"
    "- ANGLE [MCU]: Close on Ryan's face as the door seals behind him.\n"
    "PURPOSE: emotion | the audience needs to see relief break through the tension\n"
    "TRANSITION: continuous\n"
    "CAUSED_BY: M1-MASTER\n"
    "ARCHETYPE: close\n"
)


# =============================================================================
# 1. Vocabulary constants
# =============================================================================

def test_camera_height_kinds_and_dof_kinds_are_the_taught_vocabulary():
    assert CAMERA_HEIGHT_KINDS == ("ground", "low", "waist", "chest", "eye", "high", "overhead")
    assert DOF_KINDS == ("shallow", "medium", "deep")


def test_lens_range_constants():
    assert DP_LENS_MIN_MM == 10
    assert DP_LENS_MAX_MM == 200


# =============================================================================
# 2. Parsing: DP present
# =============================================================================

def test_parse_dp_extracts_all_three_slots():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [CU]: close on her face as she decides.\n"
        "DP: 35mm | eye | shallow\n"
    )
    moments = parse_coverage(directive)
    master = moments[0]["master"]
    assert master["lens_mm"] == 35
    assert master["camera_height"] == "eye"
    assert master["dof"] == "shallow"
    assert "DP" not in master["description"]
    assert master["description"] == "close on her face as she decides."


def test_parse_dp_tolerant_of_bold_and_case():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "**DP**: 85MM | EYE | SHALLOW\n"
    )
    moments = parse_coverage(directive)
    master = moments[0]["master"]
    assert master["lens_mm"] == 85
    assert master["camera_height"] == "eye"
    assert master["dof"] == "shallow"


def test_parse_dp_middle_slot_skipped_but_pipe_kept():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [CU]: close on her face.\n"
        "DP: 85mm | | shallow\n"
    )
    moments = parse_coverage(directive)
    master = moments[0]["master"]
    assert master["lens_mm"] == 85
    assert master["camera_height"] is None
    assert master["dof"] == "shallow"


def test_parse_dp_lens_and_dof_skipped_only_height_given():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [CU]: close on her face.\n"
        "DP: | low |\n"
    )
    moments = parse_coverage(directive)
    master = moments[0]["master"]
    assert master["lens_mm"] is None
    assert master["camera_height"] == "low"
    assert master["dof"] is None


def test_parse_dp_lens_only_no_pipes_at_all():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "DP: 24mm\n"
    )
    moments = parse_coverage(directive)
    master = moments[0]["master"]
    assert master["lens_mm"] == 24
    assert master["camera_height"] is None
    assert master["dof"] is None


def test_parse_dp_absent_on_one_shot_present_on_another_same_moment():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "- ANGLE [MCU]: closer on the rider.\n"
        "DP: 50mm | eye | medium\n"
    )
    moments = parse_coverage(directive)
    master, angle = moments[0]["master"], moments[0]["angles"][0]
    assert master["lens_mm"] is None
    assert master["camera_height"] is None
    assert master["dof"] is None
    assert angle["lens_mm"] == 50
    assert angle["camera_height"] == "eye"
    assert angle["dof"] == "medium"


def test_parse_all_five_rows_together_never_cross_contaminate():
    """PURPOSE, TRANSITION, CAUSED_BY, ARCHETYPE, and DP stacked together
    (the taught order) must each extract independently, description fully
    stripped of all five."""
    directive = (
        "[MOMENT 2 | x]\n"
        "- MASTER [MCU]: close on the door handle turning.\n"
        "PURPOSE: story | opens the beat\n"
        "TRANSITION: continuous\n"
        "CAUSED_BY: M1-MASTER\n"
        "ARCHETYPE: close\n"
        "DP: 50mm | eye | shallow\n"
        "- ANGLE [CU]: reaction shot from behind.\n"
        "PURPOSE: emotion | shows tension\n"
        "TRANSITION: time_cut | the same door handle, now rusted\n"
        "CAUSED_BY: M2-MASTER\n"
        "ARCHETYPE: freeze_reaction\n"
        "DP: 135mm | high | deep\n"
    )
    moments = parse_coverage(directive)
    master, angle = moments[0]["master"], moments[0]["angles"][0]

    assert master["description"] == "close on the door handle turning."
    assert master["purpose_kind"] == "story"
    assert master["transition_kind"] == "continuous"
    assert master["caused_by"] == "M1-MASTER"
    assert master["shot_archetype"] == "close"
    assert master["lens_mm"] == 50
    assert master["camera_height"] == "eye"
    assert master["dof"] == "shallow"

    assert angle["description"] == "reaction shot from behind."
    assert angle["purpose_kind"] == "emotion"
    assert angle["transition_kind"] == "time_cut"
    assert angle["caused_by"] == "M2-MASTER"
    assert angle["shot_archetype"] == "freeze_reaction"
    assert angle["lens_mm"] == 135
    assert angle["camera_height"] == "high"
    assert angle["dof"] == "deep"


def test_parse_rows_in_reversed_order_still_extract_correctly():
    """Same discipline as D9-6/D9-7/D11-1's equivalent test — extraction
    must not depend on the taught row order, since _strip_shot_metadata_rows
    always peels whichever candidate starts latest."""
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide shot.\n"
        "DP: 28mm | low | deep\n"
        "ARCHETYPE: establishing_wide\n"
        "CAUSED_BY: M0-MASTER\n"
        "TRANSITION: montage | quick cuts\n"
        "PURPOSE: action | shows movement\n"
    )
    moments = parse_coverage(directive)
    master = moments[0]["master"]
    assert master["description"] == "wide shot."
    assert master["lens_mm"] == 28
    assert master["camera_height"] == "low"
    assert master["dof"] == "deep"
    assert master["shot_archetype"] == "establishing_wide"
    assert master["purpose_kind"] == "action"
    assert master["transition_kind"] == "montage"
    assert master["caused_by"] == "M0-MASTER"


def test_parse_dp_only_no_other_rows():
    """DP may appear completely alone — it doesn't require PURPOSE/
    TRANSITION/CAUSED_BY/ARCHETYPE to also be present (all five are
    independently optional)."""
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide shot.\n"
        "DP: 24mm | ground | deep\n"
    )
    moments = parse_coverage(directive)
    master = moments[0]["master"]
    assert master["lens_mm"] == 24
    assert master["camera_height"] == "ground"
    assert master["dof"] == "deep"
    assert master["purpose_kind"] is None
    assert master["transition_kind"] is None
    assert master["caused_by"] is None
    assert master["shot_archetype"] is None


# =============================================================================
# 3. BACKWARD COMPATIBILITY — all four prior directive eras
# =============================================================================

def test_legacy_sample_era_parses_byte_identical_dp_absent():
    """Era 1: zero metadata rows of any kind (predates D9-1)."""
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
            assert shot["lens_mm"] is None
            assert shot["camera_height"] is None
            assert shot["dof"] is None


def test_d9_1_era_parses_byte_identical_dp_absent():
    """Era 2: PURPOSE rows only (D9-1 era, predates D9-6/D9-7/D11-1/this chunk)."""
    moments = parse_coverage(D9_1_ERA)
    assert len(moments) == 1
    master, angle = moments[0]["master"], moments[0]["angles"][0]
    assert master["description"] == "Ryan pushes through the pod's hatch into the corridor."
    assert master["purpose_kind"] == "spatial"
    for shot in (master, angle):
        assert shot["lens_mm"] is None
        assert shot["camera_height"] is None
        assert shot["dof"] is None


def test_d9_6_7_era_parses_byte_identical_dp_absent():
    """Era 3: PURPOSE+TRANSITION+CAUSED_BY (D9-6/D9-7 era, predates D11-1
    and this chunk)."""
    moments = parse_coverage(D9_6_7_ERA)
    assert len(moments) == 1
    master, angle = moments[0]["master"], moments[0]["angles"][0]
    assert master["transition_kind"] == "opening"
    assert angle["caused_by"] == "M1-MASTER"
    for shot in (master, angle):
        assert shot["lens_mm"] is None
        assert shot["camera_height"] is None
        assert shot["dof"] is None


def test_d11_1_era_parses_byte_identical_dp_absent():
    """Era 4: PURPOSE+TRANSITION+CAUSED_BY+ARCHETYPE (D11-1 era, predates
    this chunk) — the decisive backward-compat proof for this harvest."""
    moments = parse_coverage(D11_1_ERA)
    assert len(moments) == 1
    master, angle = moments[0]["master"], moments[0]["angles"][0]
    assert master["shot_archetype"] == "establishing_wide"
    assert angle["shot_archetype"] == "close"
    for shot in (master, angle):
        assert shot["lens_mm"] is None
        assert shot["camera_height"] is None
        assert shot["dof"] is None


def test_all_four_eras_check_gate_does_not_crash_and_stays_silent():
    """check_shot_dp_valid must run cleanly over every prior era with ZERO
    warnings — unlike the "present" checks (D9-1/D9-6/D9-7), an absent DP
    row/slot is never an error here, since it's optional."""
    for directive in (SAMPLE, D9_1_ERA, D9_6_7_ERA, D11_1_ERA):
        moments = parse_coverage(directive)
        assert check_shot_dp_valid(moments) == 0


# =============================================================================
# 4. The WARN gate — flags an INVALID/malformed value, never an ABSENT one
# =============================================================================

def test_check_shot_dp_valid_silent_when_no_dp_rows():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "- ANGLE [MCU]: closer on the rider.\n"
    )
    moments = parse_coverage(directive)
    assert check_shot_dp_valid(moments) == 0


def test_check_shot_dp_valid_silent_for_valid_values():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "DP: 35mm | eye | shallow\n"
    )
    moments = parse_coverage(directive)
    assert check_shot_dp_valid(moments) == 0


def test_check_shot_dp_valid_flags_lens_out_of_range():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "DP: 400mm | eye | shallow\n"
    )
    moments = parse_coverage(directive)
    assert moments[0]["master"]["lens_mm"] == 400  # parsed, just out of range
    assert check_shot_dp_valid(moments) == 1


def test_check_shot_dp_valid_flags_malformed_lens_text():
    """A lens slot with TEXT that doesn't match "<digits>mm" must still be
    flagged — otherwise it silently vanishes to None, indistinguishable from
    "no lens value written"."""
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "DP: fifty mm | eye | shallow\n"
    )
    moments = parse_coverage(directive)
    assert moments[0]["master"]["lens_mm"] is None
    assert check_shot_dp_valid(moments) == 1


def test_check_shot_dp_valid_flags_out_of_vocabulary_camera_height():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "DP: 35mm | bird's eye | shallow\n"
    )
    moments = parse_coverage(directive)
    assert check_shot_dp_valid(moments) == 1


def test_check_shot_dp_valid_flags_out_of_vocabulary_dof():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "DP: 35mm | eye | soft\n"
    )
    moments = parse_coverage(directive)
    assert check_shot_dp_valid(moments) == 1


def test_check_shot_dp_valid_counts_independent_issues_on_same_shot():
    """All three slots invalid on ONE shot = three separate warnings, not
    one merged warning — each slot is an independently checkable fact."""
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "DP: 5mm | nowhere | blurry\n"
    )
    moments = parse_coverage(directive)
    assert check_shot_dp_valid(moments) == 3


def test_check_shot_dp_valid_flags_only_the_invalid_shot():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "DP: 35mm | eye | shallow\n"
        "- ANGLE [MCU]: closer, invalid dof here.\n"
        "DP: 50mm | eye | blurry\n"
    )
    moments = parse_coverage(directive)
    assert check_shot_dp_valid(moments) == 1


# =============================================================================
# 5. generate_coverage_frames threads lens_mm/camera_height/dof — and the
#    row text never rides into the actual draw prompt.
# =============================================================================

class _FakeImageClientForFrames:
    SCENE_MODEL = "nano-banana-2"

    def __init__(self):
        self.calls = []

    async def generate_scene_image_zimage(self, prompt, aspect_ratio="16:9", **_kwargs):
        self.calls.append(("generate_scene_image_zimage", prompt, aspect_ratio))
        return {"url": f"https://img/{len(self.calls)}.png"}


def test_generate_coverage_frames_threads_dp_fields_onto_frame_dicts():
    moment = {
        "moment_number": 1,
        "master": {
            "shot_type": "WS", "description": "wide shot of the rider at dawn",
            "lens_mm": 24, "camera_height": "eye", "dof": "deep",
        },
        "angles": [{
            "shot_type": "MCU", "description": "close on the rider's face",
            "lens_mm": 85, "camera_height": "chest", "dof": "shallow",
        }],
    }
    ic = _FakeImageClientForFrames()
    frames = asyncio.run(generate_coverage_frames(
        moment, "https://cast.png", ic, None, aspect="16:9", resolution="1K",
        model_override="z-image"))
    assert frames is not None and len(frames) == 2
    master, angle = frames
    assert master["lens_mm"] == 24
    assert master["camera_height"] == "eye"
    assert master["dof"] == "deep"
    assert angle["lens_mm"] == 85
    assert angle["camera_height"] == "chest"
    assert angle["dof"] == "shallow"


def test_generate_coverage_frames_dp_row_syntax_never_reaches_the_draw_prompt():
    """UPDATED for D11-3 (mechanical prompt compiler): when this test was
    written (D11-2), DP was pure inert metadata — nothing consumed it, so
    "the raw values don't appear in the prompt" was a correct (if indirect)
    proxy for "the row was stripped at parse time and nothing re-introduced
    it". D11-3 is the chunk that INTENTIONALLY starts consuming these
    fields: compose_shot_cinematography (storyboard/shot_archetypes.py)
    translates them into fixed English phrasing, and this function's
    assembly points now PREPEND that clause. So "24mm"/"overhead" NOW
    appearing in the prompt is the whole point of that chunk, not a
    regression — this test is narrowed to what it was actually protecting:
    the raw ROW SYNTAX (the literal "DP:" label with its pipe-separated
    slots) must never leak through, which remains true (it's stripped by
    _strip_shot_metadata_rows before this function ever sees the shot dict,
    unrelated to whether compose_shot_cinematography later translates the
    values). See test_d11_3_prompt_compiler.py for the full compiler
    coverage, including a planted-marker proof that the clause is sourced
    from the archetype catalog/DP fields, never from the description."""
    moment = {
        "moment_number": 1,
        "master": {
            "shot_type": "WS", "description": "wide shot of the rider at dawn",
            "lens_mm": 24, "camera_height": "overhead", "dof": "shallow",
        },
        "angles": [],
    }
    ic = _FakeImageClientForFrames()
    frames = asyncio.run(generate_coverage_frames(
        moment, "https://cast.png", ic, None, aspect="16:9", resolution="1K",
        model_override="z-image"))
    assert frames is not None and len(frames) == 1
    prompt = ic.calls[0][1]
    # The raw row syntax never appears — never did, never will (stripped at
    # parse time, long before this function runs).
    assert "DP:" not in prompt
    assert "DP :" not in prompt
    # D11-3: the compiled clause DOES now translate lens_mm/camera_height/
    # dof into the prompt, deliberately — this is the mechanical-compiler
    # chunk's whole point (Ryan: "are the prompts mechanically assembled
    # from the database of the shot angles and cinematography language?").
    assert "24mm" in prompt
    assert "overhead" in prompt


# =============================================================================
# 6. DP fields travel WITH content through a variety-swap
# =============================================================================

def _flat(*shots):
    """Mirrors test_d11_1_shot_archetype.py's local _flat helper, extended
    with the three DP fields."""
    out = []
    for i, spec in enumerate(shots):
        fam, role = spec[0], spec[1]
        mi = spec[2] if len(spec) > 2 else 0
        lens_mm = spec[3] if len(spec) > 3 else None
        out.append({"shot_type": "MS", "role": role, "_mi": mi,
                    "description": f"(SETUP {fam}) placeholder shot {i}.",
                    "purpose_kind": None, "shot_purpose": None,
                    "transition_kind": None, "continuity_bridge": None, "caused_by": None,
                    "shot_archetype": None,
                    "lens_mm": lens_mm,
                    "camera_height": f"h{lens_mm}" if lens_mm else None,
                    "dof": "shallow" if lens_mm else None})
    return out


def test_enforce_setup_variety_swaps_dp_fields_with_content():
    flat = _flat(
        ("B", "master", 0, 24),
        ("B", "angle", 0, 35),
        ("B", "angle", 0, 50),   # will move
        ("C", "angle", 0, 85),   # will move
    )
    n = enforce_setup_variety(flat)
    assert n == 1
    assert flat[2]["description"] == "(SETUP C) placeholder shot 3."
    assert flat[3]["description"] == "(SETUP B) placeholder shot 2."
    # DP fields swapped RIGHT ALONG WITH the content.
    assert flat[2]["lens_mm"] == 85
    assert flat[2]["camera_height"] == "h85"
    assert flat[3]["lens_mm"] == 50
    assert flat[3]["camera_height"] == "h50"
    # The untouched master keeps its own DP fields.
    assert flat[0]["lens_mm"] == 24


# =============================================================================
# 7. plan_moments_deterministic preserves lens_mm/camera_height/dof end to end.
# =============================================================================

def test_plan_moments_deterministic_preserves_dp_through_full_pipeline():
    directive = (
        "[SETUPS | A: wide two-shot; B: MCU on Ryan; C: MCU on Vanessa]\n"
        "[MOMENT 1 | opening]\n"
        "- MASTER [WS]: (SETUP A) Wide two-shot establishing the kitchen.\n"
        "DP: 24mm | eye | deep\n"
        "[MOMENT 2 | Ryan speaks]\n"
        "LINE: Ryan | \"Hello there.\"\n"
        "- MASTER [MCU]: (SETUP B) Ryan speaks, looking at Vanessa.\n"
        "DP: 50mm | eye | shallow\n"
        "[MOMENT 3 | Vanessa speaks]\n"
        "LINE: Vanessa | \"Hi Ryan.\"\n"
        "- MASTER [MCU]: (SETUP C) Vanessa speaks, looking at Ryan.\n"
        "DP: 50mm | eye | shallow\n"
        "[MOMENT 4 | Ryan speaks again]\n"
        "LINE: Ryan | \"How are you?\"\n"
        "- MASTER [MCU]: (SETUP B) Ryan speaks again.\n"
        "DP: 85mm | eye | shallow\n"
    )
    moments = plan_moments_deterministic(directive, 10, 4, max_frames=None)
    assert moments is not None
    flat = [shot for m in moments for shot in [m["master"], *(m.get("angles") or [])]]
    # 4 planned masters + exactly 1 REACTION floor shot (same shape as
    # D9-1/D9-6/D9-7/D11-1's equivalent tests — this directive is modeled on
    # the same fixture).
    assert len(flat) == 5

    tagged = [s for s in flat if s.get("lens_mm")]
    assert len(tagged) == 4
    assert {s["lens_mm"] for s in tagged} == {24, 50, 85}

    # The floor-added REACTION shot has no LLM prose to draw a DP row from —
    # None, not a crash. check_shot_dp_valid stays silent (absence is never
    # an error, only an INVALID/malformed value is).
    untagged = [s for s in flat if not s.get("lens_mm")]
    assert len(untagged) == 1
    assert check_shot_dp_valid(moments) == 0


if __name__ == "__main__":
    test_camera_height_kinds_and_dof_kinds_are_the_taught_vocabulary()
    test_lens_range_constants()
    test_parse_dp_extracts_all_three_slots()
    test_parse_dp_tolerant_of_bold_and_case()
    test_parse_dp_middle_slot_skipped_but_pipe_kept()
    test_parse_dp_lens_and_dof_skipped_only_height_given()
    test_parse_dp_lens_only_no_pipes_at_all()
    test_parse_dp_absent_on_one_shot_present_on_another_same_moment()
    test_parse_all_five_rows_together_never_cross_contaminate()
    test_parse_rows_in_reversed_order_still_extract_correctly()
    test_parse_dp_only_no_other_rows()
    test_legacy_sample_era_parses_byte_identical_dp_absent()
    test_d9_1_era_parses_byte_identical_dp_absent()
    test_d9_6_7_era_parses_byte_identical_dp_absent()
    test_d11_1_era_parses_byte_identical_dp_absent()
    test_all_four_eras_check_gate_does_not_crash_and_stays_silent()
    test_check_shot_dp_valid_silent_when_no_dp_rows()
    test_check_shot_dp_valid_silent_for_valid_values()
    test_check_shot_dp_valid_flags_lens_out_of_range()
    test_check_shot_dp_valid_flags_malformed_lens_text()
    test_check_shot_dp_valid_flags_out_of_vocabulary_camera_height()
    test_check_shot_dp_valid_flags_out_of_vocabulary_dof()
    test_check_shot_dp_valid_counts_independent_issues_on_same_shot()
    test_check_shot_dp_valid_flags_only_the_invalid_shot()
    test_generate_coverage_frames_threads_dp_fields_onto_frame_dicts()
    test_generate_coverage_frames_dp_row_syntax_never_reaches_the_draw_prompt()
    test_enforce_setup_variety_swaps_dp_fields_with_content()
    test_plan_moments_deterministic_preserves_dp_through_full_pipeline()
    print("ok — D11-2 shot-DP tests passed")
