"""Thumbnail prompt templates for Economy FastForward.

Three templates, each producing a distinct visual layout:
  - Template A: CFH Split (default, ~70% usage)
  - Template B: Mindplicit Banner (~20% usage)
  - Template C: Power Dynamic (~10% usage, EFF exclusive)

All templates produce 1280x720 (16:9) editorial comic illustrations
via Nano Banana Pro with text baked directly into the image.
"""


# ---------------------------------------------------------------------------
# Template A: CFH Split
# ---------------------------------------------------------------------------
TEMPLATE_A_CFH_SPLIT = (
    "Editorial comic illustration, bold graphic novel style, dark navy background "
    "with dramatic amber side lighting, 16:9 landscape aspect ratio,\n\n"
    "Left 60% of frame: {nationality} {worker_type} with {emotion} facial expression, "
    "wearing {cultural_signifier}, mouth {mouth_expression}, waist-up framing, "
    "face is large and clearly readable, bold black outlines, high color saturation, "
    "sweat drops or motion lines reinforcing the emotion,\n\n"
    "Right side: {secondary_element}, this element tells the second half of the story "
    "and contrasts with the figure's emotion,\n\n"
    'Bold text in upper right area reading "{line_1}" in large white bold condensed '
    'all-caps font with heavy black outline stroke, the word "{red_word}" is bright red, '
    'below it smaller white bold text "{line_2}" with black outline,\n\n'
    "Dark navy gradient background, simple composition, thick confident black linework, "
    "bold saturated colors, magazine cover composition"
)


# ---------------------------------------------------------------------------
# Template B: Mindplicit Banner
# ---------------------------------------------------------------------------
TEMPLATE_B_MINDPLICIT_BANNER = (
    "Editorial comic illustration, dark dramatic scene, deep navy black background "
    "with warm amber lighting from below, 16:9 landscape aspect ratio,\n\n"
    'Bold text banner across top of frame reading "{line_1}" in large white bold '
    'condensed all-caps font with heavy black outline stroke, the word "{red_word}" '
    'is bright red, below it smaller white text "{line_2}" with black outline,\n\n'
    "Center and lower frame: {power_scene}, dramatic shadows with warm amber accent "
    "lighting on key focal points,\n\n"
    "{ground_detail}, editorial illustration with noir influence, bold blacks, "
    "dramatic contrast, thick black linework"
)


# ---------------------------------------------------------------------------
# Template C: Power Dynamic (EFF Exclusive)
# ---------------------------------------------------------------------------
TEMPLATE_C_POWER_DYNAMIC = (
    "Editorial comic illustration, bold graphic novel style, dark navy background "
    "with dramatic golden amber lighting, 16:9 landscape aspect ratio,\n\n"
    "Left side: {victim_type} stumbling backward in {emotion}, {cultural_signifier} "
    "flying off, mouth open, eyes wide, bold black outlines, high color saturation, "
    "waist-up framing with large readable facial expression, cold blue lighting on "
    "this figure,\n\n"
    "Right side: {power_figure}, a {instrument} standing beside the power figure like "
    "a loyal servant, warm golden amber lighting on this side, floating dollar signs "
    "in the golden glow,\n\n"
    "A large bold red arrow pointing from the victim toward the instrument suggesting "
    "{relationship},\n\n"
    'Bold text reading "{line_1}" in large white bold condensed all-caps font with '
    'heavy black outline stroke at top of frame, the word "{red_word}" is bright red, '
    'below it smaller white text "{line_2}" with black outline,\n\n'
    "Simple composition, thick confident black linework, magazine cover style, "
    "dramatic contrast between cold blue victim side and warm golden power side"
)


# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------
TEMPLATES = {
    "template_a": {
        "name": "CFH Split",
        "prompt": TEMPLATE_A_CFH_SPLIT,
        "usage_weight": 0.70,
        "variables": [
            "nationality", "worker_type", "emotion", "cultural_signifier",
            "mouth_expression", "secondary_element", "line_1", "red_word",
            "line_2",
        ],
    },
    "template_b": {
        "name": "Mindplicit Banner",
        "prompt": TEMPLATE_B_MINDPLICIT_BANNER,
        "usage_weight": 0.20,
        "variables": [
            "line_1", "red_word", "line_2", "power_scene", "ground_detail",
        ],
    },
    "template_c": {
        "name": "Power Dynamic",
        "prompt": TEMPLATE_C_POWER_DYNAMIC,
        "usage_weight": 0.10,
        "variables": [
            "victim_type", "emotion", "cultural_signifier", "power_figure",
            "instrument", "relationship", "line_1", "red_word", "line_2",
        ],
    },
}


# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------
COLOR_PALETTE = {
    "background_default": "#0A0F1A",      # deep navy black
    "background_crisis": "#8B1A1A",        # deep crimson (crisis/collapse)
    "background_geopolitical": "#1A2A4A",  # midnight blue (geopolitical)
    "accent_gold": "#FFB800",              # dollar amounts, wealth symbols
    "alert_red": "#E63946",                # ONE highlighted word
    "accent_green": "#22C55E",             # wealth/growth (sparingly)
    "text_white": "#FFFFFF",               # all body text (+ black stroke)
}
