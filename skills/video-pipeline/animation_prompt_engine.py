"""Animation Prompt Engine.

Generates Grok Imagine animation prompts for each segmented video clip.
Animation intensity varies based on the segment's narrative intensity score
from the segmentation engine.

Each segment gets:
1. An image (from the holographic display image prompt engine)
2. An animation prompt (from this engine)
3. An intensity level (from the segmentation engine)

==========================================================================
ANIMATION PROMPT RULES (established Mar 2026)
==========================================================================

RULE 1 — VERB-FIRST MOTION DESIGN
  The animation prompt derives its primary motion from the VERB in the
  sentence text. Process:
    1. Read the sentence text for this clip
    2. Identify the core verb or action
    3. The subject animation must LITERALLY ENACT that verb
    4. Everything else in frame holds still
  The verb IS the animation. Not a metaphor. Not decoration. The literal
  visual enactment of what the sentence describes.

RULE 2 — CAMERA MOVES ONLY WHEN CAMERA IS THE MEANING
  Camera is STATIC by default. Only add camera motion for exactly one of:
    REVEAL   — motion uncovers something new
    SCALE    — motion communicates size
    ISOLATION — motion narrows focus on one critical element
  If the camera move doesn't serve REVEAL, SCALE, or ISOLATION, it's a
  static shot. No default orbits, drifts, or push-ins.

RULE 3 — TWO ACTIONS MAXIMUM PER CLIP
  Each prompt gets AT MOST:
    - 1 camera action (only if it passes Rule 2) + 1 subject action
    - OR 0 camera action + 2 subject actions
    - NEVER more than 2 total animated elements
  If a sentence needs more complexity, split across multiple clips.
==========================================================================
"""

from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Verb extraction — Rule 1 support
# ---------------------------------------------------------------------------

# Common "stop verbs" that are too generic to drive animation
_STOP_VERBS = frozenset({
    "is", "are", "was", "were", "be", "been", "being", "has", "have", "had",
    "do", "does", "did", "can", "could", "will", "would", "shall", "should",
    "may", "might", "must", "get", "got", "say", "said", "says", "know",
    "knew", "think", "thought", "see", "saw", "make", "made", "come", "came",
    "go", "went", "take", "took", "give", "gave", "find", "found", "tell",
    "told", "let", "put", "seem", "need", "mean", "keep", "begin", "show",
    "hear", "play", "run", "move", "live", "believe", "happen", "call",
    "try", "ask", "use", "want", "look",
})

# Phrasal verbs / multi-word actions that should be captured whole
_PHRASAL_VERB_PATTERNS = [
    re.compile(r"\b(going\s+dark)\b", re.IGNORECASE),
    re.compile(r"\b(shut(?:ting)?\s+down)\b", re.IGNORECASE),
    re.compile(r"\b(break(?:ing)?\s+apart)\b", re.IGNORECASE),
    re.compile(r"\b(fall(?:ing)?\s+apart)\b", re.IGNORECASE),
    re.compile(r"\b(lock(?:s|ed|ing)?\s+(?:in|on|frozen|up))\b", re.IGNORECASE),
    re.compile(r"\b(pile(?:s|d|ing)?\s+up)\b", re.IGNORECASE),
    re.compile(r"\b(dry(?:s|ing|ied)?\s+up)\b", re.IGNORECASE),
    re.compile(r"\b(light(?:s|ing|ed)?\s+up)\b", re.IGNORECASE),
    re.compile(r"\b(blow(?:s|n|ing)?\s+(?:up|apart))\b", re.IGNORECASE),
    re.compile(r"\b(rip(?:s|ped|ping)?\s+(?:through|apart))\b", re.IGNORECASE),
    re.compile(r"\b(don'?t\s+matter)\b", re.IGNORECASE),
    re.compile(r"\b(wip(?:e[sd]?|ing)\s+out)\b", re.IGNORECASE),
    re.compile(r"\b(spread(?:s|ing)?\s+(?:across|out))\b", re.IGNORECASE),
]

