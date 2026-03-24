"""
Holographic Intelligence Display style configuration.

Self-contained module defining all visual identity constants for the
holographic intelligence display system. No cross-package imports.

When a visual profile is loaded, constants are read from the profile.
When no profile is available, hardcoded defaults are used (zero risk
to production).

Version: 4.0 (Mar 2026) — Holographic Intelligence Display system
"""

from enum import Enum


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


# =============================================================================
# DISPLAY CONTENT TYPES (Variable 1)
# =============================================================================

class ContentType(Enum):
    """8 display content types that rotate across a video's image sequence."""

    GEOGRAPHIC_MAP = "geographic_map"
    DATA_TERMINAL = "data_terminal"
    OBJECT_COMPARISON = "object_comparison"
    DOCUMENT_DISPLAY = "document_display"
    NETWORK_DIAGRAM = "network_diagram"
    TIMELINE = "timeline"
    SATELLITE_RECON = "satellite_recon"
    CONCEPT_VISUALIZATION = "concept_viz"


CONTENT_TYPE_CONFIG = {
    ContentType.GEOGRAPHIC_MAP: {
        "label": "Geographic Map",
        "use_for": "Locations, territories, shipping routes, military positions, chokepoints, borders",
        "key_elements": "Country outlines with labels, route lines with directional arrows, position markers, distance annotations, terrain features",
    },
    ContentType.DATA_TERMINAL: {
        "label": "Data/Financial Terminal",
        "use_for": "Market reactions, price movements, economic data, statistics, inflation, trade volumes",
        "key_elements": "Candlestick or line charts, ticker tape feeds, percentage changes with arrows, side panel data readouts, warning indicators",
    },
    ContentType.OBJECT_COMPARISON: {
        "label": "Object/Asset Comparison",
        "use_for": "Scale contrasts, asymmetric warfare, cost comparisons, force comparisons",
        "key_elements": "Two or more objects in holographic wireframe at relative scale, floating data labels with costs/specs, comparison panels",
    },
    ContentType.DOCUMENT_DISPLAY: {
        "label": "Document/Contract Display",
        "use_for": "Legal frameworks, treaties, insurance policies, executive orders, classified briefs",
        "key_elements": "Floating translucent document with legible key clauses, highlight annotations, stamps (DENIED/CLASSIFIED/APPROVED), comparison panels",
    },
    ContentType.NETWORK_DIAGRAM: {
        "label": "Network/System Diagram",
        "use_for": "Trade flows, supply chains, alliance structures, chokepoint networks, cascade effects",
        "key_elements": "Nodes (glowing orbs) connected by flow lines of varying thickness, labels with percentages, disruption as severed connections",
    },
    ContentType.TIMELINE: {
        "label": "Timeline/Historical Comparison",
        "use_for": "Historical parallels, pattern recognition, chronological sequences, before/after",
        "key_elements": "Side-by-side or sequential panels showing different time periods, connecting visual threads, era labels with dates",
    },
    ContentType.SATELLITE_RECON: {
        "label": "Satellite/Overhead Reconnaissance",
        "use_for": "Facility damage, ship positions, military deployments, geographic features, before/after",
        "key_elements": "Top-down or angled satellite perspective, annotation markers, measurement lines, timestamp/classification labels",
    },
    ContentType.CONCEPT_VISUALIZATION: {
        "label": "Abstract Concept Visualization",
        "use_for": "Theoretical frameworks, power dynamics, game theory, strategic concepts",
        "key_elements": "Metaphorical visual structures (chess boards, scales, pressure systems, domino chains), force arrows, equilibrium diagrams",
    },
}

