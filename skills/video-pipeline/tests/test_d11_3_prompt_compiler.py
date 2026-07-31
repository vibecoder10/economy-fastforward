"""D11-3: the mechanical prompt compiler — the final closure of the
film-studio audit's point 18 ("prompt assembly should be mechanical
translation of structured decisions").

WHY THIS EXISTS: Ryan, kicking off this chunk: "something that bit us before
is the prompt assembler was not really mechanical but really invented from
the ai — are the prompts mechanically assembled from the database of the
shot angles and cinematography language?" Before this chunk, D11-1's
shot_archetype and D11-2's lens_mm/camera_height/dof were parsed, validated
(warn-only) and PERSISTED — but never actually CONSUMED by prompt assembly.
The draw prompt's cinematography language was still 100% the planner LLM's
own prose, with these structured fields riding alongside as inert metadata.

compose_shot_cinematography (storyboard/shot_archetypes.py) is the fix: a
PURE function that translates those fields into the clause that now LEADS
every draw prompt, at all three assembly points:
  1. generate_coverage_frames (this file, THE first-draw path)
  2. coverage_to_app.py's _plan_sheet_prompts (the sheet-preview path)
  3. coverage_to_app.py's redraw_asset_image (the redraw path)
See test_d11_3_prompt_compiler_assembly.py (storyengine/backend/tests/
functional/) for #2 and #3 — this file covers the pure compose function and
#1, which both live in the pipeline package.

This file proves, in order:
  1. compose_shot_cinematography is PURE and deterministic: same fields in,
     byte-identical clause out, across a spread of field combinations.
  2. It never reads shot["description"] — a planted-marker proof: a marker
     planted in a catalog entry's image_setup DOES land in the clause; a
     different marker planted in the description does NOT.
  3. Fixed-wording DP phrasing is exact and stable.
  4. compose_shot_cinematography returns "" for a shot with neither a valid
     archetype nor any DP field (byte-identical-legacy case).
  5. _shot_prompt_description (the assembly-point helper in coverage.py)
     leaves every prior-era fixture (SAMPLE/D9_1_ERA/D9_6_7_ERA — zero
     archetype/DP fields) byte-identical, and prepends the clause for a
     tagged shot.
  6. generate_coverage_frames' actual draw prompt (assembly point #1)
     carries the clause for a tagged shot and is untouched for a legacy one
     — proven through the REAL assembly point, not just the helper.
  7. check_shot_camera_prose_redundant (the new warn-only redundancy guard)
     fires only when a shot is BOTH tagged (archetype/DP) AND its own
     description repeats obvious camera vocabulary — never on an untagged
     shot, never on a tagged-but-clean one.
  8. Rule 29 exists in the planner system prompt and rule 11 is reconciled
     to point at it.

Run:
    cd skills/video-pipeline && python -m pytest tests/test_d11_3_prompt_compiler.py -q
"""
import asyncio
import dataclasses
import os
import sys

_PIPELINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PIPELINE_ROOT)
sys.path.insert(0, os.path.join(_PIPELINE_ROOT, "storyboard"))
sys.path.append(os.path.join(_PIPELINE_ROOT, "image_prompts"))

import storyboard.shot_archetypes as shot_archetypes_module  # noqa: E402
from storyboard.shot_archetypes import (  # noqa: E402
    compose_shot_cinematography, get_archetype, SHOT_ARCHETYPES,
)
from storyboard.coverage import (  # noqa: E402
    parse_coverage, generate_coverage_frames, check_shot_camera_prose_redundant,
    _shot_prompt_description, _coverage_system_prompt,
)
from storyboard.bot import build_image_prompt_from_keyframe  # noqa: E402

# =============================================================================
# The three prior directive eras with NO archetype/DP fields (mirrors
# test_d11_2_shot_dp.py's SAMPLE/D9_1_ERA/D9_6_7_ERA) — the byte-identical-
# legacy fixtures this compiler must never touch.
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

