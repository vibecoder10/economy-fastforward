"""Select best title from variants using pattern memory."""

import re
from dataclasses import dataclass, field
from typing import List, Optional
from autopilot.learning.pattern_library import PatternLibrary


@dataclass
class ScoredTitle:
    """A title with its pattern score."""
    title: str
    score: float
    matched_patterns: List[str] = field(default_factory=list)
    avoided_antipatterns: List[str] = field(default_factory=list)
    penalties: List[str] = field(default_factory=list)
    reasoning: str = ""


class TitleSelector:
    """Score and select best title variant."""

    # Pattern detection regexes
    QUESTION_PATTERN = re.compile(r'\?$')
    NUMBER_PATTERN = re.compile(r'\d+')
    CAPS_PATTERN = re.compile(r'[A-Z]{2,}')
    URGENCY_WORDS = ["now", "just", "breaking", "urgent", "finally"]
    CURIOSITY_WORDS = ["secret", "hidden", "truth", "real", "actually"]

    # Scoring weights (per spec 8.6)
    PROVEN_PATTERN_BONUS = 2.0
    ANTI_PATTERN_PENALTY = -3.0
    COMPETITOR_SIMILARITY_BONUS = 1.0
    BASE_SCORE = 50.0  # Start at 50

    def __init__(self, pattern_library: Optional[PatternLibrary] = None):
        """Initialize selector.

        Args:
            pattern_library: Pattern library for memory queries
        """
        if pattern_library is None:
            pattern_library = PatternLibrary()
        self.patterns = pattern_library

    def detect_patterns(self, title: str) -> List[str]:
        """Detect which patterns a title matches.

        Args:
            title: Title to analyze

        Returns:
            List of pattern names detected
        """
        detected = []

        # Question pattern
        if self.QUESTION_PATTERN.search(title):
            detected.append("question")

        # Number pattern
        if self.NUMBER_PATTERN.search(title):
            detected.append("number")

        # Caps emphasis
        if self.CAPS_PATTERN.search(title):
            detected.append("caps_emphasis")

        # Urgency
        title_lower = title.lower()
        if any(word in title_lower for word in self.URGENCY_WORDS):
            detected.append("urgency")

        # Curiosity gap
        if any(word in title_lower for word in self.CURIOSITY_WORDS):
            detected.append("curiosity_gap")

        return detected

    def _detect_anti_patterns(self, title: str) -> List[str]:
        """Detect anti-patterns in a title.

        Args:
            title: Title to analyze

        Returns:
            List of anti-pattern names detected
        """
        detected = []

        # All lowercase
        if title == title.lower():
            detected.append("all_lowercase")

        # Too long (>70 chars)
        if len(title) > 70:
            detected.append("too_long")

        # No capital letters at all
        if not any(c.isupper() for c in title):
            detected.append("no_capitals")

        return detected

    def _calculate_competitor_similarity(self, title: str, competitor_title: str) -> float:
        """Calculate structural similarity to competitor title.

        Args:
            title: Our title
            competitor_title: Competitor's title

        Returns:
            Similarity score (0-1)
        """
        # Simple heuristics for structural similarity
        similarity = 0.0

        # Same start word pattern (Why/How/What/The)
        our_first = title.split()[0].lower() if title.split() else ""
        their_first = competitor_title.split()[0].lower() if competitor_title.split() else ""
        if our_first == their_first and our_first in ["why", "how", "what", "the"]:
            similarity += 0.5

        # Same ending pattern (? or :)
        if title[-1] == competitor_title[-1] and title[-1] in ["?", ":", "!"]:
            similarity += 0.3

        # Similar length (within 20%)
        len_ratio = len(title) / max(len(competitor_title), 1)
        if 0.8 <= len_ratio <= 1.2:
            similarity += 0.2

        return min(similarity, 1.0)

    def score_title(self, title: str, competitor_title: Optional[str] = None) -> ScoredTitle:
        """Score a single title against patterns.

        Args:
            title: Title to score
            competitor_title: Optional competitor title for similarity bonus

        Returns:
            ScoredTitle with score and reasoning
        """
        score = self.BASE_SCORE
        matched = []
        penalties = []
        reasoning_parts = []

        # Detect patterns
        detected = self.detect_patterns(title)

        # Get proven patterns from memory
        proven_patterns = self.patterns.get_title_patterns(status="proven")
        proven_names = [p.formula for p in proven_patterns]

        # Score proven patterns
        for pattern in detected:
            if pattern in proven_names:
                score += self.PROVEN_PATTERN_BONUS
                matched.append(pattern)
                reasoning_parts.append(f"+{self.PROVEN_PATTERN_BONUS} for proven pattern: {pattern}")
            else:
                # Still good, just not proven yet
                score += 0.5
                matched.append(pattern)

        # Detect and penalize anti-patterns
        anti_detected = self._detect_anti_patterns(title)
        anti_patterns = self.patterns.get_title_patterns(status="anti")
        anti_names = [p.formula for p in anti_patterns]

        for anti in anti_detected:
            if anti in anti_names:
                score += self.ANTI_PATTERN_PENALTY
                penalties.append(anti)
                reasoning_parts.append(f"{self.ANTI_PATTERN_PENALTY} for anti-pattern: {anti}")

        # Competitor similarity bonus
        if competitor_title:
            similarity = self._calculate_competitor_similarity(title, competitor_title)
            if similarity > 0.3:
                bonus = similarity * self.COMPETITOR_SIMILARITY_BONUS
                score += bonus
                reasoning_parts.append(f"+{bonus:.1f} for competitor similarity")

        # Clamp score
        score = max(0, min(100, score))

        return ScoredTitle(
            title=title,
            score=score,
            matched_patterns=matched,
            penalties=penalties,
            reasoning="; ".join(reasoning_parts) if reasoning_parts else "Base score only"
        )

    def select_best(
        self,
        variants: List[str],
        competitor_title: Optional[str] = None,
        min_score: float = 0.0,
    ) -> Optional[ScoredTitle]:
        """Select the highest-scoring title variant.

        Args:
            variants: List of title options (usually 3)
            competitor_title: Original competitor title for structure matching
            min_score: Minimum acceptable score

        Returns:
            Best title or None if all below threshold
        """
        if not variants:
            return None

        scored = [self.score_title(v, competitor_title) for v in variants]
        scored.sort(key=lambda s: s.score, reverse=True)

        best = scored[0]
        if best.score >= min_score:
            return best
        return None

    def rank_variants(
        self,
        variants: List[str],
        competitor_title: Optional[str] = None,
    ) -> List[ScoredTitle]:
        """Rank all variants by score.

        Args:
            variants: List of title options
            competitor_title: Optional competitor title

        Returns:
            Sorted list of ScoredTitle (highest first)
        """
        scored = [self.score_title(v, competitor_title) for v in variants]
        return sorted(scored, key=lambda s: s.score, reverse=True)
