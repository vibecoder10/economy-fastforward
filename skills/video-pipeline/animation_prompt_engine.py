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

import logging
import re
from typing import Callable, Awaitable, Optional

logger = logging.getLogger(__name__)


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
    re.compile(r"\b(turn(?:s|ed|ing)?\s+on)\b", re.IGNORECASE),
    re.compile(r"\b(turn(?:s|ed|ing)?\s+off)\b", re.IGNORECASE),
    re.compile(r"\b(kick(?:s|ed|ing)?\s+in)\b", re.IGNORECASE),
    re.compile(r"\b(pull(?:s|ed|ing)?\s+(?:back|away|out))\b", re.IGNORECASE),
    re.compile(r"\b(zero(?:s|ed|ing)?\s+(?:in|out))\b", re.IGNORECASE),
    re.compile(r"\b(cut(?:ting|s)?\s+off)\b", re.IGNORECASE),
    re.compile(r"\b(snap(?:s|ped|ping)?\s+(?:shut|open|back))\b", re.IGNORECASE),
    re.compile(r"\b(open(?:s|ed|ing)?\s+up)\b", re.IGNORECASE),
    re.compile(r"\b(peel(?:s|ed|ing)?\s+(?:back|away))\b", re.IGNORECASE),
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


# Common words that look verb-like but aren't (prepositions, adverbs, nouns)
_NON_VERB_WORDS = frozenset({
    "the", "and", "but", "for", "not", "its", "this", "that", "these",
    "those", "their", "them", "his", "her", "from", "with", "into",
    "across", "between", "after", "before", "about", "against", "over",
    "under", "every", "each", "most", "more", "less", "other", "another",
    "some", "all", "many", "much", "behind", "around", "along", "among",
    "during", "through", "within", "without", "toward", "towards",
    "beside", "besides", "beyond", "despite", "until", "unless",
    "since", "while", "where", "when", "then", "than", "thus",
    "hence", "once", "twice", "here", "there", "never", "ever",
    "often", "always", "already", "also", "just", "still", "even",
    "only", "very", "quite", "rather", "really", "almost", "enough",
    "indeed", "perhaps", "maybe", "however", "although", "because",
    "three", "thousand", "hundred", "million", "billion",
    "real", "closed", "doors", "designed", "hardened",
    "money", "printer", "missiles", "bunkers", "launchers",
    "numbers", "troop", "tanks",
})


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

    # Fallback: only accept words ending in verb-like suffixes (-ing, -ed, -es)
    # to avoid catching prepositions, adverbs, and nouns.
    # We require the -ing/-ed/-es suffix to be confident it's actually a verb form.
    words = re.findall(r"\b([a-z]+(?:ing|ed|es))\b", sentence_text.lower())
    for word in words:
        base = re.sub(r"(ing|ed|es)$", "", word)
        if len(base) >= 3 and word not in _STOP_VERBS and base not in _STOP_VERBS:
            if word not in _NON_VERB_WORDS:
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
    re.compile(r"\b(?:pan (?:left|right|across)|lateral[- ]pan|tracking shot)\b", re.IGNORECASE),
    re.compile(r"\b(?:tilt (?:up|down)|crane (?:up|down))\b", re.IGNORECASE),
    re.compile(r"\b(?:snap zoom|crash zoom|fast push)\b", re.IGNORECASE),
    re.compile(r"\b(?:orbit(?:al|s|ing)?|rotat(?:e[sd]?|ing|ion))\b", re.IGNORECASE),
    re.compile(r"\b(?:punch(?:es|ed|ing)?\s+(?:forward|in|out|through))\b", re.IGNORECASE),
    re.compile(r"\bcamera\s+(?:drift(?:s|ing)?|mov(?:es?|ing)|sweep(?:s|ing)?)\b", re.IGNORECASE),
]

# Split on clause boundaries: punctuation, conjunctions, em-dashes, "as", "then", "while"
_ACTION_CLAUSE_SPLIT = re.compile(
    r"[.;]\s+"                      # Period or semicolon + space
    r"|,\s+(?:and\s+|then\s+|as\s+|while\s+|but\s+)?"  # Comma (optionally + conjunction)
    r"|(?<=[a-z])\s+(?:as|then|while)\s+(?=[a-z])"      # Mid-sentence conjunctions
    r"|\s*—\s*"                     # Em-dash
    r"|\s*--\s*"                    # Double-hyphen as em-dash
    r"|\s+(?:and then|and)\s+(?=[a-z])",                 # "and then" / "and" between clauses
    re.IGNORECASE,
)

