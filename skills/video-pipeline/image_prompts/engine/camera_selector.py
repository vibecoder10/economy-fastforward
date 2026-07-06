"""Camera Move Auto-Selector — picks the right move BEFORE the image is drawn.

Runs during the image-prompt step so the chosen move's ``image_setup`` can
shape the still image's composition, and the same move's ``motion_prompt``
later drives the animation prompt. One decision, both prompts.

Discipline: EARN THE MOVE. The camera is static by default (the existing
Rule 2). A move is only selected when the shot justifies it:
- classify_camera_purpose() says REVEAL / SCALE / ISOLATION, or
- the shot is a scene-opening wide (ESTABLISH), or
- the shot is a scene-final beat at high intensity (PAYOFF).
Everything else returns None → static shot, exactly like today.

Selection is deterministic scoring; an optional Claude tie-break fires only
when the top two candidates land within a threshold and a client is given.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Optional

from .camera_moves import (
    CAMERA_MOVES,
    CameraMove,
    PURPOSE_REVEAL,
    PURPOSE_SCALE,
    PURPOSE_ISOLATION,
    PURPOSE_ESTABLISH,
    PURPOSE_PAYOFF,
    SUBJECT_CHARACTER,
    SUBJECT_TWO_SUBJECTS,
    SUBJECT_ENVIRONMENT,
    SUBJECT_DATA,
    SUBJECT_OBJECT,
)

logger = logging.getLogger(__name__)

# Compositions that qualify a scene-opener as an establishing shot
_ESTABLISH_COMPOSITIONS = frozenset({
    "wide", "environmental", "overhead", "wide_establishing",
    "isometric_diorama", "overhead_map", "data_landscape",
})

# Narrative intensity → target move intensity (1-5 scale)
_INTENSITY_TARGET = {"low": 1, "medium": 3, "high": 4}

# Interior settings where aerial/drone moves are nonsense
import re as _re_mod
_INTERIOR_RE = _re_mod.compile(
    r"\b(?:room|interior|workshop|hall|hallway|kitchen|office|bedroom|"
    r"basement|attic|cabin|shop|store|classroom|library|lab|laboratory|"
    r"studio|garage|barn|church|temple|tavern|inn|corridor|chamber)\b",
    _re_mod.IGNORECASE,
)

# Tie-break threshold: top-two scores within this delta → ambiguous
TIE_THRESHOLD = 2

# How many recent move ids attract a variety penalty
_RECENT_WINDOW = 3


@dataclass
class ShotContext:
    """Everything the selector knows about one shot."""

    sentence_text: str = ""
    composition: str = "medium"        # wide/medium/closeup/environmental/portrait/overhead/low_angle
    subject_kind: str = ""             # SUBJECT_* value; inferred from text when blank
    intensity: str = "medium"          # low | medium | high (narrative intensity)
    is_scene_open: bool = False        # first shot of a scene
    is_scene_final: bool = False       # last shot of a scene
    is_video_open: bool = False        # very first shot of the video
    video_model: str = ""              # animation model id; blank = don't filter
    prev_move_ids: list = field(default_factory=list)      # recent selected move ids
    prev_legacy_keys: list = field(default_factory=list)   # recent legacy camera keys


@dataclass
class Selection:
    """The selector's full answer for one shot."""

    move: Optional[CameraMove]   # None = static shot
    purpose: str                 # why the camera moves (or "STATIC")
    score: float = 0.0
    reason: str = ""
    tie_broken: bool = False


# ---------------------------------------------------------------------------
# Subject-kind inference — light heuristics, caller can always override
# ---------------------------------------------------------------------------

import re as _re

_CHARACTER_WORDS = frozenset({
    "man", "men", "woman", "women", "boy", "girl", "child", "children",
    "kid", "kids", "person", "people", "he", "she", "they", "him",
    "his", "her", "their", "face", "hand", "hands", "character",
    "figure", "couple", "family", "crowd", "soldier", "worker",
    "farmer", "teacher", "doctor", "chef", "captain", "stranger",
})
_DATA_WORDS = frozenset({
    "chart", "graph", "display", "screen", "terminal", "dashboard",
    "map", "diagram", "timeline", "data", "number", "numbers",
    "percentage", "statistic", "statistics", "document", "hologram",
    "holographic", "interface",
})
_ENVIRONMENT_WORDS = frozenset({
    "landscape", "city", "town", "village", "forest", "mountain",
    "mountains", "ocean", "sea", "desert", "field", "fields", "valley",
    "skyline", "street", "streets", "horizon", "sky", "room", "hall",
    "building", "interior", "warehouse", "factory", "workshop",
})
_TWO_SUBJECT_HINTS = (
    "watches", "looks at", "stares at", "between them", "across from",
    "behind him", "behind her", "in the foreground", "in the background",
    "while the other", "over the shoulder", "shoulder of",
)