# Single-word action verbs (gerunds, past tense, base forms) that drive motion
_ACTION_VERB_PATTERN = re.compile(
    r"\b("
    r"scatter(?:s|ed|ing)?|launch(?:es|ed|ing)?|freeze(?:s|d)?|freez(?:ing)|frozen|"
    r"crash(?:es|ed|ing)?|collapse(?:s|d)?|collaps(?:ing)|"
    r"explod(?:e[sd]?|ing)|dissolv(?:e[sd]?|ing)|shatter(?:s|ed|ing)?|"
    r"surge(?:s|d)?|surg(?:ing)|spike(?:s|d)?|spik(?:ing)|"
    r"plunge(?:s|d)?|plung(?:ing)|plummet(?:s|ed|ing)?|"
    r"spread(?:s|ing)?|multiply|multipli(?:es|ed)|"
    r"flood(?:s|ed|ing)?|drain(?:s|ed|ing)?|"
    r"extinguish(?:es|ed|ing)?|ignit(?:e[sd]?|ing)|"
    r"sever(?:s|ed|ing)?|snap(?:s|ped|ping)?|"
    r"cascade(?:s|d)?|cascad(?:ing)|rippl(?:e[sd]?|ing)|"
    r"lock(?:s|ed|ing)?|unlock(?:s|ed|ing)?|"
    r"block(?:s|ed|ing)?|halt(?:s|ed|ing)?|stall(?:s|ed|ing)?|"
    r"climb(?:s|ed|ing)?|drop(?:s|ped|ping)?|"
    r"erode(?:s|d)?|erod(?:ing)|strip(?:s|ped|ping)?|"
    r"consum(?:e[sd]?|ing)|devour(?:s|ed|ing)?|"
    r"overwhelm(?:s|ed|ing)?|dominat(?:e[sd]?|ing)|"
    r"fractur(?:e[sd]?|ing)|crack(?:s|ed|ing)?|"
    r"accelerat(?:e[sd]?|ing)|decelerat(?:e[sd]?|ing)|"
    r"assembl(?:e[sd]?|ing)|disassembl(?:e[sd]?|ing)|"
    r"connect(?:s|ed|ing)?|disconnect(?:s|ed|ing)?|"
    r"activate(?:s|d)?|activat(?:ing)|deactivat(?:e[sd]?|ing)|"
    r"engulf(?:s|ed|ing)?|swarm(?:s|ed|ing)?|"
    r"tighten(?:s|ed|ing)?|loosen(?:s|ed|ing)?|"
    r"expand(?:s|ed|ing)?|contract(?:s|ed|ing)?|"
    r"burn(?:s|ed|ing)?|melt(?:s|ed|ing)?|"
    r"rise(?:s)?|rising|risen|rose|"
    r"fall(?:s|ing)?|fell|fallen|"
    r"split(?:s|ting)?|tear(?:s|ing)?|tore|torn|"
    r"sink(?:s|ing)?|sank|sunk"
    r")\b",
    re.IGNORECASE,
)


def extract_core_verb(sentence_text: str) -> str:
    """Extract the core action verb or phrasal verb from sentence text.

    Returns the verb/phrase that should drive the animation motion.
    Falls back to an empty string if no meaningful verb is found.
    """
    if not sentence_text:
        return ""

    # Try phrasal verbs first (multi-word actions are more specific)
    for pattern in _PHRASAL_VERB_PATTERNS:
        match = pattern.search(sentence_text)
        if match:
            return match.group(1).lower().strip()

    # Try single-word action verbs
    match = _ACTION_VERB_PATTERN.search(sentence_text)
    if match:
        return match.group(1).lower().strip()

    # Fallback: scan all words for any verb-like word not in stop list
    words = re.findall(r"\b[a-z]+(?:ing|ed|es|s)?\b", sentence_text.lower())
    for word in words:
        base = re.sub(r"(ing|ed|es|s)$", "", word)
        if len(base) >= 3 and word not in _STOP_VERBS and base not in _STOP_VERBS:
            # Skip common non-verbs
            if word not in {"the", "and", "but", "for", "not", "its", "this",
                            "that", "these", "those", "their", "them", "his",
                            "her", "from", "with", "into", "across", "between",
                            "after", "before", "about", "against", "over",
                            "under", "every", "each", "most", "more", "less",
                            "other", "another", "some", "all", "many", "much"}:
                return word

    return ""


# ---------------------------------------------------------------------------
# Camera purpose validation — Rule 2 support
# ---------------------------------------------------------------------------

# Camera purpose tags
CAMERA_PURPOSE_REVEAL = "REVEAL"
CAMERA_PURPOSE_SCALE = "SCALE"
CAMERA_PURPOSE_ISOLATION = "ISOLATION"
CAMERA_PURPOSE_STATIC = "STATIC"

VALID_CAMERA_PURPOSES = frozenset({
    CAMERA_PURPOSE_REVEAL,
    CAMERA_PURPOSE_SCALE,
    CAMERA_PURPOSE_ISOLATION,
    CAMERA_PURPOSE_STATIC,
})