# D11-1 era: HAS an ARCHETYPE row (predates D11-2's DP row) — this is a
# POSITIVE-path fixture, not a legacy one: an old D11-1-only plan now starts
# getting a compiled clause too, which is intentional (the archetype field
# was always meant to eventually be consumed, and this chunk is that).
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

LEGACY_ERAS = (SAMPLE, D9_1_ERA, D9_6_7_ERA)


class _FakeImageClientForFrames:
    SCENE_MODEL = "nano-banana-2"

    def __init__(self):
        self.calls = []

    async def generate_scene_image_zimage(self, prompt, aspect_ratio="16:9", **_kwargs):
        self.calls.append(("generate_scene_image_zimage", prompt, aspect_ratio))
        return {"url": f"https://img/{len(self.calls)}.png"}


# =============================================================================
# 1. Purity: same fields in, byte-identical clause out.
# =============================================================================

_FIELD_COMBOS = [
    {},
    {"shot_archetype": "wide"},
    {"shot_archetype": "not_a_real_catalog_id_xyz"},
    {"lens_mm": 35},
    {"camera_height": "eye"},
    {"dof": "shallow"},
    {"lens_mm": 24, "camera_height": "low", "dof": "deep"},
    {"shot_archetype": "close", "lens_mm": 85, "camera_height": "eye", "dof": "shallow"},
    {"shot_archetype": "ots", "camera_height": "waist"},
    {"shot_archetype": "extreme_wide", "lens_mm": 16},
    {"lens_mm": 999, "camera_height": "sideways", "dof": "blurry"},  # invalid values, still renders
]


def test_compose_is_deterministic_across_repeated_calls():
    for combo in _FIELD_COMBOS:
        shot_a = {"description": "irrelevant planner prose", "shot_type": "WS", **combo}
        shot_b = dict(shot_a)  # a fresh dict, same values
        first = compose_shot_cinematography(shot_a)
        second = compose_shot_cinematography(shot_b)
        third = compose_shot_cinematography(shot_a)
        assert first == second == third, combo


def test_compose_ignores_description_content_entirely():
    combo = {"shot_archetype": "wide", "lens_mm": 35, "camera_height": "eye", "dof": "shallow"}
    a = compose_shot_cinematography({"description": "AAAAAAA", **combo})
    b = compose_shot_cinematography({"description": "totally different ZZZZZ text", **combo})
    c = compose_shot_cinematography({**combo})  # no description key at all
    assert a == b == c


def test_compose_does_not_mutate_the_shot_dict():
    shot = {"description": "a wide shot", "shot_archetype": "wide", "lens_mm": 35}
    before = dict(shot)
    compose_shot_cinematography(shot)
    assert shot == before


# =============================================================================
# 2. Planted-marker proof: sourced from the catalog, never from the
#    description.
# =============================================================================

def test_planted_marker_proves_clause_sourced_from_catalog_not_description(monkeypatch):
    marker_in_catalog = "PLANTED_CATALOG_MARKER_9f3c1a"
    marker_in_description = "PLANTED_DESCRIPTION_MARKER_2b7ed4"

    original = SHOT_ARCHETYPES["wide"]
    patched = dataclasses.replace(original, image_setup=marker_in_catalog)
    monkeypatch.setitem(shot_archetypes_module.SHOT_ARCHETYPES, "wide", patched)

    shot = {"shot_archetype": "wide",
            "description": f"an ordinary hallway scene {marker_in_description}"}
    clause = compose_shot_cinematography(shot)

    assert marker_in_catalog in clause
    assert marker_in_description not in clause


def test_compose_uses_real_archetype_image_setup_verbatim():
    archetype = get_archetype("ots")
    clause = compose_shot_cinematography({"shot_archetype": "ots"})
    assert archetype.image_setup.strip().rstrip(". ") in clause


# =============================================================================
# 3. Fixed-wording DP phrasing, exact and stable.
# =============================================================================

