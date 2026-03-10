"""Cinematic Dossier — Legacy reference profile (pre-Mar 2026).

The original 3-style system (Dossier/Schema/Echo) used for the Economy
FastForward YouTube channel. Preserved for reference and potential reuse.

Aesthetic: Prestige documentary photography with Rembrandt lighting,
anonymous human figures with faces obscured by shadow/silhouette/backlighting,
desaturated palette with accent colors.
"""

from visual_profiles.schema import (
    AnimationConfig,
    FigureRulesConfig,
    ImageGenConfig,
    KenBurnsConfig,
    RotationConfig,
    SceneDescriptionConfig,
    StyleSystemConfig,
    SubstyleConfig,
    ThumbnailConfig,
    VisualProfile,
)


# =============================================================================
# Style Prefix / Suffix (the Dossier era)
# =============================================================================

_DOSSIER_PREFIX = (
    "Cinematic photorealistic still, dark moody atmosphere, desaturated palette, "
    "Rembrandt lighting with deep shadows, shot on Arri Alexa with Kodak Vision "
    "film stock, 16:9 cinematic composition."
)

_DOSSIER_SUFFIX = (
    "Anonymous human figures with faces obscured by shadow silhouette or "
    "backlighting, cinematic depth of field, no text overlays, "
    "subtle ambient light, photorealistic rendering, 16:9 aspect ratio"
)


PROFILE = VisualProfile(
    # Identity
    profile_id="cinematic_dossier",
    profile_name="Cinematic Photorealistic Dossier",
    description=(
        "Prestige documentary photography. Rembrandt lighting, anonymous "
        "human figures with faces obscured by shadow/silhouette/backlighting. "
        "3-style system: Dossier (60%), Schema (22%), Echo (18%)."
    ),
    version="3.0",
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
        thumbnail_model="nano-banana-pro",
        thumbnail_model_params={
            "aspect_ratio": "16:9",
            "resolution": "2K",
            "output_format": "png",
        },
        thumbnail_cost_per_image=0.09,
    ),

    # Style system
    style_system=StyleSystemConfig(
        style_prefix=_DOSSIER_PREFIX,
        style_suffix=_DOSSIER_SUFFIX,
        substyles={
            "dossier": SubstyleConfig(
                name="Dossier",
                weight=0.60,
                suffix=(
                    "Rembrandt lighting, cinematic photorealism, "
                    "deep shadows and warm accent color highlights"
                ),
                description="Investigation, corporate, power. Photorealistic with accent colors.",
            ),
            "schema": SubstyleConfig(
                name="Schema",
                weight=0.22,
                suffix=(
                    "Data overlay aesthetic, glowing nodes on dark background, "
                    "HUD elements and wireframe overlays"
                ),
                description="Systems, networks, data. Glowing data overlays on dark backgrounds.",
            ),
            "echo": SubstyleConfig(
                name="Echo",
                weight=0.18,
                suffix=(
                    "Painterly historical texture, candlelit warm tones, "
                    "oil painting meets documentary photography"
                ),
                description="Backstory, historical context. Painterly, candlelit aesthetic.",
            ),
        },
        accent_colors={
            "geopolitical": "cold teal",
            "financial": "warm amber",
            "conflict": "muted crimson",
            "default": "cold teal",
        },
        accent_color_to_mood={
            "cold teal": "cold teal",
            "warm amber": "warm amber",
            "muted crimson": "muted crimson",
            "muted green": "muted green",
        },
        category_to_mood={
            "geopolitical": "cold teal",
            "ai_tech": "cold teal",
            "corporate_power": "warm amber",
            "surveillance": "cold teal",
            "economic": "warm amber",
            "financial": "warm amber",
            "historical_power": "warm amber",
            "conflict": "muted crimson",
            "warfare": "muted crimson",
            "military": "muted crimson",
        },
    ),

    # Rotation
    rotation=RotationConfig(
        compositions=[
            "wide", "medium", "closeup", "environmental",
            "portrait", "overhead", "low_angle",
        ],
        max_consecutive_same_content_type=4,  # Original: max 4 consecutive same style
        max_consecutive_same_format=2,
        max_consecutive_same_palette=3,
        max_consecutive_close_up=1,
        act_weights={
            "act1": {"dossier": 0.75, "schema": 0.25, "echo": 0.00},
            "act2": {"dossier": 0.65, "schema": 0.30, "echo": 0.05},
            "act3": {"dossier": 0.40, "schema": 0.20, "echo": 0.40},
            "act4": {"dossier": 0.35, "schema": 0.20, "echo": 0.45},
            "act5": {"dossier": 0.50, "schema": 0.35, "echo": 0.15},
            "act6": {"dossier": 0.65, "schema": 0.35, "echo": 0.00},
        },
        scene_expander_style_distribution={
            1: {"dossier": 90, "schema": 10, "echo": 0},
            2: {"dossier": 70, "schema": 30, "echo": 0},
            3: {"dossier": 45, "schema": 20, "echo": 35},
            4: {"dossier": 35, "schema": 20, "echo": 45},
            5: {"dossier": 50, "schema": 35, "echo": 15},
            6: {"dossier": 65, "schema": 35, "echo": 0},
        },
    ),

    # Figure rules — anonymous figures allowed (faces obscured)
    figure_rules=FigureRulesConfig(
        allow_human_figures=True,
        allow_silhouettes=True,
        allow_mannequins=False,
        protagonist_config=None,
        negative_prompt_suffix=(
            "no visible faces, faces obscured by shadow or backlighting"
        ),
        people_words=[],
        people_replacements=[],
    ),

    # Scene description
    scene_description=SceneDescriptionConfig(
        system_prompt=(
            "You are a visual director creating cinematic photorealistic "
            "documentary image prompts for a YouTube documentary channel.\n\n"
            "Every prompt should feel like a still from a prestige documentary. "
            "Dark moody atmosphere, desaturated palette, Rembrandt lighting.\n\n"
            "Anonymous human figures with faces obscured by shadow, silhouette, "
            "or backlighting. Body language conveys emotion."
        ),
        metaphor_translation_table={
            "money_flow": "Show the institution: central bank, trading floor, vault",
            "power_consolidation": "Show the person/building: corporate HQ, signing ceremony",
        },
        quantitative_requirement=False,
        text_in_image_rules="no narrative text, only analytical data labels and readouts",
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
        thumbnail_text_style="bold block capitals, thick black outline",
    ),

    # Ken Burns
    ken_burns=KenBurnsConfig(
        direction_map={
            "wide": "slow_zoom_in",
            "medium": "slow_pan_right",
            "closeup": "slow_zoom_out",
            "environmental": "slow_pan_left",
            "portrait": "slow_zoom_in",
            "overhead": "slow_zoom_in",
            "low_angle": "slow_tilt_up",
        },
    ),

    # Raw data
    raw={
        "style_engine_prefix": _DOSSIER_PREFIX,
        "style_engine_suffix": _DOSSIER_SUFFIX,
    },
)
