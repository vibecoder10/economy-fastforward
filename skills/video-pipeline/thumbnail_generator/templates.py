"""Thumbnail prompt templates for Economy FastForward.

Three templates:
  - Template Map: Top-down map + strategic verdict (default, ~60% usage)
  - Template A: Cinematic Scene (fallback for non-geographic topics, ~25%)
  - Template B: Cinematic Close-Up (~15%, person-focused)

All templates produce 16:9 images via Nano Banana Pro
with text baked directly into the image.
"""


# ---------------------------------------------------------------------------
# Template Map: Top-down Map + Strategic Verdict (default — ~60% of thumbnails)
# Select when: Countries, regions, trade routes, military actions, geopolitical events.
# ---------------------------------------------------------------------------
TEMPLATE_MAP = (
    "Bright editorial illustration of a top-down map of {region}, "
    "clean cartographic style with warm tan landmasses and light blue water, "
    "{strategic_overlay}, "
    "{map_icons}, "
    "bold white block capital text reading '{verdict}' in the bottom-left "
    "corner at roughly 35% of frame width with thick black outline and heavy "
    "drop shadow, country name labels in smaller black text on landmasses, "
    "the map geography should be clearly visible and not obscured by text, "
    "clean minimal composition, no people no faces no figures, "
    "must be readable at 160x90 pixels, 16:9 aspect ratio"
)

# Template Map required variables
TEMPLATE_MAP_VARS = [
    "region", "strategic_overlay", "map_icons", "verdict",
]


# ---------------------------------------------------------------------------
# Template A: Cinematic Scene (fallback — ~25% of thumbnails)
# Select when: Finance, tech, corporate — non-geographic topics.
# ---------------------------------------------------------------------------
TEMPLATE_A = (
    "Cinematic photorealistic movie poster composition, 16:9 landscape aspect "
    "ratio, ultra dramatic lighting with single amber light source from the left, "
    "deep crushed blacks, shallow depth of field, film grain, shot on Arri Alexa,\n\n"
    "{scene_description}, epic scale, the scene tells a story of power and "
    "consequence,\n\n"
    "Extreme contrast — highlights pushed bright, shadows near black, desaturated "
    "color palette with only {accent_color} as the single vivid accent color,\n\n"
    "Bold white block capital text reading '{verdict}' with thick black outline "
    "and heavy drop shadow, anchored to upper-right 30% of frame, "
    "must not overlap the main focal point,\n\n"
    "Movie poster composition, high contrast, must be instantly readable at "
    "120x68 pixel mobile thumbnail size"
)

# Template A required variables
TEMPLATE_A_VARS = [
    "scene_description", "accent_color", "verdict",
]


# ---------------------------------------------------------------------------
# Template B: Cinematic Close-Up (~15% of thumbnails)
# Select when: Person-focused stories, assassinations, leaders, CEO,
#               president, dictator, commander, general, individual power figures.
# ---------------------------------------------------------------------------
TEMPLATE_B = (
    "Cinematic photorealistic extreme close-up, 16:9 landscape aspect ratio, "
    "Rembrandt lighting with dramatic shadow cutting across the frame, ultra "
    "shallow depth of field, film grain, dark moody atmosphere,\n\n"
    "{close_up_subject}, intense detail, occupying left 55% of frame, "
    "{emotion_detail},\n\n"
    "Background is dark with subtle {background_element} visible in bokeh, "
    "desaturated palette with only {accent_color} as vivid accent,\n\n"
    "Bold white block capital text reading '{verdict}' with thick black outline "
    "and heavy drop shadow, anchored to right 40% of frame,\n\n"
    "Cinematic color grade, crushed blacks, single light source, readable at "
    "mobile thumbnail size"
)

# Template B required variables
TEMPLATE_B_VARS = [
    "close_up_subject", "emotion_detail", "background_element",
    "accent_color", "verdict",
]


# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------
TEMPLATES = {
    "template_map": {"name": "Map + Verdict", "prompt": TEMPLATE_MAP, "variables": TEMPLATE_MAP_VARS},
    "template_a": {"name": "Cinematic Scene", "prompt": TEMPLATE_A, "variables": TEMPLATE_A_VARS},
    "template_b": {"name": "Cinematic Close-Up", "prompt": TEMPLATE_B, "variables": TEMPLATE_B_VARS},
}


# ---------------------------------------------------------------------------
# Template selection
# ---------------------------------------------------------------------------

# Keywords that trigger Template B: Cinematic Close-Up (person-focused)
_PERSON_KEYWORDS = [
    "assassin", "assassination", "murder", "killed",
    "leader", "leaders", "leadership",
    "ceo", "founder", "executive",
    "president", "prime minister", "chancellor",
    "dictator", "tyrant", "authoritarian",
    "commander", "general", "admiral", "military leader",
    "king", "queen", "emperor", "monarch", "dynasty",
    "oligarch", "billionaire", "tycoon", "mogul",
    "spy", "agent", "defector",
    "warlord", "rebel leader", "coup",
    "who is", "the man who", "the woman who",
    "his plan", "her plan", "his secret", "her secret",
]

# Keywords that trigger Template A: Cinematic Scene (non-geographic fallback)
_NON_GEO_KEYWORDS = [
    "crypto", "bitcoin", "blockchain", "ai ", "artificial intelligence",
    "stock market", "wall street", "silicon valley", "tech company",
    "startup", "venture capital", "hedge fund", "private equity",
    "algorithm", "software", "platform", "social media",
    "bank", "banking", "financial", "fintech",
]


def select_template(topic: str, tags: list[str] = None) -> str:
    """Select thumbnail template based on topic and tags.

    Priority:
    1. Template B (Cinematic Close-Up) — person-focused stories
    2. Template A (Cinematic Scene) — non-geographic topics (finance, tech)
    3. Template Map (default) — all geopolitical/geographic content

    Args:
        topic: Video topic string.
        tags: Optional list of tags for template selection.

    Returns:
        One of 'template_map', 'template_a', 'template_b'.
    """
    topic_lower = topic.lower()
    tags_lower = [t.lower() for t in (tags or [])]
    all_text = topic_lower + " " + " ".join(tags_lower)

    # Template B: Cinematic Close-Up — person-focused stories
    if any(kw in all_text for kw in _PERSON_KEYWORDS):
        return "template_b"

    # Template A: Cinematic Scene — non-geographic topics
    if any(kw in all_text for kw in _NON_GEO_KEYWORDS):
        return "template_a"

    # Template Map: Map + Verdict — default for geopolitical content
    return "template_map"