def test_compose_dp_fixed_wording_single_fields():
    assert compose_shot_cinematography({"lens_mm": 35}) == "shot on a 35mm lens."
    assert compose_shot_cinematography({"camera_height": "eye"}) == "camera at eye level."
    assert compose_shot_cinematography({"camera_height": "ground"}) == "camera at ground level."
    assert compose_shot_cinematography({"camera_height": "overhead"}) == "camera directly overhead."
    assert compose_shot_cinematography({"dof": "shallow"}) == (
        "shallow depth of field, background soft.")
    assert compose_shot_cinematography({"dof": "deep"}) == "deep focus, background sharp."


def test_compose_dp_all_three_fields_joined_in_order():
    result = compose_shot_cinematography({"lens_mm": 35, "camera_height": "eye", "dof": "shallow"})
    assert result == (
        "shot on a 35mm lens, camera at eye level, shallow depth of field, background soft.")


def test_compose_archetype_plus_dp_joined_with_period():
    archetype = get_archetype("wide")
    result = compose_shot_cinematography({"shot_archetype": "wide", "lens_mm": 28})
    assert result == f"{archetype.image_setup.strip()}. shot on a 28mm lens."


def test_compose_invalid_archetype_id_contributes_nothing_but_dp_still_renders():
    result = compose_shot_cinematography(
        {"shot_archetype": "definitely_not_in_the_catalog", "camera_height": "low"})
    assert result == "a low camera angle, tilted up."


def test_compose_unrecognized_dp_values_still_render_via_literal_fallback():
    # check_shot_dp_valid (coverage.py) already flags these, warn-only —
    # compose never validates, only translates, so it must still produce
    # deterministic output rather than raising or silently dropping.
    result = compose_shot_cinematography({"camera_height": "sideways", "dof": "blurry"})
    assert result == "camera at sideways height, blurry depth of field."


# =============================================================================
# 3b. Cookie-cutter guard (Ryan's amendment): location interpolation stays
#     within the ESTABLISHING category, folds into ONE sentence (never a
#     third), and the compiler never invents mood/lighting/palette itself.
# =============================================================================

def test_compose_interpolates_location_for_establishing_category():
    archetype = get_archetype("establishing_wide")
    result = compose_shot_cinematography(
        {"shot_archetype": "establishing_wide", "shot_location": "the corridor"})
    assert result == f"{archetype.image_setup.strip()} — this is the corridor."
    # Still at most TWO sentences (one period before the DP segment, one at
    # the very end) — the location interpolation must not add a THIRD.
    assert result.count(". ") == 0
    assert result.count(".") == 1


def test_compose_location_interpolation_absent_when_no_location_known():
    archetype = get_archetype("establishing_wide")
    result = compose_shot_cinematography({"shot_archetype": "establishing_wide"})
    assert result == f"{archetype.image_setup.strip()}."
    assert "this is" not in result


def test_compose_no_location_interpolation_for_non_establishing_category():
    # "close" is CATEGORY_COVERAGE, not CATEGORY_ESTABLISHING — a location
    # name would read as noise on a tight face shot, so it must never fire.
    result = compose_shot_cinematography(
        {"shot_archetype": "close", "shot_location": "the corridor"})
    assert "this is" not in result
    assert "corridor" not in result


def test_compose_archetype_location_and_dp_together_stays_at_two_sentences_max():
    result = compose_shot_cinematography({
        "shot_archetype": "establishing_wide", "shot_location": "the corridor",
        "lens_mm": 24, "camera_height": "eye", "dof": "deep",
    })
    # Segment 1 (archetype + interpolated location, one sentence) + segment
    # 2 (the DP phrase, one sentence) = exactly two sentences — the
    # cookie-cutter guard's compact budget, even with every field present.
    sentences = [s for s in result.split(". ") if s]
    assert len(sentences) == 2
    assert "this is the corridor" in sentences[0]
    assert "24mm" in sentences[1]


