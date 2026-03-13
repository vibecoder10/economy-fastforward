"""
Prompt builder for the Holographic Intelligence Display system.

Takes scene descriptions and sequencing metadata, produces fully constructed
image generation prompts for the holographic intelligence display aesthetic.

When a visual profile is loaded, reads prefix/suffix/figure rules from the
profile. Falls back to hardcoded defaults when no profile is available.

Version: 4.0 (Mar 2026) — Holographic Intelligence Display system
"""

from __future__ import annotations

import re
from typing import Optional


# ---------------------------------------------------------------------------
# Profile integration — thin adapter with hardcoded fallbacks
# ---------------------------------------------------------------------------

def _get_profile():
    """Return the active visual profile, or None."""
    try:
        from visual_profiles import load_profile
        return load_profile()
    except Exception:
        return None

from .style_config import (
    ColorMood,
    COLOR_MOOD_CONFIG,
    COLOR_MOOD_KEYWORDS,
    COLOR_MOOD_PRIORITY,
    ContentType,
    CONTENT_TYPE_KEYWORDS,
    DisplayFormat,
    DISPLAY_FORMAT_CONFIG,
    HOLOGRAPHIC_SUFFIX,
    DEFAULT_CONFIG,
    resolve_color_mood,
    resolve_content_type,
    resolve_display_format,
    get_accent_color_to_mood,
    get_category_to_mood,
)
from .sequencer import assign_styles


# ---------------------------------------------------------------------------
# No-people validation
# ---------------------------------------------------------------------------

PEOPLE_WORDS = [
    "officer", "officers", "commander", "analyst", "operator", "operators",
    "figure", "figures", "person", "people", "man", "woman", "soldier",
    "soldiers", "guard", "guards", "hand", "hands", "silhouette",
    "silhouettes", "face", "faces", "human", "crew", "staff",
    "seated", "standing", "watching", "huddle", "checking", "dials",
]


_PEOPLE_PATTERNS = [re.compile(rf"\b{re.escape(w)}\b", re.IGNORECASE) for w in PEOPLE_WORDS]


def validate_no_people(prompt: str) -> tuple[bool, list[str]]:
    """Check an image prompt for people-related words (word-boundary match).

    Returns (is_clean, list_of_violations).
    """
    violations = [w for w, pat in zip(PEOPLE_WORDS, _PEOPLE_PATTERNS) if pat.search(prompt)]
    return (len(violations) == 0, violations)


# ---------------------------------------------------------------------------
# Style-language patterns to strip from scene descriptions
# ---------------------------------------------------------------------------
_STYLE_STRIP_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bcinematic(?:\s+photorealistic)?\b",
        r"\bphotorealistic\b",
        r"\bholographic\b",
        r"\b16:\s?9\b",
        r"\b8K\s+resolution\b",
        r"\bshallow depth of field\b",
        r"\bfilm grain\b",
    ]
]


# ---------------------------------------------------------------------------
# People-word replacements for auto-rewriting prompts
# ---------------------------------------------------------------------------
_PEOPLE_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(p, re.IGNORECASE), r)
    for p, r in [
        (r"\bofficers?\s+(?:at|huddle\w*\s+around|seated\s+at)\s+\w+", "unmanned consoles with active displays"),
        (r"\bcommander\s+\w+\s+\w+", "command terminal with priority alerts flashing"),
        (r"\banalyst\s+workstation", "workstation with open data feeds"),
        (r"\boperators?\s+(?:at|seated\s+at|monitoring)\s+\w+", "autonomous monitoring stations"),
        (r"\bofficers?\b", "autonomous terminals"),
        (r"\bcommander\b", "command terminal"),
        (r"\banalysts?\b", "data terminals"),
        (r"\boperators?\b", "monitoring stations"),
        (r"\bfigures?\b", "equipment"),
        (r"\bperson\b", "terminal"),
        (r"\bpeople\b", "unmanned equipment"),
        (r"\bsoldiers?\b", "military hardware"),
        (r"\bguards?\b", "security sensors"),
        (r"\bsilhouettes?\b", "equipment outlines"),
        (r"\bhuman\b", "autonomous"),
        (r"\bcrew\b", "autonomous systems"),
        (r"\bstaff\b", "automated systems"),
        (r"\bseated\b", "positioned"),
        (r"\bstanding\b", "mounted"),
        (r"\bwatching\b", "scanning"),
        (r"\bhuddle\b", "cluster"),
        (r"\bchecking\b", "processing"),
        (r"\bdials\b", "activates"),
        (r"\bhands?\b", "sensors"),
        (r"\bfaces?\b", "displays"),
        (r"\bman\b", "unit"),
        (r"\bwoman\b", "unit"),
    ]
]


