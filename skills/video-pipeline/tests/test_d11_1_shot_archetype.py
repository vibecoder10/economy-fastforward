"""D11-1: the professional shot-archetype library — a follow-on to the
film-studio audit's camera-MOVEMENT harvest (image_prompts/engine/
camera_moves.py, a 37-entry metadata catalog) for the STATIC shot side, which
was still a bare unannotated string (storyboard/coverage.py's
`SHOT_TYPES = "ELS, WS, MS, MCU, CU, ECU, OTS, INSERT"`).

WHY THIS EXISTS: storyboard/shot_archetypes.py adds a 45-entry catalog
(establishing/coverage/detail/angle/composition/specialty) describing WHICH
professional archetype a shot resembles — a richer descriptor than the bare
shot_type letter code. Unlike D9-1/D9-6/D9-7's PURPOSE/TRANSITION/CAUSED_BY
rows, tagging a shot with an archetype is OPTIONAL for the planner (rule 27:
"you MAY", never "must").

This file proves, in order:
  1. Catalog integrity — storyboard/shot_archetypes.py's own contract: every
     id unique, every required field non-empty, every category one of the
     six the D11-1 brief specifies, format_archetype_menu() renders under a
     real size budget, get_archetype() is case/whitespace tolerant.
  2. parse_coverage extracts shot_archetype from a shot's own trailing
     "ARCHETYPE: <id>" row, and the row never survives into the stored
     description — same grammar/extraction discipline as D9-1/D9-6/D9-7.
  3. BACKWARD COMPATIBILITY across all THREE prior directive eras: zero
     metadata rows (predates D9-1), PURPOSE-only (D9-1 era), and
     PURPOSE+TRANSITION+CAUSED_BY (D9-6/D9-7 era, predates this chunk) — all
     three parse BYTE-IDENTICAL on shot_type/description, with
     shot_archetype simply absent (None), no crash.
  4. check_shot_archetype_valid (the new WARN-only gate) fires only on an
     INVALID archetype id — never on an absent one, since tagging is
     optional (unlike D9-1/D9-6/D9-7's "present" checks).
  5. generate_coverage_frames threads shot_archetype into the frame dicts
     store_scene persists — and the ARCHETYPE row text never rides into the
     actual image-generation prompt.
  6. enforce_setup_variety's content swap carries shot_archetype along with
     shot_type/description/purpose_kind/etc.
  7. plan_moments_deterministic (the ONE shared sheet-preview + real-pictures
     pipeline) preserves shot_archetype end to end, including a floor-added
     filler shot correctly landing with none.

Run:
    cd skills/video-pipeline && python -m pytest tests/test_d11_1_shot_archetype.py -q
"""
import asyncio
import os
import sys

_PIPELINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PIPELINE_ROOT)
sys.path.insert(0, os.path.join(_PIPELINE_ROOT, "storyboard"))
sys.path.append(os.path.join(_PIPELINE_ROOT, "image_prompts"))

from storyboard.coverage import (  # noqa: E402
    parse_coverage, check_shot_archetype_valid, generate_coverage_frames,
    enforce_setup_variety, plan_moments_deterministic,
)
from storyboard.shot_archetypes import (  # noqa: E402
    SHOT_ARCHETYPES, CATEGORY_ORDER, get_archetype, archetypes_for_category,
    format_archetype_menu,
)

# =============================================================================
# The three prior directive eras — real fixture shapes, not synthesized for
# this PR. SAMPLE and D9_1_ERA are the exact fixtures test_d9_1_shot_purpose.py
# / test_d9_6_7_transition_causality.py already use; D9_6_7_ERA mirrors their
# same directive shape extended with TRANSITION/CAUSED_BY (predates this
# chunk, since ARCHETYPE didn't exist yet).
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


# =============================================================================
# 1. Catalog integrity (storyboard/shot_archetypes.py's own contract)
# =============================================================================

_VALID_CATEGORIES = {"establishing", "coverage", "detail", "angle", "composition", "specialty"}
_REQUIRED_TEXT_FIELDS = ("id", "name", "category", "purpose", "emotion", "typical_lens", "image_setup")


def test_catalog_size_within_seed_range():
    """The D11-1 brief calls for 40-60 seeded archetypes."""
    assert 40 <= len(SHOT_ARCHETYPES) <= 60


def test_catalog_ids_are_unique_and_match_dict_keys():
    ids = [a.id for a in SHOT_ARCHETYPES.values()]
    assert len(ids) == len(set(ids))
    for key, archetype in SHOT_ARCHETYPES.items():
        assert key == archetype.id


