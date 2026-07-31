"""D12-3 (board rhythm report) — the sheet-preview SURFACE.

skills/video-pipeline/storyboard/coverage.py gained build_rhythm_report(moments)
(a pure per-scene rhythm summary — shot-size runs, lens repetition, purpose
monotony) plus three warn-only checks wired into run_coverage (proved by
tests/test_d12_3_board_rhythm.py in the pipeline suite). This file proves the
OTHER half: coverage_to_app.py's sheet-preview path (generate_storyboard_
sheet_for_scene) surfaces a few human-readable rhythm lines through its
return dict — the ONLY place that function's response shape (routes/
pipeline.py:1671-1673 reads only .get("status")/.get("message")/.get("error")
off it — see that file) has room for a new, purely additive field.

_rhythm_notes_for_scene(scene_number, moments) is the pure helper factored
out of that async DB-bound function specifically so it's testable here with a
plain moments list — no DB mocking required (same reasoning
test_d11_1_shot_archetype_stamp.py gives for exercising store_scene
directly instead of the whole pipeline).

Covers:
  1. A scene whose rhythm never crosses a threshold -> [] (so the caller
     never adds the "rhythm_notes" key at all — today's payload shape,
     byte-identical).
  2. A planted shot-size run -> one note, worded with the run's length,
     shot_type, and start_moment.
  3. A planted lens run and a planted purpose run -> their own notes,
     independently.
  4. All three planted at once on the SAME scene -> three notes, same order
     build_rhythm_report's own keys are documented in (size, lens, purpose).
  5. The threshold used here is the EXACT same constant the warn checks in
     storyboard/coverage.py use (imported, not duplicated) — a run AT the
     threshold produces no note, one shot PAST it does.

Run: cd storyengine/backend && ./venv/bin/python -m pytest \
    tests/functional/test_d12_3_board_rhythm_surface.py -q
"""
import os
import sys
import types

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


async def _boom(*a, **k):
    raise AssertionError("pure tests must not touch runtime services")


_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom)
_stub("storage", upload_bytes=_boom)
_stub("vault", get_secret=_boom)
_stub("kie_unified", get_text_client_for_tenant=_boom)
_stub("actions", picture_price_for=lambda model_label=None: 0.05)

from scripts.coverage_to_app import _rhythm_notes_for_scene  # noqa: E402
from storyboard.coverage import (  # noqa: E402
    _SHOT_SIZE_RUN_THRESHOLD, _LENS_RUN_THRESHOLD, _PURPOSE_RUN_THRESHOLD,
)


def _shot(shot_type, **overrides):
    base = {
        "shot_type": shot_type, "description": "placeholder.",
        "purpose_kind": None, "shot_purpose": None,
        "transition_kind": None, "continuity_bridge": None, "caused_by": None,
        "shot_archetype": None,
        "lens_mm": None, "camera_height": None, "dof": None,
    }
    base.update(overrides)
    return base


def _moments(*rows):
    out = []
    for row in rows:
        mn, master = row[0], row[1]
        angles = row[2] if len(row) > 2 else []
        out.append({"moment_number": mn, "master": master, "angles": angles})
    return out


def test_no_notes_when_nothing_crosses_a_threshold():
    moments = _moments((1, _shot("WS")), (2, _shot("MS")), (3, _shot("CU")))
    assert _rhythm_notes_for_scene(1, moments) == []


def test_run_exactly_at_threshold_produces_no_note():
    """_SHOT_SIZE_RUN_THRESHOLD (2) consecutive MS shots is AT the cap, not
    past it — check_shot_size_rhythm itself would stay silent here too
    (run_len > threshold, not >=), so the note must too."""
    moments = _moments(*[(i, _shot("MS")) for i in range(1, _SHOT_SIZE_RUN_THRESHOLD + 1)])
    assert _rhythm_notes_for_scene(3, moments) == []


def test_shot_size_run_note_worded_with_length_type_and_moment():
    n = _SHOT_SIZE_RUN_THRESHOLD + 2  # comfortably past the cap
    moments = _moments(*[(i, _shot("MS")) for i in range(1, n + 1)])
    notes = _rhythm_notes_for_scene(4, moments)
    assert len(notes) == 1
    assert notes[0] == (
        f"Scene 4: {n} MS shots in a row starting moment 1 — worth a glance for visual variety.")


def test_lens_run_note():
    # shot_type ALTERNATES (WS/MS/WS/MS/...) so the shot-size dimension never
    # crosses its own (lower) threshold — isolates the lens note.
    n = _LENS_RUN_THRESHOLD + 1
    types_cycle = ["WS", "MS"]
    moments = _moments(*[
        (i, _shot(types_cycle[i % 2], lens_mm=35)) for i in range(1, n + 1)
    ])
    notes = _rhythm_notes_for_scene(2, moments)
    assert len(notes) == 1
    assert notes[0] == (
        f"Scene 2: {n} shots in a row at 35mm starting moment 1 — worth a glance for lens "
        "variety.")


def test_purpose_run_note():
    n = _PURPOSE_RUN_THRESHOLD + 1
    types_cycle = ["WS", "MS"]
    moments = _moments(*[
        (i, _shot(types_cycle[i % 2], purpose_kind="emotion")) for i in range(1, n + 1)
    ])
    notes = _rhythm_notes_for_scene(5, moments)
    assert len(notes) == 1
    assert notes[0] == (
        f"Scene 5: {n} shots in a row with purpose 'emotion' starting moment 1 — worth a "
        "glance for narrative variety.")


def test_all_three_dimensions_note_independently_same_scene():
    n_size = _SHOT_SIZE_RUN_THRESHOLD + 1
    n_lens = _LENS_RUN_THRESHOLD + 1
    n_purpose = _PURPOSE_RUN_THRESHOLD + 1
    # Same shot_type run AND same lens run AND same purpose run, all on the
    # first n_purpose shots (the longest requirement) — every shot shares
    # shot_type "MS" and lens_mm 50 and purpose_kind "emotion" so all three
    # dimensions report their longest run starting at moment 1.
    n = max(n_size, n_lens, n_purpose)
    moments = _moments(*[
        (i, _shot("MS", lens_mm=50, purpose_kind="emotion")) for i in range(1, n + 1)
    ])
    notes = _rhythm_notes_for_scene(7, moments)
    assert len(notes) == 3
    assert "shots in a row" in notes[0] and "visual variety" in notes[0]
    assert "50mm" in notes[1] and "lens variety" in notes[1]
    assert "'emotion'" in notes[2] and "narrative variety" in notes[2]


def test_empty_moments_produces_no_notes():
    assert _rhythm_notes_for_scene(1, []) == []


if __name__ == "__main__":
    test_no_notes_when_nothing_crosses_a_threshold()
    test_run_exactly_at_threshold_produces_no_note()
    test_shot_size_run_note_worded_with_length_type_and_moment()
    test_lens_run_note()
    test_purpose_run_note()
    test_all_three_dimensions_note_independently_same_scene()
    test_empty_moments_produces_no_notes()
    print("ok — D12-3 board rhythm surface tests passed")
