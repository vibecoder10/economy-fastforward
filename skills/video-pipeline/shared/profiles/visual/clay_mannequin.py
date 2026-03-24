"""Clay Mannequin — The original 3D editorial conceptual render style.

The earliest Economy FastForward visual system using faceless ceramic
mannequin figures in diorama compositions. The protagonist mannequin has
a distinctive golden amber chest glow that tracks narrative intensity.

Aesthetic: 3D editorial clay render, matte ceramic surfaces, studio-lit
diorama composition. Faceless smooth-skinned mannequin figures with subtle
anatomical indentations. Mixed material contrasts — brushed steel, frosted
glass, worn leather, polished chrome. Protagonist has warm amber chest glow.

This is a COMPLETE, STANDALONE profile. Loading it as the active profile
produces a fully different visual output with zero holographic or dossier
style leakage.
"""

from .schema import (
    AnimationConfig,
    FigureRulesConfig,
    ImageGenConfig,
    KenBurnsConfig,
    RotationConfig,
    SceneDescriptionConfig,
    StyleSystemConfig,
    TemplateMetadata,
    ThumbnailConfig,
    VisualProfile,
)
from orchestrator.pipeline_constants import Models


# =============================================================================
# Section 1: Identity
# =============================================================================

_IDENTITY = dict(
    profile_id="clay_mannequin",
    profile_name="3D Clay Mannequin Render",
    description=(
        "3D editorial conceptual render with faceless matte gray ceramic "
        "mannequin figures. Protagonist has golden amber chest glow that "
        "tracks narrative intensity. Department store display diorama "
        "aesthetic with mixed material contrasts."
    ),
    version="2.0",
    channel="economy_fastforward",
)


# =============================================================================
# Section 2: Image Generation Config
# =============================================================================

_IMAGE_GEN = ImageGenConfig(
    scene_model="seedream-v4",
    scene_model_params={
        "aspect_ratio": "16:9",
        "resolution": "1K",
        "output_format": "png",
    },
    scene_cost_per_image=0.025,
    thumbnail_model=Models.IMAGE_THUMBNAIL,
    thumbnail_model_params={
        "aspect_ratio": "16:9",
        "resolution": "2K",
        "output_format": "png",
    },
    thumbnail_cost_per_image=0.04,
)


# =============================================================================
# Section 3: Style System — single style, no substyles
# =============================================================================

_CLAY_PREFIX = (
    "3D editorial clay render, matte ceramic surfaces, studio-lit diorama "
    "composition, faceless smooth-skinned mannequin figures with subtle "
    "anatomical indentations, mixed material contrasts — brushed steel, "
    "frosted glass, worn leather, polished chrome."
)

_CLAY_SUFFIX = (
    ", dramatic directional studio lighting, shallow depth of field, "
    "volumetric atmosphere, cinematic 16:9 composition, "
    "material surfaces: concrete, chrome, brushed steel, glass, leather, velvet, "
    "color grade: desaturated with selective warm accent lighting, "
    "no photorealistic skin, no flat 2D, no anime, no cartoon"
)

_STYLE_SYSTEM = StyleSystemConfig(
    style_prefix=_CLAY_PREFIX,
    style_suffix=_CLAY_SUFFIX,
    substyles={},  # Clay uses single style — no substyle rotation
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
)


# =============================================================================
# Section 4: Rotation & Composition — cycling only, no substyles
# =============================================================================

_ROTATION = RotationConfig(
    compositions=[
        "wide", "medium", "closeup", "environmental",
        "portrait", "overhead", "low_angle",
    ],
    # Clay uses simple composition cycling — no substyle constraints
    max_consecutive_same_content_type=3,  # Generic variety rule
    max_consecutive_same_format=2,
    max_consecutive_same_palette=3,
    max_consecutive_close_up=1,
    act_weights={},  # No substyle weights — single style system
    scene_expander_style_distribution={},  # Not applicable
)


# =============================================================================
# Section 5: Figure Rules — mannequins with protagonist glow
# =============================================================================

