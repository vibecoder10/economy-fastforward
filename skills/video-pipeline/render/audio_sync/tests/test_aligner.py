"""Tests for audio_sync.aligner — scene-to-timestamp alignment."""

import pytest

from audio_sync.aligner import (
    normalize_text,
    align_scenes_to_timestamps,
    interpolate_failed_alignments,
    validate_alignment,
)
from audio_sync.transcriber import WordTimestamp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_words(texts: list[str], start: float = 0.0, gap: float = 0.3) -> list[WordTimestamp]:
    """Build a list of WordTimestamp objects from plain text tokens."""
    words = []
    t = start
    for text in texts:
        words.append(WordTimestamp(text, round(t, 2), round(t + gap - 0.02, 2)))
        t += gap
    return words


# ---------------------------------------------------------------------------
# normalize_text
# ---------------------------------------------------------------------------

class TestNormalizeText:
    def test_lowercase(self):
        assert normalize_text("Hello World") == "hello world"

    def test_strip_punctuation(self):
        assert normalize_text("Hello, World!") == "hello world"

    def test_collapse_whitespace(self):
        assert normalize_text("  hello   world  ") == "hello world"

    def test_numbers_preserved(self):
        assert normalize_text("$1.25 trillion") == "125 trillion"

    def test_empty_string(self):
        assert normalize_text("") == ""


# ---------------------------------------------------------------------------
# align_scenes_to_timestamps
# ---------------------------------------------------------------------------

class TestAlignScenes:
    def test_exact_match(self):
        """Scenes whose excerpt exactly matches Whisper output."""
        words = _make_words(["the", "quick", "brown", "fox", "jumped", "over"])
        scenes = [
            {"scene_number": 1, "script_excerpt": "the quick brown"},
            {"scene_number": 2, "script_excerpt": "fox jumped over"},
        ]
        aligned = align_scenes_to_timestamps(scenes, words)

        assert aligned[0]["alignment_method"] == "fuzzy_match"
        assert aligned[0]["start_time"] == words[0].start
        assert aligned[0]["end_time"] == words[2].end

        assert aligned[1]["alignment_method"] == "fuzzy_match"
        assert aligned[1]["start_time"] == words[3].start
        assert aligned[1]["end_time"] == words[5].end

    def test_fuzzy_match_with_punctuation_differences(self):
        """Whisper output may differ in punctuation from the script."""
        words = _make_words(["and", "this", "is", "where", "musk", "made"])
        scenes = [
            {"scene_number": 1, "script_excerpt": "And, this is where Musk made"},
        ]
        aligned = align_scenes_to_timestamps(scenes, words)

        assert aligned[0]["alignment_method"] == "fuzzy_match"
        assert aligned[0]["alignment_score"] >= 0.6

    def test_empty_excerpt_treated_as_no_narration(self):
        words = _make_words(["hello", "world"])
        scenes = [{"scene_number": 1, "script_excerpt": ""}]
        aligned = align_scenes_to_timestamps(scenes, words)

        assert aligned[0]["alignment_method"] == "no_narration"
        assert aligned[0]["start_time"] is None

    def test_sequential_ordering_preserved(self):
        """Scene 2 can only match words AFTER scene 1's match."""
        words = _make_words(["a", "b", "c", "d", "e", "f", "g", "h"])
        scenes = [
            {"scene_number": 1, "script_excerpt": "a b c"},
            {"scene_number": 2, "script_excerpt": "e f g"},
        ]
        aligned = align_scenes_to_timestamps(scenes, words)

        assert aligned[0]["end_time"] < aligned[1]["start_time"]

    def test_failed_alignment_gets_interpolated(self):
        """A scene that can't match gets interpolated from neighbours."""
        words = _make_words(["alpha", "beta", "gamma", "delta", "epsilon"])
        scenes = [
            {"scene_number": 1, "script_excerpt": "alpha beta"},
            {"scene_number": 2, "script_excerpt": "ZZZZZ YYYYY"},  # won't match
            {"scene_number": 3, "script_excerpt": "delta epsilon"},
        ]
        aligned = align_scenes_to_timestamps(scenes, words)

        assert aligned[1]["alignment_method"] == "interpolated"
        assert aligned[1]["start_time"] is not None
        assert aligned[1]["end_time"] is not None
        # Interpolated scene should fall between scene 1 end and scene 3 start
        assert aligned[1]["start_time"] >= aligned[0]["end_time"]
        assert aligned[1]["end_time"] <= aligned[2]["start_time"]


# ---------------------------------------------------------------------------
# interpolate_failed_alignments
# ---------------------------------------------------------------------------

class TestInterpolation:
    def test_single_gap(self):
        scenes = [
            {"scene_number": 1, "start_time": 0.0, "end_time": 5.0},
            {"scene_number": 2, "start_time": None, "end_time": None},
            {"scene_number": 3, "start_time": 10.0, "end_time": 15.0},
        ]
        result = interpolate_failed_alignments(scenes)

        assert result[1]["start_time"] == 5.0
        assert result[1]["end_time"] == 10.0
        assert result[1]["alignment_method"] == "interpolated"

    def test_multiple_gaps(self):
        scenes = [
            {"scene_number": 1, "start_time": 0.0, "end_time": 4.0},
            {"scene_number": 2, "start_time": None, "end_time": None},
            {"scene_number": 3, "start_time": None, "end_time": None},
            {"scene_number": 4, "start_time": 10.0, "end_time": 14.0},
        ]
        result = interpolate_failed_alignments(scenes)

        # 6 seconds gap split into 2 x 3 seconds
        assert result[1]["start_time"] == 4.0
        assert result[1]["end_time"] == 7.0
        assert result[2]["start_time"] == 7.0
        assert result[2]["end_time"] == 10.0


# ---------------------------------------------------------------------------
# validate_alignment
# ---------------------------------------------------------------------------

class TestValidateAlignment:
    def test_clean_alignment(self):
        scenes = [
            {"scene_number": 1, "start_time": 0.0, "end_time": 5.0,
             "alignment_method": "fuzzy_match", "alignment_score": 0.95},
            {"scene_number": 2, "start_time": 5.1, "end_time": 10.0,
             "alignment_method": "fuzzy_match", "alignment_score": 0.88},
        ]
        report = validate_alignment(scenes)

        assert report["quality"] == "good"
        assert report["overlaps"] == 0
        assert report["large_gaps"] == 0
        assert report["total_scenes"] == 2

    def test_overlap_detected(self):
        scenes = [
            {"scene_number": 1, "start_time": 0.0, "end_time": 6.0,
             "alignment_method": "fuzzy_match", "alignment_score": 0.9},
            {"scene_number": 2, "start_time": 5.0, "end_time": 10.0,
             "alignment_method": "fuzzy_match", "alignment_score": 0.9},
        ]
        report = validate_alignment(scenes)

        assert report["overlaps"] == 1

    def test_large_gap_detected(self):
        scenes = [
            {"scene_number": 1, "start_time": 0.0, "end_time": 5.0,
             "alignment_method": "fuzzy_match", "alignment_score": 0.9},
            {"scene_number": 2, "start_time": 9.0, "end_time": 14.0,
             "alignment_method": "fuzzy_match", "alignment_score": 0.9},
        ]
        report = validate_alignment(scenes)

        assert report["large_gaps"] == 1