def test_catalog_every_archetype_has_non_empty_required_fields():
    for archetype in SHOT_ARCHETYPES.values():
        for field_name in _REQUIRED_TEXT_FIELDS:
            value = getattr(archetype, field_name)
            assert isinstance(value, str) and value.strip(), (
                f"{archetype.id}.{field_name} is empty")
        assert isinstance(archetype.typical_duration_s, (int, float))
        assert archetype.typical_duration_s > 0
        assert isinstance(archetype.aliases, tuple)
        assert isinstance(archetype.pairs_well_after, tuple)


def test_catalog_every_category_is_one_of_the_six_specified():
    for archetype in SHOT_ARCHETYPES.values():
        assert archetype.category in _VALID_CATEGORIES
    # And every category actually has at least one member — no dead category.
    for cat in CATEGORY_ORDER:
        assert len(archetypes_for_category(cat)) >= 1


def test_catalog_covers_the_required_named_archetypes():
    """The D11-1 brief names specific archetypes the seed MUST cover —
    proven by id membership (aliases carry the exact phrase, ids are the
    canonical slug the planner is taught to write)."""
    required_ids = {
        "establishing_wide", "extreme_wide", "wide", "full", "cowboy", "medium",
        "medium_close", "close", "extreme_close", "pov", "ots", "insert", "cutaway",
        "dutch", "low_angle", "high_angle", "top_down", "profile", "silhouette",
        "reflection", "static_symmetry", "nested_frame", "two_shot", "group_shot",
        "macro_detail", "reveal_framing",
    }
    assert required_ids.issubset(SHOT_ARCHETYPES.keys())


def test_pairs_well_after_references_only_real_catalog_ids():
    """A dangling pairs_well_after reference would be a silent catalog bug —
    every id it names must itself be a real archetype in this catalog."""
    for archetype in SHOT_ARCHETYPES.values():
        for prior_id in archetype.pairs_well_after:
            assert prior_id in SHOT_ARCHETYPES, (
                f"{archetype.id}.pairs_well_after references unknown id '{prior_id}'")


def test_get_archetype_is_case_and_whitespace_tolerant():
    assert get_archetype("close") is not None
    assert get_archetype("  Close  ") is get_archetype("close")
    assert get_archetype("CLOSE") is get_archetype("close")


def test_get_archetype_returns_none_for_unknown_or_blank():
    assert get_archetype("not_a_real_archetype") is None
    assert get_archetype("") is None
    assert get_archetype(None) is None


def test_format_archetype_menu_renders_under_size_budget():
    """The menu is injected into the coverage system prompt on EVERY call —
    its size is a real token-budget line item. Budget generously (the whole
    coverage system prompt already runs into the thousands of words) but
    still bounded, so a future catalog growth spurt gets caught here instead
    of silently bloating every coverage call."""
    menu = format_archetype_menu()
    assert len(menu) < 8000, f"archetype menu is {len(menu)} chars — over budget"
    # Every category header and every archetype id must actually appear.
    for cat in CATEGORY_ORDER:
        assert cat.upper() in menu
    for archetype_id in SHOT_ARCHETYPES:
        assert archetype_id in menu


# =============================================================================
# 2. Parsing: ARCHETYPE present
# =============================================================================

def test_parse_archetype_extracts_id():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [CU]: close on her face as she decides.\n"
        "ARCHETYPE: close\n"
    )
    moments = parse_coverage(directive)
    master = moments[0]["master"]
    assert master["shot_archetype"] == "close"
    assert "ARCHETYPE" not in master["description"]
    assert master["description"] == "close on her face as she decides."


def test_parse_archetype_lowercased_and_tolerant_of_bold_and_case():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "**ARCHETYPE**: Establishing_Wide\n"
    )
    moments = parse_coverage(directive)
    assert moments[0]["master"]["shot_archetype"] == "establishing_wide"


def test_parse_archetype_absent_on_one_shot_present_on_another_same_moment():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "- ANGLE [MCU]: closer on the rider.\n"
        "ARCHETYPE: medium_close\n"
    )
    moments = parse_coverage(directive)
    master, angle = moments[0]["master"], moments[0]["angles"][0]
    assert master["shot_archetype"] is None
    assert angle["shot_archetype"] == "medium_close"