_FIGURE_RULES = FigureRulesConfig(
    allow_human_figures=False,
    allow_silhouettes=False,
    allow_mannequins=True,
    protagonist_config={
        "glow_color": "gold/amber",
        "glow_intensity_range": [0, 100],
        "base_material": "smooth matte gray ceramic",
        "glow_location": "chest/heart area",
        "description": (
            "Faceless mannequin with warm amber glow emanating from chest, "
            "intensity tracks narrative arc: steady=comfort, flickering=unease, "
            "dimming=loss, surging=awakening"
        ),
        "glow_intensity_mapping": {
            "comfort": "steady warm glow, 40-60% intensity",
            "tension": "flickering glow, 50-70% intensity, uneven",
            "unease": "faint flickering glow, 20-40% intensity",
            "loss": "dim fading glow, 5-15% intensity",
            "awakening": "surging bright glow, 80-100% intensity",
            "neutral": "gentle warm glow, 30-50% intensity",
        },
        "background_characters": "neutral gray droids with no glow",
    },
    negative_prompt_suffix=(
        "no photorealistic skin, no flat 2D, no realistic skin texture, "
        "no anime, no cartoon, no facial features, smooth matte gray ceramic"
    ),
    people_words=[
        "person", "people", "man", "woman", "face", "faces",
        "smile", "expression", "eyes", "mouth", "hair",
    ],
    people_replacements=[
        (r"\bperson\b", "mannequin figure"),
        (r"\bpeople\b", "mannequin figures"),
        (r"\bman\b", "mannequin figure"),
        (r"\bwoman\b", "mannequin figure"),
        (r"\bfaces?\b", "smooth featureless head"),
        (r"\bsmil(?:e|ing)\b", "tilted head posture"),
        (r"\bexpression\b", "body language"),
        (r"\beyes\b", "smooth eye indentations"),
        (r"\bmouth\b", "smooth surface"),
        (r"\bhair\b", "smooth ceramic head"),
    ],
)


# =============================================================================
# Section 6: Scene Description Rules
# =============================================================================

_SCENE_DESCRIPTION = SceneDescriptionConfig(
    system_prompt=(
        "You are a visual director creating 3D CLAY MANNEQUIN RENDER image "
        "prompts for a YouTube documentary channel.\n\n"
        "Every image is a conceptual editorial diorama — like a high-end "
        "department store window display that tells a story. Faceless matte "
        "gray ceramic mannequin figures with smooth anatomical indentations "
        "where eyes, nose, and mouth would be.\n\n"
        "THE PROTAGONIST: One mannequin has a warm golden amber glow "
        "emanating from its chest/heart area. This is the viewer's avatar. "
        "The glow intensity tracks the narrative: steady=comfort, "
        "flickering=unease, dimming=loss, surging=awakening.\n\n"
        "BACKGROUND CHARACTERS: Neutral gray mannequins with NO glow. "
        "They are scenery, not protagonists.\n\n"
        "CAMERA RULES:\n"
        "- Eye level = neutral observation\n"
        "- Overhead = vulnerability, being watched\n"
        "- Low angle = power, authority, intimidation\n"
        "- Push in = intimacy, focus, revelation\n\n"
        "MATERIAL PALETTE: Every scene uses mixed material contrasts — "
        "concrete, chrome, brushed steel, glass, leather, velvet. The "
        "diorama should feel tactile and three-dimensional.\n\n"
        "NEVER visualize metaphors literally. When the script says 'economy "
        "crumbling' — show mannequins in a cracked concrete environment with "
        "falling debris, NOT a literal crumbling pie chart.\n\n"
        "FILMABLE DIORAMA RULE: Every image must look like it could be a "
        "physical department store display you could walk around and photograph."
    ),
    metaphor_translation_table={
        "money_flow": "Show mannequin at bank vault diorama, stacks of prop currency, conveyor belt",
        "power_consolidation": "Show mannequin in executive chair, others standing below on lower platform",
        "economic_pressure": "Show mannequin surrounded by shrinking walls, price tags, empty shelves",
        "military_force": "Show mannequin figures around scale model warships and tanks",
        "political_tension": "Show mannequins seated opposite each other at long diplomatic table",
        "surveillance_state": "Show mannequin under spotlight with camera props and glass panels",
        "market_crash": "Show mannequin amid falling prop stock certificates and broken glass",
        "corruption": "Show mannequin in luxury setting with hidden compartment props",
        "inequality": "Show split diorama: gold platform vs concrete pit, mannequins at each level",
    },
    quantitative_requirement=False,
    text_in_image_rules="no text overlays — all storytelling through spatial composition and materials",
)