CONTENT_TYPE_KEYWORDS = {
    ContentType.GEOGRAPHIC_MAP: [
        "map", "strait", "chokepoint", "border", "territory", "route",
        "shipping lane", "coastline", "geography", "region", "peninsula",
        "island", "ocean", "sea", "gulf", "channel", "passage",
    ],
    ContentType.DATA_TERMINAL: [
        "price", "market", "stock", "inflation", "gdp", "trade volume",
        "billion", "trillion", "percent", "rate", "index", "crash",
        "surge", "spike", "plunge", "recession", "growth",
    ],
    ContentType.OBJECT_COMPARISON: [
        "versus", "compared to", "asymmetric", "scale", "cost",
        "drone", "carrier", "fleet", "weapon", "defense", "missile",
    ],
    ContentType.DOCUMENT_DISPLAY: [
        "treaty", "contract", "policy", "insurance", "sanction",
        "executive order", "law", "regulation", "agreement", "clause",
        "coverage", "premium", "legal",
    ],
    ContentType.NETWORK_DIAGRAM: [
        "supply chain", "network", "flow", "interconnected", "cascade",
        "domino", "contagion", "ripple", "chain reaction", "system",
        "pipeline", "dependency",
    ],
    ContentType.TIMELINE: [
        "history", "historical", "century", "decade", "era", "parallel",
        "pattern", "1956", "1973", "1979", "2008", "crisis", "before",
        "precedent", "lesson",
    ],
    ContentType.SATELLITE_RECON: [
        "satellite", "overhead", "reconnaissance", "facility", "base",
        "deployment", "imagery", "aerial", "surveillance",
    ],
    ContentType.CONCEPT_VISUALIZATION: [
        "theory", "framework", "game theory", "equilibrium", "balance",
        "power dynamic", "strategy", "dilemma", "paradox", "concept",
    ],
}


# =============================================================================
# DISPLAY FORMAT TEMPLATES (Variable 2)
# =============================================================================

class DisplayFormat(Enum):
    """5 display format templates controlling spatial layout and framing."""

    WAR_TABLE = "war_table"
    WALL_DISPLAY = "wall_display"
    FLOATING_PROJECTION = "floating"
    MULTI_PANEL = "multi_panel"
    CLOSE_UP_DETAIL = "close_up_detail"


DISPLAY_FORMAT_CONFIG = {
    DisplayFormat.WAR_TABLE: {
        "label": "The War Table (Top-Down Angled)",
        "camera_angle": "30-45 degree overhead angle looking down at horizontal holographic table surface",
        "best_for": "Geographic maps, network diagrams, satellite views",
        "layout": "Content projected on table surface with floating data panels rising above it",
        "room_context": "Edge of table visible, subtle console lights in background periphery",
        "framing": "Overhead angled view of a holographic war table surface projecting",
    },
    DisplayFormat.WALL_DISPLAY: {
        "label": "The Wall Display (Front-Facing)",
        "camera_angle": "Straight-on or slight angle, massive wall-mounted display",
        "best_for": "Financial terminals, document displays, timeline comparisons",
        "layout": "Main content fills 70% center, supporting data in smaller side panels",
        "room_context": "Display edges visible, dark room receding into background",
        "framing": "Front-facing view of a massive holographic wall display showing",
    },
    DisplayFormat.FLOATING_PROJECTION: {
        "label": "The Floating Projection (Mid-Air)",
        "camera_angle": "Eye level or slight low angle, content floating in dark space",
        "best_for": "Object comparisons, abstract concepts, symbolic visualizations",
        "layout": "Objects float freely in dark space with data labels orbiting them",
        "room_context": "Minimal — dark void with subtle floor grid or ambient light",
        "framing": "Eye-level view of holographic objects floating in dark space showing",
    },
    DisplayFormat.MULTI_PANEL: {
        "label": "The Multi-Panel Command (Split Screen)",
        "camera_angle": "Slight wide angle showing multiple displays at once",
        "best_for": "Before/after comparisons, historical parallels, cascading events",
        "layout": "2-4 panels showing related information, visually linked by connecting elements",
        "room_context": "Multiple screens visible suggesting larger operations center",
        "framing": "Wide angle view of multiple holographic display panels showing",
    },
    DisplayFormat.CLOSE_UP_DETAIL: {
        "label": "The Close-Up Detail (Macro Focus)",
        "camera_angle": "Tight crop on specific data point, chart section, or document detail",
        "best_for": "Key statistics, critical text, turning-point moments",
        "layout": "One element fills 80%+ of frame, minimal surrounding context",
        "room_context": "Almost none — just the data filling the viewer's vision",
        "framing": "Extreme close-up of a holographic display detail showing",
    },
}

