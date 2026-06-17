"""
Prompt builder for the Holographic Intelligence Display system.

Takes scene descriptions and sequencing metadata, produces fully constructed
image generation prompts for the holographic intelligence display aesthetic.

When a visual profile is loaded, reads prefix/suffix/figure rules from the
profile. Falls back to hardcoded defaults when no profile is available.

Version: 4.0 (Mar 2026) — Holographic Intelligence Display system
"""

from __future__ import annotations

import os
import re
from typing import Optional


# ---------------------------------------------------------------------------
# Profile integration — thin adapter with hardcoded fallbacks
# ---------------------------------------------------------------------------

def _get_profile():
    """Return the active visual profile, or None."""
    try:
        from shared.profiles.visual import load_profile
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
        # Full old-format prefix (catches residual Claude output or cached data)
        r"cinematic\s+animated\s+illustration\s+in\s+muted\s+earthy\s+color\s+palette"
        r"\s+with\s+(?:visible\s+)?ink\s+outlines\s+and\s+dramatic\s+(?:directional\s+)?lighting\.?\s*",
        # Old-format suffix phrases
        r",?\s*stylized\s+2D\s+animation\s+aesthetic\s+with\s+visible\s+ink\s+outlines"
        r",?\s*muted\s+film\s+grain\s+texture,?\s*16:?\s?9\s+cinematic\s+composition\s*",
        # Old character prefix fragment
        r"stylized\s+illustrated\s+characters?\s+with\s+expressive\s+faces?\s+"
        r"showing\s+emotion\.?\s*",
        # Old substyle fragments that duplicate builder-added content
        r",?\s*muted\s+earthy\s+palette\b",
        r",?\s*visible\s+ink\s+outlines\b",
        # Individual style words (legacy)
        r"\bcinematic(?:\s+photorealistic)?\b",
        r"\bphotorealistic\b",
        r"\bholographic\b",
        r"\b16:\s?9\b",
        r"\b8K\s+resolution\b",
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


# ---------------------------------------------------------------------------
# Equipment integrity enforcement
# ---------------------------------------------------------------------------

# Equipment keywords that should default to "fully assembled"
_EQUIPMENT_KEYWORDS = [
    "drone", "drones", "quadcopter", "uav",
    "missile", "missiles", "rocket", "rockets",
    "fighter jet", "aircraft", "helicopter", "warplane",
    "tank", "armored vehicle", "artillery",
    "weapon system", "weapons system", "defense system",
    "satellite", "radar", "launcher",
]

# Damage/destruction words that override the assembled default
_DAMAGE_KEYWORDS = [
    "wreckage", "debris", "destroyed", "destroyed",
    "burning", "crashed", "crash site", "ruins",
    "damaged", "broken", "exploded", "explosion aftermath",
    "shot down", "shattered", "mangled",
]

# Words that indicate disassembly (should be removed unless damage context)
_DISASSEMBLY_PATTERNS = [
    (re.compile(r"\bdetached\b", re.IGNORECASE), ""),
    (re.compile(r"\bdisassembled\b", re.IGNORECASE), ""),
    (re.compile(r"\bsections removed\b", re.IGNORECASE), ""),
    (re.compile(r"\bpartially assembled\b", re.IGNORECASE), "fully assembled"),
    (re.compile(r"\bcomponents separated\b", re.IGNORECASE), ""),
]


def _enforce_equipment_integrity(description: str) -> str:
    """Ensure military equipment is described as intact unless damage is explicit.

    For drone/weapon/vehicle descriptions:
    - If NO damage keywords are present, remove disassembly language
    - Add "fully assembled and operational" if equipment is the focus
    - Do NOT modify if the narration explicitly describes wreckage/destruction

    Returns the modified description.
    """
    desc_lower = description.lower()

    # Check if this is an equipment scene
    has_equipment = any(kw in desc_lower for kw in _EQUIPMENT_KEYWORDS)
    if not has_equipment:
        return description

    # Check if damage/destruction is explicitly mentioned
    has_damage = any(kw in desc_lower for kw in _DAMAGE_KEYWORDS)
    if has_damage:
        # Damage is explicit, leave the description as-is
        return description

    # No damage mentioned: enforce integrity
    result = description

    # Remove disassembly language
    for pattern, replacement in _DISASSEMBLY_PATTERNS:
        result = pattern.sub(replacement, result)

    # Clean up any double spaces created by removals
    result = re.sub(r"\s{2,}", " ", result).strip()

    return result


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


