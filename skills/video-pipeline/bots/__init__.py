"""Bot implementations for Video Production Pipeline.

Currently implemented:
- IdeaBot: Generates video ideas from URLs or concepts
- TrendingIdeaBot: Generates ideas by analyzing trending YouTube videos

Future bots (logic currently in pipeline.py):
- ScriptBot
- VoiceBot
- ImagePromptBot
- ImageBot
- ThumbnailBot
"""

from .idea_bot import IdeaBot
from .trending_idea_bot import TrendingIdeaBot

__all__ = [
    "IdeaBot",
    "TrendingIdeaBot",
]
