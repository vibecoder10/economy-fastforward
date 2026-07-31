"""D12-3 (board rhythm report): the audit found storyboard intelligence
checks setup-family variety (enforce_setup_variety, WITH a repair leg) and
duplicate panels (check_no_duplicate_panels), but nothing reports on visual
RHYTHM — shot-size runs, lens repetition, purpose monotony — even though the
structured per-shot data (purpose_kind D9-1, transition_kind D9-6,
shot_archetype D11-1, lens_mm D11-2) has existed since those harvest chunks.

This chunk adds, all in storyboard/coverage.py:
  1. build_rhythm_report(moments) — a PURE function (no printing, no
     mutation) returning a compact dict: counts per shot_type; the longest
     consecutive same-size run (and where); the longest same-lens_mm run;
     the longest same-purpose_kind run; archetype diversity
     (distinct/total); transition-kind mix.
  2. Three WARN-only checks in the existing check_* family style —
     check_shot_size_rhythm, check_lens_rhythm, check_purpose_monotony —
     wired into run_coverage's post-parse block alongside check_shot_dp_
     valid and friends.

Covers, bottom-up:
  1. The three private sequence helpers (_rhythm_size_sequence/_rhythm_lens_
     sequence/_rhythm_purpose_sequence) and _longest_run.
  2. build_rhythm_report on a rich fixture (planted runs on all three
     dimensions, an archetype mix, a transition mix) — every key checked.
  3. build_rhythm_report on the FOUR prior directive eras (same fixtures
     test_d11_2_shot_dp.py already proved parse byte-identical) — tolerant
     of every D9-1/D9-6/D11-1/D11-2 field being absent; shot_type itself
     (predates all of them) still produces a real, non-None
     longest_size_run.
  4. check_shot_size_rhythm: silent under the threshold, fires on a planted
     run, INSERT shots are excluded from the run ENTIRELY (neither extend
     nor break it), REACTION shots are NOT exempted (mirrors the codebase's
     own asymmetry: _carries_facing_law excludes INSERT but actively
     INCLUDES REACTION).
  5. check_lens_rhythm / check_purpose_monotony: silent when the field is
     absent throughout (every legacy era), fires on a planted run, a run
     interrupted by an absent-field shot does not carry across the gap.
  6. Byte-identical/silent-pass guarantee: all three checks return 0 on
     every one of the four prior directive eras — the exact "plans with all
     [D9-1/D9-6/D11-1/D11-2] metadata absent produce the same warn behavior
     as today" contract this chunk promises.

STASH-PROOF: build_rhythm_report/check_shot_size_rhythm/check_lens_rhythm/
check_purpose_monotony do not exist before D12-3 — `git stash` (or
`git apply -R` the diff) on this branch makes this whole file fail at
COLLECTION (ImportError), the loudest possible "before" signal.

Run:
    cd skills/video-pipeline && python -m pytest tests/test_d12_3_board_rhythm.py -q
"""
import os
import sys

_PIPELINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PIPELINE_ROOT)
sys.path.insert(0, os.path.join(_PIPELINE_ROOT, "storyboard"))
sys.path.append(os.path.join(_PIPELINE_ROOT, "image_prompts"))

from storyboard.coverage import (  # noqa: E402
    parse_coverage,
    build_rhythm_report,
    check_shot_size_rhythm,
    check_lens_rhythm,
    check_purpose_monotony,
    _rhythm_size_sequence,
    _rhythm_lens_sequence,
    _rhythm_purpose_sequence,
    _longest_run,
    _SHOT_SIZE_RUN_THRESHOLD,
    _LENS_RUN_THRESHOLD,
    _PURPOSE_RUN_THRESHOLD,
)

# =============================================================================
# The four prior directive eras — identical to test_d11_2_shot_dp.py's own
# SAMPLE/D9_1_ERA/D9_6_7_ERA/D11_1_ERA fixtures (never re-authored — reusing
# the SAME proven-parse fixtures keeps this file's "legacy plan" claims
# anchored to what the parser actually produces, not a guess).
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

ALL_PRIOR_ERAS = (SAMPLE, D9_1_ERA, D9_6_7_ERA, D11_1_ERA)


# =============================================================================
# Synthetic moments builder — direct dict construction (never through
# parse_coverage) so every field this chunk cares about is under precise
# test control, same "build the shape parse_coverage produces, by hand"
# approach test_d11_2_shot_dp.py's own _flat() helper uses for
# enforce_setup_variety.
# =============================================================================
def _shot(shot_type, description="placeholder.", **overrides):
    base = {
        "shot_type": shot_type, "description": description,
        "purpose_kind": None, "shot_purpose": None,
        "transition_kind": None, "continuity_bridge": None, "caused_by": None,
        "shot_archetype": None,
        "lens_mm": None, "camera_height": None, "dof": None,
    }
    base.update(overrides)
    return base


