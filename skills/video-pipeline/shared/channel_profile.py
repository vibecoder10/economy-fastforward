"""
Channel Profile — defines the cinematic and editorial identity for a channel.

This is used by the storyboard_bot to drive the Cinematic Directive Generator.
It controls HOW the AI director plans shots: visual style, lens choices, color
grading, character handling, emotional arc templates, and shot requirements.

This is SEPARATE from visual_profiles/ which controls image prompt construction
(prefixes, suffixes, substyles, rotation). Channel profile is the DIRECTOR's
brief; visual profile is the ARTIST's palette.

For now, EFF profile is the default. Future: load per-tenant from config or Airtable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from shared.profiles.visual import get_profile_or_default as load_visual_profile


@dataclass
class LensProfile:
    """Camera and lens behavior for shot planning."""
    focal_range: str = "24-85mm"
    dof_tendency: str = (
        "medium — deeper in establishing wides, shallower in character close-ups"
    )
    movement_vocabulary: list[str] = field(default_factory=lambda: [
        "slow push-in for tension building",
        "lateral track for reveals",
        "subtle orbit for power dynamics",
        "static lock-off for impact moments",
        "gentle handheld micro-shake for urgency/chaos",
    ])
    shutter_feel: str = "cinematic — smooth motion blur, deliberate pacing"
    grain: str = "subtle organic film grain, warm texture"


@dataclass
class ColorGrade:
    """Lighting and color grading direction."""
    primary_palette: str = "teal-navy dominant with warm amber accent highlights"
    contrast: str = "high contrast — deep blacks, controlled highlights"
    shadow_treatment: str = "rich shadows with visible detail, never crushed"
    highlight_treatment: str = "warm key light on subjects, cool environmental fill"
    material_priorities: str = (
        "metallic surfaces catch highlights, fabric absorbs shadow, "
        "skin tones stay warm"
    )
    time_of_day_default: str = (
        "varies by scene emotional beat — dawn for hope, dusk for tension, "
        "night for crisis"
    )


@dataclass
class CharacterHandling:
    """How subjects are treated in storyboards."""
    mode: str = "archetype"  # "archetype", "named_persistent", "no_characters"
    description: str = (
        "Use archetypal figures — The Strategist (suited, war room energy), "
        "The Operative (field agent, tactical gear), The Civilian (everyman), "
        "The Authority Figure (government/institutional), The Disruptor "
        "(tech/finance). Characters should have expressive faces and body "
        "language that convey the narrative beat. Do NOT use real-world "
        "political figures by name — imply through context and setting."
    )
    reference_images: dict[str, str] = field(default_factory=dict)


@dataclass
class EmotionalArc:
    """Default 4-beat structure for scene-level storytelling."""
    beat_1: str = "Setup — establish the stakes, ground the viewer in the environment"
    beat_2: str = "Build — tension escalates, new information or threat emerges"
    beat_3: str = "Turn — the revelation, the shift, the moment everything changes"
    beat_4: str = "Payoff — consequence lands, emotional resolution or cliffhanger"


@dataclass
class ShotRequirements:
    """Hard rules for every storyboard grid."""
    mandatory_shots: list[str] = field(default_factory=lambda: [
        "1 environment-establishing wide (ELS or LS)",
        "1 intimate character close-up (CU or MCU)",
        "1 extreme detail shot (ECU) — hands, documents, screens, objects",
        "1 power-angle shot (low angle or high angle)",
    ])
    continuity_rules: list[str] = field(default_factory=lambda: [
        "Strict continuity: same subjects, wardrobe, environment, lighting "
        "across all panels",
        "Only action, expression, blocking, framing, and camera movement "
        "may change between panels",
        "Depth of field must be realistic: deeper in wides, shallower in "
        "close-ups",
        "Maintain ONE consistent color grade across all 9 panels",
        "Do NOT introduce new characters/objects not established in the "
        "scene context",
    ])
    edit_rules: list[str] = field(default_factory=lambda: [
        "Ensure edit-motivated continuity between shots",
        "Eyeline match between sequential panels",
        "Action continuation across cuts",
        "Consistent screen direction / 180-degree axis",
    ])


@dataclass
class ChannelProfile:
    """Complete cinematic identity for the storyboard directive generator."""
    channel_name: str
    visual_style_directive: str
    lens_profile: LensProfile
    color_grade: ColorGrade
    character_handling: CharacterHandling
    emotional_arc: EmotionalArc
    shot_requirements: ShotRequirements
    duration_defaults: dict[str, float] = field(default_factory=dict)


# =============================================================================
# Model Profile — Video Generation Model Capabilities
# =============================================================================

@dataclass
class ModelProfile:
    """Defines a video generation model's capabilities and cost structure.

    Used by the duration-aware binner and video generation bot.
    Hot-swappable: changing the model on an Idea Concepts record
    re-runs duration binning with the new model's profile.
    """
    model_id: str
    display_name: str
    provider: str

    # Duration options (seconds, ascending)
    durations: list[int] = field(default_factory=lambda: [10])
    preferred_max: int = 10
    allow_max_override: bool = True

    # Cost per duration tier: {seconds: usd}
    cost_per_clip: dict[int, float] = field(default_factory=dict)

    # Capabilities
    resolution: str = "720p"
    supports_image_input: bool = True
    supports_first_last_frame: bool = False
    supports_camera_control: bool = False
    camera_control_type: str = "prompt"  # "prompt", "bracket", "keyframe", "none"
    aspect_ratios: list[str] = field(default_factory=lambda: ["16:9"])
    max_concurrent: int = 5
    avg_generation_time_seconds: int = 30

    # Audio
    includes_audio: bool = False
    strip_audio: bool = True


# --- Model Instances ---

GROK_IMAGINE = ModelProfile(
    model_id="grok-imagine",
    display_name="Grok Imagine",
    provider="kie.ai",
    durations=[6, 10, 15],
    preferred_max=10,
    allow_max_override=True,
    cost_per_clip={6: 0.10, 10: 0.15, 15: 0.20},
    resolution="720p",
    supports_image_input=True,
    supports_camera_control=False,
    camera_control_type="prompt",
    includes_audio=True,
    strip_audio=True,
    avg_generation_time_seconds=15,
    max_concurrent=10,
)

VEO_31_FAST = ModelProfile(
    model_id="veo-3.1-fast",
    display_name="Veo 3.1 Fast",
    provider="kie.ai",
    durations=[8],
    preferred_max=8,
    allow_max_override=False,
    cost_per_clip={8: 0.30},
    resolution="720p",
    supports_image_input=True,
    supports_first_last_frame=True,
    supports_camera_control=False,
    camera_control_type="none",
    avg_generation_time_seconds=60,
    max_concurrent=5,
)

VEO_31_QUALITY = ModelProfile(
    model_id="veo-3.1-quality",
    display_name="Veo 3.1 Quality",
    provider="kie.ai",
    durations=[8],
    preferred_max=8,
    allow_max_override=False,
    cost_per_clip={8: 1.25},
    resolution="1080p",
    supports_image_input=True,
    supports_first_last_frame=True,
    supports_camera_control=False,
    camera_control_type="none",
    avg_generation_time_seconds=120,
    max_concurrent=3,
)

KLING_30_PRO = ModelProfile(
    model_id="kling-3.0-pro",
    display_name="Kling 3.0 Pro",
    provider="kie.ai",
    durations=[5, 10],
    preferred_max=10,
    allow_max_override=False,
    cost_per_clip={5: 0.80, 10: 1.50},
    resolution="1080p",
    supports_image_input=True,
    supports_camera_control=True,
    camera_control_type="keyframe",
    avg_generation_time_seconds=90,
    max_concurrent=3,
)

RUNWAY_GEN4_TURBO = ModelProfile(
    model_id="runway-gen4-turbo",
    display_name="Runway Gen-4 Turbo",
    provider="runway",
    durations=[5, 10],
    preferred_max=10,
    allow_max_override=False,
    cost_per_clip={5: 0.25, 10: 0.50},
    resolution="720p",
    supports_image_input=True,
    supports_camera_control=True,
    camera_control_type="prompt",
    avg_generation_time_seconds=360,
    max_concurrent=5,
)

HAILUO_23_STANDARD = ModelProfile(
    model_id="hailuo-2.3-standard",
    display_name="Hailuo 2.3 Standard",
    provider="fal.ai",
    durations=[6, 10],
    preferred_max=10,
    allow_max_override=False,
    cost_per_clip={6: 0.28, 10: 0.47},
    resolution="768p",
    supports_image_input=True,
    supports_camera_control=True,
    camera_control_type="bracket",
    avg_generation_time_seconds=45,
    max_concurrent=5,
)

# --- Model Registry ---

MODEL_REGISTRY: dict[str, ModelProfile] = {
    "grok-imagine": GROK_IMAGINE,
    "veo-3.1-fast": VEO_31_FAST,
    "veo-3.1-quality": VEO_31_QUALITY,
    "kling-3.0-pro": KLING_30_PRO,
    "runway-gen4-turbo": RUNWAY_GEN4_TURBO,
    "hailuo-2.3-standard": HAILUO_23_STANDARD,
}

DEFAULT_VIDEO_MODEL = "grok-imagine"


def load_model_profile(idea_record: Optional[dict] = None) -> ModelProfile:
    """Load video generation model profile.

    Reads 'Video Model' from idea record, falls back to DEFAULT_VIDEO_MODEL.
    """
    model_id = DEFAULT_VIDEO_MODEL
    if idea_record:
        override = idea_record.get("Video Model")
        if override and override in MODEL_REGISTRY:
            model_id = override
    return MODEL_REGISTRY[model_id]


# =============================================================================
# Default Profile — Economy FastForward / Power Doctrine
# =============================================================================

DEFAULT_PROFILE = ChannelProfile(
    channel_name="Power Doctrine",

    visual_style_directive=(
        "Cinematic animated illustration style inspired by War Archive channel. "
        "Characters with expressive faces performing actions in narrative "
        "environments. Emotional lighting with dramatic compositions. Rich "
        "environmental detail. NOT photorealistic. NOT holographic HUD. NOT "
        "mannequins. Think graphic novel meets documentary cinematography."
    ),

    lens_profile=LensProfile(),
    color_grade=ColorGrade(),
    character_handling=CharacterHandling(),
    emotional_arc=EmotionalArc(),
    shot_requirements=ShotRequirements(),

    duration_defaults={
        "ELS": 2.5,
        "LS": 2.0,
        "MLS": 1.5,
        "MS": 1.5,
        "MCU": 1.5,
        "CU": 1.5,
        "ECU": 1.0,
        "Low Angle": 1.5,
        "High Angle": 1.5,
        "Worm's-eye": 1.0,
        "Bird's-eye": 1.5,
        "Insert": 1.0,
    },
)


def _build_visual_style_directive(profile_id: str) -> Optional[str]:
    """Resolve a storyboard-ready style directive from a visual profile id."""
    visual_profile = load_visual_profile(profile_id)
    if visual_profile is None:
        return None

    parts: list[str] = []
    if visual_profile.profile_name:
        parts.append(visual_profile.profile_name)
    if visual_profile.description:
        parts.append(visual_profile.description)

    style_system = getattr(visual_profile, "style_system", None)
    if style_system is not None:
        if getattr(style_system, "style_prefix", ""):
            parts.append(style_system.style_prefix.strip())
        if getattr(style_system, "style_suffix", ""):
            parts.append(style_system.style_suffix.strip().lstrip(','))

    figure_rules = getattr(visual_profile, "figure_rules", None)
    if figure_rules is not None and getattr(figure_rules, "negative_prompt_suffix", ""):
        parts.append(f"Figure rules: {figure_rules.negative_prompt_suffix.strip()}")

    return " ".join(part for part in parts if part).strip() or None


def load_profile(idea_record: Optional[dict] = None) -> ChannelProfile:
    """Load channel profile for storyboard generation.

    For now, returns DEFAULT_PROFILE (EFF).
    Future: read from idea_record['Channel Profile'] or a per-tenant config.

    If the idea record has a visual style override, merge it into the
    visual_style_directive.
    """
    profile = ChannelProfile(
        channel_name=DEFAULT_PROFILE.channel_name,
        visual_style_directive=DEFAULT_PROFILE.visual_style_directive,
        lens_profile=DEFAULT_PROFILE.lens_profile,
        color_grade=DEFAULT_PROFILE.color_grade,
        character_handling=DEFAULT_PROFILE.character_handling,
        emotional_arc=DEFAULT_PROFILE.emotional_arc,
        shot_requirements=DEFAULT_PROFILE.shot_requirements,
        duration_defaults=dict(DEFAULT_PROFILE.duration_defaults),
    )

    if idea_record:
        # Freeform per-video instructions should win over any preset style id.
        image_style_override = idea_record.get("Image Style Override")
        if image_style_override and isinstance(image_style_override, str):
            profile.visual_style_directive = image_style_override
            return profile

        visual_style = idea_record.get("Visual Style")
        if visual_style and isinstance(visual_style, str):
            resolved_directive = _build_visual_style_directive(visual_style.strip())
            if resolved_directive:
                profile.visual_style_directive = resolved_directive
            else:
                profile.visual_style_directive = visual_style

    return profile
