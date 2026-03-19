"""Generate thumbnail style overrides from analysis."""

from typing import Optional, List
from autopilot.analysis.thumbnail_analyzer import ThumbnailAnalysis
from autopilot.learning.pattern_library import PatternLibrary


class ThumbnailAdapter:
    """Generate style overrides from analysis + memory."""

    # Known anti-patterns to always avoid
    DEFAULT_ANTI_PATTERNS = ["blue background", "blue tones", "low contrast"]

    def __init__(self, pattern_library: Optional[PatternLibrary] = None):
        """Initialize adapter.

        Args:
            pattern_library: Pattern library for memory queries. If None, creates new one.
        """
        if pattern_library is None:
            pattern_library = PatternLibrary()
        self.patterns = pattern_library

    def _describe_colors(self, colors: dict) -> str:
        """Generate color description for override.

        Args:
            colors: Color dict from analysis

        Returns:
            Natural language color description
        """
        parts = []

        if colors.get("background"):
            parts.append(f"{colors['background']} background")

        if colors.get("text"):
            parts.append(f"{colors['text']} text")

        if colors.get("accents"):
            parts.append(f"accent colors: {colors['accents']}")

        return ". ".join(parts) if parts else "Neutral color scheme"

    def _describe_composition(self, composition: str, subject: dict) -> str:
        """Generate composition description.

        Args:
            composition: Composition string from analysis
            subject: Subject dict from analysis

        Returns:
            Natural language composition description
        """
        parts = []

        # Parse composition string
        if "left" in composition.lower():
            if subject.get("face"):
                parts.append(f"{subject.get('type', 'Subject')} positioned on LEFT side of frame")
            else:
                parts.append("Main element positioned on LEFT side")

        if "right" in composition.lower():
            if "text" in composition.lower():
                parts.append("Text on RIGHT side of frame")
            else:
                parts.append("Secondary element on RIGHT")

        if "center" in composition.lower():
            parts.append("Centered composition")

        # Add subject details
        if subject.get("face") and subject.get("expression"):
            parts.append(f"Expression: {subject['expression']}")

        return ". ".join(parts) if parts else "Balanced composition"

    def _describe_text(self, text: dict) -> str:
        """Generate text style description.

        Args:
            text: Text dict from analysis

        Returns:
            Natural language text description
        """
        parts = []

        if text.get("lines"):
            parts.append(f"{text['lines']} line(s) of text")

        if text.get("size_pct"):
            parts.append(f"approximately {text['size_pct']}% of frame width")

        if text.get("style"):
            parts.append(f"{text['style']} style")

        return ", ".join(parts) if parts else "Standard text styling"

    def _get_anti_patterns_to_avoid(self) -> List[str]:
        """Get list of anti-patterns to explicitly avoid.

        Returns:
            List of anti-pattern descriptions
        """
        anti_patterns = list(self.DEFAULT_ANTI_PATTERNS)

        # Add from memory
        thumbnail_antis = self.patterns.get_thumbnail_patterns(status="anti")
        for p in thumbnail_antis:
            anti_patterns.append(p.description or p.element)

        return anti_patterns

    def generate_override(
        self,
        analysis: ThumbnailAnalysis,
        use_replace: bool = True,
    ) -> str:
        """Generate Thumbnail Style Override field content.

        Args:
            analysis: Extracted thumbnail elements
            use_replace: Use REPLACE: prefix (full override) vs APPEND:

        Returns:
            Override string for Airtable field
        """
        prefix = "REPLACE:" if use_replace else "APPEND:"

        # Build description parts
        parts = []

        # Colors
        if analysis.colors:
            parts.append(self._describe_colors(analysis.colors))

        # Composition and subject
        if analysis.composition or analysis.subject:
            parts.append(self._describe_composition(
                analysis.composition,
                analysis.subject or {}
            ))

        # Text styling
        if analysis.text:
            parts.append(f"Text: {self._describe_text(analysis.text)}")

        # Overall style
        if analysis.style:
            parts.append(f"Style: {analysis.style}")

        # Anti-patterns to avoid
        anti_patterns = self._get_anti_patterns_to_avoid()
        if anti_patterns:
            avoid_list = ", ".join(anti_patterns[:3])  # Top 3
            parts.append(f"AVOID: {avoid_list}")

        # Combine
        override_text = " ".join(parts)

        return f"{prefix} {override_text}"

    def generate_from_competitor(
        self,
        analysis: ThumbnailAnalysis,
        competitor_title: str,
    ) -> str:
        """Generate override with competitor attribution.

        Args:
            analysis: Extracted thumbnail elements
            competitor_title: Title of competitor video being modeled

        Returns:
            Override string with modeling note
        """
        base_override = self.generate_override(analysis, use_replace=True)

        # Add modeling attribution (useful for experiment tracking)
        return f"{base_override} [Modeling: {competitor_title[:50]}]"
