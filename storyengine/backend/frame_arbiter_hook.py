"""D5 chunk A6 (storyengine/FRAME-ARBITER-PLAN.md): flag-gated single-scene
wiring. A1 (budget), A2 (fingerprints), A3/A3b (judge), A5 (board repair) are
all built and tested but, per every one of their own module docstrings,
"nothing in the product calls this module yet." This chunk is the one file
that actually calls them, and it does so behind a flag scoped to exactly ONE
(video_id, scene) pair — never a whole tenant, never "all scenes."

Board station only (Ryan's 2026-07-29 ruling + the A3b eval split verdict,
tasks/loop-checklist.md): the board station graduated (5/5 known defects,
correct class) and is the PRIMARY gate; the frame station did not graduate
and its repair leg is frozen (arbiter_repair.FRAME_REPAIR_ENABLED = False).
This hook only ever calls judge_board_sheet / repair_board_finding —
judge_scene_batch (frames) is not wired here, on purpose.

Two flags, both env-configured, BOTH DEFAULT OFF:

  * FRAME_ARBITER_A6_ENABLED — master switch. Judging (judge_board_sheet,
    which itself is A1 budget-gated + A2 fingerprint-recorded + ledger-
    metered) runs ONLY for the exact (video_id, scene) named by
    FRAME_ARBITER_A6_VIDEO_ID / FRAME_ARBITER_A6_SCENE below — see
    scene_is_in_scope, the one function the entire "ONE scene of ONE video"
    scoping law lives in. Every other video/scene in the product is
    BYTE-IDENTICAL to before this chunk: scene_is_in_scope's check is env
    reads + a string/int comparison, no DB, no network — so the disabled/
    out-of-scope path costs nothing, not even a query.
  * FRAME_ARBITER_A6_REDRAW_ENABLED — sub-flag for the repair ladder's PAID
    redraw leg (arbiter_repair.repair_board_finding's step 3, "ROLL").
    Independent of the master switch and DEFAULT OFF: judging (and the
    freeze/budget legs of a repair DECISION) can run safely with zero
    real-dollar redraw risk while this is off. When off, the real
    `arbiter_repair._default_board_reroll` (which imports
    scripts.coverage_to_app and calls the actual paid drawing model) is
    never imported, let alone invoked — `_redraw_refused_reroll` below
    stands in for it, returning a "failed"-shaped result so
    repair_board_finding takes its OWN pre-existing "reroll_failed" branch
    (no ledger write, `acted: False`) instead of a new code path invented
    here. The freeze check (step 1) and the budget check (step 2) inside
    repair_board_finding run IDENTICALLY whether the sub-flag is on or off
    — only the reroll step itself is swapped, via the same `reroll_fn` DI
    seam arbiter_repair.py's own test suite already uses.

Video id + scene are configurable (env — FRAME-ARBITER-PLAN.md's A6 chunk
doesn't call for a DB config UI this early, and Ryan's ruling only asks that
they not be hardcoded, not that they live in a table yet; A7/A9 own moving
this into per-tenant config once the Review feed exists). A missing or
unparsable target refuses scope — never guesses, never defaults to "every
scene."

Budget: this hook adds NO new spend mechanism. Every dollar it can possibly
spend already flows through frame_arbiter_budget.arbiter_budget_check (the
$0.25/scene + $0.50/video caps, now env-overridable — see that module) via
judge_board_sheet and repair_board_finding's own pre-existing calls. This
hook only decides WHEN those functions are allowed to run at all.

Pure hook — the only thing that imports this module is
pipeline_executor.PipelineExecutor.run_storyboard_sheet (the single unified
board-sheet entry point every chat verb / button / MCP tool already
converges on, per actions.py's own "extend here, never fork it" law — see
that call site for the wiring).
"""
from __future__ import annotations

import os
from typing import Any, Awaitable, Callable, Optional

from arbiter_repair import rejudge_board_after_repair, repair_board_finding
from database import fetch_all
from frame_arbiter import judge_board_sheet

_TRUE = {"1", "true", "yes", "on"}

# Board sheets are stored as up to 5 columns on `scripts`
# (storyboard_1_url..storyboard_5_url) — see generate_storyboard_sheet_for_scene
# in scripts/coverage_to_app.py, the writer of these exact columns.
_MAX_BEATS = 5


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE


def arbiter_enabled() -> bool:
    """Master A6 switch. DEFAULT OFF."""
    return _env_bool("FRAME_ARBITER_A6_ENABLED", False)


def redraw_enabled() -> bool:
    """Sub-flag for the repair ladder's paid redraw leg. DEFAULT OFF,
    independent of arbiter_enabled — judging must be able to run with zero
    real-dollar redraw risk."""
    return _env_bool("FRAME_ARBITER_A6_REDRAW_ENABLED", False)


def target_video_id() -> Optional[str]:
    return os.getenv("FRAME_ARBITER_A6_VIDEO_ID") or None


def target_scene() -> Optional[int]:
    raw = os.getenv("FRAME_ARBITER_A6_SCENE")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def scene_is_in_scope(video_id: Any, scene: Optional[int]) -> bool:
    """True ONLY when arbiter_enabled() AND (video_id, scene) is EXACTLY the
    one pair FRAME_ARBITER_A6_VIDEO_ID / FRAME_ARBITER_A6_SCENE name.

    Cheap and DB-free by construction (env reads + a string/int comparison
    only) — this is what makes the disabled path genuinely free rather than
    "a judge call that happens to no-op": nothing downstream of a False
    return here ever touches a DB or a network call.

    Deliberately conservative: a missing or unparsable target config value
    refuses scope (returns False) rather than guessing. There is no tenant
    parameter here on purpose — video_id already uniquely determines a
    tenant (scripts/videos rows are always looked up as (video_id,
    tenant_id) pairs, never video_id alone), so an extra tenant check would
    be redundant, not an additional safety margin.
    """
    if scene is None or not arbiter_enabled():
        return False
    tvid = target_video_id()
    tscene = target_scene()
    if not tvid or tscene is None:
        return False
    return str(video_id) == str(tvid) and int(scene) == int(tscene)


async def _redraw_refused_reroll(
    video_id: str, tenant_id: str, *, scene: int, beat: int, progress=None,
) -> dict:
    """Stands in for arbiter_repair._default_board_reroll when
    FRAME_ARBITER_A6_REDRAW_ENABLED is off. Returns a "failed"-shaped result
    (never "completed") so repair_board_finding's OWN pre-existing reroll-
    result check (``reroll_result.get("status") == "failed"``) takes the
    SAME "reroll_failed" branch a real transient draw failure would take —
    no ledger write, ``acted: False`` — no new branch invented here. The
    real, paid ``_default_board_reroll`` (which imports
    scripts.coverage_to_app and calls the actual drawing model) is never
    imported by this module, let alone called, while the sub-flag is off.
    """
    return {
        "status": "failed",
        "error": "frame_arbiter_a6_redraw_disabled",
        "message": (
            "FRAME_ARBITER_A6_REDRAW_ENABLED is off — the repair ladder's "
            "paid redraw leg did not fire for this MODEL_DEFECT finding."
        ),
    }


async def _fetch_scene_sheets(tenant_id: str, video_id: str, scene: int) -> list[dict]:
    """Every DRAWN board sheet (beat 1..storyboard_beat_count that actually
    has a URL) for this one scene, straight off the same `scripts` row
    generate_storyboard_sheet_for_scene just wrote — the same spec_text
    (storyboard_prompts) frame_arbiter._parse_sheet_panels already knows how
    to read. Returns [] for a scene with no drawn boards yet (never raises)."""
    rows = await fetch_all(
        "SELECT storyboard_1_url, storyboard_2_url, storyboard_3_url, "
        "storyboard_4_url, storyboard_5_url, storyboard_beat_count, "
        "storyboard_prompts FROM scripts "
        "WHERE video_id = $1 AND tenant_id = $2 AND scene = $3",
        video_id, tenant_id, scene,
    )
    if not rows:
        return []
    row = rows[0]
    spec_text = row.get("storyboard_prompts") or ""
    beat_count = min(int(row.get("storyboard_beat_count") or 0), _MAX_BEATS)
    sheets: list[dict] = []
    for beat in range(1, beat_count + 1):
        url = row.get(f"storyboard_{beat}_url")
        if url:
            sheets.append({"image_url": url, "sheet_index": beat, "spec_text": spec_text})
    return sheets


