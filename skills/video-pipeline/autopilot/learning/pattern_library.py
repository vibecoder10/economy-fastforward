"""Read and query patterns from memory files."""

import re
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional


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
