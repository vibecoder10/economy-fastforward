"""Programmatic Scene List Validation.

Validates the expanded scene list against production requirements before
it enters the pipeline. Supports both the unified scene format (20-30 scenes)
and the legacy flat format (~136 scenes).
"""

from typing import Optional


# Required fields for each scene (unified format with backward-compat aliases)
REQUIRED_FIELDS_UNIFIED = [
    "scene_number", "parent_act", "visual_style", "narration_text",
    "composition", "description",
]

# Legacy required fields (backward compat)
REQUIRED_FIELDS_LEGACY = [
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
    "dossier": (0.60, 0.15),  # target, tolerance (relaxed for 20-30 scenes)
    "schema": (0.22, 0.12),
    "echo": (0.18, 0.12),
}

# Max consecutive same-style scenes
MAX_CONSECUTIVE_SAME_STYLE = 4


def _get_style(scene: dict) -> str:
    """Get style from a scene, supporting both field names."""
    return scene.get("visual_style") or scene.get("style") or ""


def _get_act(scene: dict) -> int:
    """Get act number from a scene, supporting both field names."""
    return scene.get("parent_act") or scene.get("act") or 0


def _get_composition(scene: dict) -> str:
    """Get composition from a scene, supporting both field names."""
    return scene.get("composition") or scene.get("composition_hint") or ""