async def run_after_storyboard_sheet(
    tenant_id: str,
    video_id: str,
    scene: int,
    *,
    fetch_sheets: Callable[..., Awaitable[list]] = _fetch_scene_sheets,
    judge_fn: Callable[..., Awaitable[dict]] = judge_board_sheet,
    repair_fn: Callable[..., Awaitable[dict]] = repair_board_finding,
    rejudge_fn: Callable[..., Awaitable[dict]] = rejudge_board_after_repair,
) -> Optional[dict]:
    """A6's own hook — called by
    pipeline_executor.PipelineExecutor.run_storyboard_sheet right after a
    scene's board sheet(s) land.

    Returns None, doing NOTHING else (no DB read, no vision call, no
    import even resolving beyond this module's own top), for every
    (video_id, scene) except the one pair named by
    FRAME_ARBITER_A6_VIDEO_ID / FRAME_ARBITER_A6_SCENE while
    FRAME_ARBITER_A6_ENABLED is on — see scene_is_in_scope. This is what
    makes "flag off = zero arbiter calls, byte-identical behavior" true:
    the disabled path is one boolean check, not a judge call that happens
    to no-op.

    For the one in-scope scene: judges EVERY drawn sheet (a scene can have
    up to 5 boards/beats) via judge_fn (default judge_board_sheet — the
    GRADUATED board station, itself budget-gated/ledger-metered/
    fingerprint-recorded per its own contract, unchanged by this hook). For
    each sheet with at least one MODEL_DEFECT finding, attempts ONE repair
    (repair_fn, default repair_board_finding) using that sheet's FIRST
    MODEL_DEFECT finding — repair rerolls the WHOLE sheet, not a single
    panel, so a second MODEL_DEFECT finding on a sheet THIS PASS already
    attempted is recorded (judge_fn's own fingerprint write already ran)
    but does not trigger a second reroll of a sheet this pass already spent
    on. redraw_enabled() decides whether repair_fn's reroll leg is the real
    paid draw or the refused stub (_redraw_refused_reroll) — the freeze/
    budget legs inside repair_fn run identically either way (see module
    docstring). A successful repair is re-judged exactly once via
    rejudge_fn (rejudge_board_after_repair), forwarding this hook's OWN
    judge_fn so the rejudge sees the identical DI wiring the first judgment
    did — this is what lets a repeat MODEL_DEFECT on the SAME fingerprint
    cross A2's freeze threshold, per arbiter_repair.py's own module
    docstring (the ratchet only ever moves through judge_board_sheet, at
    judgment time).

    Returns ``{"scene": scene, "sheets": [{"beat", "judged", "repair"},
    ...]}`` — never raises on its own account; a judge/repair call's own
    internal fail-closed behavior (skipped dicts, a refused reroll) is what
    this function surfaces, not a try/except swallow.
    """
    if not scene_is_in_scope(video_id, scene):
        return None

    sheets = await fetch_sheets(tenant_id, video_id, scene)
    if not sheets:
        return {"scene": scene, "sheets": [], "reason": "no_drawn_sheets"}

    reroll = None if redraw_enabled() else _redraw_refused_reroll

    results = []
    for sheet in sheets:
        beat = sheet["sheet_index"]
        judged = await judge_fn(tenant_id, video_id, scene, sheet)
        repair_result = None
        if not judged.get("skipped"):
            model_defects = [
                f for f in judged.get("findings", [])
                if not f.get("skipped") and f.get("classification") == "MODEL_DEFECT"
            ]
            if model_defects:
                repair_result = await repair_fn(
                    tenant_id, video_id, scene, model_defects[0],
                    sheet_index=beat, reroll_fn=reroll,
                )
                if repair_result.get("acted"):
                    rejudged = await rejudge_fn(
                        tenant_id, video_id, scene, sheet, judge_fn=judge_fn,
                    )
                    repair_result = dict(repair_result, rejudge=rejudged)
        results.append({"beat": beat, "judged": judged, "repair": repair_result})

    return {"scene": scene, "sheets": results}