# =============================================================================
# Section 7: Animation — selective (hero shots only)
# =============================================================================

_CLAY_LOW_MOTION = {
    "wide_establishing": "Static shot. Protagonist's chest glow pulses slowly with gentle warmth.",
    "medium_scene": "Static shot. One material element shifts slightly — a glass panel catches light.",
    "closeup_detail": "Static shot. Protagonist's glow flickers once, casting subtle shadow shift.",
    "environmental": "Static shot. Volumetric atmosphere drifts slowly through the diorama.",
    "portrait": "Static shot. Protagonist mannequin's glow breathes — slow intensity cycle.",
    "overhead": "Static shot. One small prop element shifts position on the diorama surface.",
    "low_angle": "Static shot. Light source shifts subtly, changing shadow angles on ceramic surfaces.",
}

_CLAY_MEDIUM_MOTION = {
    "wide_establishing": "Static shot. Protagonist's chest glow intensifies as they step forward. Background mannequins remain frozen.",
    "medium_scene": "Static shot. A material element transforms — glass cracks, metal bends. Protagonist reacts with glow shift.",
    "closeup_detail": "Static shot. Protagonist's hand reaches toward an object. Glow light spills onto the surface.",
    "environmental": "Static shot. Environmental elements shift — walls close in or open up. Lighting changes temperature.",
    "portrait": "Static shot. Protagonist mannequin turns head slightly. Glow shifts from steady to flickering.",
    "overhead": "Static shot. Props rearrange on the diorama surface as if moved by invisible force.",
    "low_angle": "Static shot. Shadow patterns sweep across mannequin as light source moves overhead.",
}

_CLAY_HIGH_MOTION = {
    "wide_establishing": "Static shot. Diorama environment fractures — concrete cracks, glass shatters. Protagonist's glow surges bright.",
    "medium_scene": "Static shot. Background mannequins topple in sequence. Protagonist stands firm, glow blazing.",
    "closeup_detail": "Static shot. Object in frame disintegrates into particles. Protagonist's glow pulses with each impact.",
    "environmental": "Static shot. Entire diorama platform tilts. Materials slide and crash. Volumetric dust erupts.",
    "portrait": "Static shot. Protagonist's glow explodes outward in a burst of amber light, then contracts.",
    "overhead": "Static shot. Impact crater forms on diorama surface. Debris scatters outward from center.",
    "low_angle": "Static shot. Towering structure behind mannequin collapses. Protagonist's shadow stretches across frame.",
}