def infer_subject_kind(text: str) -> str:
    """Guess the shot's hero subject kind from its description text.

    Whole-word matching (not substrings — "the" must never match "he").
    Character wins over data/environment when both appear: a person in a
    place is a character shot.
    """
    t = text.lower()
    words = set(_re.findall(r"[a-z']+", t))
    has_character = bool(words & _CHARACTER_WORDS)
    if has_character and any(h in t for h in _TWO_SUBJECT_HINTS):
        return SUBJECT_TWO_SUBJECTS
    if has_character:
        return SUBJECT_CHARACTER
    if words & _DATA_WORDS:
        return SUBJECT_DATA
    if words & _ENVIRONMENT_WORDS:
        return SUBJECT_ENVIRONMENT
    return SUBJECT_OBJECT


# ---------------------------------------------------------------------------
# The earn-the-move gate
# ---------------------------------------------------------------------------

def resolve_purpose(ctx: ShotContext) -> str:
    """Decide whether this shot earns a camera move, and why.

    Order matters: an explicit narrative purpose (from the sentence) beats
    positional purposes; positional purposes only fire when the narrative
    is neutral. Returns "STATIC" when nothing earns the move.
    """
    from animation_prompt_engine import classify_camera_purpose, CAMERA_PURPOSE_STATIC

    purpose = classify_camera_purpose(ctx.sentence_text)
    if purpose != CAMERA_PURPOSE_STATIC:
        return purpose

    # Positional upgrade 1: scene-opening wide → ESTABLISH
    if (ctx.is_scene_open or ctx.is_video_open) and ctx.composition in _ESTABLISH_COMPOSITIONS:
        return PURPOSE_ESTABLISH

    # Positional upgrade 2: scene-final beat at high intensity → PAYOFF
    if ctx.is_scene_final and ctx.intensity == "high":
        return PURPOSE_PAYOFF

    return "STATIC"


# ---------------------------------------------------------------------------
# Deterministic scoring
# ---------------------------------------------------------------------------

def _stable_jitter(move_id: str, sentence: str) -> float:
    """Tiny deterministic tiebreaker (0..0.99) so exact-tie siblings
    (pan_left vs pan_right) vary across shots without randomness."""
    h = hashlib.md5(f"{move_id}|{sentence}".encode()).hexdigest()
    return int(h[:4], 16) / 65535.0

def score_move(move: CameraMove, ctx: ShotContext, purpose: str) -> float:
    """Score one candidate move for this shot. Higher = better fit."""
    if purpose not in move.best_for:
        return float("-inf")

    # Model support is a hard filter when we know the model
    if ctx.video_model and ctx.video_model not in move.model_support:
        return float("-inf")

    # Anti-repeat: same legacy camera key as the immediately previous move
    # is a hard exclude (mirrors the existing consecutive-camera rule).
    # A "static" previous shot resets the rule — anything may follow a
    # static frame, including rack_focus whose legacy key is "static".
    if ctx.prev_legacy_keys:
        prev_key = ctx.prev_legacy_keys[-1]
        if prev_key != "static" and move.legacy_key == prev_key:
            return float("-inf")

    score = 10.0  # serves the purpose

    # Subject fit
    subject = ctx.subject_kind or infer_subject_kind(ctx.sentence_text)
    if subject in move.subject_fit:
        score += 6.0
    else:
        score -= 8.0

    # Intensity match: move aggression should track narrative intensity
    target = _INTENSITY_TARGET.get(ctx.intensity, 3)
    score -= abs(move.intensity - target) * 2.0

    # Variety: recently used moves get nudged down (not excluded)
    recent = ctx.prev_move_ids[-_RECENT_WINDOW:]
    if move.id in recent:
        score -= 5.0

    # Composition nudges: aerial/crane families want wide framings
    if move.category == "drone_crane" and ctx.composition in ("closeup", "close_up_vignette", "portrait"):
        score -= 6.0
    # Aerial moves make no sense indoors
    if move.category == "drone_crane" and _INTERIOR_RE.search(ctx.sentence_text or ""):
        score -= 8.0
    if move.id in ("slow_zoom_in", "crash_zoom_in", "fast_zoom_in") and ctx.composition in ("wide", "wide_establishing"):
        score -= 2.0  # zooming in from a wide covers too much ground in 6s

    score += _stable_jitter(move.id, ctx.sentence_text)
    return score


