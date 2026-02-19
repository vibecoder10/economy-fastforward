"""Tests for scene description diversity and per-scene description generation."""

import sys
import os
import asyncio

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from brief_translator.scene_expander import (
    check_scene_diversity,
    _plan_batches,
    _generate_description_for_scene,
    _generate_all_descriptions,
    _fallback_description,
    BATCH_SIZE,
)


def _scene(desc: str, **kwargs) -> dict:
    base = {"description": desc, "scene_description": desc}
    base.update(kwargs)
    return base


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


# ---------------------------------------------------------------------------
# Per-scene description generation tests
# ---------------------------------------------------------------------------


class FakeAnthropicClient:
    """Mock client that returns a predictable description based on call count."""

    def __init__(self, responses=None, fail_on=None):
        self.calls = []
        self._responses = responses or []
        self._call_count = 0
        self._fail_on = set(fail_on or [])

    async def generate(self, prompt, model, max_tokens, temperature):
        self.calls.append({
            "prompt": prompt,
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
        })
        if self._call_count in self._fail_on:
            self._call_count += 1
            raise RuntimeError("Simulated API failure")
        if self._responses:
            resp = self._responses[self._call_count % len(self._responses)]
        else:
            resp = f"Unique scene description number {self._call_count + 1}"
        self._call_count += 1
        return resp


class TestGenerateDescriptionForScene:
    def test_prompt_contains_narration(self):
        """The per-scene prompt includes the scene's narration text."""
        client = FakeAnthropicClient()
        scene = _scene(
            "",
            narration_text="The Federal Reserve announced rate cuts today.",
            act=2, style="dossier", composition="medium",
        )
        result = asyncio.get_event_loop().run_until_complete(
            _generate_description_for_scene(client, scene, [])
        )
        assert "Federal Reserve announced rate cuts" in client.calls[0]["prompt"]
        assert result  # Got a non-empty description

    def test_prompt_includes_previous_descriptions(self):
        """Previous descriptions are included as DO NOT REPEAT context."""
        client = FakeAnthropicClient()
        scene = _scene(
            "",
            narration_text="Markets reacted sharply.",
            act=3, style="schema", composition="wide",
        )
        prev = [
            "A central bank building at dawn",
            "Traders watching screens on a dark floor",
            "An empty factory with idle machinery",
        ]
        asyncio.get_event_loop().run_until_complete(
            _generate_description_for_scene(client, scene, prev)
        )
        prompt = client.calls[0]["prompt"]
        assert "DO NOT repeat" in prompt
        for desc in prev:
            assert desc in prompt

    def test_prompt_with_no_previous_descriptions(self):
        """First scene has no previous context — no DO NOT REPEAT section."""
        client = FakeAnthropicClient()
        scene = _scene(
            "",
            narration_text="Opening line of the documentary.",
            act=1, style="dossier", composition="wide",
        )
        asyncio.get_event_loop().run_until_complete(
            _generate_description_for_scene(client, scene, [])
        )
        prompt = client.calls[0]["prompt"]
        assert "DO NOT repeat" not in prompt

    def test_strips_quotes_from_response(self):
        """Surrounding quotes in LLM response are stripped."""
        client = FakeAnthropicClient(
            responses=['"A lone figure standing in a vast empty warehouse"']
        )
        scene = _scene("", narration_text="Test.", act=1, style="dossier", composition="wide")
        result = asyncio.get_event_loop().run_until_complete(
            _generate_description_for_scene(client, scene, [])
        )
        assert not result.startswith('"')
        assert not result.endswith('"')


