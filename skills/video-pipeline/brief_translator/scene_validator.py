"""Programmatic Scene List Validation.

Validates the expanded scene list against production requirements before
it enters the pipeline.
"""

from typing import Optional


# Required fields for each scene
REQUIRED_FIELDS = [
    "scene_number", "act", "style", "description",
    "script_excerpt", "composition_hint",
]

# Valid values
VALID_STYLES = {"dossier", "schema", "echo"}
VALID_ACTS = {1, 2, 3, 4, 5, 6}
VALID_COMPOSITIONS = {
    "wide", "medium", "closeup", "environmental",
    "portrait", "overhead", "low_angle",
}

# Acts where Echo style is not allowed
NO_ECHO_ACTS = {1, 2, 6}

# Style distribution targets and tolerances
STYLE_TARGETS = {
    "dossier": (0.60, 0.12),  # target, tolerance
    "schema": (0.22, 0.10),
    "echo": (0.18, 0.10),
}

# Max consecutive same-style scenes
MAX_CONSECUTIVE_SAME_STYLE = 4


def validate_scene_list(scenes: list[dict], config: Optional[dict] = None) -> dict:
    """Validate the scene list meets all production requirements.

    Args:
        scenes: List of scene dicts from scene expansion
        config: Optional config with "total_images" key

    Returns:
        {
            "valid": bool,
            "issue_count": int,
            "issues": list[str],
            "stats": dict,
        }
    """
    if config is None:
        config = {}

    issues = []
    expected = config.get("total_images", 136)

    if not scenes:
        return {
            "valid": False,
            "issue_count": 1,
            "issues": ["Scene list is empty"],
            "stats": {"total_scenes": 0},
        }

    # 1. Correct total count
    if len(scenes) < expected * 0.9:
        issues.append(f"Too few scenes: {len(scenes)} vs {expected} expected")

    # 2. All required fields present
    for i, scene in enumerate(scenes):
        for field in REQUIRED_FIELDS:
            if field not in scene or not scene[field]:
                issues.append(f"Scene {i+1}: missing field '{field}'")

    # 3. Valid field values
    for i, scene in enumerate(scenes):
        if scene.get("style") and scene["style"] not in VALID_STYLES:
            issues.append(f"Scene {i+1}: invalid style '{scene['style']}'")
        if scene.get("act") and scene["act"] not in VALID_ACTS:
            issues.append(f"Scene {i+1}: invalid act {scene['act']}")
        if scene.get("composition_hint") and scene["composition_hint"] not in VALID_COMPOSITIONS:
            issues.append(f"Scene {i+1}: invalid composition '{scene['composition_hint']}'")

    # 4. Style distribution within tolerance
    style_counts = {"dossier": 0, "schema": 0, "echo": 0}
    for scene in scenes:
        style = scene.get("style", "")
        if style in style_counts:
            style_counts[style] += 1

    total = len(scenes)
    dossier_pct = style_counts["dossier"] / total if total > 0 else 0
    schema_pct = style_counts["schema"] / total if total > 0 else 0
    echo_pct = style_counts["echo"] / total if total > 0 else 0

    for style, (target, tolerance) in STYLE_TARGETS.items():
        actual = style_counts[style] / total if total > 0 else 0
        if abs(actual - target) > tolerance:
            issues.append(
                f"{style.title()} distribution off: {actual:.0%} vs ~{target:.0%} target"
            )

    # 5. No Echo in Acts 1, 2, or 6
    for scene in scenes:
        if scene.get("style") == "echo" and scene.get("act") in NO_ECHO_ACTS:
            issues.append(
                f"Scene {scene.get('scene_number', '?')}: Echo in Act {scene['act']} (not allowed)"
            )

    # 6. First and last are Dossier
    if scenes[0].get("style") != "dossier":
        issues.append("First scene is not Dossier")
    if scenes[-1].get("style") != "dossier":
        issues.append("Last scene is not Dossier")

    # 7. No more than MAX_CONSECUTIVE_SAME_STYLE consecutive same style
    for i in range(len(scenes) - MAX_CONSECUTIVE_SAME_STYLE):
        window = [
            scenes[i + j].get("style")
            for j in range(MAX_CONSECUTIVE_SAME_STYLE + 1)
        ]
        if len(set(window)) == 1 and window[0] is not None:
            issues.append(
                f"{MAX_CONSECUTIVE_SAME_STYLE + 1}+ consecutive {window[0]} "
                f"at scene {scenes[i].get('scene_number', i + 1)}"
            )

    # 8. No isolated Echo singles
    for i, scene in enumerate(scenes):
        if scene.get("style") == "echo":
            prev_echo = i > 0 and scenes[i - 1].get("style") == "echo"
            next_echo = (
                i < len(scenes) - 1 and scenes[i + 1].get("style") == "echo"
            )
            if not prev_echo and not next_echo:
                issues.append(
                    f"Scene {scene.get('scene_number', i + 1)}: Isolated Echo single"
                )

    # 9. No duplicate descriptions (fuzzy check on first 50 chars)
    descriptions = [s.get("description", "").lower()[:50] for s in scenes]
    seen = set()
    for i, desc in enumerate(descriptions):
        if desc and desc in seen:
            issues.append(
                f"Scene {scenes[i].get('scene_number', i + 1)}: Possible duplicate description"
            )
        if desc:
            seen.add(desc)

    # 10. Composition variety within same-style runs of 4
    for i in range(len(scenes) - 3):
        if (
            scenes[i].get("style")
            == scenes[i + 1].get("style")
            == scenes[i + 2].get("style")
            == scenes[i + 3].get("style")
        ):
            comps = [scenes[i + j].get("composition_hint", "") for j in range(4)]
            if len(set(comps)) < 3:
                issues.append(
                    f"Low composition variety in {scenes[i]['style']} run "
                    f"at scene {scenes[i].get('scene_number', i + 1)}: {comps}"
                )

    return {
        "valid": len(issues) == 0,
        "issue_count": len(issues),
        "issues": issues,
        "stats": {
            "total_scenes": len(scenes),
            "dossier": f"{dossier_pct:.0%}",
            "schema": f"{schema_pct:.0%}",
            "echo": f"{echo_pct:.0%}",
        },
    }


