# skills/video-pipeline/autopilot/tests/test_pattern_library_curiosity_gap.py
"""Tests for curiosity gap extensions to pattern library."""

import pytest
from pathlib import Path
from autopilot.learning.pattern_library import PatternLibrary

# Import CuriosityStructure - the test runs from skills/video-pipeline/
# so curiosity_gap is a sibling package that should be importable
from curiosity_gap.structures import CuriosityStructure


SAMPLE_COMPETITOR_PATTERNS = """# Competitor Patterns

Last updated: 2026-03-20
Videos analyzed: 47

## Top Performing Structures (by VPH)

### hidden_flaw (n=12, avg VPH: 165)
- CaspianReport: "The Pipeline Trap Nobody..." (VPH: 210)
- Economics Explained: "The $2T Mistake..." (VPH: 180)

### time_bomb (n=8, avg VPH: 148)
- PolyMatter: "The 30-Year Trap China..." (VPH: 175)

## Thumbnail Styles (by channel)

### CaspianReport
- Dominant: red/yellow, face-left, 2-line text
- Yin/yang: Title = problem → Thumbnail = consequence

## Unclassified (other) — Pending Review
- "5 Days Until China's Dollar Deadline" (countdown pattern?)
"""


class TestPatternLibraryCuriosityGap:
    """Test suite for curiosity gap pattern library extensions."""

    @pytest.fixture
    def temp_memory_dir(self, tmp_path):
        """Create temp memory directory with sample files."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        # Write sample competitor patterns
        (memory_dir / "competitor_patterns.md").write_text(SAMPLE_COMPETITOR_PATTERNS)

        return memory_dir

    @pytest.fixture
    def library(self, temp_memory_dir):
        return PatternLibrary(memory_dir=temp_memory_dir)

    def test_get_curiosity_gap_patterns_all(self, library):
        """Should return all curiosity gap structure performance."""
        patterns = library.get_curiosity_gap_patterns()

        assert len(patterns) >= 2  # hidden_flaw and time_bomb have data
        hidden_flaw = next((p for p in patterns if p.structure == CuriosityStructure.HIDDEN_FLAW), None)
        assert hidden_flaw is not None
        assert hidden_flaw.sample_size_competitors == 12
        assert hidden_flaw.avg_vph_competitors == 165

    def test_get_curiosity_gap_patterns_filtered(self, library):
        """Should filter by specific structure."""
        patterns = library.get_curiosity_gap_patterns(
            structure=CuriosityStructure.TIME_BOMB
        )

        assert len(patterns) == 1
        assert patterns[0].structure == CuriosityStructure.TIME_BOMB
        assert patterns[0].avg_vph_competitors == 148

    def test_get_competitor_patterns_all(self, library):
        """Should return all competitor patterns."""
        patterns = library.get_competitor_patterns()

        assert len(patterns) >= 3  # 3 videos listed

    def test_get_competitor_patterns_by_channel(self, library):
        """Should filter by channel."""
        patterns = library.get_competitor_patterns(channel="CaspianReport")

        assert len(patterns) >= 1
        assert all(p.channel == "CaspianReport" for p in patterns)

    def test_get_competitor_patterns_by_min_vph(self, library):
        """Should filter by minimum VPH."""
        patterns = library.get_competitor_patterns(min_vph=200)

        assert all(p.vph >= 200 for p in patterns)

    def test_get_unclassified_titles(self, library):
        """Should return unclassified 'other' titles."""
        unclassified = library.get_unclassified_titles()

        assert len(unclassified) >= 1
        assert "Dollar Deadline" in unclassified[0]["title"]
