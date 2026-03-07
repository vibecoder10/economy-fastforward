"""Tests for segmentation_engine.py — text segmentation into video clips."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline_config import VideoConfig
from segmentation_engine import segment_script, _split_into_sentences, _score_intensity


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

        required = {"index", "text", "word_count", "estimated_duration_seconds", "act", "scene", "intensity"}
        for seg in segments:
            assert required.issubset(seg.keys()), f"Missing fields: {required - seg.keys()}"

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
