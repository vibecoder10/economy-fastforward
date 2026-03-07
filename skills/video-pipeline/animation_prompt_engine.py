"""Animation Prompt Engine.

Generates Grok Imagine animation prompts for each segmented video clip.
Animation intensity varies based on the segment's narrative intensity score
from the segmentation engine.

Each segment gets:
1. An image (from the holographic display image prompt engine)
2. An animation prompt (from this engine)
3. An intensity level (from the segmentation engine)
"""

# Universal rules appended to every animation prompt
UNIVERSAL_RULES = (
    "Maintain the full original frame composition and camera angle, do not zoom or reframe. "
    "No human figures, faces, or hands should appear at any point during the animation. "
    "All text and data labels must remain legible throughout the animation. "
    "Holographic elements maintain their established color palette."
)

# Content-specific motion descriptions by intensity and content type
_LOW_MOTION = {
    "A_geographic_map": "Map contour lines shimmer subtly, route arrows pulse with faint traveling light dots moving along the paths, country label text glows slightly brighter then dims in a slow rhythm",
    "B_data_terminal": "Chart lines have a faint pixel shimmer, ticker tape scrolls slowly at the bottom, numerical values hold steady with occasional last-digit flicker",
    "C_object_comparison": "Wireframe objects rotate very slowly in place, holographic grid lines on the display surface pulse gently, floating labels sway almost imperceptibly",
    "D_document_display": "Document has subtle translucent shimmer as if projected through moving air, stamps and highlights pulse gently, page edges have faint particle drift",
    "E_network_diagram": "Network connection lines pulse with faint traveling light, nodes glow brighter and dimmer in slow rhythm, percentage labels hold steady",
    "F_timeline": "Timeline panels have subtle internal animation, connecting thread pulses with traveling light, era labels glow gently",
    "G_satellite": "Satellite image has subtle scan line moving across it, annotation markers pulse, timestamp updates slowly",
    "H_abstract_concept": "Conceptual elements drift very slightly, force arrows pulse, symbolic objects rotate imperceptibly slowly",
}

_MEDIUM_MOTION = {
    "A_geographic_map": "Route lines draw themselves across the map progressively, position markers appear one by one with brief flash effects, a highlighted zone expands outward with pulsing border, country labels illuminate sequentially",
    "B_data_terminal": "Chart line draws itself from left to right revealing the trend in real time, data panels populate line by line as if being typed, warning indicators flash on at key thresholds, ticker tape accelerates",
    "C_object_comparison": "Objects materialize from particle clouds assembling into wireframe form, measurement lines extend and lock into position with data appearing, comparison panel illuminates section by section",
    "D_document_display": "Document scrolls or pages turn revealing new content, highlight annotations draw themselves around key clauses, stamps materialize and slam down with impact particle effects",
    "E_network_diagram": "Connection lines between nodes light up sequentially showing flow direction, a disruption pulse travels from the source node outward through the network, affected nodes change color as the pulse reaches them",
    "F_timeline": "Timeline panels appear left to right revealing each era in sequence, connecting thread draws itself between them, data overlays within each panel animate their charts or markers",
    "G_satellite": "Image resolves from blurry to sharp as if the satellite is focusing, annotation markers drop in from above and lock to positions, comparison overlay slides in from the side",
    "H_abstract_concept": "Conceptual elements assemble from scattered particles into their final configuration, force arrows extend and lock, the balance or dynamic of the concept becomes visible through motion",
}

