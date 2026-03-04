"""
Visual identity style configuration for the NanoBanana pipeline.

Defines the three visual styles (Dossier, Schema, Echo), accent colors,
camera/art style directives, Ken Burns zoom rules, and default configuration.
"""

# ---------------------------------------------------------------------------
# Nano Banana 2 Prompt Structure
# ---------------------------------------------------------------------------
# Prompts follow the Nano Banana 2 optimum structure:
#
#   [Subject + Action]  ~30-50 words  (scene description — FIRST)
#   [Environment/Lighting]  ~14 words  (per-style mood)
#   [Art Style/Camera]  ~10 words  (per-composition framing)
#   ────────────────────────────────
#   Total: ~54-74 words  (within the 30-75 word sweet spot)
#
# Natural language sentences, not keyword tags. Subject leads.
# The placeholder [ACCENT_COLOR] is replaced at build time.

# ---------------------------------------------------------------------------
# Environment/Lighting — per-style mood layer
# ---------------------------------------------------------------------------
# Describes atmosphere and lighting. Differentiates Dossier / Schema / Echo.

STYLE_ENVIRONMENTS = {
    "dossier": (
        "Dark moody atmosphere with [ACCENT_COLOR] accent lighting "
        "and deep Rembrandt shadows from a single dramatic light source "
        "with subtle halation."
    ),
    "schema": (
        "Dark atmosphere with translucent glowing [ACCENT_COLOR] data nodes "
        "and thin connection lines against deep blacks."
    ),
    "echo": (
        "Warm candlelit chiaroscuro with oil painting texture, "
        "period-accurate details in soft painterly focus."
    ),
}

# ---------------------------------------------------------------------------
# Art Style / Camera — per-composition framing layer
# ---------------------------------------------------------------------------
# Controls framing, camera angle, and visual identity. Cycled through for
# consecutive same-style images to ensure visual variety.

STYLE_CAMERAS = {
    "wide": (
        "Cinematic photorealistic editorial photograph, "
        "wide establishing shot, shallow depth of field."
    ),
    "medium": (
        "Cinematic photorealistic editorial photograph, "
        "medium shot, figure from waist up."
    ),
    "closeup": (
        "Cinematic photorealistic editorial close-up, "
        "shallow depth of field, detail filling frame."
    ),
    "environmental": (
        "Cinematic photorealistic editorial photograph, "
        "environmental detail, no human figure."
    ),
    "portrait": (
        "Cinematic photorealistic editorial photograph, "
        "medium close-up, face partially in shadow."
    ),
    "overhead": (
        "Cinematic photorealistic editorial photograph, "
        "high angle overhead, surveillance perspective."
    ),
    "low_angle": (
        "Cinematic photorealistic editorial photograph, "
        "low angle looking up, powerful and imposing."
    ),
}

# Ordered rotation list for cycling compositions within consecutive same-style runs.
COMPOSITION_CYCLE = ["wide", "medium", "closeup", "environmental", "portrait", "overhead", "low_angle"]

# ---------------------------------------------------------------------------
# Accent Color Map
# ---------------------------------------------------------------------------

ACCENT_COLOR_MAP = {
    # Teal = tech / geopolitical
    "geopolitical": "cold teal",
    "ai_tech": "cold teal",
    "corporate_power": "cold teal",
    "surveillance": "cold teal",
    # Amber = power / money
    "economic": "warm amber",
    "financial": "warm amber",
    "historical_power": "warm amber",
    "old_money": "warm amber",
    # Red = military / conflict
    "conflict": "muted crimson",
    "warfare": "muted crimson",
    "political_violence": "muted crimson",
    "military": "muted crimson",
    # Green = economics / growth
    "markets": "deep green",
    "growth": "deep green",
    "trade": "deep green",
    # Default
    "default": "cold teal",
}

# Valid accent colors that can be set via Slack or Airtable
VALID_ACCENT_COLORS = {"cold teal", "muted crimson", "warm amber", "muted green"}

# ---------------------------------------------------------------------------
# Per-Scene Accent Color Rotation
# ---------------------------------------------------------------------------
# Maps content keywords in scene descriptions to accent colors. When a scene
# description contains these keywords, the accent color shifts to match the
# content — giving visual variety across 120 images instead of one flat color.

SCENE_COLOR_MAP = {
    "muted crimson": [
        "strike", "attack", "drone", "missile", "destroy", "bomb", "fire",
        "explosion", "military", "war", "kill", "dead", "weapon", "assault",
    ],
    "warm amber": [
        "power", "wealth", "oil", "palace", "king", "prince", "empire",
        "gold", "throne", "control", "dominance", "historical",
        "1941", "1953", "roosevelt",
    ],
    "cold teal": [
        "surveillance", "data", "intelligence", "command center", "monitor",
        "screen", "radar", "satellite", "strategic", "analysis", "map",
        "strait", "chokepoint",
    ],
    "muted green": [
        "market", "trade", "price", "stock", "economy", "recession",
        "inflation", "wall street", "bloomberg", "gdp", "dollar", "currency",
    ],
}

# Tie-breaking priority: crimson > amber > teal > green (conflict-heavy bias).
SCENE_COLOR_PRIORITY = ["muted crimson", "warm amber", "cold teal", "muted green"]

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
