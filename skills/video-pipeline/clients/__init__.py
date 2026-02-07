"""API Clients for Video Production Pipeline."""

from .anthropic_client import AnthropicClient
from .airtable_client import AirtableClient
from .google_client import GoogleClient
from .slack_client import SlackClient
from .elevenlabs_client import ElevenLabsClient
from .style_engine import (
    STYLE_ENGINE,
    SceneType,
    CameraRole,
    SCENE_TYPE_CONFIG,
    get_documentary_pattern,
    get_scene_type_for_segment,
    PROMPT_MIN_WORDS,
    PROMPT_MAX_WORDS,
)

__all__ = [
    "AnthropicClient",
    "AirtableClient",
    "GoogleClient",
    "SlackClient",
    "ElevenLabsClient",
    "STYLE_ENGINE",
    "SceneType",
    "CameraRole",
    "SCENE_TYPE_CONFIG",
    "get_documentary_pattern",
    "get_scene_type_for_segment",
    "PROMPT_MIN_WORDS",
    "PROMPT_MAX_WORDS",
]
