# skills/video-pipeline/autopilot/learning/memory_writer.py
"""Update markdown memory files with learnings.

This module persists experiment results and extracted learnings to
the markdown memory files in autopilot/memory/. These files are
loaded into context at the start of each production cycle.

Memory files:
- LEARNINGS.md - Master summary with stats
- experiments_log.md - Full experiment ledger
- thumbnail_patterns.md - Thumbnail pattern notes
- title_patterns.md - Title pattern notes
- topic_performance.md - Topic/angle/theme performance
"""

from datetime import datetime
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass, field

from autopilot.monitoring.early_warning import CTRVerdict


@dataclass
class ExtractedLearning:
    """A learning extracted from video performance.

    Represents a single pattern observation from a video's
    CTR performance that should be recorded to memory.
    """
    category: str  # thumbnail, title, topic, structure, etc.
    pattern: str  # Description of the pattern
    verdict: CTRVerdict  # KEEP, DISCARD, or NEUTRAL
    confidence: float  # 0.0 - 1.0
    evidence: str  # Why this learning was extracted
    video_title: str  # Source video
    ctr: float  # CTR percentage


@dataclass
class ExperimentResult:
    """Full result of a video experiment.

    Captures everything about a video production cycle
    for logging and pattern extraction.
    """
    video_title: str
    date: str
    modeled_from: Optional[str]
    predicted_ctr: Optional[float]
    actual_ctr: float
    verdict: CTRVerdict
    thumbnail_override: Optional[str]
    title_formula: Optional[str]
    learnings: List[ExtractedLearning] = field(default_factory=list)


