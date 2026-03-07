"""API Clients for Video Production Pipeline."""

from .anthropic_client import AnthropicClient
from .airtable_client import AirtableClient
from .google_client import GoogleClient, get_direct_drive_url
from .slack_client import SlackClient
from .elevenlabs_client import ElevenLabsClient
from .style_engine import (
    # Legacy compatibility
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
    # New holographic system (re-exported from image_prompt_engine.style_config)
    ContentType,
    DisplayFormat,
    ColorMood,
    CONTENT_TYPE_CONFIG,
    DISPLAY_FORMAT_CONFIG,
    COLOR_MOOD_CONFIG,
    HOLOGRAPHIC_SUFFIX,
    resolve_content_type,
    resolve_color_mood,
    resolve_display_format,
)

__all__ = [
    "AnthropicClient",
    "AirtableClient",
    "GoogleClient",
    "get_direct_drive_url",
    "SlackClient",
    "ElevenLabsClient",
    # Legacy compatibility
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
    # New holographic system
    "ContentType",
    "DisplayFormat",
    "ColorMood",
    "CONTENT_TYPE_CONFIG",
    "DISPLAY_FORMAT_CONFIG",
    "COLOR_MOOD_CONFIG",
    "HOLOGRAPHIC_SUFFIX",
    "resolve_content_type",
    "resolve_color_mood",
    "resolve_display_format",
]
