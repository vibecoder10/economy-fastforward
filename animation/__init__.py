"""Animation production module for Economy FastForward.

Manages the full flow from scene planning through image generation,
animation via Veo 3.1 Fast, and QC — using a separate Airtable base
(R50 | Cinematic Adverts System).
"""

from animation.pipeline import AnimationPipeline
from animation.airtable import AnimationAirtableClient
from animation.scene_planner import ScenePlanner
from animation.image_generator import AnimationImageGenerator
from animation.prompt_generator import ImagePromptGenerator
from animation.animator import Animator
from animation.qc_checker import QCChecker
from animation.cost_tracker import CostTracker
from animation.notify import AnimationNotifier

__all__ = [
    "AnimationPipeline",
    "AnimationAirtableClient",
    "ScenePlanner",
    "AnimationImageGenerator",
    "ImagePromptGenerator",
    "Animator",
    "QCChecker",
    "CostTracker",
    "AnimationNotifier",
]