def auto_fix_minor_issues(scenes: list[dict]) -> list[dict]:
    """Attempt to programmatically fix minor scene list issues.

    Fixes:
    - Isolated Echo singles (merge into nearest Echo cluster or change to Dossier)
    - First/last scene not Dossier
    - Invalid composition hints (default to "medium")
    - Echo in disallowed acts (change to Dossier)

    Returns:
        Fixed copy of the scene list.
    """
    fixed = [dict(s) for s in scenes]  # Deep-ish copy

    # Fix first/last not dossier
    if fixed and fixed[0].get("style") != "dossier":
        fixed[0]["style"] = "dossier"
    if fixed and fixed[-1].get("style") != "dossier":
        fixed[-1]["style"] = "dossier"

    # Fix Echo in disallowed acts
    for scene in fixed:
        if scene.get("style") == "echo" and scene.get("act") in NO_ECHO_ACTS:
            scene["style"] = "dossier"

    # Fix invalid composition hints
    for scene in fixed:
        if scene.get("composition_hint") not in VALID_COMPOSITIONS:
            scene["composition_hint"] = "medium"

    # Fix isolated Echo singles
    for i, scene in enumerate(fixed):
        if scene.get("style") == "echo":
            prev_echo = i > 0 and fixed[i - 1].get("style") == "echo"
            next_echo = i < len(fixed) - 1 and fixed[i + 1].get("style") == "echo"
            if not prev_echo and not next_echo:
                # Change isolated echo to dossier
                fixed[i]["style"] = "dossier"

    # Fix consecutive same-style runs > 4 by swapping middle scenes
    for i in range(len(fixed) - MAX_CONSECUTIVE_SAME_STYLE):
        window_styles = [
            fixed[i + j].get("style")
            for j in range(MAX_CONSECUTIVE_SAME_STYLE + 1)
        ]
        if len(set(window_styles)) == 1 and window_styles[0] is not None:
            # Swap the middle scene to schema (least disruptive)
            mid = i + MAX_CONSECUTIVE_SAME_STYLE // 2
            if fixed[mid]["style"] != "schema":
                fixed[mid]["style"] = "schema"

    return fixed