def classify_camera_purpose(sentence_text: str) -> str:
    """Determine if camera motion is justified and what purpose it serves.

    Returns one of: REVEAL, SCALE, ISOLATION, or STATIC (default).
    Camera motion is only justified for REVEAL, SCALE, or ISOLATION.
    """
    if not sentence_text:
        return CAMERA_PURPOSE_STATIC

    text_lower = sentence_text.lower()

    # REVEAL keywords: uncovering, discovering, exposing
    reveal_words = [
        "reveal", "uncover", "discover", "expose", "behind", "hidden",
        "beneath", "underneath", "secret", "unknown", "unseen", "emerges",
        "appears", "showing", "unveil",
    ]
    if any(w in text_lower for w in reveal_words):
        return CAMERA_PURPOSE_REVEAL

    # SCALE keywords: vastness, quantity, magnitude
    scale_words = [
        "thousands", "millions", "billions", "trillions", "massive", "vast",
        "enormous", "entire", "all of", "every single", "across the",
        "spanning", "worldwide", "global", "continent", "ocean",
        "how many", "how much", "scale", "magnitude",
    ]
    if any(w in text_lower for w in scale_words):
        return CAMERA_PURPOSE_SCALE

    # ISOLATION keywords: one specific thing, focus, critical detail
    isolation_words = [
        "only one", "single", "lone", "just one", "the one", "critical",
        "this specific", "that exact", "pinpoint", "zero in", "focus on",
        "the key", "the crucial",
    ]
    if any(w in text_lower for w in isolation_words):
        return CAMERA_PURPOSE_ISOLATION

    return CAMERA_PURPOSE_STATIC


# ---------------------------------------------------------------------------
# Animated element counting — Rule 3 support
# ---------------------------------------------------------------------------

# Patterns that indicate a distinct animated element
_ANIMATION_ACTION_PATTERNS = [
    re.compile(r"\b(?:push[- ]in|pull[- ]back|zoom (?:in|out)|dolly (?:in|out))\b", re.IGNORECASE),
    re.compile(r"\b(?:pan (?:left|right|across)|lateral pan|tracking shot)\b", re.IGNORECASE),
    re.compile(r"\b(?:tilt (?:up|down)|crane (?:up|down))\b", re.IGNORECASE),
    re.compile(r"\b(?:snap zoom|crash zoom|fast push)\b", re.IGNORECASE),
    re.compile(r"\b(?:orbit(?:al|s|ing)?|rotat(?:e[sd]?|ing|ion))\b", re.IGNORECASE),
]

# Sentence-splitting pattern to count independent actions
_ACTION_SENTENCE_SPLIT = re.compile(r"[.;,]\s+(?=[A-Z])")


def count_animated_elements(prompt: str) -> int:
    """Count the number of distinct animated elements in an animation prompt.

    Counts camera motions + subject actions. Returns total count.
    A prompt should have at most 2 animated elements per Rule 3.
    """
    if not prompt:
        return 0

    count = 0

    # Count camera motions (any non-static camera direction counts as 1)
    has_camera = False
    for pattern in _ANIMATION_ACTION_PATTERNS:
        if pattern.search(prompt):
            has_camera = True
            break
    if has_camera:
        count += 1

    # Count subject actions by splitting on sentence boundaries
    # Each clause with an action verb is one animated element
    clauses = _ACTION_SENTENCE_SPLIT.split(prompt)
    subject_actions = 0
    for clause in clauses:
        clause_lower = clause.lower().strip()
        # Skip camera-only clauses
        if any(p.search(clause) for p in _ANIMATION_ACTION_PATTERNS):
            if len(clause.split()) < 8:  # Short clause = camera-only
                continue
        # Check if clause has a subject action verb
        action_verbs = [
            "extinguish", "dissolve", "spread", "multiply", "freeze",
            "lock", "snap", "sever", "cascade", "ripple", "collapse",
            "explode", "shatter", "surge", "spike", "plunge", "drain",
            "flood", "ignite", "crack", "tear", "burn", "melt",
            "assemble", "materialize", "illuminate", "activate",
            "draw", "scroll", "appear", "flash", "slam", "drop",
            "retract", "expand", "contract", "accelerate", "decelerate",
            "pulse", "flicker", "shimmer", "glow",
        ]
        if any(v in clause_lower for v in action_verbs):
            subject_actions += 1

    count += subject_actions
    return max(count, 1)  # At least 1 if prompt is non-empty


def validate_max_actions(prompt: str, max_actions: int = 2) -> tuple[bool, int]:
    """Validate that a prompt doesn't exceed the maximum animated elements.

    Returns (is_valid, element_count).
    """
    count = count_animated_elements(prompt)
    return (count <= max_actions, count)