"""Content-driven prefix detection.

Simplified approach: Claude writes whatever prompt best tells the story moment.
The system detects whether characters are present by looking for character
indicator words in the visual description, then:

1. If characters ARE present: prepend character prefix
2. If characters are NOT present: no prefix (description stands alone)
3. Universal suffix for ALL scenes

Scene type labels become DESCRIPTIVE (assigned after prompt is written
based on content) not PRESCRIPTIVE (assigned before, constraining output).
"""

# Neutral module-level fallbacks (used only when no profile loads). The look
# is NOT hardcoded here anymore — the channel's style is injected at build time
# (VISUAL_STYLE_DESCRIPTION / per-video image_style_override). The old Power
# Doctrine "Cinematic 2D animated illustration / ink outlines / earthy palette"
# now lives only in the opt-in cinematic_illustration profile.
_CHARACTER_PREFIX = ""

# Same for environment scenes.
_ENVIRONMENT_PREFIX = ""

# Universal suffix for ALL scenes — purely technical, no style/palette lock-in.
_UNIVERSAL_SUFFIX = " Full-bleed 16:9 composition, no black bars."

# Words that indicate character presence in the visual description
# If ANY of these appear, the scene has characters and needs character prefix
#
# IMPORTANT: Avoid words with common non-character uses:
# - "standing" matches "standing poles", "standing order" - FALSE POSITIVE
# - "head" matches "overhead", "at the head of" - FALSE POSITIVE
# - "hand" matches "on the other hand" - FALSE POSITIVE
# Instead rely on clothing/role words which are more reliable.
_CHARACTER_INDICATOR_WORDS = [
    # Figure references
    "figure", "figures",
    # Clothing (implies character wearing it - very reliable)
    "wearing", "suit", "suits", "uniform", "uniforms", "robes", "robe",
    "jacket", "coat", "dress", "shirt", "tie", "turban", "keffiyeh",
    "thobe", "vest", "costume", "clothes", "clothing", "attire",
    # Postures that ONLY apply to people (removed "standing" - too many false positives)
    "sitting", "seated", "leaning", "kneeling", "crouching",
    "walking", "running", "pointing", "reaching", "gesturing",
    "turning", "facing", "looking", "watching", "signing", "reading",
    "writing", "typing", "slamming", "pushing", "pulling",
    # Body parts (removed "head"/"hand" - too many false positives)
    "hands", "gloved", "arms", "shoulder", "shoulders",
    "posture", "stance", "silhouette",
    # Role/position words (implies character)
    "leader", "official", "general", "diplomat", "officer", "banker",
    "trader", "analyst", "soldier", "guard", "agent", "citizen",
]

# Compile patterns for efficient matching
import re as _re
_CHARACTER_PATTERNS = [
    _re.compile(rf"\b{_re.escape(w)}\b", _re.IGNORECASE)
    for w in _CHARACTER_INDICATOR_WORDS
]

# Patterns that EXCLUDE character detection (false positive filters)
# These override any character indicator match
_FALSE_POSITIVE_PATTERNS = [
    _re.compile(r"\bstanding\s+(poles?|order|water|ovation|committee|army|desk|lamp)\b", _re.IGNORECASE),
    _re.compile(r"\boverhead\b", _re.IGNORECASE),
    _re.compile(r"\bat the head of\b", _re.IGNORECASE),
    _re.compile(r"\bon the other hand\b", _re.IGNORECASE),
]

# Non-character scene indicators — if ANY of these appear, this is NOT a character scene
# and should NOT receive the character prefix. These take priority over character indicators.
_NON_CHARACTER_SCENE_KEYWORDS = [
    # Data/visualization scenes
    "holographic display", "data visualization", "bar chart", "line graph", "pie chart",
    "financial dashboard", "stock ticker", "operations room", "control room monitors",
    "projected display", "glowing digits", "percentage numbers", "floating numbers",
    "data overlay", "trend line", "infographic", "map overlay", "network diagram",
    # Environment/landscape scenes
    "aerial view", "cityscape", "skyline", "landscape", "establishing shot",
    "wide establishing", "panoramic", "empty streets", "deserted", "uninhabited",
    # Technology/infrastructure scenes (no people)
    "factory floor", "assembly line", "production line", "industrial machinery",
    "military base", "operations center", "refinery", "pipeline", "oil rig",
    "cargo container", "shipyard", "warehouse", "server room", "data center",
    # Object closeups
    "close-up of document", "closeup of document", "close up of document",
    "close-up of currency", "closeup of currency", "treaty document",
    "official seal", "wax seal", "stamp closeup", "object detail",
    # Maps and geographical
    "world map", "regional map", "satellite view", "geographic", "topographic",
    "trade route", "shipping lane", "flight path", "migration pattern",
]

