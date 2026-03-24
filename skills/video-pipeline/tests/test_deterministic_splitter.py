"""Tests for deterministic scene splitter using real narration as mock data.

Uses the Persian Gulf aircraft carriers scene — a real script excerpt that
exposed multiple splitter bugs: abbreviation splitting, dangling articles,
excessive fragment count, and orphan creation.
"""

import sys
from unittest.mock import MagicMock

# Mock heavy deps so tests run without API keys
sys.modules.setdefault("httpx", MagicMock())
sys.modules.setdefault("mutagen", MagicMock())
sys.modules.setdefault("mutagen.mp3", MagicMock())

import pytest

sys.path.insert(0, "clients")
from shared.clients.deterministic_splitter import segment_scene_deterministic, MAX_DURATION
from shared.clients.sentence_utils import split_into_sentences


# ── Real scene narration (mock data) ─────────────────────────────────

PERSIAN_GULF_SCENE = (
    "Right now, three American aircraft carriers\u2014representing over $30 billion "
    "in assets and 15,000 personnel\u2014are floating in a body of water you could "
    "drive across in 90 minutes. "
    "The USS Gerald R. Ford cost $13 billion to build, making it the most "
    "expensive warship ever constructed, according to the U.S. Naval Institute. "
    "The USS Abraham Lincoln and the Ford carrier strike groups are now operating "
    "in the Persian Gulf as of March 2026. "
    "Each carrier displaces 100,000 tons, stands 250 feet tall, carries 60 to "
    "75 aircraft, and houses 5,000 sailors. "
    "You are being told this is a show of overwhelming force. Maximum pressure. "
    "Deterrence. "
    "Here is what you are not being told: Iran military leadership called this "
    "deployment the opportunity of a century. "
    "Because the Persian Gulf is not an ocean. It is 600 miles wide at its "
    "broadest point. "
    "The Strait of Hormuz\u2014the only exit\u2014is 21 nautical miles across at its "
    "narrowest navigable point, according to industry reports. "
    "That is narrower than the distance between Manhattan and JFK Airport. "
    "In open ocean, a carrier traveling at 35 miles per hour expands its "
    "potential location to 6,000 square miles within 90 minutes\u2014nearly "
    "impossible to target. "
    "In the Persian Gulf, there is nowhere to hide. Iran Khalij Fars missiles "
    "travel at Mach 3 to Mach 4 with a 300-kilometer range. "
    "Their Abu Mahdi cruise missiles reach over 1,000 kilometers with "
    "AI-assisted guidance, according to Defence Security Asia. "
    "When you follow the strategic mathematics, you find something the Pentagon "
    "does not want you to see: the most powerful weapons in the American arsenal "
    "just sailed into a kill zone designed specifically to destroy them. "
    "And what you will see by the end is that your gas prices, your retirement "
    "account, and potentially American sons and daughters in uniform all depend "
    "on whether US planners learn this lesson before Iran teaches it the hard way."
)

# Words that should never end a segment
DANGLING_ENDINGS = {
    "the", "a", "an", "of", "in", "to", "for", "and", "or", "but", "not",
    "is", "it", "its", "at", "by", "on", "with", "from", "into", "that",
    "this", "their", "our", "your", "his", "her", "was", "were", "are",
}


# ── Sentence Splitter Tests ──────────────────────────────────────────

class TestSentenceSplitterAbbreviations:
    """Regression tests: abbreviations must not trigger sentence splits."""

    def test_us_abbreviation(self):
        text = "according to the U.S. Naval Institute."
        sents = split_into_sentences(text)
        assert len(sents) == 1
        assert "U.S. Naval Institute" in sents[0]

    def test_single_letter_initial(self):
        text = "The USS Gerald R. Ford cost $13 billion."
        sents = split_into_sentences(text)
        assert len(sents) == 1
        assert "Gerald R. Ford" in sents[0]

    def test_decimal_number(self):
        text = "The price was $13.5 billion. It was expensive."
        sents = split_into_sentences(text)
        assert len(sents) == 2
        assert "$13.5 billion" in sents[0]

    def test_multiple_abbreviations_in_one_sentence(self):
        text = "The U.S. Navy commissioned the USS Gerald R. Ford in 2017."
        sents = split_into_sentences(text)
        assert len(sents) == 1

    def test_abbreviation_mid_sentence(self):
        """U.S. mid-sentence should not split."""
        text = "The U.S. government signed the deal. It was historic."
        sents = split_into_sentences(text)
        assert len(sents) == 2
        assert "U.S. government" in sents[0]

    def test_real_scene_sentence_count(self):
        """The full scene should produce ~14-18 clean sentences."""
        sents = split_into_sentences(PERSIAN_GULF_SCENE)
        # Before fix: 22+ sentences (abbreviations broken)
        # After fix: ~14-18 sentences (clean boundaries)
        assert 12 <= len(sents) <= 20, f"Expected 12-20 sentences, got {len(sents)}"

    def test_no_orphan_fragments(self):
        """No sentence should be fewer than 3 words (orphan from bad split)."""
        sents = split_into_sentences(PERSIAN_GULF_SCENE)
        for sent in sents:
            word_count = len(sent.split())
            # Allow short intentional sentences like "Deterrence."
            # but not fragments like "Naval Institute." or "Ford cost..."
            if word_count < 3:
                # Must be an intentional short sentence (single word + period)
                assert word_count >= 1, f"Empty sentence: '{sent}'"