def _remove_people_references(description: str) -> str:
    """Replace people-related words with unmanned equipment equivalents."""
    result = description
    for pattern, replacement in _PEOPLE_REPLACEMENTS:
        result = pattern.sub(replacement, result)
    return result


def _apply_profile_people_replacements(description: str, figure_rules) -> str:
    """Apply profile-specific people-word replacements.

    Reads ``people_replacements`` from the profile's FigureRulesConfig and
    applies them as regex substitutions.
    """
    result = description
    for pattern_str, replacement in (figure_rules.people_replacements or []):
        try:
            result = re.sub(pattern_str, replacement, result, flags=re.IGNORECASE)
        except re.error:
            pass
    return result


def _strip_style_language(description: str) -> str:
    """Remove style/lighting/camera language from a scene description."""
    cleaned = description
    for pat in _STYLE_STRIP_PATTERNS:
        cleaned = pat.sub("", cleaned)
    cleaned = re.sub(r",\s*,", ",", cleaned)
    cleaned = re.sub(r"^\s*,\s*", "", cleaned)
    cleaned = re.sub(r"\s*,\s*$", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def resolve_scene_color_mood(
    scene_description: str,
    video_color_mood: str = "strategic",
) -> str:
    """Pick a color mood for a single image based on scene content.

    Scans *scene_description* for keyword matches in COLOR_MOOD_KEYWORDS.
    Returns the mood value with the most hits. Falls back to *video_color_mood*.
    """
    mood = resolve_color_mood(scene_description)
    # If resolve_color_mood found keywords, use that; otherwise fall back
    text_lower = scene_description.lower()
    has_any_hit = False
    for keywords in COLOR_MOOD_KEYWORDS.values():
        if any(kw in text_lower for kw in keywords):
            has_any_hit = True
            break
    if has_any_hit:
        return mood.value
    return video_color_mood


def build_prompt(
    scene_description: str,
    content_type: str,
    display_format: str,
    color_mood: str,
    image_style_override: Optional[str] = None,
) -> str:
    """Assemble a complete image generation prompt.

    When a visual profile is active, reads framing, suffix, and figure rules
    from the profile. Falls back to holographic defaults when no profile is
    loaded or the profile is ``holographic_hud``.

    Template (holographic)::

        [DISPLAY FORMAT framing] [DISPLAY CONTENT] [COLOR MOOD] [UNIVERSAL SUFFIX]

    Template (other profiles)::

        [STYLE PREFIX] [DISPLAY CONTENT] [STYLE SUFFIX]

    Parameters
    ----------
    scene_description : str
        What the image depicts — the analytical content description.
    content_type : str
        Value from ContentType enum (e.g. ``"geographic_map"``).
    display_format : str
        Value from DisplayFormat enum (e.g. ``"war_table"``).
    color_mood : str
        Value from ColorMood enum (e.g. ``"strategic"``).
    image_style_override : str, optional
        Per-video style override from Airtable.

    Returns
    -------
    str
        The complete prompt string, ready for image generation.
    """
    profile = _get_profile()
    is_holographic = (
        profile is None
        or profile.profile_id == "holographic_hud"
    )

    # Clean scene description
    clean_desc = _strip_style_language(scene_description).rstrip(". ")

    # --- Figure rules: profile-driven ---
    if is_holographic:
        # Holographic: no people at all — replace with unmanned equipment
        is_clean, violations = validate_no_people(clean_desc)
        if not is_clean:
            clean_desc = _remove_people_references(clean_desc)
    elif profile and profile.figure_rules:
        fr = profile.figure_rules
        if fr.allow_mannequins:
            # Mannequin style: replace human words with mannequin equivalents
            clean_desc = _apply_profile_people_replacements(clean_desc, fr)
        elif not fr.allow_human_figures:
            # Other no-people profiles: use profile-specific word list
            clean_desc = _apply_profile_people_replacements(clean_desc, fr)

    if is_holographic:
        # --- Holographic path: framing + content + mood + suffix ---
        fmt_enum = _format_from_value(display_format)
        framing = DISPLAY_FORMAT_CONFIG[fmt_enum]["framing"]

        mood_enum = _mood_from_value(color_mood)
        mood_language = COLOR_MOOD_CONFIG[mood_enum]["prompt_language"]

        if image_style_override and image_style_override.strip():
            mood_language = _apply_style_override(mood_language, image_style_override)

        suffix = profile.style_system.style_suffix if profile else HOLOGRAPHIC_SUFFIX
        return f"{framing} {clean_desc}, {mood_language}{suffix}"
    else:
        # --- Profile path: prefix + content + global suffix ---
        prefix = profile.style_system.style_prefix if profile.style_system.style_prefix else ""
        global_suffix = profile.style_system.style_suffix if profile.style_system.style_suffix else ""

        # Strip prefix from description if Claude already included it
        # (the system prompt instructs Claude to open with the style anchor)
        if prefix and clean_desc.lower().startswith(prefix.lower()):
            clean_desc = clean_desc[len(prefix):].strip().lstrip(",").strip()

        # NOTE: substyle.suffix (e.g. "two or more mannequin figures in tension...")
        # is intentionally NOT appended here. Those are scene type INSTRUCTIONS
        # that guide Claude's prompt writing (via system prompt), not literal
        # text for the image model. Scene type is classified BEFORE writing
        # and passed to Claude as guidance in scene_expander.py.

        if image_style_override and image_style_override.strip():
            global_suffix = _apply_style_override(global_suffix, image_style_override)

        return f"{prefix} {clean_desc}{global_suffix}"


def assign_profile_styles(
    total_images: int,
    profile,
    *,
    seed: Optional[int] = None,
) -> list[dict]:
    """Profile-aware style assignment using the profile's substyles.

    Replaces the holographic ``assign_styles()`` for non-holographic profiles.
    Uses the profile's substyle weights for distribution and rotation config
    for anti-clustering constraints.

    Returns a list of dicts with keys: ``display_format`` (substyle key),
    ``content_type`` (same as display_format for profiles), ``color_mood``,
    ``composition``, ``ken_burns``.
    """
    import random as _random

    rng = _random.Random(seed)

    substyles = profile.style_system.substyles
    if not substyles:
        # Fallback: no substyles defined, return empty-ish assignments
        return [{"display_format": "unknown", "content_type": "unknown",
                 "color_mood": "strategic", "composition": "wide",
                 "ken_burns": "slow_zoom_in"} for _ in range(total_images)]

    # Build weighted pool from substyle weights
    substyle_keys = list(substyles.keys())
    substyle_weights = [substyles[k].weight for k in substyle_keys]

    # Composition affinity from profile raw config
    composition_affinity = {}
    if profile.raw and "composition_affinity" in profile.raw:
        composition_affinity = profile.raw["composition_affinity"]

    # Ken Burns direction map from profile
    direction_map = {}
    if profile.ken_burns and profile.ken_burns.direction_map:
        direction_map = profile.ken_burns.direction_map

    # Rotation constraints
    max_consecutive = 3
    if profile.rotation:
        max_consecutive = profile.rotation.max_consecutive_same_content_type

    compositions = ["wide", "medium", "closeup", "environmental",
                    "portrait", "overhead", "low_angle"]
    if profile.rotation and profile.rotation.compositions:
        compositions = profile.rotation.compositions

    # Default color mood
    default_mood = "cold teal"
    if profile.style_system.accent_colors:
        default_mood = profile.style_system.accent_colors.get("default", "cold teal")

    assignments: list[dict] = []
    recent_substyles: list[str] = []
    recent_compositions: list[str] = []

    for i in range(total_images):
        # Select substyle with weighted random, respecting anti-clustering
        chosen = _weighted_choice_with_constraint(
            rng, substyle_keys, substyle_weights,
            recent_substyles, max_consecutive,
        )
        recent_substyles.append(chosen)
        if len(recent_substyles) > max_consecutive + 1:
            recent_substyles.pop(0)

        # Select composition based on affinity for this substyle
        affinity = composition_affinity.get(chosen, compositions)
        comp = _composition_with_constraint(
            rng, affinity, compositions, recent_compositions,
            max_consecutive=2,
        )
        recent_compositions.append(comp)
        if len(recent_compositions) > 3:
            recent_compositions.pop(0)

        # Ken Burns from direction map
        ken_burns = direction_map.get(comp, "slow_zoom_in")

        assignments.append({
            "display_format": chosen,
            "content_type": chosen,
            "color_mood": default_mood,
            "composition": comp,
            "ken_burns": ken_burns,
        })

    return assignments


def _weighted_choice_with_constraint(
    rng, keys: list[str], weights: list[float],
    recent: list[str], max_consecutive: int,
) -> str:
    """Weighted random choice that avoids exceeding max_consecutive same value."""
    # Check if constraint applies
    if len(recent) >= max_consecutive and all(r == recent[-1] for r in recent[-max_consecutive:]):
        # Must avoid the repeated value
        excluded = recent[-1]
        filtered_keys = [k for k in keys if k != excluded]
        filtered_weights = [w for k, w in zip(keys, weights) if k != excluded]
        if filtered_keys:
            return rng.choices(filtered_keys, weights=filtered_weights, k=1)[0]

    return rng.choices(keys, weights=weights, k=1)[0]


def _composition_with_constraint(
    rng, affinity: list[str], all_compositions: list[str],
    recent: list[str], max_consecutive: int,
) -> str:
    """Pick composition from affinity list, avoiding repetition."""
    if recent and len(recent) >= max_consecutive and all(r == recent[-1] for r in recent[-max_consecutive:]):
        excluded = recent[-1]
        candidates = [c for c in affinity if c != excluded]
        if not candidates:
            candidates = [c for c in all_compositions if c != excluded]
        return rng.choice(candidates) if candidates else affinity[0]

    return rng.choices(affinity, k=1)[0]


def _format_from_value(value: str) -> DisplayFormat:
    """Convert a string value to DisplayFormat enum."""
    for fmt in DisplayFormat:
        if fmt.value == value:
            return fmt
    return DisplayFormat.WAR_TABLE


def _mood_from_value(value: str) -> ColorMood:
    """Convert a string value to ColorMood enum."""
    for mood in ColorMood:
        if mood.value == value:
            return mood
    return ColorMood.STRATEGIC


def _apply_style_override(mood_language: str, override: str) -> str:
    """Apply an image style override to the color mood layer."""
    stripped = override.strip()
    if stripped.upper().startswith("REPLACE:"):
        return stripped[len("REPLACE:"):].strip()
    if stripped.startswith("+"):
        return mood_language + " " + stripped[1:].strip()
    if stripped.upper().startswith("APPEND:"):
        return mood_language + " " + stripped[len("APPEND:"):].strip()
    return mood_language + " " + stripped


def generate_prompts(
    scenes: list[dict],
    *,
    accent_color: Optional[str] = None,
    topic_category: Optional[str] = None,
    act_timestamps: Optional[dict] = None,
    seed: Optional[int] = None,
    image_style_override: Optional[str] = None,
) -> list[dict]:
    """Generate fully constructed prompts for an entire video.

    Parameters
    ----------
    scenes : list[dict]
        Each dict must contain at minimum:
        - ``"scene_description"`` (str): what the image depicts.
    accent_color : str, optional
        Explicit color mood override (maps to a ColorMood value).
    topic_category : str, optional
        Topic category (unused in v4, kept for API compatibility).
    act_timestamps : dict, optional
        Custom act timestamp breakpoints.
    seed : int, optional
        RNG seed for reproducible sequencing.
    image_style_override : str, optional
        Per-video style override applied to every prompt.

    Returns
    -------
    list[dict]
        One entry per scene with keys: ``prompt``, ``content_type``,
        ``display_format``, ``color_mood``, ``act``, ``index``, ``ken_burns``.
    """
    total_images = len(scenes)

    # Generate the content_type/format/mood sequence
    assignments = assign_styles(
        total_images,
        act_timestamps=act_timestamps,
        seed=seed,
    )

    results: list[dict] = []
    for scene, assignment in zip(scenes, assignments):
        desc = scene.get("scene_description", "")
        content_type = assignment["content_type"]
        display_format = assignment["display_format"]
        color_mood = assignment["color_mood"]

        # Per-scene color mood rotation based on content
        scene_mood = resolve_scene_color_mood(desc, color_mood)

        prompt = build_prompt(
            desc, content_type, display_format, scene_mood,
            image_style_override=image_style_override,
        )

        results.append({
            "prompt": prompt,
            "content_type": content_type,
            "display_format": display_format,
            "color_mood": scene_mood,
            "act": assignment["act"],
            "index": assignment["index"],
            "ken_burns": assignment["ken_burns"],
        })

    return results


# ---------------------------------------------------------------------------
# Legacy API compatibility — resolve_accent_color
# ---------------------------------------------------------------------------

def resolve_accent_color(
    accent_color: Optional[str] = None,
    topic_category: Optional[str] = None,
) -> str:
    """Returns a color mood value string from profile mappings.

    Maps accent_color/topic_category to mood using profile's
    accent_color_to_mood and category_to_mood mappings.
    """
    if accent_color:
        accent_to_mood = get_accent_color_to_mood()
        return accent_to_mood.get(accent_color, accent_color)
    if topic_category:
        cat_to_mood = get_category_to_mood()
        return cat_to_mood.get(topic_category, "strategic")
    return "strategic"


def resolve_scene_accent_color(
    scene_description: str,
    video_accent_color: str,
) -> str:
    """Legacy API: resolve per-scene accent color.

    Maps to the new color mood system.
    """
    return resolve_scene_color_mood(scene_description, video_accent_color)


# ---------------------------------------------------------------------------
# Camera movement detection — used for rotation enforcement
# ---------------------------------------------------------------------------

CAMERA_MOVEMENTS: dict[str, list[str]] = {
    "push-in": ["push-in", "push in", "pushing in", "dolly in", "move closer"],
    "pull-back": ["pull-back", "pull back", "pulling back", "zoom out", "dolly out", "pulling away"],
    "lateral-pan": ["lateral pan", "tracking shot", "pan across", "pan left", "pan right", "horizontal track"],
    "static": ["static shot", "locked-off", "locked off", "fixed camera", "steady shot", "stationary"],
    "tilt-up": ["tilt up", "tilting up", "crane up", "rising shot"],
    "tilt-down": ["tilt down", "tilting down", "crane down", "descending shot"],
    "snap-zoom": ["snap zoom", "fast push", "rapid zoom", "quick zoom", "crash zoom"],
    "orbital": ["orbital", "rotation", "circling", "orbiting", "rotating around", "arc around", "orbit around"],
}


def detect_camera_movement(prompt: str) -> str:
    """Detect which camera movement a video prompt uses.

    Scans the prompt text for keywords matching the 8 canonical camera
    movement types.  Returns the movement key (e.g. ``"push-in"``) or
    ``"unknown"`` if nothing matches.
    """
    prompt_lower = prompt.lower()
    for movement, keywords in CAMERA_MOVEMENTS.items():
        for keyword in keywords:
            if keyword in prompt_lower:
                return movement
    return "unknown"


# ---------------------------------------------------------------------------
# Video prompt validation — Banned pattern detector
# ---------------------------------------------------------------------------

FILLER_PATTERNS = [
    "gently pulse", "softly intensif", "subtly flicker", "softly blink",
    "dust particles drift", "reflections shift across", r"ambient.*glow",
    "equipment indicators", "projector beams", "light slowly sweeps",
    r"holographic data.*pulse", "subtle ambient",
]

SCREENSAVER_TEST_WORDS = ["gently", "softly", "subtly", "slightly"]


def validate_video_prompt(
    prompt: str,
    sentence_text: str = "",
    prev_cameras: list[str] | None = None,
    clip_duration_seconds: int | None = None,
) -> dict:
    """Validate a video prompt meets narrative quality standards.

    Enforces three animation rules:
    - Rule 1: Verb-first motion design (verb from sentence drives animation)
    - Rule 2: Camera static by default (only REVEAL/SCALE/ISOLATION justify motion)
    - Rule 3: Maximum 2 animated elements per clip

    Args:
        prompt: The video animation prompt to validate.
        sentence_text: The narrative text this clip supports.
        prev_cameras: History of previously used camera movements.
        clip_duration_seconds: Clip duration (6 or 10). Scales the minimum
            word count: ~25 words for 6s clips, ~42 for 10s. Falls back to
            40-word minimum when not provided.

    Returns a dict with ``valid`` (bool), ``issues`` (list[str]),
    ``prompt``, ``sentence``, ``camera`` (detected movement),
    ``camera_purpose``, and ``animated_element_count``.
    """
    from animation_prompt_engine import (
        classify_camera_purpose,
        count_animated_elements,
        CAMERA_PURPOSE_STATIC,
    )

    issues: list[str] = []

    # Check for banned filler patterns
    for pattern in FILLER_PATTERNS:
        if re.search(pattern, prompt, re.IGNORECASE):
            issues.append(f"BANNED FILLER: '{pattern}' found")

    # Screensaver word density check — more than 2 = likely filler
    screensaver_count = sum(1 for w in SCREENSAVER_TEST_WORDS if w in prompt.lower())
    if screensaver_count >= 2:
        issues.append(f"SCREENSAVER RISK: {screensaver_count} soft/gentle/subtle words")

    # Length checks — scale minimum by clip duration
    # 6s clips need ~25 words, 10s clips need ~42 words.
    # Formula: round(duration * 4.2). Falls back to 40 when duration unknown.
    word_count = len(prompt.split())
    if clip_duration_seconds is not None:
        min_words = round(clip_duration_seconds * 4.2)
    else:
        min_words = 40
    if word_count < min_words:
        issues.append(f"TOO SHORT: {word_count} words (min {min_words} for {clip_duration_seconds or '?'}s clip)")
    if word_count > 90:
        issues.append(f"TOO LONG: {word_count} words (max 90)")

    # Check the last sentence for payoff quality
    sentences = prompt.strip().split(".")
    last_sentence = sentences[-2] if sentences[-1].strip() == "" else sentences[-1]
    last_words = last_sentence.lower().strip()
    for sw in SCREENSAVER_TEST_WORDS:
        if sw in last_words:
            issues.append(f"WEAK PAYOFF: Final line contains '{sw}' — rewrite for stronger landing")

    # Camera movement detection
    current_camera = detect_camera_movement(prompt)

    # Rule 2: Camera should be static unless purpose justifies it
    camera_purpose = classify_camera_purpose(sentence_text)
    if current_camera not in ("static", "unknown") and camera_purpose == CAMERA_PURPOSE_STATIC:
        issues.append(
            f"UNJUSTIFIED CAMERA: '{current_camera}' detected but sentence doesn't justify "
            f"REVEAL, SCALE, or ISOLATION — use static shot"
        )

    # Camera repeat check (still valid when camera motion IS justified)
    if current_camera not in ("static", "unknown") and prev_cameras and len(prev_cameras) >= 1:
        if current_camera == prev_cameras[-1]:
            issues.append(
                f"CAMERA REPEAT: '{current_camera}' used on consecutive clips — pick a different movement"
            )

    # Rule 3: Max 2 animated elements
    element_count = count_animated_elements(prompt)
    if element_count > 2:
        issues.append(
            f"TOO MANY ACTIONS: {element_count} animated elements detected (max 2)"
        )

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "prompt": prompt,
        "sentence": sentence_text,
        "camera": current_camera,
        "camera_purpose": camera_purpose,
        "animated_element_count": element_count,
    }