def _moments(*rows):
    """Each row is (moment_number, master_shot, [angle_shot, ...])."""
    out = []
    for row in rows:
        mn, master = row[0], row[1]
        angles = row[2] if len(row) > 2 else []
        out.append({"moment_number": mn, "master": master, "angles": angles})
    return out


# =============================================================================
# 1. Sequence helpers + _longest_run
# =============================================================================

def test_rhythm_size_sequence_excludes_insert_and_empty_shot_type():
    moments = _moments(
        (1, _shot("WS")),
        (2, _shot("MS"), [_shot("INSERT"), _shot("")]),
        (3, _shot("MS")),
    )
    seq = _rhythm_size_sequence(moments)
    assert seq == [(1, "WS"), (2, "MS"), (3, "MS")]


def test_rhythm_lens_sequence_drops_none():
    moments = _moments(
        (1, _shot("WS", lens_mm=24)),
        (2, _shot("MS"), [_shot("MCU", lens_mm=50)]),
    )
    seq = _rhythm_lens_sequence(moments)
    assert seq == [(1, 24), (2, 50)]


def test_rhythm_purpose_sequence_drops_none_and_falsy():
    moments = _moments(
        (1, _shot("WS", purpose_kind="spatial")),
        (2, _shot("MS", purpose_kind=None), [_shot("MCU", purpose_kind="emotion")]),
    )
    seq = _rhythm_purpose_sequence(moments)
    assert seq == [(1, "spatial"), (2, "emotion")]


def test_longest_run_empty_sequence_is_none():
    assert _longest_run([], "shot_type") is None


def test_longest_run_ties_keep_the_first():
    seq = [(1, "WS"), (2, "MS"), (3, "CU")]
    assert _longest_run(seq, "shot_type") == {"shot_type": "WS", "length": 1, "start_moment": 1}


def test_longest_run_finds_the_true_longest():
    seq = [(1, "WS"), (2, "MS"), (3, "MS"), (4, "MS"), (5, "CU"), (6, "CU")]
    assert _longest_run(seq, "shot_type") == {"shot_type": "MS", "length": 3, "start_moment": 2}


# =============================================================================
# 2. build_rhythm_report — rich fixture, every key checked
# =============================================================================

def test_build_rhythm_report_rich_fixture():
    moments = _moments(
        (1, _shot("WS", lens_mm=24, purpose_kind="spatial",
                   shot_archetype="establishing_wide", transition_kind="opening")),
        (2, _shot("MS", lens_mm=50, purpose_kind="emotion",
                   shot_archetype="close", transition_kind="continuous"),
         [_shot("MS", lens_mm=50, purpose_kind="emotion", transition_kind="continuous"),
          _shot("MS", lens_mm=50, purpose_kind="emotion", transition_kind="continuous")]),
        (3, _shot("CU", lens_mm=85, purpose_kind="action", transition_kind="time_cut")),
    )
    report = build_rhythm_report(moments)

    assert report["shot_type_counts"] == {"WS": 1, "MS": 3, "CU": 1}
    assert report["longest_size_run"] == {"shot_type": "MS", "length": 3, "start_moment": 2}
    assert report["longest_lens_run"] == {"lens_mm": 50, "length": 3, "start_moment": 2}
    assert report["longest_purpose_run"] == {"purpose_kind": "emotion", "length": 3,
                                              "start_moment": 2}
    assert report["archetype_diversity"] == {"distinct": 2, "total": 2}
    assert report["transition_mix"] == {"opening": 1, "continuous": 3, "time_cut": 1}


def test_build_rhythm_report_insert_counted_in_shot_type_counts_not_size_run():
    """shot_type_counts is a genuine tally (INSERT included); longest_size_run
    is the INSERT-excluded rhythm reading — the two must not agree here by
    construction, proving they really are computed differently."""
    moments = _moments(
        (1, _shot("MS")),
        (2, _shot("MS"), [_shot("INSERT"), _shot("INSERT")]),
        (3, _shot("MS")),
    )
    report = build_rhythm_report(moments)
    assert report["shot_type_counts"] == {"MS": 3, "INSERT": 2}
    # INSERT shots excluded entirely -> MS, MS, MS is one unbroken run of 3.
    assert report["longest_size_run"] == {"shot_type": "MS", "length": 3, "start_moment": 1}