def test_compose_never_invents_mood_lighting_or_palette_language():
    """The compiler's OWN vocabulary (the DP phrase tables + the location
    interpolation template) never mentions mood, lighting, or palette —
    those keep flowing from the scene's own existing channels. This checks
    every DP phrase table entry plus the location-interpolation template,
    not the catalog's pre-existing image_setup text (a few of which embed
    an archetype-INTRINSIC optical trait, e.g. silhouette's required
    backlight — catalog content audited at D11-1, not this compiler's own
    invention)."""
    banned = ("mood", "palette", "warm", "cool tone", "saturat", "vibe")
    for lens_mm in (24, 85):
        for height in ("ground", "low", "waist", "chest", "eye", "high", "overhead"):
            for dof in ("shallow", "medium", "deep"):
                clause = compose_shot_cinematography(
                    {"lens_mm": lens_mm, "camera_height": height, "dof": dof})
                low = clause.lower()
                for word in banned:
                    assert word not in low, (clause, word)
    location_only = compose_shot_cinematography(
        {"shot_archetype": "establishing_wide", "shot_location": "the greenhouse"})
    for word in banned:
        assert word not in location_only.lower()


# =============================================================================
# 4. Empty for a shot with no structured fields — byte-identical-legacy.
# =============================================================================

def test_compose_empty_for_shot_with_no_structured_fields():
    assert compose_shot_cinematography({}) == ""
    assert compose_shot_cinematography(
        {"description": "some prose", "shot_type": "WS", "purpose_kind": "story"}) == ""


def test_compose_empty_for_none_and_absent_keys():
    assert compose_shot_cinematography(
        {"shot_archetype": None, "lens_mm": None, "camera_height": None, "dof": None}) == ""


# =============================================================================
# 5. _shot_prompt_description (assembly-point helper): byte-identical for
#    every legacy-era shot, clause-prepended for a tagged one.
# =============================================================================

def test_shot_prompt_description_byte_identical_for_every_legacy_era():
    for era_text in LEGACY_ERAS:
        moments = parse_coverage(era_text)
        assert moments, era_text
        for m in moments:
            for shot in [m["master"], *(m.get("angles") or [])]:
                assert _shot_prompt_description(shot) == shot["description"]


def test_shot_prompt_description_prepends_clause_for_tagged_shot():
    shot = {"description": "Ryan speaks, looking at Vanessa.",
            "shot_archetype": "medium_close", "lens_mm": 50, "camera_height": "eye"}
    result = _shot_prompt_description(shot)
    archetype = get_archetype("medium_close")
    assert result.startswith(archetype.image_setup.strip().rstrip(". "))
    assert result.endswith("Ryan speaks, looking at Vanessa.")
    # Original description untouched.
    assert shot["description"] == "Ryan speaks, looking at Vanessa."


def test_shot_prompt_description_untagged_shot_unchanged_string():
    shot = {"description": "a wide shot of the valley", "shot_archetype": None,
            "lens_mm": None, "camera_height": None, "dof": None}
    assert _shot_prompt_description(shot) == "a wide shot of the valley"


# =============================================================================
# 6. generate_coverage_frames (assembly point #1): the REAL draw prompt.
# =============================================================================

def test_generate_coverage_frames_legacy_shot_prompt_byte_identical_via_build_image_prompt_from_keyframe():
    """The strongest legacy proof: for a shot with NO archetype/DP fields,
    the ACTUAL draw prompt this function sends to the image client contains
    build_image_prompt_from_keyframe's rendering of the RAW, unmodified
    description — proving no clause was prepended at the real assembly
    point, not just at the _shot_prompt_description helper level."""
    for era_text in LEGACY_ERAS:
        moments = parse_coverage(era_text)
        moment = moments[0]
        master = moment["master"]
        expected_composition = build_image_prompt_from_keyframe(
            {"composition": master["description"]}, None)
        ic = _FakeImageClientForFrames()
        frames = asyncio.run(generate_coverage_frames(
            {"moment_number": moment["moment_number"], "master": master,
             "angles": moment.get("angles") or []},
            "https://cast.png", ic, None, aspect="16:9", resolution="1K",
            model_override="z-image"))
        assert frames is not None and len(frames) >= 1
        actual_prompt = ic.calls[0][1]
        assert expected_composition in actual_prompt, era_text