# ---------------------------------------------------------------------------
# Universal rules appended to every animation prompt
# ---------------------------------------------------------------------------

UNIVERSAL_RULES = (
    "Maintain the full original frame composition. "
    "No human figures, faces, or hands should appear at any point during the animation. "
    "All text and data labels must remain legible throughout the animation. "
    "Holographic elements maintain their established color palette."
)


# ---------------------------------------------------------------------------
# Content-specific motion templates — VERB-FIRST, STATIC CAMERA, 2-ACTION MAX
# ---------------------------------------------------------------------------
# Each template describes 1-2 subject actions. No camera motion by default.
# Camera motion is added separately only when justified by REVEAL/SCALE/ISOLATION.
# ---------------------------------------------------------------------------

_LOW_MOTION = {
    "A_geographic_map": "Static wide shot. Route arrows pulse with faint traveling light dots moving along paths.",
    "B_data_terminal": "Static wide shot. Numerical values hold steady with occasional last-digit flicker.",
    "C_object_comparison": "Static wide shot. Floating labels hold position, wireframe edges shimmer faintly.",
    "D_document_display": "Static wide shot. Document text holds steady, stamps pulse with faint glow.",
    "E_network_diagram": "Static wide shot. Connection lines pulse with faint traveling light between nodes.",
    "F_timeline": "Static wide shot. Connecting thread pulses with traveling light across panels.",
    "G_satellite": "Static wide shot. A single scan line moves slowly across the satellite image.",
    "H_abstract_concept": "Static wide shot. Force arrows pulse faintly, all other elements hold still.",
}

_MEDIUM_MOTION = {
    "A_geographic_map": "Static wide shot. Route lines draw themselves across the map progressively. Position markers appear one by one with brief flash effects.",
    "B_data_terminal": "Static wide shot. Chart line draws itself from left to right revealing the trend. Warning indicators flash on at key thresholds.",
    "C_object_comparison": "Static wide shot. Objects materialize from particle clouds assembling into wireframe form. Measurement lines extend and lock into position.",
    "D_document_display": "Static wide shot. Highlight annotations draw themselves around key clauses. A stamp materializes and slams down with impact particles.",
    "E_network_diagram": "Static wide shot. Connection lines light up sequentially showing flow direction. A disruption pulse travels from source node outward through the network.",
    "F_timeline": "Static wide shot. Timeline panels appear left to right revealing each era in sequence. Connecting thread draws itself between them.",
    "G_satellite": "Static wide shot. Image resolves from blurry to sharp as if focusing. Annotation markers drop in from above and lock to positions.",
    "H_abstract_concept": "Static wide shot. Conceptual elements assemble from scattered particles into final configuration. Force arrows extend and lock.",
}

_HIGH_MOTION = {
    "A_geographic_map": "Static wide shot. A shockwave explodes outward from the crisis point. Route lines sever and retract with sparking particle effects.",
    "B_data_terminal": "Static wide shot. Chart line spikes violently upward with the screen shaking from the force. Warning indicators flood the display in red.",
    "C_object_comparison": "Static wide shot. Projectile crosses the frame leaving a particle trail. Target object glitches violently on impact with wireframe sections breaking apart.",
    "D_document_display": "Static wide shot. A massive stamp slams down with shockwave. Red DENIED overlays cascade across the content.",
    "E_network_diagram": "Static wide shot. A critical node goes dark with an explosion of particles. Its connections snap and recoil like severed cables.",
    "F_timeline": "Static wide shot. The final panel ignites dramatically. Connecting thread turns from gold to red as the pattern completes.",
    "G_satellite": "Static wide shot. Impact strikes appear on the facility — explosions, structural damage. Smoke and debris particles rise from impact points.",
    "H_abstract_concept": "Static wide shot. The conceptual balance breaks — one side overwhelms the other. Scales tip violently with burst of particles.",
}

ANIMATION_TEMPLATES = {
    "low": {
        "description": "Subtle ambient motion. Single element animates, everything else still.",
        "prefix": "Static shot.",
        "suffix": "No camera movement.",
        "motion_by_type": _LOW_MOTION,
    },
    "medium": {
        "description": "Active reveal motion. Up to two subject actions, static camera unless justified.",
        "prefix": "Static shot.",
        "suffix": "No camera movement unless serving REVEAL, SCALE, or ISOLATION.",
        "motion_by_type": _MEDIUM_MOTION,
    },
    "high": {
        "description": "Dramatic action. Up to two subject actions, camera only for REVEAL/SCALE/ISOLATION.",
        "prefix": "Static shot.",
        "suffix": "Camera motion only if serving REVEAL, SCALE, or ISOLATION.",
        "motion_by_type": _HIGH_MOTION,
    },
}

