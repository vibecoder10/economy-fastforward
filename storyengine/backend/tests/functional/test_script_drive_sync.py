"""Script <-> Google Drive sync: the scene-marker contract (the fragile bit).

Push builds a scene-delimited Doc; Pull splits it back by "### SCENE n" markers.
These tests lock the round-trip, the lenient matching, and the fail-loud behavior
so a creator's edits can never silently mis-map. Pure-function tests — no Drive,
no DB.
"""
import pytest

from routes.videos import _build_script_doc_text, _parse_script_doc


def _rows(*texts):
    return [{"scene": i, "scene_text": t} for i, t in enumerate(texts, start=1)]


def test_round_trip_preserves_scene_text():
    rows = _rows(
        "Opening hook about the layoffs.",
        "The middle builds tension.\nA second line in scene two.",
        "The payoff and call to action.",
    )
    doc = _build_script_doc_text("My Video", rows)
    parsed = _parse_script_doc(doc)
    assert set(parsed.keys()) == {1, 2, 3}
    assert parsed[1] == "Opening hook about the layoffs."
    assert parsed[2] == "The middle builds tension.\nA second line in scene two."
    assert parsed[3] == "The payoff and call to action."


def test_preamble_before_first_marker_is_ignored():
    doc = _build_script_doc_text("Title", _rows("Scene one text."))
    # The instructional header lines sit before "### SCENE 1" and must not leak
    # into scene 1's text.
    assert _parse_script_doc(doc)[1] == "Scene one text."


def test_lenient_markers_still_map():
    # Creator edits in Google Docs may drop the '###', add a title, or a ':'.
    doc = (
        "intro\n"
        "Scene 1\nfirst\n\n"
        "### SCENE 2 — The Turn\nsecond\n\n"
        "SCENE 3:\nthird\n"
    )
    parsed = _parse_script_doc(doc)
    assert parsed == {1: "first", 2: "second", 3: "third"}


def test_missing_markers_fails_loud():
    with pytest.raises(ValueError):
        _parse_script_doc("Just some prose with no scene markers at all.")


def test_null_scene_number_falls_back_to_index():
    rows = [{"scene": None, "scene_text": "a"}, {"scene": None, "scene_text": "b"}]
    doc = _build_script_doc_text("T", rows)
    parsed = _parse_script_doc(doc)
    assert parsed == {1: "a", 2: "b"}
