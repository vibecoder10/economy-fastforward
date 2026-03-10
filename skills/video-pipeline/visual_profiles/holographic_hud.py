"""Holographic Intelligence Display — Active production profile.

Extracted from the current codebase (Mar 2026). When loaded, this profile
produces IDENTICAL output to the current hardcoded system.

Aesthetic: Dark high-security intelligence operations center with holographic
projections. War room from Tom Clancy crossed with Bloomberg Terminal crossed
with Minority Report. Zero human figures. Every frame carries actual
analytical information.
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


# =============================================================================
# Section 1: Identity
# =============================================================================

_IDENTITY = dict(
    profile_id="holographic_hud",
    profile_name="Holographic Intelligence Display",
    description=(
        "Dark operations room with projected holographic maps, data terminals, "
        "and analytical visualizations. War room meets Bloomberg Terminal meets "
        "Minority Report. Zero human figures — only data displays."
    ),
    version="4.0",
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
    thumbnail_cost_per_image=0.09,
)


# =============================================================================
# Section 3: Style System
# =============================================================================

_HOLOGRAPHIC_PREFIX = (
    "Holographic intelligence display, dark high-security operations center, "
    "holographic projections floating in dark space, clinical precision, "
    "data-dense analytical visualization, photorealistic rendering, "
    "16:9 cinematic composition."
)

_HOLOGRAPHIC_SUFFIX = (
    ", no people visible no human figures no faces no silhouettes of people, "
    "only data displays and holographic projections and room environment, "
    "dark operations room background with subtle ambient equipment glow, "
    "photorealistic rendering with cinematic depth of field, 16:9 aspect ratio"
)

_STYLE_SYSTEM = StyleSystemConfig(
    style_prefix=_HOLOGRAPHIC_PREFIX,
    style_suffix=_HOLOGRAPHIC_SUFFIX,
    substyles={},  # Holographic uses 3-variable system, not substyles
    accent_colors={
        "geopolitical": "strategic",
        "financial": "personal",
        "conflict": "alert",
        "default": "strategic",
    },
    accent_color_to_mood={
        "cold teal": "strategic",
        "warm amber": "archive",
        "muted crimson": "alert",
        "muted green": "contagion",
        "deep green": "contagion",
    },
    category_to_mood={
        "geopolitical": "strategic",
        "ai_tech": "strategic",
        "corporate_power": "power",
        "surveillance": "strategic",
        "economic": "personal",
        "financial": "personal",
        "historical_power": "archive",
        "old_money": "archive",
        "conflict": "alert",
        "warfare": "alert",
        "political_violence": "alert",
        "military": "power",
        "markets": "contagion",
        "growth": "contagion",
        "trade": "contagion",
    },
)


# =============================================================================
# Section 4: Rotation & Composition
# =============================================================================

_ROTATION = RotationConfig(
    compositions=[
        "wide", "medium", "closeup", "environmental",
        "overhead", "low_angle",
    ],
    max_consecutive_same_content_type=2,
    max_consecutive_same_format=2,
    max_consecutive_same_palette=3,
    max_consecutive_close_up=1,
    act_weights={
        "act1": {
            "strategic": 0.50, "alert": 0.25, "power": 0.20,
            "archive": 0.00, "contagion": 0.00, "personal": 0.05,
        },
        "act2": {
            "strategic": 0.30, "alert": 0.35, "power": 0.20,
            "archive": 0.05, "contagion": 0.05, "personal": 0.05,
        },
        "act3": {
            "strategic": 0.10, "alert": 0.10, "power": 0.05,
            "archive": 0.55, "contagion": 0.10, "personal": 0.10,
        },
        "act4": {
            "strategic": 0.10, "alert": 0.30, "power": 0.10,
            "archive": 0.30, "contagion": 0.15, "personal": 0.05,
        },
        "act5": {
            "strategic": 0.05, "alert": 0.35, "power": 0.05,
            "archive": 0.05, "contagion": 0.35, "personal": 0.15,
        },
        "act6": {
            "strategic": 0.45, "alert": 0.10, "power": 0.20,
            "archive": 0.05, "contagion": 0.05, "personal": 0.15,
        },
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
# Section 5: Figure Rules
# =============================================================================

_PEOPLE_WORDS = [
    "officer", "officers", "commander", "analyst", "operator", "operators",
    "figure", "figures", "person", "people", "man", "woman", "soldier",
    "soldiers", "guard", "guards", "hand", "hands", "silhouette",
    "silhouettes", "face", "faces", "human", "crew", "staff",
    "seated", "standing", "watching", "huddle", "checking", "dials",
]

_PEOPLE_REPLACEMENTS = [
    (r"\bofficers?\s+(?:at|huddle\w*\s+around|seated\s+at)\s+\w+", "unmanned consoles with active displays"),
    (r"\bcommander\s+\w+\s+\w+", "command terminal with priority alerts flashing"),
    (r"\banalyst\s+workstation", "workstation with open data feeds"),
    (r"\boperators?\s+(?:at|seated\s+at|monitoring)\s+\w+", "autonomous monitoring stations"),
    (r"\bofficers?\b", "autonomous terminals"),
    (r"\bcommander\b", "command terminal"),
    (r"\banalysts?\b", "data terminals"),
    (r"\boperators?\b", "monitoring stations"),
    (r"\bfigures?\b", "equipment"),
    (r"\bperson\b", "terminal"),
    (r"\bpeople\b", "unmanned equipment"),
    (r"\bsoldiers?\b", "military hardware"),
    (r"\bguards?\b", "security sensors"),
    (r"\bsilhouettes?\b", "equipment outlines"),
    (r"\bhuman\b", "autonomous"),
    (r"\bcrew\b", "autonomous systems"),
    (r"\bstaff\b", "automated systems"),
    (r"\bseated\b", "positioned"),
    (r"\bstanding\b", "mounted"),
    (r"\bwatching\b", "scanning"),
    (r"\bhuddle\b", "cluster"),
    (r"\bchecking\b", "processing"),
    (r"\bdials\b", "activates"),
    (r"\bhands?\b", "sensors"),
    (r"\bfaces?\b", "displays"),
    (r"\bman\b", "unit"),
    (r"\bwoman\b", "unit"),
]

_FIGURE_RULES = FigureRulesConfig(
    allow_human_figures=False,
    allow_silhouettes=False,
    allow_mannequins=False,
    protagonist_config=None,
    negative_prompt_suffix=(
        "no people visible no human figures no faces no silhouettes of people"
    ),
    people_words=_PEOPLE_WORDS,
    people_replacements=_PEOPLE_REPLACEMENTS,
)


# =============================================================================
# Section 6: Scene Description Rules
# =============================================================================

_SCENE_DESCRIPTION = SceneDescriptionConfig(
    system_prompt=(
        "You are a visual director creating HOLOGRAPHIC INTELLIGENCE DISPLAY "
        "image prompts for a YouTube documentary channel.\n\n"
        "Every image exists inside a dark, high-security intelligence "
        "operations center. The room is barely visible (10-15% of frame max). "
        "The star of every frame is the HOLOGRAPHIC PROJECTION SURFACE — "
        "a table, wall display, or floating mid-air projection showing "
        "analytical content.\n\n"
        "Think: war room from Tom Clancy crossed with Bloomberg Terminal "
        "crossed with Minority Report. Clinical. Precise. Authoritative."
    ),
    metaphor_translation_table={
        "money_flow": "Show the institution: central bank, trading floor, vault",
        "power_consolidation": "Show the person/building: corporate HQ, signing ceremony",
        "economic_pressure": "Show the data: price charts, inflation indicators, market terminals",
        "military_force": "Show the hardware: fleet positions, weapon systems, satellite imagery",
        "political_tension": "Show the documents: treaties, executive orders, diplomatic cables",
    },
    quantitative_requirement=True,
    text_in_image_rules=(
        "data-formatted only, not narrative — "
        "text elements must be data-formatted labels, numbers, percentages, "
        "or classification stamps only"
    ),
)


# =============================================================================
# Section 7: Animation Config
# =============================================================================

_LOW_MOTION = {
    "A_geographic_map": "Static wide shot. Route arrows pulse with faint traveling light dots moving along paths.",
    "B_data_terminal": "Static wide shot. Numerical values hold steady with occasional last-digit flicker.",
    "C_object_comparison": "Static wide shot. Floating labels hold position, wireframe edges shimmer faintly.",
    "D_document_display": "Static wide shot. Document page holds still, a single clause highlight pulses faintly.",
    "E_network_diagram": "Static wide shot. Connection lines maintain steady brightness, one node pulses faintly brighter.",
    "F_timeline": "Static wide shot. Timeline holds position, a single date marker glows faintly brighter.",
    "G_satellite": "Static wide shot. Satellite image holds still, a single annotation marker blinks.",
    "H_abstract_concept": "Static wide shot. Concept structure holds position, one element pulses with faint energy.",
}

_MEDIUM_MOTION = {
    "A_geographic_map": "Static wide shot. Route lines draw themselves across the map progressively. Position markers appear one by one with brief flash effects.",
    "B_data_terminal": "Static wide shot. Chart line draws itself from left to right revealing the trend. Warning indicators flash on at key thresholds.",
    "C_object_comparison": "Static wide shot. Objects materialize from particle clouds assembling into wireframe form. Measurement lines extend and lock into position.",
    "D_document_display": "Static wide shot. Document text reveals line by line as if being declassified. Key clauses highlight sequentially in amber.",
    "E_network_diagram": "Static wide shot. Nodes light up in sequence following the flow direction. Connection lines pulse with traveling energy showing direction.",
    "F_timeline": "Static wide shot. Timeline events appear in chronological order with connecting threads drawing between them.",
    "G_satellite": "Static wide shot. Annotation overlays materialize one by one. Measurement lines extend from points of interest.",
    "H_abstract_concept": "Static wide shot. Concept elements assemble from scattered particles into structured form. Force arrows activate showing direction.",
}

_HIGH_MOTION = {
    "A_geographic_map": "Static wide shot. A shockwave explodes outward from the crisis point. Route lines sever and retract with sparking particle effects.",
    "B_data_terminal": "Static wide shot. Chart line spikes violently upward with the screen shaking from the force. Warning indicators flood the display in red.",
    "C_object_comparison": "Static wide shot. Projectile crosses the frame leaving a particle trail. Target object glitches violently on impact with wireframe sections breaking apart.",
    "D_document_display": "Static wide shot. Document shatters into fragments that scatter across the display. DENIED stamp slams down with screen shake.",
    "E_network_diagram": "Static wide shot. Nodes overload and burst in sequence creating a cascade failure. Connection lines snap with sparking disconnection effects.",
    "F_timeline": "Static wide shot. A fracture line rips through the timeline splitting it. Events on one side dissolve while the other side burns brighter.",
    "G_satellite": "Static wide shot. Explosion blooms at the facility location. Debris field expands outward. Before/after overlay wipes across the image.",
    "H_abstract_concept": "Static wide shot. The balanced structure collapses as one side overwhelms the other. Force arrows reverse direction violently.",
}

_ANIMATION = AnimationConfig(
    animation_model="grok-imagine/image-to-video",
    animation_cost_per_clip=0.10,
    motion_templates={
        **{f"low_{k}": v for k, v in _LOW_MOTION.items()},
        **{f"medium_{k}": v for k, v in _MEDIUM_MOTION.items()},
        **{f"high_{k}": v for k, v in _HIGH_MOTION.items()},
    },
    motion_base_rule=(
        "Maintain the full original frame composition and camera angle, "
        "do not zoom or reframe"
    ),
    intensity_levels={
        "low": "Subtle ambient motion. Single element animates, everything else still.",
        "medium": "Active reveal motion. Up to two subject actions, static camera unless justified.",
        "high": "Dramatic action. Up to two subject actions, camera only for REVEAL/SCALE/ISOLATION.",
    },
    universal_rules=[
        "Maintain the full original frame composition.",
        "No human figures, faces, or hands should appear at any point during the animation.",
        "All text and data labels must remain legible throughout the animation.",
        "Holographic elements maintain their established color palette.",
    ],
    banned_motion_words=[
        "gently pulse", "softly intensif", "subtly flicker", "softly blink",
        "dust particles drift", "reflections shift across", "ambient.*glow",
        "equipment indicators", "projector beams", "light slowly sweeps",
        "holographic data.*pulse", "subtle ambient",
    ],
    emotional_motion_dict={
        "collapse_failure": [
            "freeze", "stutter", "desync", "dim in sequence", "go dark one by one",
            "slow to crawl", "lock up", "disconnect", "fragment", "dissolve",
            "drain", "flatline",
        ],
        "escalation_threat": [
            "accelerate", "multiply", "cascade", "spread outward", "intensify",
            "stack up", "compound", "swarm", "converge", "tighten",
        ],
        "revelation_discovery": [
            "snap into focus", "illuminate", "peel back layers", "zoom through",
            "resolve from static", "sharpen", "decode", "materialize",
        ],
        "dominance_power": [
            "override", "flood", "overwhelm", "lock on", "absorb", "eclipse",
            "tower over", "consume", "replace",
        ],
        "tension_standoff": [
            "hold unnaturally still", "vibrate", "strain", "pull apart slowly",
            "hover", "suspend", "balance on edge",
        ],
        "loss_absence": [
            "extinguish", "fade to nothing", "leave empty", "hollow out",
            "strip away", "erode", "scatter",
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
    thumbnail_prompt_templates={},  # Templates are in thumbnail_generator/templates.py
    thumbnail_color_presets={
        "geopolitics": ["#1a5c6b", "#FFD700", "#333", "#fff"],
        "finance": ["#b8860b", "#FFD700", "#333", "#fff"],
    },
    thumbnail_system_prompt="",  # Full prompt is in anthropic_client.py
    thumbnail_figure_rules="Generic building/hand, no named political figures",
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
# Section 10: Raw data — enum configs for the 3-variable system
# =============================================================================

_RAW = {
    # Content type configurations (8 types)
    "content_types": {
        "geographic_map": {
            "label": "Geographic Map",
            "use_for": "Locations, territories, shipping routes, military positions, chokepoints, borders",
            "key_elements": "Country outlines with labels, route lines with directional arrows, position markers, distance annotations, terrain features",
            "keywords": [
                "map", "strait", "chokepoint", "border", "territory", "route",
                "shipping lane", "coastline", "geography", "region", "peninsula",
                "island", "ocean", "sea", "gulf", "channel", "passage",
            ],
        },
        "data_terminal": {
            "label": "Data/Financial Terminal",
            "use_for": "Market reactions, price movements, economic data, statistics, inflation, trade volumes",
            "key_elements": "Candlestick or line charts, ticker tape feeds, percentage changes with arrows, side panel data readouts, warning indicators",
            "keywords": [
                "price", "market", "stock", "inflation", "gdp", "trade volume",
                "billion", "trillion", "percent", "rate", "index", "crash",
                "surge", "spike", "plunge", "recession", "growth",
            ],
        },
        "object_comparison": {
            "label": "Object/Asset Comparison",
            "use_for": "Scale contrasts, asymmetric warfare, cost comparisons, force comparisons",
            "key_elements": "Two or more objects in holographic wireframe at relative scale, floating data labels with costs/specs, comparison panels",
            "keywords": [
                "versus", "compared to", "asymmetric", "scale", "cost",
                "drone", "carrier", "fleet", "weapon", "defense", "missile",
            ],
        },
        "document_display": {
            "label": "Document/Contract Display",
            "use_for": "Legal frameworks, treaties, insurance policies, executive orders, classified briefs",
            "key_elements": "Floating translucent document with legible key clauses, highlight annotations, stamps (DENIED/CLASSIFIED/APPROVED), comparison panels",
            "keywords": [
                "treaty", "contract", "policy", "insurance", "sanction",
                "executive order", "law", "regulation", "agreement", "clause",
                "coverage", "premium", "legal",
            ],
        },
        "network_diagram": {
            "label": "Network/System Diagram",
            "use_for": "Trade flows, supply chains, alliance structures, chokepoint networks, cascade effects",
            "key_elements": "Nodes (glowing orbs) connected by flow lines of varying thickness, labels with percentages, disruption as severed connections",
            "keywords": [
                "supply chain", "network", "flow", "interconnected", "cascade",
                "domino", "contagion", "ripple", "chain reaction", "system",
                "pipeline", "dependency",
            ],
        },
        "timeline": {
            "label": "Timeline/Historical Comparison",
            "use_for": "Historical parallels, pattern recognition, chronological sequences, before/after",
            "key_elements": "Side-by-side or sequential panels showing different time periods, connecting visual threads, era labels with dates",
            "keywords": [
                "history", "historical", "century", "decade", "era", "parallel",
                "pattern", "1956", "1973", "1979", "2008", "crisis", "before",
                "precedent", "lesson",
            ],
        },
        "satellite_recon": {
            "label": "Satellite/Overhead Reconnaissance",
            "use_for": "Facility damage, ship positions, military deployments, geographic features, before/after",
            "key_elements": "Top-down or angled satellite perspective, annotation markers, measurement lines, timestamp/classification labels",
            "keywords": [
                "satellite", "overhead", "reconnaissance", "facility", "base",
                "deployment", "imagery", "aerial", "surveillance",
            ],
        },
        "concept_viz": {
            "label": "Abstract Concept Visualization",
            "use_for": "Theoretical frameworks, power dynamics, game theory, strategic concepts",
            "key_elements": "Metaphorical visual structures (chess boards, scales, pressure systems, domino chains), force arrows, equilibrium diagrams",
            "keywords": [
                "theory", "framework", "game theory", "equilibrium", "balance",
                "power dynamic", "strategy", "dilemma", "paradox", "concept",
            ],
        },
    },
    # Display format configurations (5 formats)
    "display_formats": {
        "war_table": {
            "label": "The War Table (Top-Down Angled)",
            "framing": "Overhead angled view of a holographic war table surface projecting",
            "camera_angle": "30-45 degree overhead angle looking down at horizontal holographic table surface",
            "best_for": "Geographic maps, network diagrams, satellite views",
        },
        "wall_display": {
            "label": "The Wall Display (Front-Facing)",
            "framing": "Front-facing view of a massive holographic wall display showing",
            "camera_angle": "Straight-on or slight angle, massive wall-mounted display",
            "best_for": "Financial terminals, document displays, timeline comparisons",
        },
        "floating": {
            "label": "The Floating Projection (Mid-Air)",
            "framing": "Eye-level view of holographic objects floating in dark space showing",
            "camera_angle": "Eye level or slight low angle, content floating in dark space",
            "best_for": "Object comparisons, abstract concepts, symbolic visualizations",
        },
        "multi_panel": {
            "label": "The Multi-Panel Command (Split Screen)",
            "framing": "Wide angle view of multiple holographic display panels showing",
            "camera_angle": "Slight wide angle showing multiple displays at once",
            "best_for": "Before/after comparisons, historical parallels, cascading events",
        },
        "close_up_detail": {
            "label": "The Close-Up Detail (Macro Focus)",
            "framing": "Extreme close-up of a holographic display detail showing",
            "camera_angle": "Tight crop on specific data point, chart section, or document detail",
            "best_for": "Key statistics, critical text, turning-point moments",
        },
    },
    # Color mood configurations (6 moods)
    "color_moods": {
        "strategic": {
            "label": "STRATEGIC (Teal/Cyan)",
            "use_for": "Calm analysis, geographic explanation, establishing context, framework introduction",
            "primary": "#00CED1 teal, #00FFFF cyan",
            "prompt_language": "cool teal and cyan holographic light against dark background, clinical intelligence aesthetic",
            "keywords": [
                "analysis", "strategic", "map", "geography", "framework",
                "chokepoint", "strait", "position", "context", "overview",
                "examine", "consider", "intelligence",
            ],
        },
        "alert": {
            "label": "ALERT (Red/Amber)",
            "use_for": "Crisis moments, market crashes, attacks, closures, breaking events",
            "primary": "#FF2D2D deep red, #FFB000 amber",
            "prompt_language": "red and amber warning colors dominating the display, emergency alert aesthetic, pulsing warning indicators",
            "keywords": [
                "crisis", "crash", "attack", "closure", "emergency", "war",
                "strike", "collapse", "panic", "threat", "danger", "warning",
                "breaking", "escalate", "conflict", "missile", "bomb",
            ],
        },
        "archive": {
            "label": "ARCHIVE (Gold/Sepia)",
            "use_for": "Historical parallels, pattern recognition, lessons from the past",
            "primary": "#C9A84C warm gold, #D4A574 antique amber",
            "prompt_language": "warm golden amber holographic light suggesting historical archive, antique brass and wood tones in the room periphery",
            "keywords": [
                "history", "historical", "century", "1956", "1973", "1979",
                "parallel", "pattern", "precedent", "lesson", "era", "past",
                "archive", "ancient", "empire",
            ],
        },
        "contagion": {
            "label": "CONTAGION (Green-to-Red)",
            "use_for": "Cascading effects, spreading economic damage, interconnected failures, domino chains",
            "primary": "#00FF88 green transitioning through #FFD700 yellow to #FF2D2D red",
            "prompt_language": "color transitioning from green through yellow to red showing contagion spread, pandemic-style cascade visualization",
            "keywords": [
                "cascade", "spread", "contagion", "ripple", "domino",
                "chain reaction", "infect", "interconnected", "systemic",
                "spillover", "downstream",
            ],
        },
        "power": {
            "label": "POWER (Deep Blue/White)",
            "use_for": "Military force analysis, defense spending, naval power, institutional authority",
            "primary": "#1B3A5C deep navy, #4682B4 steel blue",
            "prompt_language": "deep navy blue and steel holographic wireframes with clean white labels, military precision aesthetic",
            "keywords": [
                "military", "navy", "fleet", "carrier", "defense", "pentagon",
                "force", "power", "authority", "institutional", "deployment",
                "base", "command",
            ],
        },
        "personal": {
            "label": "PERSONAL (Orange/White)",
            "use_for": "Viewer impact scenes, personal financial consequences",
            "primary": "#FF8C00 warm orange, white",
            "prompt_language": "warm orange and white display with green and red financial indicators, personal impact dashboard aesthetic",
            "keywords": [
                "your", "viewer", "wallet", "personal", "afford", "pay",
                "cost of living", "grocery", "gas price", "savings",
                "retirement", "household",
            ],
        },
    },
    # Color mood priority order (for tie-breaking)
    "color_mood_priority": ["alert", "archive", "strategic", "power", "contagion", "personal"],
    # Content-format affinity mapping
    "content_format_affinity": {
        "geographic_map": ["war_table", "multi_panel"],
        "data_terminal": ["wall_display", "close_up_detail"],
        "object_comparison": ["floating", "war_table"],
        "document_display": ["wall_display", "close_up_detail"],
        "network_diagram": ["war_table", "floating"],
        "timeline": ["multi_panel", "wall_display"],
        "satellite_recon": ["war_table", "close_up_detail"],
        "concept_viz": ["floating", "war_table"],
    },
    # Display format rotation cycle
    "format_cycle": ["war_table", "wall_display", "floating", "multi_panel", "close_up_detail"],
    # Establishing shot formats (preferred for first image of each act)
    "establishing_formats": ["war_table", "wall_display"],
    # Ken Burns rules per display format
    "ken_burns_rules_by_format": {
        "war_table": "slow_zoom_in",
        "wall_display": "slow_pan_right",
        "floating": "slow_zoom_out",
        "multi_panel": "slow_pan_left",
        "close_up_detail": "slow_zoom_in",
    },
    # Default config values
    "default_config": {
        "image_duration_seconds": 11,
        "video_duration_seconds": 1500,
        "total_images": 136,
        "act_timestamps": {
            "act1_end": 90,
            "act2_end": 360,
            "act3_end": 720,
            "act4_end": 1020,
            "act5_end": 1320,
            "act6_end": 1500,
        },
    },
    # Style engine legacy constants
    "style_engine_prefix": _HOLOGRAPHIC_PREFIX,
    "style_engine_suffix": (
        "No people visible, no human figures, no faces, no silhouettes, "
        "only holographic data displays and dark room environment, "
        "cinematic depth of field, subtle ambient equipment glow."
    ),
    # Camera movement vocabulary (for video animation prompts)
    "camera_movement_by_format": {
        "war_table": [
            "Slow orbit around the table surface",
            "Gentle push-in toward the center of the projection",
            "Slow crane upward revealing the full table layout",
            "Subtle drift with parallax depth between table and floating panels",
        ],
        "wall_display": [
            "Slow push-in toward the central display",
            "Gentle lateral pan across the data panels",
            "Slow drift from left panel to right panel",
            "Subtle crane downward from overview to detail",
        ],
        "floating": [
            "Slow orbit around the floating objects",
            "Gentle push-in between floating elements",
            "Slow rise from below the projection level",
            "Subtle rotation revealing different angles of the display",
        ],
        "multi_panel": [
            "Slow lateral pan from left panel to right panel",
            "Gentle pull-back revealing all panels at once",
            "Slow drift connecting the panels visually",
            "Subtle push-in on the central connecting element",
        ],
        "close_up_detail": [
            "Very slow drift to the right across the data",
            "Gentle push-in on the key data point",
            "Slow breathing zoom on the focal element",
            "Subtle rack focus between foreground and background data",
        ],
    },
    # Material vocabulary
    "material_vocabulary": {
        "premium": [
            "holographic gold wireframe", "brass instrument bezels",
            "polished console surfaces", "amber status indicators",
        ],
        "institutional": [
            "dark console banks", "security-grade displays",
            "reinforced server racks", "military-grade equipment",
        ],
        "data": [
            "holographic projections", "translucent data overlays",
            "glowing node networks", "floating analytical panels",
        ],
    },
    # Prompt word budget
    "prompt_min_words": 60,
    "prompt_max_words": 150,
    # Valid scene models for hot-swap
    "valid_scene_models": {
        "z-image": "Z Image (default — holographic display, $0.004/img)",
        "nano-banana-2": "Nano Banana 2 (legacy — reference support, $0.025/img)",
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
    raw=_RAW,
)
