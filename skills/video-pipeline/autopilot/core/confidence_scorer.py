"""Score idea candidates using weighted signals."""

import math
from dataclasses import dataclass, field
from typing import List, Optional
from autopilot.core.config_parser import AutopilotConfig


@dataclass
class IdeaCandidate:
    """A potential video idea to score."""
    record_id: str
    title: str
    source_type: str  # "competitor" or "discovery"
    competitor_vph: float = 0.0
    competitor_title: Optional[str] = None
    hours_old: float = 0.0
    topic: Optional[str] = None
    # Future: topic_fit_score, retention_history, etc.


@dataclass
class ScoredIdea:
    """An idea with its confidence score and reasoning."""
    candidate: IdeaCandidate
    score: float  # 0-100
    reasoning: List[str] = field(default_factory=list)
    component_scores: dict = field(default_factory=dict)


class ConfidenceScorer:
    """Score ideas using weighted signals from config."""

    # Normalization constants
    MAX_VPH = 500.0  # VPH above this gets max score
    MAX_HOURS = 168.0  # 7 days - older than this gets 0 freshness

    def __init__(self, config: AutopilotConfig):
        """Initialize scorer with config weights.

        Args:
            config: Autopilot configuration with weights
        """
        self.config = config
        self.weights = config.weights

    def _score_vph(self, vph: float) -> float:
        """Score based on competitor VPH (0-100).

        Higher VPH = more proven appeal.
        """
        if vph <= 0:
            return 0.0
        # Log scale to handle wide range
        # VPH 50 = 50, VPH 200 = 75, VPH 500 = 100
        normalized = min(1.0, math.log10(max(1, vph)) / math.log10(self.MAX_VPH))
        return normalized * 100

    def _score_freshness(self, hours_old: float) -> float:
        """Score based on idea freshness (0-100).

        Fresher = more timely.
        """
        if hours_old <= 0:
            return 100.0
        if hours_old >= self.MAX_HOURS:
            return 0.0
        # Linear decay
        return (1 - hours_old / self.MAX_HOURS) * 100

    def _score_topic_fit(self, topic: Optional[str]) -> float:
        """Score based on topic fit for our channel (0-100).

        TODO: Cross-reference with topic_performance.md
        For now, return neutral score.
        """
        # Placeholder - will be enhanced in Chunk 2 with memory
        return 50.0

    def _score_channel_momentum(self, competitor_title: Optional[str]) -> float:
        """Score based on competitor channel momentum (0-100).

        TODO: Track competitor channel trends over time
        For now, return neutral score.
        """
        # Placeholder
        return 50.0

    def _score_retention_patterns(self, topic: Optional[str]) -> float:
        """Score based on our retention on similar topics (0-100).

        TODO: Cross-reference with script_forensics.md (V2)
        For now, return neutral score.
        """
        # Placeholder
        return 50.0

    def _score_title_formula(self, title: str) -> float:
        """Score based on title formula patterns (0-100).

        TODO: Cross-reference with title_patterns.md
        For now, return neutral score.
        """
        # Placeholder
        return 50.0

    def score(self, candidate: IdeaCandidate) -> ScoredIdea:
        """Calculate confidence score for a candidate idea.

        Args:
            candidate: Idea to score

        Returns:
            ScoredIdea with score and reasoning
        """
        reasoning = []
        components = {}

        # Score each component
        vph_score = self._score_vph(candidate.competitor_vph)
        components['competitor_vph'] = vph_score
        reasoning.append(f"VPH {candidate.competitor_vph:.0f} → {vph_score:.0f}/100")

        freshness_score = self._score_freshness(candidate.hours_old)
        components['timing_freshness'] = freshness_score
        reasoning.append(f"Age {candidate.hours_old:.0f}h → {freshness_score:.0f}/100")

        topic_fit_score = self._score_topic_fit(candidate.topic)
        components['topic_channel_fit'] = topic_fit_score

        momentum_score = self._score_channel_momentum(candidate.competitor_title)
        components['channel_momentum'] = momentum_score

        retention_score = self._score_retention_patterns(candidate.topic)
        components['retention_patterns'] = retention_score

        title_score = self._score_title_formula(candidate.title)
        components['title_formula'] = title_score

        # Calculate weighted sum
        total_score = (
            vph_score * self.weights.competitor_vph +
            freshness_score * self.weights.timing_freshness +
            topic_fit_score * self.weights.topic_channel_fit +
            momentum_score * self.weights.channel_momentum +
            retention_score * self.weights.retention_patterns +
            title_score * self.weights.title_formula
        )

        return ScoredIdea(
            candidate=candidate,
            score=total_score,
            reasoning=reasoning,
            component_scores=components,
        )

    def rank(
        self,
        candidates: List[IdeaCandidate],
        min_score: Optional[float] = None,
    ) -> List[ScoredIdea]:
        """Score and rank candidates.

        Args:
            candidates: Ideas to rank
            min_score: Filter out ideas below this score (optional)

        Returns:
            Scored ideas sorted by score descending
        """
        scored = [self.score(c) for c in candidates]

        if min_score is not None:
            scored = [s for s in scored if s.score >= min_score]

        return sorted(scored, key=lambda s: s.score, reverse=True)

    def get_best(
        self,
        candidates: List[IdeaCandidate],
    ) -> Optional[ScoredIdea]:
        """Get the highest-scoring candidate.

        Args:
            candidates: Ideas to evaluate

        Returns:
            Best idea or None if none pass threshold
        """
        min_score = self.config.thresholds.min_confidence_score
        ranked = self.rank(candidates, min_score=min_score)
        return ranked[0] if ranked else None
