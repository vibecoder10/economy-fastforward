"""Clay Mannequin — Legacy reference profile (earliest style).

The original animation-focused style using 3D clay render mannequins
with a golden chest glow protagonist. Preserved for reference.

Aesthetic: 3D editorial conceptual render, smooth matte gray ceramic
mannequin figures, department store display aesthetic, golden amber
chest glow for the protagonist figure.
"""

from visual_profiles.schema import (
    AnimationConfig,
    FigureRulesConfig,
    ImageGenConfig,
    KenBurnsConfig,
    RotationConfig,
    SceneDescriptionConfig,
    StyleSystemConfig,
    ThumbnailConfig,
    VisualProfile,
)


_CLAY_PREFIX = (
    "3D editorial conceptual render, smooth matte gray ceramic mannequin "
    "figures in a department store display diorama, "
    "cinematic soft studio lighting, 16:9 composition."
)

_CLAY_SUFFIX = (
    "Faceless mannequin figures, no facial features, smooth matte gray "
    "ceramic material, department store display aesthetic, "
    "cinematic depth of field, 16:9 aspect ratio"
)


PROFILE = VisualProfile(
    # Identity
    profile_id="clay_mannequin",
    profile_name="3D Clay Mannequin Render",
    description=(
        "3D editorial conceptual render with faceless matte gray ceramic "
        "mannequin figures. Protagonist has golden amber chest glow. "
        "Department store display diorama aesthetic."
    ),
    version="1.0",
    channel="economy_fastforward",

    # Image generation
    image_gen=ImageGenConfig(
        scene_model="nano-banana-2",
        scene_model_params={
            "aspect_ratio": "16:9",
            "resolution": "1K",
            "output_format": "png",
        },
        scene_cost_per_image=0.025,
    ),

    # Style system
    style_system=StyleSystemConfig(
        style_prefix=_CLAY_PREFIX,
        style_suffix=_CLAY_SUFFIX,
        substyles={},
        accent_colors={
            "default": "cold teal",
        },
    ),

    # Rotation
    rotation=RotationConfig(
        compositions=[
            "wide", "medium", "closeup", "environmental",
            "portrait", "overhead", "low_angle",
        ],
    ),

    # Figure rules — mannequins allowed with protagonist glow
    figure_rules=FigureRulesConfig(
        allow_human_figures=False,
        allow_silhouettes=False,
        allow_mannequins=True,
        protagonist_config={
            "glow_color": "gold/amber",
            "glow_intensity_range": [0, 100],
            "base_material": "smooth matte gray ceramic",
            "glow_location": "chest/heart area",
        },
        negative_prompt_suffix=(
            "no facial features, no real human skin, smooth matte gray ceramic"
        ),
    ),

    # Scene description
    scene_description=SceneDescriptionConfig(
        system_prompt=(
            "You are a visual director creating 3D clay mannequin render "
            "image prompts. Every scene is a conceptual diorama with smooth "
            "matte gray ceramic mannequin figures. The protagonist mannequin "
            "has a golden amber glow emanating from the chest area."
        ),
        quantitative_requirement=False,
        text_in_image_rules="no text overlays",
    ),

    # Animation
    animation=AnimationConfig(
        animation_model="grok-imagine/image-to-video",
        animation_cost_per_clip=0.10,
    ),

    # Thumbnail
    thumbnail=ThumbnailConfig(
        thumbnail_style="bright_editorial_illustration",
        thumbnail_text_color="#FFD700",
    ),

    # Ken Burns
    ken_burns=KenBurnsConfig(),

    # Raw data
    raw={
        "style_engine_prefix": _CLAY_PREFIX,
        "style_engine_suffix": _CLAY_SUFFIX,
    },
)