CONTENT_FORMAT_AFFINITY = {
    ContentType.GEOGRAPHIC_MAP: [DisplayFormat.WAR_TABLE, DisplayFormat.MULTI_PANEL],
    ContentType.DATA_TERMINAL: [DisplayFormat.WALL_DISPLAY, DisplayFormat.CLOSE_UP_DETAIL],
    ContentType.OBJECT_COMPARISON: [DisplayFormat.FLOATING_PROJECTION, DisplayFormat.WAR_TABLE],
    ContentType.DOCUMENT_DISPLAY: [DisplayFormat.WALL_DISPLAY, DisplayFormat.CLOSE_UP_DETAIL],
    ContentType.NETWORK_DIAGRAM: [DisplayFormat.WAR_TABLE, DisplayFormat.FLOATING_PROJECTION],
    ContentType.TIMELINE: [DisplayFormat.MULTI_PANEL, DisplayFormat.WALL_DISPLAY],
    ContentType.SATELLITE_RECON: [DisplayFormat.WAR_TABLE, DisplayFormat.CLOSE_UP_DETAIL],
    ContentType.CONCEPT_VISUALIZATION: [DisplayFormat.FLOATING_PROJECTION, DisplayFormat.WAR_TABLE],
}


# =============================================================================
# COLOR MOOD PALETTES (Variable 3)
# =============================================================================

class ColorMood(Enum):
    """6 color mood palettes for emotional pacing across the video."""

    STRATEGIC = "strategic"
    ALERT = "alert"
    ARCHIVE = "archive"
    CONTAGION = "contagion"
    POWER = "power"
    PERSONAL = "personal"


COLOR_MOOD_CONFIG = {
    ColorMood.STRATEGIC: {
        "label": "STRATEGIC (Teal/Cyan)",
        "use_for": "Calm analysis, geographic explanation, establishing context, framework introduction",
        "primary": "#00CED1 teal, #00FFFF cyan",
        "prompt_language": "cool teal and cyan holographic light against dark background, clinical intelligence aesthetic",
    },
    ColorMood.ALERT: {
        "label": "ALERT (Red/Amber)",
        "use_for": "Crisis moments, market crashes, attacks, closures, breaking events",
        "primary": "#FF2D2D deep red, #FFB000 amber",
        "prompt_language": "red and amber warning colors dominating the display, emergency alert aesthetic, pulsing warning indicators",
    },
    ColorMood.ARCHIVE: {
        "label": "ARCHIVE (Gold/Sepia)",
        "use_for": "Historical parallels, pattern recognition, lessons from the past",
        "primary": "#C9A84C warm gold, #D4A574 antique amber",
        "prompt_language": "warm golden amber holographic light suggesting historical archive, antique brass and wood tones in the room periphery",
    },
    ColorMood.CONTAGION: {
        "label": "CONTAGION (Green-to-Red)",
        "use_for": "Cascading effects, spreading economic damage, interconnected failures, domino chains",
        "primary": "#00FF88 green transitioning through #FFD700 yellow to #FF2D2D red",
        "prompt_language": "color transitioning from green through yellow to red showing contagion spread, pandemic-style cascade visualization",
    },
    ColorMood.POWER: {
        "label": "POWER (Deep Blue/White)",
        "use_for": "Military force analysis, defense spending, naval power, institutional authority",
        "primary": "#1B3A5C deep navy, #4682B4 steel blue",
        "prompt_language": "deep navy blue and steel holographic wireframes with clean white labels, military precision aesthetic",
    },
    ColorMood.PERSONAL: {
        "label": "PERSONAL (Orange/White)",
        "use_for": "Viewer impact scenes, personal financial consequences",
        "primary": "#FF8C00 warm orange, white",
        "prompt_language": "warm orange and white display with green and red financial indicators, personal impact dashboard aesthetic",
    },
}

