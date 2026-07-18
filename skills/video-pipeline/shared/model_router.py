"""Per-shot video-model router (checklist §1.2/C12, §C13b, tasks/storyengine-wiring-fix-checklist.md).

Maps a shot's narrative intent — the camera purpose already computed by
``image_prompts.engine.camera_selector.select_camera_move()``/``resolve_purpose()``
(REVEAL / ESTABLISH / PAYOFF / SCALE / ISOLATION / STATIC) — to a video
generation model, using ONLY the decision-table fields C11/C13b added to
``shared.channel_profile.MODEL_REGISTRY`` entries (``best_for`` / ``tier`` /
``styles`` / ``wired``). This module holds no second list of model
capabilities: it is a pure lookup over that registry, so adding/removing/
re-tagging a model in channel_profile.py is picked up automatically, with no
edit needed here.

Called at SHOT-PLAN time (storyboard/coverage.py's ``plan_camera_moves()``,
before any frame is drawn) to compute a recommendation that rides the shot
dict into the ``assets`` table's ``routed_model``/``routing_reason``
columns (migration 088). Data + recommendation only — clip generation does
not read ``routed_model`` yet (that's C13); there is no UI for it yet
(C14).

C13b (Ryan, 2026-07-18): the video's LOOK gates model choice BEFORE scene
importance does. An animated channel (ElevenLabs voice-over + Grok
animation, e.g. Poco a Poco) must never get recommended a realistic-only
model just because a scene earned the "hero" tag — Grok is genuinely good
at animating a single stylized scene, but has no realistic capability, and
the realistic palette (Seedance/Veo/Kling/Runway/Hailuo) is priced and built
for photoreal work, not stylized animation. See ``videos.render_style``
(migration 089) and ``ModelProfile.styles``.

Guarantees:
  - Only ever returns a WIRED model id (``ModelProfile.wired is True``) —
    UNLESS ``render_style`` is unset, in which case it returns the caller's
    own ``video_model_id`` verbatim (which may itself be unwired if the
    caller passed a stale/unknown value — this module trusts that input the
    same way ``resolve_clip_model`` already does downstream).
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


def _first_wired_with_tag(tag: str, style: str | None = None):
    """First wired registry entry carrying ``tag`` in ``best_for``. When
    ``style`` is given, ALSO requires that style in the entry's ``styles``
    list (case-insensitive) — this is the C13b palette filter: "purpose→tag
    mapping unchanged, but only within the models whose look matches the
    channel's declared style"."""
    for mid, profile in _wired_models().items():
        if tag not in profile.best_for:
            continue
        if style is not None:
            if style not in [s.lower() for s in profile.styles]:
                continue
        return mid, profile
    return None


