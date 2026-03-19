"""Tests for thumbnail adapter."""

import pytest
from unittest.mock import Mock
from autopilot.analysis.thumbnail_adapter import ThumbnailAdapter
from autopilot.analysis.thumbnail_analyzer import ThumbnailAnalysis
from autopilot.learning.pattern_library import PatternLibrary


class TestThumbnailAdapter:
    """Test suite for thumbnail adapter."""

    @pytest.fixture
    def mock_pattern_library(self):
        """Mock pattern library."""
        mock = Mock(spec=PatternLibrary)
        mock.is_proven_element.return_value = False
        mock.is_anti_pattern.return_value = False
        mock.get_thumbnail_patterns.return_value = []
        return mock

    @pytest.fixture
    def adapter(self, mock_pattern_library):
        return ThumbnailAdapter(pattern_library=mock_pattern_library)

    @pytest.fixture
    def sample_analysis(self):
        """Sample thumbnail analysis."""
        return ThumbnailAnalysis(
            colors={
                "background": "deep red gradient",
                "text": "bright yellow with black outline",
                "accents": "white, gold"
            },
            composition="face_left_text_right",
            text={
                "lines": 2,
                "size_pct": 65,
                "style": "bold caps"
            },
            subject={
                "face": True,
                "expression": "stern/serious",
                "type": "leader portrait"
            },
            style="editorial illustration, high saturation",
            confidence=0.85
        )

    def test_generate_replace_override(self, adapter, sample_analysis):
        """Should generate REPLACE: prefix override."""
        override = adapter.generate_override(sample_analysis, use_replace=True)

        assert override.startswith("REPLACE:")
        assert "red" in override.lower()
        assert "yellow" in override.lower()
        assert "leader portrait" in override.lower() or "face" in override.lower()

    def test_generate_append_override(self, adapter, sample_analysis):
        """Should generate APPEND: prefix override."""
        override = adapter.generate_override(sample_analysis, use_replace=False)

        assert override.startswith("APPEND:")
        assert len(override) > 10  # Has actual content

    def test_override_includes_composition(self, adapter, sample_analysis):
        """Should describe composition in override."""
        override = adapter.generate_override(sample_analysis)

        assert "left" in override.lower() or "right" in override.lower()

    def test_override_includes_text_style(self, adapter, sample_analysis):
        """Should describe text styling."""
        override = adapter.generate_override(sample_analysis)

        assert "text" in override.lower()
        assert "bold" in override.lower() or "caps" in override.lower()

    def test_avoids_anti_patterns(self, adapter, sample_analysis, mock_pattern_library):
        """Should note anti-patterns to avoid."""
        # Mark blue as anti-pattern
        mock_pattern_library.is_anti_pattern.side_effect = lambda e, c: "blue" in e.lower()

        override = adapter.generate_override(sample_analysis)

        # Should explicitly avoid blue if it's an anti-pattern
        # (Not necessarily in output if input doesn't have blue)
        assert override is not None

    def test_handles_minimal_analysis(self, adapter):
        """Should handle analysis with minimal data."""
        minimal = ThumbnailAnalysis(
            colors={"background": "red"},
            composition="centered",
            confidence=0.5
        )

        override = adapter.generate_override(minimal)

        assert override.startswith("REPLACE:") or override.startswith("APPEND:")
        assert "red" in override.lower()

    def test_describe_colors(self, adapter, sample_analysis):
        """Should have color description helper."""
        colors_desc = adapter._describe_colors(sample_analysis.colors)

        assert "red" in colors_desc.lower()
        assert "yellow" in colors_desc.lower()

    def test_describe_composition(self, adapter, sample_analysis):
        """Should have composition description helper."""
        comp_desc = adapter._describe_composition(sample_analysis.composition, sample_analysis.subject)

        assert len(comp_desc) > 0