def test_generate_coverage_frames_prepends_compiled_clause_for_tagged_master():
    moment = {
        "moment_number": 1,
        "master": {"shot_type": "WS", "description": "wide shot of the rider at dawn",
                   "shot_archetype": "establishing_wide", "lens_mm": 24},
        "angles": [],
    }
    ic = _FakeImageClientForFrames()
    frames = asyncio.run(generate_coverage_frames(
        moment, "https://cast.png", ic, None, aspect="16:9", resolution="1K",
        model_override="z-image"))
    assert frames is not None and len(frames) == 1
    prompt = ic.calls[0][1]
    archetype = get_archetype("establishing_wide")
    clause_text = archetype.image_setup.strip().rstrip(". ")
    assert clause_text in prompt
    assert "24mm" in prompt
    # The clause LEADS the shot's own description — proves PREPEND.
    assert prompt.index(clause_text) < prompt.index("wide shot of the rider at dawn")


def test_generate_coverage_frames_prepends_compiled_clause_for_tagged_angle():
    moment = {
        "moment_number": 1,
        "master": {"shot_type": "WS", "description": "wide establishing shot"},
        "angles": [{"shot_type": "MCU", "description": "close on her face, jaw set",
                    "lens_mm": 85, "camera_height": "eye", "dof": "shallow"}],
    }
    ic = _FakeImageClientForFrames()
    frames = asyncio.run(generate_coverage_frames(
        moment, "https://cast.png", ic, None, aspect="16:9", resolution="1K",
        model_override="z-image"))
    assert frames is not None and len(frames) == 2
    angle_prompt = ic.calls[1][1]
    assert "shot on a 85mm lens" in angle_prompt
    assert "camera at eye level" in angle_prompt
    assert "shallow depth of field" in angle_prompt


def test_generate_coverage_frames_archetype_only_era_now_gets_compiled_clause():
    """Positive path: the D11-1-only era (ARCHETYPE row, no DP) now DOES get
    a compiled clause — the archetype field was always meant to be
    eventually consumed, and this chunk is that."""
    moments = parse_coverage(D11_1_ERA)
    moment = moments[0]
    master = moment["master"]
    assert master["shot_archetype"] == "establishing_wide"
    archetype = get_archetype("establishing_wide")
    ic = _FakeImageClientForFrames()
    frames = asyncio.run(generate_coverage_frames(
        {"moment_number": 1, "master": master, "angles": moment.get("angles") or []},
        "https://cast.png", ic, None, aspect="16:9", resolution="1K",
        model_override="z-image"))
    assert frames is not None and len(frames) >= 1
    prompt = ic.calls[0][1]
    assert archetype.image_setup.strip().rstrip(". ") in prompt


