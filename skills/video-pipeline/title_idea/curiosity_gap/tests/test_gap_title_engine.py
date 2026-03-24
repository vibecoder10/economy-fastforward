"""Tests for gap title engine."""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch, Mock
from title_idea.curiosity_gap.structures import CuriosityStructure


def run_async(coro):
    """Helper to run async coroutines in sync tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestGeneratedTitle:
    """Test suite for GeneratedTitle dataclass."""

    def test_generated_title_creation(self):
        """Should create GeneratedTitle with all fields."""
        from title_idea.curiosity_gap.gap_title_engine import GeneratedTitle

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
        from title_idea.curiosity_gap.gap_title_engine import ScoredStructure

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
        from title_idea.curiosity_gap.gap_title_engine import ScoredStructure

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
        from title_idea.curiosity_gap.gap_title_engine import score_structures

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
        from title_idea.curiosity_gap.gap_title_engine import score_structures

        scores = score_structures(sample_story_context)

        confidences = [s.confidence for s in scores]
        assert confidences == sorted(confidences, reverse=True)

    def test_waste_story_scores_hidden_flaw_highest(self, sample_story_context):
        """Story about waste should score hidden_flaw highest."""
        from title_idea.curiosity_gap.gap_title_engine import score_structures

        scores = score_structures(sample_story_context)

        # hidden_flaw should be among top 2 for this waste story
        top_structures = [s.structure for s in scores[:2]]
        assert CuriosityStructure.HIDDEN_FLAW in top_structures


class TestMFFallback:
    """Test suite for MF formula fallback."""

    def test_mf_formulas_exist(self):
        """Should have 3 MF fallback formulas defined."""
        from title_idea.curiosity_gap.gap_title_engine import MF_FORMULAS

        assert len(MF_FORMULAS) >= 3
        assert "MF-0" in MF_FORMULAS or 0 in MF_FORMULAS

    def test_get_viable_structures_filters_by_floor(self):
        """Should filter structures below confidence floor."""
        from title_idea.curiosity_gap.gap_title_engine import (
            get_viable_structures,
            ScoredStructure,
            CONFIDENCE_FLOOR,
        )

        scores = [
            ScoredStructure(CuriosityStructure.HIDDEN_FLAW, 75, "high"),
            ScoredStructure(CuriosityStructure.TIME_BOMB, 55, "low"),
            ScoredStructure(CuriosityStructure.ASYMMETRIC_DG, 65, "mid"),
        ]

        viable = get_viable_structures(scores)

        # Only structures >= 60 should pass
        assert len(viable) == 2
        assert all(s.confidence >= CONFIDENCE_FLOOR for s in viable)

    def test_get_mf_fallback_count(self):
        """Should calculate how many MF fallbacks needed."""
        from title_idea.curiosity_gap.gap_title_engine import get_mf_fallback_count

        # If 2 viable structures, need 1 MF fallback
        assert get_mf_fallback_count(viable_count=2, target=3) == 1
        # If 1 viable, need 2 MF
        assert get_mf_fallback_count(viable_count=1, target=3) == 2
        # If 0 viable, need 3 MF
        assert get_mf_fallback_count(viable_count=0, target=3) == 3
        # If 3+ viable, need 0 MF
        assert get_mf_fallback_count(viable_count=3, target=3) == 0
        assert get_mf_fallback_count(viable_count=5, target=3) == 0


class TestGenerateTitles:
    """Test suite for title generation."""

    @pytest.fixture
    def sample_story(self):
        return {
            "hook": "Saudi Arabia spent $100 billion on pipelines that now sit empty.",
            "thesis": "The kingdom's bet on being an oil transit hub has failed.",
            "facts": [
                "NEOM pipeline: $500M spent, 0% utilized",
                "Total waste: estimated $100B",
            ],
        }

    @pytest.fixture
    def mock_claude_response(self):
        """Mock Claude response for title generation."""
        return {
            "titles": [
                {
                    "text": "The $100B Mistake Saudi Arabia Is Hiding",
                    "structure": "hidden_flaw",
                    "confidence": 85,
                    "thumbnail_text": "WORTHLESS PIPELINES",
                    "thumbnail_approach": "from_gap",
                    "reasoning": "Clear financial waste angle",
                },
                {
                    "text": "The 30-Year Trap Saudi Arabia Walked Into",
                    "structure": "time_bomb",
                    "confidence": 72,
                    "thumbnail_text": "CHECKMATE",
                    "thumbnail_approach": "from_gap",
                    "reasoning": "Long-term strategy failure",
                },
                {
                    "text": "Why Saudi Arabia Can't Escape Its Pipeline Trap",
                    "structure": "illusion_control",
                    "confidence": 65,
                    "thumbnail_text": "NO EXIT",
                    "thumbnail_approach": "from_hook",
                    "reasoning": "Personal stakes for kingdom",
                },
            ]
        }

    def test_generate_titles_returns_three(self, sample_story, mock_claude_response):
        """Should generate 3 titles by default."""
        from title_idea.curiosity_gap.gap_title_engine import GapTitleEngine

        engine = GapTitleEngine()

        async def run_test():
            with patch.object(engine, '_call_claude_for_titles', return_value=mock_claude_response):
                return await engine.generate_titles(sample_story)

        titles = run_async(run_test())

        assert len(titles) == 3
        assert all(isinstance(t.text, str) for t in titles)
        assert all(t.structure in CuriosityStructure for t in titles)

    def test_generate_titles_sorted_by_confidence(self, sample_story, mock_claude_response):
        """Titles should be sorted by confidence descending."""
        from title_idea.curiosity_gap.gap_title_engine import GapTitleEngine

        engine = GapTitleEngine()

        async def run_test():
            with patch.object(engine, '_call_claude_for_titles', return_value=mock_claude_response):
                return await engine.generate_titles(sample_story)

        titles = run_async(run_test())

        confidences = [t.structure_confidence for t in titles]
        assert confidences == sorted(confidences, reverse=True)

    def test_generate_titles_with_kill_switch_disabled(self, sample_story):
        """Should return empty list when kill switch is off."""
        from title_idea.curiosity_gap.gap_title_engine import GapTitleEngine

        engine = GapTitleEngine()

        async def run_test():
            return await engine.generate_titles(sample_story)

        with patch('title_idea.curiosity_gap.gap_title_engine.CURIOSITY_GAP_ENABLED', False):
            titles = run_async(run_test())

        assert titles == []


class TestMFIntegration:
    """Test suite for MF fallback integration."""

    @pytest.fixture
    def low_confidence_story(self):
        """Story that doesn't fit well into any structure."""
        return {
            "hook": "A small policy change happened.",
            "thesis": "The change is interesting.",
            "facts": ["It happened last week."],
        }

    def test_fallback_triggered_when_low_confidence(self, low_confidence_story):
        """Should use MF fallback when no structures score above floor."""
        from title_idea.curiosity_gap.gap_title_engine import GapTitleEngine, ScoredStructure

        engine = GapTitleEngine()

        # Mock Claude to return MF-style titles
        mock_response = {
            "titles": [
                {
                    "text": "How Policy Changed Everything",
                    "structure": "other",
                    "confidence": 45,
                    "thumbnail_text": "CHANGE COMING",
                    "thumbnail_approach": "from_gap",
                    "reasoning": "MF fallback applied",
                }
            ]
        }

        async def run_test():
            with patch.object(engine, '_call_claude_for_titles', return_value=mock_response):
                with patch('title_idea.curiosity_gap.gap_title_engine.score_structures') as mock_score:
                    # All structures score below floor
                    mock_score.return_value = [
                        ScoredStructure(CuriosityStructure.HIDDEN_FLAW, 40, "low"),
                        ScoredStructure(CuriosityStructure.TIME_BOMB, 35, "low"),
                        ScoredStructure(CuriosityStructure.ASYMMETRIC_DG, 30, "low"),
                        ScoredStructure(CuriosityStructure.PARADIGM_SHIFT, 25, "low"),
                        ScoredStructure(CuriosityStructure.ILLUSION_CONTROL, 20, "low"),
                    ]

                    return await engine.generate_titles(low_confidence_story)

        titles = run_async(run_test())

        # Should still return titles via MF fallback
        assert isinstance(titles, list)
        assert len(titles) >= 1