class MemoryWriter:
    """Write learnings to markdown memory files.

    Updates the persistent memory files in autopilot/memory/
    with experiment results and extracted patterns.
    """

    def __init__(self, memory_dir: Optional[Path] = None):
        """Initialize memory writer.

        Args:
            memory_dir: Path to memory directory.
                       Defaults to autopilot/memory/
        """
        if memory_dir is None:
            memory_dir = Path(__file__).parent.parent / "memory"
        self.memory_dir = memory_dir

    def append_experiment(self, result: ExperimentResult) -> None:
        """Append experiment to experiments_log.md.

        Creates a new entry in the experiment log with full
        details of the video production and its results.

        Args:
            result: Full experiment result to log
        """
        log_path = self.memory_dir / "experiments_log.md"

        # Count existing experiments to determine number
        existing = log_path.read_text() if log_path.exists() else ""
        exp_count = existing.count("## Video #") + 1

        # Format learnings as comma-separated list
        learnings_str = ", ".join(l.pattern for l in result.learnings) or "None extracted"

        # Format predicted CTR (may be None)
        predicted = f"{result.predicted_ctr:.1f}" if result.predicted_ctr else "N/A"

        # Format modeled from (may be None)
        modeled = result.modeled_from or "N/A"

        # Format thumbnail override (may be None)
        thumb_override = result.thumbnail_override or "None"

        entry = f"""
## Video #{exp_count}: "{result.video_title}"
- Date: {result.date}
- Modeled: {modeled}
- Predicted CTR: {predicted}% | Actual: {result.actual_ctr:.1f}%
- Status: {result.verdict.value.upper()}
- Thumbnail override: {thumb_override}
- Learnings: {learnings_str}

"""

        with open(log_path, "a") as f:
            f.write(entry)

    def update_thumbnail_patterns(self, learnings: List[ExtractedLearning]) -> None:
        """Update thumbnail_patterns.md with new pattern notes.

        Adds notes about thumbnail patterns observed from
        video performance data.

        Args:
            learnings: List of learnings (only thumbnail category used)
        """
        pattern_path = self.memory_dir / "thumbnail_patterns.md"
        content = pattern_path.read_text() if pattern_path.exists() else ""

        for learning in learnings:
            if learning.category != "thumbnail":
                continue

            note = (
                f"\n- {learning.pattern}: CTR {learning.ctr:.1f}% "
                f"({learning.verdict.value}) - {learning.video_title}"
            )

            if "## Notes" in content:
                # Insert note after "## Notes" line
                content = content.replace("## Notes\n", f"## Notes{note}\n", 1)
            else:
                content += f"\n## Notes{note}\n"

        pattern_path.write_text(content)

    def update_title_patterns(self, learnings: List[ExtractedLearning]) -> None:
        """Update title_patterns.md with new pattern notes.

        Adds notes about title patterns observed from
        video performance data.

        Args:
            learnings: List of learnings (only title category used)
        """
        pattern_path = self.memory_dir / "title_patterns.md"
        content = pattern_path.read_text() if pattern_path.exists() else ""

        for learning in learnings:
            if learning.category != "title":
                continue

            note = (
                f"\n- {learning.pattern}: CTR {learning.ctr:.1f}% "
                f"({learning.verdict.value}) - {learning.video_title}"
            )

            if "## Notes" in content:
                # Insert note after "## Notes" line
                content = content.replace("## Notes\n", f"## Notes{note}\n", 1)
            else:
                content += f"\n## Notes{note}\n"

        pattern_path.write_text(content)

    def update_learnings_summary(
        self,
        videos_produced: int,
        avg_ctr: float,
        best_ctr: float,
        best_title: str,
    ) -> None:
        """Update LEARNINGS.md summary header with latest stats.

        Updates the header section of LEARNINGS.md with current
        video count and CTR statistics while preserving the
        sections below.

        Args:
            videos_produced: Total videos produced
            avg_ctr: Average CTR across all videos
            best_ctr: Best CTR achieved
            best_title: Title of best performing video
        """
        path = self.memory_dir / "LEARNINGS.md"
        content = path.read_text() if path.exists() else ""

        today = datetime.now().strftime("%Y-%m-%d")

        new_header = f"""# Autopilot Learnings

Last updated: {today}
Videos produced: {videos_produced}
Avg CTR: {avg_ctr:.1f}%
Best CTR: {best_ctr:.1f}% ("{best_title}")
"""

        # Find where the header ends (first ## or --- after first line)
        if "# Autopilot Learnings" in content:
            lines = content.split("\n")
            header_end = 0
            for i, line in enumerate(lines):
                if i > 0 and (line.startswith("## ") or line.startswith("---")):
                    header_end = i
                    break
            if header_end > 0:
                # Preserve everything from header_end onwards
                content = new_header + "\n" + "\n".join(lines[header_end:])
            else:
                content = new_header
        else:
            # No existing header, prepend new header
            content = new_header + "\n" + content

        path.write_text(content)

    def update_topic_performance(self, learnings: List[ExtractedLearning]) -> None:
        """Update topic_performance.md with topic, angle, and hook patterns.

        Adds notes about topic categories, angles, and emotional hooks
        observed from video performance data.

        Args:
            learnings: List of learnings (topic, angle, hook, formula categories used)
        """
        pattern_path = self.memory_dir / "topic_performance.md"
        content = pattern_path.read_text() if pattern_path.exists() else ""

        for learning in learnings:
            if learning.category not in ("topic", "angle", "hook", "formula"):
                continue

            # Determine which section to update based on category
            if learning.category == "topic":
                section = "## Topic CTR Rankings"
            elif learning.category == "angle":
                section = "## Angle Performance"
            elif learning.category == "formula":
                section = "## Theme Patterns"
            else:  # hook
                section = "## Notes"

            note = (
                f"\n- {learning.pattern}: CTR {learning.ctr:.1f}% "
                f"({learning.verdict.value}) - {learning.video_title}"
            )

            if section in content:
                # Insert note after section heading
                content = content.replace(f"{section}\n", f"{section}{note}\n", 1)
            else:
                content += f"\n{section}{note}\n"

        pattern_path.write_text(content)

    def update_curiosity_gap_patterns(self, learnings: List[ExtractedLearning]) -> None:
        """Update title_patterns.md with curiosity gap structure performance.

        Adds notes about which curiosity gap structures performed well
        (KEEP) or poorly (DISCARD) based on CTR data.

        Args:
            learnings: List of learnings (only "structure" category used)
        """
        pattern_path = self.memory_dir / "title_patterns.md"
        content = pattern_path.read_text() if pattern_path.exists() else ""

        for learning in learnings:
            if learning.category != "structure":
                continue

            note = (
                f"\n- {learning.pattern}: CTR {learning.ctr:.1f}% "
                f"({learning.verdict.value}) - {learning.video_title}"
            )

            # Insert into Curiosity Gap Structures section
            if "## Curiosity Gap Structures" in content:
                content = content.replace(
                    "## Curiosity Gap Structures\n",
                    f"## Curiosity Gap Structures{note}\n",
                    1
                )
            else:
                # Create section if missing
                content += f"\n## Curiosity Gap Structures{note}\n"

        pattern_path.write_text(content)

    def process_result(self, result: ExperimentResult) -> None:
        """Process a full experiment result and update all memory files.

        Convenience method that updates experiments_log.md and
        the relevant pattern files based on the learnings.

        Args:
            result: Full experiment result with learnings
        """
        # Always log the experiment
        self.append_experiment(result)

        # Filter learnings by category
        thumbnail_learnings = [l for l in result.learnings if l.category == "thumbnail"]
        title_learnings = [l for l in result.learnings if l.category == "title"]
        topic_learnings = [l for l in result.learnings if l.category in ("topic", "angle", "hook", "formula")]
        structure_learnings = [l for l in result.learnings if l.category == "structure"]

        # Update pattern files if there are relevant learnings
        if thumbnail_learnings:
            self.update_thumbnail_patterns(thumbnail_learnings)
        if title_learnings:
            self.update_title_patterns(title_learnings)
        if topic_learnings:
            self.update_topic_performance(topic_learnings)
        if structure_learnings:
            self.update_curiosity_gap_patterns(structure_learnings)