def test_cookie_cutter_defense_same_archetype_two_scenes_different_full_prompts():
    """Ryan's amendment: 'make sure how it gets assembled is strategic and
    not robotic — the last thing we want is a cookie-cutter video.' This is
    the direct proof: the SAME archetype ("establishing_wide") drawn in two
    scenes with different mood/environment/genre data. The CRAFT clause
    (archetype + DP) is intentionally similar — that consistency is the
    whole point of a shared vocabulary — but the interpolated location
    differs (data, not chance), and the FULL prompt differs enormously
    because everything this compiler never touches (style prefix, the
    shot's own subject/action sentence, cast/environment locks) differs
    too. The sameness risk is bounded to the craft facts, which SHOULD be
    consistent; it never spreads to the full prompt."""
    scene_a_master = {
        "shot_type": "WS",
        "description": ("Nyla stands at the corridor's far end, breath visible in the cold "
                        "air, one hand braced against the bulkhead."),
        "shot_archetype": "establishing_wide", "shot_location": "the derelict station corridor",
        "lens_mm": 24, "camera_height": "eye",
    }
    scene_b_master = {
        "shot_type": "WS",
        "description": ("Ryan and Vanessa stand at opposite ends of the sunlit kitchen island, "
                        "a bowl of eggs between them."),
        "shot_archetype": "establishing_wide", "shot_location": "the sunlit home kitchen",
        "lens_mm": 24, "camera_height": "eye",
    }

    class _ThrillerProfile:
        visual_style_directive = "Gritty sci-fi thriller, desaturated teal, hard shadow."

    class _CozyProfile:
        visual_style_directive = "Warm domestic sitcom, bright and saturated, soft light."

    ic_a = _FakeImageClientForFrames()
    asyncio.run(generate_coverage_frames(
        {"moment_number": 1, "master": scene_a_master, "angles": []},
        "https://cast-a.png", ic_a, _ThrillerProfile(), aspect="16:9", resolution="1K",
        model_override="z-image"))
    ic_b = _FakeImageClientForFrames()
    asyncio.run(generate_coverage_frames(
        {"moment_number": 1, "master": scene_b_master, "angles": []},
        "https://cast-b.png", ic_b, _CozyProfile(), aspect="16:9", resolution="1K",
        model_override="z-image"))

    prompt_a, prompt_b = ic_a.calls[0][1], ic_b.calls[0][1]

    # The craft clause: archetype composition guidance is IDENTICAL (as
    # designed — a shared vocabulary), the location differs (real data).
    archetype = get_archetype("establishing_wide")
    craft_text = archetype.image_setup.strip()
    assert craft_text in prompt_a and craft_text in prompt_b
    assert "this is the derelict station corridor" in prompt_a
    assert "this is the sunlit home kitchen" in prompt_b
    assert "derelict station corridor" not in prompt_b
    assert "sunlit home kitchen" not in prompt_a

    # The FULL prompt is nowhere near identical — different style, subject,
    # cast, mood — proving the sameness never escapes the craft segment.
    assert prompt_a != prompt_b
    assert "Gritty sci-fi thriller" in prompt_a and "Gritty sci-fi thriller" not in prompt_b
    assert "Warm domestic sitcom" in prompt_b and "Warm domestic sitcom" not in prompt_a
    assert "Nyla" in prompt_a and "Nyla" not in prompt_b
    assert "Vanessa" in prompt_b and "Vanessa" not in prompt_a


# =============================================================================
# 7. check_shot_camera_prose_redundant: the redundancy guard.
# =============================================================================

def test_check_camera_prose_redundant_fires_on_lens_mm_pattern_when_tagged():
    moments = [{
        "moment_number": 1,
        "master": {"shot_type": "WS", "description": "wide shot on a 35mm lens of the valley",
                   "shot_archetype": "establishing_wide"},
        "angles": [],
    }]
    assert check_shot_camera_prose_redundant(moments) == 1


def test_check_camera_prose_redundant_fires_on_close_up_phrase_when_dp_tagged():
    moments = [{
        "moment_number": 1,
        "master": {"shot_type": "CU", "description": "a tight close-up on her eyes",
                   "lens_mm": 85},
        "angles": [],
    }]
    assert check_shot_camera_prose_redundant(moments) == 1


def test_check_camera_prose_redundant_fires_on_wide_shot_phrase():
    moments = [{
        "moment_number": 1,
        "master": {"shot_type": "WS", "description": "a wide shot of the harbor at dusk",
                   "camera_height": "eye"},
        "angles": [],
    }]
    assert check_shot_camera_prose_redundant(moments) == 1


def test_check_camera_prose_redundant_silent_when_untagged():
    moments = [{
        "moment_number": 1,
        "master": {"shot_type": "WS",
                   "description": "a wide shot on a 35mm lens, close-up feel to it"},
        "angles": [],
    }]
    assert check_shot_camera_prose_redundant(moments) == 0


