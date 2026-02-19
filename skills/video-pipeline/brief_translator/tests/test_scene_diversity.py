"""Tests for scene description diversity checking and batch planning."""

import sys
import os

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from brief_translator.scene_expander import check_scene_diversity, _plan_batches, BATCH_SIZE


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


# ---------------------------------------------------------------------------
# _plan_batches tests
# ---------------------------------------------------------------------------

def _make_acts(word_counts: dict[int, int]) -> dict[int, str]:
    """Create act dict with specified word counts per act."""
    return {n: " ".join(["word"] * wc) for n, wc in word_counts.items()}


class TestPlanBatches:
    def test_six_equal_acts_produces_multiple_batches(self):
        """6 equal-length acts with 25 scenes should split into 3 batches."""
        acts = _make_acts({1: 500, 2: 500, 3: 500, 4: 500, 5: 500, 6: 500})
        batches = _plan_batches(acts, 25)
        assert len(batches) >= 2
        # Total target scenes across batches should equal 25
        total = sum(b["target_scenes"] for b in batches)
        assert total == 25

    def test_all_acts_covered(self):
        """Every act number appears in exactly one batch."""
        acts = _make_acts({1: 300, 2: 600, 3: 800, 4: 700, 5: 500, 6: 400})
        batches = _plan_batches(acts, 25)
        covered = []
        for b in batches:
            covered.extend(a["act_number"] for a in b["acts"])
        assert sorted(covered) == [1, 2, 3, 4, 5, 6]

    def test_per_act_scenes_clamped_3_to_5(self):
        """Each act gets 3-5 scenes regardless of word count."""
        acts = _make_acts({1: 100, 2: 2000, 3: 500, 4: 500, 5: 500, 6: 500})
        batches = _plan_batches(acts, 25)
        for b in batches:
            for a in b["acts"]:
                assert 3 <= a["target_scenes"] <= 5, (
                    f"Act {a['act_number']} got {a['target_scenes']} scenes"
                )

    def test_small_trailing_batch_merged(self):
        """A trailing batch with <4 scenes gets merged into previous."""
        # 3 acts with 4 scenes each = 12, then 3 acts with 3 each = 9
        # With BATCH_SIZE=8, after first batch (8 scenes), remaining (17-8=9)
        # should form second batch, not be split further
        acts = _make_acts({1: 500, 2: 500, 3: 500, 4: 200, 5: 200, 6: 200})
        batches = _plan_batches(acts, 25)
        for b in batches:
            # No batch should have fewer than 4 target scenes
            assert b["target_scenes"] >= 4 or len(batches) == 1

    def test_single_act_produces_one_batch(self):
        """A script with only one act produces a single batch."""
        acts = _make_acts({1: 3000})
        batches = _plan_batches(acts, 5)
        assert len(batches) == 1
        assert batches[0]["target_scenes"] >= 3

    def test_batch_target_scenes_sum(self):
        """Sum of all batch target_scenes equals total_scenes."""
        acts = _make_acts({1: 400, 2: 600, 3: 800, 4: 700, 5: 500, 6: 300})
        for total in [20, 25, 30]:
            batches = _plan_batches(acts, total)
            actual_total = sum(b["target_scenes"] for b in batches)
            assert actual_total == total, (
                f"Expected {total} total scenes, got {actual_total}"
            )

    def test_acts_in_order(self):
        """Acts appear in sequential order across batches."""
        acts = _make_acts({1: 500, 2: 500, 3: 500, 4: 500, 5: 500, 6: 500})
        batches = _plan_batches(acts, 25)
        act_order = []
        for b in batches:
            act_order.extend(a["act_number"] for a in b["acts"])
        assert act_order == sorted(act_order)