# Subject action verbs for element counting (broader than _ACTION_VERB_PATTERN)
_ELEMENT_COUNT_VERBS = re.compile(
    r"\b(?:"
    r"extinguish|dissolve|spread|multiply|freeze|lock|snap|sever|cascade|ripple|"
    r"collapse|explode|shatter|surge|spike|plunge|drain|flood|ignite|crack|tear|"
    r"burn|melt|assemble|materialize|illuminate|activate|deactivate|"
    r"draw|scroll|appear|flash|slam|drop|retract|expand|contract|accelerate|"
    r"decelerate|pulse|flicker|shimmer|glow|flare|"
    r"snapping|completing|continuing|accelerating|"
    r"break|sever|detach|fragment|scatter|overwhelm|consume|override|"
    r"ignit|blaz|erupt|detonate|burst|swarm|converge|"
    # -s, -ed, -ing forms
    r"(?:extinguish|dissolv|spread|multipl|freez|lock|snap|sever|cascad|"
    r"collapse|explod|shatter|surg|spike|plung|drain|flood|ignit|crack|tear|"
    r"burn|melt|assembl|materializ|illuminat|activat|deactivat|"
    r"draw|scroll|appear|flash|slam|drop|retract|expand|contract|accelerat|"
    r"decelerat|puls|flicker|shimmer|glow|flar|"
    r"break|sever|detach|fragment|scatter|overwhelm|consum|overrid|"
    r"blaz|erupt|detonat|burst|swarm|converg"
    r")(?:e[sd]?|s|ing|ed)"
    r")\b",
    re.IGNORECASE,
)


# Words that signal a new subject (articles, pronouns, demonstratives).
# If a clause after "and" starts with one of these + a noun, it's a new
# subject and counts as a separate action. If the clause starts with a
# bare verb, it shares the previous subject → compound verb → 1 action.
_SUBJECT_STARTERS = re.compile(
    r"^(?:the|a|an|its|their|his|her|our|my|your|this|that|these|those|"
    r"all|each|every|some|no|any|another|other|"
    r"[A-Z][a-z]"  # Capitalized noun (proper noun or sentence start)
    r")\s",
    re.IGNORECASE,
)


def _is_compound_verb_clause(clause: str) -> bool:
    """Check if a clause is a bare verb phrase sharing the previous subject.

    "dissolve into fragments" → True (bare verb, shares previous subject)
    "the display dissolves" → False (has its own subject "the display")
    "alarms begin pulsing" → False (has its own subject "alarms")
    """
    clause = clause.strip()
    if not clause:
        return False
    # If it starts with a subject starter (article/pronoun/demonstrative + noun),
    # it has its own subject → not a compound verb
    if _SUBJECT_STARTERS.match(clause):
        return False
    # If the first word IS an action verb (or verb form), it's a bare verb
    # sharing the previous subject
    first_word = clause.split()[0] if clause.split() else ""
    if _ELEMENT_COUNT_VERBS.match(first_word):
        return True
    return False


def count_animated_elements(prompt: str) -> int:
    """Count the number of distinct animated elements in an animation prompt.

    Counts each distinct camera motion + each distinct subject action.
    A prompt should have at most 2 animated elements per Rule 3.

    Compound verbs sharing a subject ("snap and dissolve") count as ONE
    action, not two. A clause after "and" that starts with a bare verb
    (no new subject) is merged with the previous action.
    """
    if not prompt:
        return 0

    # Count ALL camera motions (each distinct camera motion = 1 element)
    camera_count = 0
    for pattern in _ANIMATION_ACTION_PATTERNS:
        camera_count += len(pattern.findall(prompt))

    # Split into clauses on conjunctions, em-dashes, semicolons, etc.
    clauses = _ACTION_CLAUSE_SPLIT.split(prompt)

    # Count subject actions, merging compound verbs on the same subject
    subject_actions = 0
    prev_was_subject_action = False
    for clause in clauses:
        clause_stripped = clause.strip()
        if not clause_stripped:
            continue
        # Skip clauses that are purely camera descriptions (short + camera pattern)
        is_camera_clause = (
            any(p.search(clause_stripped) for p in _ANIMATION_ACTION_PATTERNS)
            and len(clause_stripped.split()) < 8
        )
        if is_camera_clause:
            prev_was_subject_action = False
            continue
        # Check for subject action verbs
        if _ELEMENT_COUNT_VERBS.search(clause_stripped):
            # If this clause is a bare verb sharing the previous subject,
            # don't count it as a new action
            if prev_was_subject_action and _is_compound_verb_clause(clause_stripped):
                continue  # compound verb — already counted with previous
            subject_actions += 1
            prev_was_subject_action = True
        else:
            prev_was_subject_action = False

    total = camera_count + subject_actions
    return max(total, 1) if prompt.strip() else 0


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

