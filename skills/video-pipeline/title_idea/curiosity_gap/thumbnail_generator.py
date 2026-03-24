"""Yin/yang thumbnail text generator.

The thumbnail text should COMPLEMENT the title, not repeat it.
Two approaches:
- from_gap: Reveals the answer/consequence the title withholds
- from_hook: Shows a surprising detail from the hook script

This module handles text selection and formatting. The actual thumbnail
IMAGE generation is handled by thumbnail_title/title_generator.py.
"""

from dataclasses import dataclass
from typing import List
from title_idea.curiosity_gap.structures import CuriosityStructure


VALID_APPROACHES = ["from_hook", "from_gap"]

# Words to strip from thumbnail text
FILLER_WORDS = {"the", "a", "an", "is", "are", "was", "were", "of", "to", "in", "for"}

# Structure -> preferred approach mapping
STRUCTURE_APPROACH_PREFERENCE = {
    CuriosityStructure.HIDDEN_FLAW: "from_gap",      # Reveal the consequence
    CuriosityStructure.ASYMMETRIC_DG: "from_hook",   # Show the surprising detail
    CuriosityStructure.TIME_BOMB: "from_gap",        # Hint at what triggers
    CuriosityStructure.PARADIGM_SHIFT: "from_gap",   # Hint at the truth
    CuriosityStructure.ILLUSION_CONTROL: "from_hook", # Show the personal impact
    CuriosityStructure.OTHER: "from_gap",            # Default to from_gap
}


@dataclass
class ThumbnailText:
    """Generated yin/yang thumbnail text."""
    text: str            # "WORTHLESS PIPELINES"
    approach: str        # "from_gap" or "from_hook"
    reasoning: str       # Why this approach was chosen


def format_thumbnail_text(raw_text: str, max_words: int = 4) -> str:
    """Format text for thumbnail display.

    - Converts to ALL CAPS
    - Removes filler words (the, a, an, etc.)
    - Truncates to max_words

    Args:
        raw_text: Raw text to format
        max_words: Maximum words to include

    Returns:
        Formatted thumbnail text in ALL CAPS
    """
    if not raw_text:
        return ""

    # Split into words
    words = raw_text.upper().split()

    # Remove filler words
    filtered = [w for w in words if w.lower() not in FILLER_WORDS]

    # Use original if all words were filler
    if not filtered:
        filtered = words

    # Truncate to max words
    truncated = filtered[:max_words]

    return " ".join(truncated)


def select_approach(
    structure: CuriosityStructure,
    title: str,
    hook: str,
) -> str:
    """Select thumbnail approach based on structure and content.

    Args:
        structure: The curiosity gap structure being used
        title: The video title
        hook: The hook script text

    Returns:
        "from_hook" or "from_gap"
    """
    # Use structure preference as default
    return STRUCTURE_APPROACH_PREFERENCE.get(structure, "from_gap")
