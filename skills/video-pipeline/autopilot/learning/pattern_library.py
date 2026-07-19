"""Read and query patterns from memory files."""

import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

# Import CuriosityStructure - curiosity_gap is a sibling package
from title_idea.curiosity_gap.structures import CuriosityStructure


@dataclass
class ThumbnailPattern:
    """A thumbnail pattern with performance data."""
    element: str
    description: str
    category: str = "general"  # color, composition, subject, text
    status: str = "unknown"  # proven, testing, anti
    avg_ctr: Optional[float] = None
    sample_size: int = 0


@dataclass
class TitlePattern:
    """A title formula pattern."""
    formula: str
    description: str
    status: str = "unknown"  # proven, testing, anti
    avg_ctr: Optional[float] = None
    sample_size: int = 0


@dataclass
class TopicPerformance:
    """Performance data for a topic/angle."""
    name: str
    avg_ctr: float
    sample_size: int
    verdicts: Dict[str, int] = field(default_factory=dict)  # keep/discard counts


@dataclass
class CuriosityGapPattern:
    """Performance data for a curiosity gap structure."""
    structure: CuriosityStructure
    avg_ctr_ours: Optional[float] = None
    sample_size_ours: int = 0
    avg_vph_competitors: Optional[float] = None
    sample_size_competitors: int = 0
    status: str = "testing"  # "proven", "testing", "anti"


@dataclass
class CompetitorPattern:
    """Extracted pattern from competitor video."""
    video_id: str = ""
    channel: str = ""
    title: str = ""
    structure: CuriosityStructure = CuriosityStructure.OTHER
    confidence: int = 0
    vph: float = 0.0
    thumbnail_style: Dict[str, Any] = field(default_factory=dict)
    yin_yang_approach: str = ""