def validate_scene_list(scenes: list[dict], config: Optional[dict] = None) -> dict:
    """Validate the scene list meets all production requirements.

    Args:
        scenes: List of scene dicts from scene expansion
        config: Optional config with "total_images" or "total_scenes" key

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
    expected = config.get("total_scenes", config.get("total_images", 25))

    if not scenes:
        return {
            "valid": False,
            "issue_count": 1,
            "issues": ["Scene list is empty"],
            "stats": {"total_scenes": 0},
        }

    # 1. Correct total count (allow wider range for dynamic scene counts)
    min_scenes = max(1, int(expected * 0.7))
    max_scenes = int(expected * 1.4)
    if len(scenes) < min_scenes:
        issues.append(f"Too few scenes: {len(scenes)} (expected at least {min_scenes})")
    elif len(scenes) > max_scenes:
        issues.append(f"Too many scenes: {len(scenes)} (expected at most {max_scenes})")

    # 2. Detect format (unified or legacy)
    is_unified = any("parent_act" in s or "visual_style" in s for s in scenes)
    required_fields = REQUIRED_FIELDS_UNIFIED if is_unified else REQUIRED_FIELDS_LEGACY

    # 3. Required fields present (check both formats)
    for i, scene in enumerate(scenes):
        missing = []
        for field in required_fields:
            if field not in scene or not scene[field]:
                # Check backward-compat alias
                aliases = {
                    "parent_act": "act",
                    "visual_style": "style",
                    "narration_text": "script_excerpt",
                    "composition": "composition_hint",
                    "act": "parent_act",
                    "style": "visual_style",
                    "script_excerpt": "narration_text",
                    "composition_hint": "composition",
                }
                alias = aliases.get(field, "")
                if alias and alias in scene and scene[alias]:
                    continue
                missing.append(field)
        if missing:
            issues.append(f"Scene {i+1}: missing fields {missing}")

    # 4. Valid field values
    for i, scene in enumerate(scenes):
        style = _get_style(scene)
        act = _get_act(scene)
        comp = _get_composition(scene)

        if style and style not in VALID_STYLES:
            issues.append(f"Scene {i+1}: invalid style '{style}'")
        if act and act not in VALID_ACTS:
            issues.append(f"Scene {i+1}: invalid act {act}")
        if comp and comp not in VALID_COMPOSITIONS:
            issues.append(f"Scene {i+1}: invalid composition '{comp}'")

    # 5. Style distribution within tolerance
    style_counts = {"dossier": 0, "schema": 0, "echo": 0}
    for scene in scenes:
        style = _get_style(scene)
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

    # 6. No Echo in Acts 1, 2, or 6
    for scene in scenes:
        if _get_style(scene) == "echo" and _get_act(scene) in NO_ECHO_ACTS:
            issues.append(
                f"Scene {scene.get('scene_number', '?')}: Echo in Act {_get_act(scene)} (not allowed)"
            )

    # 7. First and last are Dossier
    if _get_style(scenes[0]) != "dossier":
        issues.append("First scene is not Dossier")
    if _get_style(scenes[-1]) != "dossier":
        issues.append("Last scene is not Dossier")

    # 8. No more than MAX_CONSECUTIVE_SAME_STYLE consecutive same style
    for i in range(len(scenes) - MAX_CONSECUTIVE_SAME_STYLE):
        window = [
            _get_style(scenes[i + j])
            for j in range(MAX_CONSECUTIVE_SAME_STYLE + 1)
        ]
        if len(set(window)) == 1 and window[0]:
            issues.append(
                f"{MAX_CONSECUTIVE_SAME_STYLE + 1}+ consecutive {window[0]} "
                f"at scene {scenes[i].get('scene_number', i + 1)}"
            )

    # 9. No isolated Echo singles
    for i, scene in enumerate(scenes):
        if _get_style(scene) == "echo":
            prev_echo = i > 0 and _get_style(scenes[i - 1]) == "echo"
            next_echo = (
                i < len(scenes) - 1 and _get_style(scenes[i + 1]) == "echo"
            )
            if not prev_echo and not next_echo:
                issues.append(
                    f"Scene {scene.get('scene_number', i + 1)}: Isolated Echo single"
                )

    # 10. Word count check (unified format: total narration should hit 3000-4500 words)
    if is_unified:
        total_words = sum(
            len((s.get("narration_text") or "").split()) for s in scenes
        )
        if total_words > 0:
            if total_words < 2500:
                issues.append(f"Total narration too short: {total_words} words (min 2500)")
            elif total_words > 5000:
                issues.append(f"Total narration too long: {total_words} words (max 5000)")

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
    - Isolated Echo singles (change to Dossier)
    - First/last scene not Dossier
    - Invalid composition hints (default to "medium")
    - Echo in disallowed acts (change to Dossier)
    """
    fixed = [dict(s) for s in scenes]  # Shallow copy

    # Determine style field name
    style_field = "visual_style" if "visual_style" in (fixed[0] if fixed else {}) else "style"
    comp_field = "composition" if "composition" in (fixed[0] if fixed else {}) else "composition_hint"

    # Fix first/last not dossier
    if fixed and _get_style(fixed[0]) != "dossier":
        fixed[0][style_field] = "dossier"
    if fixed and _get_style(fixed[-1]) != "dossier":
        fixed[-1][style_field] = "dossier"

    # Fix Echo in disallowed acts
    for scene in fixed:
        if _get_style(scene) == "echo" and _get_act(scene) in NO_ECHO_ACTS:
            scene[style_field] = "dossier"

    # Fix invalid composition hints
    for scene in fixed:
        if _get_composition(scene) not in VALID_COMPOSITIONS:
            scene[comp_field] = "medium"

    # Fix isolated Echo singles
    for i, scene in enumerate(fixed):
        if _get_style(scene) == "echo":
            prev_echo = i > 0 and _get_style(fixed[i - 1]) == "echo"
            next_echo = i < len(fixed) - 1 and _get_style(fixed[i + 1]) == "echo"
            if not prev_echo and not next_echo:
                fixed[i][style_field] = "dossier"

    # Fix consecutive same-style runs > 4
    for i in range(len(fixed) - MAX_CONSECUTIVE_SAME_STYLE):
        window_styles = [
            _get_style(fixed[i + j])
            for j in range(MAX_CONSECUTIVE_SAME_STYLE + 1)
        ]
        if len(set(window_styles)) == 1 and window_styles[0]:
            mid = i + MAX_CONSECUTIVE_SAME_STYLE // 2
            if _get_style(fixed[mid]) != "schema":
                fixed[mid][style_field] = "schema"

    return fixed