_ANIMATION = AnimationConfig(
    animation_model=Models.ANIMATION_GROK,
    animation_cost_per_clip=0.10,
    motion_templates={
        **{f"low_{k}": v for k, v in _CLAY_LOW_MOTION.items()},
        **{f"medium_{k}": v for k, v in _CLAY_MEDIUM_MOTION.items()},
        **{f"high_{k}": v for k, v in _CLAY_HIGH_MOTION.items()},
    },
    motion_base_rule=(
        "Maintain the full original frame composition. Preserve the protagonist "
        "mannequin's golden amber chest glow throughout the animation — do not "
        "let the model wash it out or change its color."
    ),
    intensity_levels={
        "low": "Subtle ambient motion. Glow breathes, one material element shifts.",
        "medium": "Active reveal. Up to two elements animate, glow reacts to events.",
        "high": "Dramatic action. Environment fractures, glow surges or dims.",
    },
    universal_rules=[
        "Maintain the full original frame composition.",
        "Protagonist's golden amber chest glow must remain visible throughout.",
        "Mannequin surfaces must remain matte ceramic — no skin-like texture.",
        "Material contrasts (concrete, chrome, glass) must stay consistent.",
        "No facial features should appear on any mannequin at any point.",
    ],
    banned_motion_words=[
        "realistic skin", "facial expression", "hair movement", "eye movement",
        "lip movement", "breathing chest", "muscle flex",
    ],
    emotional_motion_dict={
        "comfort_safety": [
            "glow steadies", "glow warms", "materials smooth",
            "light softens", "space opens up",
        ],
        "tension_unease": [
            "glow flickers", "materials vibrate", "shadows sharpen",
            "space constricts", "surfaces crack",
        ],
        "loss_absence": [
            "glow dims", "glow fades", "materials crumble",
            "surfaces erode", "space empties",
        ],
        "awakening_power": [
            "glow surges", "glow blazes", "glow explodes outward",
            "materials transform", "space expands",
        ],
        "confrontation": [
            "glow intensifies", "materials shatter", "surfaces fracture",
            "props scatter", "environment tilts",
        ],
    },
)


# =============================================================================
# Section 8: Thumbnail Identity
# =============================================================================

_THUMBNAIL = ThumbnailConfig(
    thumbnail_style="bright_editorial_illustration",
    thumbnail_text_color="#FFD700",
    thumbnail_text_style="bold block capitals, thick black outline",
    thumbnail_max_words_per_line=4,
    thumbnail_max_lines=2,
    thumbnail_background="simple, recognizable, reads at 160x90px",
    thumbnail_palette_max_colors=4,
    thumbnail_prompt_templates={},  # Templates in thumbnail_generator/templates.py
    thumbnail_color_presets={
        "geopolitics": ["#1a5c6b", "#FFD700", "#333", "#fff"],
        "finance": ["#b8860b", "#FFD700", "#333", "#fff"],
        "conflict": ["#8b1a1a", "#FFD700", "#333", "#fff"],
    },
    thumbnail_system_prompt="",  # Full prompt in anthropic_client.py
    thumbnail_figure_rules=(
        "Mannequin figure silhouette or symbolic object. "
        "No recognizable faces — use featureless ceramic head shape."
    ),
)


# =============================================================================
# Section 9: Ken Burns Config
# =============================================================================

_KEN_BURNS = KenBurnsConfig(
    direction_map={
        "wide": "slow_zoom_in",
        "medium": "slow_pan_right",
        "closeup": "slow_zoom_out",
        "environmental": "slow_pan_left",
        "portrait": "slow_zoom_in",
        "overhead": "slow_zoom_in",
        "low_angle": "slow_tilt_up",
    },
    presets={
        "slow_zoom_in": {"start_scale": 1.0, "end_scale": 1.15},
        "slow_zoom_out": {"start_scale": 1.15, "end_scale": 1.0},
        "slow_pan_right": {"start_x_offset": -40, "end_x_offset": 40},
        "slow_pan_left": {"start_x_offset": 40, "end_x_offset": -40},
        "slow_tilt_up": {"start_y_offset": 30, "end_y_offset": -30},
    },
    base_duration=11.0,
    pan_alternates={
        "slow_pan_right": "slow_pan_left",
        "slow_pan_left": "slow_pan_right",
    },
)


# =============================================================================
# Section 10: Template Metadata (StoryEngine)
# =============================================================================

