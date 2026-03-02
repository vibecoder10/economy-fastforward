"""Thumbnail prompt templates for Economy FastForward.

Two cinematic photorealistic templates:
  - Template A: Cinematic Scene (default, ~60% usage)
  - Template B: Cinematic Close-Up (~40% usage, person-focused)

All templates produce 1280x720 (16:9) cinematic photorealistic images
via Nano Banana Pro with text baked directly into the image.
"""


# ---------------------------------------------------------------------------
# Template A: Cinematic Scene (default — ~60% of thumbnails)
# ---------------------------------------------------------------------------
# scene_description: dramatic environment that tells the story visually.
# Examples: "military command bunker with glowing screens and a single empty
# chair under a spotlight", "massive oil tanker in dark ocean with a single
# red warning light", "Wall Street trading floor frozen mid-crash with papers
# suspended in air"
TEMPLATE_A_CINEMATIC_SCENE = (
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


# ---------------------------------------------------------------------------
# Template B: Cinematic Close-Up (~40% of thumbnails)
# ---------------------------------------------------------------------------
# close_up_subject: an object or detail that represents the person/power.
# Examples: "a weathered hand gripping a nuclear launch key", "a cracked
# military medal on a dark wooden desk", "classified documents stamped
# TOP SECRET under harsh desk lamp light"
TEMPLATE_B_CINEMATIC_CLOSEUP = (
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


# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------
TEMPLATES = {
    "template_a": {
        "name": "Cinematic Scene",
        "prompt": TEMPLATE_A_CINEMATIC_SCENE,
        "usage_weight": 0.60,
        "variables": [
            "scene_description", "accent_color",
            "line_1", "red_word", "line_2",
        ],
    },
    "template_b": {
        "name": "Cinematic Close-Up",
        "prompt": TEMPLATE_B_CINEMATIC_CLOSEUP,
        "usage_weight": 0.40,
        "variables": [
            "close_up_subject", "emotion_detail", "background_element",
            "accent_color", "line_1", "red_word", "line_2",
        ],
    },
}


# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------
COLOR_PALETTE = {
    "background_default": "#0A0F1A",      # deep crushed blacks
    "accent_amber": "#FFB800",            # power, money, authority
    "accent_teal": "#00BFA5",             # tech, AI, innovation
    "accent_red": "#E63946",              # military, conflict, crisis
    "accent_green": "#22C55E",            # economics, growth, markets
    "alert_red": "#E63946",               # ONE highlighted word
    "text_white": "#FFFFFF",              # all body text (+ black stroke)
}