def test_parse_all_four_rows_together_never_cross_contaminate():
    """PURPOSE, TRANSITION, CAUSED_BY, and ARCHETYPE stacked together (the
    taught order) must each extract independently, description fully
    stripped of all four."""
    directive = (
        "[MOMENT 2 | x]\n"
        "- MASTER [MCU]: close on the door handle turning.\n"
        "PURPOSE: story | opens the beat\n"
        "TRANSITION: continuous\n"
        "CAUSED_BY: M1-MASTER\n"
        "ARCHETYPE: close\n"
        "- ANGLE [CU]: reaction shot from behind.\n"
        "PURPOSE: emotion | shows tension\n"
        "TRANSITION: time_cut | the same door handle, now rusted\n"
        "CAUSED_BY: M2-MASTER\n"
        "ARCHETYPE: freeze_reaction\n"
    )
    moments = parse_coverage(directive)
    master, angle = moments[0]["master"], moments[0]["angles"][0]

    assert master["description"] == "close on the door handle turning."
    assert master["purpose_kind"] == "story"
    assert master["transition_kind"] == "continuous"
    assert master["caused_by"] == "M1-MASTER"
    assert master["shot_archetype"] == "close"

    assert angle["description"] == "reaction shot from behind."
    assert angle["purpose_kind"] == "emotion"
    assert angle["transition_kind"] == "time_cut"
    assert angle["caused_by"] == "M2-MASTER"
    assert angle["shot_archetype"] == "freeze_reaction"


def test_parse_rows_in_reversed_order_still_extract_correctly():
    """Same discipline as D9-6/D9-7's equivalent test — extraction must not
    depend on the taught row order, since _strip_shot_metadata_rows always
    peels whichever candidate starts latest."""
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide shot.\n"
        "ARCHETYPE: establishing_wide\n"
        "CAUSED_BY: M0-MASTER\n"
        "TRANSITION: montage | quick cuts\n"
        "PURPOSE: action | shows movement\n"
    )
    moments = parse_coverage(directive)
    master = moments[0]["master"]
    assert master["description"] == "wide shot."
    assert master["shot_archetype"] == "establishing_wide"
    assert master["purpose_kind"] == "action"
    assert master["transition_kind"] == "montage"
    assert master["caused_by"] == "M0-MASTER"


def test_parse_archetype_only_no_other_rows():
    """ARCHETYPE may appear completely alone — it doesn't require PURPOSE/
    TRANSITION/CAUSED_BY to also be present (all four are independently
    optional)."""
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide shot.\n"
        "ARCHETYPE: extreme_wide\n"
    )
    moments = parse_coverage(directive)
    master = moments[0]["master"]
    assert master["shot_archetype"] == "extreme_wide"
    assert master["purpose_kind"] is None
    assert master["transition_kind"] is None
    assert master["caused_by"] is None


# =============================================================================
# 3. BACKWARD COMPATIBILITY — all three prior directive eras
# =============================================================================

def test_legacy_sample_era_parses_byte_identical_archetype_absent():
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
            assert shot["shot_archetype"] is None


def test_d9_1_era_parses_byte_identical_archetype_absent():
    """Era 2: PURPOSE rows only (D9-1 era, predates D9-6/D9-7 and this chunk)."""
    moments = parse_coverage(D9_1_ERA)
    assert len(moments) == 1
    master, angle = moments[0]["master"], moments[0]["angles"][0]
    assert master["description"] == "Ryan pushes through the pod's hatch into the corridor."
    assert master["purpose_kind"] == "spatial"
    assert master["shot_archetype"] is None
    assert angle["purpose_kind"] == "emotion"
    assert angle["shot_archetype"] is None


def test_d9_6_7_era_parses_byte_identical_archetype_absent():
    """Era 3: PURPOSE+TRANSITION+CAUSED_BY (D9-6/D9-7 era, predates this
    chunk) — the decisive backward-compat proof for this harvest."""
    moments = parse_coverage(D9_6_7_ERA)
    assert len(moments) == 1
    master, angle = moments[0]["master"], moments[0]["angles"][0]
    assert master["description"] == "Ryan pushes through the pod's hatch into the corridor."
    assert master["purpose_kind"] == "spatial"
    assert master["transition_kind"] == "opening"
    assert master["caused_by"] is None  # scene's true first shot, rule 26 exempt
    assert master["shot_archetype"] is None
    assert angle["purpose_kind"] == "emotion"
    assert angle["transition_kind"] == "continuous"
    assert angle["caused_by"] == "M1-MASTER"
    assert angle["shot_archetype"] is None


def test_all_three_eras_check_gate_does_not_crash_and_stays_silent():
    """check_shot_archetype_valid must run cleanly over every prior era with
    ZERO warnings — unlike the "present" checks (D9-1/D9-6/D9-7), an absent
    tag is never an error here, since tagging is optional."""
    for directive in (SAMPLE, D9_1_ERA, D9_6_7_ERA):
        moments = parse_coverage(directive)
        assert check_shot_archetype_valid(moments) == 0