def test_check_camera_prose_redundant_silent_when_tagged_but_clean():
    moments = [{
        "moment_number": 1,
        "master": {"shot_type": "WS", "description": "the rider stands beside the dragon at dawn",
                   "shot_archetype": "wide", "lens_mm": 28},
        "angles": [],
    }]
    assert check_shot_camera_prose_redundant(moments) == 0


def test_check_camera_prose_redundant_counts_per_shot_independently():
    moments = [{
        "moment_number": 1,
        "master": {"shot_type": "WS", "description": "35mm establishing wide shot",
                   "shot_archetype": "establishing_wide"},
        "angles": [
            {"shot_type": "CU", "description": "a close-up on her face", "lens_mm": 85},
            {"shot_type": "MS", "description": "clean plain prose, nothing camera-ish here",
             "dof": "shallow"},
        ],
    }]
    assert check_shot_camera_prose_redundant(moments) == 2


# =============================================================================
# 8. Rule 29 exists; rule 11 is reconciled to point at it.
# =============================================================================

from shared.channel_profile import load_profile  # noqa: E402


def test_rule_29_present_in_system_prompt():
    prompt = _coverage_system_prompt(load_profile({}), max_moments=8, angles_min=2, angles_max=4)
    assert "29) THE COMPILER OWNS CAMERA/COMPOSITION LANGUAGE" in prompt
    assert "D11-3" in prompt


def test_rule_11_reconciled_to_reference_the_dp_row_and_rule_29():
    prompt = _coverage_system_prompt(load_profile({}), max_moments=8, angles_min=2, angles_max=4)
    rule_11_start = prompt.index("11) FOUR CAMERA FACTS")
    rule_12_start = prompt.index("12) A REPEATED SETUP")
    rule_11_text = prompt[rule_11_start:rule_12_start]
    assert "DP row" in rule_11_text
    assert "rule 29" in rule_11_text
    # Facts (a)/(c)/(d) are explicitly kept as prose-only, unstructured.
    assert "no structured field yet" in rule_11_text


if __name__ == "__main__":
    test_compose_is_deterministic_across_repeated_calls()
    test_compose_ignores_description_content_entirely()
    test_compose_does_not_mutate_the_shot_dict()
    test_compose_uses_real_archetype_image_setup_verbatim()
    test_compose_dp_fixed_wording_single_fields()
    test_compose_dp_all_three_fields_joined_in_order()
    test_compose_archetype_plus_dp_joined_with_period()
    test_compose_invalid_archetype_id_contributes_nothing_but_dp_still_renders()
    test_compose_unrecognized_dp_values_still_render_via_literal_fallback()
    test_compose_empty_for_shot_with_no_structured_fields()
    test_compose_empty_for_none_and_absent_keys()
    test_shot_prompt_description_byte_identical_for_every_legacy_era()
    test_shot_prompt_description_prepends_clause_for_tagged_shot()
    test_shot_prompt_description_untagged_shot_unchanged_string()
    test_generate_coverage_frames_legacy_shot_prompt_byte_identical_via_build_image_prompt_from_keyframe()
    test_generate_coverage_frames_prepends_compiled_clause_for_tagged_master()
    test_generate_coverage_frames_prepends_compiled_clause_for_tagged_angle()
    test_generate_coverage_frames_archetype_only_era_now_gets_compiled_clause()
    test_check_camera_prose_redundant_fires_on_lens_mm_pattern_when_tagged()
    test_check_camera_prose_redundant_fires_on_close_up_phrase_when_dp_tagged()
    test_check_camera_prose_redundant_fires_on_wide_shot_phrase()
    test_check_camera_prose_redundant_silent_when_untagged()
    test_check_camera_prose_redundant_silent_when_tagged_but_clean()
    test_check_camera_prose_redundant_counts_per_shot_independently()
    test_rule_29_present_in_system_prompt()
    test_rule_11_reconciled_to_reference_the_dp_row_and_rule_29()
    print("ok — D11-3 mechanical prompt compiler tests passed")
