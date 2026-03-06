"""Thumbnail & Title generation system for Economy FastForward.

Generates matched thumbnail/title pairs using bright editorial illustration
templates (Map+Barrier, Character, Split, Symbolic) and six title formulas.
Integrates into the Airtable pipeline at Stage 6: Ready For Thumbnail.

IMPORTANT: This is the THUMBNAIL system — bright editorial illustration style.
The SCENE IMAGE system (style_engine.py) stays cinematic photorealistic.
These are completely separate pipelines.
"""

from thumbnail_title.templates import (
    TEMPLATE_A_MAP_BARRIER,
    TEMPLATE_B_CHARACTER,
    TEMPLATE_C_SPLIT,
    TEMPLATE_D_SYMBOLIC,
    TEMPLATES,
    THUMBNAIL_PALETTES,
    detect_palette,
)
from thumbnail_title.selector import select_template
from thumbnail_title.title_generator import TitleGenerator
from thumbnail_title.prompt_builder import ThumbnailPromptBuilder
from thumbnail_title.validator import validate_thumbnail
from thumbnail_title.engine import ThumbnailTitleEngine

__all__ = [
    "TEMPLATE_A_MAP_BARRIER",
    "TEMPLATE_B_CHARACTER",
    "TEMPLATE_C_SPLIT",
    "TEMPLATE_D_SYMBOLIC",
    "TEMPLATES",
    "THUMBNAIL_PALETTES",
    "detect_palette",
    "select_template",
    "TitleGenerator",
    "ThumbnailPromptBuilder",
    "validate_thumbnail",
    "ThumbnailTitleEngine",
]
