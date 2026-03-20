"""Tests for confidence scorer."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock
from autopilot.core.confidence_scorer import (
    ConfidenceScorer,
    IdeaCandidate,
    ScoredIdea,
)
from autopilot.core.config_parser import AutopilotConfig, WeightsConfig
from autopilot.learning.pattern_library import TopicPerformance


class TestConfidenceScorer:
    """Test suite for confidence scoring."""

    @pytest.fixture
    def config(self):
        return AutopilotConfig()

    @pytest.fixture
    def scorer(self, config):
        return ConfidenceScorer(config)

    def test_score_single_idea(self, scorer):
        """Should score an idea based on weighted signals."""
        candidate = IdeaCandidate(
            record_id="rec123",
            title="China's $3T Dollar Trap",
            source_type="competitor",
            competitor_vph=150.0,
            competitor_title="China's Economic Collapse",
            hours_old=24,
        )

        scored = scorer.score(candidate)

        assert scored.score > 0
        assert scored.score <= 100
        assert scored.candidate == candidate
        assert len(scored.reasoning) > 0

    def test_higher_vph_scores_higher(self, scorer):
        """Ideas from higher VPH competitors should score higher."""
        low_vph = IdeaCandidate(
            record_id="rec1",
            title="Low VPH Idea",
            source_type="competitor",
            competitor_vph=20.0,
            hours_old=24,
        )
        high_vph = IdeaCandidate(
            record_id="rec2",
            title="High VPH Idea",
            source_type="competitor",
            competitor_vph=200.0,
            hours_old=24,
        )

        low_score = scorer.score(low_vph)
        high_score = scorer.score(high_vph)

        assert high_score.score > low_score.score

    def test_fresher_ideas_score_higher(self, scorer):
        """Fresher ideas should score higher."""
        old = IdeaCandidate(
            record_id="rec1",
            title="Old Idea",
            source_type="competitor",
            competitor_vph=100.0,
            hours_old=168,  # 7 days
        )
        fresh = IdeaCandidate(
            record_id="rec2",
            title="Fresh Idea",
            source_type="competitor",
            competitor_vph=100.0,
            hours_old=12,  # 12 hours
        )

        old_score = scorer.score(old)
        fresh_score = scorer.score(fresh)

        assert fresh_score.score > old_score.score

    def test_rank_candidates(self, scorer):
        """Should rank candidates by score descending."""
        candidates = [
            IdeaCandidate(record_id="low", title="Low", source_type="competitor", competitor_vph=20.0, hours_old=72),
            IdeaCandidate(record_id="high", title="High", source_type="competitor", competitor_vph=200.0, hours_old=12),
            IdeaCandidate(record_id="mid", title="Mid", source_type="competitor", competitor_vph=100.0, hours_old=24),
        ]

        ranked = scorer.rank(candidates)

        assert len(ranked) == 3
        assert ranked[0].candidate.record_id == "high"
        assert ranked[0].score > ranked[1].score > ranked[2].score

    def test_filter_by_threshold(self, scorer):
        """Should filter out ideas below min_confidence_score."""
        candidates = [
            IdeaCandidate(record_id="good", title="Good", source_type="competitor", competitor_vph=150.0, hours_old=12),
            IdeaCandidate(record_id="bad", title="Bad", source_type="competitor", competitor_vph=10.0, hours_old=168),
        ]

        ranked = scorer.rank(candidates, min_score=50)

        # Only good idea should pass threshold
        assert all(s.score >= 50 for s in ranked)


class TestPatternBasedScoring:
    """Test pattern-based scoring with PatternLibrary."""

    @pytest.fixture
    def config(self):
        return AutopilotConfig()

    @pytest.fixture
    def mock_pattern_library(self):
        """Mock pattern library with sample performance data."""
        lib = Mock()
        lib.get_topic_performance.return_value = {
            'geopolitics': TopicPerformance(
                name='geopolitics',
                avg_ctr=5.2,
                sample_size=3,
                verdicts={'keep': 2, 'discard': 0, 'neutral': 1},
            ),
            'economy': TopicPerformance(
                name='economy',
                avg_ctr=2.1,
                sample_size=2,
                verdicts={'keep': 0, 'discard': 2, 'neutral': 0},
            ),
        }
        lib.get_angle_performance.return_value = {
            'hidden_truth': TopicPerformance(
                name='hidden_truth',
                avg_ctr=4.8,
                sample_size=2,
                verdicts={'keep': 2, 'discard': 0, 'neutral': 0},
            ),
        }
        lib.get_title_notes.return_value = [
            {'pattern': 'question_format', 'ctr': 5.5, 'verdict': 'keep', 'video_title': 'Test 1'},
            {'pattern': 'question_format', 'ctr': 4.8, 'verdict': 'keep', 'video_title': 'Test 2'},
        ]
        lib.get_title_patterns.return_value = []
        return lib

    def test_strong_topic_boosts_score(self, config, mock_pattern_library):
        """Strong topics should boost the topic_fit score."""
        scorer = ConfidenceScorer(config, pattern_library=mock_pattern_library)

        candidate = IdeaCandidate(
            record_id="rec1",
            title="Why NATO is Collapsing",
            source_type="competitor",
            competitor_vph=100.0,
            hours_old=24,
            topic="geopolitics",  # Strong topic (5.2% CTR)
        )

        scored = scorer.score(candidate)

        # Topic fit should be boosted above neutral 50
        assert scored.component_scores['topic_channel_fit'] > 50
        # Reasoning should mention the topic
        assert any('geopolitics' in r.lower() for r in scored.reasoning)

    def test_weak_topic_lowers_score(self, config, mock_pattern_library):
        """Weak topics should lower the topic_fit score."""
        scorer = ConfidenceScorer(config, pattern_library=mock_pattern_library)

        candidate = IdeaCandidate(
            record_id="rec1",
            title="Economy Basics",
            source_type="competitor",
            competitor_vph=100.0,
            hours_old=24,
            topic="economy",  # Weak topic (2.1% CTR)
        )

        scored = scorer.score(candidate)

        # Topic fit should be below neutral 50
        assert scored.component_scores['topic_channel_fit'] < 50

    def test_question_title_with_pattern_data(self, config, mock_pattern_library):
        """Question titles should be scored higher when pattern data shows success."""
        scorer = ConfidenceScorer(config, pattern_library=mock_pattern_library)

        question_title = IdeaCandidate(
            record_id="rec1",
            title="Why Is China Failing?",
            source_type="competitor",
            competitor_vph=100.0,
            hours_old=24,
        )
        statement_title = IdeaCandidate(
            record_id="rec2",
            title="China Is Failing",
            source_type="competitor",
            competitor_vph=100.0,
            hours_old=24,
        )

        q_scored = scorer.score(question_title)
        s_scored = scorer.score(statement_title)

        # Question format should score higher when pattern data shows it works
        assert q_scored.component_scores['title_formula'] > s_scored.component_scores['title_formula']

    def test_angle_provides_fallback_boost(self, config, mock_pattern_library):
        """When topic unknown, strong angle should still boost score."""
        scorer = ConfidenceScorer(config, pattern_library=mock_pattern_library)

        candidate = IdeaCandidate(
            record_id="rec1",
            title="What They Don't Tell You",
            source_type="competitor",
            competitor_vph=100.0,
            hours_old=24,
            topic="unknown_topic",  # Not in performance data
            angle="hidden_truth",    # But angle is strong
        )

        scored = scorer.score(candidate)

        # Should get angle boost even if topic unknown
        assert scored.component_scores['topic_channel_fit'] >= 50

    def test_no_pattern_library_returns_neutral(self, config):
        """Without pattern library, should return neutral scores."""
        scorer = ConfidenceScorer(config)  # No pattern library

        candidate = IdeaCandidate(
            record_id="rec1",
            title="Why Is China Failing?",
            source_type="competitor",
            competitor_vph=100.0,
            hours_old=24,
            topic="geopolitics",
        )

        scored = scorer.score(candidate)

        # Topic fit should be neutral without pattern data
        # But title_formula might get heuristic boost for question
        assert scored.component_scores['topic_channel_fit'] == 50.0