COLOR_MOOD_KEYWORDS = {
    ColorMood.STRATEGIC: [
        "analysis", "strategic", "map", "geography", "framework",
        "chokepoint", "strait", "position", "context", "overview",
        "examine", "consider", "intelligence",
    ],
    ColorMood.ALERT: [
        "crisis", "crash", "attack", "closure", "emergency", "war",
        "strike", "collapse", "panic", "threat", "danger", "warning",
        "breaking", "escalate", "conflict", "missile", "bomb",
    ],
    ColorMood.ARCHIVE: [
        "history", "historical", "century", "1956", "1973", "1979",
        "parallel", "pattern", "precedent", "lesson", "era", "past",
        "archive", "ancient", "empire",
    ],
    ColorMood.CONTAGION: [
        "cascade", "spread", "contagion", "ripple", "domino",
        "chain reaction", "infect", "interconnected", "systemic",
        "spillover", "downstream",
    ],
    ColorMood.POWER: [
        "military", "navy", "fleet", "carrier", "defense", "pentagon",
        "force", "power", "authority", "institutional", "deployment",
        "base", "command",
    ],
    ColorMood.PERSONAL: [
        "your", "viewer", "wallet", "personal", "afford", "pay",
        "cost of living", "grocery", "gas price", "savings",
        "retirement", "household",
    ],
}

COLOR_MOOD_PRIORITY = [
    ColorMood.ALERT, ColorMood.ARCHIVE, ColorMood.STRATEGIC,
    ColorMood.POWER, ColorMood.CONTAGION, ColorMood.PERSONAL,
]


# =============================================================================
# UNIVERSAL SUFFIX
# =============================================================================

HOLOGRAPHIC_SUFFIX = (
    ", no people visible no human figures no faces no silhouettes of people, "
    "only data displays and holographic projections and room environment, "
    "dark operations room background with subtle ambient equipment glow, "
    "photorealistic rendering with cinematic depth of field, 16:9 aspect ratio"
)


def get_style_suffix() -> str:
    """Get universal style suffix from profile or holographic default."""
    profile = _get_profile()
    if profile and profile.style_system.style_suffix:
        return profile.style_system.style_suffix
    return HOLOGRAPHIC_SUFFIX


# =============================================================================
# ROTATION CONSTRAINTS
# =============================================================================
MAX_CONSECUTIVE_CONTENT_TYPE = 2
MAX_CONSECUTIVE_FORMAT = 2
MAX_CONSECUTIVE_PALETTE = 3
MAX_CONSECUTIVE_CLOSE_UP = 1  # close_up_detail should never appear consecutively

# Establishing shot formats — preferred for first image of each act/scene
ESTABLISHING_FORMATS = [
    DisplayFormat.WAR_TABLE,
    DisplayFormat.WALL_DISPLAY,
]


def get_max_consecutive_content_type() -> int:
    """Get max consecutive same content type from profile or default."""
    profile = _get_profile()
    if profile:
        return profile.rotation.max_consecutive_same_content_type
    return MAX_CONSECUTIVE_CONTENT_TYPE


def get_max_consecutive_format() -> int:
    """Get max consecutive same format from profile or default."""
    profile = _get_profile()
    if profile:
        return profile.rotation.max_consecutive_same_format
    return MAX_CONSECUTIVE_FORMAT


def get_max_consecutive_palette() -> int:
    """Get max consecutive same palette from profile or default."""
    profile = _get_profile()
    if profile:
        return profile.rotation.max_consecutive_same_palette
    return MAX_CONSECUTIVE_PALETTE


def get_max_consecutive_close_up() -> int:
    """Get max consecutive close-up from profile or default."""
    profile = _get_profile()
    if profile:
        return profile.rotation.max_consecutive_close_up
    return MAX_CONSECUTIVE_CLOSE_UP


# =============================================================================
# KEN BURNS DIRECTION RULES
# =============================================================================

KEN_BURNS_RULES = {
    DisplayFormat.WAR_TABLE: "slow_zoom_in",
    DisplayFormat.WALL_DISPLAY: "slow_pan_right",
    DisplayFormat.FLOATING_PROJECTION: "slow_zoom_out",
    DisplayFormat.MULTI_PANEL: "slow_pan_left",
    DisplayFormat.CLOSE_UP_DETAIL: "slow_zoom_in",
}

KEN_BURNS_PAN_ALTERNATES = {
    "slow_pan_right": "slow_pan_left",
    "slow_pan_left": "slow_pan_right",
}