_NON_CHARACTER_PATTERNS = [
    _re.compile(rf"(?<!\w){_re.escape(phrase)}(?!\w)", _re.IGNORECASE)
    for phrase in _NON_CHARACTER_SCENE_KEYWORDS
]


def _is_non_character_scene(description: str) -> bool:
    """Check if scene is definitely NOT a character scene.

    These scene types should NOT receive the character prefix regardless
    of any character indicator words that may appear in the description.

    Returns True for: data displays, landscapes, technology, object closeups, maps
    """
    for pattern in _NON_CHARACTER_PATTERNS:
        if pattern.search(description):
            return True
    return False


def _has_character_indicators(description: str) -> bool:
    """Check if a visual description contains character indicators.

    Returns True if ANY character indicator word is found, meaning
    the scene has characters and needs the character prefix.

    Uses a two-pass approach:
    1. Check for character indicator words
    2. Filter out known false positives
    """
    for pattern in _CHARACTER_PATTERNS:
        if pattern.search(description):
            return True
    return False


def _detect_scene_type(description: str) -> str:
    """Detect scene type from content for analytics/tracking.

    This is DESCRIPTIVE - assigned based on what's in the prompt,
    not prescriptive.

    Returns one of: power_move, lone_figure, environment, data_hud, object_closeup
    """
    desc_lower = description.lower()

    # Check for data/HUD indicators
    data_words = ["holographic", "chart", "graph", "data", "display", "terminal",
                  "ticker", "percentage", "statistics", "map overlay", "network"]
    if any(w in desc_lower for w in data_words) and not _has_character_indicators(description):
        return "data_hud"

    # Check for object close-up indicators
    object_words = ["close-up", "closeup", "close up", "document", "treaty",
                    "weapon", "currency", "stamp", "seal", "key", "phone",
                    "folder", "photograph", "object"]
    if any(w in desc_lower for w in object_words) and not _has_character_indicators(description):
        return "object_closeup"

    # Check for environment indicators
    env_words = ["wide shot", "establishing", "cityscape", "landscape", "skyline",
                 "port", "harbor", "street", "building", "architecture", "aerial",
                 "no people", "empty", "deserted"]
    if any(w in desc_lower for w in env_words) and not _has_character_indicators(description):
        return "environment"

    # Character scenes
    has_chars = _has_character_indicators(description)
    if has_chars:
        # Count character indicators to distinguish lone_figure vs power_move
        multi_char_words = ["figures", "characters", "two", "three", "four",
                           "group", "both", "each other", "confrontation"]
        if any(w in desc_lower for w in multi_char_words):
            return "power_move"
        return "lone_figure"

    # Default: treat as environment if no characters detected
    return "environment"


def get_style_wrapping(profile, description: str, image_style_override: str = "") -> tuple[str, str]:
    """Get the style prefix and suffix for a visual description.

    Detects whether the description is a character scene or environment/data scene
    and returns the appropriate (prefix, suffix) from the visual profile.

    This is extracted from build_prompt() so the storyboard bot can reuse
    the same style system without duplicating detection logic.

    Returns:
        (prefix, suffix) tuple of strings
    """
    if profile:
        env_prefix = profile.style_system.style_prefix or _ENVIRONMENT_PREFIX
        char_prefix = getattr(profile.style_system, "character_prefix", "") or env_prefix
        suffix = profile.style_system.style_suffix or _UNIVERSAL_SUFFIX
    else:
        env_prefix = _ENVIRONMENT_PREFIX
        char_prefix = _CHARACTER_PREFIX
        suffix = _UNIVERSAL_SUFFIX

    is_non_character = _is_non_character_scene(description)
    has_characters = _has_character_indicators(description)

    base_prefix = env_prefix if (is_non_character or not has_characters) else char_prefix

    # Channel-look injection (neutral profile) / named-profile medium kept as-is.
    prefix, suffix = _resolve_style_framing(base_prefix, suffix, image_style_override)

    return prefix, suffix


