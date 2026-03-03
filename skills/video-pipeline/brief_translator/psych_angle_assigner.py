"""Psychological Angle Assignment.

Distributes psychological angles from the research payload across script
scenes, ensuring variety through a rotation constraint (max 3 uses per
angle in a 20-scene video).
"""

import re
import logging

logger = logging.getLogger(__name__)

# Maximum times a single angle can appear across all scenes
MAX_ANGLE_REPEATS = 3


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


def assign_angles_to_scenes(
    num_scenes: int,
    psychological_angles: str,
    max_repeats: int = MAX_ANGLE_REPEATS,
) -> list[dict]:
    """Assign a psychological angle to each scene with rotation.

    Cycles through available angles round-robin, skipping any that have
    hit ``max_repeats``.  If all angles are exhausted (rare edge case for
    very long videos with few angles), usage counts are reset and the
    cycle restarts.

    Args:
        num_scenes: Number of scenes to assign angles to.
        psychological_angles: Raw text from ``research_payload["psychological_angles"]``.
        max_repeats: Maximum times any single angle can appear.

    Returns:
        List of dicts ``[{"scene": 1, "angle": "Fear of Economic Collapse"}, ...]``.
    """
    angles = parse_psych_angles(psychological_angles)

    if not angles:
        logger.warning("No psychological angles found in research payload")
        return [{"scene": i + 1, "angle": ""} for i in range(num_scenes)]

    assignments = []
    usage_count = {a: 0 for a in angles}
    angle_index = 0

    for scene_num in range(1, num_scenes + 1):
        # Find the next available angle under the repeat cap
        assigned = False
        for _ in range(len(angles)):
            candidate = angles[angle_index % len(angles)]
            if usage_count[candidate] < max_repeats:
                assignments.append({"scene": scene_num, "angle": candidate})
                usage_count[candidate] += 1
                angle_index += 1
                assigned = True
                break
            angle_index += 1

        if not assigned:
            # All angles hit the cap — pick the least-used angle to keep
            # distribution as even as possible.
            least_used = min(angles, key=lambda a: usage_count[a])
            assignments.append({"scene": scene_num, "angle": least_used})
            usage_count[least_used] += 1

    return assignments


def format_psych_arc_summary(assignments: list[dict]) -> str:
    """Format assignments into a readable arc summary for Slack.

    Groups consecutive scenes that share the same angle.

    Example output::

        Scene 1-3: Fear of Economic Collapse → Scene 4-6: Schadenfreude → ...
    """
    if not assignments or all(not a["angle"] for a in assignments):
        return ""

    groups: list[str] = []
    current_angle = assignments[0]["angle"]
    start_scene = assignments[0]["scene"]
    end_scene = start_scene

    for a in assignments[1:]:
        if a["angle"] == current_angle:
            end_scene = a["scene"]
        else:
            if start_scene == end_scene:
                groups.append(f"Scene {start_scene}: {current_angle}")
            else:
                groups.append(f"Scene {start_scene}-{end_scene}: {current_angle}")
            current_angle = a["angle"]
            start_scene = a["scene"]
            end_scene = a["scene"]

    # Last group
    if start_scene == end_scene:
        groups.append(f"Scene {start_scene}: {current_angle}")
    else:
        groups.append(f"Scene {start_scene}-{end_scene}: {current_angle}")

    return " → ".join(groups)
