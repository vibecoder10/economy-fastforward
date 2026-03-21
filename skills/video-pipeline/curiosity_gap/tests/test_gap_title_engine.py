"""Tests for gap title engine."""

import pytest
from curiosity_gap.structures import CuriosityStructure


class TestGeneratedTitle:
    """Test suite for GeneratedTitle dataclass."""

    def test_generated_title_creation(self):
        """Should create GeneratedTitle with all fields."""
        from curiosity_gap.gap_title_engine import GeneratedTitle

        title = GeneratedTitle(
            text="The $100B Mistake Saudi Arabia Is Hiding",
            structure=CuriosityStructure.HIDDEN_FLAW,
            structure_confidence=78,
            thumbnail_text="WORTHLESS PIPELINES",
            thumbnail_approach="from_gap",
            reasoning="Story has clear financial waste angle...",
            source_patterns=["competitor:rec123"],
            competitor_video_ids=["rec123"],
        )

        assert title.text == "The $100B Mistake Saudi Arabia Is Hiding"
        assert title.structure == CuriosityStructure.HIDDEN_FLAW
        assert title.structure_confidence == 78
        assert title.thumbnail_text == "WORTHLESS PIPELINES"
        assert title.thumbnail_approach == "from_gap"


class TestScoredStructure:
    """Test suite for ScoredStructure dataclass."""

    def test_scored_structure_creation(self):
        """Should create ScoredStructure with confidence and reasoning."""
        from curiosity_gap.gap_title_engine import ScoredStructure

        scored = ScoredStructure(
            structure=CuriosityStructure.HIDDEN_FLAW,
            confidence=85,
            reasoning="Story has $100B waste element",
        )

        assert scored.structure == CuriosityStructure.HIDDEN_FLAW
        assert scored.confidence == 85
        assert scored.reasoning == "Story has $100B waste element"

    def test_scored_structure_ordering(self):
        """Should compare by confidence for sorting."""
        from curiosity_gap.gap_title_engine import ScoredStructure

        high = ScoredStructure(
            structure=CuriosityStructure.HIDDEN_FLAW,
            confidence=85,
            reasoning="high",
        )
        low = ScoredStructure(
            structure=CuriosityStructure.TIME_BOMB,
            confidence=55,
            reasoning="low",
        )

        sorted_list = sorted([low, high], key=lambda s: s.confidence, reverse=True)
        assert sorted_list[0].confidence == 85
        assert sorted_list[1].confidence == 55
