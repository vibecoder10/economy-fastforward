# skills/video-pipeline/autopilot/learning/learning_extractor.py
"""Extract learnable patterns from video performance.

Analyzes 48h+ video performance and extracts patterns from thumbnail
overrides and titles. Identifies what worked (KEEP) and what didn't (DISCARD).
"""

from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime
import re

from autopilot.monitoring.early_warning import CTRVerdict, EarlyWarning


@dataclass
class ExtractedLearning:
    """A learning extracted from video performance."""
    category: str  # "thumbnail", "title", "topic"
    pattern: str  # e.g., "red_yellow_color_scheme"
    verdict: CTRVerdict
    confidence: float  # 0-100
    evidence: str  # Human-readable explanation
    video_title: str
    ctr: float


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

    def extract_all(
        self,
        video_title: str,
        ctr: float,
        thumbnail_override: Optional[str] = None,
        modeled_from: Optional[str] = None,
    ) -> ExperimentResult:
        """Extract all learnings from a video experiment.

        Combines thumbnail and title pattern extraction into a single
        experiment result with all learnings.

        Args:
            video_title: Title of the video
            ctr: Actual CTR percentage
            thumbnail_override: Text description of thumbnail override
            modeled_from: Competitor video this was modeled from

        Returns:
            ExperimentResult with verdict and all extracted learnings
        """
        verdict = self.early_warning.get_verdict(ctr)

        learnings = []
        learnings.extend(self.extract_thumbnail_learnings(video_title, ctr, thumbnail_override))
        learnings.extend(self.extract_title_learnings(video_title, ctr))

        return ExperimentResult(
            video_title=video_title,
            date=datetime.now().strftime("%Y-%m-%d"),
            modeled_from=modeled_from,
            predicted_ctr=None,
            actual_ctr=ctr,
            verdict=verdict,
            thumbnail_override=thumbnail_override,
            title_formula=None,
            learnings=learnings,
        )


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def run_daily_extraction():
    """Run daily learning extraction on 48h+ videos.

    Queries Airtable for videos uploaded 48+ hours ago that have
    CTR data but haven't been analyzed yet.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

    from autopilot.learning.memory_writer import MemoryWriter
    from autopilot.core.state_manager import StateManager

    print("🧠 Learning Extractor: Running daily extraction...")

    extractor = LearningExtractor()
    writer = MemoryWriter()
    state_manager = StateManager()

    # Get current experiment from state
    state = state_manager.load()

    if not state.current_experiment:
        print("   No current experiment to analyze.")
        return

    exp = state.current_experiment

    # Check if experiment has CTR data (would come from Airtable via performance_tracker)
    # For now, we just show what would be extracted
    if exp.status != "monitoring":
        print(f"   Current experiment '{exp.video_title}' is in status '{exp.status}', not 'monitoring'.")
        return

    print(f"   Analyzing: {exp.video_title}")
    print("   (Note: Full extraction requires CTR data from performance_tracker)")

    # TODO: Integrate with Airtable to get actual CTR data
    # For now, log that we would extract learnings
    print("   Learning extraction is ready. Will process when CTR data is available.")


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
