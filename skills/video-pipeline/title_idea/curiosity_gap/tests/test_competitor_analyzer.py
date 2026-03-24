# skills/video-pipeline/curiosity_gap/tests/test_competitor_analyzer.py
"""Tests for competitor analyzer."""

import asyncio
import pytest
from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime, timezone

from title_idea.curiosity_gap.competitor_analyzer import (
    TitleAnalysis,
    CompetitorAnalyzer,
    should_deep_analyze_sync,
)
from title_idea.curiosity_gap.structures import CuriosityStructure


def run_async(coro):
    """Run an async coroutine synchronously for testing."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestTitleAnalysis:
    """Test suite for title analysis dataclass."""

    def test_title_analysis_creation(self):
        """Should create TitleAnalysis with all fields."""
        analysis = TitleAnalysis(
            structure=CuriosityStructure.HIDDEN_FLAW,
            confidence=78,
            gap_mechanism="What's the $100B mistake?",
            variables={"amount": "$100B", "entity": "Saudi Arabia"},
        )

        assert analysis.structure == CuriosityStructure.HIDDEN_FLAW
        assert analysis.confidence == 78
        assert analysis.gap_mechanism == "What's the $100B mistake?"
        assert analysis.variables["amount"] == "$100B"


class TestShouldDeepAnalyze:
    """Test suite for VPH percentile calculation."""

    @pytest.fixture
    def mock_channel_videos(self):
        """Mock videos with various VPH values."""
        return [
            {"vph": 50}, {"vph": 75}, {"vph": 100}, {"vph": 125}, {"vph": 150},
            {"vph": 175}, {"vph": 200}, {"vph": 225}, {"vph": 250}, {"vph": 300},
        ]

    def test_top_20_percent_qualifies_sync(self, mock_channel_videos):
        """Videos in top 20% should qualify for deep analysis."""
        # VPH 280 is in top 20% of [50, 75, 100, 125, 150, 175, 200, 225, 250, 300]
        with patch('title_idea.curiosity_gap.competitor_analyzer.get_recent_channel_videos') as mock_get:
            mock_get.return_value = mock_channel_videos
            result = should_deep_analyze_sync(
                video_vph=280,
                channel_name="CaspianReport",
            )
            assert result is True

    def test_bottom_80_percent_excluded_sync(self, mock_channel_videos):
        """Videos below top 20% should not qualify."""
        # VPH 80 is in bottom 80%
        with patch('title_idea.curiosity_gap.competitor_analyzer.get_recent_channel_videos') as mock_get:
            mock_get.return_value = mock_channel_videos
            result = should_deep_analyze_sync(
                video_vph=80,
                channel_name="CaspianReport",
            )
            assert result is False

    def test_cold_start_uses_absolute_threshold_sync(self):
        """New channels with <5 videos should use absolute VPH threshold."""
        # Only 3 videos = cold start
        with patch('title_idea.curiosity_gap.competitor_analyzer.get_recent_channel_videos') as mock_get:
            mock_get.return_value = [{"vph": 50}, {"vph": 75}, {"vph": 100}]

            # VPH 120 >= 100 threshold
            result = should_deep_analyze_sync(video_vph=120, channel_name="NewChannel")
            assert result is True

            # VPH 80 < 100 threshold
            result = should_deep_analyze_sync(video_vph=80, channel_name="NewChannel")
            assert result is False

    def test_duplicate_vph_handled_correctly_sync(self):
        """Should handle duplicate VPH values using bisect."""
        # Many duplicates at 100
        with patch('title_idea.curiosity_gap.competitor_analyzer.get_recent_channel_videos') as mock_get:
            mock_get.return_value = [
                {"vph": 100}, {"vph": 100}, {"vph": 100}, {"vph": 100}, {"vph": 100},
                {"vph": 200}, {"vph": 200}, {"vph": 300}, {"vph": 400}, {"vph": 500},
            ]
            # VPH 350 should be in top 20% (position 7-8 of 10)
            result = should_deep_analyze_sync(video_vph=350, channel_name="TestChannel")
            assert result is True


class TestCompetitorAnalyzer:
    """Test suite for CompetitorAnalyzer class."""

    @pytest.fixture
    def analyzer(self):
        return CompetitorAnalyzer()

    @pytest.fixture
    def mock_claude_response(self):
        return {
            "structure": "hidden_flaw",
            "confidence": 78,
            "gap_mechanism": "What's the $100B mistake they're hiding?",
            "variables": {"amount": "$100B", "entity": "Saudi Arabia"},
        }

    def test_analyze_title_returns_analysis(self, analyzer, mock_claude_response):
        """Should return TitleAnalysis from Claude response."""
        async def _test():
            with patch.object(analyzer, '_call_claude_for_title') as mock_claude:
                mock_claude.return_value = mock_claude_response

                result = await analyzer.analyze_title("The $100B Mistake Saudi Arabia Is Hiding")

                assert isinstance(result, TitleAnalysis)
                assert result.structure == CuriosityStructure.HIDDEN_FLAW
                assert result.confidence == 78

        run_async(_test())

    def test_analyze_title_handles_other(self, analyzer):
        """Should handle 'other' structure for unclassified titles."""
        async def _test():
            with patch.object(analyzer, '_call_claude_for_title') as mock_claude:
                mock_claude.return_value = {
                    "structure": "other",
                    "confidence": 45,
                    "gap_mechanism": "countdown pattern",
                    "variables": {"days": "5"},
                }

                result = await analyzer.analyze_title("5 Days Until China's Dollar Deadline")

                assert result.structure == CuriosityStructure.OTHER
                assert result.confidence == 45

        run_async(_test())

    def test_analyze_title_normalizes_invalid_structure(self, analyzer):
        """Should normalize invalid structures to OTHER."""
        async def _test():
            with patch.object(analyzer, '_call_claude_for_title') as mock_claude:
                mock_claude.return_value = {
                    "structure": "unknown_structure",
                    "confidence": 50,
                    "gap_mechanism": "unclear",
                    "variables": {},
                }

                result = await analyzer.analyze_title("Some Random Title")

                assert result.structure == CuriosityStructure.OTHER

        run_async(_test())