_TEMPLATE_METADATA = TemplateMetadata(
    display_name="Clay Mannequin Dioramas",
    category="conceptual",
    tags=["3D", "clay", "mannequin", "diorama", "conceptual", "editorial", "warm"],
    description=(
        "3D editorial conceptual renders using faceless matte ceramic mannequin "
        "figures in department store diorama compositions. A warm golden protagonist "
        "glow tracks narrative emotion. Mixed material contrasts create tactile, "
        "three-dimensional storytelling. Best for: explainers, personal finance, "
        "social commentary, philosophical content."
    ),
    preview_prompts=[
        (
            "3D editorial clay render, a faceless matte gray ceramic mannequin "
            "with warm golden amber chest glow standing alone in a vast concrete "
            "atrium, surrounded by towering chrome pillars and frosted glass "
            "walls, dramatic directional studio lighting, shallow depth of field, "
            "cinematic 16:9 composition"
        ),
        (
            "3D editorial clay render, two faceless ceramic mannequins seated "
            "at opposite ends of a long brushed steel conference table, the "
            "protagonist (golden chest glow) on one side, neutral gray figure "
            "on the other, leather chairs, glass partition between them, "
            "overhead spotlight, cinematic 16:9 composition"
        ),
        (
            "3D editorial clay render, overhead view of a diorama showing a "
            "mannequin with amber chest glow walking through a cracked concrete "
            "maze, velvet-lined dead ends, chrome mirrors reflecting the glow, "
            "volumetric atmosphere, desaturated with warm accent, 16:9 composition"
        ),
    ],
    best_for=["explainers", "personal finance", "social commentary", "philosophy"],
    cost_tier="mid",
    estimated_cost_per_video={
        "10min_no_animation": 4.50,
        "10min_with_animation": 8.00,
        "20min_no_animation": 8.00,
        "20min_with_animation": 15.00,
    },
)


# =============================================================================
# Section 11: Raw data
# =============================================================================

_RAW = {
    "style_engine_prefix": _CLAY_PREFIX,
    "style_engine_suffix": _CLAY_SUFFIX,
    # Valid scene models
    "valid_scene_models": {
        "seedream-v4": "Seed Dream 4.0 (default — clay mannequin, $0.025/img)",
        "nano-banana-2": "Nano Banana 2 (alternative, $0.025/img)",
    },
    # Material vocabulary (unique to clay style)
    "material_vocabulary": {
        "premium": [
            "polished chrome", "brushed gold", "marble", "leather", "velvet",
        ],
        "institutional": [
            "concrete", "steel", "frosted glass", "matte ceramic",
        ],
        "decay": [
            "rusted metal", "cracked concrete", "peeling paint", "oxidized copper",
        ],
        "data": [
            "glowing neon", "holographic surfaces", "digital grids", "fiber optic",
        ],
    },
    # Prompt word budget
    "prompt_min_words": 62,
    "prompt_max_words": 84,
    # Protagonist glow intensity presets (for animation)
    "glow_intensity_by_act": {
        "act1": 50,   # Neutral — setting the scene
        "act2": 40,   # Slight unease — tension building
        "act3": 25,   # Dimming — complications mount
        "act4": 60,   # Flickering — conflict peaks
        "act5": 85,   # Surging — climax/revelation
        "act6": 70,   # Steady warm — resolution
    },
    # Camera meaning vocabulary (for prompt building)
    "camera_meaning": {
        "eye_level": "neutral observation — viewer is equal to mannequin",
        "overhead": "vulnerability — being watched, exposed, small",
        "low_angle": "power — authority, intimidation, towering presence",
        "push_in": "intimacy — focus, revelation, emotional close-up",
        "pull_back": "isolation — loneliness, scale, being overwhelmed",
    },
    # Default config values
    "default_config": {
        "image_duration_seconds": 11,
        "video_duration_seconds": 1500,
        "total_images": 120,
        "images_per_scene": 6,
        "scenes_per_video": 20,
    },
}


# =============================================================================
# PROFILE — the single export
# =============================================================================

PROFILE = VisualProfile(
    **_IDENTITY,
    image_gen=_IMAGE_GEN,
    style_system=_STYLE_SYSTEM,
    rotation=_ROTATION,
    figure_rules=_FIGURE_RULES,
    scene_description=_SCENE_DESCRIPTION,
    animation=_ANIMATION,
    thumbnail=_THUMBNAIL,
    ken_burns=_KEN_BURNS,
    template_metadata=_TEMPLATE_METADATA,
    raw=_RAW,
)
