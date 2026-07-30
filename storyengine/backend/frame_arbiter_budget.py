"""frame_arbiter_budget: pre-call spend guard for the Frame Arbiter (D5
FRAME-ARBITER-PLAN.md, chunk A1).

The mission's spine: auto-repair must be structurally incapable of
unbounded spend, so this cap exists BEFORE any paid judging/repair code
does (DoC #3). Nothing calls this module yet — A3 (the vision judge call)
and A5 (auto-repair wiring) will, once they land. This chunk is pure data
layer: a ledger-stage convention, a read-before-you-spend guard, and a
writer. No product code is touched.

Two caps, enforced INDEPENDENTLY, both read live off generation_ledger
before any paid call fires — never audited after the fact:

  * FRAME_QA_SCENE_CAP ($0.25) — total frame_qa-stage spend for one
    (video_id, scene).
  * FRAME_QA_VIDEO_CAP ($0.50) — total frame_qa-stage spend for the whole
    video, across every scene.

This is a NEW, narrower cap — separate from actions.budget_check/
budget_refusal's existing per-video ``videos.max_spend`` cap (which sums
ALL stages, has no per-scene concept, and is optional/user-set). Same
"read live spend, decide before spending" shape as that pattern
(actions.py:402-472) and routes/characters.py's ``_budget_refusal``, just
scoped to the frame_qa stage and adding the per-scene half that doesn't
exist anywhere else in the codebase.

Ledger shape (migration 140 — see its header for the full column
rationale): a frame_qa spend row is a normal generation_ledger row with
``stage='frame_qa'`` plus two additive, NULLable columns other stages
never set: ``scene`` (int, groups the per-scene cap) and ``fingerprint``
(text, the learning-ratchet's repeat-failure key — A2 owns the fingerprint
TABLE with violation counts / frozen flag; this is just A1's row-level tag
so a spend row can be traced to which fingerprint it was for).

Tenant override TODO: both caps are hardcoded module constants today, not
per-tenant. FRAME-ARBITER-PLAN.md doesn't call for tenant config in A1's
scope ("leave a TODO hook, don't build tenant config") — when that lands,
wire it into ``_scene_cap``/``_video_cap`` below (a tenant_prompt_defaults-
style lookup, same pattern as other per-tenant prompt overrides), not by
duplicating this module's call sites.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from database import fetch_one

FRAME_QA_STAGE = "frame_qa"

# TODO(tenant-config): hardcoded system-wide for A1, now env-overridable
# system-wide (D5 chunk A6, Ryan's ruling: "the cap value is config, not a
# constant buried in code"). Per-TENANT config is still the TODO — see
# module docstring — wire it into _scene_cap/_video_cap below (not the call
# sites) when a later chunk needs it; the env override below is a system-
# wide knob for A6's own live checkpoint, not a substitute for that.
FRAME_QA_SCENE_CAP = 0.25
FRAME_QA_VIDEO_CAP = 0.50


def _env_cap_override(name: str) -> Optional[float]:
    """Reads an env-var cap override, e.g. for a single flag-scoped live
    checkpoint that wants a tighter number than the system default without
    editing this file. Malformed/missing -> None (falls back to the module
    constant) — never raises, never silently becomes 0."""
    raw = os.getenv(name)
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _scene_cap(tenant_id: str) -> float:  # noqa: ARG001 - tenant hook, unused today
    return _env_cap_override("FRAME_QA_SCENE_CAP") or FRAME_QA_SCENE_CAP


def _video_cap(tenant_id: str) -> float:  # noqa: ARG001 - tenant hook, unused today
    return _env_cap_override("FRAME_QA_VIDEO_CAP") or FRAME_QA_VIDEO_CAP


async def _frame_qa_spend(tenant_id: str, video_id: str, scene: Optional[int] = None) -> float:
    """Real frame_qa-stage spend so far, read straight off generation_ledger.

    ``scene=None`` sums the whole video's frame_qa spend (the video cap);
    a real scene number scopes to just that scene's rows (the scene cap).
    This is the live read the guard checks BEFORE a paid call — the ledger
    is the only source of truth, never a running in-memory counter (which
    would drift under concurrent QA calls the same way every other
    pre-existing budget guard in this codebase avoids by reading live).
    """
    if scene is None:
        row = await fetch_one(
            "SELECT COALESCE(SUM(actual_cost), 0) AS spent FROM generation_ledger "
            "WHERE tenant_id = $1 AND video_id = $2 AND stage = $3",
            tenant_id, video_id, FRAME_QA_STAGE,
        )
    else:
        row = await fetch_one(
            "SELECT COALESCE(SUM(actual_cost), 0) AS spent FROM generation_ledger "
            "WHERE tenant_id = $1 AND video_id = $2 AND stage = $3 AND scene = $4",
            tenant_id, video_id, FRAME_QA_STAGE, scene,
        )
    return float((row or {}).get("spent") or 0)


async def arbiter_budget_check(
    tenant_id: str,
    video_id: str,
    scene: Optional[int],
    projected_cost: float,
) -> Optional[dict[str, Any]]:
    """Would ``projected_cost`` (a QA vision call or an arbiter-triggered
    repair, quoted honestly BEFORE it fires) push frame_qa-stage spend past
    either cap? Checked BEFORE any paid call — this function does the
    checking, the caller (A3/A5) is responsible for never firing the call
    when this returns a breach.

    Returns None when the quote fits under BOTH caps (or ``scene`` is None,
    which only exempts the scene-level check — the video cap still always
    applies). Returns a breach dict otherwise: ``scope`` ("scene" or
    "video") says which cap tripped, checked scene-first since it's the
    tighter, cheaper-to-hit limit and callers usually want the more
    specific reason.

    Mirrors actions.budget_check's return shape (cap/spent/quote/projected/
    message) so any caller already familiar with that pattern reads this
    one for free.
    """
    quote = round(max(projected_cost, 0.0), 2)

    if scene is not None:
        scene_cap = _scene_cap(tenant_id)
        scene_spent = await _frame_qa_spend(tenant_id, video_id, scene=scene)
        scene_projected = round(scene_spent + quote, 2)
        if scene_projected > scene_cap:
            return {
                "scope": "scene",
                "scene": scene,
                "cap": scene_cap,
                "spent": scene_spent,
                "quote": quote,
                "projected": scene_projected,
                "message": (
                    f"frame QA for scene {scene} would hit ${scene_projected:.2f} against "
                    f"its ${scene_cap:.2f} scene cap (${scene_spent:.2f} spent so far + "
                    f"${quote:.2f} for this call)."
                ),
            }

    video_cap = _video_cap(tenant_id)
    video_spent = await _frame_qa_spend(tenant_id, video_id, scene=None)
    video_projected = round(video_spent + quote, 2)
    if video_projected > video_cap:
        return {
            "scope": "video",
            "scene": scene,
            "cap": video_cap,
            "spent": video_spent,
            "quote": quote,
            "projected": video_projected,
            "message": (
                f"frame QA for this video would hit ${video_projected:.2f} against its "
                f"${video_cap:.2f} video cap (${video_spent:.2f} spent so far + "
                f"${quote:.2f} for this call)."
            ),
        }

    return None


async def arbiter_budget_refusal(
    tenant_id: str,
    video_id: str,
    scene: Optional[int],
    projected_cost: float,
    item_label: str = "this frame QA call",
) -> Optional[str]:
    """Packaged one-shot check for a call site that just wants a plain-
    English refusal or None — same shape as actions.budget_refusal /
    routes/characters.py's ``_budget_refusal``. A3/A5 call this (or
    ``arbiter_budget_check`` directly, for the breach dict) right before
    their provider call; neither exists yet, so nothing calls this today.

    Refusals are printed (flush=True), matching generation_ledger.py's
    DUPLICATE SKIPPED logging convention — this is the one signal a
    fingerprint's spend is being capped, so it needs to be loud, not
    silent.
    """
    breach = await arbiter_budget_check(tenant_id, video_id, scene, projected_cost)
    if not breach:
        return None
    message = (
        f"Paused — {item_label} would put this video's {breach['scope']} frame-QA spend at "
        f"${breach['projected']:.2f} against the ${breach['cap']:.2f} {breach['scope']} cap "
        f"(${breach['spent']:.2f} already spent, ${breach['quote']:.2f} for this call)."
    )
    print(
        f"[frame_arbiter_budget] REFUSED — video={video_id} scene={scene} "
        f"scope={breach['scope']} spent=${breach['spent']:.2f} quote=${breach['quote']:.2f} "
        f"cap=${breach['cap']:.2f}",
        flush=True,
    )
    return message


async def record_frame_qa_entry(
    tenant_id: str,
    video_id: str,
    scene: Optional[int],
    model: Optional[str],
    units: float,
    unit_cost: float,
    actual_cost: float,
    fingerprint: Optional[str] = None,
    kie_task_id: Optional[str] = None,
) -> None:
    """Write one frame_qa-stage generation_ledger row. Thin wrapper around
    generation_ledger.record_ledger_entry (the single write path into
    videos.total_cost — see that module's docstring) so every frame_qa
    caller (A3's judge call, A5's repair spend) goes through the same
    stage/scene/fingerprint shape instead of hand-rolling the INSERT.
    Deliberately NOT a separate table or a separate rollup mechanism —
    frame_qa spend is real generation spend and belongs in the same ledger
    as every other stage.
    """
    from generation_ledger import record_ledger_entry

    await record_ledger_entry(
        tenant_id=tenant_id,
        video_id=video_id,
        stage=FRAME_QA_STAGE,
        model=model,
        units=units,
        unit_cost=unit_cost,
        actual_cost=actual_cost,
        kie_task_id=kie_task_id,
        scene=scene,
        fingerprint=fingerprint,
    )
