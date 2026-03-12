"""Mannequin Storytelling — 3D documentary mannequins in real environments.

The default visual profile for Economy FastForward / Power Doctrine.
Faceless white mannequin figures in contextual clothing performing single
clear actions within photorealistic environments. Identity communicated
through costume, props, and setting — never facial features.

Aesthetic: 3D rendered faceless mannequins with smooth white oval heads,
contextual clothing (suits, uniforms, robes), photorealistic physical
environments (offices, war rooms, cities, naval ports). Warm lighting,
cinematic composition, one character or small group performing one clear
action per image.

5 scene types: Power Move, Lone Figure, Environment, Data/HUD, Object
Close-up. Character archetypes defined by 11 costume/prop/setting combos.

This is a COMPLETE, STANDALONE profile. Loading it produces fully different
visual output with zero clay-diorama or holographic leakage.
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
    profile_id="mannequin_storytelling",
    profile_name="3D Mannequin Documentary Storytelling",
    description=(
        "3D rendered faceless mannequin figures with smooth white oval heads "
        "in photorealistic environments. Characters wear contextual clothing "
        "(suits, uniforms, robes) — identity through costume, not likeness. "
        "One character or small group performing one clear action per image. "
        "5 scene types: Power Move, Lone Figure, Environment, Data/HUD, "
        "Object Close-up. Animation-ready single-figure compositions."
    ),
    version="1.0",
    channel="economy_fastforward",
)


# =============================================================================
# Section 2: Image Generation Config
# =============================================================================

_IMAGE_GEN = ImageGenConfig(
    scene_model="z-image",
    scene_model_params={
        "aspect_ratio": "16:9",
        "resolution": "1K",
        "output_format": "png",
    },
    scene_cost_per_image=0.004,
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

# The prefix is empty because scene-type-specific openings are controlled
# by the system_prompt. Character scenes open with "3D rendered faceless
# mannequin...", environment scenes open with "Cinematic wide shot...",
# data/HUD scenes open with "Dark operations room...", etc.
_PREFIX = ""

# Universal suffix per prompt construction rule #6:
# "End every prompt with this."
_SUFFIX = (
    ", Cinematic 3D documentary style, smooth matte mannequin surfaces, "
    "no facial features, 16:9"
)

_STYLE_SYSTEM = StyleSystemConfig(
    style_prefix=_PREFIX,
    style_suffix=_SUFFIX,
    substyles={
        "power_move": SubstyleConfig(
            name="Power Move",
            weight=0.275,
            suffix=(
                "two or more mannequin figures in tension, one dominant one "
                "subordinate, confrontation staging, dramatic directional lighting"
            ),
            description=(
                "Confrontation / Decision. Two or more characters in tension. "
                "Leaders signing pacts, generals slamming fists, diplomats "
                "turning away from offers."
            ),
        ),
        "lone_figure": SubstyleConfig(
            name="Lone Figure",
            weight=0.225,
            suffix=(
                "single mannequin figure in a moment of weight, solitary action, "
                "dramatic single-source lighting, contemplative or revelatory mood"
            ),
            description=(
                "Decision / Reflection / Revelation. Single character in a "
                "moment of weight. Used for turning points in the narrative."
            ),
        ),
        "environment": SubstyleConfig(
            name="Environment / Establishing",
            weight=0.175,
            suffix=(
                "cinematic wide shot, photorealistic location, no mannequin "
                "figures or tiny distant figures only, dramatic natural lighting, "
                "geography and atmosphere establish context"
            ),
            description=(
                "Photorealistic location grounding the narrative in geography. "
                "Used for transitions, act breaks, setting context. No characters "
                "or tiny/distant characters."
            ),
        ),
        "data_hud": SubstyleConfig(
            name="Data / HUD Analysis",
            weight=0.125,
            suffix=(
                "dark operations room, projected holographic display, teal/cyan "
                "glow, specific data visualization with one key number, minimal "
                "room visible, no human figures"
            ),
            description=(
                "Holographic HUD style retained for pure data reveals — "
                "statistics, maps with data overlays, economic charts. "
                "NOT the default, 10-15% of scenes max."
            ),
        ),
        "object_closeup": SubstyleConfig(
            name="Object Close-up",
            weight=0.125,
            suffix=(
                "cinematic close-up of physical object, shallow depth of field, "
                "warm amber lighting, photorealistic textures, contextual details "
                "nearby that tell the story"
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
    # "Never more than 3 consecutive scenes of the same type"
    max_consecutive_same_content_type=3,
    max_consecutive_same_format=2,
    max_consecutive_same_palette=3,
    max_consecutive_close_up=1,
    # Scene type distribution per act (power_move / lone_figure / environment / data_hud / object_closeup)
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
# Section 5: Figure Rules — white mannequins with contextual clothing
# =============================================================================

_CHARACTER_ARCHETYPES = {
    "russian_leader": {
        "costume": "dark charcoal suit OR military uniform with gold epaulettes",
        "props_setting": "Russian tricolor flag, Kremlin-style office, heavy desk",
    },
    "chinese_official": {
        "costume": "dark Mao-collar suit",
        "props_setting": "Chinese flag (red with gold stars), red-draped hall, calligraphy",
    },
    "american_president": {
        "costume": "navy suit, red tie",
        "props_setting": "American flag, Oval Office-style desk, eagle seal",
    },
    "iranian_leader": {
        "costume": "black turban, dark clerical robes",
        "props_setting": "Iranian flag, ornate Persian carpet, mosque architecture",
    },
    "saudi_royal": {
        "costume": "white thobe, red-checkered keffiyeh",
        "props_setting": "gold-trimmed chair, desert palace, oil derricks in distance",
    },
    "military_general": {
        "costume": "olive uniform with medals, peaked cap",
        "props_setting": "map table, radio equipment, sandbags",
    },
    "diplomat": {
        "costume": "dark suit, pocket square",
        "props_setting": "conference table, translator headsets, UN-style setting",
    },
    "insurgent_militia": {
        "costume": "dark tactical vest, keffiyeh/balaclava draped",
        "props_setting": "concrete room, weapon rack on wall, radio",
    },
    "wall_street_banker": {
        "costume": "pinstripe suit, loosened tie",
        "props_setting": "trading screens, falling charts, marble lobby",
    },
    "intelligence_officer": {
        "costume": "dark suit, earpiece visible",
        "props_setting": "surveillance monitors, manila folders, dim office",
    },
    "citizen_everyman": {
        "costume": "casual clothes (jacket, jeans)",
        "props_setting": "kitchen table, gas station, grocery store, living room",
    },
}

_FIGURE_RULES = FigureRulesConfig(
    allow_human_figures=False,
    allow_silhouettes=False,
    allow_mannequins=True,
    protagonist_config={
        "body": "smooth white oval head, white gloved hands, matte surface",
        "identity_method": "contextual clothing — suits, uniforms, robes communicate role",
        "no_glow": True,
        "archetypes": _CHARACTER_ARCHETYPES,
    },
    negative_prompt_suffix=(
        "no photorealistic skin, no real faces, no facial features, "
        "smooth white oval head, matte mannequin surface, no anime, no cartoon"
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
        (r"\bfaces?\b", "smooth white oval head"),
        (r"\bsmil(?:e|ing)\b", "tilted head posture"),
        (r"\bexpression\b", "body language"),
        (r"\beyes\b", "smooth featureless head"),
        (r"\bmouth\b", "smooth surface"),
        (r"\bhair\b", "smooth white oval head"),
    ],
)


# =============================================================================
# Section 6: Scene Description Rules — comprehensive system prompt
# =============================================================================

_SCENE_DESCRIPTION = SceneDescriptionConfig(
    system_prompt=(
        "You are a visual director creating 3D MANNEQUIN DOCUMENTARY image "
        "prompts for a YouTube documentary channel.\n\n"

        "CORE STYLE: 3D rendered faceless mannequin figures with smooth white "
        "oval heads in photorealistic physical environments. Mannequins wear "
        "contextual clothing (suits, military uniforms, clerical robes, etc.) "
        "that communicates identity through role, not likeness. One character "
        "or small group performing ONE clear action per image.\n\n"

        "FIVE SCENE TYPES — classify each image as one of these:\n\n"

        "1. POWER MOVE (Confrontation / Decision) — 25-30% of images\n"
        "Two or more mannequin figures in tension. One dominant, one subordinate.\n"
        "Pattern: 3D rendered faceless mannequin with smooth white oval head "
        "wearing [COSTUME A] [ACTION] while a second faceless mannequin in "
        "[COSTUME B] [REACTION]. [ENVIRONMENT with details]. [LIGHTING]. "
        "Cinematic [CAMERA ANGLE], shallow depth of field.\n"
        "Examples: Two leaders signing a pact, general slamming fist on table, "
        "diplomat turning away.\n\n"

        "2. LONE FIGURE (Decision / Reflection / Revelation) — 20-25%\n"
        "Single character in a moment of weight. Used for turning points.\n"
        "Pattern: 3D rendered faceless mannequin with smooth white oval head "
        "wearing [COSTUME] [SOLITARY ACTION] in [ENVIRONMENT]. [KEY OBJECT]. "
        "[DRAMATIC LIGHTING]. [CAMERA ANGLE — side profile or over-shoulder].\n"
        "Examples: Leader staring out window, officer reading classified "
        "document alone, trader watching screens crash.\n\n"

        "3. ENVIRONMENT / ESTABLISHING (No or distant characters) — 15-20%\n"
        "Photorealistic location grounding the narrative in geography.\n"
        "Pattern: Cinematic wide shot of [SPECIFIC LOCATION]. [TIME/WEATHER]. "
        "[KEY VISUAL DETAIL — smoke, vehicles, empty streets]. Dramatic "
        "lighting, photorealistic, 16:9. No text, no UI.\n"
        "Examples: Strait of Hormuz at dawn with tankers, burning city, "
        "empty trading floor after hours.\n\n"

        "4. DATA / HUD ANALYSIS — 10-15%\n"
        "Holographic style for pure data reveals only.\n"
        "Pattern: Dark operations room with projected holographic display "
        "showing [DATA VISUALIZATION — map, chart, document]. Teal/cyan "
        "holographic glow. [ONE KEY NUMBER]. Minimal room visible. No "
        "human figures. Cinematic front-on composition.\n"
        "Examples: Map with network connections, chart showing price spike.\n\n"

        "5. OBJECT CLOSE-UP (Document / Weapon / Symbol) — 10-15%\n"
        "Tight shot on a physical object carrying narrative weight.\n"
        "Pattern: Cinematic close-up of [OBJECT] on [SURFACE]. [CONTEXTUAL "
        "DETAILS]. Shallow depth of field, warm amber lighting. "
        "Photorealistic textures.\n"
        "Examples: Treaty with red seal, missile on rail, stack of currency.\n\n"

        "CHARACTER ARCHETYPES (identify by costume, never by face):\n"
        "- Russian Leader: dark charcoal suit OR military uniform with gold "
        "epaulettes, Kremlin office, heavy desk\n"
        "- Chinese Official: dark Mao-collar suit, red-draped hall, "
        "calligraphy\n"
        "- American President: navy suit, red tie, Oval Office desk, eagle "
        "seal\n"
        "- Iranian Leader: black turban, dark clerical robes, Persian carpet\n"
        "- Saudi Royal: white thobe, red-checkered keffiyeh, desert palace\n"
        "- Military General: olive uniform with medals, peaked cap, map "
        "table\n"
        "- Diplomat: dark suit, pocket square, conference table, UN setting\n"
        "- Insurgent: dark tactical vest, keffiyeh, concrete room\n"
        "- Wall Street Banker: pinstripe suit, loosened tie, trading "
        "screens\n"
        "- Intelligence Officer: dark suit, earpiece, surveillance monitors\n"
        "- Citizen: casual clothes, kitchen table, grocery store\n\n"

        "PROMPT RULES:\n"
        "1. ALWAYS open character scenes with '3D rendered faceless mannequin "
        "with smooth white oval head wearing...' — this is the style anchor\n"
        "2. ONE action per character. Never multi-action choreography\n"
        "3. Name the environment SPECIFICALLY. Not 'an office' — 'a dark "
        "wood-paneled office with tall bookshelves and brass desk lamps'\n"
        "4. Include one storytelling detail the narration doesn't state "
        "explicitly (circled Ukraine on map, second empty chair, clock "
        "showing 3 AM)\n"
        "5. Specify camera angle: low angle = power, high = vulnerability, "
        "side profile = contemplation, straight on = confrontation\n"
        "6. No holographic elements in character scenes — holograms and "
        "mannequins don't mix, it breaks physical grounding\n"
        "7. Flags and national symbols render well — use freely for "
        "identity cues\n"
        "8. Text in scene (dates, labels) — 2-4 words max\n\n"

        "LIGHTING VOCABULARY:\n"
        "- amber/warm = power, formality\n"
        "- cold blue = threat, surveillance\n"
        "- golden hour = transition, hope\n"
        "- harsh overhead = interrogation, exposure\n"
        "- dim single-source = secrecy, conspiracy\n\n"

        "NEVER visualize metaphors literally. 'Markets bleeding' = trader "
        "at terminal with red screens, NOT literal blood. 'Empire crumbling' "
        "= institution under pressure, NOT rubble.\n\n"

        "ROTATION: Never more than 3 consecutive same scene type. Every act "
        "must contain at least one Environment shot. Data/HUD scenes follow "
        "or precede a character scene (contrast rhythm). Object close-ups "
        "work best before or after a revelation."
    ),
    metaphor_translation_table={
        "money_flow": "Show mannequin at central bank or treasury, stacks of currency, wire transfer screens",
        "power_consolidation": "Show mannequin in executive chair at heavy desk, others standing subordinate",
        "economic_pressure": "Show mannequin surrounded by empty shelves, price tags, long queues",
        "military_force": "Show mannequin general at map table with fleet models, or naval port with warships",
        "political_tension": "Show mannequins seated opposite at diplomatic table, flags behind each",
        "surveillance_state": "Show mannequin intelligence officer at surveillance monitor wall, manila folders",
        "market_crash": "Show mannequin banker at trading terminal with red screens crashing",
        "historical_parallel": "Show environment shot of period architecture, or close-up of historical document",
        "corruption": "Show mannequin in luxury office with hidden compartment, offshore bank documents",
        "inequality": "Show split composition: mannequin in penthouse vs mannequin at bus stop",
        "proxy_war": "Show mannequin leader at table with smaller figures in tactical vests, map with arrows",
        "sanctions": "Show data/HUD with blocked trade routes, or document close-up with RESTRICTED stamps",
    },
    quantitative_requirement=False,
    text_in_image_rules=(
        "text in scene limited to 2-4 words max — dates, document labels, "
        "sign text only. AI models handle short text. No sentences."
    ),
)


# =============================================================================
# Section 7: Animation — mannequin-appropriate motion
# =============================================================================

_MANNEQUIN_LOW_MOTION = {
    "power_move": "Static mannequin figures. One figure's gloved hand shifts slightly on the table surface.",
    "lone_figure": "Static mannequin. Ambient light shifts gradually across the room, shadows move.",
    "environment": "Static shot. Smoke or atmospheric haze drifts slowly. Flag fabric shifts gently.",
    "data_hud": "Static shot. Holographic data elements pulse slowly. One number ticks upward.",
    "object_closeup": "Static shot. Dust particles drift through the light beam. One paper edge curls.",
}

_MANNEQUIN_MEDIUM_MOTION = {
    "power_move": "One mannequin figure slides a document across the table. The other figure's posture shifts.",
    "lone_figure": "Mannequin turns head slightly toward window. Light source changes temperature.",
    "environment": "Vehicles move slowly in distance. Lights flicker on in buildings. Weather shifts.",
    "data_hud": "Chart data animates — bars rise, lines draw. Warning indicator starts pulsing.",
    "object_closeup": "Camera drifts closer to the object. A second detail becomes visible.",
}

_MANNEQUIN_HIGH_MOTION = {
    "power_move": "One mannequin stands abruptly, chair pushed back. Papers scatter. Other figure recoils.",
    "lone_figure": "Mannequin figure turns sharply. Documents fan out across desk. Dramatic shadow sweep.",
    "environment": "Explosions flash in distance. Vehicles race. Dramatic weather change. Smoke billows.",
    "data_hud": "All data elements flash red. Numbers spike. Warning indicators cascade across display.",
    "object_closeup": "Object slides off surface. Impact. Pieces scatter. Dramatic light shift.",
}

_ANIMATION = AnimationConfig(
    animation_model="grok-imagine/image-to-video",
    animation_cost_per_clip=0.10,
    motion_templates={
        **{f"low_{k}": v for k, v in _MANNEQUIN_LOW_MOTION.items()},
        **{f"medium_{k}": v for k, v in _MANNEQUIN_MEDIUM_MOTION.items()},
        **{f"high_{k}": v for k, v in _MANNEQUIN_HIGH_MOTION.items()},
    },
    motion_base_rule=(
        "Maintain the full original frame composition. Mannequin surfaces "
        "must remain smooth white matte throughout — no skin texture should "
        "appear. Heads remain featureless smooth white ovals."
    ),
    intensity_levels={
        "low": "Subtle ambient changes. Light shifts, one small element moves.",
        "medium": "Active reveal. Up to two elements animate, posture shifts.",
        "high": "Dramatic action. Environment reacts, multiple elements move.",
    },
    universal_rules=[
        "Maintain the full original frame composition.",
        "Mannequin surfaces must remain smooth white matte — no skin texture.",
        "Heads must remain featureless smooth white ovals — no faces should appear.",
        "Clothing and costume details must stay consistent throughout.",
        "No mannequin should change costume or archetype during animation.",
        "Environment textures (wood, stone, metal) must stay photorealistic.",
    ],
    banned_motion_words=[
        "realistic skin", "facial expression", "hair movement", "eye movement",
        "lip movement", "breathing", "muscle flex", "blinking", "smiling",
    ],
    emotional_motion_dict={
        "power_authority": [
            "figure stands taller", "hand slams table", "document pushed forward",
            "chair pushed back", "figure turns to face camera",
        ],
        "tension_threat": [
            "figures lean in toward each other", "hands grip table edge",
            "papers slide off desk", "light flickers", "shadow sweeps room",
        ],
        "secrecy_conspiracy": [
            "figure leans in close", "folder slides across table",
            "light dims", "door closes slowly", "curtain shifts",
        ],
        "revelation_discovery": [
            "figure turns sharply", "document unfolds", "light brightens",
            "screen flickers to life", "camera pushes in",
        ],
        "loss_defeat": [
            "figure slumps", "papers scatter to floor", "light fades",
            "empty chair visible", "flag lowered slowly",
        ],
    },
)


# =============================================================================
# Section 8: Thumbnail Identity — unchanged per spec
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
        "Map silhouette, symbolic object, or mannequin figure silhouette. "
        "No recognizable faces — smooth white oval head shape only."
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
    display_name="Mannequin Documentary Storytelling",
    category="documentary",
    tags=[
        "3D", "mannequin", "documentary", "geopolitics", "storytelling",
        "photorealistic", "cinematic", "narrative", "war", "finance",
    ],
    description=(
        "3D rendered faceless mannequins in contextual clothing within "
        "photorealistic environments. Characters perform single clear actions "
        "— writing, pointing at maps, signing treaties. Identity through "
        "costume and setting, not likeness. 5 scene types create visual "
        "rhythm. Best for: geopolitics, military analysis, proxy wars, "
        "economic power, intelligence operations."
    ),
    preview_prompts=[
        (
            "3D rendered faceless mannequin with smooth white oval head wearing "
            "black turban and dark clerical robes, standing at the head of a "
            "long stone table. Four smaller faceless mannequins in dark tactical "
            "vests and keffiyehs sit along the table, each with a different "
            "colored armband (green, yellow, red, black). The central figure "
            "extends a white-gloved hand over a large map of the Middle East "
            "spread across the table, with red arrows drawn from Tehran outward "
            "to Lebanon, Yemen, Iraq, and Syria. Dim underground bunker with "
            "concrete walls and a single hanging bulb. Low angle looking up at "
            "the standing figure. Cinematic 3D documentary style, smooth matte "
            "mannequin surfaces, no facial features."
        ),
        (
            "3D rendered faceless mannequin with smooth white oval head wearing "
            "dark navy suit with visible earpiece, sitting alone in a dim "
            "office. The figure leans forward over a desk covered in satellite "
            "photographs and manila folders stamped 'CLASSIFIED' in red. A "
            "large corkboard on the wall behind shows pinned photographs "
            "connected by red string, forming a web pattern centered on Iran. "
            "Single desk lamp provides warm amber light from the left. Side "
            "profile composition, shallow depth of field. Cinematic 3D "
            "documentary style, smooth matte mannequin surfaces, no facial "
            "features."
        ),
        (
            "Cinematic wide shot of a dense urban neighborhood in southern "
            "Beirut at dusk. Concrete apartment buildings with laundry lines "
            "and satellite dishes crowd together. A massive portrait banner of "
            "a clenched fist hangs from one building. Military-style pickup "
            "trucks with mounted equipment parked in narrow streets below. "
            "Orange sky fading to deep blue, warm streetlights beginning to "
            "glow. Photorealistic, dramatic golden hour lighting, 16:9 "
            "composition. No people visible, no text."
        ),
        (
            "Dark operations room with projected holographic display showing "
            "a map of the Middle East. Glowing red lines radiate outward from "
            "a pulsing node over Tehran, connecting to labeled nodes: BEIRUT "
            "(Hezbollah), SANAA (Houthis), BAGHDAD (PMF), DAMASCUS (Quds "
            "Force). Each node displays a troop strength number in cyan text. "
            "A cost ticker in the corner reads '$16B ANNUAL' in red. Teal "
            "holographic glow with red accent on the network lines. Minimal "
            "dark room visible. No human figures. Cinematic front-on "
            "composition."
        ),
        (
            "Cinematic close-up of a weathered shipping manifest document on "
            "a scratched metal table. The document shows a list of items with "
            "Farsi script headers and numerical quantities. A rubber stamp "
            "mark in red ink partially covers one corner. Beside the document: "
            "a worn brass key, two spent rifle cartridges, and the edge of a "
            "green military radio. Harsh single overhead light creating sharp "
            "shadows. Shallow depth of field, photorealistic textures. 3D "
            "documentary style."
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
    # Style engine compatibility (for animation prompt pipeline)
    "style_engine_prefix": (
        "3D rendered faceless mannequin with smooth white oval head, "
        "photorealistic environment, cinematic documentary style."
    ),
    "style_engine_suffix": (
        "Cinematic 3D documentary style, smooth matte mannequin surfaces, "
        "no facial features. No anime, no cartoon, no photorealistic skin."
    ),
    # Valid scene models
    "valid_scene_models": {
        "z-image": "zImage (default — mannequin storytelling, $0.004/img)",
        "nano-banana-2": "Nano Banana 2 (hero shots, $0.045/img)",
    },
    # Material vocabulary (photorealistic physical environments)
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
    # Prompt word budget (longer than clay — costume details add words)
    "prompt_min_words": 62,
    "prompt_max_words": 120,
    # Character archetype library for programmatic access
    "character_archetypes": _CHARACTER_ARCHETYPES,
    # Lighting vocabulary
    "lighting_vocabulary": {
        "amber_warm": "power, formality",
        "cold_blue": "threat, surveillance",
        "golden_hour": "transition, hope",
        "harsh_overhead": "interrogation, exposure",
        "dim_single_source": "secrecy, conspiracy",
    },
    # Scene type distribution targets (for reference/validation)
    "scene_type_targets": {
        "power_move": {"min_pct": 25, "max_pct": 30},
        "lone_figure": {"min_pct": 20, "max_pct": 25},
        "environment": {"min_pct": 15, "max_pct": 20},
        "data_hud": {"min_pct": 10, "max_pct": 15},
        "object_closeup": {"min_pct": 10, "max_pct": 15},
    },
    # Default config values
    "default_config": {
        "image_duration_seconds": 11,
        "video_duration_seconds": 750,  # 10-12 min videos
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
