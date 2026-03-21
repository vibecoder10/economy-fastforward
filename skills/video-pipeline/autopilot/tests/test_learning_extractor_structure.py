"""Tests for curiosity gap structure learning extraction."""

import pytest
from autopilot.learning.learning_extractor import (
    LearningExtractor,
    ExtractedLearning,
)
from autopilot.monitoring.early_warning import CTRVerdict


class TestStructureLearningExtraction:
    """Test suite for structure learning extraction."""

    @pytest.fixture
    def extractor(self):
        return LearningExtractor()

    def test_extract_structure_learning_keep(self, extractor):
        """Should extract structure learning with KEEP verdict for high CTR."""
        learnings = extractor.extract_structure_learnings(
            video_title="The $100B Mistake Saudi Arabia Is Hiding",
            ctr=5.2,
            structure="hidden_flaw",
            structure_confidence=78,
        )

        assert len(learnings) == 1
        learning = learnings[0]
        assert learning.category == "structure"
        assert learning.pattern == "hidden_flaw"
        assert learning.verdict == CTRVerdict.KEEP
        assert learning.ctr == 5.2
        assert "hidden_flaw" in learning.evidence

    def test_extract_structure_learning_discard(self, extractor):
        """Should extract structure learning with DISCARD verdict for low CTR."""
        learnings = extractor.extract_structure_learnings(
            video_title="The Time Bomb In Iran's Strategy",
            ctr=2.1,
            structure="time_bomb",
            structure_confidence=65,
        )

        assert len(learnings) == 1
        learning = learnings[0]
        assert learning.category == "structure"
        assert learning.pattern == "time_bomb"
        assert learning.verdict == CTRVerdict.DISCARD

    def test_extract_structure_learning_none_structure(self, extractor):
        """Should return empty list when no structure provided."""
        learnings = extractor.extract_structure_learnings(
            video_title="Some Video",
            ctr=4.0,
            structure=None,
            structure_confidence=None,
        )
        assert len(learnings) == 0

    def test_extract_structure_learning_other(self, extractor):
        """Should extract 'other' structure for unclassified titles."""
        learnings = extractor.extract_structure_learnings(
            video_title="5 Days Until China's Dollar Deadline",
            ctr=4.5,
            structure="other",
            structure_confidence=45,
        )

        assert len(learnings) == 1
        assert learnings[0].pattern == "other"

    def test_extract_all_includes_structure(self, extractor):
        """extract_all should include structure learnings when present."""
        result = extractor.extract_all(
            video_title="The $100B Mistake",
            ctr=5.0,
            thumbnail_override=None,
            modeled_from=None,
            theme_data=None,
            structure="hidden_flaw",
            structure_confidence=80,
        )

        # Should have structure learning
        structure_learnings = [l for l in result.learnings if l.category == "structure"]
        assert len(structure_learnings) == 1
        assert structure_learnings[0].pattern == "hidden_flaw"