def get_ken_burns_rules() -> dict:
    """Get Ken Burns rules from profile or holographic default.

    Profile stores rules by format string key; this converts back to
    DisplayFormat enum keys for backward compatibility.
    """
    profile = _get_profile()
    if profile and profile.raw.get("ken_burns_rules_by_format"):
        raw = profile.raw["ken_burns_rules_by_format"]
        # Convert string keys to DisplayFormat enums
        fmt_map = {f.value: f for f in DisplayFormat}
        return {fmt_map[k]: v for k, v in raw.items() if k in fmt_map}
    return KEN_BURNS_RULES


def get_ken_burns_pan_alternates() -> dict:
    """Get Ken Burns pan alternates from profile or default."""
    profile = _get_profile()
    if profile and profile.ken_burns.pan_alternates:
        return profile.ken_burns.pan_alternates
    return KEN_BURNS_PAN_ALTERNATES


# =============================================================================
# ACT COLOR MOOD WEIGHTS — emotional arc across the video
# =============================================================================

ACT_MOOD_WEIGHTS = {
    "act1": {
        ColorMood.STRATEGIC: 0.50,
        ColorMood.ALERT: 0.25,
        ColorMood.POWER: 0.20,
        ColorMood.ARCHIVE: 0.00,
        ColorMood.CONTAGION: 0.00,
        ColorMood.PERSONAL: 0.05,
    },
    "act2": {
        ColorMood.STRATEGIC: 0.30,
        ColorMood.ALERT: 0.35,
        ColorMood.POWER: 0.20,
        ColorMood.ARCHIVE: 0.05,
        ColorMood.CONTAGION: 0.05,
        ColorMood.PERSONAL: 0.05,
    },
    "act3": {
        ColorMood.STRATEGIC: 0.10,
        ColorMood.ALERT: 0.10,
        ColorMood.POWER: 0.05,
        ColorMood.ARCHIVE: 0.55,
        ColorMood.CONTAGION: 0.10,
        ColorMood.PERSONAL: 0.10,
    },
    "act4": {
        ColorMood.STRATEGIC: 0.10,
        ColorMood.ALERT: 0.30,
        ColorMood.POWER: 0.10,
        ColorMood.ARCHIVE: 0.30,
        ColorMood.CONTAGION: 0.15,
        ColorMood.PERSONAL: 0.05,
    },
    "act5": {
        ColorMood.STRATEGIC: 0.05,
        ColorMood.ALERT: 0.35,
        ColorMood.POWER: 0.05,
        ColorMood.ARCHIVE: 0.05,
        ColorMood.CONTAGION: 0.35,
        ColorMood.PERSONAL: 0.15,
    },
    "act6": {
        ColorMood.STRATEGIC: 0.45,
        ColorMood.ALERT: 0.10,
        ColorMood.POWER: 0.20,
        ColorMood.ARCHIVE: 0.05,
        ColorMood.CONTAGION: 0.05,
        ColorMood.PERSONAL: 0.15,
    },
}

def get_act_mood_weights() -> dict:
    """Get act mood weights from profile or holographic default.

    Profile stores weights with string mood keys; this converts back to
    ColorMood enum keys for backward compatibility.
    """
    profile = _get_profile()
    if profile and profile.rotation.act_weights:
        raw = profile.rotation.act_weights
        mood_map = {m.value: m for m in ColorMood}
        result = {}
        for act_key, mood_weights in raw.items():
            result[act_key] = {
                mood_map.get(mk, mk): w for mk, w in mood_weights.items()
                if mk in mood_map
            }
        return result
    return ACT_MOOD_WEIGHTS


def get_default_config() -> dict:
    """Get default config from profile or holographic default."""
    profile = _get_profile()
    if profile and profile.raw.get("default_config"):
        raw_config = dict(profile.raw["default_config"])
        # Merge rotation constraints from profile
        raw_config.setdefault("max_consecutive_content_type", profile.rotation.max_consecutive_same_content_type)
        raw_config.setdefault("max_consecutive_format", profile.rotation.max_consecutive_same_format)
        raw_config.setdefault("max_consecutive_palette", profile.rotation.max_consecutive_same_palette)
        raw_config.setdefault("max_consecutive_close_up", profile.rotation.max_consecutive_close_up)
        # Ensure act_timestamps exists (some profiles may not have it)
        raw_config.setdefault("act_timestamps", DEFAULT_CONFIG["act_timestamps"])
        return raw_config
    return DEFAULT_CONFIG


