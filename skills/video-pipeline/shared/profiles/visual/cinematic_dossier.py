"""Cinematic Dossier — The original 3-style documentary system.

The Dossier/Schema/Echo visual system that defined Economy FastForward's
first era. Prestige documentary photography with three visual substyles
rotating across a 6-act narrative structure.

Aesthetic: Dark moody photorealism. Rembrandt lighting, desaturated palette,
accent color pops. Anonymous human figures with faces obscured by shadow,
silhouette, or backlighting. Body language conveys emotion.

This is a COMPLETE, STANDALONE profile. Loading it as the active profile
produces a fully different visual output with zero holographic or clay
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
    SubstyleConfig,
    TemplateMetadata,
    ThumbnailConfig,
    VisualProfile,
)
from orchestrator.pipeline_constants import Models


# =============================================================================
# Section 1: Identity
# =============================================================================

_IDENTITY = dict(
    profile_id="cinematic_dossier",
    profile_name="Cinematic Photorealistic Dossier",
    description=(
        "Prestige documentary photography. Rembrandt lighting, anonymous "
        "human figures with faces obscured by shadow/silhouette/backlighting. "
        "3-style system: Dossier (60%), Schema (22%), Echo (18%). "
        "Best for geopolitics, finance, corporate power, historical analysis."
    ),
    version="3.0",
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
# Section 3: Style System — Dossier / Schema / Echo
# =============================================================================

_DOSSIER_PREFIX = (
    "Cinematic photorealistic still, dark moody atmosphere, desaturated palette, "
    "Rembrandt lighting with deep shadows, shot on Arri Alexa with Kodak Vision "
    "film stock, 16:9 cinematic composition."
)

# Per-substyle suffixes — appended AFTER scene description
_DOSSIER_SUBSTYLE_SUFFIX = (
    "cinematic photorealistic, single dramatic light source, Rembrandt lighting, "
    "deep shadows, desaturated color palette with {accent_color} accent, "
    "shallow depth of field, subtle film grain, dark moody atmosphere, "
    "documentary photography style, shot on Arri Alexa, 16:9"
)

_SCHEMA_SUBSTYLE_SUFFIX = (
    "cinematic photorealistic background with translucent glowing data overlay, "
    "thin luminous {accent_color} connection lines and node points, "
    "Bloomberg terminal meets surveillance system aesthetic, dark atmosphere, "
    "minimal and elegant, deep blacks with light-emitting data elements, "
    "subtle film grain, 16:9"
)

_ECHO_SUBSTYLE_SUFFIX = (
    "photorealistic with subtle oil painting texture, dramatic chiaroscuro "
    "period-appropriate lighting, {accent_color} tones, "
    "period-accurate costume and architecture detail, deep shadows, "
    "slightly soft focus with painterly grain, historical documentary style, "
    "heavy film grain, atmospheric and evocative, 16:9"
)

_DOSSIER_GENERAL_SUFFIX = (
    ", anonymous human figures with faces obscured by shadow silhouette or "
    "backlighting, cinematic depth of field, no text overlays, "
    "subtle ambient light, photorealistic rendering, 16:9 aspect ratio"
)

_STYLE_SYSTEM = StyleSystemConfig(
    style_prefix=_DOSSIER_PREFIX,
    style_suffix=_DOSSIER_GENERAL_SUFFIX,
    substyles={
        "dossier": SubstyleConfig(
            name="Dossier",
            weight=0.60,
            suffix=_DOSSIER_SUBSTYLE_SUFFIX,
            description=(
                "Investigation, corporate, power. Photorealistic with Rembrandt "
                "lighting and accent color highlights. The workhorse style — "
                "60% of all images."
            ),
        ),
        "schema": SubstyleConfig(
            name="Schema",
            weight=0.22,
            suffix=_SCHEMA_SUBSTYLE_SUFFIX,
            description=(
                "Systems, networks, data. Glowing translucent data overlays on "
                "dark photorealistic backgrounds. Bloomberg terminal aesthetic."
            ),
        ),
        "echo": SubstyleConfig(
            name="Echo",
            weight=0.18,
            suffix=_ECHO_SUBSTYLE_SUFFIX,
            description=(
                "Backstory, historical context. Painterly texture over photorealism, "
                "candlelit warm tones, period-accurate detail. Only in acts 3-5."
            ),
        ),
    },
    accent_colors={
        "geopolitical": "cold teal",
        "ai_tech": "cold teal",
        "corporate_power": "cold teal",
        "surveillance": "cold teal",
        "financial": "warm amber",
        "economic": "warm amber",
        "historical_power": "warm amber",
        "old_money": "warm amber",
        "conflict": "muted crimson",
        "warfare": "muted crimson",
        "political_violence": "muted crimson",
        "military": "muted crimson",
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
        "old_money": "warm amber",
        "conflict": "muted crimson",
        "warfare": "muted crimson",
        "political_violence": "muted crimson",
        "military": "muted crimson",
        "markets": "warm amber",
        "growth": "warm amber",
        "trade": "cold teal",
    },
)


# =============================================================================
# Section 4: Rotation & Composition
# =============================================================================

_ROTATION = RotationConfig(
    compositions=[
        "wide", "medium", "closeup", "environmental",
        "portrait", "overhead", "low_angle",
    ],
    # Dossier uses max_consecutive_same_style (mapped to content_type field)
    max_consecutive_same_content_type=4,
    max_consecutive_same_format=2,
    max_consecutive_same_palette=3,
    max_consecutive_close_up=1,
    act_weights={
        "act1": {"dossier": 0.80, "schema": 0.20, "echo": 0.00},
        "act2": {"dossier": 0.65, "schema": 0.30, "echo": 0.05},
        "act3": {"dossier": 0.55, "schema": 0.20, "echo": 0.25},
        "act4": {"dossier": 0.50, "schema": 0.20, "echo": 0.30},
        "act5": {"dossier": 0.45, "schema": 0.35, "echo": 0.20},
        "act6": {"dossier": 0.75, "schema": 0.25, "echo": 0.00},
    },
    scene_expander_style_distribution={
        1: {"dossier": 90, "schema": 10, "echo": 0},
        2: {"dossier": 70, "schema": 30, "echo": 0},
        3: {"dossier": 45, "schema": 20, "echo": 35},
        4: {"dossier": 35, "schema": 20, "echo": 45},
        5: {"dossier": 50, "schema": 35, "echo": 15},
        6: {"dossier": 65, "schema": 35, "echo": 0},
    },
)


# =============================================================================
# Section 5: Figure Rules — anonymous human figures
# =============================================================================

_FIGURE_RULES = FigureRulesConfig(
    allow_human_figures=True,
    allow_silhouettes=True,
    allow_mannequins=False,
    protagonist_config=None,
    negative_prompt_suffix=(
        "no visible recognizable faces of real named public figures, "
        "faces always obscured by shadow silhouette or backlighting, "
        "body language conveys emotion instead of facial expression"
    ),
    people_words=[],  # People are ALLOWED in dossier — no filtering needed
    people_replacements=[],  # No auto-replacement — people stay in prompts
)


# =============================================================================
# Section 6: Scene Description Rules
# =============================================================================

_SCENE_DESCRIPTION = SceneDescriptionConfig(
    system_prompt=(
        "You are a visual director creating cinematic photorealistic documentary "
        "image prompts for a YouTube documentary channel.\n\n"
        "Every prompt should feel like a still from a prestige documentary — "
        "dark moody atmosphere, desaturated palette, Rembrandt lighting with "
        "deep shadows.\n\n"
        "HUMAN FIGURES: Show real people, real places, real objects. Anonymous "
        "figures with faces obscured by shadow, silhouette, or backlighting. "
        "Body language and posture convey emotion — not facial expressions.\n\n"
        "NEVER visualize metaphors literally. When the script says 'markets "
        "are bleeding' — show a trader at a terminal with red screens, NOT "
        "literal blood. When it says 'empire crumbling' — show the actual "
        "institution under pressure, NOT rubble.\n\n"
        "FILMABLE SCENE RULE: Every image must depict a scene a documentary "
        "crew could actually photograph. Real locations, real lighting, real "
        "people in real situations. No fantasy, no sci-fi, no impossible physics.\n\n"
        "VISUAL STORYTELLING TABLE:\n"
        "| Abstract Concept | DO Show | DON'T Show |\n"
        "| Money flowing | Trading floor, vault, wire transfer screen | Literal river of money |\n"
        "| Power consolidation | Corporate HQ, signing ceremony, closed doors | Giant hand crushing things |\n"
        "| Economic pressure | Empty store shelves, price tags, long queues | Abstract pressure waves |\n"
        "| Military force | Fleet at sea, weapon systems, command center | Abstract force arrows |\n"
        "| Political tension | Diplomatic table, embassy exterior, protests | Lightning bolts between leaders |\n"
        "| Surveillance state | CCTV cameras, server rooms, data centers | Giant eye in the sky |\n"
        "| Market crash | Trading floor chaos, red screens, empty desks | Literal falling graph |\n"
        "| Historical parallel | Period architecture, vintage documents, old photos | Time portal |\n"
    ),
    metaphor_translation_table={
        "money_flow": "Show the institution: central bank vault, trading floor terminals, wire transfer screens",
        "power_consolidation": "Show the person/building: corporate HQ, signing ceremony, closed-door meeting",
        "economic_pressure": "Show the evidence: empty shelves, price tags, queues, shuttered storefronts",
        "military_force": "Show the hardware: fleet at sea, command center, satellite imagery",
        "political_tension": "Show the setting: diplomatic table, embassy exterior, protest crowds from behind",
        "surveillance_state": "Show the infrastructure: CCTV arrays, server rooms, data center corridors",
        "market_crash": "Show the aftermath: trading floor chaos, red terminal screens, empty desks",
        "historical_parallel": "Show the period: vintage architecture, aged documents, sepia-toned locations",
        "corruption": "Show the setting: luxury office, offshore bank exterior, document shredder",
        "inequality": "Show the contrast: penthouse vs slum, private jet vs bus stop, boardroom vs factory floor",
    },
    quantitative_requirement=False,
    text_in_image_rules=(
        "no narrative text in images — only naturally occurring text visible in "
        "the scene (street signs, terminal displays, document headers)"
    ),
)


# =============================================================================
# Section 7: Animation — DISABLED for Dossier style
# =============================================================================

_ANIMATION = AnimationConfig(
    animation_model="disabled",
    animation_cost_per_clip=0.0,
    motion_templates={},
    motion_base_rule="Animation not used with cinematic dossier style",
    intensity_levels={},
    universal_rules=[],
    banned_motion_words=[],
    emotional_motion_dict={},
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
        "Generic building silhouette or symbolic hand gesture. "
        "No named political figures — no recognizable faces."
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
    display_name="Cinematic Intelligence Briefing",
    category="documentary",
    tags=["dark", "cinematic", "geopolitics", "finance", "thriller", "documentary", "Rembrandt"],
    description=(
        "Dark, moody photorealistic stills with Rembrandt lighting. Three visual "
        "substyles (Dossier, Schema, Echo) create a documentary thriller aesthetic. "
        "Anonymous human figures with obscured faces convey emotion through body "
        "language. Best for: geopolitics, finance, corporate power, historical analysis."
    ),
    preview_prompts=[
        (
            "A lone figure in a dark tailored suit standing at the end of a "
            "rain-slicked corridor in a government building, single overhead "
            "light casting Rembrandt shadows, cold teal accent on the wet floor "
            "reflections, cinematic depth of field, shot on Arri Alexa, 16:9"
        ),
        (
            "Dark photorealistic aerial view of a sprawling financial district "
            "at night, overlaid with translucent glowing cold teal connection "
            "lines linking major bank towers, Bloomberg terminal meets "
            "surveillance aesthetic, subtle film grain, 16:9"
        ),
        (
            "A Renaissance-era council chamber, heavy wooden table covered in "
            "maps and wax-sealed correspondence, dramatic chiaroscuro candlelight, "
            "warm amber tones, period-accurate costume detail on anonymous "
            "robed figures, oil painting texture, heavy film grain, 16:9"
        ),
    ],
    best_for=["geopolitics", "finance", "corporate power", "historical analysis"],
    cost_tier="mid",
    estimated_cost_per_video={
        "10min_no_animation": 4.50,
        "10min_with_animation": 12.00,
        "20min_no_animation": 8.00,
        "20min_with_animation": 20.00,
    },
)


# =============================================================================
# Section 11: Raw data
# =============================================================================

_RAW = {
    "style_engine_prefix": _DOSSIER_PREFIX,
    "style_engine_suffix": _DOSSIER_GENERAL_SUFFIX,
    # Dossier rotation rules (for sequencer compatibility)
    "substyle_rotation_rules": {
        "max_consecutive_same_style": 4,
        "echo_allowed_acts": [3, 4, 5],
        "echo_cluster_min": 2,
        "echo_cluster_max": 3,
        "post_echo_must_be": "dossier",
        "schema_max_consecutive": 1,
        "schema_max_consecutive_act5": 2,
        "first_image_must_be": "dossier",
        "last_image_must_be": "dossier",
    },
    # Accent color hex values
    "accent_color_hex": {
        "cold teal": "#1a5c6b",
        "warm amber": "#b8860b",
        "muted crimson": "#8b1a1a",
        "muted green": "#2d5a27",
    },
    # Valid scene models
    "valid_scene_models": {
        "seedream-v4": "Seed Dream 4.0 (default — cinematic dossier, $0.025/img)",
        "nano-banana-2": "Nano Banana 2 (alternative — reference support, $0.025/img)",
    },
    # Material vocabulary for dossier style
    "material_vocabulary": {
        "premium": [
            "mahogany desk", "leather briefcase", "gold cufflinks",
            "crystal decanter", "silk tie", "brass desk lamp",
        ],
        "institutional": [
            "concrete government building", "steel filing cabinets",
            "fluorescent-lit corridor", "security checkpoint",
            "reinforced vault door", "diplomatic conference table",
        ],
        "historical": [
            "aged parchment", "wax seal", "oil painting frame",
            "iron chandelier", "stone archway", "wooden ship hull",
        ],
        "data": [
            "Bloomberg terminal", "surveillance monitor wall",
            "fiber optic cables", "server rack LEDs",
            "radar display", "encrypted communication device",
        ],
    },
    # Prompt word budget
    "prompt_min_words": 62,
    "prompt_max_words": 84,
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