def test_build_rhythm_report_empty_moments_list():
    report = build_rhythm_report([])
    assert report["shot_type_counts"] == {}
    assert report["longest_size_run"] is None
    assert report["longest_lens_run"] is None
    assert report["longest_purpose_run"] is None
    assert report["archetype_diversity"] == {"distinct": 0, "total": 0}
    assert report["transition_mix"] == {}


# =============================================================================
# 3. build_rhythm_report over the four prior directive eras — tolerant of
#    every D9-1/D9-6/D11-1/D11-2 field being absent.
# =============================================================================

def test_build_rhythm_report_legacy_sample_era():
    """Zero metadata rows of any kind (predates D9-1) — but shot_type itself
    predates ALL of them, so longest_size_run is NOT None (every run here is
    length 1: WS, MCU, ELS, OTS are all different — INSERT excluded)."""
    moments = parse_coverage(SAMPLE)
    report = build_rhythm_report(moments)
    assert report["shot_type_counts"] == {"WS": 1, "MCU": 1, "INSERT": 1, "ELS": 1, "OTS": 1}
    assert report["longest_size_run"] == {"shot_type": "WS", "length": 1, "start_moment": 1}
    assert report["longest_lens_run"] is None
    assert report["longest_purpose_run"] is None
    assert report["archetype_diversity"] == {"distinct": 0, "total": 0}
    assert report["transition_mix"] == {}


def test_build_rhythm_report_all_four_eras_never_crash():
    for directive in ALL_PRIOR_ERAS:
        moments = parse_coverage(directive)
        report = build_rhythm_report(moments)
        assert report["longest_lens_run"] is None  # D11-2 predates all four eras
        assert isinstance(report["shot_type_counts"], dict) and report["shot_type_counts"]


# =============================================================================
# 4. check_shot_size_rhythm
# =============================================================================

def test_check_shot_size_rhythm_silent_under_threshold():
    moments = _moments((1, _shot("WS")), (2, _shot("MS")), (3, _shot("MS")))
    assert check_shot_size_rhythm(moments) == 0


def test_check_shot_size_rhythm_fires_on_planted_run():
    # 4 consecutive MS (non-INSERT) -> threshold 2 -> fires 4-2=2 warnings.
    moments = _moments(
        (1, _shot("MS")), (2, _shot("MS")), (3, _shot("MS")), (4, _shot("MS")),
    )
    assert check_shot_size_rhythm(moments) == 4 - _SHOT_SIZE_RUN_THRESHOLD


def test_check_shot_size_rhythm_insert_excluded_from_run_entirely():
    """MS, MS, INSERT, MS -> the INSERT is dropped from the sequence, so the
    run reads MS, MS, MS (length 3) -> ONE warning, exactly as if the
    INSERT had never been drawn at all (rather than the INSERT breaking the
    run into two harmless length-2 pieces, which is what would happen if it
    were merely SKIPPED IN PLACE instead of excluded from the sequence)."""
    moments = _moments(
        (1, _shot("MS")),
        (2, _shot("MS"), [_shot("INSERT")]),
        (3, _shot("MS")),
    )
    assert check_shot_size_rhythm(moments) == 1


def test_check_shot_size_rhythm_reaction_not_exempt():
    """A REACTION-tagged shot still carries a real shot_type (CU here) and is
    NOT excluded — 3 consecutive CU (one tagged REACTION) still fires,
    mirroring how _carries_facing_law actively INCLUDES REACTION rather than
    exempting it (only INSERT is exempted anywhere in this module)."""
    moments = _moments(
        (1, _shot("CU")),
        (2, _shot("CU", description="(SETUP B)(REACTION) reaction shot.")),
        (3, _shot("CU")),
    )
    assert check_shot_size_rhythm(moments) == 1


def test_check_shot_size_rhythm_silent_on_all_four_prior_eras():
    for directive in ALL_PRIOR_ERAS:
        moments = parse_coverage(directive)
        assert check_shot_size_rhythm(moments) == 0


# =============================================================================
# 5. check_lens_rhythm
# =============================================================================

def test_check_lens_rhythm_silent_when_no_lens_data():
    moments = _moments((1, _shot("WS")), (2, _shot("MS")), (3, _shot("CU")))
    assert check_lens_rhythm(moments) == 0


def test_check_lens_rhythm_fires_on_planted_run():
    # 5 consecutive 50mm -> threshold 3 -> fires 5-3=2 warnings.
    moments = _moments(
        (1, _shot("WS", lens_mm=50)), (2, _shot("MS", lens_mm=50)),
        (3, _shot("MS", lens_mm=50)), (4, _shot("MS", lens_mm=50)),
        (5, _shot("MS", lens_mm=50)),
    )
    assert check_lens_rhythm(moments) == 5 - _LENS_RUN_THRESHOLD