# Display Format rotation cycle
FORMAT_CYCLE = [
    DisplayFormat.WAR_TABLE,
    DisplayFormat.WALL_DISPLAY,
    DisplayFormat.FLOATING_PROJECTION,
    DisplayFormat.MULTI_PANEL,
    DisplayFormat.CLOSE_UP_DETAIL,
]

# Default Configuration
DEFAULT_CONFIG = {
    "image_duration_seconds": 11,
    "video_duration_seconds": 1500,
    "total_images": 136,
    "act_timestamps": {
        "act1_end": 90,
        "act2_end": 360,
        "act3_end": 720,
        "act4_end": 1020,
        "act5_end": 1320,
        "act6_end": 1500,
    },
    "max_consecutive_content_type": MAX_CONSECUTIVE_CONTENT_TYPE,
    "max_consecutive_format": MAX_CONSECUTIVE_FORMAT,
    "max_consecutive_palette": MAX_CONSECUTIVE_PALETTE,
    "max_consecutive_close_up": MAX_CONSECUTIVE_CLOSE_UP,
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def resolve_content_type(scene_text: str) -> ContentType:
    """Determine the best content type for a scene based on keyword analysis."""
    text_lower = scene_text.lower()
    hits: dict[ContentType, int] = {}
    for content_type, keywords in CONTENT_TYPE_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in text_lower)
        if count > 0:
            hits[content_type] = count

    if not hits:
        return ContentType.DATA_TERMINAL

    return max(hits, key=hits.get)


def resolve_color_mood(scene_text: str) -> ColorMood:
    """Determine the best color mood for a scene based on keyword analysis."""
    text_lower = scene_text.lower()
    hits: dict[ColorMood, int] = {}
    for mood, keywords in COLOR_MOOD_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in text_lower)
        if count > 0:
            hits[mood] = count

    if not hits:
        return ColorMood.STRATEGIC

    max_count = max(hits.values())
    top_moods = [m for m, n in hits.items() if n == max_count]

    if len(top_moods) == 1:
        return top_moods[0]

    for mood in COLOR_MOOD_PRIORITY:
        if mood in top_moods:
            return mood

    return ColorMood.STRATEGIC


def resolve_display_format(content_type: ContentType, index: int = 0) -> DisplayFormat:
    """Select a display format based on content type affinity and rotation."""
    formats = CONTENT_FORMAT_AFFINITY.get(
        content_type,
        [DisplayFormat.WAR_TABLE, DisplayFormat.WALL_DISPLAY],
    )
    return formats[index % len(formats)]


def get_accent_color_to_mood() -> dict:
    """Get accent-color-to-mood mapping from profile or holographic default."""
    profile = _get_profile()
    if profile and profile.style_system.accent_color_to_mood:
        return profile.style_system.accent_color_to_mood
    return {
        "cold teal": "strategic",
        "warm amber": "archive",
        "muted crimson": "alert",
        "muted green": "contagion",
        "deep green": "contagion",
    }


def get_category_to_mood() -> dict:
    """Get topic-category-to-mood mapping from profile or holographic default."""
    profile = _get_profile()
    if profile and profile.style_system.category_to_mood:
        return profile.style_system.category_to_mood
    return {
        "geopolitical": "strategic",
        "ai_tech": "strategic",
        "corporate_power": "power",
        "surveillance": "strategic",
        "economic": "personal",
        "financial": "personal",
        "historical_power": "archive",
        "old_money": "archive",
        "conflict": "alert",
        "warfare": "alert",
        "political_violence": "alert",
        "military": "power",
        "markets": "contagion",
        "growth": "contagion",
        "trade": "contagion",
    }


def get_accent_colors() -> dict:
    """Get accent color mapping (topic → color) from profile or holographic default."""
    profile = _get_profile()
    if profile and profile.style_system.accent_colors:
        return profile.style_system.accent_colors
    return {
        "geopolitical": "strategic",
        "financial": "personal",
        "conflict": "alert",
        "default": "strategic",
    }
