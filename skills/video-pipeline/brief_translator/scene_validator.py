"""Programmatic Scene List Validation.

Validates the expanded scene list against production requirements before
it enters the pipeline. Supports both the unified scene format (20-30 scenes)
and the legacy flat format (~136 scenes).
"""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


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

    # 10. Word count check (unified format)
    # Use config-driven thresholds when available, else legacy defaults.
    word_min = int(config.get("script_min_words", 2000) * 0.9) if config.get("script_min_words") else 2000
    word_max_warn = config.get("script_max_words", 3200)
    word_max_hard = int(word_max_warn * 1.1) if config.get("script_max_words") else 3500

    if is_unified:
        total_words = sum(
            len((s.get("narration_text") or "").split()) for s in scenes
        )
        if total_words > 0:
            if total_words < word_min:
                issues.append(f"Total narration too short: {total_words} words (min {word_min})")
            elif total_words > word_max_hard:
                issues.append(f"REJECT: Total narration too long: {total_words} words (hard max {word_max_hard})")
            elif total_words > word_max_warn:
                # Warning level — log but don't block
                logger.warning(
                    f"Total narration over target: {total_words} words (target max {word_max_warn})"
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


def validate_act6_empowerment(act6_text: str) -> dict:
    """Check that Act 6 ends with empowerment, not dread.

    Looks for explicit framework names and detection instructions.
    Returns {"valid": bool, "issues": list[str]}.
    """
    issues: list[str] = []
    if not act6_text:
        return {"valid": True, "issues": []}

    text_lower = act6_text.lower()

    # Check for dread/helpless close patterns
    _DREAD_PATTERNS = [
        "nobody will notice",
        "no one will notice",
        "before it's too late",
        "before the window closes",
        "whether anyone will notice",
        "the cage is closing",
        "you're trapped",
        "there's nothing you can do",
    ]
    for pattern in _DREAD_PATTERNS:
        if pattern in text_lower:
            issues.append(
                f"Act 6 contains dread/helpless language: '{pattern}'. "
                "The close MUST be empowerment, not fear."
            )

    # Check for framework name mentions (at least one explicit naming)
    # Look for patterns like "you just learned X", "X, Y, and Z", quoted names
    _EMPOWERMENT_SIGNALS = [
        "you just learned",
        "you now ",
        "you now know",
        "you now see",
        "you now read",
        "pattern recognition",
        "x-ray vision",
        "when you see",
        "when you notice",
        "look for",
        "ask who",
        "ask why",
        "watch who",
        "watch what",
        "watch for",
    ]
    empowerment_count = sum(1 for s in _EMPOWERMENT_SIGNALS if s in text_lower)
    if empowerment_count < 2:
        issues.append(
            f"Act 6 lacks empowerment signals (found {empowerment_count}, need >=2). "
            "Must contain framework names + detection instructions."
        )

    return {
        "valid": len(issues) == 0,
        "issues": issues,
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


# ---------------------------------------------------------------------------
# Entity consistency checking — catches hallucinated proper nouns
# ---------------------------------------------------------------------------

# Well-known framework authors / historical figures that are always allowed
# because the script engine references them as part of analytical frameworks.
_FRAMEWORK_ENTITIES = {
    "machiavelli", "greene", "robert greene", "sun tzu", "thucydides",
    "taleb", "nassim taleb", "brzezinski", "mackinder", "spykman",
    "kindleberger", "schelling", "olson", "mancur olson", "nye",
    "joseph nye", "jung", "kahneman", "tversky", "thaler", "gramsci",
    "bernays", "chomsky", "marcus aurelius", "seneca", "graham allison",
    "athens", "sparta", "rome", "ottoman", "british empire",
}

# Multiple regex patterns to catch different proper noun styles:
# 1. Multi-word proper nouns: "Sam Altman", "Goldman Sachs"
_MULTI_WORD_PN_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")
# 2. CamelCase / mixed-case: "DeepSeek", "OpenAI", "iPhone"
_CAMEL_CASE_RE = re.compile(r"\b([A-Z][a-z]+[A-Z][A-Za-z]*)\b")
# 3. Single capitalized words (4+ chars to skip "The", "And", etc.)
_SINGLE_CAP_RE = re.compile(r"\b([A-Z][a-z]{3,})\b")
# 4. All-caps acronyms (2+ chars): "IBM", "NATO", "OPEC"
_ACRONYM_RE = re.compile(r"\b([A-Z]{2,})\b")

# Common English words that start with a capital letter at sentence starts.
# We skip these to reduce false positives.
_COMMON_WORDS = {
    "this", "that", "these", "those", "there", "their", "they",
    "what", "when", "where", "which", "while", "with", "will",
    "from", "have", "here", "been", "being", "before", "after",
    "about", "above", "also", "always", "another", "because",
    "between", "both", "could", "does", "done", "during", "each",
    "either", "enough", "even", "every", "first", "found", "gave",
    "give", "goes", "going", "gone", "good", "great", "just",
    "keep", "know", "last", "like", "long", "look", "made", "make",
    "many", "might", "more", "most", "much", "must", "never", "next",
    "once", "only", "other", "over", "part", "past", "same", "should",
    "show", "since", "some", "still", "such", "take", "tell", "than",
    "then", "them", "think", "thought", "through", "time", "turn",
    "under", "used", "very", "want", "well", "were", "would", "your",
    "into", "back", "came", "come", "down", "face", "fact", "five",
    "four", "hand", "head", "high", "home", "kind", "left", "life",
    "line", "move", "name", "need", "news", "note", "number", "open",
    "play", "point", "power", "real", "right", "room", "rule", "seem",
    "side", "small", "stand", "start", "state", "story", "sure",
    "thing", "three", "today", "true", "until", "upon", "watch",
    "week", "work", "world", "year", "years",
    # Script-specific common words that often get capitalized
    "hook", "build", "payoff", "bridge", "lesson", "stakes",
    "framework", "mechanism", "mirror", "foundation", "history",
    "dark", "revelation", "pattern", "system", "empire", "stage",
}


def _extract_entities_from_text(text: str) -> set[str]:
    """Extract likely proper nouns from a block of text.

    Returns a set of lowercased entity strings for easy comparison.
    """
    entities: set[str] = set()

    for pattern in (_MULTI_WORD_PN_RE, _CAMEL_CASE_RE, _SINGLE_CAP_RE, _ACRONYM_RE):
        for m in pattern.findall(text):
            lowered = m.lower()
            # Skip very short matches and common English words
            if len(m) <= 2 or lowered in _COMMON_WORDS:
                continue
            entities.add(lowered)

    return entities


def _extract_research_entities(brief: dict) -> set[str]:
    """Extract all proper nouns / entity names from the research payload.

    Combines entities from headline, thesis, fact_sheet, character_dossier,
    historical_parallels, and other research fields.
    """
    research_fields = [
        "headline", "thesis", "executive_hook", "fact_sheet",
        "historical_parallels", "framework_analysis", "character_dossier",
        "narrative_arc", "counter_arguments", "visual_seeds",
        "source_bibliography", "source_urls",
    ]
    all_text = " ".join(str(brief.get(f, "")) for f in research_fields)
    return _extract_entities_from_text(all_text)


# Regex to strip act marker lines before entity extraction
_ACT_MARKER_LINE_RE = re.compile(
    r"\[ACT\s+\d+\s*[—–\-].*?\]", re.IGNORECASE
)


def check_entity_consistency(
    script: str,
    brief: dict,
    slack_client=None,
    video_title: str = "",
) -> list[str]:
    """Check that entities in the script are grounded in the research payload.

    This is a WARNING-level check, not a blocker. It extracts proper nouns
    from both the research payload and the script, then flags any script
    entities that don't appear in the research.

    Args:
        script: The full generated script text.
        brief: The research brief dict.
        slack_client: Optional SlackClient for sending warnings.
        video_title: Video title for Slack messages.

    Returns:
        List of warning strings for any ungrounded entities found.
    """
    research_entities = _extract_research_entities(brief)

    # Strip act marker lines so their titles don't generate false positives
    cleaned_script = _ACT_MARKER_LINE_RE.sub("", script)
    script_entities = _extract_entities_from_text(cleaned_script)

    # Also add the headline words as allowed (the title itself is fair game)
    headline = brief.get("headline", "")
    research_entities |= _extract_entities_from_text(headline)

    # Framework entities are always allowed
    allowed = research_entities | _FRAMEWORK_ENTITIES

    # Find entities in script that are NOT in the research
    ungrounded = script_entities - allowed

    warnings = []
    if ungrounded:
        # Try to locate which scene/act each ungrounded entity appears in
        # by scanning the script with act markers
        from .script_generator import extract_acts
        acts = extract_acts(script)

        for entity in sorted(ungrounded):
            # Find which act(s) reference this entity
            locations = []
            for act_num, act_text in acts.items():
                if entity in act_text.lower():
                    locations.append(f"Act {act_num}")

            location_str = ", ".join(locations) if locations else "unknown location"
            warning = (
                f"WARNING: '{entity}' found in script ({location_str}) "
                f"but not in research payload. Possible hallucination."
            )
            warnings.append(warning)
            logger.warning(warning)

        # Send summary to Slack if available
        if slack_client and warnings:
            title_label = video_title or brief.get("headline", "Untitled")
            slack_msg = (
                f"⚠️ Entity consistency check for '{title_label}':\n"
                + "\n".join(warnings[:10])  # Cap at 10 to avoid spam
            )
            try:
                slack_client.send_message(slack_msg)
            except Exception:
                pass

    return warnings
