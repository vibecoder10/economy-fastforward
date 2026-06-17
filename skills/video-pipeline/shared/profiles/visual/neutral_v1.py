"""Neutral Documentary — the style-agnostic default visual profile.

This is the IMAGE-engine equivalent of the neutral text engine: it keeps
all of the universal *craft* (the five-scene-type system, the
"describe faces + expressions", "one action per character", "name the
environment specifically", "include one storytelling detail", rotation
rules, camera/ken-burns math) while leaving the *identity* — the actual
LOOK (medium, palette, characters) — as runtime slots.

It deliberately declares **no medium of its own**: ``style_prefix`` and
``character_prefix`` are empty, and the suffix is purely technical
(aspect ratio / no black bars). The channel's look is injected at prompt
build time from the ``VISUAL_STYLE_DESCRIPTION`` environment variable (the
channel's free-text style, fed from ``IdentityContext.visual_style``) or a
per-video ``image_style_override`` — see
``image_prompts/engine/prompt_builder.py``. So a channel that says
"warm hand-drawn watercolor storybook art" or "soft 3D Pixar CG" gets THAT
look front-loaded into every prompt, with zero hardcoded "2D animated
illustration / ink outlines / earthy palette".

It allows human figures with neutral, niche-agnostic guidance (no national
leaders, no geopolitics archetypes). The Power Doctrine look survives as the
loadable ``cinematic_illustration`` preset; this profile is just the default.

This is a COMPLETE, STANDALONE profile.
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
    profile_id="neutral_v1",
    profile_name="Neutral Documentary",
    description=(
        "Style-agnostic default profile. Keeps the universal image craft "
        "(scene-type variety, expressive characters, specific environments, "
        "purposeful lighting, anti-repetition rotation) but declares no medium "
        "or palette of its own — the channel's look is injected at runtime. "
        "Allows human figures with neutral guidance and works for any niche."
    ),
    version="1.0",
    channel="generic",
)


# =============================================================================
# Section 2: Image Generation Config
# =============================================================================

_IMAGE_GEN = ImageGenConfig(
    scene_model=Models.IMAGE_SCENE,
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
    thumbnail_cost_per_image=0.075,
)


# =============================================================================
# Section 3: Style System — 5 scene types, NO baked-in medium
# =============================================================================

# The neutral profile intentionally declares no medium prefix. The channel's
# look is front-loaded at build time (VISUAL_STYLE_DESCRIPTION / per-video
# override). Leaving these empty makes that injection the leading directive.
_CHARACTER_PREFIX = ""
_ENVIRONMENT_PREFIX = ""

# Purely technical tail — no style/palette words that would lock in a look.
_SUFFIX = " Full-bleed 16:9 composition, no black bars."

_STYLE_SYSTEM = StyleSystemConfig(
    style_prefix=_ENVIRONMENT_PREFIX,
    character_prefix=_CHARACTER_PREFIX,
    style_suffix=_SUFFIX,
    substyles={
        # NOTE: keys are the engine's scene-type vocabulary (the scene
        # expander + sequencer route by these exact keys). The names and
        # suffixes are neutral identity, the keys are craft structure.
        "power_move": SubstyleConfig(
            name="Interaction / Confrontation",
            weight=0.275,
            suffix=(
                "Two or more people interacting with a clear emotional dynamic, "
                "expressive faces, purposeful staging and directional lighting"
            ),
            description=(
                "Two or more characters in a moment of interaction or tension — "
                "a decision, an exchange, a disagreement, a hand-off. Characters "
                "show emotion through facial expression and body language."
            ),
        ),
        "lone_figure": SubstyleConfig(
            name="Lone Figure",
            weight=0.225,
            suffix=(
                "Single person in a solitary moment of weight, single-source "
                "lighting, expressive face showing the emotional stakes"
            ),
            description=(
                "A single character at a turning point — focus, reflection, "
                "realization. The face carries the moment."
            ),
        ),
        "environment": SubstyleConfig(
            name="Environment / Establishing",
            weight=0.175,
            suffix=(
                "No people or only tiny distant figures, natural directional "
                "lighting, location and atmosphere establish context"
            ),
            description=(
                "An establishing location that grounds the narrative. Used for "
                "transitions, act breaks, and setting context."
            ),
        ),
        "data_hud": SubstyleConfig(
            name="Information / Diagram",
            weight=0.125,
            suffix=(
                "Clear informational graphic — chart, diagram, or labeled map — "
                "with one key figure emphasized, clean legible layout"
            ),
            description=(
                "A clear visual for a pure information beat — a statistic, a "
                "chart, a labeled diagram. One number or label leads. "
                "Use sparingly (10-15% of scenes)."
            ),
        ),
        "object_closeup": SubstyleConfig(
            name="Object Close-up",
            weight=0.125,
            suffix=(
                "Tight close-up of a single object that carries narrative "
                "weight, shallow depth of field, contextual details nearby"
            ),
            description=(
                "A tight shot on a physical object that matters to the story — "
                "a tool, a document, an artifact, a product."
            ),
        ),
    },
    accent_colors={
        # Color-mood is unused on the profile assembly path (the channel look
        # drives palette), but a benign default keeps the sequencer happy.
        "default": "neutral",
    },
    accent_color_to_mood={},
    category_to_mood={},
)


# =============================================================================
# Section 4: Rotation & Composition (pure craft — anti-repetition)
# =============================================================================

_ROTATION = RotationConfig(
    compositions=[
        "wide", "medium", "closeup", "environmental",
        "portrait", "overhead", "low_angle",
    ],
    max_consecutive_same_content_type=3,
    max_consecutive_same_format=2,
    max_consecutive_same_palette=3,
    max_consecutive_close_up=1,
    act_weights={},
    scene_expander_style_distribution={
        1: {"power_move": 30, "lone_figure": 25, "environment": 25, "data_hud": 10, "object_closeup": 10},
        2: {"power_move": 30, "lone_figure": 25, "environment": 15, "data_hud": 15, "object_closeup": 15},
        3: {"power_move": 25, "lone_figure": 25, "environment": 15, "data_hud": 20, "object_closeup": 15},
        4: {"power_move": 30, "lone_figure": 20, "environment": 15, "data_hud": 15, "object_closeup": 20},
        5: {"power_move": 25, "lone_figure": 20, "environment": 20, "data_hud": 15, "object_closeup": 20},
        6: {"power_move": 30, "lone_figure": 25, "environment": 20, "data_hud": 10, "object_closeup": 15},
    },
)


# =============================================================================
# Section 5: Figure Rules — people allowed, NO national archetypes
# =============================================================================

_FIGURE_RULES = FigureRulesConfig(
    allow_human_figures=True,
    allow_silhouettes=True,
    allow_mannequins=False,
    protagonist_config={
        "body": "a real, expressive human character rendered in the channel's look",
        "identity_method": "facial features, expression, clothing, and context",
        # No archetypes — characters are described from the script + the
        # channel's cast, never routed to national-leader templates.
        "archetypes": {},
    },
    negative_prompt_suffix="",
    people_words=[],          # no people-stripping for the neutral default
    people_replacements=[],
)


# =============================================================================
# Section 6: Scene Description Rules — neutral craft system prompt
# =============================================================================

_SCENE_DESCRIPTION = SceneDescriptionConfig(
    system_prompt=(
        "You are a visual director writing SUBJECT DESCRIPTIONS for image prompts. "
        "A separate system adds the channel's art style, the camera, and the "
        "technical suffix — you write ONLY what the image shows "
        "(subject + action + environment).\n\n"

        "YOUR OUTPUT = 20-40 words describing WHAT is in the frame. "
        "Do NOT include any of these (they are added automatically):\n"
        "- Art style / medium (that comes from the channel's look)\n"
        "- Camera angle ('wide shot', 'close-up', 'medium shot')\n"
        "- Palette / texture / aspect ratio\n\n"

        "FIVE SCENE TYPES — classify each image as one:\n\n"

        "1. INTERACTION (25-30%) — Two or more people in a moment together\n"
        "Write: [PERSON A with EXPRESSION] [ACTION] while [PERSON B with EXPRESSION] "
        "[REACTION]. [ENVIRONMENT]. [LIGHTING].\n"
        "Ex: A chef with a focused frown demonstrates a knife cut while a young "
        "student leans in wide-eyed, bright tiled teaching kitchen with hanging "
        "copper pans, warm overhead lighting.\n\n"

        "2. LONE FIGURE (20-25%) — Single person at a turning point\n"
        "Write: [PERSON with EXPRESSION] [SOLITARY ACTION] in [ENVIRONMENT]. "
        "[KEY OBJECT]. [LIGHTING].\n"
        "Ex: A marathon runner with exhausted determination ties her shoe at an "
        "empty pre-dawn starting line, race bib catching the first light, cool "
        "blue morning haze.\n\n"

        "3. ENVIRONMENT / ESTABLISHING (15-20%) — Location, no people\n"
        "Write: [SPECIFIC LOCATION] at [TIME/WEATHER]. [KEY VISUAL DETAIL].\n"
        "Ex: A terraced rice field in the highlands at sunrise, mist pooling in "
        "the valleys, a single wooden footbridge crossing a stream, golden light "
        "on the water.\n\n"

        "4. INFORMATION / DIAGRAM (10-15%) — A pure information beat\n"
        "Write: A clear [CHART / DIAGRAM / LABELED MAP] showing [WHAT]. "
        "[ONE KEY NUMBER OR LABEL].\n"
        "Ex: A clean line chart showing global coffee consumption rising over a "
        "decade, the figure 2.3 billion cups a day highlighted.\n\n"

        "5. OBJECT CLOSE-UP (10-15%) — A physical object with weight\n"
        "Write: [OBJECT] on [SURFACE]. [CONTEXTUAL DETAILS]. [LIGHTING].\n"
        "Ex: A worn leather-bound notebook open on a wooden desk, a fountain pen "
        "resting in the gutter, handwritten margins, warm desk-lamp light casting "
        "a soft shadow.\n\n"

        "RULES:\n"
        "1. ALWAYS describe character FACES with expressions — 'face showing "
        "concern', 'expression of delight'\n"
        "2. ONE action per character. No multi-action choreography.\n"
        "3. Name environments SPECIFICALLY — 'a sunlit ceramics studio with "
        "shelves of drying pots', not 'a room'\n"
        "4. Include one storytelling detail the narration doesn't state (a half-"
        "finished cup, a second empty chair, a clock showing an early hour)\n"
        "5. Describe lighting conditions — warm for interiors/intimacy, cool for "
        "exteriors/distance, golden hour for transitions\n"
        "6. Text in scene: 2-4 words max (dates, labels, signs)\n\n"

        "NEVER visualize metaphors literally. 'The market was bleeding' = a "
        "trader at a terminal of red screens (face showing alarm), NOT literal "
        "blood.\n\n"

        "ROTATION: Never more than 3 consecutive same scene type. Every act "
        "needs at least one Environment shot."
    ),
    metaphor_translation_table={},   # no hardcoded geopolitics metaphors
    quantitative_requirement=False,
    text_in_image_rules=(
        "text in scene limited to 2-4 words max — dates, labels, sign text only. "
        "AI models handle short text. No sentences."
    ),
)


# =============================================================================
# Section 7: Animation — neutral, look-agnostic motion craft
# =============================================================================

_LOW_MOTION = {
    "power_move": "Characters hold position. One character's expression subtly shifts. Light moves gently across the scene.",
    "lone_figure": "The character's eyes move slightly. Ambient light shifts gradually; shadows lengthen.",
    "environment": "Static shot. Atmospheric haze drifts slowly. A small element (fabric, water, leaves) shifts gently.",
    "data_hud": "Static shot. One element animates in slowly — a line draws, a number settles.",
    "object_closeup": "Static shot. Dust drifts through the light. One small detail moves (a page edge, a wisp of steam).",
}

_MEDIUM_MOTION = {
    "power_move": "One character makes a single deliberate gesture. The other character's expression changes in response.",
    "lone_figure": "The character turns slightly toward a light or window. Expression shifts from neutral to feeling.",
    "environment": "Distant motion animates — vehicles, water, weather. Lights come up in windows.",
    "data_hud": "The chart builds — a line draws or bars rise. One value lands and holds.",
    "object_closeup": "The camera drifts closer. A second detail becomes visible.",
}

_HIGH_MOTION = {
    "power_move": "One character moves decisively — stands, steps in, reaches. The other reacts with a clear change of expression.",
    "lone_figure": "The character turns sharply, expression shifting to resolve. The setting reacts around them.",
    "environment": "The scene comes alive — weather breaks, motion sweeps through, light changes dramatically.",
    "data_hud": "All elements resolve at once — values land, an indicator highlights the key figure.",
    "object_closeup": "The object is acted on — picked up, opened, set down. A clear, single beat of change.",
}

_ANIMATION = AnimationConfig(
    animation_model=Models.ANIMATION_GROK,
    animation_cost_per_clip=0.10,
    motion_templates={
        **{f"low_{k}": v for k, v in _LOW_MOTION.items()},
        **{f"medium_{k}": v for k, v in _MEDIUM_MOTION.items()},
        **{f"high_{k}": v for k, v in _HIGH_MOTION.items()},
    },
    motion_base_rule=(
        "Preserve the established art style and palette throughout. Characters "
        "move naturally while keeping their look consistent. Facial expressions "
        "may shift to show emotion. Do not drift to a different medium."
    ),
    intensity_levels={
        "low": "Subtle ambient changes. Light shifts, expressions hold, one small element moves.",
        "medium": "Active reveal. Up to two elements animate, expressions shift.",
        "high": "Dramatic action. The environment reacts, multiple elements move, expressions change significantly.",
    },
    universal_rules=[
        "Preserve the established art style and palette throughout.",
        "Facial expressions may shift but must stay consistent with the look.",
        "Clothing and costume details must stay consistent throughout.",
        "Do not switch medium mid-clip (no sudden photoreal or 3D drift).",
    ],
    banned_motion_words=[
        "mannequin", "faceless", "smooth oval head",
    ],
    emotional_motion_dict={
        "resolve_focus": [
            "figure stands taller", "expression sharpens", "leans into the work",
            "turns to face camera",
        ],
        "tension_unease": [
            "figures lean toward each other", "expression tightens",
            "light flickers", "a shadow sweeps the room",
        ],
        "revelation_discovery": [
            "expression shifts to surprise", "figure turns sharply",
            "an object is revealed", "light brightens", "camera pushes in",
        ],
        "loss_setback": [
            "expression falls", "figure slumps", "light fades",
            "an empty seat becomes visible",
        ],
    },
)


# =============================================================================
# Section 8: Thumbnail Identity (neutral)
# =============================================================================

_THUMBNAIL = ThumbnailConfig(
    thumbnail_style="bright_editorial_illustration",
    thumbnail_text_color="#FFD700",
    thumbnail_text_style="bold block capitals, thick outline",
    thumbnail_max_words_per_line=4,
    thumbnail_max_lines=2,
    thumbnail_background="simple, recognizable, reads at 160x90px",
    thumbnail_palette_max_colors=4,
    thumbnail_prompt_templates={},
    thumbnail_color_presets={},
    thumbnail_system_prompt="",
    thumbnail_figure_rules=(
        "A single clear subject, symbolic object, or simplified character. "
        "Faces can be shown but simplified for thumbnail readability."
    ),
)


# =============================================================================
# Section 9: Ken Burns Config (pure camera math — craft)
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
    display_name="Neutral Documentary (default)",
    category="documentary",
    tags=[
        "neutral", "documentary", "default", "any-niche", "storytelling",
        "characters", "flexible",
    ],
    description=(
        "The style-agnostic default. Keeps the full image craft (scene-type "
        "variety, expressive characters, specific environments, anti-repetition "
        "rotation) but takes its actual look from your channel's visual style — "
        "so prompts come out in YOUR aesthetic, for any niche."
    ),
    preview_prompts=[
        (
            "A baker with flour-dusted forearms and a satisfied smile lifts a "
            "golden sourdough loaf from a stone oven, warm bakery interior with "
            "wooden racks of bread behind, soft morning light through a front "
            "window. Medium shot. Full-bleed 16:9 composition, no black bars."
        ),
        (
            "A coastal lighthouse on a rocky headland at dusk, beam sweeping out "
            "over a calm sea, a single sailboat on the horizon, deep blue sky "
            "fading to amber at the waterline. Wide establishing shot. Full-bleed "
            "16:9 composition, no black bars."
        ),
        (
            "A clean line chart showing global renewable-energy capacity rising "
            "over a decade, the figure 40% highlighted in a contrasting accent. "
            "Medium shot. Full-bleed 16:9 composition, no black bars."
        ),
    ],
    best_for=[
        "any niche", "education", "explainers", "documentary", "how-to",
    ],
    cost_tier="low",
    estimated_cost_per_video={
        "10min_all_zimage": 0.24,
        "10min_mixed_hero": 0.65,
        "10min_all_nanobanana": 2.70,
        "20min_all_zimage": 0.48,
        "20min_mixed_hero": 1.30,
    },
)


# =============================================================================
# Section 11: Raw data (neutral)
# =============================================================================

_RAW = {
    # No baked-in medium — the channel look is injected at build time.
    "style_engine_prefix": "",
    "style_engine_suffix": "Full-bleed 16:9 cinematic composition.",
    # Equipment-integrity enforcement is a Power-Doctrine (military) behavior;
    # the neutral default leaves it OFF. (Absent / falsey == off.)
    "enforce_equipment_integrity": False,
    "valid_scene_models": {
        "nano-banana-2": "Nano Banana 2 ($0.025/img)",
        "z-image": "Z Image ($0.004/img)",
    },
    # Generic, niche-agnostic material vocabulary (no weapons / naval / military).
    "material_vocabulary": {
        "everyday": [
            "wooden table", "ceramic mug", "notebook", "houseplant",
            "cardboard box", "canvas tote",
        ],
        "workplace": [
            "office desk", "laptop", "whiteboard", "coffee cup",
            "filing shelves", "potted plant",
        ],
        "outdoor": [
            "park bench", "bicycle", "footpath", "wooden fence",
            "street lamp", "market stall",
        ],
        "craft": [
            "workbench", "hand tools", "sketchbook", "fabric bolt",
            "paint jars", "clay on a wheel",
        ],
    },
    "prompt_min_words": 62,
    "prompt_max_words": 120,
    "character_archetypes": {},   # no national-leader / geopolitics archetypes
    "lighting_vocabulary": {
        "warm_interior": "intimacy, comfort, focus",
        "cool_exterior": "distance, calm, scale",
        "golden_hour": "transition, hope, nostalgia",
        "overcast_soft": "neutrality, everyday realism",
        "single_source": "intimacy, a private moment",
    },
    "color_palette": {
        # No palette lock — driven by the channel look.
        "primary": [],
        "accent": [],
        "avoid": [],
    },
    "scene_type_targets": {
        "power_move": {"min_pct": 25, "max_pct": 30},
        "lone_figure": {"min_pct": 20, "max_pct": 25},
        "environment": {"min_pct": 15, "max_pct": 20},
        "data_hud": {"min_pct": 10, "max_pct": 15},
        "object_closeup": {"min_pct": 10, "max_pct": 15},
    },
    "composition_affinity": {
        "power_move": ["low_angle", "medium", "wide"],
        "lone_figure": ["portrait", "medium", "closeup"],
        "environment": ["wide", "environmental", "overhead"],
        "data_hud": ["medium", "closeup"],
        "object_closeup": ["closeup", "overhead"],
    },
    "default_config": {
        "image_duration_seconds": 11,
        "video_duration_seconds": 750,
        "total_images": 60,
        "images_per_scene": 6,
        "scenes_per_video": 10,
    },
    "camera_angle_meanings": {
        "low_angle": "power, confidence",
        "high_angle": "vulnerability, smallness",
        "side_profile": "contemplation, reflection",
        "straight_on": "directness, address",
        "over_shoulder": "revelation, shared perspective",
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
