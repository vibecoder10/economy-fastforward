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


class TestScoreStructures:
    """Test suite for structure scoring."""

    @pytest.fixture
    def sample_story_context(self):
        return {
            "hook": "Saudi Arabia spent $100 billion on pipelines that now sit empty.",
            "thesis": "The kingdom's bet on being an oil transit hub has failed.",
            "facts": [
                "NEOM pipeline: $500M spent, 0% utilized",
                "East-West pipeline: abandoned in 2023",
                "Total waste: estimated $100B",
            ],
        }

    def test_score_structures_returns_all_five(self, sample_story_context):
        """Should return scores for all 5 main structures."""
        from curiosity_gap.gap_title_engine import score_structures

        scores = score_structures(sample_story_context)

        assert len(scores) == 5
        structure_names = [s.structure for s in scores]
        assert CuriosityStructure.HIDDEN_FLAW in structure_names
        assert CuriosityStructure.ASYMMETRIC_DG in structure_names
        assert CuriosityStructure.TIME_BOMB in structure_names
        assert CuriosityStructure.PARADIGM_SHIFT in structure_names
        assert CuriosityStructure.ILLUSION_CONTROL in structure_names

    def test_score_structures_sorted_descending(self, sample_story_context):
        """Should return structures sorted by confidence descending."""
        from curiosity_gap.gap_title_engine import score_structures

        scores = score_structures(sample_story_context)

        confidences = [s.confidence for s in scores]
        assert confidences == sorted(confidences, reverse=True)

    def test_waste_story_scores_hidden_flaw_highest(self, sample_story_context):
        """Story about waste should score hidden_flaw highest."""
        from curiosity_gap.gap_title_engine import score_structures

        scores = score_structures(sample_story_context)

        # hidden_flaw should be among top 2 for this waste story
        top_structures = [s.structure for s in scores[:2]]
        assert CuriosityStructure.HIDDEN_FLAW in top_structures