# =============================================================================
# 4. The WARN gate — flags an INVALID id, never an ABSENT one
# =============================================================================

def test_check_shot_archetype_valid_silent_when_no_archetype_rows():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "- ANGLE [MCU]: closer on the rider.\n"
    )
    moments = parse_coverage(directive)
    assert check_shot_archetype_valid(moments) == 0


def test_check_shot_archetype_valid_silent_for_a_real_catalog_id():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "ARCHETYPE: establishing_wide\n"
    )
    moments = parse_coverage(directive)
    assert check_shot_archetype_valid(moments) == 0


def test_check_shot_archetype_valid_flags_an_unknown_id():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "ARCHETYPE: totally_made_up_shot_kind\n"
    )
    moments = parse_coverage(directive)
    assert check_shot_archetype_valid(moments) == 1


def test_check_shot_archetype_valid_flags_only_the_invalid_shot():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: wide of the launch.\n"
        "ARCHETYPE: establishing_wide\n"
        "- ANGLE [MCU]: closer, invalid archetype here.\n"
        "ARCHETYPE: not_a_real_one\n"
    )
    moments = parse_coverage(directive)
    assert check_shot_archetype_valid(moments) == 1


# =============================================================================
# 5. generate_coverage_frames threads shot_archetype — and the row text
#    never rides into the actual draw prompt.
# =============================================================================

class _FakeImageClientForFrames:
    SCENE_MODEL = "nano-banana-2"

    def __init__(self):
        self.calls = []

    async def generate_scene_image_zimage(self, prompt, aspect_ratio="16:9", **_kwargs):
        self.calls.append(("generate_scene_image_zimage", prompt, aspect_ratio))
        return {"url": f"https://img/{len(self.calls)}.png"}


def test_generate_coverage_frames_threads_shot_archetype_onto_frame_dicts():
    moment = {
        "moment_number": 1,
        "master": {
            "shot_type": "WS", "description": "wide shot of the rider at dawn",
            "shot_archetype": "establishing_wide",
        },
        "angles": [{
            "shot_type": "MCU", "description": "close on the rider's face",
            "shot_archetype": "medium_close",
        }],
    }
    ic = _FakeImageClientForFrames()
    frames = asyncio.run(generate_coverage_frames(
        moment, "https://cast.png", ic, None, aspect="16:9", resolution="1K",
        model_override="z-image"))
    assert frames is not None and len(frames) == 2
    master, angle = frames
    assert master["shot_archetype"] == "establishing_wide"
    assert angle["shot_archetype"] == "medium_close"


def test_generate_coverage_frames_archetype_id_never_reaches_the_draw_prompt():
    moment = {
        "moment_number": 1,
        "master": {
            "shot_type": "WS", "description": "wide shot of the rider at dawn",
            "shot_archetype": "UNMISTAKABLE_ARCHETYPE_MARKER_4f1a",
        },
        "angles": [],
    }
    ic = _FakeImageClientForFrames()
    frames = asyncio.run(generate_coverage_frames(
        moment, "https://cast.png", ic, None, aspect="16:9", resolution="1K",
        model_override="z-image"))
    assert frames is not None and len(frames) == 1
    prompt = ic.calls[0][1]
    assert "UNMISTAKABLE_ARCHETYPE_MARKER_4f1a" not in prompt
    assert "ARCHETYPE" not in prompt


# =============================================================================
# 6. shot_archetype travels WITH content through a variety-swap
# =============================================================================

def _flat(*shots):
    """Mirrors test_d9_1_shot_purpose.py's local _flat helper, extended with
    shot_archetype."""
    out = []
    for i, spec in enumerate(shots):
        fam, role = spec[0], spec[1]
        mi = spec[2] if len(spec) > 2 else 0
        shot_archetype = spec[3] if len(spec) > 3 else None
        out.append({"shot_type": "MS", "role": role, "_mi": mi,
                    "description": f"(SETUP {fam}) placeholder shot {i}.",
                    "purpose_kind": None, "shot_purpose": None,
                    "transition_kind": None, "continuity_bridge": None, "caused_by": None,
                    "shot_archetype": shot_archetype})
    return out


def test_enforce_setup_variety_swaps_shot_archetype_with_content():
    flat = _flat(
        ("B", "master", 0, "establishing_wide"),
        ("B", "angle", 0, "close"),
        ("B", "angle", 0, "medium_close"),  # will move
        ("C", "angle", 0, "wide"),           # will move
    )
    n = enforce_setup_variety(flat)
    assert n == 1
    assert flat[2]["description"] == "(SETUP C) placeholder shot 3."
    assert flat[3]["description"] == "(SETUP B) placeholder shot 2."
    # shot_archetype swapped RIGHT ALONG WITH the content.
    assert flat[2]["shot_archetype"] == "wide"
    assert flat[3]["shot_archetype"] == "medium_close"
    # The untouched master keeps its own archetype.
    assert flat[0]["shot_archetype"] == "establishing_wide"


