# skills/video-pipeline/autopilot/learning/learning_extractor.py
"""Extract learnable patterns from video performance.

Analyzes 48h+ video performance and extracts patterns from:
- Thumbnail overrides (colors, composition, text style)
- Title structure (question format, numbers, caps)
- Theme/angle/hooks (via ThemeExtractor integration)
- Topic category performance

Identifies what worked (KEEP) and what didn't (DISCARD).
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime
import re
import logging

from autopilot.monitoring.early_warning import CTRVerdict, EarlyWarning

logger = logging.getLogger(__name__)


@dataclass
class ExtractedLearning:
    """A learning extracted from video performance."""
    category: str  # "thumbnail", "title", "topic", "theme", "angle", "formula", "structure"
    pattern: str  # e.g., "red_yellow_color_scheme", "hidden_truth", "geopolitics", "hidden_flaw"
    verdict: CTRVerdict
    confidence: float  # 0-100
    evidence: str  # Human-readable explanation
    video_title: str
    ctr: float


@dataclass
class ThemeData:
    """Theme analysis data for a video."""
    primary_theme: str = ""
    secondary_themes: List[str] = field(default_factory=list)
    angle_type: str = ""
    emotional_hooks: List[str] = field(default_factory=list)
    topic_category: str = ""
    title_formula: str = ""
    formula_variables: Dict[str, str] = field(default_factory=dict)


@dataclass
class ExperimentResult:
    """Full result of a video experiment."""
    video_title: str
    date: str
    modeled_from: Optional[str]
    predicted_ctr: Optional[float]
    actual_ctr: float
    verdict: CTRVerdict
    thumbnail_override: Optional[str]
    title_formula: Optional[str]
    theme_data: Optional[ThemeData] = None  # NEW: Theme analysis data
    learnings: List[ExtractedLearning] = field(default_factory=list)


class LearningExtractor:
    """Extract patterns from video performance.

    Analyzes thumbnail overrides and titles to identify patterns
    that correlate with CTR performance. Used to build the memory
    system that guides future decisions.
    """

    def __init__(self):
        """Initialize learning extractor with early warning system."""
        self.early_warning = EarlyWarning()

    def _get_confidence_for_verdict(self, verdict: CTRVerdict) -> float:
        """Get confidence score based on verdict.

        Args:
            verdict: CTR verdict (KEEP, DISCARD, NEUTRAL)

        Returns:
            Confidence score (60 for KEEP, 40 for DISCARD, 50 for NEUTRAL)
        """
        if verdict == CTRVerdict.KEEP:
            return 60.0
        elif verdict == CTRVerdict.DISCARD:
            return 40.0
        else:
            return 50.0

    def extract_thumbnail_learnings(
        self,
        video_title: str,
        ctr: float,
        thumbnail_override: Optional[str],
    ) -> List[ExtractedLearning]:
        """Extract thumbnail-related learnings from override text.

        Parses the thumbnail override description to identify patterns
        like color schemes, compositions, and text styles.

        Args:
            video_title: Title of the video
            ctr: Actual CTR percentage
            thumbnail_override: Text description of thumbnail override

        Returns:
            List of ExtractedLearning objects for identified patterns
        """
        learnings = []
        verdict = self.early_warning.get_verdict(ctr)
        confidence = self._get_confidence_for_verdict(verdict)

        if not thumbnail_override:
            return learnings

        override_lower = thumbnail_override.lower()

        # Color patterns
        if "red" in override_lower and "yellow" in override_lower:
            learnings.append(ExtractedLearning(
                category="thumbnail",
                pattern="red_yellow_color_scheme",
                verdict=verdict,
                confidence=confidence,
                evidence=f"Red/yellow color scheme used. CTR: {ctr:.1f}%",
                video_title=video_title,
                ctr=ctr,
            ))

        # Composition patterns
        if "face" in override_lower and "left" in override_lower:
            learnings.append(ExtractedLearning(
                category="thumbnail",
                pattern="face_left_composition",
                verdict=verdict,
                confidence=confidence,
                evidence=f"Face-left composition used. CTR: {ctr:.1f}%",
                video_title=video_title,
                ctr=ctr,
            ))

        # Text patterns
        if "caps" in override_lower or "bold" in override_lower:
            learnings.append(ExtractedLearning(
                category="thumbnail",
                pattern="bold_caps_text",
                verdict=verdict,
                confidence=confidence,
                evidence=f"Bold caps text used. CTR: {ctr:.1f}%",
                video_title=video_title,
                ctr=ctr,
            ))

        return learnings

    def extract_title_learnings(
        self,
        video_title: str,
        ctr: float,
    ) -> List[ExtractedLearning]:
        """Extract title-related learnings from video title.

        Analyzes the title structure to identify patterns like
        questions, numbers, and emphasis.

        Args:
            video_title: Title of the video
            ctr: Actual CTR percentage

        Returns:
            List of ExtractedLearning objects for identified patterns
        """
        learnings = []
        verdict = self.early_warning.get_verdict(ctr)
        confidence = self._get_confidence_for_verdict(verdict)

        # Question pattern
        if video_title.rstrip().endswith("?"):
            learnings.append(ExtractedLearning(
                category="title",
                pattern="question_format",
                verdict=verdict,
                confidence=confidence,
                evidence=f"Question format title. CTR: {ctr:.1f}%",
                video_title=video_title,
                ctr=ctr,
            ))

        # Number pattern
        if re.search(r'\d+', video_title):
            learnings.append(ExtractedLearning(
                category="title",
                pattern="number_in_title",
                verdict=verdict,
                confidence=confidence,
                evidence=f"Number in title. CTR: {ctr:.1f}%",
                video_title=video_title,
                ctr=ctr,
            ))

        # Caps emphasis (2+ consecutive uppercase letters as a word)
        if re.search(r'\b[A-Z]{2,}\b', video_title):
            learnings.append(ExtractedLearning(
                category="title",
                pattern="caps_emphasis",
                verdict=verdict,
                confidence=confidence,
                evidence=f"Caps emphasis in title. CTR: {ctr:.1f}%",
                video_title=video_title,
                ctr=ctr,
            ))

        return learnings

    def extract_theme_learnings(
        self,
        video_title: str,
        ctr: float,
        theme_data: Optional[ThemeData],
    ) -> List[ExtractedLearning]:
        """Extract theme-related learnings from theme analysis.

        Analyzes the theme, angle, topic category, and emotional hooks
        to identify what resonates with our audience.

        Args:
            video_title: Title of the video
            ctr: Actual CTR percentage
            theme_data: Theme analysis from ThemeExtractor

        Returns:
            List of ExtractedLearning objects for theme patterns
        """
        learnings = []
        verdict = self.early_warning.get_verdict(ctr)
        confidence = self._get_confidence_for_verdict(verdict)

        if theme_data is None:
            return learnings

        # Topic category learning
        if theme_data.topic_category:
            learnings.append(ExtractedLearning(
                category="topic",
                pattern=theme_data.topic_category,
                verdict=verdict,
                confidence=confidence,
                evidence=f"Topic '{theme_data.topic_category}'. CTR: {ctr:.1f}%",
                video_title=video_title,
                ctr=ctr,
            ))

        # Angle type learning
        if theme_data.angle_type:
            learnings.append(ExtractedLearning(
                category="angle",
                pattern=theme_data.angle_type,
                verdict=verdict,
                confidence=confidence,
                evidence=f"Angle '{theme_data.angle_type}'. CTR: {ctr:.1f}%",
                video_title=video_title,
                ctr=ctr,
            ))

        # Emotional hooks learning
        for hook in theme_data.emotional_hooks:
            learnings.append(ExtractedLearning(
                category="hook",
                pattern=hook,
                verdict=verdict,
                confidence=confidence,
                evidence=f"Hook '{hook}' used. CTR: {ctr:.1f}%",
                video_title=video_title,
                ctr=ctr,
            ))

        # Title formula learning (if we have a recognizable formula)
        if theme_data.title_formula:
            # Normalize formula to a pattern name
            formula_pattern = self._normalize_formula(theme_data.title_formula)
            if formula_pattern:
                learnings.append(ExtractedLearning(
                    category="formula",
                    pattern=formula_pattern,
                    verdict=verdict,
                    confidence=confidence,
                    evidence=f"Formula '{theme_data.title_formula}'. CTR: {ctr:.1f}%",
                    video_title=video_title,
                    ctr=ctr,
                ))

        return learnings

    def _normalize_formula(self, formula: str) -> str:
        """Normalize a title formula to a pattern name.

        Args:
            formula: Raw formula like "How [Power] [Verb] the [Event]"

        Returns:
            Normalized pattern name like "how_power_verb_event"
        """
        if not formula:
            return ""

        # Extract just the structure words and placeholders
        # Remove brackets and lowercase
        normalized = formula.lower()
        normalized = re.sub(r'\[([^\]]+)\]', r'\1', normalized)  # Remove brackets
        normalized = re.sub(r'[^\w\s]', '', normalized)  # Remove punctuation
        normalized = re.sub(r'\s+', '_', normalized.strip())  # Spaces to underscores

        # Truncate if too long
        if len(normalized) > 50:
            normalized = normalized[:50]

        return normalized

    def extract_structure_learnings(
        self,
        video_title: str,
        ctr: float,
        structure: Optional[str],
        structure_confidence: Optional[int],
    ) -> List[ExtractedLearning]:
        """Extract curiosity gap structure learnings.

        Tracks which curiosity gap structure was used and correlates
        with CTR performance.

        Args:
            video_title: Title of the video
            ctr: Actual CTR percentage
            structure: Curiosity gap structure ID (e.g., "hidden_flaw")
            structure_confidence: Confidence score at generation time

        Returns:
            List of ExtractedLearning for structure pattern
        """
        learnings = []

        if not structure:
            return learnings

        verdict = self.early_warning.get_verdict(ctr)
        confidence = self._get_confidence_for_verdict(verdict)

        # Adjust confidence based on structure_confidence at generation
        if structure_confidence:
            # Blend: 60% CTR verdict, 40% generation confidence
            confidence = confidence * 0.6 + (structure_confidence / 100 * 100) * 0.4

        learnings.append(ExtractedLearning(
            category="structure",
            pattern=structure,
            verdict=verdict,
            confidence=confidence,
            evidence=f"Structure '{structure}' (gen_conf: {structure_confidence or 'N/A'}). CTR: {ctr:.1f}%",
            video_title=video_title,
            ctr=ctr,
        ))

        return learnings

    def extract_all(
        self,
        video_title: str,
        ctr: float,
        thumbnail_override: Optional[str] = None,
        modeled_from: Optional[str] = None,
        theme_data: Optional[ThemeData] = None,
        structure: Optional[str] = None,
        structure_confidence: Optional[int] = None,
    ) -> ExperimentResult:
        """Extract all learnings from a video experiment.

        Combines thumbnail, title, theme, and structure pattern extraction into
        a single experiment result with all learnings.

        Args:
            video_title: Title of the video
            ctr: Actual CTR percentage
            thumbnail_override: Text description of thumbnail override
            modeled_from: Competitor video this was modeled from
            theme_data: Theme analysis data (optional)
            structure: Curiosity gap structure ID (optional)
            structure_confidence: Structure confidence at generation time (optional)

        Returns:
            ExperimentResult with verdict and all extracted learnings
        """
        verdict = self.early_warning.get_verdict(ctr)

        learnings = []
        learnings.extend(self.extract_thumbnail_learnings(video_title, ctr, thumbnail_override))
        learnings.extend(self.extract_title_learnings(video_title, ctr))
        learnings.extend(self.extract_theme_learnings(video_title, ctr, theme_data))
        learnings.extend(self.extract_structure_learnings(video_title, ctr, structure, structure_confidence))

        # Get title formula from theme_data if available
        title_formula = theme_data.title_formula if theme_data else None

        return ExperimentResult(
            video_title=video_title,
            date=datetime.now().strftime("%Y-%m-%d"),
            modeled_from=modeled_from,
            predicted_ctr=None,
            actual_ctr=ctr,
            verdict=verdict,
            thumbnail_override=thumbnail_override,
            title_formula=title_formula,
            theme_data=theme_data,
            learnings=learnings,
        )

    async def extract_with_theme_analysis(
        self,
        video_title: str,
        ctr: float,
        thumbnail_override: Optional[str] = None,
        modeled_from: Optional[str] = None,
    ) -> ExperimentResult:
        """Extract learnings including theme analysis via Claude.

        Performs full theme extraction using ThemeExtractor before
        extracting patterns. Use this for comprehensive analysis.

        Args:
            video_title: Title of the video
            ctr: Actual CTR percentage
            thumbnail_override: Text description of thumbnail override
            modeled_from: Competitor video this was modeled from

        Returns:
            ExperimentResult with theme data and all extracted learnings
        """
        from autopilot.analysis.theme_extractor import ThemeExtractor, ThemeAnalysis

        # Extract theme using Claude
        extractor = ThemeExtractor()
        theme_analysis = await extractor.extract(video_title)

        # Convert ThemeAnalysis to ThemeData
        theme_data = None
        if theme_analysis:
            theme_data = ThemeData(
                primary_theme=theme_analysis.primary_theme,
                secondary_themes=theme_analysis.secondary_themes,
                angle_type=theme_analysis.angle_type,
                emotional_hooks=theme_analysis.emotional_hooks,
                topic_category=theme_analysis.topic_category,
                title_formula=theme_analysis.title_formula,
                formula_variables=theme_analysis.formula_variables,
            )

        return self.extract_all(
            video_title=video_title,
            ctr=ctr,
            thumbnail_override=thumbnail_override,
            modeled_from=modeled_from,
            theme_data=theme_data,
        )


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def run_daily_extraction():
    """Run daily learning extraction on 48h+ videos.

    STATUS: NOT WIRED - this cron entry point (`autopilot-learn`, see
    infra/setup_cron.sh) currently extracts zero learnings, every day,
    unconditionally. That's why LEARNINGS.md has shown "Videos produced: 0"
    since this was written. Two separate gaps, not one:

      1. No code anywhere ever sets `ExperimentState.status` to
         "monitoring" (grep the codebase - `core/state_manager.py`'s
         `record_production_cycle` only ever writes "producing", and
         nothing transitions it forward). The `exp.status != "monitoring"`
         guard below is therefore permanently true - this function has
         never once reached the code past it in production.
      2. Even if (1) were fixed, CTR/retention would still need to be
         pulled from Airtable (via performance_tracker) and passed into
         `LearningExtractor.extract_all()` / `MemoryWriter` - that call
         was never written either.

    Wiring both is a real feature (a state machine + a data pull across
    autopilot.py, ctr_monitor.py, and this file) - out of scope for a stub
    cleanup pass. Flagged as a follow-up, not fixed here. See C32 /
    docs/reports/2026-07-17-storyengine-agent-audit-findings.md §3.2 and
    SYSTEM_STATE.md §C32.

    StoryEngine's `storyengine/backend/routes/learning_extraction.py` is a
    complete, working version of this same idea (title/hook/framework
    pattern extraction gated on real CTR + retention) - but it reads from
    the Supabase `videos` table per-tenant, and this legacy Airtable-only
    channel (Economy FastForward) has no tenant row there. It is NOT a
    drop-in replacement for this cron job today; deprecating this path
    outright would remove the only learning loop this channel has, even
    though that loop is currently a no-op. Left running (cheap, no cost)
    with an honest log instead of the previous "ready" message that implied
    it was working.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

    from autopilot.core.state_manager import StateManager

    logger.warning(
        "learning_extractor --daily: NOT WIRED (see run_daily_extraction "
        "docstring) - no learnings will be extracted or written this run."
    )

    state_manager = StateManager()

    # Get current experiment from state
    state = state_manager.load()

    if not state.current_experiment:
        print("   No current experiment to analyze.")
        return

    exp = state.current_experiment

    # Check if experiment has CTR data (would come from Airtable via performance_tracker)
    if exp.status != "monitoring":
        print(
            f"   Current experiment '{exp.video_title}' is in status "
            f"'{exp.status}', not 'monitoring' - and nothing in this codebase "
            "ever sets that status today (see docstring), so this will "
            "never proceed further."
        )
        return

    # Unreachable in current production (see docstring) - kept so a future
    # fix to the state machine has somewhere to land the CTR pull.
    print(f"   Analyzing: {exp.video_title}")
    logger.warning(
        "   Reached the 'monitoring' branch, but CTR/retention pull from "
        "Airtable is still unwired - no learnings extracted. See docstring."
    )


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Learning Extractor")
    parser.add_argument("--daily", action="store_true", help="Run daily extraction on 48h+ videos")
    args = parser.parse_args()

    if args.daily:
        run_daily_extraction()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
