"""Tests for pattern library."""

import pytest
from pathlib import Path
from autopilot.learning.pattern_library import PatternLibrary, ThumbnailPattern, TitlePattern


class TestPatternLibrary:
    """Test suite for pattern library."""

    @pytest.fixture
    def temp_memory_dir(self, tmp_path):
        """Create temporary memory directory with sample files."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        # Create sample LEARNINGS.md
        (memory_dir / "LEARNINGS.md").write_text("""# Autopilot Learnings

Last updated: 2026-03-18
Videos produced: 5
Avg CTR: 4.2%
Best CTR: 5.8% ("China's Dollar Trap")

---

## Top 5 Proven Patterns

1. Red/yellow color scheme (n=3)
2. Question format titles (n=4)

---

## Anti-Patterns (Stop Doing)

- Blue backgrounds (2 failures)
""")

        # Create sample thumbnail_patterns.md
        (memory_dir / "thumbnail_patterns.md").write_text("""# Thumbnail Patterns

## Proven Elements (KEEP)

- red_yellow_combo: Red background with yellow text
- face_left: Face on left side of frame

## Anti-Patterns (AVOID)

- blue_background: Blue tones in background
""")

        # Create sample title_patterns.md
        (memory_dir / "title_patterns.md").write_text("""# Title Patterns

## Proven Formulas (USE)

- question: End title with question mark
- number: Include specific numbers

## Anti-Patterns (AVOID)

- all_lowercase: All lowercase titles
""")

        return memory_dir

    @pytest.fixture
    def library(self, temp_memory_dir):
        return PatternLibrary(memory_dir=temp_memory_dir)

    def test_get_learnings_summary(self, library):
        """Should return full LEARNINGS.md content."""
        content = library.get_learnings_summary()
        assert "Autopilot Learnings" in content
        assert "Videos produced: 5" in content
        assert "Red/yellow color scheme" in content

    def test_get_learnings_empty_dir(self, tmp_path):
        """Should return empty string if file doesn't exist."""
        library = PatternLibrary(memory_dir=tmp_path)
        assert library.get_learnings_summary() == ""

    def test_get_thumbnail_patterns_proven(self, library):
        """Should parse proven thumbnail elements."""
        patterns = library.get_thumbnail_patterns(status="proven")
        assert len(patterns) >= 1
        assert any(p.element == "red_yellow_combo" for p in patterns)

    def test_get_thumbnail_anti_patterns(self, library):
        """Should parse anti-patterns."""
        patterns = library.get_thumbnail_patterns(status="anti")
        assert len(patterns) >= 1
        assert any(p.element == "blue_background" for p in patterns)

    def test_get_title_patterns_proven(self, library):
        """Should parse proven title formulas."""
        patterns = library.get_title_patterns(status="proven")
        assert len(patterns) >= 1
        assert any(p.formula == "question" for p in patterns)

    def test_is_proven_element(self, library):
        """Should check if element is proven."""
        assert library.is_proven_element("red_yellow_combo", "thumbnail") is True
        assert library.is_proven_element("unknown_element", "thumbnail") is False

    def test_is_anti_pattern(self, library):
        """Should check if element is anti-pattern."""
        assert library.is_anti_pattern("blue_background", "thumbnail") is True
        assert library.is_anti_pattern("red_yellow_combo", "thumbnail") is False