def route_shot_model(
    purpose: str | None,
    is_multi_shot: bool = False,
    render_style: str | None = None,
    video_model_id: str | None = None,
) -> RoutingDecision:
    """Pick a video model + a human-readable reason for one shot.

    ``purpose`` is whatever camera_selector's resolve_purpose()/
    select_camera_move() returned for this shot: REVEAL, ESTABLISH,
    PAYOFF, SCALE, ISOLATION, or STATIC (no camera-move purpose earned).
    Anything falsy/unrecognized is treated like STATIC. ``is_multi_shot``
    is an optional forward-looking hint (see _MULTI_SHOT_TAG above).

    ``render_style`` is the video's declared LOOK (``videos.render_style``:
    'animated' | 'realistic' | None) and ``video_model_id`` is that video's
    own ``video_model`` — both new in C13b.

    GUARDRAIL (C13b, Ryan 2026-07-18 — the video's LOOK gates model choice
    BEFORE scene importance does):

      1. ``render_style`` is falsy (None/'') — the case for EVERY video
         created before this chunk shipped, and any new video whose look
         wasn't declared. The router stays fully opt-in: it returns
         ``video_model_id`` (or DEFAULT_VIDEO_MODEL if that's also empty)
         UNCHANGED, with a reason that says so. This deliberately turns OFF
         the purpose-based tier-upgrading below until a channel opts in by
         declaring its style — the money-safe default, so an animated
         channel never gets recommended a realistic-only premium model
         just because nobody told the router it's animated.
      2. ``render_style`` is set — every recommendation below is FILTERED
         to wired models whose ``styles`` include it (the "palette"). The
         same multi_shot → purpose-tag → draft priority cascade as before
         runs, but only ever picks from that palette. An animated channel
         therefore NEVER routes to veo/seedance (neither carries
         "animated"/"stylized") even for a REVEAL/PAYOFF ("hero") shot —
         it falls through the cascade to whatever IS in the animated
         palette (today: Grok, tagged "draft"/"broll"), giving a reason
         like "reveal scene, but channel is animated → Grok Imagine".
      3. If NO wired model anywhere carries ``render_style`` (not even at
         the draft tier — e.g. a style value nothing in the registry is
         tagged with yet) the palette is empty and there is nothing to
         recommend: falls back to ``video_model_id``/DEFAULT_VIDEO_MODEL,
         same as case 1, with a reason naming the unmatched style.

    Only ever returns a wired model_id when ``render_style`` is set (cases
    2/3 both bottom out on a wired pick or the video-level fallback). When
    ``render_style`` is unset, returns ``video_model_id`` verbatim — trusted
    input, same contract ``resolve_clip_model`` already relies on.
    """
    purpose = (purpose or "STATIC").upper()
    label = _PURPOSE_LABEL.get(purpose, purpose.lower() or "ordinary")
    fallback_model = video_model_id or DEFAULT_VIDEO_MODEL

    style = (render_style or "").strip().lower() or None
    if style is None:
        return RoutingDecision(
            fallback_model, "channel style not set — using channel default")

    if is_multi_shot:
        hit = _first_wired_with_tag(_MULTI_SHOT_TAG, style=style)
        if hit:
            mid, profile = hit
            return RoutingDecision(
                mid, f"multi-shot sequence, {style} channel → "
                     f"{_MULTI_SHOT_TAG} tier ({profile.tier})")

    tag = _PURPOSE_TAG.get(purpose)
    if tag:
        hit = _first_wired_with_tag(tag, style=style)
        if hit:
            mid, profile = hit
            return RoutingDecision(
                mid, f"{label} scene, {style} channel → {tag} tier ({profile.tier})")

    # STATIC, unrecognized, or the earned tag has no match within this
    # style's palette: the same cheap-iteration tier the pipeline already
    # defaults to, still restricted to the declared style.
    hit = _first_wired_with_tag("draft", style=style)
    if hit:
        mid, profile = hit
        if tag and tag != "draft":
            # The purpose earned a real tag (e.g. "hero"), but no model in
            # this style's palette carries it — name that explicitly rather
            # than silently reading like an ordinary/STATIC shot.
            return RoutingDecision(
                mid, f"{label} scene, but channel is {style} → {profile.display_name}")
        return RoutingDecision(mid, f"{label} scene, {style} channel → draft tier ({profile.tier})")

    # No wired model anywhere carries this style — nothing to recommend.
    return RoutingDecision(
        fallback_model, f"no wired model supports '{style}' style — using channel default")


def resolve_clip_model(
    routed_model: str | None,
    video_model_id: str,
    scene_override: str | None = None,
) -> str:
    """Resolve which model_id actually generates ONE shot's clip (checklist
    §1.2/C13 — the read side of C12's write-only ``routed_model`` column).

    Precedence:
      1. ``scene_override`` — an explicit per-scene choice. No column exists
         for this yet (C14 owns that UI); this parameter is the seam a
         future caller wires a real value into. Always None today.
      2. ``routed_model`` — ``assets.routed_model``, C12's shot-plan-time
         recommendation — but ONLY when it names a model that is BOTH in
         ``MODEL_REGISTRY`` and ``wired`` (an unknown id, or a registry
         entry that's since been un-wired, must not silently attempt a
         dead generation path).
      3. ``video_model_id`` — the video-level model the caller already
         resolved (mirrors pre-C13 behavior: ``(video.get("video_model")
         or "").strip() or DEFAULT_VIDEO_MODEL``, gated wired upstream).

    A NULL/unknown/unwired ``routed_model`` — i.e. every asset row that
    predates C12, or any row whose shot-plan-time routing try/except
    tripped — falls through step 2 and returns ``video_model_id``
    UNCHANGED: byte-identical to what clip generation did before this
    function existed.
    """
    for candidate in (scene_override, routed_model):
        if candidate and candidate in MODEL_REGISTRY and MODEL_REGISTRY[candidate].wired:
            return candidate
    return video_model_id or DEFAULT_VIDEO_MODEL