# Default content type when image type is unknown
_DEFAULT_CONTENT_TYPE = "B_data_terminal"

# Camera motion templates keyed by purpose — only used when purpose is not STATIC
_CAMERA_BY_PURPOSE = {
    CAMERA_PURPOSE_REVEAL: "Slow lateral pan revealing",
    CAMERA_PURPOSE_SCALE: "Gradual pull-back showing full scale of",
    CAMERA_PURPOSE_ISOLATION: "Slow push-in isolating",
}


def generate_animation_prompt(
    segment: dict,
    image_content_type: str = "",
    clip_duration: int = 10,
) -> str:
    """Generate a Grok Imagine animation prompt for a segment.

    Applies the three animation rules:
    - Rule 1: Verb from sentence text drives the primary motion
    - Rule 2: Camera is static unless REVEAL/SCALE/ISOLATION is justified
    - Rule 3: Maximum 2 animated elements per prompt

    Args:
        segment: Segment dict from segmentation engine. Must have "intensity" key.
            May have "text" key with sentence text for verb extraction.
        image_content_type: One of A_geographic_map through H_abstract_concept.
            Falls back to B_data_terminal if empty or unknown.
        clip_duration: Duration in seconds (6 or 10).

    Returns:
        Complete animation prompt string.
    """
    intensity = segment.get("intensity", "low")
    sentence_text = segment.get("text", "")
    template = ANIMATION_TEMPLATES.get(intensity, ANIMATION_TEMPLATES["low"])

    content_type = (
        image_content_type
        if image_content_type in template["motion_by_type"]
        else _DEFAULT_CONTENT_TYPE
    )
    content_motion = template["motion_by_type"][content_type]

    # Rule 1: Extract verb and build verb-driven motion note
    verb = extract_core_verb(sentence_text)
    verb_note = ""
    if verb:
        verb_note = f"Primary motion driven by verb: \"{verb}\". "

    # Rule 2: Camera purpose — static by default
    camera_purpose = classify_camera_purpose(sentence_text)
    camera_note = ""
    if camera_purpose != CAMERA_PURPOSE_STATIC:
        camera_prefix = _CAMERA_BY_PURPOSE.get(camera_purpose, "")
        if camera_prefix:
            camera_note = f"{camera_prefix} the scene. "
            # Replace "Static wide shot" prefix in content_motion
            content_motion = re.sub(
                r"^Static wide shot\.\s*",
                "",
                content_motion,
            )

    parts = [
        verb_note,
        camera_note if camera_note else "",
        content_motion,
        "Data labels and text remain stable and legible throughout.",
        "Dark room background unchanged.",
        f"{clip_duration} seconds.",
        UNIVERSAL_RULES,
    ]

    # Filter empty parts and join
    prompt = " ".join(p for p in parts if p)
    # Clean up double spaces
    prompt = re.sub(r"\s{2,}", " ", prompt).strip()

    return prompt


def generate_prompts_for_segments(
    segments: list[dict],
    content_types: dict[int, str] | None = None,
    clip_duration: int = 10,
) -> list[dict]:
    """Generate animation prompts for all segments.

    Args:
        segments: List of segment dicts from segmentation engine.
            Each segment may have a "clip_duration" field (6 or 10) set
            dynamically based on narration length. If present, it overrides
            the global clip_duration parameter.
            Each segment may have a "text" field with sentence text for
            verb extraction (Rule 1).
        content_types: Optional mapping of segment index to content type string.
            When None, defaults to B_data_terminal for all segments.
        clip_duration: Default duration in seconds (6 or 10). Used only when
            a segment doesn't have its own clip_duration.

    Returns:
        List of dicts with segment index, clip_duration, camera_purpose,
        core_verb, and animation_prompt.
    """
    if content_types is None:
        content_types = {}

    results = []
    for seg in segments:
        idx = seg["index"]
        ct = content_types.get(idx, _DEFAULT_CONTENT_TYPE)
        seg_clip_duration = seg.get("clip_duration", clip_duration)
        prompt = generate_animation_prompt(seg, ct, seg_clip_duration)

        sentence_text = seg.get("text", "")
        results.append({
            "segment_index": idx,
            "intensity": seg.get("intensity", "low"),
            "clip_duration": seg_clip_duration,
            "animation_prompt": prompt,
            "camera_purpose": classify_camera_purpose(sentence_text),
            "core_verb": extract_core_verb(sentence_text),
        })
    return results
