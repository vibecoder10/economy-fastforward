"""Psychological Angle Assignment.

Assigns psychological angles per act to create a deliberate EMOTIONAL ARC
across the 6-act video structure.

FRAMEWORK vs PSYCH ANGLE (two different things):
- FRAMEWORK = the intellectual lens (constant across the entire video).
  Selected once during outline generation. Lives on Idea Concepts table.
- PSYCHOLOGICAL ANGLE = the emotional lever per act. Creates an arc from
  shock to empowerment. Different angle per act. Lives on Script table.

The emotional arc generally moves from negative emotions (shock, fear,
paranoia) in acts 1-3 toward empowerment and clarity in acts 5-6, with
act 4 as the pivot point (historical pattern recognition).
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Default emotional arc when research payload angles are unavailable.
# Maps act number → (angle name, emotional category).
DEFAULT_ARC = {
    1: "Shock/Betrayal",
    2: "Paranoia/Revelation",
    3: "Fascination with Hidden Mechanism",
    4: "Historical Dread/Recognition",
    5: "Personal Vulnerability",
    6: "Empowerment/Clarity",
}

# Emotional categories for matching research angles to arc positions.
# Each list is ordered by preference — first match wins.
_ARC_SLOT_KEYWORDS = {
    1: ["shock", "betray", "outrage", "disbelief", "pattern interrupt", "alarm"],
    2: ["paranoi", "curiosi", "suspici", "revelat", "unease", "conspira"],
    3: ["fascinat", "intrigue", "mechanism", "hidden", "secret", "schadenfreude"],
    4: ["dread", "histor", "recogni", "forebod", "déjà vu", "pattern", "cycle"],
    5: ["vulnerab", "personal", "anger", "fear", "anxiety", "your", "wallet"],
    6: ["empower", "clarity", "reframe", "tool", "agency", "control", "permanent"],
}


def parse_psych_angles(psychological_angles: str) -> list[str]:
    """Parse psychological_angles text into a list of named angles.

    The research payload's psychological_angles field contains named
    approaches like "Fear of Economic Collapse", "Schadenfreude and
    Reversal of Fortune", etc. — typically as a bulleted or numbered list.

    Returns:
        List of angle name strings (cleaned).
    """
    if not psychological_angles:
        return []

    angles = []
    for line in psychological_angles.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # Strip common list prefixes: "1. ", "1) ", "- ", "* ", "•"
        line = re.sub(r"^[\d]+[.\)]\s*", "", line)
        line = line.lstrip("- •*").strip()
        # Strip bold markdown
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        # Take only the angle name (before any colon/dash explanation)
        if ":" in line:
            line = line.split(":")[0].strip()
        elif " — " in line:
            line = line.split(" — ")[0].strip()
        elif " - " in line and len(line.split(" - ")[0]) > 5:
            line = line.split(" - ")[0].strip()
        if line and len(line) > 3:
            angles.append(line)

    return angles


def _match_angle_to_slot(angle: str, slot: int) -> float:
    """Score how well a research angle matches an arc slot (0.0-1.0)."""
    lower = angle.lower()
    keywords = _ARC_SLOT_KEYWORDS.get(slot, [])
    for i, keyword in enumerate(keywords):
        if keyword in lower:
            # Earlier keywords = stronger match
            return 1.0 - (i * 0.1)
    return 0.0


def assign_angles_to_scenes(
    num_scenes: int,
    psychological_angles: str,
    max_repeats: int = 3,
) -> list[dict]:
    """Assign a psychological angle to each act with a deliberate emotional arc.

    Instead of round-robin rotation, maps research angles to arc positions:
    - Act 1: Shock, betrayal, or pattern interrupt
    - Act 2: Paranoia, curiosity, or revelation
    - Act 3: Fascination with the hidden mechanism
    - Act 4: Historical dread or recognition (pivot point)
    - Act 5: Personal vulnerability or anger
    - Act 6: Empowerment, clarity, or permanent reframe

    If research angles are available, best-matches them to slots.
    Otherwise falls back to the default arc.

    Args:
        num_scenes: Number of acts/scenes to assign angles to (typically 6).
        psychological_angles: Raw text from research payload.
        max_repeats: Unused, kept for API compatibility.

    Returns:
        List of dicts ``[{"scene": 1, "angle": "Shock/Betrayal"}, ...]``.
    """
    angles = parse_psych_angles(psychological_angles)

    if not angles:
        logger.warning("No psychological angles found — using default emotional arc")
        return [
            {"scene": act, "angle": DEFAULT_ARC.get(act, "")}
            for act in range(1, num_scenes + 1)
        ]

    # Match research angles to arc slots using keyword scoring
    assignments = []
    used_angles: set[str] = set()

    for act_num in range(1, num_scenes + 1):
        if act_num > 6:
            # Beyond 6 acts (rare), cycle through defaults
            assignments.append({
                "scene": act_num,
                "angle": DEFAULT_ARC.get(((act_num - 1) % 6) + 1, ""),
            })
            continue

        # Score all unused angles against this slot
        best_angle: Optional[str] = None
        best_score = -1.0

        for angle in angles:
            if angle in used_angles:
                continue
            score = _match_angle_to_slot(angle, act_num)
            if score > best_score:
                best_score = score
                best_angle = angle

        if best_angle and best_score > 0.0:
            assignments.append({"scene": act_num, "angle": best_angle})
            used_angles.add(best_angle)
        else:
            # No good match — use default arc label for this slot
            assignments.append({
                "scene": act_num,
                "angle": DEFAULT_ARC.get(act_num, ""),
            })

    return assignments


def format_psych_arc_summary(assignments: list[dict]) -> str:
    """Format assignments into a readable arc summary for Slack.

    Example output::

        Act 1: Shock → Act 2: Paranoia → Act 3: Fascination → ...
    """
    if not assignments or all(not a["angle"] for a in assignments):
        return ""

    parts = [f"Act {a['scene']}: {a['angle']}" for a in assignments if a["angle"]]
    return " -> ".join(parts)
