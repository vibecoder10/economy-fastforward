"""Tests for osiris.title_analyzer module."""

import pytest
from unittest.mock import MagicMock, AsyncMock

from osiris.title_analyzer import TitleAnalyzer, TitlePattern


class TestGroupByVphTier:
    """Tests for _group_by_vph_tier method."""

    def test_groups_videos_correctly(self):
        """Videos should be grouped into correct VPH tiers."""
        mock_airtable = MagicMock()
        mock_anthropic = MagicMock()
        analyzer = TitleAnalyzer(mock_airtable, mock_anthropic)

        videos = [
            {"Title": "Top video", "VPH": 250},
            {"Title": "Good video", "VPH": 150},
            {"Title": "Average video", "VPH": 75},
            {"Title": "Below video", "VPH": 30},
        ]

        tiers = analyzer._group_by_vph_tier(videos)

        assert len(tiers["top"]) == 1
        assert len(tiers["good"]) == 1
        assert len(tiers["average"]) == 1
        assert len(tiers["below"]) == 1
        assert tiers["top"][0]["Title"] == "Top video"

    def test_handles_empty_list(self):
        """Should handle empty video list."""
        mock_airtable = MagicMock()
        mock_anthropic = MagicMock()
        analyzer = TitleAnalyzer(mock_airtable, mock_anthropic)

        tiers = analyzer._group_by_vph_tier([])

        assert tiers["top"] == []
        assert tiers["good"] == []


class TestExtractStructuralPatterns:
    """Tests for _extract_structural_patterns method."""

    def test_detects_question_format(self):
        """Should detect question mark titles."""
        mock_airtable = MagicMock()
        mock_anthropic = MagicMock()
        analyzer = TitleAnalyzer(mock_airtable, mock_anthropic)

        videos = [
            {"Title": "Why Did Russia Invade?", "VPH": 100},
            {"Title": "What Happens Next?", "VPH": 150},
            {"Title": "No question here", "VPH": 80},
        ] * 3  # Need 5+ for pattern detection

        insights, raw_data = analyzer._extract_structural_patterns(videos)

        question_insights = [i for i in insights if "Question" in i]
        assert len(question_insights) >= 1

    def test_detects_caps_emphasis(self):
        """Should detect ALL CAPS words."""
        mock_airtable = MagicMock()
        mock_anthropic = MagicMock()
        analyzer = TitleAnalyzer(mock_airtable, mock_anthropic)

        videos = [
            {"Title": "Russia EXPOSED: The Truth", "VPH": 200},
            {"Title": "China's COLLAPSE Begins", "VPH": 180},
        ] * 3

        insights, raw_data = analyzer._extract_structural_patterns(videos)

        caps_insights = [i for i in insights if "Caps" in i]
        assert len(caps_insights) >= 1

    def test_detects_numbers(self):
        """Should detect numbers/statistics."""
        mock_airtable = MagicMock()
        mock_anthropic = MagicMock()
        analyzer = TitleAnalyzer(mock_airtable, mock_anthropic)

        # Need 5+ videos matching the same pattern to generate insight
        videos = [
            {"Title": "The $50 Billion Problem", "VPH": 200},
            {"Title": "Why $80 Billion Was Lost", "VPH": 180},
            {"Title": "The $100 Billion Question", "VPH": 190},
            {"Title": "$20 Billion Deal Revealed", "VPH": 170},
            {"Title": "How $500 Billion Disappeared", "VPH": 210},
        ]

        insights, raw_data = analyzer._extract_structural_patterns(videos)

        number_insights = [i for i in insights if "Numbers" in i]
        assert len(number_insights) >= 1
        # Also verify raw_data structure
        assert len(raw_data) >= 1
        assert raw_data[0]["pattern_name"] == "Numbers Stats"
        assert raw_data[0]["count"] == 5


class TestExtractThemeClusters:
    """Tests for _extract_theme_clusters method."""

    def test_clusters_by_keyword(self):
        """Should cluster videos by theme keywords."""
        mock_airtable = MagicMock()
        mock_anthropic = MagicMock()
        analyzer = TitleAnalyzer(mock_airtable, mock_anthropic)

        videos = [
            {"Title": "Russia War Escalates", "VPH": 200},
            {"Title": "NATO Military Response", "VPH": 180},
            {"Title": "Dollar Collapse Coming", "VPH": 150},
        ]

        clusters = analyzer._extract_theme_clusters(videos)

        assert "geopolitics" in clusters
        assert "economy" in clusters
        assert len(clusters["geopolitics"]) == 2
        assert len(clusters["economy"]) == 1


class TestBuildChannelBreakdowns:
    """Tests for _build_channel_breakdowns method."""

    def test_calculates_channel_averages(self):
        """Should calculate per-channel VPH averages."""
        mock_airtable = MagicMock()
        mock_anthropic = MagicMock()
        analyzer = TitleAnalyzer(mock_airtable, mock_anthropic)

        videos = [
            {"Title": "Video 1", "Channel": "CaspianReport", "VPH": 200},
            {"Title": "Video 2", "Channel": "CaspianReport", "VPH": 300},
            {"Title": "Video 3", "Channel": "CaspianReport", "VPH": 250},
            {"Title": "Video 4", "Channel": "AiTelly", "VPH": 150},
            {"Title": "Video 5", "Channel": "AiTelly", "VPH": 150},
            {"Title": "Video 6", "Channel": "AiTelly", "VPH": 150},
        ]

        breakdowns = analyzer._build_channel_breakdowns(videos)

        assert "CaspianReport" in breakdowns
        assert breakdowns["CaspianReport"]["avg_vph"] == 250
        assert breakdowns["CaspianReport"]["count"] == 3
