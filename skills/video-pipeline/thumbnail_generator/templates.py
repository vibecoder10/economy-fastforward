"""Thumbnail prompt templates for Economy FastForward.

Three templates, each producing a distinct visual layout:
  - Template A: CFH Split (default, ~70% usage)
  - Template B: Mindplicit Banner (~20% usage)
  - Template C: Power Dynamic (~10% usage, EFF exclusive)

All templates produce 16:9 editorial comic illustrations via Nano Banana Pro
with text baked directly into the image.

TEXT PLACEMENT FIX: Both text lines are always described as one stacked unit
in the same sentence. Never describe line_1 and line_2 as separate instructions
in different paragraphs — Nano Banana Pro places them unpredictably otherwise.
"""


# ---------------------------------------------------------------------------
# Template A: CFH Split (default — 70% of thumbnails)
# Select when: Country stories, economic explanations, system breakdowns,
#               human-impact hook.
# ---------------------------------------------------------------------------
TEMPLATE_A = """Editorial comic illustration, bold graphic novel style, dark navy background with dramatic amber side lighting, 16:9 landscape aspect ratio,

Left 60% of frame: {nationality} {worker_type} with {emotion} facial expression, wearing {cultural_signifier}, mouth {mouth_expression}, waist-up framing, face is large and clearly readable, bold black outlines, high color saturation, sweat drops or motion lines reinforcing the emotion,

Right side: {secondary_element}, this element tells the second half of the story and contrasts with the figure's emotion,

Bold text stacked in upper right reading "{line_1}" in large white bold condensed all-caps font with heavy black outline stroke, the word "{red_word}" is bright red, and directly below it in smaller white bold text "{line_2}" with the same black outline, both lines tightly grouped together in the same area,

Dark navy gradient background, simple composition, thick confident black linework, bold saturated colors, magazine cover composition"""

# Template A required variables
TEMPLATE_A_VARS = [
    "nationality", "worker_type", "emotion", "cultural_signifier",
    "mouth_expression", "secondary_element", "line_1", "red_word", "line_2",
]


# ---------------------------------------------------------------------------
# Template B: Mindplicit Banner (20% of thumbnails)
# Select when: Machiavellian strategy, power dynamics, hidden systems,
#               warning/command style.
# ---------------------------------------------------------------------------
TEMPLATE_B = """Editorial comic illustration, dark dramatic scene, deep navy black background with warm amber lighting from below, 16:9 landscape aspect ratio,

Bold text banner across top 20 percent of frame reading "{line_1}" in large white bold condensed all-caps font with heavy black outline stroke, the word "{red_word}" is bright red, and directly below it in smaller white text "{line_2}" with black outline, both lines at the top of the frame,

Center and lower frame: {power_scene}, dramatic shadows with warm amber accent lighting on key focal points,

{ground_detail}, editorial illustration with noir influence, bold blacks, dramatic contrast, thick black linework"""

# Template B required variables
TEMPLATE_B_VARS = [
    "line_1", "red_word", "line_2", "power_scene", "ground_detail",
]


# ---------------------------------------------------------------------------
# Template C: Power Dynamic (10% of thumbnails — EFF exclusive)
# Select when: Robot/AI replacement, wealth inequality, corporate power,
#               winners vs losers narratives.
# ---------------------------------------------------------------------------
TEMPLATE_C = """Editorial comic illustration, bold graphic novel style, dark navy background with dramatic golden amber lighting, 16:9 landscape aspect ratio,

Left side: {victim_type} stumbling backward in {emotion}, {cultural_signifier} flying off, mouth open, eyes wide, bold black outlines, high color saturation, waist-up framing with large readable facial expression, cold blue lighting on this figure,

Right side: {power_figure}, a {instrument} standing beside the power figure like a loyal servant, warm golden amber lighting on this side, floating dollar signs in the golden glow,

A large bold red arrow pointing from the victim toward the instrument suggesting {relationship},

Bold text stacked at top of frame reading "{line_1}" in large white bold condensed all-caps font with heavy black outline stroke, the word "{red_word}" is bright red, and directly below it in smaller white text "{line_2}" with black outline, both lines tightly grouped,

Simple composition, thick confident black linework, magazine cover style, dramatic contrast between cold blue victim side and warm golden power side"""

# Template C required variables
TEMPLATE_C_VARS = [
    "victim_type", "emotion", "cultural_signifier", "power_figure",
    "instrument", "relationship", "line_1", "red_word", "line_2",
]


# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------
TEMPLATES = {
    "template_a": {"name": "CFH Split", "prompt": TEMPLATE_A, "variables": TEMPLATE_A_VARS},
    "template_b": {"name": "Mindplicit Banner", "prompt": TEMPLATE_B, "variables": TEMPLATE_B_VARS},
    "template_c": {"name": "Power Dynamic", "prompt": TEMPLATE_C, "variables": TEMPLATE_C_VARS},
}


# ---------------------------------------------------------------------------
# Template selection
# ---------------------------------------------------------------------------

# Keywords that trigger Template C: Power Dynamic
_POWER_KEYWORDS = [
    "robot", "ai replace", "monopoly", "inequality",
    "corporate", "billionaire", "oligarch", "who owns",
    "who controls", "who profits", "replacement",
]

# Keywords that trigger Template B: Mindplicit Banner
_STRATEGY_KEYWORDS = [
    "machiavelli", "strategy", "hidden", "secret",
    "never do", "warning", "dark", "manipulation",
    "power play", "puppet", "behind the curtain",
]


def select_template(topic: str, tags: list[str] = None) -> str:
    """Select thumbnail template based on topic and tags.

    Args:
        topic: Video topic string.
        tags: Optional list of tags for template selection.

    Returns:
        One of 'template_a', 'template_b', 'template_c'.
    """
    topic_lower = topic.lower()
    tags_lower = [t.lower() for t in (tags or [])]
    all_text = topic_lower + " " + " ".join(tags_lower)

    # Template C: Power Dynamic — winners vs losers
    if any(kw in all_text for kw in _POWER_KEYWORDS):
        return "template_c"

    # Template B: Mindplicit Banner — strategy/warning
    if any(kw in all_text for kw in _STRATEGY_KEYWORDS):
        return "template_b"

    # Template A: CFH Split — default
    return "template_a"