def test_check_lens_rhythm_run_broken_by_a_different_lens():
    moments = _moments(
        (1, _shot("WS", lens_mm=50)), (2, _shot("MS", lens_mm=50)),
        (3, _shot("MS", lens_mm=50)), (4, _shot("MS", lens_mm=24)),
        (5, _shot("MS", lens_mm=50)),
    )
    assert check_lens_rhythm(moments) == 0


def test_check_lens_rhythm_run_not_broken_by_an_absent_lens_shot():
    """A shot with NO lens_mm is dropped from the sequence entirely — it
    neither breaks nor extends a neighboring run, same discipline as INSERT
    in the shot-size dimension."""
    moments = _moments(
        (1, _shot("WS", lens_mm=50)), (2, _shot("MS", lens_mm=50)),
        (3, _shot("MS", lens_mm=None)),   # absent — dropped, not a break
        (4, _shot("MS", lens_mm=50)), (5, _shot("MS", lens_mm=50)),
    )
    # Effective sequence: 50, 50, 50, 50 -> run of 4 -> fires 4-3=1.
    assert check_lens_rhythm(moments) == 1


def test_check_lens_rhythm_silent_on_all_four_prior_eras():
    for directive in ALL_PRIOR_ERAS:
        moments = parse_coverage(directive)
        assert check_lens_rhythm(moments) == 0


# =============================================================================
# 6. check_purpose_monotony
# =============================================================================

def test_check_purpose_monotony_silent_when_no_purpose_data():
    moments = _moments((1, _shot("WS")), (2, _shot("MS")), (3, _shot("CU")))
    assert check_purpose_monotony(moments) == 0


def test_check_purpose_monotony_fires_on_planted_run():
    # 5 consecutive "emotion" -> threshold 3 -> fires 5-3=2 warnings.
    moments = _moments(
        (1, _shot("WS", purpose_kind="emotion")), (2, _shot("MS", purpose_kind="emotion")),
        (3, _shot("MS", purpose_kind="emotion")), (4, _shot("MS", purpose_kind="emotion")),
        (5, _shot("MS", purpose_kind="emotion")),
    )
    assert check_purpose_monotony(moments) == 5 - _PURPOSE_RUN_THRESHOLD


def test_check_purpose_monotony_run_broken_by_a_different_purpose():
    moments = _moments(
        (1, _shot("WS", purpose_kind="emotion")), (2, _shot("MS", purpose_kind="emotion")),
        (3, _shot("MS", purpose_kind="emotion")), (4, _shot("MS", purpose_kind="spatial")),
        (5, _shot("MS", purpose_kind="emotion")),
    )
    assert check_purpose_monotony(moments) == 0


def test_check_purpose_monotony_silent_on_all_four_prior_eras():
    for directive in ALL_PRIOR_ERAS:
        moments = parse_coverage(directive)
        assert check_purpose_monotony(moments) == 0


if __name__ == "__main__":
    test_rhythm_size_sequence_excludes_insert_and_empty_shot_type()
    test_rhythm_lens_sequence_drops_none()
    test_rhythm_purpose_sequence_drops_none_and_falsy()
    test_longest_run_empty_sequence_is_none()
    test_longest_run_ties_keep_the_first()
    test_longest_run_finds_the_true_longest()
    test_build_rhythm_report_rich_fixture()
    test_build_rhythm_report_insert_counted_in_shot_type_counts_not_size_run()
    test_build_rhythm_report_empty_moments_list()
    test_build_rhythm_report_legacy_sample_era()
    test_build_rhythm_report_all_four_eras_never_crash()
    test_check_shot_size_rhythm_silent_under_threshold()
    test_check_shot_size_rhythm_fires_on_planted_run()
    test_check_shot_size_rhythm_insert_excluded_from_run_entirely()
    test_check_shot_size_rhythm_reaction_not_exempt()
    test_check_shot_size_rhythm_silent_on_all_four_prior_eras()
    test_check_lens_rhythm_silent_when_no_lens_data()
    test_check_lens_rhythm_fires_on_planted_run()
    test_check_lens_rhythm_run_broken_by_a_different_lens()
    test_check_lens_rhythm_run_not_broken_by_an_absent_lens_shot()
    test_check_lens_rhythm_silent_on_all_four_prior_eras()
    test_check_purpose_monotony_silent_when_no_purpose_data()
    test_check_purpose_monotony_fires_on_planted_run()
    test_check_purpose_monotony_run_broken_by_a_different_purpose()
    test_check_purpose_monotony_silent_on_all_four_prior_eras()
    print("ok — D12-3 board rhythm report tests passed")
