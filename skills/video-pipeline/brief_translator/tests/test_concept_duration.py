"""Tests for concept duration validation in scene_expander."""

import pytest
from brief_translator.scene_expander import (
    _validate_concept_durations,
    MIN_WORDS_PER_CONCEPT,
    MAX_WORDS_PER_CONCEPT,
)


def _make_concept(text: str, **kwargs) -> dict:
    """Helper to build a concept dict."""
    return {
        "concept_index": kwargs.get("index", 1),
        "sentence_text": text,
        "visual_description": "A scene showing something",
        "visual_style": "dossier",
        "composition": "wide",
        "mood": "tension",
        **kwargs,
    }


class TestValidateConceptDurations:
    """Test that _validate_concept_durations merges short and splits long concepts."""

    def test_concepts_within_bounds_unchanged(self):
        """Concepts with 12-25 words should pass through unchanged."""
        concepts = [
            _make_concept("word " * 15, index=1),  # 15 words
            _make_concept("word " * 20, index=2),  # 20 words
        ]
        result = _validate_concept_durations(concepts)
        assert len(result) == 2
        assert "needs_new_prompt" not in result[0]
        assert "needs_new_prompt" not in result[1]

    def test_short_concept_merged_with_next(self):
        """A concept under MIN_WORDS should be merged with its neighbor."""
        concepts = [
            _make_concept("short text here", index=1),        # 3 words — too short
            _make_concept("word " * 15, index=2),             # 15 words — ok
            _make_concept("word " * 18, index=3),             # 18 words — ok
        ]
        result = _validate_concept_durations(concepts)
        # First two merged into one, third stays
        assert len(result) == 2
        assert "short text here" in result[0]["sentence_text"]
        assert result[0]["needs_new_prompt"] is True
        # Re-indexed
        assert result[0]["concept_index"] == 1
        assert result[1]["concept_index"] == 2

    def test_long_concept_split_into_two(self):
        """A concept over MAX_WORDS should be split."""
        long_text = " ".join(f"word{i}" for i in range(40))  # 40 words
        concepts = [
            _make_concept(long_text, index=1),
        ]
        result = _validate_concept_durations(concepts)
        assert len(result) == 2
        assert result[0]["needs_new_prompt"] is True
        assert result[1]["needs_new_prompt"] is True
        # Combined text should equal original
        recombined = result[0]["sentence_text"] + " " + result[1]["sentence_text"]
        assert recombined == long_text

    def test_last_short_concept_not_merged(self):
        """A short concept at the end (no next neighbor) should pass through."""
        concepts = [
            _make_concept("word " * 18, index=1),
            _make_concept("end", index=2),  # 1 word, last concept
        ]
        result = _validate_concept_durations(concepts)
        # No next neighbor to merge with — stays as-is
        assert len(result) == 2
        assert result[1]["sentence_text"].strip() == "end"

    def test_reindexing_after_merge(self):
        """After merge, concept_index values should be sequential."""
        concepts = [
            _make_concept("tiny", index=1),                   # too short
            _make_concept("word " * 15, index=2),             # ok
            _make_concept("word " * 18, index=3),             # ok
            _make_concept("word " * 20, index=4),             # ok
        ]
        result = _validate_concept_durations(concepts)
        for i, c in enumerate(result):
            assert c["concept_index"] == i + 1

    def test_empty_list(self):
        """Empty list should return empty."""
        assert _validate_concept_durations([]) == []

    def test_all_within_bounds(self):
        """All concepts within bounds should return same count."""
        concepts = [_make_concept("word " * 15, index=i) for i in range(1, 8)]
        result = _validate_concept_durations(concepts)
        assert len(result) == 7