# ---------------------------------------------------------------------------
# Verb-to-motion mapping — Rule 1: the verb IS the animation
# ---------------------------------------------------------------------------
# Maps extracted verbs (or verb categories) to concrete motion descriptions
# that literally enact the verb. When a verb matches, this REPLACES the
# generic content-type template motion, ensuring the animation is driven
# by what the sentence says, not by what content type the image happens to be.
# ---------------------------------------------------------------------------

_VERB_MOTION_MAP: dict[str, str] = {
    # Phrasal verbs
    "going dark": "Lights and indicator points extinguish one by one across the display until the screen is nearly black.",
    "shutting down": "Systems deactivate in sequence — screens go black, indicators flatline, power drains from the edges inward.",
    "shut down": "Systems deactivate in sequence — screens go black, indicators flatline, power drains from the edges inward.",
    "turning on": "Elements activate in rapid sequence — displays ignite, numbers spin up from zero, power surges outward from center.",
    "turned on": "Elements activate in rapid sequence — displays ignite, numbers spin up from zero, power surges outward from center.",
    "turn on": "Elements activate in rapid sequence — displays ignite, numbers spin up from zero, power surges outward from center.",
    "breaking apart": "Structure fractures along stress lines, sections separate and drift apart, fragments dissolve at the edges.",
    "falling apart": "Components detach and drift downward, connections sever, pieces separate and scatter.",
    "don't matter": "Asset icons dissolve to static noise, then fade to blank one by one.",
    "wiped out": "Elements are erased in a sweep from one side to the other, leaving empty black space.",
    "spread across": "A single point multiplies and dots spread outward across the surface in all directions.",
    "spreading across": "A single point multiplies and dots spread outward across the surface in all directions.",
    "blown up": "Central element detonates outward — fragments scatter radially, shockwave ripples through surrounding data.",
    "blowing up": "Central element detonates outward — fragments scatter radially, shockwave ripples through surrounding data.",
    "locks frozen": "Number or counter stops mid-increment and holds completely still, all motion ceases.",
    "locked in": "Elements snap into fixed positions and hold rigid, all motion ceases.",
    "piling up": "Items stack vertically, each new element landing on top of the last with increasing speed.",
    "turned off": "Displays go dark in sequence, indicators flatline, ambient light drains to black.",
    "kicked in": "Elements slam into active state — numbers jump, indicators spike, displays flash to life.",
    "cut off": "Connection lines sever sharply, separated sections drift apart, data flow stops.",
    "cutting off": "Connection lines sever sharply, separated sections drift apart, data flow stops.",

    # Single-word verbs
    "scattered": "A single dot multiplies and spreads across the terrain, points appearing in dispersed positions.",
    "scattering": "A single dot multiplies and spreads across the terrain, points appearing in dispersed positions.",
    "scatter": "A single dot multiplies and spreads across the terrain, points appearing in dispersed positions.",
    "collapsed": "Structure buckles inward, data lines flatline, elements compress and go dark from the edges.",
    "collapsing": "Structure buckles inward, data lines flatline, elements compress and go dark from the edges.",
    "collapse": "Structure buckles inward, data lines flatline, elements compress and go dark from the edges.",
    "collapses": "Structure buckles inward, data lines flatline, elements compress and go dark from the edges.",
    "surging": "Values spike upward violently, chart line rockets past thresholds, warning indicators flood on.",
    "surge": "Values spike upward violently, chart line rockets past thresholds, warning indicators flood on.",
    "surges": "Values spike upward violently, chart line rockets past thresholds, warning indicators flood on.",
    "surged": "Values spike upward violently, chart line rockets past thresholds, warning indicators flood on.",
    "frozen": "All motion ceases — counter stops mid-digit, indicators freeze in place, complete stillness.",
    "freeze": "All motion ceases — counter stops mid-digit, indicators freeze in place, complete stillness.",
    "freezes": "All motion ceases — counter stops mid-digit, indicators freeze in place, complete stillness.",
    "exploded": "Central element detonates outward, shockwave ripples through surrounding elements, fragments scatter.",
    "explodes": "Central element detonates outward, shockwave ripples through surrounding elements, fragments scatter.",
    "exploding": "Central element detonates outward, shockwave ripples through surrounding elements, fragments scatter.",
    "dissolved": "Elements lose opacity and fade to nothing, leaving empty space where data once was.",
    "dissolving": "Elements lose opacity and fade to nothing, leaving empty space where data once was.",
    "dissolves": "Elements lose opacity and fade to nothing, leaving empty space where data once was.",
    "cascading": "Effect triggers from one element to the next in rapid sequence, each activation triggering the next.",
    "cascade": "Effect triggers from one element to the next in rapid sequence, each activation triggering the next.",
    "cascades": "Effect triggers from one element to the next in rapid sequence, each activation triggering the next.",
    "flooding": "Data or color washes across the display in a wave, overwhelming existing elements.",
    "floods": "Data or color washes across the display in a wave, overwhelming existing elements.",
    "flooded": "Data or color washes across the display in a wave, overwhelming existing elements.",
    "draining": "Values count down, levels drop, elements empty from top to bottom.",
    "drains": "Values count down, levels drop, elements empty from top to bottom.",
    "drained": "Values count down, levels drop, elements empty from top to bottom.",
    "shattering": "Element fractures into angular fragments that scatter outward, cracks propagate through the structure.",
    "shatters": "Element fractures into angular fragments that scatter outward, cracks propagate through the structure.",
    "shattered": "Element fractures into angular fragments that scatter outward, cracks propagate through the structure.",
    "accelerating": "Motion speeds up — elements move faster, numbers increment more rapidly, pace builds.",
    "accelerates": "Motion speeds up — elements move faster, numbers increment more rapidly, pace builds.",
    "multiplying": "Elements duplicate — one becomes two, two becomes four, copies spread outward.",
    "multiply": "Elements duplicate — one becomes two, two becomes four, copies spread outward.",
    "ignited": "Element blazes to life — light erupts, color saturates, energy radiates outward.",
    "ignites": "Element blazes to life — light erupts, color saturates, energy radiates outward.",
    "extinguished": "Light dies — element dims to black, glow fades, surrounding area darkens.",
    "extinguishes": "Light dies — element dims to black, glow fades, surrounding area darkens.",
    "severed": "Connection line snaps apart cleanly, separated ends recoil, data flow between nodes stops.",
    "severs": "Connection line snaps apart cleanly, separated ends recoil, data flow between nodes stops.",
    "snapped": "Element breaks with sudden force, fragments fly apart, sharp discontinuity appears.",
    "snaps": "Element breaks with sudden force, fragments fly apart, sharp discontinuity appears.",
    "overwhelmed": "Dominant element grows to fill the frame, pushing all other elements to the margins.",
    "overwhelms": "Dominant element grows to fill the frame, pushing all other elements to the margins.",
    "spreading": "Effect or mark expands outward from its origin point, covering more area with each moment.",
    "spreads": "Effect or mark expands outward from its origin point, covering more area with each moment.",
    "rising": "Elements lift upward — values climb, chart lines ascend, indicators move toward the top of frame.",
    "rises": "Elements lift upward — values climb, chart lines ascend, indicators move toward the top of frame.",
    "sinking": "Elements descend — values drop, chart lines fall, indicators move toward the bottom of frame.",
    "sinks": "Elements descend — values drop, chart lines fall, indicators toward the bottom of frame.",
    "burning": "Element glows hot, edges char and curl, material consumed from the outside in.",
    "burns": "Element glows hot, edges char and curl, material consumed from the outside in.",
    "melting": "Structure loses rigidity, edges soften and drip downward, form distorts and pools.",
    "melts": "Structure loses rigidity, edges soften and drip downward, form distorts and pools.",
    "tearing": "Material rips apart along a line, edges fray, separated halves pull away from each other.",
    "tears": "Material rips apart along a line, edges fray, separated halves pull away from each other.",
    "cracking": "Fracture lines propagate across the surface, spreading from impact point outward.",
    "cracks": "Fracture lines propagate across the surface, spreading from impact point outward.",
    "expanding": "Element grows outward in all directions, boundaries push further, space fills.",
    "expands": "Element grows outward in all directions, boundaries push further, space fills.",
    "contracting": "Element shrinks inward from all edges, boundaries tighten, space compresses.",
    "contracts": "Element shrinks inward from all edges, boundaries tighten, space compresses.",
    "dropping": "Element falls from its position, descending through the frame with increasing speed.",
    "drops": "Element falls from its position, descending through the frame with increasing speed.",
    "spiking": "Value shoots upward sharply, chart line goes vertical, threshold indicators trip.",
    "spikes": "Value shoots upward sharply, chart line goes vertical, threshold indicators trip.",
    "plunging": "Value drops sharply downward, chart line nosedives, floor indicators trip.",
    "plunges": "Value drops sharply downward, chart line nosedives, floor indicators trip.",
}


