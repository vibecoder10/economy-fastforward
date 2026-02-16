"""EFF Thumbnail & Title Generator.

Standalone module for generating matched thumbnail/title pairs for the
Economy FastForward YouTube pipeline. Uses Nano Banana Pro (via Kie.ai)
for image generation with three editorial comic templates.

Quick start:
    from thumbnail_generator import produce_thumbnail_and_title

    result = produce_thumbnail_and_title(
        topic="China's $140 Billion Dollar Trap",
        tags=["china", "dollar", "trap"],
        template_vars={...},
        title_formula="country_dollar",
        title_vars={...},
    )
"""

from thumbnail_generator.generator import generate_thumbnail, produce_thumbnail_and_title
from thumbnail_generator.templates import (
    TEMPLATE_A,
    TEMPLATE_B,
    TEMPLATE_C,
    TEMPLATES,
    select_template,
)
from thumbnail_generator.titles import TITLE_FORMULAS, generate_title, extract_caps_word
from thumbnail_generator.validator import validate_thumbnail
from thumbnail_generator.config import (
    ASPECT_RATIO,
    COST_PER_IMAGE,
    MAX_ATTEMPTS,
    COLORS,
)

__all__ = [
    "generate_thumbnail",
    "produce_thumbnail_and_title",
    "TEMPLATE_A",
    "TEMPLATE_B",
    "TEMPLATE_C",
    "TEMPLATES",
    "select_template",
    "TITLE_FORMULAS",
    "generate_title",
    "extract_caps_word",
    "validate_thumbnail",
    "ASPECT_RATIO",
    "COST_PER_IMAGE",
    "MAX_ATTEMPTS",
    "COLORS",
]
