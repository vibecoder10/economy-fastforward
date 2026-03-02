"""Thumbnail & Title generation system for Economy FastForward.

Generates matched thumbnail/title pairs using two cinematic photorealistic
templates (Cinematic Scene, Cinematic Close-Up) and six title formulas.
Integrates into the Airtable pipeline at Stage 6: Ready For Thumbnail.
"""

from thumbnail_title.templates import (
    TEMPLATE_A_CINEMATIC_SCENE,
    TEMPLATE_B_CINEMATIC_CLOSEUP,
    TEMPLATES,
)
from thumbnail_title.selector import select_template
from thumbnail_title.title_generator import TitleGenerator
from thumbnail_title.prompt_builder import ThumbnailPromptBuilder
from thumbnail_title.validator import validate_thumbnail
from thumbnail_title.engine import ThumbnailTitleEngine

__all__ = [
    "TEMPLATE_A_CINEMATIC_SCENE",
    "TEMPLATE_B_CINEMATIC_CLOSEUP",
    "TEMPLATES",
    "select_template",
    "TitleGenerator",
    "ThumbnailPromptBuilder",
    "validate_thumbnail",
    "ThumbnailTitleEngine",
]