def rank_moves(ctx: ShotContext, purpose: str) -> list[tuple[float, CameraMove]]:
    """All viable candidates for this shot, best first."""
    scored = []
    for move in CAMERA_MOVES.values():
        s = score_move(move, ctx, purpose)
        if s != float("-inf"):
            scored.append((s, move))
    scored.sort(key=lambda t: (-t[0], t[1].id))
    return scored


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def select_camera_move(ctx: ShotContext) -> Selection:
    """Deterministic selection. Returns Selection(move=None) for static."""
    purpose = resolve_purpose(ctx)
    if purpose == "STATIC":
        return Selection(move=None, purpose="STATIC", reason="shot does not earn a camera move")

    ranked = rank_moves(ctx, purpose)
    if not ranked:
        return Selection(move=None, purpose=purpose,
                         reason=f"purpose {purpose} earned but no catalog move fits")

    best_score, best = ranked[0]
    return Selection(
        move=best, purpose=purpose, score=best_score,
        reason=f"{purpose}: best fit for {ctx.subject_kind or infer_subject_kind(ctx.sentence_text)} "
               f"at {ctx.intensity} intensity",
    )


# Per-run tie-break cache: (purpose, subject, top-two ids) -> winning move id
_tiebreak_cache: dict[tuple, str] = {}


def clear_tiebreak_cache() -> None:
    """Clear the per-run tie-break cache. Call between videos."""
    _tiebreak_cache.clear()


async def select_camera_move_async(
    ctx: ShotContext,
    anthropic_client: Optional[object] = None,
) -> Selection:
    """Selection with an optional Claude tie-break on genuinely close calls.

    Identical to select_camera_move() unless the top two candidates score
    within TIE_THRESHOLD and a client is provided — then one short, cached
    Haiku call picks between them. Any failure falls back to deterministic.
    """
    purpose = resolve_purpose(ctx)
    if purpose == "STATIC":
        return Selection(move=None, purpose="STATIC", reason="shot does not earn a camera move")

    ranked = rank_moves(ctx, purpose)
    if not ranked:
        return Selection(move=None, purpose=purpose,
                         reason=f"purpose {purpose} earned but no catalog move fits")

    best_score, best = ranked[0]
    subject = ctx.subject_kind or infer_subject_kind(ctx.sentence_text)

    is_tie = len(ranked) >= 2 and (best_score - ranked[1][0]) < TIE_THRESHOLD
    if is_tie and anthropic_client is not None:
        second = ranked[1][1]
        cache_key = (purpose, subject, best.id, second.id)
        winner_id = _tiebreak_cache.get(cache_key)

        if winner_id is None:
            try:
                from orchestrator.pipeline_constants import Models
                answer = await anthropic_client.generate(
                    prompt=(
                        f'Shot narration: "{ctx.sentence_text}"\n'
                        f"Camera purpose: {purpose}. Subject: {subject}. "
                        f"Intensity: {ctx.intensity}. Framing: {ctx.composition}.\n\n"
                        f"Option A — {best.name}: {best.motion_prompt}\n"
                        f"Option B — {second.name}: {second.motion_prompt}\n\n"
                        "Which camera move better serves this exact narration beat? "
                        "Answer with exactly one letter: A or B."
                    ),
                    system_prompt="You are a film cinematographer choosing between two camera moves. Answer A or B only.",
                    model=Models.CLAUDE_HAIKU,
                    max_tokens=4,
                    temperature=0.0,
                )
                winner_id = second.id if "B" in (answer or "").strip().upper()[:2] else best.id
                _tiebreak_cache[cache_key] = winner_id
            except Exception as e:
                logger.warning("Camera tie-break failed, using deterministic pick: %s", e)
                winner_id = best.id

        if winner_id == second.id:
            return Selection(
                move=second, purpose=purpose, score=ranked[1][0], tie_broken=True,
                reason=f"{purpose}: Claude tie-break picked {second.name} over {best.name}",
            )
        return Selection(
            move=best, purpose=purpose, score=best_score, tie_broken=True,
            reason=f"{purpose}: Claude tie-break confirmed {best.name}",
        )

    return Selection(
        move=best, purpose=purpose, score=best_score,
        reason=f"{purpose}: best fit for {subject} at {ctx.intensity} intensity",
    )