class TestGenerateAllDescriptions:
    def test_all_scenes_get_unique_descriptions(self):
        """Each scene gets a distinct description overwriting the original."""
        client = FakeAnthropicClient()
        scenes = [
            _scene("placeholder", narration_text=f"Sentence {i}.", act=1, style="dossier", composition="wide")
            for i in range(5)
        ]
        result = asyncio.get_event_loop().run_until_complete(
            _generate_all_descriptions(client, scenes)
        )
        descs = [s["description"] for s in result]
        # All descriptions should be unique (FakeAnthropicClient returns numbered descriptions)
        assert len(set(descs)) == 5
        # None should be the placeholder
        assert "placeholder" not in descs

    def test_rolling_context_window(self):
        """Each call receives up to 3 previous descriptions as context."""
        client = FakeAnthropicClient()
        scenes = [
            _scene("", narration_text=f"Line {i}.", act=1, style="dossier", composition="wide")
            for i in range(5)
        ]
        asyncio.get_event_loop().run_until_complete(
            _generate_all_descriptions(client, scenes)
        )
        # First call: no previous context
        assert "DO NOT repeat" not in client.calls[0]["prompt"]
        # Second call: 1 previous
        assert "Unique scene description number 1" in client.calls[1]["prompt"]
        # Fourth call: should have 3 previous
        assert "Unique scene description number 1" in client.calls[3]["prompt"]
        assert "Unique scene description number 2" in client.calls[3]["prompt"]
        assert "Unique scene description number 3" in client.calls[3]["prompt"]
        # Fifth call: rolling window — should NOT have description 1 (only 2, 3, 4)
        assert "Unique scene description number 1" not in client.calls[4]["prompt"]
        assert "Unique scene description number 2" in client.calls[4]["prompt"]

    def test_makes_one_call_per_scene(self):
        """Exactly one LLM call is made per scene."""
        client = FakeAnthropicClient()
        scenes = [
            _scene("", narration_text=f"Line {i}.", act=1, style="dossier", composition="wide")
            for i in range(7)
        ]
        asyncio.get_event_loop().run_until_complete(
            _generate_all_descriptions(client, scenes)
        )
        assert len(client.calls) == 7

    def test_empty_scene_list(self):
        """Empty input returns empty output without any LLM calls."""
        client = FakeAnthropicClient()
        result = asyncio.get_event_loop().run_until_complete(
            _generate_all_descriptions(client, [])
        )
        assert result == []
        assert len(client.calls) == 0

    def test_backward_compat_fields_updated(self):
        """Both 'description' and 'scene_description' are set."""
        client = FakeAnthropicClient()
        scenes = [_scene("old", narration_text="Test.", act=1, style="dossier", composition="wide")]
        result = asyncio.get_event_loop().run_until_complete(
            _generate_all_descriptions(client, scenes)
        )
        assert result[0]["description"] == result[0]["scene_description"]
        assert result[0]["description"] != "old"


# ---------------------------------------------------------------------------
# Fallback and error handling tests
# ---------------------------------------------------------------------------


class TestFallbackDescription:
    def test_extracts_key_words(self):
        """Fallback strips filler and builds a description from content words."""
        result = _fallback_description(
            "The Federal Reserve announced sweeping rate cuts today."
        )
        assert "Federal" in result
        assert "Reserve" in result
        assert "rate" in result
        # Filler should be stripped
        assert result.startswith("A scene depicting")

    def test_short_narration(self):
        """Fallback handles very short narration gracefully."""
        result = _fallback_description("Factories closed.")
        assert "Factories" in result
        assert "closed" in result

    def test_empty_narration(self):
        """Fallback handles empty narration without crashing."""
        result = _fallback_description("")
        assert result.startswith("A scene depicting")


class TestErrorHandling:
    def test_api_failure_uses_fallback(self):
        """When the LLM call raises, a fallback description is returned."""
        client = FakeAnthropicClient(fail_on={0})
        scene = _scene(
            "",
            narration_text="The economy contracts sharply in Q4.",
            act=2, style="dossier", composition="wide",
        )
        result = asyncio.get_event_loop().run_until_complete(
            _generate_description_for_scene(client, scene, [])
        )
        # Should get a fallback, not crash
        assert result
        assert "scene depicting" in result.lower()

    def test_mid_sequence_failure_continues(self):
        """A failure mid-sequence falls back and continues processing."""
        # Fail on 3rd call (index 2), succeed on everything else
        client = FakeAnthropicClient(fail_on={2})
        scenes = [
            _scene("", narration_text=f"The topic number {i} is discussed.", act=1, style="dossier", composition="wide")
            for i in range(5)
        ]
        result = asyncio.get_event_loop().run_until_complete(
            _generate_all_descriptions(client, scenes)
        )
        # All 5 scenes should have descriptions (no crash)
        assert len(result) == 5
        for s in result:
            assert s["description"]
            assert s["scene_description"]
        # Scene 3 (index 2) should have a fallback description
        assert "scene depicting" in result[2]["description"].lower()
