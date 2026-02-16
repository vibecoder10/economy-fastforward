"""
Visual identity style configuration for the NanoBanana pipeline.

Defines the three visual styles (Dossier, Schema, Echo), accent colors,
composition directives, Ken Burns zoom rules, and default configuration.
"""

# ---------------------------------------------------------------------------
# YouTube Pipeline Style Prefix — Cinematic Dossier
# ---------------------------------------------------------------------------
# Applied at the BEGINNING of every YouTube pipeline image prompt.
# Models weight early tokens more heavily, so the prefix establishes
# the photorealistic cinematic look before scene-specific content.
#
# The placeholder [ACCENT_COLOR] is replaced at build time.
#
# IMPORTANT: This is NOT the mannequin/clay render style. The mannequin
# style lives in clients/style_engine.py and is used ONLY by the
# Animation pipeline.

YOUTUBE_STYLE_PREFIX = (
    "Cinematic photorealistic editorial photograph, dark moody atmosphere, "
    "desaturated color palette with [ACCENT_COLOR] accent lighting, "
    "Rembrandt lighting, deep shadows, shallow depth of field, subtle film grain, "
    "documentary photography style, shot on Arri Alexa, 16:9 cinematic composition, "
    "epic scale."
)

# ---------------------------------------------------------------------------
# Style Prompt Suffixes
# ---------------------------------------------------------------------------
# Each style has a prompt suffix appended to every image prompt of that type.
# The placeholder [ACCENT_COLOR] is replaced at build time with the video's
# chosen accent color string (e.g. "cold teal").

STYLE_SUFFIXES = {
    "dossier": (
        ", cinematic photorealistic, single dramatic light source, Rembrandt lighting, "
        "deep shadows, desaturated color palette with [ACCENT_COLOR] accent, shallow "
        "depth of field, subtle film grain, dark moody atmosphere, documentary "
        "photography style, shot on Arri Alexa, 16:9"
    ),
    "schema": (
        ", cinematic photorealistic background with translucent glowing data overlay, "
        "thin luminous [ACCENT_COLOR] connection lines and node points, Bloomberg "
        "terminal meets surveillance system aesthetic, dark atmosphere, minimal and "
        "elegant, deep blacks with light-emitting data elements, subtle film grain, "
        "16:9"
    ),
    "echo": (
        ", photorealistic with subtle oil painting texture, dramatic chiaroscuro "
        "candlelight lighting, warm amber tones, period-accurate costume and "
        "architecture detail, deep shadows, slightly soft focus with painterly grain, "
        "historical documentary style, heavy film grain, atmospheric and evocative, "
        "16:9"
    ),
}

# ---------------------------------------------------------------------------
# Composition Directives
# ---------------------------------------------------------------------------
# Controls framing / camera angle for each image. Cycled through for
# consecutive same-style images to ensure visual variety.

COMPOSITION_DIRECTIVES = {
    "wide": "wide establishing shot, full environment visible, figure small in frame",
    "medium": "medium shot, figure from waist up in context of environment",
    "closeup": "close-up detail shot, shallow depth of field, object or hands filling frame",
    "environmental": "environmental detail, no human figure, architecture or objects telling the story",
    "portrait": "medium close-up, figure from chest up, face partially in shadow",
    "overhead": "high angle overhead view, looking down on scene, surveillance perspective",
    "low_angle": "low angle looking up, figure or structure appearing powerful and imposing",
}

# Ordered rotation list for cycling compositions within consecutive same-style runs.
COMPOSITION_CYCLE = ["wide", "medium", "closeup", "environmental", "portrait", "overhead", "low_angle"]

# ---------------------------------------------------------------------------
# Accent Color Map
# ---------------------------------------------------------------------------

ACCENT_COLOR_MAP = {
    "geopolitical": "cold teal",
    "ai_tech": "cold teal",
    "corporate_power": "cold teal",
    "surveillance": "cold teal",
    "economic": "warm amber",
    "financial": "warm amber",
    "historical_power": "warm amber",
    "old_money": "warm amber",
    "conflict": "muted crimson",
    "warfare": "muted crimson",
    "political_violence": "muted crimson",
    "default": "cold teal",
}

# ---------------------------------------------------------------------------
# Act Style Weights
# ---------------------------------------------------------------------------
# Probability weights for style selection per act, before sequencing rule
# adjustments.

ACT_STYLE_WEIGHTS = {
    "act1": {"dossier": 0.90, "schema": 0.10, "echo": 0.00},
    "act2": {"dossier": 0.70, "schema": 0.30, "echo": 0.00},
    "act3": {"dossier": 0.45, "schema": 0.20, "echo": 0.35},
    "act4": {"dossier": 0.35, "schema": 0.20, "echo": 0.45},
    "act5": {"dossier": 0.50, "schema": 0.35, "echo": 0.15},
    "act6": {"dossier": 0.65, "schema": 0.35, "echo": 0.00},
}

# ---------------------------------------------------------------------------
# Ken Burns Zoom Direction Rules
# ---------------------------------------------------------------------------

KEN_BURNS_RULES = {
    "wide": "slow_zoom_in",
    "medium": "slow_pan_right",
    "closeup": "slow_zoom_out",
    "environmental": "slow_pan_left",
    "portrait": "slow_zoom_in",
    "overhead": "slow_zoom_in",
    "low_angle": "slow_tilt_up",
}

# Alternate pan directions to avoid monotony for compositions that pan.
KEN_BURNS_PAN_ALTERNATES = {
    "slow_pan_right": "slow_pan_left",
    "slow_pan_left": "slow_pan_right",
}

# ---------------------------------------------------------------------------
# Default Configuration
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    # Image timing
    "image_duration_seconds": 11,
    "video_duration_seconds": 1500,  # 25 minutes
    "total_images": 136,             # ~1500/11, rounded

    # Act breakpoints (in seconds from video start)
    "act_timestamps": {
        "act1_end": 90,
        "act2_end": 360,
        "act3_end": 720,
        "act4_end": 1020,
        "act5_end": 1320,
        "act6_end": 1500,
    },

    # Style distribution targets (actual will vary due to sequencing rules)
    "target_distribution": {
        "dossier": 0.60,
        "schema": 0.22,
        "echo": 0.18,
    },

    # Default accent color
    "default_accent_color": "cold teal",

    # Sequencing constraints
    "max_consecutive_same_style": 4,
    "echo_cluster_min": 2,
    "echo_cluster_max": 3,
    "schema_cluster_max_default": 1,  # Max consecutive Schema outside Act 5
    "schema_cluster_max_act5": 2,     # Max consecutive Schema in Act 5
}