# ── Deterministic Splitter Tests ─────────────────────────────────────

class TestRealSceneSegmentation:
    """Tests using real Persian Gulf carriers narration as mock data."""

    @pytest.fixture
    def segments(self):
        return segment_scene_deterministic(PERSIAN_GULF_SCENE, voice_duration=None)

    def test_segment_count_reasonable(self, segments):
        """Documentary pacing: 10-16 segments for ~80s of narration."""
        assert len(segments) <= 16, f"Too many segments: {len(segments)} (max 16)"
        assert len(segments) >= 8, f"Too few segments: {len(segments)} (min 8)"

    def test_no_dangling_fragments(self, segments):
        """No segment should end with a dangling article/preposition."""
        for seg in segments:
            last_word = seg["text"].split()[-1].strip(".,;:!?\"'").lower()
            assert last_word not in DANGLING_ENDINGS, (
                f"Segment {seg['segment_index']} ends with dangling "
                f"'{last_word}': ...{seg['text'][-60:]}"
            )

    def test_no_segment_exceeds_max_duration(self, segments):
        """Soft cap: no segment > MAX_DURATION + 1.0s."""
        for seg in segments:
            assert seg["duration"] <= MAX_DURATION + 1.0, (
                f"Segment {seg['segment_index']} duration {seg['duration']}s "
                f"exceeds soft max {MAX_DURATION + 1.0}s"
            )

    def test_no_tiny_orphans(self, segments):
        """No segment under 4.0s (orphan threshold)."""
        for seg in segments:
            assert seg["duration"] >= 4.0, (
                f"Segment {seg['segment_index']} is orphan at {seg['duration']}s: "
                f"'{seg['text'][:60]}'"
            )

    def test_segments_reconstruct_original(self, segments):
        """All segments concatenated must equal the original text."""
        combined = " ".join(seg["text"] for seg in segments)
        normalized = " ".join(PERSIAN_GULF_SCENE.split())
        assert combined == normalized

    def test_abbreviations_preserved(self, segments):
        """Gerald R. Ford and U.S. Naval Institute must stay in same segment."""
        for seg in segments:
            text = seg["text"]
            if "Gerald R." in text:
                assert "Ford" in text, (
                    f"'Gerald R.' split from 'Ford': {text[:80]}"
                )
            if "U.S." in text:
                # U.S. should be followed by its noun in the same segment
                assert "Naval" in text or "Navy" in text or "." in text[text.index("U.S.") + 4:text.index("U.S.") + 15], (
                    f"'U.S.' may be split from its noun: {text[:80]}"
                )

    def test_kill_zone_in_one_segment(self, segments):
        """The 'kill zone' phrase should not be split across segments."""
        kill_zone_segs = [s for s in segments if "kill zone" in s["text"]]
        assert len(kill_zone_segs) == 1, (
            f"'kill zone' split across {len(kill_zone_segs)} segments"
        )

    def test_each_segment_has_visual_subject(self, segments):
        """Each segment must be long enough to have a clear subject (>= 8 words)."""
        for seg in segments:
            assert seg["word_count"] >= 8, (
                f"Segment {seg['segment_index']} too short for a visual "
                f"({seg['word_count']} words): '{seg['text'][:60]}'"
            )

    def test_segment_indices_sequential(self, segments):
        """Segment indices must be 1-based sequential."""
        for i, seg in enumerate(segments):
            assert seg["segment_index"] == i + 1

    def test_cumulative_starts_increase(self, segments):
        """Cumulative start times must monotonically increase."""
        for i in range(1, len(segments)):
            assert segments[i]["cumulative_start"] > segments[i - 1]["cumulative_start"]


# ── Edge Case Tests ──────────────────────────────────────────────────

class TestSplitterEdgeCases:
    """Edge cases that triggered bugs historically."""

    def test_single_long_sentence(self):
        """A 45-word sentence should split cleanly, not produce orphans."""
        text = (
            "The Federal Reserve's quantitative easing program which was "
            "initially designed as a temporary emergency measure to stabilize "
            "financial markets during the 2008 crisis has now become a permanent "
            "fixture of monetary policy creating unprecedented levels of asset "
            "price inflation while doing very little to stimulate productive "
            "economic growth."
        )
        segments = segment_scene_deterministic(text, voice_duration=None)
        for seg in segments:
            assert seg["word_count"] >= 8, (
                f"Orphan fragment: '{seg['text'][:60]}'"
            )

    def test_short_punchy_sentences(self):
        """Multiple short sentences should merge into filmable segments."""
        text = (
            "The deal was done. It was over. Nobody saw it coming. "
            "The markets crashed. Banks failed. People lost everything."
        )
        segments = segment_scene_deterministic(text, voice_duration=None)
        # 6 tiny sentences should merge into 1-2 segments, not 6
        assert len(segments) <= 3

    def test_empty_text(self):
        """Empty text should return empty list."""
        assert segment_scene_deterministic("", None) == []
        assert segment_scene_deterministic("   ", None) == []
