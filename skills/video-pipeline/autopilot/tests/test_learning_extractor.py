# skills/video-pipeline/autopilot/tests/test_learning_extractor.py
"""Tests for learning extractor."""

import pytest
from autopilot.learning.learning_extractor import (
    LearningExtractor,
    ExtractedLearning,
    ExperimentResult,
    ThemeData,
)
from autopilot.monitoring.early_warning import CTRVerdict


class TestLearningExtractor:
    """Test suite for learning extractor."""

    @pytest.fixture
    def extractor(self):
        return LearningExtractor()

    def test_extract_thumbnail_color_pattern(self, extractor):
        """'red background with yellow text' should extract red_yellow_color_scheme."""
        learnings = extractor.extract_thumbnail_learnings(
            video_title="China's Collapse",
            ctr=4.5,
            thumbnail_override="Red gradient background transitioning to darker red. Yellow text with bold outline.",
        )

        patterns = [l.pattern for l in learnings]
        assert "red_yellow_color_scheme" in patterns

        # Find the specific learning
        color_learning = next(l for l in learnings if l.pattern == "red_yellow_color_scheme")
        assert color_learning.category == "thumbnail"
        assert color_learning.ctr == 4.5

    def test_extract_thumbnail_composition_pattern(self, extractor):
        """'face on left side' should extract face_left_composition."""
        learnings = extractor.extract_thumbnail_learnings(
            video_title="Putin's Next Move",
            ctr=3.8,
            thumbnail_override="Leader portrait with face on left side of frame, text on right.",
        )

        patterns = [l.pattern for l in learnings]
        assert "face_left_composition" in patterns

        comp_learning = next(l for l in learnings if l.pattern == "face_left_composition")
        assert comp_learning.category == "thumbnail"

    def test_extract_title_question_pattern(self, extractor):
        """'Why Is China Failing?' should extract question_format."""
        learnings = extractor.extract_title_learnings(
            video_title="Why Is China Failing?",
            ctr=5.2,
        )

        patterns = [l.pattern for l in learnings]
        assert "question_format" in patterns

        question_learning = next(l for l in learnings if l.pattern == "question_format")
        assert question_learning.category == "title"
        assert question_learning.ctr == 5.2

    def test_extract_title_number_pattern(self, extractor):
        """'3 Reasons Why...' should extract number_in_title."""
        learnings = extractor.extract_title_learnings(
            video_title="3 Reasons Why Russia Will Fail",
            ctr=4.0,
        )

        patterns = [l.pattern for l in learnings]
        assert "number_in_title" in patterns

    def test_verdict_affects_confidence(self, extractor):
        """KEEP verdict should give 60% confidence, DISCARD should give 40%."""
        # High CTR (KEEP verdict)
        keep_learnings = extractor.extract_title_learnings(
            video_title="Why Is This Happening?",
            ctr=5.0,  # >= 4.0 = KEEP
        )
        keep_learning = next(l for l in keep_learnings if l.pattern == "question_format")
        assert keep_learning.verdict == CTRVerdict.KEEP
        assert keep_learning.confidence == 60.0

        # Low CTR (DISCARD verdict)
        discard_learnings = extractor.extract_title_learnings(
            video_title="Why Did This Fail?",
            ctr=2.0,  # <= 2.5 = DISCARD
        )
        discard_learning = next(l for l in discard_learnings if l.pattern == "question_format")
        assert discard_learning.verdict == CTRVerdict.DISCARD
        assert discard_learning.confidence == 40.0

    def test_extract_all_combines_learnings(self, extractor):
        """Full extraction should combine thumbnail and title patterns."""
        result = extractor.extract_all(
            video_title="Why Is China's $3T TRAP Failing?",
            ctr=4.8,
            thumbnail_override="Red background with yellow bold caps text. Face positioned on left.",
            modeled_from="Competitor Video: China Analysis",
        )

        assert isinstance(result, ExperimentResult)
        assert result.video_title == "Why Is China's $3T TRAP Failing?"
        assert result.actual_ctr == 4.8
        assert result.verdict == CTRVerdict.KEEP
        assert result.modeled_from == "Competitor Video: China Analysis"

        # Should have learnings from both thumbnail and title
        categories = {l.category for l in result.learnings}
        assert "thumbnail" in categories
        assert "title" in categories

        # Should have multiple patterns
        patterns = [l.pattern for l in result.learnings]
        assert "red_yellow_color_scheme" in patterns
        assert "face_left_composition" in patterns
        assert "question_format" in patterns
        assert "caps_emphasis" in patterns  # TRAP is in caps

    def test_extract_theme_learnings(self, extractor):
        """Theme extraction should create topic, angle, and hook learnings."""
        theme_data = ThemeData(
            primary_theme="US-China conflict",
            secondary_themes=["trade war", "technology"],
            angle_type="hidden_truth",
            emotional_hooks=["curiosity_gap", "fear"],
            topic_category="geopolitics",
            title_formula="How [Power] [Verb] the [Event]",
            formula_variables={"power": "US", "verb": "Engineered", "event": "Trade War"},
        )

        learnings = extractor.extract_theme_learnings(
            video_title="How the US Engineered the Trade War",
            ctr=5.5,
            theme_data=theme_data,
        )

        # Should have topic, angle, hook, and formula learnings
        categories = {l.category for l in learnings}
        assert "topic" in categories
        assert "angle" in categories
        assert "hook" in categories
        assert "formula" in categories

        # Check specific patterns
        patterns = [l.pattern for l in learnings]
        assert "geopolitics" in patterns  # topic_category
        assert "hidden_truth" in patterns  # angle_type
        assert "curiosity_gap" in patterns  # emotional hook
        assert "fear" in patterns  # emotional hook

    def test_extract_all_with_theme_data(self, extractor):
        """Full extraction with theme data should include all categories."""
        theme_data = ThemeData(
            primary_theme="China economy",
            angle_type="warning",
            emotional_hooks=["fear"],
            topic_category="economy",
            title_formula="Why [Entity] Will [Outcome]",
        )

        result = extractor.extract_all(
            video_title="Why China Will Collapse?",
            ctr=4.2,
            thumbnail_override="Red background with yellow text",
            modeled_from="Competitor video",
            theme_data=theme_data,
        )

        # Should have all categories
        categories = {l.category for l in result.learnings}
        assert "thumbnail" in categories
        assert "title" in categories
        assert "topic" in categories
        assert "angle" in categories

        # Title formula should be set from theme_data
        assert result.title_formula == "Why [Entity] Will [Outcome]"

    def test_normalize_formula(self, extractor):
        """Formula normalization should create consistent pattern names."""
        # Test typical formula
        normalized = extractor._normalize_formula("How [Power] [Verb] the [Event]")
        assert normalized == "how_power_verb_the_event"

        # Test empty formula
        assert extractor._normalize_formula("") == ""
        assert extractor._normalize_formula(None) == ""
