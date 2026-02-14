"""API Clients for Video Production Pipeline."""

from .anthropic_client import AnthropicClient
from .airtable_client import AirtableClient
from .google_client import GoogleClient, get_direct_drive_url
from .slack_client import SlackClient
from .elevenlabs_client import ElevenLabsClient
from .style_engine import (
    STYLE_ENGINE,
    STYLE_ENGINE_PREFIX,
    STYLE_ENGINE_SUFFIX,
    MATERIAL_VOCABULARY,
    SceneType,
    CameraRole,
    SCENE_TYPE_CONFIG,
    get_documentary_pattern,
    get_scene_type_for_segment,
    get_camera_motion,
    PROMPT_MIN_WORDS,
    PROMPT_MAX_WORDS,
)

__all__ = [
    "AnthropicClient",
    "AirtableClient",
    "GoogleClient",
    "get_direct_drive_url",
    "SlackClient",
    "ElevenLabsClient",
    "STYLE_ENGINE",
    "STYLE_ENGINE_PREFIX",
    "STYLE_ENGINE_SUFFIX",
    "MATERIAL_VOCABULARY",
    "SceneType",
    "CameraRole",
    "SCENE_TYPE_CONFIG",
    "get_documentary_pattern",
    "get_scene_type_for_segment",
    "get_camera_motion",
    "PROMPT_MIN_WORDS",
    "PROMPT_MAX_WORDS",
]
