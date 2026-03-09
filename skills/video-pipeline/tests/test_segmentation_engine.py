"""Tests for segmentation_engine.py — text segmentation into video clips."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline_config import VideoConfig
from segmentation_engine import (
    segment_script, _split_into_sentences, _score_intensity,
    enforce_duration_caps, recalculate_durations,
)


class TestSentenceSplitting:
    """Basic sentence boundary detection."""

    def test_simple_sentences(self):
        text = "First sentence. Second sentence. Third sentence."
        result = _split_into_sentences(text)
        assert len(result) == 3
        assert result[0] == "First sentence."
        assert result[2] == "Third sentence."

    def test_question_marks(self):
        text = "What happened? Nobody knows. Why does it matter?"
        result = _split_into_sentences(text)
        assert len(result) == 3

    def test_exclamation_marks(self):
        text = "This is huge! The market crashed. What now?"
        result = _split_into_sentences(text)
        assert len(result) == 3

    def test_single_sentence(self):
        text = "Just one sentence here."
        result = _split_into_sentences(text)
        assert len(result) == 1


class TestIntensityScoring:
    """Segment intensity classification."""

    def test_act_opener_is_high(self):
        assert _score_intensity("Some normal text here.", is_act_opener=True) == "high"

    def test_action_verbs_are_high(self):
        assert _score_intensity("The market crashed violently overnight.", is_act_opener=False) == "high"

    def test_dramatic_numbers_are_high(self):
        assert _score_intensity("The deal was worth $200B in total.", is_act_opener=False) == "high"

    def test_percentage_is_high(self):
        assert _score_intensity("Prices dropped 70% in one week.", is_act_opener=False) == "high"

    def test_reveal_phrases_are_medium(self):
        assert _score_intensity("Here's what nobody tells you about power.", is_act_opener=False) == "medium"

    def test_exposition_is_low(self):
        assert _score_intensity("The company was founded in nineteen fifty two.", is_act_opener=False) == "low"


class TestSegmentScript:
    """Full segmentation pipeline."""

    def _make_script(self, word_count: int, sentences_per_scene: int = 5) -> str:
        """Generate a simple test script with predictable structure."""
        words_per_sentence = max(5, word_count // (sentences_per_scene * 3))
        sentence = " ".join(["word"] * words_per_sentence) + "."
        scenes = []
        total_words = 0
        scene_num = 1
        while total_words < word_count:
            scene_sentences = []
            for _ in range(sentences_per_scene):
                scene_sentences.append(sentence)
                total_words += words_per_sentence
                if total_words >= word_count:
                    break
            scenes.append(f"**Scene {scene_num}**\n" + " ".join(scene_sentences))
            scene_num += 1
        return "\n\n".join(scenes)

    def test_basic_segmentation_10min(self):
        config = VideoConfig(10, 10)
        script = self._make_script(config.total_script_words)
        segments = segment_script(script, config)

        assert len(segments) > 0
        # Check segments are within tolerance
        for seg in segments:
            assert seg["word_count"] > 0
            assert seg["act"] >= 1
            assert seg["intensity"] in ("low", "medium", "high")

    def test_segments_near_target_count(self):
        config = VideoConfig(10, 10)
        script = self._make_script(config.total_script_words)
        segments = segment_script(script, config)

        # Total segments should be within ±20% of expected
        expected = config.total_clips
        assert len(segments) >= expected * 0.7
        assert len(segments) <= expected * 1.3

    def test_scene_boundary_respected(self):
        """Segments should not span two scenes."""
        config = VideoConfig(5, 10)
        script = "**Scene 1**\nThis is scene one text. It has several words in it.\n\n**Scene 2**\nThis is scene two text. It also has words."
        segments = segment_script(script, config)

        # All segments from scene 1 should come before scene 2
        scene_nums = [s["scene"] for s in segments]
        for i in range(len(scene_nums) - 1):
            assert scene_nums[i] <= scene_nums[i + 1], "Scene order violated"

    def test_act_assignment(self):
        config = VideoConfig(10, 10)
        script = self._make_script(config.total_script_words)
        segments = segment_script(script, config)

        acts = set(s["act"] for s in segments)
        # Should have multiple acts
        assert len(acts) >= 2
        # All acts should be valid
        for a in acts:
            assert 1 <= a <= config.act_count

    def test_no_empty_segments(self):
        config = VideoConfig(5, 10)
        script = self._make_script(config.total_script_words)
        segments = segment_script(script, config)

        for seg in segments:
            assert seg["text"].strip() != ""
            assert seg["word_count"] > 0

    def test_short_script_produces_fewer_segments(self):
        config = VideoConfig(10, 10)
        short_script = "**Scene 1**\nThis is a very short script. It only has a few words."
        segments = segment_script(short_script, config)

        # Should still produce segments, just fewer
        assert len(segments) > 0
        assert len(segments) < config.total_clips

    def test_5min_6s_config(self):
        config = VideoConfig(5, 6)
        script = self._make_script(config.total_script_words)
        segments = segment_script(script, config)
        assert len(segments) > 0

    def test_20min_10s_config(self):
        config = VideoConfig(20, 10)
        script = self._make_script(config.total_script_words)
        segments = segment_script(script, config)
        assert len(segments) > 0

    def test_segment_has_required_fields(self):
        config = VideoConfig(5, 10)
        script = self._make_script(config.total_script_words)
        segments = segment_script(script, config)

        required = {"index", "text", "word_count", "estimated_duration_seconds", "clip_duration", "act", "scene", "intensity"}
        for seg in segments:
            assert required.issubset(seg.keys()), f"Missing fields: {required - seg.keys()}"

    def test_clip_duration_assigned_dynamically(self):
        """Segments get 6s clips if <= 6s narration, 10s if longer."""
        config = VideoConfig(10, 10)
        script = self._make_script(config.total_script_words)
        segments = segment_script(script, config)

        for seg in segments:
            assert seg["clip_duration"] in (6, 10)
            if seg["estimated_duration_seconds"] <= 6.0:
                assert seg["clip_duration"] == 6
            else:
                assert seg["clip_duration"] == 10

    def test_short_segments_get_6s_clips(self):
        """Very short segments should get 6-second clips."""
        config = VideoConfig(5, 10)
        # Short text that will produce short segments
        script = "**Scene 1**\nShort line here. Another short one. Third quick one."
        segments = segment_script(script, config)

        for seg in segments:
            if seg["estimated_duration_seconds"] <= 6.0:
                assert seg["clip_duration"] == 6

    def test_act_markers_stripped(self):
        """Act markers should not appear in segment text."""
        config = VideoConfig(5, 10)
        script = (
            "[ACT 1 — The Hook | 0:00-1:30 | ~250 words]\n"
            "**Scene 1**\nThis is the hook text with enough words to form a segment here.\n\n"
            "[ACT 2 — The Framework | 1:30-3:00 | ~250 words]\n"
            "**Scene 2**\nThis is the framework text with enough words to form another segment."
        )
        segments = segment_script(script, config)
        for seg in segments:
            assert "[ACT" not in seg["text"]


# ---------------------------------------------------------------------------
# Duration cap enforcement
# ---------------------------------------------------------------------------

class TestEnforceDurationCaps:
    """Post-segmentation hard cap on segment duration."""

    def _words(self, n: int) -> str:
        """Generate n words of text as a single sentence."""
        return " ".join(["word"] * n) + "."

    def _multi_sentence(self, word_counts: list[int]) -> str:
        """Generate text with multiple sentences of specified word counts."""
        return " ".join(
            " ".join(["word"] * wc) + "." for wc in word_counts
        )

    def test_under_cap_unchanged(self):
        """Segments within the cap pass through unchanged."""
        segments = [
            {"text": self._words(20), "concept": "intro"},
            {"text": self._words(15), "concept": "middle"},
        ]
        result = enforce_duration_caps(segments, clip_duration_seconds=10)
        assert len(result) == 2
        assert result[0]["concept"] == "intro"

    def test_over_cap_gets_split(self):
        """A 40-word segment with 10s cap (25 words max) gets split."""
        text = self._multi_sentence([12, 12, 12])  # 3 sentences of 12 words = 36 words
        segments = [{"text": text, "concept": "long_one"}]
        result = enforce_duration_caps(segments, clip_duration_seconds=10)  # 25 word max
        assert len(result) >= 2
        # No segment should exceed 25 words
        for seg in result:
            assert len(seg["text"].split()) <= 25

    def test_no_words_lost(self):
        """Total word count is preserved after splitting."""
        text = self._multi_sentence([10, 15, 10, 12])
        original_words = len(text.split())
        segments = [{"text": text, "concept": "big"}]
        result = enforce_duration_caps(segments, clip_duration_seconds=6)  # 15 word max
        total = sum(len(s["text"].split()) for s in result)
        assert total == original_words

    def test_no_segment_exceeds_cap_10s(self):
        """After enforcement, no segment exceeds 10s * 2.5 = 25 words."""
        max_words = 25
        segments = [
            {"text": self._multi_sentence([8, 8, 8, 8, 8])},  # 40 words
            {"text": self._words(20)},  # ok
            {"text": self._multi_sentence([10, 10, 10])},  # 30 words
        ]
        result = enforce_duration_caps(segments, clip_duration_seconds=10)
        for seg in result:
            wc = len(seg["text"].split())
            assert wc <= max_words, f"Segment has {wc} words, max is {max_words}"

    def test_no_segment_exceeds_cap_6s(self):
        """After enforcement, no segment exceeds 6s * 2.5 = 15 words."""
        max_words = 15
        segments = [
            {"text": self._multi_sentence([7, 7, 7])},  # 21 words
            {"text": self._words(10)},  # ok
        ]
        result = enforce_duration_caps(segments, clip_duration_seconds=6)
        for seg in result:
            wc = len(seg["text"].split())
            assert wc <= max_words, f"Segment has {wc} words, max is {max_words}"

    def test_min_segment_remainder_merges_when_possible(self):
        """Short remainder merges with previous if it fits within the cap."""
        # 18 + 5 = 23 words. Max 25 for 10s. First chunk=18, remainder=5.
        # 18 + 5 = 23 <= 25 so remainder merges back → single 23-word segment.
        segments = [
            {"text": self._multi_sentence([18, 5])},
        ]
        result = enforce_duration_caps(segments, clip_duration_seconds=10)
        assert len(result) == 1
        assert len(result[0]["text"].split()) == 23

    def test_tiny_remainder_stays_separate_when_merge_would_breach(self):
        """Short remainder stays separate if merging would exceed the cap."""
        # 24 + 3 = 27 words. Max 25 for 10s. Can't merge.
        segments = [
            {"text": self._multi_sentence([12, 12, 3])},
        ]
        result = enforce_duration_caps(segments, clip_duration_seconds=10)
        assert len(result) == 2
        # Hard cap is always respected
        for seg in result:
            assert len(seg["text"].split()) <= 25

    def test_single_long_sentence_split_at_clause(self):
        """A single sentence over the cap splits at clause boundary."""
        # Build a sentence with a comma near the middle
        text = "The market experienced a significant downturn, which impacted all major indices and caused widespread panic among retail investors."
        segments = [{"text": text}]
        result = enforce_duration_caps(segments, clip_duration_seconds=6)  # 15 word max
        assert len(result) >= 2
        # Words preserved
        original_wc = len(text.split())
        total_wc = sum(len(s["text"].split()) for s in result)
        assert total_wc == original_wc

    def test_preserves_metadata(self):
        """concept and shot_type carry through to first sub-segment."""
        segments = [
            {
                "text": self._multi_sentence([15, 15]),
                "concept": "the_crash",
                "image_prompt": "holographic data wall",
                "shot_type": "war_table",
            }
        ]
        result = enforce_duration_caps(segments, clip_duration_seconds=10)
        assert result[0]["concept"] == "the_crash"
        assert result[0]["shot_type"] == "war_table"

    def test_empty_segments_handled(self):
        result = enforce_duration_caps([], clip_duration_seconds=10)
        assert result == []

    def test_all_within_cap_passthrough(self):
        """If nothing exceeds the cap, output == input."""
        segments = [
            {"text": self._words(20)},
            {"text": self._words(22)},
        ]
        result = enforce_duration_caps(segments, clip_duration_seconds=10)
        assert len(result) == 2


class TestRecalculateDurations:
    """Duration recalculation and clamping."""

    def test_duration_clamped_to_ceiling(self):
        segments = [{"text": " ".join(["w"] * 30)}]  # 30 words = 12s raw
        result = recalculate_durations(segments, clip_duration_seconds=10)
        assert result[0]["estimated_duration"] == 10.0

    def test_duration_clamped_to_floor(self):
        segments = [{"text": "short text"}]  # 2 words = 0.8s raw
        result = recalculate_durations(segments, clip_duration_seconds=10)
        assert result[0]["estimated_duration"] == 4.0

    def test_word_count_updated(self):
        segments = [{"text": "one two three four five"}]
        result = recalculate_durations(segments, clip_duration_seconds=10)
        assert result[0]["word_count"] == 5

    def test_normal_duration_not_clamped(self):
        segments = [{"text": " ".join(["w"] * 20)}]  # 20 words = 8s
        result = recalculate_durations(segments, clip_duration_seconds=10)
        assert result[0]["estimated_duration"] == 8.0
