"""Animation Pipeline Module.

Handles the full animation workflow:
- Scene planning with glow arc tracking
- Image generation with Seed Dream 4.0
- Video generation with Veo 3.1
- QC checking with Haiku
- Cost tracking and budget enforcement
"""

from .scene_planner import ScenePlanner, PROTAGONIST_GLOW_FRAGMENT
from .image_generator import ImagePromptGenerator
from .airtable_client import AnimationAirtableClient
from .pipeline import AnimationPipeline

__all__ = [
    "ScenePlanner",
    "PROTAGONIST_GLOW_FRAGMENT",
    "ImagePromptGenerator",
    "AnimationAirtableClient",
    "AnimationPipeline",
]
