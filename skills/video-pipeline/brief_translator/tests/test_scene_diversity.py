"""Tests for scene description diversity checking."""

import sys
import os

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from brief_translator.scene_expander import check_scene_diversity


def _scene(desc: str) -> dict:
    return {"description": desc, "scene_description": desc}


class TestCheckSceneDiversity:
    def test_no_duplicates_returns_empty(self):
        scenes = [
            _scene("A lone figure in a dark suit standing at the end of a corridor"),
            _scene("Close-up of hands placing a black king chess piece onto a world map"),
            _scene("Dark aerial view of a sprawling city at night with glowing lights"),
        ]
        assert check_scene_diversity(scenes) == []

    def test_identical_descriptions_flagged(self):
        """Near-identical descriptions (same subject/setting) are caught."""
        scenes = [
            _scene("A conference stage with a speaker at a podium presenting optimistic graphs"),
            _scene("A conference stage with a speaker at a podium showing robot imagery"),
            _scene("A conference stage with a speaker at a podium audience silhouetted"),
        ]
        flagged = check_scene_diversity(scenes)
        assert len(flagged) >= 1

    def test_high_overlap_flagged(self):
        """Two consecutive scenes sharing >60% of first 8 words should be flagged."""
        scenes = [
            _scene("A conference stage with a speaker at a podium presenting data"),
            _scene("A conference stage with a speaker at a podium showing charts"),
        ]
        assert 1 in check_scene_diversity(scenes)

    def test_low_overlap_not_flagged(self):
        """Two completely different descriptions should not be flagged."""
        scenes = [
            _scene("A 19th century textile mill with children operating mechanical looms"),
            _scene("A boarded-up storefront on an empty main street with foreclosure sign"),
        ]
        assert check_scene_diversity(scenes) == []

    def test_short_descriptions_skipped(self):
        """Descriptions shorter than 6 words should not be compared."""
        scenes = [
            _scene("A building"),
            _scene("A building"),
        ]
        # Too short to reliably compare
        assert check_scene_diversity(scenes) == []

    def test_single_scene_returns_empty(self):
        assert check_scene_diversity([_scene("Any description here is fine")]) == []

    def test_empty_list_returns_empty(self):
        assert check_scene_diversity([]) == []

    def test_middle_of_run_flagged(self):
        """In a run of 4 similar scenes, indices 1-3 should be flagged."""
        scenes = [
            _scene("A conference room with executives around a large table discussing"),
            _scene("A conference room with executives around a large table reviewing"),
            _scene("A conference room with executives around a large table debating"),
            _scene("A military convoy moving through a desert highway at dawn"),
        ]
        flagged = check_scene_diversity(scenes)
        assert 1 in flagged
        assert 2 in flagged
        assert 3 not in flagged
