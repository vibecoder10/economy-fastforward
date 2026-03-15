"""Cinematic Animated Illustration — War Archive style documentary visuals.

The default visual profile for Economy FastForward / Power Doctrine.
Stylized illustrated characters with expressive angular faces in muted
earthy color palettes with ink outlines and dramatic directional lighting.

Aesthetic: Cinematic animated illustration with visible ink outlines,
muted earthy tones (olive, amber, slate, burgundy, worn gold, steel blue),
characters with expressive illustrated faces showing emotion. Dramatic
directional lighting with warm tungsten for interiors, cold steel blue
for exteriors. Period-appropriate clothing with visible wear and detail.

5 scene types: Power Move, Lone Figure, Environment, Data/HUD, Object
Close-up. Characters have faces and expressions, unlike the deprecated
mannequin style.

This is a COMPLETE, STANDALONE profile. Loading it produces stylized
animated illustration output.
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
    TemplateMetadata,
    ThumbnailConfig,
    VisualProfile,
)


# =============================================================================
# Section 1: Identity
# =============================================================================

_IDENTITY = dict(
    profile_id="cinematic_illustration",
    profile_name="Cinematic Animated Illustration",
    description=(
        "Cinematic animated illustration in muted earthy color palette "
        "with ink outlines and dramatic lighting. Characters have expressive "
        "illustrated faces with strong jawlines and angular features. "
        "Period-appropriate clothing with visible wear. Dramatic directional "
        "lighting with warm tungsten for interiors, cold steel blue for exteriors. "
        "5 scene types: Power Move, Lone Figure, Environment, Data/HUD, "
        "Object Close-up. Animation-ready compositions with visual storytelling."
    ),
    version="2.0",
    channel="economy_fastforward",
)


# =============================================================================
# Section 2: Image Generation Config
# =============================================================================

_IMAGE_GEN = ImageGenConfig(
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
    thumbnail_cost_per_image=0.075,
)


# =============================================================================
# Section 3: Style System — 5 scene types
# =============================================================================

# Style prefix for character scenes
# Short medium declaration — front-loaded so the model knows WHAT first.
# Claude's visual description follows immediately (subject + action).
_CHARACTER_PREFIX = (
    "Cinematic 2D animated illustration of"
)

_ENVIRONMENT_PREFIX = (
    "Cinematic 2D animated illustration of"
)

# Technical tail — aspect ratio, texture, palette. No style words that
# duplicate the prefix or substyle suffixes.
_SUFFIX = (
    " Stylized ink outlines, muted earthy palette, film grain texture, "
    "16:9 composition"
)

_STYLE_SYSTEM = StyleSystemConfig(
    style_prefix=_ENVIRONMENT_PREFIX,
    character_prefix=_CHARACTER_PREFIX,
    style_suffix=_SUFFIX,
    substyles={
        "power_move": SubstyleConfig(
            name="Power Move",
            weight=0.275,
            suffix=(
                "Two or more characters in confrontation, one dominant one subordinate, "
                "dramatic directional lighting, expressive faces showing determination"
            ),
            description=(
                "Confrontation / Decision. Two or more characters in tension. "
                "Leaders signing pacts, generals slamming fists, diplomats "
                "turning away from offers. Characters show emotion through "
                "facial expressions and body language."
            ),
        ),
        "lone_figure": SubstyleConfig(
            name="Lone Figure",
            weight=0.225,
            suffix=(
                "Single character in solitary moment of weight, single-source lighting, "
                "expressive face showing internal conflict or resolve"
            ),
            description=(
                "Decision / Reflection / Revelation. Single character in a "
                "moment of weight. Used for turning points in the narrative. "
                "Character's face shows the emotional stakes."
            ),
        ),
        "environment": SubstyleConfig(
            name="Environment / Establishing",
            weight=0.175,
            suffix=(
                "No characters or tiny distant figures only, dramatic natural lighting, "
                "geography and atmosphere establish context"
            ),
            description=(
                "Illustrated location grounding the narrative in geography. "
                "Used for transitions, act breaks, setting context. No characters "
                "or tiny/distant characters."
            ),
        ),
        "data_hud": SubstyleConfig(
            name="Data / HUD Analysis",
            weight=0.125,
            suffix=(
                "Dark operations room with projected data visualization, "
                "teal glow against amber interior, one key number highlighted, "
                "no human figures"
            ),
            description=(
                "Data display style retained for pure data reveals — "
                "statistics, maps with data overlays, economic charts. "
                "NOT the default, 10-15% of scenes max."
            ),
        ),
        "object_closeup": SubstyleConfig(
            name="Object Close-up",
            weight=0.125,
            suffix=(
                "Tight close-up of physical object, shallow depth of field, "
                "warm amber lighting, contextual details nearby"
            ),
            description=(
                "Tight shot on a physical object carrying narrative weight. "
                "Treaty documents, weapons, currency, satellite phones on maps."
            ),
        ),
    },
    accent_colors={
        "geopolitical": "cold teal",
        "ai_tech": "cold teal",
        "corporate_power": "warm amber",
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
    max_consecutive_same_content_type=3,
    max_consecutive_same_format=2,
    max_consecutive_same_palette=3,
    max_consecutive_close_up=1,
    act_weights={
        "act1": {"strategic": 0.30, "alert": 0.20, "power": 0.20, "archive": 0.10, "personal": 0.10, "contagion": 0.10},
        "act2": {"strategic": 0.25, "power": 0.25, "alert": 0.20, "personal": 0.15, "archive": 0.10, "contagion": 0.05},
        "act3": {"alert": 0.30, "power": 0.20, "strategic": 0.15, "contagion": 0.15, "archive": 0.15, "personal": 0.05},
        "act4": {"power": 0.30, "alert": 0.25, "contagion": 0.20, "strategic": 0.10, "archive": 0.10, "personal": 0.05},
        "act5": {"alert": 0.30, "contagion": 0.25, "power": 0.20, "strategic": 0.15, "personal": 0.05, "archive": 0.05},
        "act6": {"strategic": 0.30, "power": 0.25, "personal": 0.20, "archive": 0.15, "alert": 0.05, "contagion": 0.05},
    },
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
# Section 5: Figure Rules — illustrated characters with faces
# =============================================================================

_CHARACTER_ARCHETYPES = {
    "russian_leader": {
        "costume": "dark charcoal suit OR military uniform with gold epaulettes",
        "appearance": "stern angular face, short hair, calculating expression",
        "props_setting": "Russian tricolor flag, Kremlin-style office, heavy desk",
    },
    "chinese_official": {
        "costume": "dark Mao-collar suit",
        "appearance": "composed expression, neat hair, watchful eyes",
        "props_setting": "Chinese flag (red with gold stars), red-draped hall, calligraphy",
    },
    "american_president": {
        "costume": "navy suit, red tie",
        "appearance": "determined expression, presidential bearing",
        "props_setting": "American flag, Oval Office-style desk, eagle seal",
    },
    "iranian_leader": {
        "costume": "black turban, dark clerical robes",
        "appearance": "bearded face, intense gaze, religious authority",
        "props_setting": "Iranian flag, ornate Persian carpet, mosque architecture",
    },
    "saudi_royal": {
        "costume": "white thobe, red-checkered keffiyeh",
        "appearance": "regal bearing, trimmed beard, confident expression",
        "props_setting": "gold-trimmed chair, desert palace, oil derricks in distance",
    },
    "military_general": {
        "costume": "olive uniform with medals, peaked cap",
        "appearance": "weathered face, strong jaw, commanding presence",
        "props_setting": "map table, radio equipment, sandbags",
    },
    "diplomat": {
        "costume": "dark suit, pocket square",
        "appearance": "diplomatic composure, attentive expression",
        "props_setting": "conference table, translator headsets, UN-style setting",
    },
    "insurgent_militia": {
        "costume": "dark tactical vest, keffiyeh/balaclava draped",
        "appearance": "hardened expression, determined eyes",
        "props_setting": "concrete room, weapon rack on wall, radio",
    },
    "wall_street_banker": {
        "costume": "pinstripe suit, loosened tie",
        "appearance": "stressed expression, exhausted features",
        "props_setting": "trading screens, falling charts, marble lobby",
    },
    "intelligence_officer": {
        "costume": "dark suit, earpiece visible",
        "appearance": "alert expression, scanning eyes, professional demeanor",
        "props_setting": "surveillance monitors, manila folders, dim office",
    },
    "citizen_everyman": {
        "costume": "casual clothes (jacket, jeans)",
        "appearance": "relatable expression, everyday features, concerned face",
        "props_setting": "kitchen table, gas station, grocery store, living room",
    },
}

_FIGURE_RULES = FigureRulesConfig(
    allow_human_figures=True,  # Characters have illustrated faces
    allow_silhouettes=True,
    allow_mannequins=False,    # Mannequin style deprecated
    protagonist_config={
        "body": "stylized illustrated character with expressive angular face",
        "identity_method": "illustrated facial features, clothing, and context",
        "archetypes": _CHARACTER_ARCHETYPES,
    },
    negative_prompt_suffix="",
    people_words=[],  # No word replacement needed - characters have faces
    people_replacements=[],  # No replacement needed
)


# =============================================================================
# Section 6: Scene Description Rules — comprehensive system prompt
# =============================================================================

_SCENE_DESCRIPTION = SceneDescriptionConfig(
    system_prompt=(
        "You are a visual director creating CINEMATIC ANIMATED ILLUSTRATION image "
        "prompts for a YouTube documentary channel.\n\n"

        "CORE STYLE: Cinematic animated illustration in muted earthy color palette "
        "(olive, amber, slate, burgundy, worn gold, steel blue) with visible ink "
        "outlines and dramatic directional lighting. Characters have EXPRESSIVE "
        "ILLUSTRATED FACES with strong jawlines, angular features, and visible "
        "emotions. This is NOT faceless — characters show determination, concern, "
        "anger, contemplation through their expressions.\n\n"

        "COLOR PALETTE:\n"
        "- Muted earthy tones: olive, amber, slate, burgundy, worn gold, steel blue\n"
        "- Warm tungsten for interiors (offices, war rooms, signing ceremonies)\n"
        "- Cold steel blue for exteriors and night scenes\n"
        "- Accent colors for emphasis: crimson for conflict, gold for power\n\n"

        "FIVE SCENE TYPES — classify each image as one of these:\n\n"

        "1. POWER MOVE (Confrontation / Decision) — 25-30% of images\n"
        "Two or more illustrated characters in tension. One dominant, one subordinate.\n"
        "Pattern: Cinematic animated illustration, [CHARACTER A with EXPRESSION] in "
        "[COSTUME] [ACTION] while [CHARACTER B with EXPRESSION] in [COSTUME] "
        "[REACTION]. [ENVIRONMENT with details]. [LIGHTING]. Shallow depth of field.\n"
        "Examples: Two leaders signing a pact (one satisfied, one reluctant), "
        "general slamming fist (face showing anger), diplomat turning away (disgust visible).\n\n"

        "2. LONE FIGURE (Decision / Reflection / Revelation) — 20-25%\n"
        "Single character in a moment of weight. Used for turning points.\n"
        "Pattern: Cinematic animated illustration, [CHARACTER with EXPRESSION] in "
        "[COSTUME] [SOLITARY ACTION] in [ENVIRONMENT]. [KEY OBJECT]. [DRAMATIC LIGHTING]. "
        "[CAMERA ANGLE — side profile or over-shoulder].\n"
        "Examples: Leader staring out window (face showing worry), officer reading "
        "classified document alone (expression of disbelief), trader watching screens "
        "crash (face showing despair).\n\n"

        "3. ENVIRONMENT / ESTABLISHING (No or distant characters) — 15-20%\n"
        "Illustrated location grounding the narrative in geography.\n"
        "Pattern: Cinematic animated illustration, wide shot of [SPECIFIC LOCATION]. "
        "[TIME/WEATHER]. [KEY VISUAL DETAIL — smoke, vehicles, empty streets]. "
        "Muted earthy palette, visible ink outlines, 16:9. No text, no UI.\n"
        "Examples: Strait of Hormuz at dawn with tankers, burning city with smoke "
        "columns, empty trading floor after hours.\n\n"

        "4. DATA / HUD ANALYSIS — 10-15%\n"
        "Data display style for pure data reveals only.\n"
        "Pattern: Dark operations room with projected display showing [DATA VIZ]. "
        "Teal holographic glow against warm amber room. [ONE KEY NUMBER]. Minimal "
        "room visible. No human figures. Cinematic front-on composition.\n"
        "Examples: Map with network connections, chart showing price spike.\n\n"

        "5. OBJECT CLOSE-UP (Document / Weapon / Symbol) — 10-15%\n"
        "Tight shot on a physical object carrying narrative weight.\n"
        "Pattern: Cinematic animated illustration, close-up of [OBJECT] on [SURFACE]. "
        "[CONTEXTUAL DETAILS]. Shallow depth of field, warm amber lighting. "
        "Visible ink outlines on textures.\n"
        "Examples: Treaty with red seal, missile on rail, stack of currency.\n\n"

        "CHARACTER APPEARANCE (describe faces AND expressions):\n"
        "- Russian Leader: stern angular face, short hair, calculating expression\n"
        "- Chinese Official: composed expression, neat hair, watchful eyes\n"
        "- American President: determined expression, presidential bearing\n"
        "- Iranian Leader: bearded face, intense gaze, religious authority\n"
        "- Saudi Royal: regal bearing, trimmed beard, confident expression\n"
        "- Military General: weathered face, strong jaw, commanding presence\n"
        "- Diplomat: diplomatic composure, attentive expression\n"
        "- Insurgent: hardened expression, determined eyes\n"
        "- Wall Street Banker: stressed expression, exhausted features\n"
        "- Intelligence Officer: alert expression, scanning eyes\n"
        "- Citizen: relatable expression, everyday features, concerned face\n\n"

        "PROMPT RULES:\n"
        "1. ALWAYS describe character FACES with expressions — this is key to "
        "the style. 'Face showing concern', 'expression of triumph', etc.\n"
        "2. ONE action per character. Never multi-action choreography.\n"
        "3. Name the environment SPECIFICALLY. Not 'an office' — 'a dark "
        "wood-paneled office with tall bookshelves and brass desk lamps'\n"
        "4. Include one storytelling detail the narration doesn't state "
        "explicitly (circled Ukraine on map, second empty chair, clock "
        "showing 3 AM)\n"
        "5. Specify camera angle: low angle = power, high = vulnerability, "
        "side profile = contemplation, straight on = confrontation\n"
        "6. Use muted earthy color palette — no bright neon or saturated colors\n"
        "7. Include 'ink outlines' or 'visible outlines' in the description\n"
        "8. Text in scene (dates, labels) — 2-4 words max\n\n"

        "LIGHTING VOCABULARY:\n"
        "- warm amber/tungsten = power, formality, interiors\n"
        "- cold steel blue = threat, surveillance, exteriors\n"
        "- golden hour = transition, hope\n"
        "- harsh overhead = interrogation, exposure\n"
        "- dim single-source = secrecy, conspiracy\n\n"

        "NEVER visualize metaphors literally. 'Markets bleeding' = trader "
        "at terminal with red screens (face showing panic), NOT literal blood. "
        "'Empire crumbling' = institution under pressure, NOT rubble.\n\n"

        "ROTATION: Never more than 3 consecutive same scene type. Every act "
        "must contain at least one Environment shot. Data/HUD scenes follow "
        "or precede a character scene (contrast rhythm). Object close-ups "
        "work best before or after a revelation."
    ),
    metaphor_translation_table={
        "money_flow": "Show character at central bank or treasury (expression: calculating), stacks of currency, wire transfer screens",
        "power_consolidation": "Show character in executive chair at heavy desk (expression: triumphant), others standing subordinate (expressions: deferential)",
        "economic_pressure": "Show character surrounded by empty shelves (expression: worried), price tags, long queues",
        "military_force": "Show general at map table with fleet models (expression: strategic), or naval port with warships",
        "political_tension": "Show characters seated opposite at diplomatic table (expressions: hostile), flags behind each",
        "surveillance_state": "Show intelligence officer at surveillance monitor wall (expression: alert), manila folders",
        "market_crash": "Show banker at trading terminal with red screens crashing (expression: panic)",
        "historical_parallel": "Show environment shot of period architecture, or close-up of historical document",
        "corruption": "Show character in luxury office with hidden compartment (expression: guilty), offshore bank documents",
        "inequality": "Show split composition: character in penthouse (expression: satisfied) vs character at bus stop (expression: weary)",
        "proxy_war": "Show leader at table with smaller figures in tactical vests (expression: commanding), map with arrows",
        "sanctions": "Show data/HUD with blocked trade routes, or document close-up with RESTRICTED stamps",
    },
    quantitative_requirement=False,
    text_in_image_rules=(
        "text in scene limited to 2-4 words max — dates, document labels, "
        "sign text only. AI models handle short text. No sentences."
    ),
)


# =============================================================================
# Section 7: Animation — illustrated character motion
# =============================================================================

_ILLUSTRATED_LOW_MOTION = {
    "power_move": "Characters hold position. One character's expression subtly shifts. Light moves across faces.",
    "lone_figure": "Character's eyes move slightly. Ambient light shifts gradually across the room, shadows lengthen.",
    "environment": "Static shot. Smoke or atmospheric haze drifts slowly. Flag fabric shifts gently.",
    "data_hud": "Static shot. Data elements pulse slowly. One number ticks upward.",
    "object_closeup": "Static shot. Dust particles drift through the light beam. One paper edge curls.",
}

_ILLUSTRATED_MEDIUM_MOTION = {
    "power_move": "One character slides a document across the table. The other character's expression changes.",
    "lone_figure": "Character turns head slightly toward window. Expression shifts from neutral to concern.",
    "environment": "Vehicles move slowly in distance. Lights flicker on in buildings. Weather shifts.",
    "data_hud": "Chart data animates — bars rise, lines draw. Warning indicator starts pulsing.",
    "object_closeup": "Camera drifts closer to the object. A second detail becomes visible.",
}

_ILLUSTRATED_HIGH_MOTION = {
    "power_move": "One character stands abruptly, expression showing anger. Papers scatter. Other character recoils in surprise.",
    "lone_figure": "Character turns sharply, expression shifting to determination. Documents fan out across desk.",
    "environment": "Explosions flash in distance. Vehicles race. Dramatic weather change. Smoke billows.",
    "data_hud": "All data elements flash red. Numbers spike. Warning indicators cascade across display.",
    "object_closeup": "Object slides off surface. Impact. Pieces scatter. Dramatic light shift.",
}

_ANIMATION = AnimationConfig(
    animation_model="grok-imagine/image-to-video",
    animation_cost_per_clip=0.10,
    motion_templates={
        **{f"low_{k}": v for k, v in _ILLUSTRATED_LOW_MOTION.items()},
        **{f"medium_{k}": v for k, v in _ILLUSTRATED_MEDIUM_MOTION.items()},
        **{f"high_{k}": v for k, v in _ILLUSTRATED_HIGH_MOTION.items()},
    },
    motion_base_rule=(
        "Maintain the illustrated animation aesthetic throughout. "
        "Characters should move naturally but retain the stylized look. "
        "Facial expressions can shift subtly to show emotion changes. "
        "Ink outlines and muted color palette must be preserved."
    ),
    intensity_levels={
        "low": "Subtle ambient changes. Light shifts, expressions hold, one small element moves.",
        "medium": "Active reveal. Up to two elements animate, expressions shift.",
        "high": "Dramatic action. Environment reacts, multiple elements move, expressions change significantly.",
    },
    universal_rules=[
        "Maintain the illustrated animation aesthetic — visible ink outlines.",
        "Muted earthy color palette must be preserved throughout.",
        "Facial expressions can shift but must remain stylized, not photorealistic.",
        "Clothing and costume details must stay consistent throughout.",
        "Environment textures (wood, stone, metal) must stay illustrated style.",
        "No transition to photorealistic or 3D render look.",
    ],
    banned_motion_words=[
        "photorealistic skin", "3D render", "mannequin", "faceless",
        "smooth oval head", "photorealistic", "hyperrealistic",
    ],
    emotional_motion_dict={
        "power_authority": [
            "figure stands taller", "expression hardens", "hand slams table",
            "document pushed forward", "figure turns to face camera",
        ],
        "tension_threat": [
            "figures lean in toward each other", "expressions grow hostile",
            "papers slide off desk", "light flickers", "shadow sweeps room",
        ],
        "secrecy_conspiracy": [
            "figure leans in close", "expression becomes guarded",
            "folder slides across table", "light dims", "door closes slowly",
        ],
        "revelation_discovery": [
            "expression shifts to surprise", "figure turns sharply",
            "document unfolds", "light brightens", "camera pushes in",
        ],
        "loss_defeat": [
            "expression falls", "figure slumps", "papers scatter to floor",
            "light fades", "empty chair visible",
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
    thumbnail_prompt_templates={},
    thumbnail_color_presets={
        "geopolitics": ["#1a5c6b", "#FFD700", "#333", "#fff"],
        "finance": ["#b8860b", "#FFD700", "#333", "#fff"],
        "conflict": ["#8b1a1a", "#FFD700", "#333", "#fff"],
    },
    thumbnail_system_prompt="",
    thumbnail_figure_rules=(
        "Map silhouette, symbolic object, or illustrated character silhouette. "
        "Character faces can be shown but simplified for thumbnail readability."
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
    display_name="Cinematic Animated Illustration",
    category="documentary",
    tags=[
        "illustration", "animated", "documentary", "geopolitics", "storytelling",
        "cinematic", "narrative", "war", "finance", "expressive",
    ],
    description=(
        "Cinematic animated illustration in muted earthy color palette with "
        "ink outlines and dramatic lighting. Characters have expressive illustrated "
        "faces with angular features showing emotion. Period-appropriate clothing "
        "with visible wear. 5 scene types create visual rhythm. Best for: "
        "geopolitics, military analysis, proxy wars, economic power, intelligence "
        "operations."
    ),
    preview_prompts=[
        (
            "Cinematic animated illustration in muted earthy color palette with "
            "ink outlines. Iranian news anchor with stern bearded face in dark wool "
            "suit sits behind polished wooden desk reading official document into "
            "vintage chrome microphone, expression grave with furrowed brow and "
            "tight jaw, framed portrait of supreme leader on wooden easel behind "
            "right shoulder, world map pinned to wall in background, warm tungsten "
            "desk lamp casting sharp shadow across papers, medium shot straight-on "
            "angle, stylized 2D animation aesthetic with visible ink outlines, "
            "muted film grain texture, 16:9 cinematic composition"
        ),
        (
            "Cinematic animated illustration in muted earthy color palette with "
            "ink outlines. Desert military airfield at dawn, row of white interceptor "
            "drones lined up on camouflage netting beside concrete hangar, olive drab "
            "duffel bags open on ground showing drone components, Ukrainian flag patch "
            "sewn on nearest bag, distant mountains under pink-orange sunrise sky, "
            "heat shimmer rising from tarmac, two soldiers in background walking toward "
            "hangar carrying equipment cases, wide establishing shot low angle, stylized "
            "2D animation aesthetic with visible ink outlines, muted film grain texture, "
            "16:9 cinematic composition"
        ),
        (
            "Cinematic animated illustration in muted earthy color palette with "
            "ink outlines. Close-up of compact white 3D-printed interceptor drone "
            "resting on metal workbench, modular wing sections attached, fiber-optic "
            "guidance cable coiled beside it, small handwritten price tag reading "
            "$1,000 tied to landing strut with twine, Ukrainian flag sticker on "
            "fuselage, scattered tools and soldering iron in soft focus background, "
            "warm overhead workshop lighting with sharp shadows on textured plastic "
            "surface, macro detail shot, stylized 2D animation aesthetic with visible "
            "ink outlines, muted film grain texture, 16:9 cinematic composition"
        ),
        (
            "Cinematic animated illustration in muted earthy color palette with "
            "ink outlines. Night sky over Kyiv filled with dozens of delta-wing "
            "Shahed drones approaching as dark silhouettes against amber city glow, "
            "three interceptor drones streaking upward trailing white exhaust, distant "
            "explosion flash illuminating clouds where interceptor meets Shahed, "
            "apartment buildings below with lit windows, cold steel blue atmosphere "
            "with orange explosion highlights, wide angle deep depth of field capturing "
            "scale of aerial battle, stylized 2D animation aesthetic with visible ink "
            "outlines, muted film grain texture, 16:9 cinematic composition"
        ),
    ],
    best_for=[
        "geopolitics", "military analysis", "proxy wars",
        "economic power", "intelligence operations",
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
# Section 11: Raw data
# =============================================================================

_RAW = {
    # Style engine compatibility
    "style_engine_prefix": (
        "Cinematic animated illustration in muted earthy color palette "
        "with ink outlines and dramatic lighting, stylized characters "
        "with expressive faces."
    ),
    "style_engine_suffix": (
        "Stylized 2D animation aesthetic with visible ink outlines, "
        "muted film grain texture, 16:9 cinematic composition."
    ),
    # Valid scene models
    "valid_scene_models": {
        "nano-banana-2": "Nano Banana 2 (default — cinematic illustration, $0.025/img)",
        "z-image": "Z Image ($0.004/img)",
    },
    # Material vocabulary
    "material_vocabulary": {
        "premium": [
            "mahogany desk", "leather briefcase", "brass desk lamp",
            "gold-trimmed chair", "silk flag", "crystal decanter",
        ],
        "institutional": [
            "concrete government building", "wood-paneled office",
            "marble lobby", "security checkpoint", "diplomatic conference table",
            "reinforced bunker walls",
        ],
        "military": [
            "map table", "radio equipment", "sandbags", "weapon rack",
            "military pickup trucks", "naval vessels",
        ],
        "diplomatic": [
            "conference table", "translator headsets", "national flags",
            "document folders", "wax seals", "ornate carpet",
        ],
        "data": [
            "trading screens", "surveillance monitors", "holographic projections",
            "manila folders", "satellite photographs", "corkboard with string",
        ],
    },
    # Prompt word budget
    "prompt_min_words": 62,
    "prompt_max_words": 120,
    # Character archetype library
    "character_archetypes": _CHARACTER_ARCHETYPES,
    # Lighting vocabulary
    "lighting_vocabulary": {
        "warm_tungsten": "power, formality, interiors",
        "cold_steel_blue": "threat, surveillance, exteriors",
        "golden_hour": "transition, hope",
        "harsh_overhead": "interrogation, exposure",
        "dim_single_source": "secrecy, conspiracy",
    },
    # Color palette
    "color_palette": {
        "primary": ["olive", "amber", "slate", "burgundy", "worn gold", "steel blue"],
        "accent": ["crimson", "gold"],
        "avoid": ["neon", "bright saturated", "pastel"],
    },
    # Scene type distribution targets
    "scene_type_targets": {
        "power_move": {"min_pct": 25, "max_pct": 30},
        "lone_figure": {"min_pct": 20, "max_pct": 25},
        "environment": {"min_pct": 15, "max_pct": 20},
        "data_hud": {"min_pct": 10, "max_pct": 15},
        "object_closeup": {"min_pct": 10, "max_pct": 15},
    },
    # Composition affinity
    "composition_affinity": {
        "power_move": ["low_angle", "medium", "wide"],
        "lone_figure": ["portrait", "medium", "closeup"],
        "environment": ["wide", "environmental", "overhead"],
        "data_hud": ["medium", "closeup"],
        "object_closeup": ["closeup", "overhead"],
    },
    # Default config values
    "default_config": {
        "image_duration_seconds": 11,
        "video_duration_seconds": 750,
        "total_images": 60,
        "images_per_scene": 6,
        "scenes_per_video": 10,
    },
    # Camera angle vocabulary
    "camera_angle_meanings": {
        "low_angle": "power, authority, intimidation",
        "high_angle": "vulnerability, being watched, small",
        "side_profile": "contemplation, reflection",
        "straight_on": "confrontation, direct address",
        "over_shoulder": "revelation, discovery, shared perspective",
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