_HIGH_MOTION = {
    "A_geographic_map": "A shockwave or disruption pulse explodes outward from the crisis point, route lines sever and retract with sparking particle effects, affected regions flash red and glitch, the entire map flickers with interference at the moment of impact",
    "B_data_terminal": "Chart line spikes violently upward or crashes downward with the screen shaking from the force, warning klaxon indicators flood the display in red, numbers spin rapidly before locking on extreme values, the entire terminal flashes emergency colors",
    "C_object_comparison": "One object attacks or impacts the other — projectile crosses the frame leaving a particle trail, the target object glitches violently on impact with wireframe sections breaking apart and dissolving into scattered particles, cost labels flash and update rapidly",
    "D_document_display": "Document is overridden — a massive stamp slams down with shockwave, or the document tears apart, or red DENIED or CLASSIFIED overlays cascade across the content, particle effects explode from the impact",
    "E_network_diagram": "A critical node goes dark with an explosion of particles, its connections snap and recoil like severed cables with sparking effects, cascade failure ripples outward as connected nodes flash warning colors and fail sequentially",
    "F_timeline": "The final panel ignites or activates dramatically, connecting thread turns from gold to red as the pattern completes, the current-era panel pulses with urgency as if the lesson is happening right now",
    "G_satellite": "Impact strikes are visible — explosions, fire, structural damage appearing on the facility, before/after split slides dramatically revealing destruction, smoke or debris particles rise",
    "H_abstract_concept": "The conceptual balance breaks dramatically — one side overwhelms the other, scales tip violently, chess pieces shatter, dominoes fall in rapid succession with each impact creating a burst of particles",
}

ANIMATION_TEMPLATES = {
    "low": {
        "description": "Subtle ambient motion. Data pulses, gentle glow shifts, minimal movement.",
        "prefix": "Subtle ambient motion only.",
        "suffix": "No dramatic movements or camera changes.",
        "motion_by_type": _LOW_MOTION,
    },
    "medium": {
        "description": "Active reveal motion. Data appearing, elements activating, builds energy.",
        "prefix": "Active reveal animation.",
        "suffix": "Slow deliberate camera push or pull acceptable (max 10% frame shift).",
        "motion_by_type": _MEDIUM_MOTION,
    },
    "high": {
        "description": "Dramatic action. Impacts, destructions, cascades, maximum visual energy.",
        "prefix": "Dramatic high-energy animation.",
        "suffix": "Camera may push in toward impact point (max 15% frame shift).",
        "motion_by_type": _HIGH_MOTION,
    },
}

# Default content type when image type is unknown
_DEFAULT_CONTENT_TYPE = "B_data_terminal"


def generate_animation_prompt(
    segment: dict,
    image_content_type: str = "",
    clip_duration: int = 10,
) -> str:
    """Generate a Grok Imagine animation prompt for a segment.

    Args:
        segment: Segment dict from segmentation engine (must have "intensity" key).
        image_content_type: One of A_geographic_map through H_abstract_concept.
            Falls back to B_data_terminal if empty or unknown.
        clip_duration: Duration in seconds (6 or 10).

    Returns:
        Complete animation prompt string.
    """
    intensity = segment.get("intensity", "low")
    template = ANIMATION_TEMPLATES.get(intensity, ANIMATION_TEMPLATES["low"])

    content_type = image_content_type if image_content_type in template["motion_by_type"] else _DEFAULT_CONTENT_TYPE
    content_motion = template["motion_by_type"][content_type]

    parts = [
        template["prefix"],
        content_motion,
        "Data labels and text remain stable and legible throughout.",
        "Dark room background unchanged." if intensity == "low" else (
            "Dark room background may have subtle reactive ambient light changes." if intensity == "medium"
            else "Room ambient lighting reacts dramatically — screens flash, warning lights activate."
        ),
        template["suffix"],
        f"{clip_duration} seconds.",
        UNIVERSAL_RULES,
    ]

    return " ".join(parts)


def generate_prompts_for_segments(
    segments: list[dict],
    content_types: dict[int, str] | None = None,
    clip_duration: int = 10,
) -> list[dict]:
    """Generate animation prompts for all segments.

    Args:
        segments: List of segment dicts from segmentation engine.
        content_types: Optional mapping of segment index to content type string.
            When None, defaults to B_data_terminal for all segments.
        clip_duration: Duration in seconds (6 or 10).

    Returns:
        List of dicts with segment index and animation_prompt.
    """
    if content_types is None:
        content_types = {}

    results = []
    for seg in segments:
        idx = seg["index"]
        ct = content_types.get(idx, _DEFAULT_CONTENT_TYPE)
        prompt = generate_animation_prompt(seg, ct, clip_duration)
        results.append({
            "segment_index": idx,
            "intensity": seg.get("intensity", "low"),
            "animation_prompt": prompt,
        })
    return results
