"""Score idea candidates using weighted signals."""

import logging
import math
import re
from dataclasses import dataclass, field
from typing import List, Optional, TYPE_CHECKING
from autopilot.core.config_parser import AutopilotConfig

if TYPE_CHECKING:
    from autopilot.learning.pattern_library import PatternLibrary

logger = logging.getLogger(__name__)


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
    angle: Optional[str] = None  # angle_type from theme extraction


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

    # CTR thresholds for scoring
    STRONG_CTR = 4.0  # Topics with avg CTR >= this get high scores
    WEAK_CTR = 2.5    # Topics with avg CTR <= this get low scores

    def __init__(
        self,
        config: AutopilotConfig,
        pattern_library: Optional["PatternLibrary"] = None,
    ):
        """Initialize scorer with config weights.

        Args:
            config: Autopilot configuration with weights
            pattern_library: Optional PatternLibrary for learned patterns
        """
        self.config = config
        self.weights = config.weights
        self._pattern_library = pattern_library

        # channel_momentum / retention_patterns are unimplemented placeholder
        # scorers (see _score_channel_momentum / _score_retention_patterns).
        # Surface it once per cycle in the cron log rather than silently
        # letting a stub weight influence real production decisions.
        for stub_weight in ("channel_momentum", "retention_patterns"):
            if getattr(self.weights, stub_weight, 0.0) != 0.0:
                logger.warning(
                    "ConfidenceScorer: %s has weight %.2f but its scorer is "
                    "unimplemented (always returns 50.0) - see C32. "
                    "Expected 0.0 in autopilot_program.md until it's wired.",
                    stub_weight, getattr(self.weights, stub_weight),
                )

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

    def _score_topic_fit(self, topic: Optional[str], angle: Optional[str] = None) -> tuple[float, Optional[str]]:
        """Score based on topic fit for our channel (0-100).

        Cross-references with topic_performance.md to find topics
        that have historically performed well for THIS channel.

        Args:
            topic: Topic category (e.g., "geopolitics", "economy")
            angle: Angle type (e.g., "hidden_truth", "warning")

        Returns:
            Tuple of (score, reasoning string or None)
        """
        if self._pattern_library is None or not topic:
            return 50.0, None

        # Check topic performance
        topic_perf = self._pattern_library.get_topic_performance()
        topic_lower = topic.lower()

        if topic_lower in topic_perf:
            perf = topic_perf[topic_lower]
            if perf.sample_size >= 1:
                # Score based on historical CTR
                if perf.avg_ctr >= self.STRONG_CTR:
                    score = 70.0 + min(30.0, (perf.avg_ctr - self.STRONG_CTR) * 10)
                    return score, f"Topic '{topic}' strong (CTR {perf.avg_ctr:.1f}%, n={perf.sample_size})"
                elif perf.avg_ctr <= self.WEAK_CTR:
                    score = 30.0 - min(20.0, (self.WEAK_CTR - perf.avg_ctr) * 10)
                    return max(10.0, score), f"Topic '{topic}' weak (CTR {perf.avg_ctr:.1f}%, n={perf.sample_size})"
                else:
                    # Neutral range
                    return 50.0, f"Topic '{topic}' neutral (CTR {perf.avg_ctr:.1f}%, n={perf.sample_size})"

        # Check angle performance if topic not found
        if angle:
            angle_perf = self._pattern_library.get_angle_performance()
            angle_lower = angle.lower()
            if angle_lower in angle_perf:
                perf = angle_perf[angle_lower]
                if perf.sample_size >= 1 and perf.avg_ctr >= self.STRONG_CTR:
                    return 65.0, f"Angle '{angle}' strong (CTR {perf.avg_ctr:.1f}%)"

        return 50.0, None

    def _score_channel_momentum(self, competitor_title: Optional[str]) -> float:
        """Score based on competitor channel momentum (0-100).

        NOT IMPLEMENTED: there is no data pipeline that tracks a competitor
        channel's VPH trend over time (competitor_scraper stores point-in-time
        snapshots, not a time series). Always returns the neutral midpoint.
        `channel_momentum` is pinned to weight 0.0 in `autopilot_program.md`
        (see C32, docs/reports/2026-07-17-storyengine-agent-audit-findings.md
        §3.2) so this constant does not silently inflate every candidate's
        score. The method is kept so a real implementation only has to change
        this function + flip the weight back on - it is not dead code, it is
        an intentionally-disconnected seam.
        """
        return 50.0

    def _score_retention_patterns(self, topic: Optional[str]) -> float:
        """Score based on our retention on similar topics (0-100).

        NOT IMPLEMENTED: `topic_performance.md` (parsed by PatternLibrary)
        only ever records CTR, never retention - because the upstream
        writer (`learning_extractor.run_daily_extraction`) that would
        populate it is itself unwired (see C32). Always returns the neutral
        midpoint. `retention_patterns` is pinned to weight 0.0 in
        `autopilot_program.md` for the same reason as `_score_channel_momentum`
        above - fix the data source first, then this function, then the weight.
        """
        return 50.0

    def _score_title_formula(self, title: str) -> tuple[float, Optional[str]]:
        """Score based on title formula patterns (0-100).

        Cross-references with title_patterns.md to identify
        structural patterns that work for this channel.

        Args:
            title: Video title to analyze

        Returns:
            Tuple of (score, reasoning string or None)
        """
        score = 50.0
        matches = []

        # Check for structural patterns
        is_question = title.rstrip().endswith('?')
        has_number = bool(re.search(r'\d+', title))
        has_caps = bool(re.search(r'\b[A-Z]{2,}\b', title))
        has_how = title.lower().startswith('how ')
        has_why = title.lower().startswith('why ')

        if self._pattern_library is None:
            # No library, use heuristic scoring
            if is_question:
                score += 5
                matches.append("question format")
            if has_number:
                score += 3
            return min(100.0, score), None if not matches else f"Title uses {', '.join(matches)}"

        # Check against learned patterns
        title_notes = self._pattern_library.get_title_notes()
        if title_notes:
            # Aggregate pattern performance from notes
            pattern_ctrs = {}
            for note in title_notes:
                pattern = note['pattern']
                if pattern not in pattern_ctrs:
                    pattern_ctrs[pattern] = []
                pattern_ctrs[pattern].append(note['ctr'])

            # Check if current title matches known patterns
            for pattern, ctrs in pattern_ctrs.items():
                avg_ctr = sum(ctrs) / len(ctrs)
                pattern_lower = pattern.lower()

                if 'question' in pattern_lower and is_question:
                    if avg_ctr >= self.STRONG_CTR:
                        score += 15
                        matches.append(f"question format (CTR {avg_ctr:.1f}%)")
                    elif avg_ctr <= self.WEAK_CTR:
                        score -= 10
                        matches.append(f"question format weak (CTR {avg_ctr:.1f}%)")

                if 'number' in pattern_lower and has_number:
                    if avg_ctr >= self.STRONG_CTR:
                        score += 10
                        matches.append(f"number in title (CTR {avg_ctr:.1f}%)")

                if 'caps' in pattern_lower and has_caps:
                    if avg_ctr >= self.STRONG_CTR:
                        score += 8
                        matches.append(f"caps emphasis (CTR {avg_ctr:.1f}%)")

        # Check proven formulas
        proven = self._pattern_library.get_title_patterns(status="proven")
        for p in proven:
            formula_lower = p.formula.lower()
            if 'question' in formula_lower and is_question:
                score += 10
                if "question" not in str(matches):
                    matches.append("proven question formula")
            if 'how' in formula_lower and has_how:
                score += 8
                matches.append("proven 'How' formula")
            if 'why' in formula_lower and has_why:
                score += 8
                matches.append("proven 'Why' formula")

        # Check anti-patterns
        anti = self._pattern_library.get_title_patterns(status="anti")
        for p in anti:
            formula_lower = p.formula.lower()
            if 'lowercase' in formula_lower and title == title.lower():
                score -= 15
                matches.append("AVOID: all lowercase")

        reasoning = f"Title patterns: {', '.join(matches)}" if matches else None
        return min(100.0, max(0.0, score)), reasoning

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

        # Topic fit (with learned patterns)
        topic_fit_score, topic_reason = self._score_topic_fit(
            candidate.topic, candidate.angle
        )
        components['topic_channel_fit'] = topic_fit_score
        if topic_reason:
            reasoning.append(topic_reason)

        momentum_score = self._score_channel_momentum(candidate.competitor_title)
        components['channel_momentum'] = momentum_score

        retention_score = self._score_retention_patterns(candidate.topic)
        components['retention_patterns'] = retention_score

        # Title formula (with learned patterns)
        title_score, title_reason = self._score_title_formula(candidate.title)
        components['title_formula'] = title_score
        if title_reason:
            reasoning.append(title_reason)

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
