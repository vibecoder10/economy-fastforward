"""C4 prop manifest — kill cross-scene prop drift.

Each approved environment gets a canonical structured prop list authored ONCE
at approval time and injected VERBATIM into every scene's planning prompt and
draw prompt — replacing the old mechanism where a fresh LLM call re-paraphrased
the location's prose every scene (the proven drift source: stove/fridge
swapped within one setup, whole kitchen swapped by shot 125 despite env refs
+ anchors).

This file covers the storyboard.bot / storyboard.coverage half:
  - render_prop_manifest: the ONE verbatim renderer every consumer shares
    (beat prompt, real draw prompt, redraw/repair prompt).
  - _format_story_bible_for_beat: injects the manifest into the planning
    prompt when present; absent -> byte-identical to before this feature.
  - apply_prop_manifest: appends the manifest to every shot's draw prompt
    (run_coverage's PICTURES-path tail-lock block); absent -> no-op.
  - check_prop_manifest_consistency: the cheap, deterministic, warning-only
    drift alarm.

The approval-time extraction, the edit-route validation, and the "sheet-
preview path is provably NOT touched" proof live in storyengine/backend/
tests/functional/test_c4_prop_manifest.py (backend-only code).

Run: cd skills/video-pipeline && python3 -m pytest tests/test_prop_manifest.py -q
"""
import os
import sys

_PIPELINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PIPELINE_ROOT)
sys.path.insert(0, os.path.join(_PIPELINE_ROOT, "storyboard"))
sys.path.append(os.path.join(_PIPELINE_ROOT, "image_prompts"))

from storyboard.bot import render_prop_manifest, _format_story_bible_for_beat  # noqa: E402
from storyboard.coverage import (  # noqa: E402
    apply_prop_manifest, check_prop_manifest_consistency,
)

SAMPLE_PROPS = [
    {"name": "red kettle", "position": "on the rear left burner"},
    {"name": "wooden spoon", "position": "in the ceramic utensil jar by the stove"},
]


# =============================================================================
# render_prop_manifest — the shared verbatim renderer
# =============================================================================

class TestRenderPropManifest:
    def test_none_and_empty_render_blank(self):
        assert render_prop_manifest(None) == ""
        assert render_prop_manifest([]) == ""

    def test_renders_verbatim_enumerated_list(self):
        text = render_prop_manifest(SAMPLE_PROPS)
        assert text.startswith("The ONLY movable props in this environment are: ")
        assert "1. red kettle — on the rear left burner" in text
        assert "2. wooden spoon — in the ceramic utensil jar by the stove" in text
        assert text.endswith("Do not add, remove, or substitute any prop.")

    def test_prop_without_position_omits_the_dash(self):
        text = render_prop_manifest([{"name": "toaster", "position": ""}])
        assert "1. toaster" in text
        assert "1. toaster —" not in text

    def test_blank_name_entries_are_skipped_not_numbered(self):
        text = render_prop_manifest([{"name": "  ", "position": "x"}, {"name": "mug", "position": "on the counter"}])
        # the blank-name entry is dropped, so the surviving prop is numbered 1, not 2
        assert "1. mug — on the counter" in text

    def test_bare_string_entries_are_tolerated(self):
        text = render_prop_manifest(["cast iron pan"])
        assert "1. cast iron pan" in text

    def test_deterministic(self):
        assert render_prop_manifest(SAMPLE_PROPS) == render_prop_manifest(SAMPLE_PROPS)


# =============================================================================
# _format_story_bible_for_beat — the planning-prompt injection point
# =============================================================================

def _bible(locations):
    return {"characters": [], "locations": locations}


