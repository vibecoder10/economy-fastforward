"""BOARD LAWS (storyengine/BOARD-LAWS.md) self-check — the board-laws build
lane's acceptance test for storyboard/coverage.py: the directive-planning
system prompt (PROMPT leg), the new parser functions (L3/L20 multi-location
+ material-map schema), the deterministic GATE functions, and the
run_coverage REPAIR-leg stamps.

Run: python skills/video-pipeline/tests/test_board_laws.py   (or via pytest)

Companion file storyengine/backend/tests/functional/test_board_laws_sheet_
and_quality_rules.py covers the coverage_to_app.py sheet-composer (which
needs the backend's own venv) and the quality_rules board-scope addition.
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

_PIPELINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PIPELINE_ROOT)
sys.path.insert(0, os.path.join(_PIPELINE_ROOT, "storyboard"))
sys.path.append(os.path.join(_PIPELINE_ROOT, "image_prompts"))

from storyboard.coverage import (  # noqa: E402
    parse_coverage, parse_location_sets, parse_material_map, parse_set_dressing,
    parse_axis_line, parse_setups_line, format_boundary_blocks, scene_has_motion,
    _coverage_system_prompt, _coverage_user_prompt, run_coverage,
    check_headcount_stated, check_group_arrangement_stated, check_camera_facts_present,
    check_repeated_setup_frame_side, check_motion_axis_anchor, check_no_duplicate_panels,
    check_material_map_present_when_mixed, check_location_scoping,
    check_nested_frame_content_specified, check_pov_setup_neutral_and_into_camera,
    check_no_caption_leaking_labels,
)
from shared.channel_profile import load_profile  # noqa: E402


# =============================================================================
# Fixtures — a hand-authored multi-location MOTION scene (modeled on the
# acceptance target, scene1_board_prompt_CORRECTED_v3.txt: pod -> hatch ->
# corridor) and a single-location DIALOGUE/group scene (modeled on
# scene2_board_prompt_v5.txt: the elite viewing hall).
# =============================================================================

MULTI_LOCATION_MOTION_DIRECTIVE = """\
[LOCSET | Pod | Nyla's glass bubble-pod: bed frame-LEFT, armchair CENTRE-RIGHT, a \
human-sized hatch set in the frame-LEFT curve, its sill flush with the catwalk outside. \
These props appear ONLY in Pod panels; never in Corridor panels.]
[LOCSET | Corridor | The underground warren catwalk: wet reflective floor plating, \
stacked glass pods receding into darkness. These props appear ONLY in Corridor panels; \
never in Pod panels.]
[MATERIAL | The pod is part clear glass at the front, part solid white shell at the rear \
and above; the boundary runs along the rib hub directly overhead.]
[AXIS | Nyla frame-LEFT looking frame-RIGHT; key light from screen-left. Holds in every \
shot unless the shot says NEUTRAL]
[SETUPS | A: WS two-shot outside the pod at bed height; F: WS low on the corridor \
catwalk, lens down the tunnel toward the vanishing point]

[MOMENT 1 | LOCATION: Pod | Nyla wakes on the bed]
- MASTER [WS]: (SETUP A) camera outside the pod at bed height, Nyla lies on the bed \
frame-left, eyes closed, occupying a tenth of the frame, three-quarter to the lens.

[MOMENT 2 | LOCATION: Pod | Nyla climbs through the hatch]
- MASTER [MS]: (SETUP A)(BRIDGE) Nyla climbs through the open human-sized hatch, exits \
frame-right and camera holds, one foot already down on the catwalk, to-lens.

[MOMENT 3 | LOCATION: Corridor | Nyla runs down the tunnel]
- MASTER [WS]: (SETUP F) camera low on the wet catwalk at floor height, Nyla small and \
running toward the frame-right vanishing point, the corridor's walls converging on it, \
past her near shoulder, face square to the lens.
"""

DIALOGUE_GROUP_DIRECTIVE = """\
[SET | The elite viewing hall: a curved front row of leather armchairs facing a giant \
screen. Gold Woman and Old Man sit directly beside one another at the frame-LEFT end.]
[AXIS | Gold Woman frame-LEFT looking frame-RIGHT; Old Man frame-RIGHT looking frame-LEFT; \
key light from screen-left. Holds in every shot unless the shot says NEUTRAL]
[SETUPS | A: WS establishing the row from behind and above; B: MS on Gold Woman at seated \
eye height; H: MS two-shot of the pair, camera between the row and the screen]

[MOMENT 1 | the hall is established]
- MASTER [WS]: (SETUP A) camera behind and above the row at standing height, five elites \
fill the row, Gold Woman nearest camera at the frame-left end, then Old Man, then the \
three others receding toward frame-right, all faces turned to the screen.

[MOMENT 2 | Gold Woman speaks]
LINE: Gold Woman | "They never wake up, do they."
- MASTER [MS]: (SETUP B) Gold Woman fills the middle third at frame-left, three-quarter \
to the lens, lifting her glass toward the screen.
"""

_PROFILE = load_profile({})


# =============================================================================
# PARSER (L3/L20 multi-location + material-map schema)
# =============================================================================

def test_parse_location_sets_multi_location():
    sets = parse_location_sets(MULTI_LOCATION_MOTION_DIRECTIVE)
    assert set(sets.keys()) == {"Pod", "Corridor"}
    assert "hatch" in sets["Pod"]
    assert "catwalk" in sets["Corridor"]
    assert "bed" not in sets["Corridor"]


def test_parse_location_sets_empty_for_single_location_plan():
    assert parse_location_sets(DIALOGUE_GROUP_DIRECTIVE) == {}


def test_parse_material_map():
    assert "clear glass" in parse_material_map(MULTI_LOCATION_MOTION_DIRECTIVE)
    assert parse_material_map(DIALOGUE_GROUP_DIRECTIVE) is None


def test_parse_coverage_captures_per_moment_location():
    moments = parse_coverage(MULTI_LOCATION_MOTION_DIRECTIVE)
    assert len(moments) == 3
    assert moments[0]["location"] == "Pod"
    assert moments[1]["location"] == "Pod"
    assert moments[2]["location"] == "Corridor"
    # summary text has the "LOCATION: name | " prefix stripped out.
    assert "LOCATION" not in moments[0]["summary"]


def test_parse_coverage_location_none_for_single_location_plan():
    moments = parse_coverage(DIALOGUE_GROUP_DIRECTIVE)
    assert all(m["location"] is None for m in moments)


def test_parse_coverage_legacy_plan_unaffected_by_location_field():
    """Byte-compatibility: a plan with no LOCATION prefix at all parses to
    location=None for every moment — the new key never disturbs the master/
    angle/speaker/line fields legacy callers already depend on."""
    legacy = "[MOMENT 1 | x]\n- MASTER [WS]: a plain establishing shot.\n"
    moments = parse_coverage(legacy)
    assert moments[0]["location"] is None
    assert moments[0]["master"]["shot_type"] == "WS"


def test_scene_has_motion_true_for_bridge_tag():
    moments = parse_coverage(MULTI_LOCATION_MOTION_DIRECTIVE)
    assert scene_has_motion(moments, parse_location_sets(MULTI_LOCATION_MOTION_DIRECTIVE)) is True


def test_scene_has_motion_false_for_planted_dialogue_scene():
    moments = parse_coverage(DIALOGUE_GROUP_DIRECTIVE)
    assert scene_has_motion(moments, parse_location_sets(DIALOGUE_GROUP_DIRECTIVE)) is False


def test_format_boundary_blocks_shape():
    text = format_boundary_blocks(
        incoming={"description": "she climbs through the hatch, turning frame-right",
                  "relationship": "CONTINUATION",
                  "instruction": "enter from frame-left, keep travelling the same way"},
        outgoing={"description": "the dead end fills the frame, she has stopped",
                  "relationship": "CONTINUATION, with the reversal on screen"},
    )
    assert "INCOMING — the previous scene ended on:" in text
    assert "relates to it by CONTINUATION" in text
    assert "OUTGOING — your FINAL panel must be:" in text
    assert "because the next scene opens by" in text


def test_format_boundary_blocks_empty_when_neither_given():
    assert format_boundary_blocks(None, None) == ""
    assert format_boundary_blocks({}, {}) == ""


# =============================================================================
# PROMPT leg — the directive-planning system/user prompt
# =============================================================================

def test_system_prompt_carries_every_new_law_marker():
    prompt = _coverage_system_prompt(_PROFILE, max_moments=6, angles_min=2, angles_max=4)
    for marker in (
        "MULTIPLE LOCATIONS", "LOCSET", "MATERIAL MAP", "MOTION IS LEGAL",
        "FOUR CAMERA FACTS", "REPEATED SETUP NAMES", "VISIBLE LINE",
        "SECOND FRAME", "BACKGROUND PEOPLE ARE PART OF THE SET",
        "SHIFT OF ATTENTION", "REVERSE ANGLE CHANGES", "LOCK THE HEADCOUNT",
        "DISCOVERY OBJECT IS PLANTED", "DIEGETIC CAMERA POV",
        "STILL PANEL CANNOT SHOW DURATION", "SCENE BOUNDARIES ARE ASSIGNED",
        "INSTRUCTIONS ARE NOT CAPTIONS",
    ):
        assert marker in prompt, f"missing law marker: {marker!r}"
    # L0/L1/L2 preserved byte-compatibly (inherited, unmodified rule text).
    assert "NEVER describe" in prompt and "world space" in prompt  # L0
    assert "180-DEGREE RULE" in prompt  # L1
    assert "ONE flowing sentence" in prompt  # L2-adjacent panel discipline


def test_system_prompt_omits_board_rules_block_when_none_given():
    prompt = _coverage_system_prompt(_PROFILE, max_moments=6, angles_min=2, angles_max=4)
    assert "<board_quality_rules>" not in prompt


def test_system_prompt_includes_board_rules_block_when_given():
    prompt = _coverage_system_prompt(
        _PROFILE, max_moments=6, angles_min=2, angles_max=4,
        board_rules_text="[BQ-1] [HARD-GATE] Every hatch must be human-sized.")
    assert "<board_quality_rules>" in prompt
    assert "Every hatch must be human-sized." in prompt


def test_user_prompt_includes_boundary_blocks_when_given():
    prompt = _coverage_user_prompt(
        "Nyla wakes.", "Test Video", None, [1], [],
        incoming={"description": "the previous scene's final panel",
                  "relationship": "MATCH", "instruction": "match its shape"},
        outgoing={"description": "her final panel", "relationship": "CONTRAST"})
    assert "SCENE BOUNDARIES" in prompt
    assert "INCOMING —" in prompt and "OUTGOING —" in prompt


def test_user_prompt_omits_boundary_section_when_absent():
    prompt = _coverage_user_prompt("Nyla wakes.", "Test Video", None, [1], [])
    assert "SCENE BOUNDARIES" not in prompt


# =============================================================================
# GATE leg — deterministic checks (all warning-only, return violation counts)
# =============================================================================

def test_check_headcount_stated_flags_missing_number():
    moments = [{"moment_number": 1, "master": {"shot_type": "WS",
               "description": "A crowd of elites fills the row, watching the screen."},
               "angles": []}]
    assert check_headcount_stated(moments) == 1


def test_check_headcount_stated_passes_when_number_present():
    moments = parse_coverage(DIALOGUE_GROUP_DIRECTIVE)
    assert check_headcount_stated(moments) == 0


def test_check_group_arrangement_stated_flags_count_with_no_order():
    moments = [{"moment_number": 1, "master": {"shot_type": "WS",
               "description": "Exactly five elites fill the row, watching the screen."},
               "angles": []}]
    assert check_group_arrangement_stated(moments) == 1


def test_check_group_arrangement_stated_passes_the_acceptance_style_phrasing():
    moments = parse_coverage(DIALOGUE_GROUP_DIRECTIVE)
    assert check_group_arrangement_stated(moments) == 0


def test_check_camera_facts_present_flags_missing_face_visibility_term():
    moments = [{"moment_number": 1, "speaker": "X", "line": "hi", "master": {"shot_type": "MCU",
               "description": "Close on her, delivering the line."}, "angles": []}]
    assert check_camera_facts_present(moments) == 1


def test_check_camera_facts_present_passes_with_explicit_term():
    moments = [{"moment_number": 1, "speaker": "X", "line": "hi", "master": {"shot_type": "MCU",
               "description": "Close on her, three-quarter to the lens, delivering the line."},
               "angles": []}]
    assert check_camera_facts_present(moments) == 0


def test_check_repeated_setup_frame_side_flags_unqualified_repeat():
    moments = [
        {"moment_number": 1, "master": {"shot_type": "WS",
         "description": "(SETUP A) she stands at the pod's frame-right curve."}, "angles": []},
        {"moment_number": 2, "master": {"shot_type": "WS",
         "description": "(SETUP A) she is pressed to the glass."}, "angles": []},
    ]
    assert check_repeated_setup_frame_side(moments) == 1


def test_check_repeated_setup_frame_side_passes_the_acceptance_style_phrasing():
    moments = [
        {"moment_number": 1, "master": {"shot_type": "WS",
         "description": "(SETUP A) she stands at the pod's frame-right curve."}, "angles": []},
        {"moment_number": 2, "master": {"shot_type": "WS",
         "description": "(SETUP A) she is pressed to THAT SAME frame-right pane."}, "angles": []},
    ]
    assert check_repeated_setup_frame_side(moments) == 0


def test_check_motion_axis_anchor_flags_bridge_with_no_visible_line():
    moments = [{"moment_number": 1, "master": {"shot_type": "WS",
               "description": "(SETUP F)(BRIDGE) she runs down the corridor."}, "angles": []}]
    assert check_motion_axis_anchor(moments) == 1


def test_check_motion_axis_anchor_passes_the_fixture_directive():
    moments = parse_coverage(MULTI_LOCATION_MOTION_DIRECTIVE)
    assert check_motion_axis_anchor(moments) == 0


def test_check_no_duplicate_panels_flags_identical_repeat():
    moments = [
        {"moment_number": 1, "master": {"shot_type": "WS",
         "description": "Nyla stands still in the room."}, "angles": []},
        {"moment_number": 2, "master": {"shot_type": "WS",
         "description": "Nyla stands still in the room."}, "angles": []},
    ]
    assert check_no_duplicate_panels(moments) == 1


def test_check_no_duplicate_panels_passes_an_escalation():
    moments = [
        {"moment_number": 1, "master": {"shot_type": "WS",
         "description": "Nyla stands still in the room."}, "angles": []},
        {"moment_number": 2, "master": {"shot_type": "MCU",
         "description": "Nyla's face, still and unreadable."}, "angles": []},
    ]
    assert check_no_duplicate_panels(moments) == 0


def test_check_material_map_present_when_mixed_flags_omission():
    directive = ("[SET | a pod, part glass at the front and part solid at the rear]\n"
                "[MOMENT 1 | x]\n- MASTER [WS]: establishing.\n")
    assert check_material_map_present_when_mixed(directive) == 1


def test_check_material_map_present_when_mixed_passes_the_fixture_directive():
    assert check_material_map_present_when_mixed(MULTI_LOCATION_MOTION_DIRECTIVE) == 0


def test_check_location_scoping_flags_cross_contamination():
    location_sets = parse_location_sets(MULTI_LOCATION_MOTION_DIRECTIVE)
    moments = [{"moment_number": 9, "location": "Corridor", "master": {"shot_type": "WS",
               "description": "The corridor recedes past the armchair centre-right."},
               "angles": []}]
    assert check_location_scoping(moments, location_sets) >= 1


def test_check_location_scoping_passes_the_fixture_directive():
    moments = parse_coverage(MULTI_LOCATION_MOTION_DIRECTIVE)
    location_sets = parse_location_sets(MULTI_LOCATION_MOTION_DIRECTIVE)
    assert check_location_scoping(moments, location_sets) == 0


def test_check_location_scoping_is_zero_for_single_location_scene():
    moments = parse_coverage(DIALOGUE_GROUP_DIRECTIVE)
    assert check_location_scoping(moments, {}) == 0


def test_check_nested_frame_content_specified_flags_unspecified_screen():
    moments = [{"moment_number": 1, "master": {"shot_type": "WS",
               "description": "The screen looms over the row."}, "angles": []}]
    assert check_nested_frame_content_specified(moments) == 1


def test_check_pov_setup_neutral_and_into_camera_flags_missing_terms():
    moments = [{"moment_number": 1, "master": {"shot_type": "WS",
               "description": "The lens POV looks down at her."}, "angles": []}]
    assert check_pov_setup_neutral_and_into_camera(moments) == 1


def test_check_pov_setup_neutral_and_into_camera_passes_full_phrasing():
    moments = [{"moment_number": 1, "master": {"shot_type": "WS",
               "description": "NEUTRAL: the lens POV looks down, her eyes going into camera."},
               "angles": []}]
    assert check_pov_setup_neutral_and_into_camera(moments) == 0


def test_check_no_caption_leaking_labels_flags_all_caps_directive():
    moments = [{"moment_number": 1, "master": {"shot_type": "WS",
               "description": "ARRANGEMENT AS SEEN FROM THIS CAMERA REVERSED: five elites."},
               "angles": []}]
    assert check_no_caption_leaking_labels(moments) == 1


def test_check_no_caption_leaking_labels_passes_ordinary_prose():
    moments = parse_coverage(DIALOGUE_GROUP_DIRECTIVE)
    assert check_no_caption_leaking_labels(moments) == 0


def test_check_no_caption_leaking_labels_ignores_structural_tags():
    moments = [{"moment_number": 1, "master": {"shot_type": "WS",
               "description": "(SETUP A)(BRIDGE) NEVER mirror this, ALWAYS hold the frame."},
               "angles": []}]
    # Emphasis words (NEVER/ALWAYS) and structural (SETUP)/(BRIDGE) tags never
    # false-positive the caption-leak check (no colon-terminated caps run).
    assert check_no_caption_leaking_labels(moments) == 0


# =============================================================================
# REPAIR leg — run_coverage's per-shot lock stamps
# =============================================================================

def _fake_frames_factory():
    async def _fake_frames(moment, cast_url, image_client, profile=None, env_url=None,
                           aspect="16:9", resolution="1K", sem=None, model_override=None,
                           setup_anchors=None):
        frames = [{"role": "master", "shot_type": moment["master"]["shot_type"],
                  "description": moment["master"]["description"], "url": "https://img/m.png"}]
        for a in moment.get("angles") or []:
            frames.append({"role": "angle", "shot_type": a["shot_type"],
                           "description": a["description"], "url": "https://img/a.png"})
        return frames
    return _fake_frames


def test_run_coverage_location_scoped_set_lock_applied(tmp_path):
    """L3 REPAIR leg: a multi-location scene's per-shot draw prompt is
    stamped with ONLY its own moment's location text — Pod shots never carry
    the Corridor set text and vice versa — never the old blanket scene-wide
    stamp, which is the exact bug L3 exists to fix."""
    outdir = str(tmp_path)
    with patch("storyboard.coverage.resolve_cast_url", AsyncMock(return_value="https://cast.png")), \
         patch("storyboard.coverage.generate_coverage_frames", AsyncMock(side_effect=_fake_frames_factory())), \
         patch("storyboard.coverage._download", lambda url, path: None):
        out = asyncio.run(run_coverage(
            beat_text="Nyla wakes and runs.", image_client=None, outdir=outdir,
            cast_url="https://cast.png", directive_text=MULTI_LOCATION_MOTION_DIRECTIVE,
            max_moments=10, angles_max=4, max_frames=None,
        ))
    assert not out.get("error"), out
    m1, m3 = out["moments"][0], out["moments"][2]
    assert "hatch" in m1["master"]["description"]
    assert "catwalk" in m1["master"]["description"]  # Pod's own text mentions the catwalk sill
    assert "armchair" not in m3["master"]["description"]  # Corridor shot never gets Pod-only props
    assert "never" in m1["master"]["description"].lower()  # cross-contamination prohibition present


def test_run_coverage_material_map_lock_applied(tmp_path):
    outdir = str(tmp_path)
    with patch("storyboard.coverage.resolve_cast_url", AsyncMock(return_value="https://cast.png")), \
         patch("storyboard.coverage.generate_coverage_frames", AsyncMock(side_effect=_fake_frames_factory())), \
         patch("storyboard.coverage._download", lambda url, path: None):
        out = asyncio.run(run_coverage(
            beat_text="Nyla wakes and runs.", image_client=None, outdir=outdir,
            cast_url="https://cast.png", directive_text=MULTI_LOCATION_MOTION_DIRECTIVE,
            max_moments=10, angles_max=4, max_frames=None,
        ))
    assert not out.get("error"), out
    for m in out["moments"]:
        assert "Material map" in m["master"]["description"]


def test_run_coverage_motion_capable_staging_lock_for_motion_scene(tmp_path):
    """L4 REPAIR leg fix: a scene with a (BRIDGE) shot gets the motion-
    capable CAMERA KIT tail, never the unconditional (and here, WRONG)
    "actors are PLANTED and never move" text."""
    outdir = str(tmp_path)
    with patch("storyboard.coverage.resolve_cast_url", AsyncMock(return_value="https://cast.png")), \
         patch("storyboard.coverage.generate_coverage_frames", AsyncMock(side_effect=_fake_frames_factory())), \
         patch("storyboard.coverage._download", lambda url, path: None):
        out = asyncio.run(run_coverage(
            beat_text="Nyla wakes and runs.", image_client=None, outdir=outdir,
            cast_url="https://cast.png", directive_text=MULTI_LOCATION_MOTION_DIRECTIVE,
            max_moments=10, angles_max=4, max_frames=None,
        ))
    assert not out.get("error"), out
    desc = out["moments"][0]["master"]["description"]
    assert "MOTION-CAPABLE" in desc
    assert "PLANTED and never move" not in desc


def test_run_coverage_planted_staging_lock_unaffected_for_planted_scene(tmp_path):
    """Byte-compatible control: a purely planted dialogue scene keeps the
    ORIGINAL "actors are PLANTED and never move" text — L4's fix changes
    nothing for the scene shape it was never wrong about."""
    outdir = str(tmp_path)
    with patch("storyboard.coverage.resolve_cast_url", AsyncMock(return_value="https://cast.png")), \
         patch("storyboard.coverage.generate_coverage_frames", AsyncMock(side_effect=_fake_frames_factory())), \
         patch("storyboard.coverage._download", lambda url, path: None):
        out = asyncio.run(run_coverage(
            beat_text="They watch the screen.", image_client=None, outdir=outdir,
            cast_url="https://cast.png", directive_text=DIALOGUE_GROUP_DIRECTIVE,
            max_moments=10, angles_max=4, max_frames=None,
        ))
    assert not out.get("error"), out
    desc = out["moments"][0]["master"]["description"]
    assert "PLANTED and never move" in desc
    assert "MOTION-CAPABLE" not in desc


if __name__ == "__main__":
    test_parse_location_sets_multi_location()
    test_parse_location_sets_empty_for_single_location_plan()
    test_parse_material_map()
    test_parse_coverage_captures_per_moment_location()
    test_parse_coverage_location_none_for_single_location_plan()
    test_parse_coverage_legacy_plan_unaffected_by_location_field()
    test_scene_has_motion_true_for_bridge_tag()
    test_scene_has_motion_false_for_planted_dialogue_scene()
    test_format_boundary_blocks_shape()
    test_format_boundary_blocks_empty_when_neither_given()
    test_system_prompt_carries_every_new_law_marker()
    test_system_prompt_omits_board_rules_block_when_none_given()
    test_system_prompt_includes_board_rules_block_when_given()
    test_user_prompt_includes_boundary_blocks_when_given()
    test_user_prompt_omits_boundary_section_when_absent()
    test_check_headcount_stated_flags_missing_number()
    test_check_headcount_stated_passes_when_number_present()
    test_check_group_arrangement_stated_flags_count_with_no_order()
    test_check_group_arrangement_stated_passes_the_acceptance_style_phrasing()
    test_check_camera_facts_present_flags_missing_face_visibility_term()
    test_check_camera_facts_present_passes_with_explicit_term()
    test_check_repeated_setup_frame_side_flags_unqualified_repeat()
    test_check_repeated_setup_frame_side_passes_the_acceptance_style_phrasing()
    test_check_motion_axis_anchor_flags_bridge_with_no_visible_line()
    test_check_motion_axis_anchor_passes_the_fixture_directive()
    test_check_no_duplicate_panels_flags_identical_repeat()
    test_check_no_duplicate_panels_passes_an_escalation()
    test_check_material_map_present_when_mixed_flags_omission()
    test_check_material_map_present_when_mixed_passes_the_fixture_directive()
    test_check_location_scoping_flags_cross_contamination()
    test_check_location_scoping_passes_the_fixture_directive()
    test_check_location_scoping_is_zero_for_single_location_scene()
    test_check_nested_frame_content_specified_flags_unspecified_screen()
    test_check_pov_setup_neutral_and_into_camera_flags_missing_terms()
    test_check_pov_setup_neutral_and_into_camera_passes_full_phrasing()
    test_check_no_caption_leaking_labels_flags_all_caps_directive()
    test_check_no_caption_leaking_labels_passes_ordinary_prose()
    test_check_no_caption_leaking_labels_ignores_structural_tags()
    import tempfile
    with tempfile.TemporaryDirectory() as _td:
        import pathlib
        _p = pathlib.Path(_td)
        test_run_coverage_location_scoped_set_lock_applied(_p)
        test_run_coverage_material_map_lock_applied(_p)
        test_run_coverage_motion_capable_staging_lock_for_motion_scene(_p)
        test_run_coverage_planted_staging_lock_unaffected_for_planted_scene(_p)
    print("ok — board laws (coverage.py) self-checks passed")
