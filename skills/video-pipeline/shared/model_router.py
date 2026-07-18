"""Per-shot video-model router (checklist §1.2/C12, tasks/storyengine-wiring-fix-checklist.md).

Maps a shot's narrative intent — the camera purpose already computed by
``image_prompts.engine.camera_selector.select_camera_move()``/``resolve_purpose()``
(REVEAL / ESTABLISH / PAYOFF / SCALE / ISOLATION / STATIC) — to a video
generation model, using ONLY the decision-table fields C11 added to
``shared.channel_profile.MODEL_REGISTRY`` entries (``best_for`` / ``tier`` /
``wired``). This module holds no second list of model capabilities: it is a
pure lookup over that registry, so adding/removing/re-tagging a model in
channel_profile.py is picked up automatically, with no edit needed here.

Called at SHOT-PLAN time (storyboard/coverage.py's ``plan_camera_moves()``,
before any frame is drawn) to compute a recommendation that rides the shot
dict into the ``assets`` table's ``routed_model``/``routing_reason``
columns (migration 088). Data + recommendation only — clip generation does
not read ``routed_model`` yet (that's C13); there is no UI for it yet
(C14).

Guarantees:
  - Only ever returns a WIRED model id (``ModelProfile.wired is True``).
  - Always returns a ``routing_reason`` a user could read.
  - Never raises for a recognized OR unrecognized purpose string — the
    worst case is the "default" fallback, never an exception. (Callers at
    the shot-plan write site still wrap the call in their own try/except
    per the fail-soft requirement — this module simply tries hard not to
    need it.)
"""
from __future__ import annotations

from dataclasses import dataclass

from shared.channel_profile import MODEL_REGISTRY, DEFAULT_VIDEO_MODEL

# Camera purpose -> the single best_for tag that purpose "earns", tried in
# this priority order. A purpose not listed here (including "STATIC", the
# camera engine's own "no move earned" value) falls through to the "draft"
# tag below — the same cheap-iteration tier the pipeline already defaults
# to when nothing routes it elsewhere.
_PURPOSE_TAG: dict[str, str] = {
    # Gap-analysis routing table (docs/reports/2026-07-17-higgsfield-vs-
    # storyengine-gap-analysis.md ~line 85): "Veo Quality = hero/final
    # shots" — a scene's reveal or its final payoff beat is exactly that.
    "REVEAL": "hero",
    "PAYOFF": "hero",
    # "Veo Fast = atmospheric/outdoor b-roll" — an establishing wide sets
    # mood/space rather than driving character action.
    "ESTABLISH": "atmospheric",
    "SCALE": "broll",
    "ISOLATION": "broll",
}

# A scene planned as a multi-shot sequence (several angles that must hold
# together across cuts, not a one-off) earns Seedance's "multi_shot" tag
# ahead of the purpose-based tag above. No shot-plan-time caller passes
# this yet (C12 wires purpose only) — it exists so a future caller (a
# scene-level "this is a continuous multi-angle sequence" signal) has a
# tested, ready lookup instead of a second hand-rolled mapping.
_MULTI_SHOT_TAG = "multi_shot"

_PURPOSE_LABEL: dict[str, str] = {
    "REVEAL": "reveal", "PAYOFF": "payoff", "ESTABLISH": "establish",
    "SCALE": "scale", "ISOLATION": "isolation", "STATIC": "ordinary",
}


@dataclass(frozen=True)
class RoutingDecision:
    model_id: str
    routing_reason: str


def _wired_models() -> dict:
    """Wired registry entries, in MODEL_REGISTRY's own (insertion) order —
    the deterministic tie-break when more than one wired model carries the
    same best_for tag."""
    return {mid: p for mid, p in MODEL_REGISTRY.items() if p.wired}


def _first_wired_with_tag(tag: str):
    for mid, profile in _wired_models().items():
        if tag in profile.best_for:
            return mid, profile
    return None


def route_shot_model(purpose: str | None, is_multi_shot: bool = False) -> RoutingDecision:
    """Pick a video model + a human-readable reason for one shot.

    ``purpose`` is whatever camera_selector's resolve_purpose()/
    select_camera_move() returned for this shot: REVEAL, ESTABLISH,
    PAYOFF, SCALE, ISOLATION, or STATIC (no camera-move purpose earned).
    Anything falsy/unrecognized is treated like STATIC. ``is_multi_shot``
    is an optional forward-looking hint (see _MULTI_SHOT_TAG above) — no
    current caller sets it True.

    Only ever returns a wired model_id. Falls back to DEFAULT_VIDEO_MODEL
    with reason "default" if, somehow, no wired model carries even the
    "draft" tag (belt-and-braces — today's registry always does).
    """
    purpose = (purpose or "STATIC").upper()
    label = _PURPOSE_LABEL.get(purpose, purpose.lower() or "ordinary")

    if is_multi_shot:
        hit = _first_wired_with_tag(_MULTI_SHOT_TAG)
        if hit:
            mid, profile = hit
            return RoutingDecision(
                mid, f"multi-shot sequence → {_MULTI_SHOT_TAG} tier ({profile.tier})")

    tag = _PURPOSE_TAG.get(purpose)
    if tag:
        hit = _first_wired_with_tag(tag)
        if hit:
            mid, profile = hit
            return RoutingDecision(mid, f"{label} scene → {tag} tier ({profile.tier})")

    # STATIC, unrecognized, or the earned tag has no wired match: the same
    # cheap-iteration tier the pipeline already defaults to.
    hit = _first_wired_with_tag("draft")
    if hit:
        mid, profile = hit
        return RoutingDecision(mid, f"{label} scene → draft tier ({profile.tier})")

    return RoutingDecision(DEFAULT_VIDEO_MODEL, "default")
