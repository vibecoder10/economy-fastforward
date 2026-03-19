"""Tests for confidence scorer."""

import pytest
from datetime import datetime, timezone, timedelta
from autopilot.core.confidence_scorer import (
    ConfidenceScorer,
    IdeaCandidate,
    ScoredIdea,
)
from autopilot.core.config_parser import AutopilotConfig, WeightsConfig


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