class TestBeatPromptInjection:
    def test_absent_props_is_byte_identical_to_before_the_feature(self):
        """No `props` key on the location at all (every location dict in
        production before this migration) must render exactly like today."""
        bible = _bible([
            {"id": "kitchen", "description": "A sunlit kitchen.", "lighting": "warm morning",
             "type": "interior", "scenes_present": []},
        ])
        out = _format_story_bible_for_beat(bible, [1])
        assert "movable props" not in out.lower()
        assert "KITCHEN:" in out
        assert "A sunlit kitchen." in out

    def test_empty_props_list_is_also_a_no_op(self):
        bible = _bible([
            {"id": "kitchen", "description": "A sunlit kitchen.", "scenes_present": [], "props": []},
        ])
        out = _format_story_bible_for_beat(bible, [1])
        assert "movable props" not in out.lower()

    def test_props_present_renders_the_manifest_verbatim(self):
        bible = _bible([
            {"id": "kitchen", "description": "A sunlit kitchen.", "scenes_present": [], "props": SAMPLE_PROPS},
        ])
        out = _format_story_bible_for_beat(bible, [1])
        assert render_prop_manifest(SAMPLE_PROPS) in out
        # still keeps the original prose description alongside the manifest —
        # the manifest supplements, it doesn't replace the location's prose
        assert "A sunlit kitchen." in out

    def test_props_filtered_by_scenes_present_like_every_other_location_field(self):
        """A location scoped to scenes NOT in this beat is skipped entirely
        (existing behavior) — its manifest must not leak in either."""
        bible = _bible([
            {"id": "garage", "description": "A cluttered garage.", "scenes_present": [7],
             "props": SAMPLE_PROPS},
        ])
        out = _format_story_bible_for_beat(bible, [1])
        assert "GARAGE" not in out
        assert "red kettle" not in out


# =============================================================================
# apply_prop_manifest — the real draw-prompt tail (run_coverage, PICTURES path)
# =============================================================================

def _moment(n, description, angle_descriptions=None):
    return {
        "moment_number": n,
        "summary": f"moment {n}",
        "master": {"shot_type": "MS", "description": description},
        "angles": [{"shot_type": "CU", "description": d} for d in (angle_descriptions or [])],
    }


class TestApplyPropManifest:
    def test_props_absent_is_a_true_no_op(self):
        moments = [_moment(1, "Wide shot of the kitchen.", ["Close on the stove."])]
        before = [m["master"]["description"] for m in moments] + \
                 [a["description"] for m in moments for a in m["angles"]]
        n = apply_prop_manifest(moments, None)
        after = [m["master"]["description"] for m in moments] + \
                [a["description"] for m in moments for a in m["angles"]]
        assert n == 0
        assert before == after

    def test_empty_list_is_also_a_no_op(self):
        moments = [_moment(1, "Wide shot of the kitchen.")]
        n = apply_prop_manifest(moments, [])
        assert n == 0
        assert moments[0]["master"]["description"] == "Wide shot of the kitchen."

    def test_props_present_appends_manifest_to_every_shot_master_and_angle(self):
        moments = [
            _moment(1, "Wide shot of the kitchen.", ["Close on the stove."]),
            _moment(2, "Medium shot at the counter.", ["Insert of hands.", "Reaction shot."]),
        ]
        manifest = render_prop_manifest(SAMPLE_PROPS)
        n = apply_prop_manifest(moments, SAMPLE_PROPS)
        assert n == 5  # 2 masters + 3 angles
        for m in moments:
            assert m["master"]["description"].endswith(manifest)
            assert m["master"]["description"].startswith("Wide shot" if m["moment_number"] == 1
                                                           else "Medium shot")
            for a in m["angles"]:
                assert a["description"].endswith(manifest)


# =============================================================================
# check_prop_manifest_consistency — the cheap, deterministic drift alarm
# =============================================================================

class TestCheckPropManifestConsistency:
    def test_no_props_or_no_set_line_is_a_silent_no_op(self):
        assert check_prop_manifest_consistency(None, "kitchen counter") == 0
        assert check_prop_manifest_consistency(SAMPLE_PROPS, None) == 0
        assert check_prop_manifest_consistency(SAMPLE_PROPS, "") == 0

    def test_every_manifest_prop_echoed_in_set_line_warns_zero(self):
        set_line = "the counter holds a red kettle and a wooden spoon by the stove"
        assert check_prop_manifest_consistency(SAMPLE_PROPS, set_line) == 0

    def test_contradiction_fixture_warns_for_each_missing_prop(self):
        """The planner's own [SET|] line never mentions the manifest's props —
        the cheap direction this gate checks (not fuzzy prop-invention
        detection in arbitrary shot prose)."""
        set_line = "a kitchen counter with a blue teapot and a cutting board"
        assert check_prop_manifest_consistency(SAMPLE_PROPS, set_line) == 2

    def test_case_and_punctuation_insensitive_match(self):
        set_line = "RED KETTLE! sits near a Wooden-Spoon on the counter."
        assert check_prop_manifest_consistency(SAMPLE_PROPS, set_line) == 0


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
