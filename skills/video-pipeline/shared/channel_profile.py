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

import os
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
        "subtle orbit for emphasis",
        "static lock-off for impact moments",
        "gentle handheld micro-shake for urgency/chaos",
    ])
    shutter_feel: str = "cinematic — smooth motion blur, deliberate pacing"
    grain: str = "subtle organic film grain, warm texture"


@dataclass
class ColorGrade:
    """Lighting and color grading direction. Style-agnostic by default — the
    palette is whatever the video's visual style and reference images call for,
    NOT a fixed channel look."""
    primary_palette: str = (
        "no fixed palette — follow the video's visual style and the attached "
        "reference images; use colors that fit the scene and the channel's look"
    )
    contrast: str = "contrast appropriate to the visual style and the scene's mood"
    shadow_treatment: str = "shadows with visible detail, never crushed"
    highlight_treatment: str = "motivated lighting that reads the subject clearly"
    material_priorities: str = (
        "render materials (skin, fabric, surfaces) believably for the chosen style"
    )
    time_of_day_default: str = (
        "match the time of day implied by the script and the location reference"
    )


@dataclass
class CharacterHandling:
    """How subjects are treated in storyboards."""
    mode: str = "named_persistent"  # "archetype", "named_persistent", "no_characters"
    description: str = (
        "Use the characters that appear in the script, kept visually consistent "
        "with the attached cast sheet. Give them expressive faces and body "
        "language that convey each narrative beat. Do NOT invent characters who "
        "are not in the scene, and do NOT use real-world public figures by name."
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
        "1 dynamic-angle shot (low angle or high angle)",
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

    # Single source of truth for "does this model have a live generation path".
    # Read directly by pipeline_executor.run_clip_generation's gate AND by
    # GET /api/models (storyengine/backend/routes/model_registry.py) — the
    # frontend's clip-model dropdown derives its selectable list from that
    # endpoint instead of hand-copying model ids, so this flag is the ONLY
    # place "wired" is decided (see tasks/storyengine-wiring-fix-checklist.md §0.2).
    wired: bool = False


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
    wired=True,
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
    wired=True,
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
    wired=True,
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
    wired=False,  # no live generation path yet
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
    wired=False,  # no live generation path yet
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
    wired=False,  # no live generation path yet
)

SEEDANCE_2_FAST = ModelProfile(
    model_id="seedance-2-fast",
    display_name="Seedance 2.0 (Cinematic)",
    provider="kie.ai",
    durations=[6, 10],
    preferred_max=10,
    allow_max_override=False,
    cost_per_clip={6: 0.30, 10: 0.50},
    resolution="720p",
    supports_image_input=True,
    supports_first_last_frame=True,
    supports_camera_control=True,
    camera_control_type="prompt",
    avg_generation_time_seconds=90,
    max_concurrent=3,
    wired=True,
)

# --- Model Registry ---

MODEL_REGISTRY: dict[str, ModelProfile] = {
    "grok-imagine": GROK_IMAGINE,
    "seedance-2-fast": SEEDANCE_2_FAST,
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
# Default Profile — style-agnostic. The channel's actual look is supplied per
# video (image_style_override / Visual Style / the VISUAL_STYLE_DESCRIPTION the
# backend exports). This default must NOT impose any specific channel identity.
# =============================================================================

DEFAULT_PROFILE = ChannelProfile(
    channel_name="Default",

    visual_style_directive=(
        "Render in the channel's defined visual style, supplied per video and "
        "shown in the attached cast and location references — match those "
        "references exactly and never switch art styles mid-video. When no "
        "style is supplied, default to a clean, modern, cinematic look: "
        "characters with expressive faces performing actions in believable "
        "environments, with motivated lighting and clear compositions."
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
    """Load the channel profile for storyboard generation.

    The base profile is style-agnostic (DEFAULT_PROFILE). The channel's actual
    look is layered on in priority order:
      1. idea_record['Image Style Override'] — freeform per-video instruction.
      2. idea_record['Visual Style'] — a preset style id, resolved to a directive.
      3. VISUAL_STYLE_DESCRIPTION env var — the look the backend exports for this
         video (the engine seam), so the directive uses it even when the idea
         record didn't carry the field. This closes the gap where the storyboard
         directive ignored the backend's resolved look.
      4. otherwise the neutral default.
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
        # Freeform per-video instructions win over any preset style id.
        image_style_override = idea_record.get("Image Style Override")
        if image_style_override and isinstance(image_style_override, str) and image_style_override.strip():
            profile.visual_style_directive = image_style_override.strip()
            return profile

        visual_style = idea_record.get("Visual Style")
        if visual_style and isinstance(visual_style, str) and visual_style.strip():
            resolved_directive = _build_visual_style_directive(visual_style.strip())
            profile.visual_style_directive = resolved_directive or visual_style.strip()
            return profile

    # Engine seam: the backend exports the resolved channel look here so the
    # directive matches the rest of the pipeline even without an idea_record field.
    env_style = os.getenv("VISUAL_STYLE_DESCRIPTION")
    if env_style and env_style.strip():
        profile.visual_style_directive = env_style.strip()

    return profile
