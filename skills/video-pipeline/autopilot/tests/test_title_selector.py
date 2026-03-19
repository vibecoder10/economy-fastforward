"""Tests for title selector."""

import pytest
from unittest.mock import Mock
from autopilot.analysis.title_selector import TitleSelector, ScoredTitle
from autopilot.learning.pattern_library import PatternLibrary, TitlePattern


class TestTitleSelector:
    """Test suite for title selection."""

    @pytest.fixture
    def mock_pattern_library(self):
        """Mock pattern library with some proven patterns."""
        mock = Mock(spec=PatternLibrary)

        # Proven patterns
        proven = [
            TitlePattern(formula="question", description="End with question mark", status="proven"),
            TitlePattern(formula="number", description="Include specific numbers", status="proven"),
        ]
        # Anti patterns
        anti = [
            TitlePattern(formula="all_lowercase", description="All lowercase", status="anti"),
        ]

        mock.get_title_patterns.side_effect = lambda status=None: {
            "proven": proven,
            "anti": anti,
            None: proven + anti
        }.get(status, [])

        return mock

    @pytest.fixture
    def selector(self, mock_pattern_library):
        return TitleSelector(pattern_library=mock_pattern_library)

    def test_score_title_with_question(self, selector):
        """Question titles should score higher."""
        scored = selector.score_title("Why Is China Collapsing?")

        assert scored.score > 0
        assert "question" in [p.lower() for p in scored.matched_patterns]

    def test_score_title_with_number(self, selector):
        """Titles with numbers should score higher."""
        scored = selector.score_title("The $3 Trillion Dollar Trap")

        assert scored.score > 0
        assert any("number" in p.lower() for p in scored.matched_patterns)

    def test_score_title_multiple_patterns(self, selector):
        """Titles matching multiple patterns should score highest."""
        # Both question AND number
        multi = selector.score_title("Why Did 47 Countries Just Abandon the Dollar?")
        # Just question
        single = selector.score_title("Why Is the Dollar Falling?")

        assert multi.score > single.score

    def test_penalize_anti_pattern(self, selector):
        """Anti-pattern titles should score lower."""
        normal = selector.score_title("China's Economic Collapse")
        lowercase = selector.score_title("china's economic collapse")

        assert normal.score > lowercase.score

    def test_competitor_similarity_bonus(self, selector):
        """Similar structure to competitor should add points."""
        competitor = "Why China's Economy Is Doomed"
        similar = selector.score_title("Why Russia's Economy Is Failing", competitor_title=competitor)
        different = selector.score_title("The End of Russian Power", competitor_title=competitor)

        # Similar structure (Why X's Y Is Z) should score higher
        assert similar.score >= different.score

    def test_select_best_from_variants(self, selector):
        """Should select highest-scoring variant."""
        variants = [
            "China Economic News",  # boring
            "Why Is China Collapsing?",  # question
            "The $3T Dollar Trap: China's Crisis",  # number
        ]

        best = selector.select_best(variants)

        assert best is not None
        # Should pick one with patterns
        assert "?" in best.title or "$" in best.title

    def test_select_best_with_min_score(self, selector):
        """Should return None if no variant meets threshold."""
        variants = [
            "news update",  # lowercase, boring
            "another thing",  # lowercase, boring
        ]

        best = selector.select_best(variants, min_score=50)

        # May or may not pass depending on scoring - test the mechanic
        assert best is None or best.score >= 50

    def test_detect_question_pattern(self, selector):
        """Should detect question pattern."""
        patterns = selector.detect_patterns("Why Is This Happening?")
        assert "question" in patterns

    def test_detect_number_pattern(self, selector):
        """Should detect number pattern."""
        patterns = selector.detect_patterns("The 5 Reasons Everything Failed")
        assert "number" in patterns

    def test_detect_caps_emphasis(self, selector):
        """Should detect caps emphasis."""
        patterns = selector.detect_patterns("China's MASSIVE Problem")
        assert "caps_emphasis" in patterns

    def test_scored_title_has_reasoning(self, selector):
        """ScoredTitle should include reasoning."""
        scored = selector.score_title("Why Did 47 Countries Abandon It?")

        assert scored.reasoning is not None
        assert len(scored.reasoning) > 0