# ---------------------------------------------------------------------------
# Claude Haiku fallback for unknown verbs — long tail coverage
# ---------------------------------------------------------------------------
# The _VERB_MOTION_MAP handles common verbs fast. For verbs not in the map,
# a single Claude Haiku call turns {verb + sentence} into a concrete motion.
# Cost: ~$0.001 per call. Results are cached per-video so repeat verbs are free.
# ---------------------------------------------------------------------------

_HAIKU_VERB_PROMPT = (
    "Given the sentence '{sentence}' and the action verb '{verb}', "
    "describe ONE concrete visual motion in under 20 words that literally "
    "enacts this verb on a holographic data display. No camera movement, "
    "no metaphors, no people. Just the physical motion."
)

# Per-run cache: verb -> motion description (avoids repeat API calls within one video)
_verb_motion_cache: dict[str, str] = {}

# Track total Haiku fallback calls for cost logging
_haiku_call_count: int = 0
_haiku_input_tokens: int = 0
_haiku_output_tokens: int = 0


def clear_verb_motion_cache() -> None:
    """Clear the per-run verb motion cache. Call between videos."""
    global _haiku_call_count, _haiku_input_tokens, _haiku_output_tokens
    _verb_motion_cache.clear()
    _haiku_call_count = 0
    _haiku_input_tokens = 0
    _haiku_output_tokens = 0


