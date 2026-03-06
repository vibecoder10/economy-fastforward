"""Thumbnail prompt templates for Economy FastForward.

Four bright editorial illustration templates optimized for high CTR:
  - Template A: Map + Barrier (highest CTR — geopolitical, chokepoints, trade)
  - Template B: Character + Bold Text (person/entity-focused stories)
  - Template C: Split Winner/Loser (versus/comparison stories)
  - Template D: Symbolic Action (metaphor-driven — fist, valve, trap)

All templates produce 1280x720 (16:9) bright editorial illustrations
via Nano Banana Pro with text baked directly into the image.

IMPORTANT: This is the THUMBNAIL system — bright, bold, editorial.
The SCENE IMAGE system (style_engine.py) stays cinematic photorealistic.
These are completely separate pipelines. Do NOT mix them.
"""


# ---------------------------------------------------------------------------
# Template A: Map + Barrier (highest CTR — geopolitical stories)
# ---------------------------------------------------------------------------
# Best for: oil, trade routes, chokepoints, sanctions, regional conflict
# CTR benchmark: 7.0%+ when done right
TEMPLATE_A_MAP_BARRIER = (
    "Bright colorful editorial illustration of the {region} from satellite "
    "view, vivid blue ocean and golden tan desert landmasses, {country_labels}, "
    "{barrier_description}, {consequence_elements}, bright saturated colors "
    "with high contrast, no dark areas, clean editorial map style, "
    "{palette_suffix}. "
    "In the exact center of the image, enormous bold yellow text reading "
    "'{line_1}' on the first line and '{line_2}' on the second line, the text "
    "is the single largest and most dominant element in the entire image "
    "filling 70 percent of frame width, thick black outline on every letter "
    "with heavy drop shadow, the text must be absolutely massive and "
    "impossible to miss at any size. Bright but not oversaturated, clean "
    "editorial style, 16:9 aspect ratio"
)


# ---------------------------------------------------------------------------
# Template B: Character + Bold Text (person/entity-focused)
# ---------------------------------------------------------------------------
# Best for: leaders, companies, figures, tech moguls, institutions
# CTR benchmark: 7.4%+ with bright saturated colors
TEMPLATE_B_CHARACTER = (
    "Bright colorful editorial illustration of {character_description} "
    "standing {pose} in center of frame, surrounded by {thematic_elements}, "
    "{brand_elements}, bright blue sky or colorful background, {floating_elements} "
    "floating around them, bright saturated colors, high energy composition, "
    "{palette_suffix}. "
    "In the {text_position}, enormous bold yellow text reading '{line_1}' on "
    "the first line and '{line_2}' on the second line, the text is the single "
    "largest element filling 65 percent of frame width, thick black outline, "
    "heavy drop shadow, massive and impossible to miss. Bright lighting, "
    "high saturation, editorial illustration style, 16:9 aspect ratio"
)


# ---------------------------------------------------------------------------
# Template C: Split Winner/Loser (comparison/versus stories)
# ---------------------------------------------------------------------------
# Best for: sanctions, trade wars, bans, winners vs losers, before/after
# CTR benchmark: 4.2%+
TEMPLATE_C_SPLIT = (
    "Bright colorful editorial illustration showing a split scene, on the "
    "left side {loser_element}, on the right side {winner_element}, "
    "{connecting_element} between them, {scattered_elements} scattered around, "
    "bright saturated colors with high contrast, no dark areas, editorial "
    "illustration style, {palette_suffix}. "
    "In the {text_position} of the image, enormous bold yellow text reading "
    "'{line_1}' on the first line and '{line_2}' on the second line, the text "
    "is the single largest element filling 65-70 percent of frame width, "
    "thick black outline on every letter, heavy drop shadow, massive and "
    "readable at any size. Bright lighting, high saturation, 16:9 aspect ratio"
)


# ---------------------------------------------------------------------------
# Template D: Symbolic Action (metaphor-driven)
# ---------------------------------------------------------------------------
# Best for: traps, power moves, economic mechanisms, abstract concepts
# CTR benchmark: varies, strong when metaphor is clear
TEMPLATE_D_SYMBOLIC = (
    "Bright editorial illustration showing a map of {region}, countries in "
    "muted tan and sand tones, {highlight_country}. {metaphor_description}, "
    "{consequence_elements}, {geographic_labels}. Clean editorial map style "
    "with {palette_suffix}. "
    "In the exact center, enormous bold yellow text reading '{line_1}' on "
    "the first line and '{line_2}' on the second line, the text is the single "
    "largest element filling 70 percent of frame width, thick black outline, "
    "heavy drop shadow, absolutely massive. Bright but not oversaturated, "
    "editorial illustration style, 16:9 aspect ratio"
)


# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------
TEMPLATES = {
    "template_a": {
        "name": "Map + Barrier",
        "prompt": TEMPLATE_A_MAP_BARRIER,
        "usage_weight": 0.35,
        "best_for": "geopolitical, oil, trade routes, chokepoints, sanctions",
        "variables": [
            "region", "country_labels", "barrier_description",
            "consequence_elements", "palette_suffix",
            "line_1", "line_2",
        ],
    },
    "template_b": {
        "name": "Character + Bold Text",
        "prompt": TEMPLATE_B_CHARACTER,
        "usage_weight": 0.25,
        "best_for": "leaders, companies, tech moguls, institutional power",
        "variables": [
            "character_description", "pose", "thematic_elements",
            "brand_elements", "floating_elements", "text_position",
            "palette_suffix", "line_1", "line_2",
        ],
    },
    "template_c": {
        "name": "Split Winner/Loser",
        "prompt": TEMPLATE_C_SPLIT,
        "usage_weight": 0.20,
        "best_for": "sanctions, trade wars, bans, winners vs losers",
        "variables": [
            "loser_element", "winner_element", "connecting_element",
            "scattered_elements", "text_position", "palette_suffix",
            "line_1", "line_2",
        ],
    },
    "template_d": {
        "name": "Symbolic Action",
        "prompt": TEMPLATE_D_SYMBOLIC,
        "usage_weight": 0.20,
        "best_for": "traps, power moves, economic mechanisms, metaphors",
        "variables": [
            "region", "highlight_country", "metaphor_description",
            "consequence_elements", "geographic_labels", "palette_suffix",
            "line_1", "line_2",
        ],
    },
}


# ---------------------------------------------------------------------------
# Color palette presets (topic-matched)
# ---------------------------------------------------------------------------
THUMBNAIL_PALETTES = {
    "middle_east": {
        "description": "For Middle East, oil, Iran, Saudi Arabia topics",
        "prompt_suffix": (
            "only three dominant colors red blue and tan, no rainbow no neon, "
            "high contrast but restrained color scheme"
        ),
    },
    "finance": {
        "description": "For economy, markets, bubble, collapse topics",
        "prompt_suffix": (
            "dominant colors gold blue and green with red accent arrows, "
            "no rainbow no neon, bright saturated financial editorial style"
        ),
    },
    "tech": {
        "description": "For AI, tech companies, Silicon Valley topics",
        "prompt_suffix": (
            "dominant colors blue green and orange, bright tech editorial "
            "style, no rainbow no neon, clean high contrast"
        ),
    },
    "military": {
        "description": "For military, power, government topics",
        "prompt_suffix": (
            "dominant colors red blue and white with military authority feel, "
            "no rainbow no neon, clean high contrast editorial style"
        ),
    },
    "global": {
        "description": "For world order, empire, collapse topics",
        "prompt_suffix": (
            "dominant colors deep blue red and gold, no rainbow no neon, "
            "geopolitical editorial map style"
        ),
    },
}


# Keywords used to auto-detect the right palette from topic text
PALETTE_KEYWORDS = {
    "middle_east": [
        "iran", "iraq", "saudi", "arabia", "oil", "opec", "hormuz",
        "gulf", "yemen", "qatar", "uae", "emirates", "kuwait", "oman",
        "bahrain", "petroleum", "crude", "barrel", "pipeline",
    ],
    "finance": [
        "economy", "market", "stock", "bubble", "collapse", "debt",
        "dollar", "currency", "inflation", "recession", "fed", "bank",
        "interest rate", "gdp", "trade deficit", "bond", "treasury",
        "wall street", "crash", "bailout",
    ],
    "tech": [
        "ai", "artificial intelligence", "tech", "silicon valley",
        "google", "apple", "microsoft", "nvidia", "openai", "chip",
        "semiconductor", "algorithm", "data", "cyber", "robot",
        "automation", "deepfake",
    ],
    "military": [
        "military", "army", "navy", "air force", "pentagon", "nato",
        "weapon", "missile", "drone", "war", "invasion", "nuclear",
        "defense", "soldier", "commander", "general", "admiral",
    ],
    "global": [
        "empire", "world order", "hegemony", "superpower", "brics",
        "un", "united nations", "g7", "g20", "geopolitical", "alliance",
        "multipolar", "unipolar", "cold war", "dominance",
    ],
}


def detect_palette(topic_text: str) -> str:
    """Auto-detect the best color palette from topic keywords.

    Args:
        topic_text: Combined title + summary text to scan.

    Returns:
        Palette key (middle_east, finance, tech, military, global).
    """
    lower = topic_text.lower()
    scores = {}
    for palette, keywords in PALETTE_KEYWORDS.items():
        scores[palette] = sum(1 for kw in keywords if kw in lower)

    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "global"  # safe default
    return best