def build_prompt(
    scene_description: str,
    content_type: str,
    display_format: str,
    color_mood: str,
    image_style_override: Optional[str] = None,
) -> str:
    """Assemble a complete image generation prompt.

    When a visual profile is active, uses content-driven prefix detection:
    - If characters are present in description: prepend character prefix
    - If no characters: environment prefix
    - Universal suffix for all scenes

    Falls back to holographic defaults when no profile is loaded or
    the profile is ``holographic_hud``.

    Template (holographic)::

        [DISPLAY FORMAT framing] [DISPLAY CONTENT] [COLOR MOOD] [UNIVERSAL SUFFIX]

    Template (illustrated profiles with characters)::

        [CHARACTER PREFIX] [DISPLAY CONTENT] [UNIVERSAL SUFFIX]

    Template (illustrated profiles without characters)::

        [ENVIRONMENT PREFIX] [DISPLAY CONTENT] [UNIVERSAL SUFFIX]

    Parameters
    ----------
    scene_description : str
        What the image depicts — the visual content description from Claude.
    content_type : str
        Value from ContentType enum (e.g. ``"geographic_map"``).
        For profile-based systems, may be scene type (now DESCRIPTIVE).
    display_format : str
        Value from DisplayFormat enum (e.g. ``"war_table"``).
        For profile-based systems, same as content_type.
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
    if profile is None:
        # Unknown/stale visual_style id, or a load failure. Fall back to the
        # NEUTRAL default — never the holographic look (handoff §2.C / §7: the
        # default is the gate, and the Power Doctrine look must not resurface).
        try:
            from shared.profiles.visual import (
                load_profile as _load_default,
                DEFAULT_PROFILE_ID as _default_id,
            )
            profile = _load_default(_default_id)
        except Exception:
            profile = None
    # Holographic is now an EXPLICIT opt-in only; a missing profile is neutral.
    is_holographic = profile is not None and profile.profile_id == "holographic_hud"

    # Clean scene description
    clean_desc = _strip_style_language(scene_description).rstrip(". ")

    # Equipment-integrity enforcement (drones/weapons/vehicles default to
    # "fully assembled") is a Power-Doctrine (military) behavior — opt-in via
    # the profile, plus the holographic intelligence-display path. OFF for the
    # neutral default.
    _enforce_equip = is_holographic or bool(
        profile and profile.raw.get("enforce_equipment_integrity")
    )
    if _enforce_equip:
        clean_desc = _enforce_equipment_integrity(clean_desc)

    # --- Figure rules: profile-driven ---
    if is_holographic:
        # Holographic: no people at all — replace with unmanned equipment
        is_clean, violations = validate_no_people(clean_desc)
        if not is_clean:
            clean_desc = _remove_people_references(clean_desc)
    elif profile and profile.figure_rules:
        fr = profile.figure_rules
        if fr.allow_mannequins:
            # Clay mannequin style: replace human words with mannequin equivalents
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
        # --- Profile path: CONTENT-DRIVEN prefix detection ---
        # (profile is the neutral default here; or None only if even that failed
        # to load — then use the neutral module constants, NEVER holographic.)
        default_prefix = (profile.style_system.style_prefix if profile else _ENVIRONMENT_PREFIX) or ""

        # Strip any existing prefix from description if Claude already included it
        if default_prefix and clean_desc.lower().startswith(default_prefix.lower()):
            clean_desc = clean_desc[len(default_prefix):].strip().lstrip(",").strip()
        # Also strip our standard prefixes (skip empties — neutral profile)
        for std_prefix in [_CHARACTER_PREFIX, _ENVIRONMENT_PREFIX]:
            if std_prefix and clean_desc.lower().startswith(std_prefix.lower()):
                clean_desc = clean_desc[len(std_prefix):].strip().lstrip(",").strip()
                break

        # Use profile prefix/suffix — character_prefix for character scenes
        if profile:
            env_prefix = default_prefix
            char_prefix = getattr(profile.style_system, "character_prefix", "") or env_prefix
            suffix = profile.style_system.style_suffix or ""
        else:
            env_prefix, char_prefix, suffix = _ENVIRONMENT_PREFIX, _CHARACTER_PREFIX, _UNIVERSAL_SUFFIX

        is_non_character = _is_non_character_scene(clean_desc)
        has_characters = _has_character_indicators(clean_desc)

        base_prefix = env_prefix if (is_non_character or not has_characters) else char_prefix

        # Apply the channel-look injection (neutral profile) or keep the named
        # profile's medium (legacy override tweaks the suffix).
        prefix, suffix = _resolve_style_framing(base_prefix, suffix, image_style_override)

        # Build final prompt: [Medium] [Subject]. [Technical tail]
        if prefix:
            return f"{prefix} {clean_desc}.{suffix}"
        else:
            return f"{clean_desc}.{suffix}"


def _match_archetype_expression(char_id: str, profile) -> str:
    """Look up character expression from profile archetypes.

    Matches Story Bible character IDs to profile archetype keys via
    fuzzy keyword overlap (e.g., "irgc_commander" matches "military_general").
    """
    if not profile:
        return ""
    archetypes = {}
    try:
        archetypes = profile.raw.get("character_archetypes", {})
    except (AttributeError, TypeError):
        try:
            archetypes = profile.figure_rules.protagonist_config.get("archetypes", {})
        except (AttributeError, TypeError):
            return ""
    if not archetypes:
        return ""

    char_lower = char_id.lower().replace("_", " ")

    # Direct match first
    if char_id in archetypes:
        return archetypes[char_id].get("appearance", "")

    # Keyword matching: "irgc_commander" → "military_general"
    _ARCHETYPE_KEYWORDS = {
        "russian_leader": ["russian", "kremlin", "putin", "moscow"],
        "chinese_official": ["chinese", "beijing", "china"],
        "american_president": ["american", "president", "white house", "us"],
        "iranian_leader": ["iranian", "iran", "tehran", "ayatollah", "irgc"],
        "saudi_royal": ["saudi", "riyal", "mbs", "gulf"],
        "military_general": ["general", "commander", "military", "admiral", "officer", "colonel"],
        "diplomat": ["diplomat", "ambassador", "envoy", "negotiator"],
        "insurgent_militia": ["insurgent", "militia", "rebel", "houthi", "hezbollah", "hamas"],
        "wall_street_banker": ["banker", "trader", "wall street", "financ"],
        "intelligence_officer": ["intelligence", "spy", "cia", "mossad", "agent"],
        "citizen_everyman": ["citizen", "civilian", "worker", "farmer", "family"],
    }
    for arch_key, keywords in _ARCHETYPE_KEYWORDS.items():
        if arch_key in archetypes and any(kw in char_lower for kw in keywords):
            return archetypes[arch_key].get("appearance", "")

    return ""


def _check_metaphor_table(text: str, profile) -> str:
    """Check text against profile's metaphor translation table.

    Returns a visualization hint if a metaphor is detected, empty string otherwise.
    """
    if not profile:
        return ""
    try:
        table = profile.scene_description.metaphor_translation_table
    except (AttributeError, TypeError):
        return ""
    if not table:
        return ""

    text_lower = text.lower()
    for metaphor_key, visual_hint in table.items():
        # Convert key to searchable words: "money_flow" → "money flow"
        search_terms = metaphor_key.replace("_", " ").split()
        if all(term in text_lower for term in search_terms):
            return visual_hint
    return ""



def build_prompt_from_block(
    concept: dict,
    story_bible: dict,
    image_style_override: Optional[str] = None,
    content_type: str = "",
    display_format: str = "",
    color_mood: str = "",
) -> str:
    """Build image prompt from Claude-generated visual description + style framing.

    Claude already wrote the visual_description with full block context
    (location, lighting, characters, action, mood) via one-call-per-block
    in scene_expander._expand_with_scene_blocks(). This function wraps it
    with style prefix, camera/substyle suffix, and universal suffix.

    PROMPT FLOW:
    1. Style prefix (character vs environment)
    2. Claude's visual description (already contains setting, characters, action)
    3. Camera composition + substyle suffix (from sequencer's display_format)
    4. Mood clause (from sequencer's color_mood)
    5. Universal suffix (aspect ratio, texture)

    Parameters
    ----------
    concept : dict
        Concept dict from scene_expander with:
        - visual_description: Claude-generated 40-70 word filmable description
        - scene_type: LLM-assigned scene type (power_move, lone_figure, etc.)
        - composition: camera angle (wide/medium/closeup)
        - block_characters: list of character IDs (for prefix selection)
    story_bible : dict
        Full Story Bible (used for character ID lookup)
    image_style_override : str, optional
        Per-video style override from Airtable
    content_type : str, optional
        Sequencer-assigned content/substyle type (e.g. "data_hud", "environment")
    display_format : str, optional
        Sequencer-assigned display format (same as content_type for profiles)
    color_mood : str, optional
        Sequencer-assigned color mood (e.g. "cold teal", "warm amber")
    """
    from script.story_bible import get_character_by_id

    # Load profile for intelligent assembly
    profile = _get_profile()

    # Extract block context
    block_location = concept.get("block_location", "").strip()
    block_lighting = concept.get("block_lighting", "").strip()
    block_characters = concept.get("block_characters", [])
    camera = concept.get("composition", "medium")
    mood = concept.get("block_mood", concept.get("mood", "neutral"))

    # Story Bible action field = what happens in THIS specific image
    # This is scene direction, not camera direction
    action = concept.get("camera_direction", "").strip()

    # Visual description = narration_excerpt from Story Bible (what to SHOW)
    visual_desc = concept.get("visual_description", "").strip()
    if not visual_desc:
        visual_desc = concept.get("sentence_text", "Scene continues").strip()
    visual_desc = _strip_style_language(visual_desc).rstrip(". ")

    # Strip leading camera/shot language — it's added separately by camera_map
    visual_desc = re.sub(
        r'^(?:wide\s+(?:establishing\s+)?shot\s+of\s+'
        r'|medium\s+shot\s+of\s+'
        r'|close[- ]?up\s+(?:shot\s+)?of\s+'
        r'|extreme\s+close[- ]?up\s+of\s+)',
        '', visual_desc, flags=re.IGNORECASE,
    ).strip()

    # ---------------------------------------------------------------
    # Scene type resolution (3-tier):
    #   1. Expander-assigned scene_type (narrative-aware, from LLM)
    #   2. Sequencer display_format (rotation-based, validated)
    #   3. Text detection fallback (keyword heuristics)
    #
    # The expander sees the full narration context and assigns
    # scene_type per image with visual arc awareness.  This is more
    # accurate than the sequencer's blind rotation or keyword
    # heuristics.  Sequencer still controls color_mood and
    # composition cycling.
    # ---------------------------------------------------------------
    _CHARACTER_SUBSTYLES = {"power_move", "lone_figure"}
    _NON_CHARACTER_SUBSTYLES = {"environment", "data_hud", "object_closeup"}
    _ALL_SUBSTYLES = _CHARACTER_SUBSTYLES | _NON_CHARACTER_SUBSTYLES

    # Tier 1: Expander-assigned scene_type (narrative-aware)
    expander_scene_type = concept.get("scene_type", "")

    if expander_scene_type and expander_scene_type in _ALL_SUBSTYLES:
        scene_type = expander_scene_type
    elif display_format:
        # Tier 2: Sequencer rotation, validated against content
        detected_type = _detect_scene_type(visual_desc)
        has_characters_in_desc = detected_type in _CHARACTER_SUBSTYLES
        sequencer_wants_characters = display_format in _CHARACTER_SUBSTYLES
        compatible = (sequencer_wants_characters == has_characters_in_desc)
        if compatible:
            scene_type = display_format
        elif not has_characters_in_desc:
            scene_type = detected_type
        else:
            scene_type = detected_type
    else:
        # Tier 3: Text detection fallback
        scene_type = _detect_scene_type(visual_desc)

    substyle_suffix = ""
    if profile:
        try:
            substyles = profile.style_system.substyles
            if scene_type in substyles:
                substyle_suffix = substyles[scene_type].suffix or ""
        except (AttributeError, TypeError):
            pass

    # ---------------------------------------------------------------
    # Prefix + suffix from profile (falls back to module constants)
    # ---------------------------------------------------------------
    has_characters = bool(block_characters)
    if profile:
        try:
            ss = profile.style_system
            env_prefix = ss.style_prefix or _ENVIRONMENT_PREFIX
            char_prefix = ss.character_prefix or env_prefix
            suffix = ss.style_suffix or _UNIVERSAL_SUFFIX
        except (AttributeError, TypeError):
            env_prefix, char_prefix, suffix = _ENVIRONMENT_PREFIX, _CHARACTER_PREFIX, _UNIVERSAL_SUFFIX
    else:
        env_prefix, char_prefix, suffix = _ENVIRONMENT_PREFIX, _CHARACTER_PREFIX, _UNIVERSAL_SUFFIX

    base_prefix = char_prefix if has_characters else env_prefix
    # Channel-look injection (neutral profile front-loads the channel's look)
    # or named-profile medium kept as-is (per-video override tweaks the suffix).
    prefix, suffix = _resolve_style_framing(base_prefix, suffix, image_style_override)

    # ---------------------------------------------------------------
    # Assemble prompt following Nano Banana 2 optimum order:
    #   [Medium] [Subject + Action] . [Camera] . [Substyle context] . [Technical]
    #
    # Models weigh the beginning most heavily, so the WHAT (medium +
    # subject) comes first.  Style/texture/aspect go last as a
    # technical tail the model uses for rendering decisions.
    #
    # Claude's visual_description already contains location, characters,
    # lighting, mood, and action — all written with block context.
    # Do NOT re-add block_location, block_lighting, or character costumes.
    # ---------------------------------------------------------------

    # 1. Medium + Subject (highest weight)
    if visual_desc:
        core = f"{prefix} {visual_desc}.".strip()
    else:
        core = prefix

    # 2. Camera composition
    camera_map = {
        "wide": "Wide establishing shot",
        "medium": "Medium shot",
        "closeup": "Close-up",
        "close-up": "Close-up",
        "extreme_closeup": "Extreme close-up",
        "overhead": "Overhead shot",
        "low_angle": "Low angle shot",
        "portrait": "Portrait shot",
        "environmental": "Wide establishing shot",
    }
    camera_desc = camera_map.get(camera.lower(), "Medium shot")

    # 3. Substyle context — apply for ALL scene types with a substyle suffix.
    # The sequencer rotates substyles (power_move, environment, data_hud, etc.)
    # and each carries a unique suffix that drives visual diversity.
    if substyle_suffix:
        style_direction = f"{camera_desc}. {substyle_suffix.rstrip('. ')}."
    else:
        style_direction = f"{camera_desc}."

    prompt_body = f"{core} {style_direction}"

    # 4. Technical tail (palette, texture, aspect ratio). The channel-look
    # injection / per-video override was already folded into `suffix` (and, for
    # the neutral profile, into `prefix`) by _resolve_style_framing above.
    return f"{prompt_body}{suffix}"


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


# ---------------------------------------------------------------------------
# Channel-look injection (the "QUICK" identity path)
#
# The neutral default profile declares no medium of its own. The channel's
# actual look is injected at build time, with this precedence:
#   1. per-video image_style_override (e.g. modeled clone DNA)
#   2. VISUAL_STYLE_DESCRIPTION env var (the channel's free-text style, set by
#      the backend from IdentityContext.visual_style)
# When the active profile DOES declare its own medium (a named preset like
# cinematic_illustration), that medium is kept and a per-video override still
# tweaks the technical suffix — the legacy behavior, unchanged.
# ---------------------------------------------------------------------------

def _clean_style_text(text: str) -> str:
    """Strip REPLACE:/APPEND:/+ markers, returning the bare look sentence."""
    s = (text or "").strip()
    if s.upper().startswith("REPLACE:"):
        return s[len("REPLACE:"):].strip()
    if s.upper().startswith("APPEND:"):
        return s[len("APPEND:"):].strip()
    if s.startswith("+"):
        return s[1:].strip()
    return s


def _channel_style_injection() -> str:
    """The channel's look sentence, set per-run by the backend. '' when unset."""
    return (os.getenv("VISUAL_STYLE_DESCRIPTION") or "").strip()


def _resolve_style_framing(
    base_prefix: str,
    base_suffix: str,
    image_style_override: Optional[str],
) -> tuple[str, str]:
    """Return the (prefix, suffix) to wrap a scene description.

    - Named profile (``base_prefix`` non-empty): keep its medium; a per-video
      override still tweaks the technical suffix (legacy behavior).
    - Neutral profile (``base_prefix`` empty): front-load the channel look
      (per-video override, else ``VISUAL_STYLE_DESCRIPTION``) as the leading
      style directive; the suffix stays purely technical.
    """
    override = (image_style_override or "").strip()
    if base_prefix:
        suffix = base_suffix
        if override:
            suffix = _apply_style_override(suffix, image_style_override)
        return base_prefix, suffix

    injected = _clean_style_text(override or _channel_style_injection())
    prefix = (injected.rstrip(" .") + ".") if injected else ""
    return prefix, base_suffix


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
