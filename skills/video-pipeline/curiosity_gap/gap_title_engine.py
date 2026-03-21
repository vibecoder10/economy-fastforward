"""Curiosity gap title generation engine.

Generates titles using 5 curiosity gap structures, scoring each against
story content. Falls back to MF formulas when <3 structures score above
the confidence floor (60).

NOTE: This file is named gap_title_engine.py (NOT title_generator.py)
to avoid confusion with thumbnail_title/title_generator.py which handles
thumbnail text formatting.
"""

from dataclasses import dataclass, field
from typing import List
from curiosity_gap.structures import CuriosityStructure


# Confidence floor - structures must score at least this to generate titles
CONFIDENCE_FLOOR = 60


@dataclass
class ScoredStructure:
    """A curiosity gap structure with its fit score for a story."""
    structure: CuriosityStructure
    confidence: int  # 0-100
    reasoning: str


@dataclass
class GeneratedTitle:
    """A generated title with its curiosity gap metadata."""
    text: str                        # "The $100B Mistake Saudi Arabia Is Hiding"
    structure: CuriosityStructure    # HIDDEN_FLAW
    structure_confidence: int        # 78
    thumbnail_text: str              # "WORTHLESS PIPELINES"
    thumbnail_approach: str          # "from_gap" or "from_hook"
    reasoning: str                   # "Story has clear financial waste angle..."

    # Traceability
    source_patterns: List[str] = field(default_factory=list)       # ["competitor:rec123"]
    competitor_video_ids: List[str] = field(default_factory=list)  # Airtable record IDs
