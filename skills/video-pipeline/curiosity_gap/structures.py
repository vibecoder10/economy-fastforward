# skills/video-pipeline/curiosity_gap/structures.py
"""Curiosity gap structure definitions.

The 5 curiosity gap structures create cognitive dissonance that forces clicks:
1. hidden_flaw - "What mistake are they hiding?"
2. asymmetric_dg - "How does small beat big?"
3. time_bomb - "What trap was set?"
4. paradigm_shift - "What am I missing?"
5. illusion_control - "How does this affect ME?"
6. other - Novel pattern for review
"""

from enum import Enum
from typing import Dict, List


class CuriosityStructure(str, Enum):
    """Valid curiosity gap structure IDs."""
    HIDDEN_FLAW = "hidden_flaw"
    ASYMMETRIC_DG = "asymmetric_dg"
    TIME_BOMB = "time_bomb"
    PARADIGM_SHIFT = "paradigm_shift"
    ILLUSION_CONTROL = "illusion_control"
    OTHER = "other"


# Structure definitions with gap mechanisms and examples
STRUCTURE_DEFINITIONS: Dict[CuriosityStructure, Dict[str, str]] = {
    CuriosityStructure.HIDDEN_FLAW: {
        "gap_mechanism": "What's the mistake they're hiding?",
        "when_to_use": "Financial waste, failed strategies, cover-ups",
        "example": "The $100B Mistake Saudi Arabia Is Hiding",
    },
    CuriosityStructure.ASYMMETRIC_DG: {
        "gap_mechanism": "How does small beat big?",
        "when_to_use": "Power imbalances, unexpected advantages",
        "example": "Why the Navy Is Terrified of $500 Plastic",
    },
    CuriosityStructure.TIME_BOMB: {
        "gap_mechanism": "What trap was set? When does it trigger?",
        "when_to_use": "Long-term strategies, delayed consequences",
        "example": "The 40-Year Trap America Walked Into",
    },
    CuriosityStructure.PARADIGM_SHIFT: {
        "gap_mechanism": "What reality am I missing?",
        "when_to_use": "Reframing events, hidden truths",
        "example": "The Map That Proves WWIII Already Begun",
    },
    CuriosityStructure.ILLUSION_CONTROL: {
        "gap_mechanism": "How does this affect ME personally?",
        "when_to_use": "Personal stakes, economic impacts",
        "example": "The Chokepoint That Controls Your Bank Account",
    },
    CuriosityStructure.OTHER: {
        "gap_mechanism": "Novel pattern — flag for review",
        "when_to_use": "Doesn't fit above structures",
        "example": "Logged for weekly digest clustering",
    },
}


def get_structure_prompt() -> str:
    """Generate Claude prompt text listing all structures.

    Returns:
        Formatted prompt section for structure analysis
    """
    lines = ["STRUCTURES:"]
    for i, structure in enumerate(CuriosityStructure, 1):
        if structure == CuriosityStructure.OTHER:
            lines.append(f"{i}. {structure.value} - Doesn't fit above (describe the pattern)")
        else:
            defn = STRUCTURE_DEFINITIONS[structure]
            lines.append(f"{i}. {structure.value} - \"{defn['gap_mechanism']}\"")
    return "\n".join(lines)


def validate_structure(structure_str: str) -> CuriosityStructure:
    """Validate and normalize a structure string.

    Args:
        structure_str: Structure identifier from Claude response

    Returns:
        CuriosityStructure enum (defaults to OTHER if invalid)
    """
    if not structure_str:
        return CuriosityStructure.OTHER

    normalized = structure_str.lower().strip()

    try:
        return CuriosityStructure(normalized)
    except ValueError:
        return CuriosityStructure.OTHER


def get_main_structures() -> List[CuriosityStructure]:
    """Get the 5 main structures (excluding OTHER).

    Returns:
        List of main CuriosityStructure values
    """
    return [s for s in CuriosityStructure if s != CuriosityStructure.OTHER]