# =============================================================================
# 7. plan_moments_deterministic preserves shot_archetype end to end.
# =============================================================================

def test_plan_moments_deterministic_preserves_archetype_through_full_pipeline():
    directive = (
        "[SETUPS | A: wide two-shot; B: MCU on Ryan; C: MCU on Vanessa]\n"
        "[MOMENT 1 | opening]\n"
        "- MASTER [WS]: (SETUP A) Wide two-shot establishing the kitchen.\n"
        "ARCHETYPE: establishing_wide\n"
        "[MOMENT 2 | Ryan speaks]\n"
        "LINE: Ryan | \"Hello there.\"\n"
        "- MASTER [MCU]: (SETUP B) Ryan speaks, looking at Vanessa.\n"
        "ARCHETYPE: medium\n"
        "[MOMENT 3 | Vanessa speaks]\n"
        "LINE: Vanessa | \"Hi Ryan.\"\n"
        "- MASTER [MCU]: (SETUP C) Vanessa speaks, looking at Ryan.\n"
        "ARCHETYPE: medium\n"
        "[MOMENT 4 | Ryan speaks again]\n"
        "LINE: Ryan | \"How are you?\"\n"
        "- MASTER [MCU]: (SETUP B) Ryan speaks again.\n"
        "ARCHETYPE: close\n"
    )
    moments = plan_moments_deterministic(directive, 10, 4, max_frames=None)
    assert moments is not None
    flat = [shot for m in moments for shot in [m["master"], *(m.get("angles") or [])]]
    # 4 planned masters + exactly 1 REACTION floor shot (same shape as D9-1/
    # D9-6/D9-7's equivalent tests — this directive is modeled on the same
    # fixture).
    assert len(flat) == 5

    tagged = [s for s in flat if s.get("shot_archetype")]
    assert len(tagged) == 4
    assert {s["shot_archetype"] for s in tagged} == {"establishing_wide", "medium", "close"}

    # The floor-added REACTION shot has no LLM prose to draw an archetype
    # from — None, not a crash. check_shot_archetype_valid stays silent
    # (absence is never an error, only an INVALID value is).
    untagged = [s for s in flat if not s.get("shot_archetype")]
    assert len(untagged) == 1
    assert check_shot_archetype_valid(moments) == 0


if __name__ == "__main__":
    test_catalog_size_within_seed_range()
    test_catalog_ids_are_unique_and_match_dict_keys()
    test_catalog_every_archetype_has_non_empty_required_fields()
    test_catalog_every_category_is_one_of_the_six_specified()
    test_catalog_covers_the_required_named_archetypes()
    test_pairs_well_after_references_only_real_catalog_ids()
    test_get_archetype_is_case_and_whitespace_tolerant()
    test_get_archetype_returns_none_for_unknown_or_blank()
    test_format_archetype_menu_renders_under_size_budget()
    test_parse_archetype_extracts_id()
    test_parse_archetype_lowercased_and_tolerant_of_bold_and_case()
    test_parse_archetype_absent_on_one_shot_present_on_another_same_moment()
    test_parse_all_four_rows_together_never_cross_contaminate()
    test_parse_rows_in_reversed_order_still_extract_correctly()
    test_parse_archetype_only_no_other_rows()
    test_legacy_sample_era_parses_byte_identical_archetype_absent()
    test_d9_1_era_parses_byte_identical_archetype_absent()
    test_d9_6_7_era_parses_byte_identical_archetype_absent()
    test_all_three_eras_check_gate_does_not_crash_and_stays_silent()
    test_check_shot_archetype_valid_silent_when_no_archetype_rows()
    test_check_shot_archetype_valid_silent_for_a_real_catalog_id()
    test_check_shot_archetype_valid_flags_an_unknown_id()
    test_check_shot_archetype_valid_flags_only_the_invalid_shot()
    test_generate_coverage_frames_threads_shot_archetype_onto_frame_dicts()
    test_generate_coverage_frames_archetype_id_never_reaches_the_draw_prompt()
    test_enforce_setup_variety_swaps_shot_archetype_with_content()
    test_plan_moments_deterministic_preserves_archetype_through_full_pipeline()
    print("ok — D11-1 shot-archetype tests passed")
