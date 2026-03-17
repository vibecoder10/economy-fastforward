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
        # Per-video visual style override from Airtable
        style_override = (
            idea_record.get("Image Style Override")
            or idea_record.get("Visual Style")
        )
        if style_override and isinstance(style_override, str):
            profile.visual_style_directive = style_override

    return profile