class PatternLibrary:
    """Read and query memory files."""

    def __init__(self, memory_dir: Optional[Path] = None):
        """Initialize pattern library.

        Args:
            memory_dir: Path to memory directory. Defaults to autopilot/memory/
        """
        if memory_dir is None:
            memory_dir = Path(__file__).parent.parent / "memory"
        self.memory_dir = Path(memory_dir)
        self._thumbnail_cache: Optional[List[ThumbnailPattern]] = None
        self._title_cache: Optional[List[TitlePattern]] = None

    def get_learnings_summary(self) -> str:
        """Get the LEARNINGS.md content for context injection.

        Returns:
            Full content of LEARNINGS.md or empty string if not found
        """
        path = self.memory_dir / "LEARNINGS.md"
        if path.exists():
            return path.read_text()
        return ""

    def _parse_thumbnail_patterns(self) -> List[ThumbnailPattern]:
        """Parse thumbnail_patterns.md into structured data."""
        path = self.memory_dir / "thumbnail_patterns.md"
        if not path.exists():
            return []

        content = path.read_text()
        patterns = []

        # Parse Proven Elements section
        proven_match = re.search(
            r'## Proven Elements \(KEEP\)\s*\n(.*?)(?=\n##|\Z)',
            content,
            re.DOTALL
        )
        if proven_match:
            for line in proven_match.group(1).strip().split('\n'):
                line = line.strip()
                if line.startswith('- ') and ':' in line:
                    # Format: - element_name: description
                    parts = line[2:].split(':', 1)
                    element = parts[0].strip()
                    description = parts[1].strip() if len(parts) > 1 else ""
                    patterns.append(ThumbnailPattern(
                        element=element,
                        description=description,
                        status="proven"
                    ))

        # Parse Anti-Patterns section
        anti_match = re.search(
            r'## Anti-Patterns \(AVOID\)\s*\n(.*?)(?=\n##|\Z)',
            content,
            re.DOTALL
        )
        if anti_match:
            for line in anti_match.group(1).strip().split('\n'):
                line = line.strip()
                if line.startswith('- ') and ':' in line:
                    parts = line[2:].split(':', 1)
                    element = parts[0].strip()
                    description = parts[1].strip() if len(parts) > 1 else ""
                    patterns.append(ThumbnailPattern(
                        element=element,
                        description=description,
                        status="anti"
                    ))

        return patterns

    def _parse_title_patterns(self) -> List[TitlePattern]:
        """Parse title_patterns.md into structured data."""
        path = self.memory_dir / "title_patterns.md"
        if not path.exists():
            return []

        content = path.read_text()
        patterns = []

        # Parse Proven Formulas section
        proven_match = re.search(
            r'## Proven Formulas \(USE\)\s*\n(.*?)(?=\n##|\Z)',
            content,
            re.DOTALL
        )
        if proven_match:
            for line in proven_match.group(1).strip().split('\n'):
                line = line.strip()
                if line.startswith('- ') and ':' in line:
                    parts = line[2:].split(':', 1)
                    formula = parts[0].strip()
                    description = parts[1].strip() if len(parts) > 1 else ""
                    patterns.append(TitlePattern(
                        formula=formula,
                        description=description,
                        status="proven"
                    ))

        # Parse Anti-Patterns section
        anti_match = re.search(
            r'## Anti-Patterns \(AVOID\)\s*\n(.*?)(?=\n##|\Z)',
            content,
            re.DOTALL
        )
        if anti_match:
            for line in anti_match.group(1).strip().split('\n'):
                line = line.strip()
                if line.startswith('- ') and ':' in line:
                    parts = line[2:].split(':', 1)
                    formula = parts[0].strip()
                    description = parts[1].strip() if len(parts) > 1 else ""
                    patterns.append(TitlePattern(
                        formula=formula,
                        description=description,
                        status="anti"
                    ))

        return patterns

    def get_thumbnail_patterns(self, status: Optional[str] = None) -> List[ThumbnailPattern]:
        """Get thumbnail patterns, optionally filtered by status.

        Args:
            status: Filter by status (proven, testing, anti) or None for all

        Returns:
            List of ThumbnailPattern objects
        """
        if self._thumbnail_cache is None:
            self._thumbnail_cache = self._parse_thumbnail_patterns()

        if status is None:
            return self._thumbnail_cache

        return [p for p in self._thumbnail_cache if p.status == status]

    def get_title_patterns(self, status: Optional[str] = None) -> List[TitlePattern]:
        """Get title patterns, optionally filtered by status.

        Args:
            status: Filter by status (proven, testing, anti) or None for all

        Returns:
            List of TitlePattern objects
        """
        if self._title_cache is None:
            self._title_cache = self._parse_title_patterns()

        if status is None:
            return self._title_cache

        return [p for p in self._title_cache if p.status == status]

    def is_proven_element(self, element: str, category: str) -> bool:
        """Check if an element is in the proven list.

        Args:
            element: Element name to check
            category: "thumbnail" or "title"

        Returns:
            True if element is proven
        """
        if category == "thumbnail":
            patterns = self.get_thumbnail_patterns(status="proven")
            return any(p.element == element for p in patterns)
        elif category == "title":
            patterns = self.get_title_patterns(status="proven")
            return any(p.formula == element for p in patterns)
        return False

    def is_anti_pattern(self, element: str, category: str) -> bool:
        """Check if an element is an anti-pattern.

        Args:
            element: Element name to check
            category: "thumbnail" or "title"

        Returns:
            True if element is an anti-pattern
        """
        if category == "thumbnail":
            patterns = self.get_thumbnail_patterns(status="anti")
            return any(p.element == element for p in patterns)
        elif category == "title":
            patterns = self.get_title_patterns(status="anti")
            return any(p.formula == element for p in patterns)
        return False

    def invalidate_cache(self) -> None:
        """Clear cached patterns (call after memory files are updated)."""
        self._thumbnail_cache = None
        self._title_cache = None
        self._topic_cache = None
        self._angle_cache = None

    def _parse_notes_section(self, content: str, section: str) -> List[Dict]:
        """Parse a notes section into structured data.

        Format: - pattern: CTR X.X% (verdict) - video_title

        Args:
            content: Full file content
            section: Section header to find

        Returns:
            List of dicts with pattern, ctr, verdict, video_title
        """
        results = []

        # Find the section
        pattern = rf'{re.escape(section)}\s*\n(.*?)(?=\n##|\Z)'
        match = re.search(pattern, content, re.DOTALL)
        if not match:
            return results

        section_content = match.group(1)

        # Parse each line: - pattern: CTR X.X% (verdict) - video_title
        line_pattern = r'-\s*([^:]+):\s*CTR\s*([\d.]+)%\s*\((\w+)\)\s*-\s*(.+)'
        for line in section_content.split('\n'):
            line = line.strip()
            line_match = re.match(line_pattern, line)
            if line_match:
                results.append({
                    'pattern': line_match.group(1).strip(),
                    'ctr': float(line_match.group(2)),
                    'verdict': line_match.group(3).strip().lower(),
                    'video_title': line_match.group(4).strip(),
                })

        return results

    def _aggregate_performance(self, notes: List[Dict]) -> Dict[str, TopicPerformance]:
        """Aggregate notes into performance data per pattern.

        Args:
            notes: List of note dicts from _parse_notes_section

        Returns:
            Dict mapping pattern name to TopicPerformance
        """
        aggregated: Dict[str, Dict] = {}

        for note in notes:
            name = note['pattern']
            if name not in aggregated:
                aggregated[name] = {
                    'ctrs': [],
                    'verdicts': {'keep': 0, 'discard': 0, 'neutral': 0},
                }
            aggregated[name]['ctrs'].append(note['ctr'])
            verdict = note['verdict']
            if verdict in aggregated[name]['verdicts']:
                aggregated[name]['verdicts'][verdict] += 1

        result = {}
        for name, data in aggregated.items():
            avg_ctr = sum(data['ctrs']) / len(data['ctrs']) if data['ctrs'] else 0
            result[name] = TopicPerformance(
                name=name,
                avg_ctr=avg_ctr,
                sample_size=len(data['ctrs']),
                verdicts=data['verdicts'],
            )

        return result

    def get_topic_performance(self) -> Dict[str, TopicPerformance]:
        """Get topic category performance data.

        Returns:
            Dict mapping topic name to TopicPerformance
        """
        if hasattr(self, '_topic_cache') and self._topic_cache is not None:
            return self._topic_cache

        path = self.memory_dir / "topic_performance.md"
        if not path.exists():
            self._topic_cache = {}
            return self._topic_cache

        content = path.read_text()
        notes = self._parse_notes_section(content, "## Topic CTR Rankings")
        self._topic_cache = self._aggregate_performance(notes)
        return self._topic_cache

    def get_angle_performance(self) -> Dict[str, TopicPerformance]:
        """Get angle type performance data.

        Returns:
            Dict mapping angle name to TopicPerformance
        """
        if hasattr(self, '_angle_cache') and self._angle_cache is not None:
            return self._angle_cache

        path = self.memory_dir / "topic_performance.md"
        if not path.exists():
            self._angle_cache = {}
            return self._angle_cache

        content = path.read_text()
        notes = self._parse_notes_section(content, "## Angle Performance")
        self._angle_cache = self._aggregate_performance(notes)
        return self._angle_cache

    def get_title_notes(self) -> List[Dict]:
        """Get raw title pattern notes from the Notes section.

        Returns:
            List of note dicts with pattern, ctr, verdict, video_title
        """
        path = self.memory_dir / "title_patterns.md"
        if not path.exists():
            return []

        content = path.read_text()
        return self._parse_notes_section(content, "## Notes")

    def _parse_competitor_patterns(self) -> tuple[List[CuriosityGapPattern], List[CompetitorPattern]]:
        """Parse competitor_patterns.md into structured data."""
        path = self.memory_dir / "competitor_patterns.md"
        if not path.exists():
            return [], []

        content = path.read_text()
        gap_patterns = []
        competitor_patterns = []

        # Parse structure sections (### hidden_flaw (n=12, avg VPH: 165))
        structure_pattern = r'### (\w+) \(n=(\d+), avg VPH: ([\d.]+|—)\)'
        for match in re.finditer(structure_pattern, content):
            structure_name = match.group(1)
            sample_size = int(match.group(2))
            avg_vph_str = match.group(3)
            avg_vph = float(avg_vph_str) if avg_vph_str != "—" else None

            try:
                structure = CuriosityStructure(structure_name)
            except ValueError:
                structure = CuriosityStructure.OTHER

            gap_patterns.append(CuriosityGapPattern(
                structure=structure,
                sample_size_competitors=sample_size,
                avg_vph_competitors=avg_vph,
            ))

        # Parse individual videos (- Channel: "Title" (VPH: X))
        # Channel name can have spaces (e.g., "Economics Explained")
        video_pattern = r'- ([^:]+): "([^"]+)" \(VPH: ([\d.]+)\)'
        # Find which section each video is in
        current_structure = CuriosityStructure.OTHER
        for line in content.split('\n'):
            struct_match = re.match(r'### (\w+)', line)
            if struct_match:
                try:
                    current_structure = CuriosityStructure(struct_match.group(1))
                except ValueError:
                    current_structure = CuriosityStructure.OTHER
                continue

            video_match = re.match(video_pattern, line.strip())
            if video_match:
                competitor_patterns.append(CompetitorPattern(
                    channel=video_match.group(1),
                    title=video_match.group(2),
                    vph=float(video_match.group(3)),
                    structure=current_structure,
                ))

        return gap_patterns, competitor_patterns

    def get_curiosity_gap_patterns(
        self,
        structure: Optional[CuriosityStructure] = None
    ) -> List[CuriosityGapPattern]:
        """Get curiosity gap structure performance from competitor_patterns.md.

        Args:
            structure: Filter by specific structure (optional)

        Returns:
            List of CuriosityGapPattern objects
        """
        gap_patterns, _ = self._parse_competitor_patterns()

        if structure is not None:
            return [p for p in gap_patterns if p.structure == structure]

        return gap_patterns

    def get_competitor_patterns(
        self,
        channel: Optional[str] = None,
        structure: Optional[CuriosityStructure] = None,
        min_vph: float = 0
    ) -> List[CompetitorPattern]:
        """Get competitor patterns from competitor_patterns.md.

        Args:
            channel: Filter by channel name (optional)
            structure: Filter by structure (optional)
            min_vph: Minimum VPH threshold

        Returns:
            List of CompetitorPattern objects
        """
        _, competitor_patterns = self._parse_competitor_patterns()

        if channel is not None:
            competitor_patterns = [p for p in competitor_patterns if p.channel == channel]

        if structure is not None:
            competitor_patterns = [p for p in competitor_patterns if p.structure == structure]

        if min_vph > 0:
            competitor_patterns = [p for p in competitor_patterns if p.vph >= min_vph]

        return competitor_patterns

    def get_unclassified_titles(self) -> List[Dict]:
        """Get unclassified 'other' titles from competitor_patterns.md.

        Returns:
            List of dicts with title and notes
        """
        path = self.memory_dir / "competitor_patterns.md"
        if not path.exists():
            return []

        content = path.read_text()
        unclassified = []

        # Find Unclassified section
        unclassified_match = re.search(
            r'## Unclassified \(other\).*?\n(.*?)(?=\n##|\n---|\Z)',
            content,
            re.DOTALL
        )

        if unclassified_match:
            section = unclassified_match.group(1)
            # Parse lines like: - "Title" (pattern note?)
            for line in section.split('\n'):
                line = line.strip()
                if line.startswith('- "'):
                    match = re.match(r'- "([^"]+)"(.*)', line)
                    if match:
                        unclassified.append({
                            "title": match.group(1),
                            "notes": match.group(2).strip(' ()'),
                        })

        return unclassified
