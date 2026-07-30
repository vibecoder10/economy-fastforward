"""D6-2 (storyengine/tasks/loop-checklist.md, PHASE D6) self-check for
storyboard/coverage.py: the NEW gates (L12, L15, L18) and the NEW repair
legs (L11, L12, L15, L16, L17, L19, L22) that give BOARD-LAWS.md's
previously prompt-only laws a real second (gate) and/or third (repair) leg.

Companion file storyengine/backend/tests/functional/test_d6_2_repair_
stamps.py is THE decisive test: it proves these repair stamps survive a
SINGLE-SHOT REDRAW (redraw_asset_image), the exact failure class that cost
$0.20 on 2026-07-29. This file covers the coverage.py functions in
isolation plus the run_coverage build-time integration (migration 143's
persist leg: shot_location / group_arrangement).

Run: python skills/video-pipeline/tests/test_d6_2_repair_stamps.py   (or via pytest)
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
    parse_coverage, parse_setups_line, parse_reverse_setup_pairs,
    compute_reverse_arrangement, run_coverage,
    check_population_specified, check_attention_orientation_stated,
    check_discovery_object_unremarked,
    apply_nested_frame_content_lock, apply_population_lock,
    apply_attention_orientation_lock, apply_pov_diegetic_lock,
    apply_reverse_background_lock, apply_group_arrangement_lock,
)
from shared.channel_profile import load_profile  # noqa: E402

_PROFILE = load_profile({})

GROUP_SCENE_WITH_REVERSE = """\
[SET | The elite viewing hall: a curved front row of leather armchairs facing a giant \
screen. Gold Woman and Old Man sit directly beside one another at the frame-LEFT end.]
[AXIS | Gold Woman frame-LEFT looking frame-RIGHT; Old Man frame-RIGHT looking frame-LEFT; \
key light from screen-left. Holds in every shot unless the shot says NEUTRAL]
[SETUPS | A: WS establishing the row from behind and above; B: MS on Gold Woman at seated \
eye height; G: WS the reverse wide from the screen's side, the matched reverse of A]

[MOMENT 1 | the hall is established]
- MASTER [WS]: (SETUP A) camera behind and above the row at standing height, five elites \
fill the row, Gold Woman nearest camera at the frame-left end, then Old Man, then the \
three others receding toward frame-right, all faces turned to the screen.

[MOMENT 2 | the reverse wide]
- MASTER [WS]: (SETUP G) camera from the screen's side looking back at the row, all five \
elites visible, watching the feed.
"""


# =============================================================================
# PARSER — parse_reverse_setup_pairs (L16's computed relationship)
# =============================================================================

def test_parse_reverse_setup_pairs_finds_the_stated_pair():
    pairs = parse_reverse_setup_pairs(parse_setups_line(GROUP_SCENE_WITH_REVERSE))
    assert pairs == {"A": "G", "G": "A"}


def test_parse_reverse_setup_pairs_empty_when_no_reverse_phrase():
    assert parse_reverse_setup_pairs("A: WS establishing; B: MS on Gold Woman") == {}


def test_parse_reverse_setup_pairs_empty_for_none():
    assert parse_reverse_setup_pairs(None) == {}


# =============================================================================
# compute_reverse_arrangement — L22's actual computation (order flip +
# frame-side swap)
# =============================================================================

def test_compute_reverse_arrangement_flips_order_and_sides():
    src = "Priya nearest camera at the frame-left end, then Marcus, then Old Man"
    flipped = compute_reverse_arrangement(src)
    assert flipped is not None
    # order reversed
    assert flipped.index("Old Man") < flipped.index("Marcus") < flipped.index("Priya")
    # frame side swapped
    assert "frame-right" in flipped
    assert "frame-left end" not in flipped


def test_compute_reverse_arrangement_none_when_not_a_list():
    assert compute_reverse_arrangement("five elites fill the row") is None
    assert compute_reverse_arrangement("") is None
    assert compute_reverse_arrangement(None) is None


# =============================================================================
# NEW gates — L12, L15, L18 (previously had NO gate at all)
# =============================================================================

def test_check_population_specified_flags_headcount_with_no_look():
    moments = [{"moment_number": 1, "master": {"shot_type": "WS",
               "description": "Exactly five elites fill the row, watching the screen."},
               "angles": []}]
    assert check_population_specified(moments) == 1


def test_check_population_specified_passes_with_descriptive_language():
    moments = [{"moment_number": 1, "master": {"shot_type": "WS",
               "description": "Exactly five elites fill the row, hooded and cloaked, "
                              "posture slouched, watching the screen."},
               "angles": []}]
    assert check_population_specified(moments) == 0


def test_check_attention_orientation_stated_flags_unanchored_turn():
    moments = [{"moment_number": 1, "master": {"shot_type": "MS",
               "description": "She turns toward him, surprised."}, "angles": []}]
    assert check_attention_orientation_stated(moments) == 1


def test_check_attention_orientation_stated_passes_with_fixed_anchor():
    moments = [{"moment_number": 1, "master": {"shot_type": "MS",
               "description": "She turns toward him, her hips and feet unchanged, only "
                              "her head and shoulders turning."}, "angles": []}]
    assert check_attention_orientation_stated(moments) == 0


def test_check_discovery_object_unremarked_flags_early_emphasis():
    moments = [
        {"moment_number": 1, "master": {"shot_type": "WS",
         "description": "A glowing key sits on the shelf, unremarked."}, "angles": []},
        {"moment_number": 2, "master": {"shot_type": "MCU",
         "description": "She finally notices the key on the shelf."}, "angles": []},
    ]
    assert check_discovery_object_unremarked(moments) == 1


def test_check_discovery_object_unremarked_zero_when_no_discovery_beat():
    moments = [{"moment_number": 1, "master": {"shot_type": "WS",
               "description": "A glowing key sits on the shelf."}, "angles": []}]
    assert check_discovery_object_unremarked(moments) == 0


# =============================================================================
# REPAIR legs — direct unit tests on the apply_* functions
# =============================================================================

def test_apply_nested_frame_content_lock_repeats_canonical_content():
    moments = [
        {"moment_number": 1, "master": {"shot_type": "WS",
         "description": "The screen shows the underground warren's live feed."}, "angles": []},
        {"moment_number": 2, "master": {"shot_type": "MCU",
         "description": "Old Man glances at the screen."}, "angles": []},
    ]
    n = apply_nested_frame_content_lock(moments)
    assert n == 1
    assert "underground warren's live feed" in moments[1]["master"]["description"]


def test_apply_nested_frame_content_lock_no_op_when_never_established():
    moments = [{"moment_number": 1, "master": {"shot_type": "MCU",
               "description": "Old Man glances at the screen."}, "angles": []}]
    assert apply_nested_frame_content_lock(moments) == 0


def test_apply_population_lock_repeats_canonical_look():
    moments = [
        {"moment_number": 1, "master": {"shot_type": "WS",
         "description": "Five elites fill the row, hooded and cloaked, posture slouched."},
         "angles": []},
        {"moment_number": 2, "master": {"shot_type": "MS",
         "description": "Five elites lean forward toward the screen."}, "angles": []},
    ]
    n = apply_population_lock(moments)
    assert n == 1
    assert "hooded and cloaked" in moments[1]["master"]["description"]


def test_apply_attention_orientation_lock_stamps_flagged_shots():
    moments = [{"moment_number": 1, "master": {"shot_type": "MS",
               "description": "She turns toward him, surprised."}, "angles": []}]
    n = apply_attention_orientation_lock(moments)
    assert n == 1
    assert "stays FIXED" in moments[0]["master"]["description"]


def test_apply_pov_diegetic_lock_stamps_flagged_shots():
    moments = [{"moment_number": 1, "master": {"shot_type": "WS",
               "description": "The lens POV looks down at her."}, "angles": []}]
    n = apply_pov_diegetic_lock(moments)
    assert n == 1
    assert "NEUTRAL setup occupying the in-story device's own" in moments[0]["master"]["description"]


def test_apply_reverse_background_lock_computed_from_setups_line():
    moments = parse_coverage(GROUP_SCENE_WITH_REVERSE)
    pairs = parse_reverse_setup_pairs(parse_setups_line(GROUP_SCENE_WITH_REVERSE))
    n = apply_reverse_background_lock(moments, pairs)
    assert n == 2  # both SETUP A and SETUP G shots get the reciprocal reminder
    assert "matched reverse of SETUP G" in moments[0]["master"]["description"]
    assert "matched reverse of SETUP A" in moments[1]["master"]["description"]


def test_apply_reverse_background_lock_no_op_without_pairs():
    moments = parse_coverage(GROUP_SCENE_WITH_REVERSE)
    assert apply_reverse_background_lock(moments, {}) == 0


def test_apply_group_arrangement_lock_flips_the_reverse_shot():
    moments = parse_coverage(GROUP_SCENE_WITH_REVERSE)
    pairs = parse_reverse_setup_pairs(parse_setups_line(GROUP_SCENE_WITH_REVERSE))
    n = apply_group_arrangement_lock(moments, pairs)
    assert n == 1  # moment 2 (SETUP G, the reverse) is repaired; moment 1 already stated it
    assert moments[0]["master"].get("group_arrangement")  # canonical captured on the establishing shot
    m2 = moments[1]["master"]
    assert "computed" in m2["description"] and "order flipped" in m2["description"]
    assert m2.get("group_arrangement")
    # the flip actually swapped a frame side token somewhere in the computed text
    assert "frame-right" in m2["group_arrangement"] or "frame-left" in m2["group_arrangement"]


# =============================================================================
# BUILD-TIME INTEGRATION — run_coverage persists shot_location and
# group_arrangement (migration 143's persist leg) onto the frame dicts that
# store_scene reads.
# =============================================================================

def _fake_frames_factory():
    async def _fake_frames(moment, cast_url, image_client, profile=None, env_url=None,
                           aspect="16:9", resolution="1K", sem=None, model_override=None,
                           setup_anchors=None):
        frames = [{"role": "master", "shot_type": moment["master"]["shot_type"],
                  "description": moment["master"]["description"], "url": "https://img/m.png",
                  "shot_location": moment["master"].get("shot_location"),
                  "group_arrangement": moment["master"].get("group_arrangement")}]
        for a in moment.get("angles") or []:
            frames.append({"role": "angle", "shot_type": a["shot_type"],
                           "description": a["description"], "url": "https://img/a.png",
                           "shot_location": a.get("shot_location"),
                           "group_arrangement": a.get("group_arrangement")})
        return frames
    return _fake_frames


def test_run_coverage_persists_group_arrangement_onto_frames(tmp_path):
    outdir = str(tmp_path)
    with patch("storyboard.coverage.resolve_cast_url", AsyncMock(return_value="https://cast.png")), \
         patch("storyboard.coverage.generate_coverage_frames", AsyncMock(side_effect=_fake_frames_factory())), \
         patch("storyboard.coverage._download", lambda url, path: None):
        out = asyncio.run(run_coverage(
            beat_text="The hall watches the screen.", image_client=None, outdir=outdir,
            cast_url="https://cast.png", directive_text=GROUP_SCENE_WITH_REVERSE,
            max_moments=10, angles_max=4, max_frames=None,
        ))
    assert not out.get("error"), out
    m1_frame = out["moments"][0]["frames"][0]
    m2_frame = out["moments"][1]["frames"][0]
    assert m1_frame.get("group_arrangement")
    assert m2_frame.get("group_arrangement")
    assert "matched reverse of SETUP" in m2_frame["description"]


def test_run_coverage_shot_location_none_for_single_location_scene(tmp_path):
    """NULL-safety: a plain single-location scene (no LOCATION: prefix)
    persists shot_location=None on every frame — no error, no crash."""
    outdir = str(tmp_path)
    with patch("storyboard.coverage.resolve_cast_url", AsyncMock(return_value="https://cast.png")), \
         patch("storyboard.coverage.generate_coverage_frames", AsyncMock(side_effect=_fake_frames_factory())), \
         patch("storyboard.coverage._download", lambda url, path: None):
        out = asyncio.run(run_coverage(
            beat_text="They watch the screen.", image_client=None, outdir=outdir,
            cast_url="https://cast.png", directive_text=GROUP_SCENE_WITH_REVERSE,
            max_moments=10, angles_max=4, max_frames=None,
        ))
    assert not out.get("error"), out
    for m in out["moments"]:
        for fr in m["frames"]:
            assert fr.get("shot_location") is None


if __name__ == "__main__":
    test_parse_reverse_setup_pairs_finds_the_stated_pair()
    test_parse_reverse_setup_pairs_empty_when_no_reverse_phrase()
    test_parse_reverse_setup_pairs_empty_for_none()
    test_compute_reverse_arrangement_flips_order_and_sides()
    test_compute_reverse_arrangement_none_when_not_a_list()
    test_check_population_specified_flags_headcount_with_no_look()
    test_check_population_specified_passes_with_descriptive_language()
    test_check_attention_orientation_stated_flags_unanchored_turn()
    test_check_attention_orientation_stated_passes_with_fixed_anchor()
    test_check_discovery_object_unremarked_flags_early_emphasis()
    test_check_discovery_object_unremarked_zero_when_no_discovery_beat()
    test_apply_nested_frame_content_lock_repeats_canonical_content()
    test_apply_nested_frame_content_lock_no_op_when_never_established()
    test_apply_population_lock_repeats_canonical_look()
    test_apply_attention_orientation_lock_stamps_flagged_shots()
    test_apply_pov_diegetic_lock_stamps_flagged_shots()
    test_apply_reverse_background_lock_computed_from_setups_line()
    test_apply_reverse_background_lock_no_op_without_pairs()
    test_apply_group_arrangement_lock_flips_the_reverse_shot()
    import tempfile
    with tempfile.TemporaryDirectory() as _td:
        import pathlib
        _p = pathlib.Path(_td)
        test_run_coverage_persists_group_arrangement_onto_frames(_p)
        test_run_coverage_shot_location_none_for_single_location_scene(_p)
    print("ok — D6-2 repair-stamp coverage.py self-checks passed")
