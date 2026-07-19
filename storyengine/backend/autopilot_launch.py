"""Candidate auto-launch loop (checklist C51, P4.2-b).

The tenant-autopilot mirror of ``routes/queue.py``'s ``auto_produce_next``,
scoring ``competitor_videos`` instead of draining a manual queue. Called by
``main.py``'s ``_auto_produce_queue`` background loop as the fallback
``routes/queue.py``'s own docstring already anticipates ("Autopilot drains
the queue in order BEFORE falling back to its scored competitor
candidates") — same per-tenant production cadence lane, so a tenant never
gets both a queue launch AND a candidate launch/proposal in one window.

Behavior is entirely gated by the C50 dial (``autopilot_dial.
get_autopilot_dial``) — this is the FIRST real reader of ``dial_level``:

- ``kill_switch_tripped_at`` set -> the tenant is skipped OUTRIGHT, before
  any scoring happens. A tripped kill switch means "a human must look
  before ANY further automation," not just "before spend" — even a
  propose_only proposal is withheld.
- ``dial_level == 'propose_only'`` (the default, every existing tenant
  today) -> DRY RUN. Scores candidates, picks the best one above the
  tenant's ``min_confidence_score`` threshold that doesn't already have an
  undecided proposal, and records ONE row via
  ``autopilot_proposals.create_proposal``. This branch never imports
  ``routes.autopilot.launch_candidate`` at all — there is no video row, no
  pipeline dispatch, no paid call possible from this code path, by
  construction, not by an if-check that could be gotten wrong.
- ``dial_level in ('auto_draft', 'full_auto')`` -> calls the EXISTING
  ``routes.autopilot.launch_candidate`` verbatim (same gates, same
  needs_approval stop as a manual click today). ``full_auto`` is treated
  identically to ``auto_draft`` here — carrying a draft through to
  finalize+upload unattended is checklist C55, not this chunk. C54 (P4.2-e)
  adds one more gate on THIS branch only, immediately before the launch
  call: ``autopilot_dial.check_weekly_budget`` — a breach trips the kill
  switch and returns None instead of launching. propose_only never reaches
  that check, so a budget breach can never block a free proposal.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import autopilot_proposals
from autopilot_dial import check_weekly_budget, get_autopilot_dial, trip_kill_switch
from database import fetch_one

logger = logging.getLogger(__name__)

_DEFAULT_MIN_CONFIDENCE = 60.0
_DEFAULT_MIN_VPH = 50.0
_DEFAULT_INTERVAL_DAYS = 2


async def _autopilot_row(tenant_id: str) -> Optional[dict]:
    return await fetch_one(
        "SELECT enabled, production_interval_days, thresholds "
        "FROM autopilot_config WHERE tenant_id = $1",
        tenant_id,
    )


def _thresholds(cfg: dict) -> dict:
    thresholds = cfg.get("thresholds") or {}
    if isinstance(thresholds, str):
        import json
        try:
            thresholds = json.loads(thresholds)
        except (ValueError, TypeError):
            thresholds = {}
    return thresholds if isinstance(thresholds, dict) else {}


async def _due(tenant_id: str, interval_days: int) -> bool:
    """Same shared-cadence discipline as ``routes.queue.auto_produce_next``,
    with one addition: a propose_only proposal also counts as "a production
    action happened", via MAX(created_at) on autopilot_proposals — otherwise
    propose_only would re-propose (a different top candidate, dedup can't
    catch that) every 30-minute tick instead of once per cadence window."""
    row = await fetch_one(
        """SELECT GREATEST(
               (SELECT MAX(launched_at) FROM production_queue WHERE tenant_id = $1),
               (SELECT MAX(created_at) FROM videos
                WHERE tenant_id = $1 AND (source = 'queue' OR source LIKE 'autopilot%')
                  AND deleted_at IS NULL),
               (SELECT MAX(created_at) FROM autopilot_proposals WHERE tenant_id = $1)
           ) AS t""",
        tenant_id,
    )
    if not row or row.get("t") is None:
        return True
    due = await fetch_one(
        "SELECT (now() - $1::timestamptz) >= make_interval(days => $2) AS due",
        row["t"], interval_days,
    )
    return bool(due and due["due"])


async def _in_flight(tenant_id: str) -> bool:
    from routes.queue import TERMINAL_STATUSES

    row = await fetch_one(
        """SELECT 1 AS x FROM videos
           WHERE tenant_id = $1 AND (source = 'queue' OR source LIKE 'autopilot%')
             AND status NOT IN ({}) AND deleted_at IS NULL
             AND created_at > now() - interval '7 days'
           LIMIT 1""".format(", ".join(f"'{s}'" for s in TERMINAL_STATUSES)),
        tenant_id,
    )
    return row is not None


async def _pick_candidate(tenant_id: str, min_vph: float, min_confidence: float):
    """Score candidates via the EXISTING routes.autopilot.get_candidates path
    (same SQL, same calculate_confidence_with_breakdown scorer a human sees
    in the dashboard — no parallel scoring logic here) and return the
    highest-confidence one that clears min_confidence_score AND has no
    undecided proposal yet. None if nothing qualifies."""
    from routes.autopilot import get_candidates

    try:
        candidates = await get_candidates(
            limit=20, min_vph=min_vph, include_modeled=False, tenant_id=tenant_id,
        )
    except Exception:
        logger.exception("[AutoLaunch] Tenant %s: candidate scoring failed", tenant_id[:8])
        return None

    for candidate in candidates:
        if candidate.confidence < min_confidence:
            continue
        if await autopilot_proposals.has_active_proposal(tenant_id, candidate.id):
            continue
        return candidate
    return None


async def auto_launch_best_candidate(tenant_id: str) -> Optional[dict]:
    """One autopilot heartbeat for scored competitor candidates. Returns the
    launch/proposal info dict, or None if nothing happened this cycle
    (kill switch tripped, autopilot disabled, not due, something already in
    flight, or no candidate cleared the bar)."""
    try:
        dial = await get_autopilot_dial(tenant_id)
    except Exception:
        logger.exception("[AutoLaunch] Tenant %s: dial read failed, skipping", tenant_id[:8])
        return None

    # Invariant 1: a tripped kill switch means a human must look before ANY
    # further automation — even scoring/proposing is withheld, not just spend.
    if dial.kill_switch_tripped_at is not None:
        return None

    cfg = await _autopilot_row(tenant_id)
    if not cfg or not cfg.get("enabled"):
        return None

    thresholds = _thresholds(cfg)
    min_confidence = float(thresholds.get("min_confidence_score", _DEFAULT_MIN_CONFIDENCE) or _DEFAULT_MIN_CONFIDENCE)
    min_vph = float(thresholds.get("min_competitor_vph", _DEFAULT_MIN_VPH) or _DEFAULT_MIN_VPH)
    interval_days = max(1, int(cfg.get("production_interval_days") or 0) or _DEFAULT_INTERVAL_DAYS)

    if not await _due(tenant_id, interval_days):
        return None
    if await _in_flight(tenant_id):
        return None

    candidate = await _pick_candidate(tenant_id, min_vph, min_confidence)
    if not candidate:
        return None

    if dial.dial_level == "propose_only":
        # Invariant 2: this branch cannot reach launch_candidate — the name
        # is never imported/bound here, so there is nothing to call even by
        # mistake. Score + record only.
        breakdown = candidate.confidence_breakdown.model_dump() if candidate.confidence_breakdown else None
        proposal = await autopilot_proposals.create_proposal(
            tenant_id,
            candidate_id=candidate.id,
            video_title=candidate.title,
            confidence_score=candidate.confidence,
            confidence_breakdown=breakdown,
        )
        return {
            "status": "proposed",
            "proposal_id": proposal["id"],
            "candidate_id": candidate.id,
            "video_title": candidate.title,
            "confidence": candidate.confidence,
            "message": "Candidate scored and proposed (propose-only) — no video created, no spend.",
        }

    # dial_level == 'auto_draft' (or 'full_auto', treated identically here —
    # carrying a full_auto draft through to finalize+upload is C55, not this
    # chunk). Calls the EXISTING launch path verbatim; all its gates
    # (already-launched check, needs_approval stop) apply unchanged.
    #
    # C54 (P4.2-e): re-check the weekly budget HERE, immediately before
    # launching — not just once at the loop level (main.py::_produce_for_
    # tenant). Candidate scoring above (_pick_candidate -> get_candidates)
    # can take real time, so the loop-level check could be a whole launch
    # stale by then; this is the last gate before an actual paid pipeline
    # starts. propose_only above never reaches this line at all, so a
    # budget breach can NEVER block a free proposal — only auto_draft/
    # full_auto spend is gated.
    try:
        ok, spent, cap = await check_weekly_budget(tenant_id)
    except Exception:
        logger.exception("[AutoLaunch] Tenant %s: budget check failed, skipping launch", tenant_id[:8])
        return None
    if not ok:
        reason = f"Weekly budget cap ${cap:.2f} reached (spent ${spent:.2f})"
        await trip_kill_switch(tenant_id, reason)
        logger.warning("[AutoLaunch] Tenant %s: %s — kill switch tripped, launch skipped", tenant_id[:8], reason)
        return None

    from fastapi import BackgroundTasks
    from routes.autopilot import launch_candidate

    bg = BackgroundTasks()
    result = await launch_candidate(candidate.id, bg, tenant_id=tenant_id)
    asyncio.create_task(bg())
    return result
