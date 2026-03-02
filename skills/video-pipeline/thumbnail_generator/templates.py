"""Thumbnail prompt templates for Economy FastForward.

Two cinematic photorealistic templates:
  - Template A: Cinematic Scene (default, ~60% usage)
  - Template B: Cinematic Close-Up (~40% usage, person-focused)

All templates produce 16:9 cinematic photorealistic images via Nano Banana Pro
with text baked directly into the image.
"""


# ---------------------------------------------------------------------------
# Template A: Cinematic Scene (default — ~60% of thumbnails)
# Select when: Systems, countries, markets, institutions, economic breakdowns.
# ---------------------------------------------------------------------------
TEMPLATE_A = (
    "Cinematic photorealistic movie poster composition, 16:9 landscape aspect "
    "ratio, ultra dramatic lighting with single amber light source from the left, "
    "deep crushed blacks, shallow depth of field, film grain, shot on Arri Alexa,\n\n"
    "{scene_description}, epic scale, the scene tells a story of power and "
    "consequence,\n\n"
    "Extreme contrast — highlights pushed bright, shadows near black, desaturated "
    "color palette with only {accent_color} as the single vivid accent color,\n\n"
    "Bold text anchored to upper-right 30% of frame reading '{line_1}' in massive "
    "white bold condensed all-caps font with heavy black outline stroke, the word "
    "'{red_word}' is bright red and is the LARGEST element in the entire image at "
    "approximately 3x the size of other text. Directly below with no gap, smaller "
    "white bold text '{line_2}' with black outline. Text must not overlap the main "
    "focal point,\n\n"
    "Movie poster composition, high contrast, must be instantly readable at "
    "120x68 pixel mobile thumbnail size"
)

# Template A required variables
TEMPLATE_A_VARS = [
    "scene_description", "accent_color", "line_1", "red_word", "line_2",
]


# ---------------------------------------------------------------------------
# Template B: Cinematic Close-Up (~40% of thumbnails)
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
    "Bold text block anchored to right 40% of frame reading '{line_1}' in "
    "massive white bold condensed all-caps font with heavy black outline stroke, "
    "the word '{red_word}' is bright red and LARGEST element. '{line_2}' directly "
    "below, smaller white text with black outline,\n\n"
    "Cinematic color grade, crushed blacks, single light source, readable at "
    "mobile thumbnail size"
)

# Template B required variables
TEMPLATE_B_VARS = [
    "close_up_subject", "emotion_detail", "background_element",
    "accent_color", "line_1", "red_word", "line_2",
]


# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------
TEMPLATES = {
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


def select_template(topic: str, tags: list[str] = None) -> str:
    """Select thumbnail template based on topic and tags.

    Args:
        topic: Video topic string.
        tags: Optional list of tags for template selection.

    Returns:
        One of 'template_a', 'template_b'.
    """
    topic_lower = topic.lower()
    tags_lower = [t.lower() for t in (tags or [])]
    all_text = topic_lower + " " + " ".join(tags_lower)

    # Template B: Cinematic Close-Up — person-focused stories
    if any(kw in all_text for kw in _PERSON_KEYWORDS):
        return "template_b"

    # Template A: Cinematic Scene — default for systems, countries, markets
    return "template_a"
