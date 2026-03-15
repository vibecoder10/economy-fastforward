"""Visual Profile schema definition.

A visual profile is a self-contained configuration that captures every
aspect of a channel's visual identity: image generation models, style
prefixes/suffixes, rotation constraints, figure rules, scene description
prompts, animation templates, thumbnail identity, and Ken Burns config.

Swapping the entire channel aesthetic = changing one profile reference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
from pipeline_constants import Models


@dataclass
class ImageGenConfig:
    """Image generation model configuration."""
    scene_model: str = Models.IMAGE_SCENE
    scene_model_params: dict[str, Any] = field(default_factory=lambda: {
        "aspect_ratio": "16:9",
        "resolution": "1K",
        "output_format": "png",
    })
    scene_cost_per_image: float = 0.004

    thumbnail_model: str = Models.IMAGE_THUMBNAIL
    thumbnail_model_params: dict[str, Any] = field(default_factory=lambda: {
        "aspect_ratio": "16:9",
        "resolution": "2K",
        "output_format": "png",
    })
    thumbnail_cost_per_image: float = 0.09


@dataclass
class SubstyleConfig:
    """Configuration for a single substyle (e.g. dossier, schema, echo)."""
    name: str
    weight: float
    suffix: str = ""
    description: str = ""


@dataclass
class StyleSystemConfig:
    """Style system configuration — replaces style_config.py constants."""
    style_prefix: str = ""
    style_suffix: str = ""
    # Optional separate prefix for scenes with characters (e.g., adds
    # "expressive faces" language).  Falls back to style_prefix when empty.
    character_prefix: str = ""
    substyles: dict[str, SubstyleConfig] = field(default_factory=dict)

    # Accent color mapping: topic_category -> color mood value
    accent_colors: dict[str, str] = field(default_factory=dict)

    # Legacy accent color -> mood value mapping
    accent_color_to_mood: dict[str, str] = field(default_factory=dict)

    # Topic category -> mood value mapping
    category_to_mood: dict[str, str] = field(default_factory=dict)


@dataclass
class RotationConfig:
    """Composition and rotation constraint configuration."""
    compositions: list[str] = field(default_factory=lambda: [
        "wide", "medium", "closeup", "environmental", "overhead", "low_angle",
    ])

    max_consecutive_same_content_type: int = 2
    max_consecutive_same_format: int = 2
    max_consecutive_same_palette: int = 3
    max_consecutive_close_up: int = 1

    # Act-based mood/style weight overrides — keys are act names ("act1".."act6")
    act_weights: dict[str, dict[str, float]] = field(default_factory=dict)

    # Scene expander style distribution by act number (1-6)
    scene_expander_style_distribution: dict[int, dict[str, int]] = field(default_factory=dict)


@dataclass
class FigureRulesConfig:
    """Figure and subject rules — controls human presence in images."""
    allow_human_figures: bool = False
    allow_silhouettes: bool = False
    allow_mannequins: bool = False
    protagonist_config: Optional[dict[str, Any]] = None
    negative_prompt_suffix: str = (
        "no people, no faces, no hands, no silhouettes, no human figures"
    )

    # Words to detect people references in prompts
    people_words: list[str] = field(default_factory=list)

    # Regex pattern -> replacement pairs for auto-rewriting people references
    people_replacements: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class SceneDescriptionConfig:
    """Scene description rules for LLM system prompts."""
    # The full system prompt fragment for image prompt generation
    system_prompt: str = ""

    # Metaphor translation table: abstract concept -> concrete visual
    metaphor_translation_table: dict[str, str] = field(default_factory=dict)

    # Whether images must contain quantitative data elements
    quantitative_requirement: bool = False

    # Text-in-image rules
    text_in_image_rules: str = ""


@dataclass
class AnimationConfig:
    """Animation/video generation configuration."""
    animation_model: str = Models.ANIMATION_GROK
    animation_cost_per_clip: float = 0.10

    # Motion templates by content_type x intensity
    motion_templates: dict[str, str] = field(default_factory=dict)

    # Base rule appended to every animation prompt
    motion_base_rule: str = (
        "Maintain the full original frame composition and camera angle, "
        "do not zoom or reframe"
    )

    # Intensity level descriptions
    intensity_levels: dict[str, str] = field(default_factory=dict)

    # Universal rules appended to every animation prompt
    universal_rules: list[str] = field(default_factory=list)

    # Verb-first motion design vocabulary (banned/required words)
    banned_motion_words: list[str] = field(default_factory=list)

    # Emotional motion dictionary
    emotional_motion_dict: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class ThumbnailConfig:
    """Thumbnail visual identity — separate from scene images."""
    thumbnail_style: str = "bright_editorial_illustration"
    thumbnail_text_color: str = "#FFD700"
    thumbnail_text_style: str = "bold block capitals, thick black outline"
    thumbnail_max_words_per_line: int = 4
    thumbnail_max_lines: int = 2
    thumbnail_background: str = "simple, recognizable, reads at 160x90px"
    thumbnail_palette_max_colors: int = 4

    # Prompt templates by category
    thumbnail_prompt_templates: dict[str, str] = field(default_factory=dict)

    # Color presets by topic
    thumbnail_color_presets: dict[str, list[str]] = field(default_factory=dict)

    # System prompt for thumbnail generation
    thumbnail_system_prompt: str = ""

    # Figure rules specific to thumbnails
    thumbnail_figure_rules: str = ""


@dataclass
class KenBurnsConfig:
    """Ken Burns / camera motion configuration."""
    # Direction map: composition -> ken burns direction
    direction_map: dict[str, str] = field(default_factory=lambda: {
        "wide": "slow_zoom_in",
        "medium": "slow_pan_right",
        "closeup": "slow_zoom_out",
        "environmental": "slow_pan_left",
        "portrait": "slow_zoom_in",
        "overhead": "slow_zoom_in",
        "low_angle": "slow_tilt_up",
    })

    # Scale/offset presets per direction
    presets: dict[str, dict[str, float]] = field(default_factory=lambda: {
        "slow_zoom_in": {"start_scale": 1.0, "end_scale": 1.15},
        "slow_zoom_out": {"start_scale": 1.15, "end_scale": 1.0},
        "slow_pan_right": {"start_x_offset": -40, "end_x_offset": 40},
        "slow_pan_left": {"start_x_offset": 40, "end_x_offset": -40},
        "slow_tilt_up": {"start_y_offset": 30, "end_y_offset": -30},
    })

    base_duration: float = 11.0

    # Pan alternation pairs
    pan_alternates: dict[str, str] = field(default_factory=lambda: {
        "slow_pan_right": "slow_pan_left",
        "slow_pan_left": "slow_pan_right",
    })


@dataclass
class TemplateMetadata:
    """StoryEngine template metadata — what customers see during onboarding."""
    display_name: str = ""
    category: str = "documentary"
    tags: list[str] = field(default_factory=list)
    description: str = ""
    preview_prompts: list[str] = field(default_factory=list)
    best_for: list[str] = field(default_factory=list)
    cost_tier: str = "mid"  # "low" ($2-4), "mid" ($8-12), "high" ($15-20)
    estimated_cost_per_video: dict[str, float] = field(default_factory=dict)


@dataclass
class VisualProfile:
    """Complete visual identity profile for a channel/style.

    Every aspect of how images, animations, and thumbnails look is
    captured here. The pipeline reads the active profile at runtime.
    """
    # Identity
    profile_id: str = ""
    profile_name: str = ""
    description: str = ""
    version: str = "1.0"
    channel: str = "economy_fastforward"

    # Sections
    image_gen: ImageGenConfig = field(default_factory=ImageGenConfig)
    style_system: StyleSystemConfig = field(default_factory=StyleSystemConfig)
    rotation: RotationConfig = field(default_factory=RotationConfig)
    figure_rules: FigureRulesConfig = field(default_factory=FigureRulesConfig)
    scene_description: SceneDescriptionConfig = field(default_factory=SceneDescriptionConfig)
    animation: AnimationConfig = field(default_factory=AnimationConfig)
    thumbnail: ThumbnailConfig = field(default_factory=ThumbnailConfig)
    ken_burns: KenBurnsConfig = field(default_factory=KenBurnsConfig)
    template_metadata: TemplateMetadata = field(default_factory=TemplateMetadata)

    # Raw profile data for sections that need enum-based configs
    # (e.g. content types, display formats, color moods with their
    # full config dicts). Stored as plain dicts for flexibility.
    raw: dict[str, Any] = field(default_factory=dict)