def get_verb_motion_cache_stats() -> dict:
    """Return stats on Haiku fallback usage for cost logging."""
    return {
        "cache_size": len(_verb_motion_cache),
        "haiku_calls": _haiku_call_count,
        "haiku_input_tokens": _haiku_input_tokens,
        "haiku_output_tokens": _haiku_output_tokens,
        "estimated_cost_usd": round(_haiku_call_count * 0.001, 4),
    }


async def resolve_verb_motion_async(
    verb: str,
    sentence_text: str,
    anthropic_client: Optional[object] = None,
) -> str:
    """Resolve a verb to a motion description, using Claude Haiku for unknown verbs.

    Lookup order:
    1. _VERB_MOTION_MAP (instant, free)
    2. _verb_motion_cache (instant, previously resolved)
    3. Claude Haiku API call (async, ~$0.001)

    Args:
        verb: The extracted verb from sentence text.
        sentence_text: Full sentence for context.
        anthropic_client: An AnthropicClient instance with a generate() method.
            If None, falls back to empty string (no API call).

    Returns:
        A concrete motion description string, or empty string if resolution fails.
    """
    global _haiku_call_count, _haiku_input_tokens, _haiku_output_tokens

    if not verb:
        return ""

    # 1. Check static map
    motion = _VERB_MOTION_MAP.get(verb, "")
    if motion:
        return motion

    # 2. Check per-run cache
    if verb in _verb_motion_cache:
        return _verb_motion_cache[verb]

    # 3. Claude Haiku fallback
    if anthropic_client is None:
        logger.debug("No anthropic_client provided, skipping Haiku fallback for verb '%s'", verb)
        return ""

    try:
        prompt = _HAIKU_VERB_PROMPT.format(sentence=sentence_text, verb=verb)
        response = await anthropic_client.generate(
            prompt=prompt,
            system_prompt="You describe visual motion for holographic data displays. Return ONLY the motion description, nothing else.",
            model="claude-haiku-4-5-20251001",
            max_tokens=60,
            temperature=0.3,
        )
        motion = response.strip().rstrip(".")  + "."
        # Cache for this run
        _verb_motion_cache[verb] = motion
        _haiku_call_count += 1
        # Rough token estimate for cost tracking
        _haiku_input_tokens += len(prompt.split()) + 20  # ~system prompt
        _haiku_output_tokens += len(motion.split())
        logger.info(
            "Haiku verb fallback: '%s' -> '%s' (call #%d, ~$%.4f total)",
            verb, motion, _haiku_call_count, _haiku_call_count * 0.001,
        )
        return motion
    except Exception as e:
        logger.warning("Haiku verb fallback failed for '%s': %s", verb, e)
        return ""


