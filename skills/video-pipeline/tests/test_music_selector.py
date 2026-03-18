"""Tests for music_selector.py - per-act mood classification and track selection.

Tests the pure logic functions without actual API calls.
"""

import asyncio
import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock heavy client dependencies before importing music_selector
# We need to mock enough to prevent the bots/__init__.py chain from loading
sys.modules.setdefault("clients.anthropic_client", MagicMock())
sys.modules.setdefault("clients.google_client", MagicMock())
sys.modules.setdefault("clients.airtable_client", MagicMock())
sys.modules.setdefault("clients.apify_client", MagicMock())
sys.modules.setdefault("json_utils", MagicMock())

# Mock the bots module itself to prevent __init__.py from importing other bots
# We'll import directly from the specific module
_mock_bots = MagicMock()
sys.modules.setdefault("bots", _mock_bots)


def _run_async(coro):
    """Run an async coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


# Import the module directly to avoid bots/__init__.py import chain
# This requires the module to be importable standalone
import importlib.util
import os

_module_path = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "bots",
    "music_selector.py"
)
_spec = importlib.util.spec_from_file_location("music_selector", _module_path)
music_selector = importlib.util.module_from_spec(_spec)
sys.modules["bots.music_selector"] = music_selector
_spec.loader.exec_module(music_selector)


class TestClassifyActMood:
    """Test mood classification for script acts."""

    def _make_mock_anthropic(self):
        """Create a mock anthropic client."""
        client = MagicMock()
        client.generate = AsyncMock()
        return client

    def test_haiku_returns_tension(self):
        """Claude Haiku classifies as tension correctly."""
        classify_act_mood = music_selector.classify_act_mood

        mock_anthropic = self._make_mock_anthropic()
        mock_anthropic.generate.return_value = "tension"

        result = _run_async(classify_act_mood(
            mock_anthropic,
            act_number=1,
            act_text="The crisis deepens as military forces gather at the border."
        ))

        assert result == "tension"

    def test_haiku_returns_strategic(self):
        """Claude Haiku classifies as strategic correctly."""
        classify_act_mood = music_selector.classify_act_mood

        mock_anthropic = self._make_mock_anthropic()
        mock_anthropic.generate.return_value = "strategic"

        result = _run_async(classify_act_mood(
            mock_anthropic,
            act_number=2,
            act_text="The chess moves of geopolitical analysis unfold."
        ))

        assert result == "strategic"

    def test_haiku_returns_revelation(self):
        """Claude Haiku classifies as revelation correctly."""
        classify_act_mood = music_selector.classify_act_mood

        mock_anthropic = self._make_mock_anthropic()
        mock_anthropic.generate.return_value = "revelation"

        result = _run_async(classify_act_mood(
            mock_anthropic,
            act_number=3,
            act_text="The hidden truth about the financial collapse emerges."
        ))

        assert result == "revelation"

    def test_normalizes_response_whitespace(self):
        """Strips whitespace from Claude response."""
        classify_act_mood = music_selector.classify_act_mood

        mock_anthropic = self._make_mock_anthropic()
        mock_anthropic.generate.return_value = "  tension  \n"

        result = _run_async(classify_act_mood(
            mock_anthropic,
            act_number=1,
            act_text="Crisis text"
        ))

        assert result == "tension"

    def test_normalizes_response_lowercase(self):
        """Converts Claude response to lowercase."""
        classify_act_mood = music_selector.classify_act_mood

        mock_anthropic = self._make_mock_anthropic()
        mock_anthropic.generate.return_value = "STRATEGIC"

        result = _run_async(classify_act_mood(
            mock_anthropic,
            act_number=1,
            act_text="Analysis text"
        ))

        assert result == "strategic"

    def test_truncates_text_to_500_words(self):
        """Truncates act text to first 500 words."""
        classify_act_mood = music_selector.classify_act_mood

        mock_anthropic = self._make_mock_anthropic()
        mock_anthropic.generate.return_value = "tension"

        # Create text with 600 words
        long_text = " ".join(["word"] * 600)

        _run_async(classify_act_mood(
            mock_anthropic,
            act_number=1,
            act_text=long_text
        ))

        # Check that the prompt was called with truncated text
        call_args = mock_anthropic.generate.call_args
        prompt = call_args.kwargs.get("prompt", call_args.args[0] if call_args.args else "")

        # Count words in the act text portion (should be <= 500 + some prompt text)
        assert "word" in prompt
        # The truncated text should have at most 500 "word" instances
        assert prompt.count("word") <= 500

    def test_fallback_to_tension_keywords(self):
        """Falls back to keyword matching for tension when Haiku fails."""
        classify_act_mood = music_selector.classify_act_mood

        mock_anthropic = self._make_mock_anthropic()
        mock_anthropic.generate.side_effect = Exception("API error")

        result = _run_async(classify_act_mood(
            mock_anthropic,
            act_number=1,
            act_text="The military threat escalates as war becomes inevitable."
        ))

        assert result == "tension"

    def test_fallback_to_strategic_keywords(self):
        """Falls back to keyword matching for strategic when Haiku fails."""
        classify_act_mood = music_selector.classify_act_mood

        mock_anthropic = self._make_mock_anthropic()
        mock_anthropic.generate.side_effect = Exception("API error")

        result = _run_async(classify_act_mood(
            mock_anthropic,
            act_number=2,
            act_text="The calculated geopolitical chess move shifts the alliance."
        ))

        assert result == "strategic"

    def test_fallback_to_revelation_keywords(self):
        """Falls back to keyword matching for revelation when Haiku fails."""
        classify_act_mood = music_selector.classify_act_mood

        mock_anthropic = self._make_mock_anthropic()
        mock_anthropic.generate.side_effect = Exception("API error")

        result = _run_async(classify_act_mood(
            mock_anthropic,
            act_number=3,
            act_text="The hidden secret exposes the truth about the collapse."
        ))

        assert result == "revelation"

    def test_fallback_default_strategic(self):
        """Falls back to strategic when no keywords match."""
        classify_act_mood = music_selector.classify_act_mood

        mock_anthropic = self._make_mock_anthropic()
        mock_anthropic.generate.side_effect = Exception("API error")

        result = _run_async(classify_act_mood(
            mock_anthropic,
            act_number=1,
            act_text="Some generic text without any mood keywords."
        ))

        assert result == "strategic"

    def test_fallback_on_invalid_haiku_response(self):
        """Falls back when Haiku returns invalid mood."""
        classify_act_mood = music_selector.classify_act_mood

        mock_anthropic = self._make_mock_anthropic()
        mock_anthropic.generate.return_value = "excited"  # Not a valid mood

        result = _run_async(classify_act_mood(
            mock_anthropic,
            act_number=1,
            act_text="The crisis escalates with military conflict."
        ))

        # Should fall back to keyword matching since "excited" is invalid
        assert result == "tension"


class TestSelectTrackForMood:
    """Test track selection from available tracks."""

    def test_selects_matching_tension_track(self):
        """Selects a track with tension_ prefix."""
        select_track_for_mood = music_selector.select_track_for_mood

        tracks = [
            {"name": "tension_dark.mp3", "id": "id1"},
            {"name": "strategic_plan.mp3", "id": "id2"},
            {"name": "revelation_truth.mp3", "id": "id3"},
        ]

        result = select_track_for_mood("tension", tracks)

        assert result is not None
        assert result["name"].startswith("tension_")

    def test_selects_matching_strategic_track(self):
        """Selects a track with strategic_ prefix."""
        select_track_for_mood = music_selector.select_track_for_mood

        tracks = [
            {"name": "tension_dark.mp3", "id": "id1"},
            {"name": "strategic_plan.mp3", "id": "id2"},
            {"name": "revelation_truth.mp3", "id": "id3"},
        ]

        result = select_track_for_mood("strategic", tracks)

        assert result is not None
        assert result["name"].startswith("strategic_")

    def test_selects_matching_revelation_track(self):
        """Selects a track with revelation_ prefix."""
        select_track_for_mood = music_selector.select_track_for_mood

        tracks = [
            {"name": "tension_dark.mp3", "id": "id1"},
            {"name": "strategic_plan.mp3", "id": "id2"},
            {"name": "revelation_truth.mp3", "id": "id3"},
        ]

        result = select_track_for_mood("revelation", tracks)

        assert result is not None
        assert result["name"].startswith("revelation_")

    def test_returns_none_when_no_match(self):
        """Returns None when no tracks match the mood."""
        select_track_for_mood = music_selector.select_track_for_mood

        tracks = [
            {"name": "tension_dark.mp3", "id": "id1"},
            {"name": "tension_crisis.mp3", "id": "id2"},
        ]

        result = select_track_for_mood("revelation", tracks)

        assert result is None

    def test_returns_none_for_empty_tracks(self):
        """Returns None when tracks list is empty."""
        select_track_for_mood = music_selector.select_track_for_mood

        result = select_track_for_mood("tension", [])

        assert result is None

    def test_random_selection_from_multiple_matches(self):
        """Selects randomly from multiple matching tracks."""
        select_track_for_mood = music_selector.select_track_for_mood

        tracks = [
            {"name": "tension_a.mp3", "id": "id1"},
            {"name": "tension_b.mp3", "id": "id2"},
            {"name": "tension_c.mp3", "id": "id3"},
        ]

        # Run multiple times to verify randomness
        results = set()
        for _ in range(50):
            result = select_track_for_mood("tension", tracks)
            results.add(result["name"])

        # Should see more than one track selected over 50 runs
        assert len(results) > 1


class TestSelectMusicForScript:
    """Test full script music selection."""

    def _make_mock_anthropic(self):
        """Create a mock anthropic client."""
        client = MagicMock()
        client.generate = AsyncMock()
        return client

    def _make_mock_tracks(self):
        """Sample tracks from Google Drive."""
        return [
            {"name": "tension_crisis.mp3", "id": "file_id_1"},
            {"name": "tension_dark.mp3", "id": "file_id_2"},
            {"name": "strategic_analysis.mp3", "id": "file_id_3"},
            {"name": "strategic_chess.mp3", "id": "file_id_4"},
            {"name": "revelation_truth.mp3", "id": "file_id_5"},
            {"name": "revelation_hidden.mp3", "id": "file_id_6"},
        ]

    def test_selects_music_for_each_act(self):
        """Selects music for each act in script."""
        select_music_for_script = music_selector.select_music_for_script

        mock_anthropic = self._make_mock_anthropic()
        # Mock Claude to return different moods per act
        mock_anthropic.generate.side_effect = ["tension", "strategic", "revelation"]

        script_acts = {
            1: "Act 1 text about crisis",
            2: "Act 2 text about analysis",
            3: "Act 3 text about truth",
        }

        with patch.object(music_selector, "_list_music_tracks", return_value=self._make_mock_tracks()):
            result = _run_async(select_music_for_script(mock_anthropic, script_acts))

        assert len(result) == 3
        assert all("act" in r for r in result)
        assert all("file" in r for r in result)
        assert all("file_id" in r for r in result)
        assert all("mood" in r for r in result)
        assert all(r["volume"] == 0.08 for r in result)

    def test_returns_correct_structure(self):
        """Returns list with correct dict structure."""
        select_music_for_script = music_selector.select_music_for_script

        mock_anthropic = self._make_mock_anthropic()
        mock_anthropic.generate.return_value = "tension"

        script_acts = {1: "Act 1 text"}

        with patch.object(music_selector, "_list_music_tracks", return_value=self._make_mock_tracks()):
            result = _run_async(select_music_for_script(mock_anthropic, script_acts))

        assert len(result) == 1
        assert result[0]["act"] == 1
        assert result[0]["file"].startswith("music/tension_")
        assert result[0]["file_id"].startswith("file_id_")
        assert result[0]["mood"] == "tension"
        assert result[0]["volume"] == 0.08

    def test_handles_no_matching_tracks(self):
        """Handles case where no tracks match mood."""
        select_music_for_script = music_selector.select_music_for_script

        mock_anthropic = self._make_mock_anthropic()
        mock_anthropic.generate.return_value = "revelation"

        # Only tension tracks available
        tracks = [{"name": "tension_only.mp3", "id": "id1"}]

        script_acts = {1: "Act 1 text"}

        with patch.object(music_selector, "_list_music_tracks", return_value=tracks):
            result = _run_async(select_music_for_script(mock_anthropic, script_acts))

        # Should still return entry but with None file info
        assert len(result) == 1
        assert result[0]["file"] is None
        assert result[0]["file_id"] is None

    def test_processes_acts_in_order(self):
        """Processes acts in numerical order."""
        select_music_for_script = music_selector.select_music_for_script

        mock_anthropic = self._make_mock_anthropic()
        mock_anthropic.generate.return_value = "strategic"

        # Pass acts out of order
        script_acts = {
            3: "Third act",
            1: "First act",
            2: "Second act",
        }

        with patch.object(music_selector, "_list_music_tracks", return_value=self._make_mock_tracks()):
            result = _run_async(select_music_for_script(mock_anthropic, script_acts))

        # Results should be in order
        assert [r["act"] for r in result] == [1, 2, 3]


class TestMoodKeywords:
    """Test mood keyword constants."""

    def test_tension_keywords_exist(self):
        """Tension mood has expected keywords."""
        MOOD_KEYWORDS = music_selector.MOOD_KEYWORDS

        assert "tension" in MOOD_KEYWORDS
        expected = {"crisis", "conflict", "danger", "threat", "war"}
        assert expected.issubset(set(MOOD_KEYWORDS["tension"]))

    def test_strategic_keywords_exist(self):
        """Strategic mood has expected keywords."""
        MOOD_KEYWORDS = music_selector.MOOD_KEYWORDS

        assert "strategic" in MOOD_KEYWORDS
        expected = {"analysis", "power", "calculated", "geopolitical", "chess"}
        assert expected.issubset(set(MOOD_KEYWORDS["strategic"]))

    def test_revelation_keywords_exist(self):
        """Revelation mood has expected keywords."""
        MOOD_KEYWORDS = music_selector.MOOD_KEYWORDS

        assert "revelation" in MOOD_KEYWORDS
        expected = {"personal", "hidden", "exposed", "truth", "secret"}
        assert expected.issubset(set(MOOD_KEYWORDS["revelation"]))


class TestMusicFolderConstant:
    """Test music folder ID constant."""

    def test_folder_id_exists(self):
        """Music folder ID constant is defined."""
        MUSIC_FOLDER_ID = music_selector.MUSIC_FOLDER_ID

        assert MUSIC_FOLDER_ID == "17FF7IanYzbgfLrIwXIjKwNlqRSkefS9i"
