"""Thumbnail & Title generation system for Economy FastForward.

Generates matched thumbnail/title pairs using three prompt templates
(CFH Split, Mindplicit Banner, Power Dynamic) and six title formulas.
Integrates into the Airtable pipeline at Stage 6: Ready For Thumbnail.
"""

from thumbnail_title.templates import (
    TEMPLATE_A_CFH_SPLIT,
    TEMPLATE_B_MINDPLICIT_BANNER,
    TEMPLATE_C_POWER_DYNAMIC,
    TEMPLATES,
)
from thumbnail_title.selector import select_template
from thumbnail_title.title_generator import TitleGenerator
from thumbnail_title.prompt_builder import ThumbnailPromptBuilder
from thumbnail_title.validator import validate_thumbnail
from thumbnail_title.engine import ThumbnailTitleEngine

__all__ = [
    "TEMPLATE_A_CFH_SPLIT",
    "TEMPLATE_B_MINDPLICIT_BANNER",
    "TEMPLATE_C_POWER_DYNAMIC",
    "TEMPLATES",
    "select_template",
    "TitleGenerator",
    "ThumbnailPromptBuilder",
    "validate_thumbnail",
    "ThumbnailTitleEngine",
]