# ---------------------------------------------------------------------------
# Verbless streak detection — quality warning
# ---------------------------------------------------------------------------
# When 3+ consecutive clips extract no verb, it means the script isn't
# giving the engine enough action language. Log a warning and return
# the streak info so callers can notify via Slack.
# ---------------------------------------------------------------------------

VERBLESS_STREAK_THRESHOLD = 3


def detect_verbless_streaks(
    results: list[dict],
) -> list[dict]:
    """Find runs of 3+ consecutive clips with no extracted verb.

    Args:
        results: Output of generate_prompts_for_segments.

    Returns:
        List of dicts with "start_index", "end_index", "length" for each streak.
    """
    streaks: list[dict] = []
    streak_start: int | None = None
    streak_len = 0

    for r in results:
        if not r.get("core_verb"):
            if streak_start is None:
                streak_start = r["segment_index"]
            streak_len += 1
        else:
            if streak_len >= VERBLESS_STREAK_THRESHOLD and streak_start is not None:
                streaks.append({
                    "start_index": streak_start,
                    "end_index": r["segment_index"] - 1,
                    "length": streak_len,
                })
            streak_start = None
            streak_len = 0

    # Handle streak at end of results
    if streak_len >= VERBLESS_STREAK_THRESHOLD and streak_start is not None:
        last_idx = results[-1]["segment_index"] if results else 0
        streaks.append({
            "start_index": streak_start,
            "end_index": last_idx,
            "length": streak_len,
        })

    return streaks


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

    # Rule 1: Extract verb and use verb-driven motion if available
    verb = extract_core_verb(sentence_text)
    verb_motion = _VERB_MOTION_MAP.get(verb, "") if verb else ""

    if verb_motion:
        # Verb-driven motion REPLACES the generic content-type template.
        # The verb IS the animation — the template is just the fallback.
        content_motion = f"Static wide shot. {verb_motion}"

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
    """Generate animation prompts for all segments (sync, map-only).

    Uses only _VERB_MOTION_MAP for verb resolution. For Claude Haiku fallback
    on unknown verbs, use generate_prompts_for_segments_async() instead.

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
        core_verb, verb_source, and animation_prompt.
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
        verb = extract_core_verb(sentence_text)
        verb_source = "map" if (verb and verb in _VERB_MOTION_MAP) else ("extracted" if verb else "none")
        results.append({
            "segment_index": idx,
            "intensity": seg.get("intensity", "low"),
            "clip_duration": seg_clip_duration,
            "animation_prompt": prompt,
            "camera_purpose": classify_camera_purpose(sentence_text),
            "core_verb": verb,
            "verb_source": verb_source,
        })
    return results


async def generate_prompts_for_segments_async(
    segments: list[dict],
    content_types: dict[int, str] | None = None,
    clip_duration: int = 10,
    anthropic_client: Optional[object] = None,
) -> tuple[list[dict], list[dict]]:
    """Generate animation prompts with Claude Haiku fallback for unknown verbs.

    Like generate_prompts_for_segments but resolves unknown verbs via a single
    Claude Haiku API call (~$0.001 each). Results are cached per-run so
    the same verb doesn't trigger multiple calls.

    Call clear_verb_motion_cache() between videos to reset the cache.

    Args:
        segments: Segment dicts (see generate_prompts_for_segments).
        content_types: Content type mapping (see generate_prompts_for_segments).
        clip_duration: Default clip duration.
        anthropic_client: AnthropicClient instance for Haiku fallback.

    Returns:
        Tuple of (results, verbless_streaks).
        results: List of prompt dicts (same as sync version + verb_source field).
        verbless_streaks: List of streaks where 3+ clips had no verb.
    """
    if content_types is None:
        content_types = {}

    results = []
    for seg in segments:
        idx = seg["index"]
        ct = content_types.get(idx, _DEFAULT_CONTENT_TYPE)
        seg_clip_duration = seg.get("clip_duration", clip_duration)
        sentence_text = seg.get("text", "")

        # Extract verb
        verb = extract_core_verb(sentence_text)

        # Check if verb has a map entry
        verb_motion = _VERB_MOTION_MAP.get(verb, "") if verb else ""
        verb_source = "none"

        if verb and not verb_motion:
            # Verb extracted but not in map — try Haiku fallback
            verb_motion = await resolve_verb_motion_async(
                verb, sentence_text, anthropic_client
            )
            if verb_motion:
                verb_source = "haiku"
            else:
                verb_source = "extracted"
        elif verb_motion:
            verb_source = "map"

        # Generate the prompt (will use map if verb is in _VERB_MOTION_MAP)
        prompt = generate_animation_prompt(seg, ct, seg_clip_duration)

        # If Haiku resolved a motion not in the map, patch the prompt
        if verb_source == "haiku" and verb_motion:
            # Replace the generic template motion with Haiku's motion
            prompt = _patch_prompt_with_verb_motion(prompt, verb_motion)

        results.append({
            "segment_index": idx,
            "intensity": seg.get("intensity", "low"),
            "clip_duration": seg_clip_duration,
            "animation_prompt": prompt,
            "camera_purpose": classify_camera_purpose(sentence_text),
            "core_verb": verb,
            "verb_source": verb_source,
        })

    # Detect verbless streaks
    streaks = detect_verbless_streaks(results)
    if streaks:
        for streak in streaks:
            logger.warning(
                "VERBLESS STREAK: %d consecutive clips (segments %d-%d) extracted "
                "no action verb. Script may need stronger action language.",
                streak["length"], streak["start_index"], streak["end_index"],
            )

    # Log cache stats
    stats = get_verb_motion_cache_stats()
    if stats["haiku_calls"] > 0:
        logger.info(
            "Haiku verb fallback stats: %d calls, %d cached, ~$%.4f total cost",
            stats["haiku_calls"], stats["cache_size"], stats["estimated_cost_usd"],
        )

    return results, streaks


def _patch_prompt_with_verb_motion(prompt: str, verb_motion: str) -> str:
    """Replace the generic template motion in a prompt with a Haiku-resolved motion.

    Keeps the camera note (if any), boilerplate suffix, and universal rules.
    Only swaps the content-type template body.
    """
    # The prompt structure is:
    # [camera_note?] Static wide shot. [TEMPLATE MOTION]. [boilerplate]...
    # We want to replace [TEMPLATE MOTION] with verb_motion.

    # Find where the boilerplate starts
    boilerplate_marker = "Data labels and text remain stable"
    marker_pos = prompt.find(boilerplate_marker)
    if marker_pos < 0:
        return prompt

    prefix_part = prompt[:marker_pos].strip()
    suffix_part = prompt[marker_pos:]

    # In the prefix, keep any camera note and "Static wide shot." but replace the rest
    static_marker = "Static wide shot."
    static_pos = prefix_part.find(static_marker)
    if static_pos >= 0:
        camera_prefix = prefix_part[:static_pos + len(static_marker)]
        return f"{camera_prefix} {verb_motion} {suffix_part}"

    # If no static marker (camera was added), keep the camera note
    # and just replace everything after the first sentence
    first_period = prefix_part.find(". ")
    if first_period >= 0:
        camera_prefix = prefix_part[:first_period + 1]
        return f"{camera_prefix} {verb_motion} {suffix_part}"

    return prompt
