"""Frame Arbiter auto-repair wiring (D5 chunk A5, storyengine/
FRAME-ARBITER-PLAN.md + the two amendments recorded in
tasks/loop-checklist.md: Ryan's 2026-07-29 board-gate-first ruling, and the
A3b split verdict).

BOARD-LEVEL ONLY. The A3b eval harness graduated the BOARD station (5/5
known defects, correct class, $0.0273/call — tasks/loop-checklist.md's
D5-A3b entry, commit 8e2cb78d) but did NOT graduate the FRAMES station
(best 1/3 known defects correctly classified). Spending real money to
"fix" a defect an unreliable judge merely THINKS it saw is worse than not
repairing at all — so only ``repair_board_finding`` below does real work.
``repair_frame_finding`` is a frozen stub (see ``FRAME_REPAIR_ENABLED``)
until D5-A3b-2 graduates the frames station.

Pure library — no pipeline hook, no flag, no migration apply. A6 wires
this behind a flag; nothing in the product calls this module yet, same
"pure library, A6 hooks it up" boundary A1/A2/A3/A3b all held.

DoC #2 (only MODEL_DEFECT ever triggers repair) is the law this whole
module exists to enforce structurally, not just by convention:
  - MODEL_DEFECT -> the repair ladder below (freeze -> budget -> roll -> record).
  - AUTHORING_DEFECT -> never repairs; files the occurrence via
    ``record_finding`` (the PROMPT/SPEC authored the flaw — redrawing the
    same spec would just reproduce it) and returns, no spend.
  - TASTE_QUESTION -> never acts at all; returns card material for the
    Review feed (A7) — not even a fingerprint write, since there is
    nothing wrong to remember, only a preference to surface to a human.

Repair ladder order matters and is unit-tested (see
tests/functional/test_d5_a5_repair.py): FREEZE is checked before BUDGET,
so a frozen fingerprint never consumes budget quota just to be told no —
consistent with DoC #3's "checked BEFORE any paid call fires, never
audited after" law applying to the freeze gate too. Only after both gates
clear does the sheet re-roll fire; only after a successful re-roll does
this module call ``record_finding`` for the occurrence — deliberately
LAST, because per A2's semantics that record call is what may CROSS the
freeze threshold (violation_count hits 2 on this exact call, not before).
The natural consequence: a fingerprint's 1st repair spends and records
(not yet frozen); its 2nd repair ALSO spends and records (this is the call
that flips frozen=True); a 3rd occurrence of the same fingerprint never
reaches the roll or the record — it is turned away at the freeze check,
step 1, before a single dollar moves. "A repair that recurs is the
ratchet's signal" (the plan's own words) — the recurrence itself is what
teaches the system to stop, not a separate counter.

Reconciliation note for A6 (not resolved here, out of this chunk's
scope): ``frame_arbiter.judge_board_sheet`` ALREADY calls
``record_finding`` unconditionally for every classified verdict it
parses, at judge time — before any repair decision is made. This module's
own step 4 (record) is a SECOND call to the same underlying fingerprint
row for a MODEL_DEFECT finding that gets repaired. Tested here in
isolation (this module's own DI seams let ``is_frozen_fn``/
``record_finding_fn`` be swapped for a stateful fake that proves the
ladder's ordering and the 2-strikes freeze crossing correctly, entirely on
its own), but in the REAL pipeline A6 wires, these are two calls against
the same fingerprint key. A6 must explicitly decide — not guess — whether
that is intentional double-counting (the "finding recorded" event and the
"repair attempted" event are legitimately different ratchets) or whether
the judge-time call needs to become a no-op for MODEL_DEFECT findings
destined for repair, with this module as the sole recorder. Flag this as
a real design decision when A6 starts, not something to silently pick.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from arbiter_fingerprints import fingerprint_key, is_frozen, record_finding
from frame_arbiter import judge_board_sheet
from frame_arbiter_budget import FRAME_QA_STAGE, arbiter_budget_check, record_frame_qa_entry

# $0.05/GPT-Image-2-2K sheet re-roll — FRAME-ARBITER-PLAN.md's own A5 line
# ("MODEL_DEFECT -> redraw_shot (cheapest paid verb, $0.05/GPT-Image-2-2K)
# up to the per-scene cap"), same flat per-image convention this codebase
# already uses for image-stage spend (unlike the vision judge's
# usage_cost(), metered off the API's own usage block — an image draw here
# has no such usage block to read back, so the honest pre-call quote IS
# what gets ledgered as the actual_cost, same "quote is real money" law
# frame_arbiter.py documents for DEFAULT_QUOTE/DEFAULT_BOARD_QUOTE).
DEFAULT_BOARD_REPAIR_QUOTE = 0.05

# The board sheet re-roll's own draw model — matches scripts/coverage_to_
# app.py's SHEET_DRAW_MODEL constant (GPT Image 2, nano banned for boards
# per Ryan's 2026-07-21 evening ruling) so a repair-triggered ledger row
# reads the same model name a normal board draw would.
REPAIR_MODEL = "gpt-image-2"


async def _default_board_reroll(
    video_id: str, tenant_id: str, *, scene: int, beat: int, progress=None,
) -> dict:
    """Real reroll call — the underlying function
    ``POST /api/pipeline/storyboard-images/{video_id}?scene=N&beat=M``
    calls (routes/pipeline.py's ``run_storyboard_images``), called
    DIRECTLY here, never over HTTP. Lazy import mirrors that route's own
    convention (the import lives inside its background-task closure, not
    at module top) so importing arbiter_repair never pulls in
    scripts.coverage_to_app's own (heavier) import graph for a caller who
    only wants the pure decision-ladder logic (e.g. every test in
    tests/functional/test_d5_a5_repair.py).

    ``beat`` is REQUIRED and must be the sheet's own ``sheet_index`` — the
    underlying function's "PER-BOARD REDO" path (beat is not None) redraws
    ONE saved board from the scene's existing plan and never re-plans.
    Passing beat=None here would silently fall through to that function's
    OTHER mode (plan + draw every board in the scene) — a completely
    different, far more expensive action than "fix the one bad sheet a
    judge just flagged". ``repair_board_finding`` below refuses to call
    this at all when it has no sheet_index, precisely to keep that
    plan-mode fallback unreachable from a repair decision.
    """
    from scripts.coverage_to_app import generate_storyboard_sheet_for_scene

    return await generate_storyboard_sheet_for_scene(
        video_id, tenant_id, scene=scene, beat=beat, plan_only=False, progress=progress,
    )


def _card_material(finding: dict) -> dict:
    """TASTE_QUESTION shape for the Review feed (A7, not built here) — a
    directorial-preference call surfaces for a human to look at, never
    auto-acted, never even fingerprint-recorded (there is no defect to
    remember, only a preference to ask about)."""
    return {
        "classification": finding.get("classification"),
        "failure_class": finding.get("failure_class"),
        "rule_id": finding.get("rule_id"),
        "description": finding.get("description"),
        "panel": finding.get("panel"),
        "sheet_index": finding.get("sheet_index"),
        "decisive_prompt_fragment": finding.get("decisive_prompt_fragment"),
    }


async def repair_board_finding(
    tenant_id: str,
    video_id: str,
    scene: int,
    finding: dict,
    *,
    sheet_index: Optional[int] = None,
    is_frozen_fn: Callable[..., Awaitable[bool]] = is_frozen,
    budget_check: Callable[..., Awaitable] = arbiter_budget_check,
    reroll_fn: Optional[Callable[..., Awaitable[dict]]] = None,
    record_finding_fn: Callable[..., Awaitable[dict]] = record_finding,
    ledger_write: Optional[Callable[..., Awaitable]] = None,
    projected_cost: float = DEFAULT_BOARD_REPAIR_QUOTE,
) -> dict:
    """Decide-and-act on ONE board-station finding (a single panel verdict
    dict from ``frame_arbiter.judge_board_sheet``'s ``findings`` list).

    ``sheet_index`` names which saved board (1-5) to re-roll if this finding
    repairs — pass it explicitly (the caller, A6, already knows which sheet
    it judged) or set it on ``finding["sheet_index"]``; either works, the
    explicit kwarg wins when both are given. A MODEL_DEFECT finding with no
    resolvable sheet_index is refused before the freeze/budget/roll ladder
    even starts (see ``_default_board_reroll``'s docstring for why beat=None
    is dangerous here, not just invalid).

    All five DB/network boundaries are dependency-injected (same convention
    ``judge_board_sheet``/``judge_frame`` already use) so every test in
    tests/functional/test_d5_a5_repair.py runs at $0 with no live DB.

    Returns one of these shapes (``acted`` distinguishes "money moved / a
    fingerprint occurrence was recorded" from "nothing happened"):
      - TASTE_QUESTION:      {"acted": False, "action": "card", "card": {...}}
      - AUTHORING_DEFECT:    {"acted": False, "action": "filed", "fingerprint_record": {...}}
      - missing sheet_index: {"acted": False, "action": "missing_sheet_index"}
      - frozen fingerprint:  {"acted": False, "action": "frozen", "fingerprint": "..."}
      - budget breach:       {"acted": False, "action": "budget_refused", "breach": {...}}
      - reroll failure:      {"acted": False, "action": "reroll_failed", "reroll_result": {...}}
      - repaired:            {"acted": True, "action": "repaired", "reroll_result": {...}, "fingerprint_record": {...}}
      - anything else:       {"acted": False, "action": "none", "reason": "..."}
    """
    classification = str(finding.get("classification") or "").strip().upper()
    failure_class = finding.get("failure_class")
    rule_id = finding.get("rule_id")
    beat = sheet_index if sheet_index is not None else finding.get("sheet_index")

    # TASTE_QUESTION: never acts, not even a fingerprint write.
    if classification == "TASTE_QUESTION":
        return {"acted": False, "action": "card", "reason": "taste_question", "card": _card_material(finding)}

    # AUTHORING_DEFECT: never repairs (the SPEC authored the flaw, not the
    # pixels) — files the occurrence so the ratchet still tracks it, no spend.
    if classification == "AUTHORING_DEFECT":
        record = await record_finding_fn(
            tenant_id, rule_id=rule_id, stage=FRAME_QA_STAGE,
            failure_class=failure_class, classification=classification,
        )
        return {"acted": False, "action": "filed", "reason": "authoring_defect", "fingerprint_record": record}

    if classification != "MODEL_DEFECT":
        # Includes NO_FINDING/"OK" (should never reach this function from a
        # real caller — only classified defects do) and any unrecognized
        # value: fails closed to "did nothing", never guesses a bucket.
        return {"acted": False, "action": "none", "reason": f"unrecognized_classification:{classification!r}"}

    if beat is None:
        return {"acted": False, "action": "missing_sheet_index", "reason": "no sheet_index to re-roll"}

    # =========================================================================
    # MODEL_DEFECT repair ladder: FREEZE -> BUDGET -> ROLL -> RECORD.
    # Order is load-bearing and unit-tested — see module docstring.
    # =========================================================================

    # 1. FREEZE FIRST. A frozen class must not even consume budget quota —
    #    checked before arbiter_budget_check, not after.
    frozen = await is_frozen_fn(
        tenant_id, rule_id=rule_id, stage=FRAME_QA_STAGE, failure_class=failure_class,
    )
    if frozen:
        return {
            "acted": False, "action": "frozen",
            "reason": "fingerprint_frozen_root_cause_only_no_third_roll",
            "fingerprint": fingerprint_key(rule_id, failure_class),
        }

    # 2. BUDGET. Checked BEFORE the reroll fires, never audited after (DoC #3).
    breach = await budget_check(tenant_id, video_id, scene, projected_cost)
    if breach:
        return {"acted": False, "action": "budget_refused", "breach": breach}

    # 3. ROLL. Same call shape as
    #    POST /api/pipeline/storyboard-images/{video_id}?scene=N&beat=M —
    #    the underlying function, never HTTP.
    roll = reroll_fn or _default_board_reroll
    reroll_result = await roll(video_id, tenant_id, scene=scene, beat=beat)
    if not isinstance(reroll_result, dict) or reroll_result.get("status") == "failed":
        return {"acted": False, "action": "reroll_failed", "reroll_result": reroll_result}

    writer = ledger_write or record_frame_qa_entry
    await writer(
        tenant_id=tenant_id, video_id=video_id, scene=scene, model=REPAIR_MODEL,
        units=1, unit_cost=projected_cost, actual_cost=projected_cost,
        fingerprint=fingerprint_key(rule_id, failure_class),
    )

    # 4. RECORD. Deliberately LAST — this occurrence is the ratchet's own
    #    signal. On a fingerprint's 2nd repair, THIS call is what crosses
    #    the freeze threshold (A2's violation_count hits 2 here); a 3rd
    #    occurrence never reaches this line at all (blocked at step 1).
    record = await record_finding_fn(
        tenant_id, rule_id=rule_id, stage=FRAME_QA_STAGE,
        failure_class=failure_class, classification=classification,
    )
    return {"acted": True, "action": "repaired", "reroll_result": reroll_result, "fingerprint_record": record}


async def rejudge_board_after_repair(
    tenant_id: str,
    video_id: str,
    scene: int,
    sheet: dict,
    *,
    judge_fn: Callable[..., Awaitable[dict]] = judge_board_sheet,
    **judge_kwargs: Any,
) -> dict:
    """Post-repair re-judgment hook shape (A5 build item 3). ONE re-
    judgment of the just-rerolled sheet, via the SAME ``judge_board_sheet``
    call the original judgment used — same budget/ledger/fingerprint
    contract, no separate re-judge pathway to drift from the primary one.

    This function does not decide anything and does not loop: it calls
    ``judge_fn`` exactly once and returns whatever it returns. The "no
    third roll" guarantee is structural, not a check written here — a
    STILL-FAILING MODEL_DEFECT verdict on the SAME fingerprint causes
    ``judge_board_sheet``'s own (already-existing) ``record_finding_fn``
    call to record that fingerprint's occurrence again, which is what
    crosses the freeze threshold; any LATER call to
    ``repair_board_finding`` for that fingerprint is what actually gets
    turned away (step 1 of its ladder). This function never calls
    ``repair_board_finding`` itself, by design — chaining a third roll
    would require this function to do so, and it structurally cannot.

    A6 schedules exactly one call to this function right after a
    successful ``repair_board_finding`` reroll (its ``reroll_result``
    tells the caller which sheet/beat/scene to re-fetch and re-judge) —
    the scheduling, the pipeline hook, and any Review-feed surfacing of
    the re-judgment's own findings are A6's job, not built here.
    """
    return await judge_fn(tenant_id, video_id, scene, sheet, **judge_kwargs)


# =============================================================================
# Frame-level repair — FROZEN pending D5-A3b-2 (tasks/loop-checklist.md).
#
# The A3b eval harness split verdict (2026-07-29, commit 8e2cb78d): the
# BOARD station graduated (5/5 known defects, correct class, $0.0273/call)
# — trustworthy, wired above. The FRAMES station did NOT graduate (best
# 1/3 known defects correctly classified; false-positive and cost bars
# were met, but classification accuracy was not). Wiring real repair spend
# to an unreliable judge's verdicts would mean paying to "fix" defects the
# judge imagined and missing the ones that were real — worse than no
# auto-repair at all. This constant is what makes doing that BY ACCIDENT
# impossible: nothing below this line can spend a dollar while it reads
# False, and nothing else in this module (or FRAME_REPAIR_ENABLED's own
# read site) can be reached without going through this exact check.
#
# GRADUATION BAR THAT UNLOCKS THIS (verbatim from tasks/loop-checklist.md's
# D5-A3b-2 entry — do not paraphrase this looser when the day comes to flip
# it): (1) re-adjudicate the disputed "facing" fixture label with Ryan as
# label authority against the POST-re-roll frames (two rubric configs and
# the eval worker's own visual read all disagreed with the original label
# — the fixture may be teaching the judge a wrong lesson); (2) rescore
# duplicate-detection at CLUSTER level, not anchor-frame level (the judge
# correctly flags a cluster of near-identical frames but won't agree with
# the fixture on which ONE frame is "the" anchor — score the cluster as
# caught, not the specific frame named); plus a FRESH eval budget quoted
# to Ryan and spent under his go-ahead (the A3b budget is already spent:
# $0.2942 of $0.30, stopped in time, nothing left to re-run against).
#
# Per the contract-triangle law this whole mission already follows (D5's
# own "Ryan's ruling reaches prompt + gate + repair in the SAME commit"
# rule): this flag flips to True ONLY in the SAME commit that also builds
# the real repair_frame_finding logic, once that graduation report lands
# — never flipped alone, never flipped speculatively ahead of the eval.
# =============================================================================
FRAME_REPAIR_ENABLED = False


async def repair_frame_finding(finding: dict, *args: Any, **kwargs: Any) -> dict:
    """Frame-level auto-repair — deliberately UNBUILT. Raises whenever
    ``FRAME_REPAIR_ENABLED`` is False, which is the shipped default, so
    this cannot get wired into a real pipeline hook by accident, nor by a
    future worker's enthusiasm to "just finish the other half" before the
    A3b-2 gate actually clears. See ``FRAME_REPAIR_ENABLED``'s own comment
    for the exact bar that has to be met first.

    Flipping ``FRAME_REPAIR_ENABLED`` to True in a TEST is fine and
    expected (tests/functional/test_d5_a5_repair.py does exactly that, to
    prove this stub's other branch is reachable at all — the mechanism
    itself must work, only the default must be off). Flipping it in
    product code without the graduation report landing in the same commit
    is exactly the accident this exists to prevent.
    """
    if not FRAME_REPAIR_ENABLED:
        raise RuntimeError(
            "Frame-level auto-repair is FROZEN pending D5-A3b-2 "
            "(tasks/loop-checklist.md) — the frames-station judge scored "
            "only 1/3 known defects correctly classified in its A3b eval "
            "and is not trustworthy enough to spend real money on its "
            "verdicts yet. Do not set FRAME_REPAIR_ENABLED=True without a "
            "fresh A3b-2 graduation report landing in the SAME commit as "
            "the real repair_frame_finding logic (contract-triangle law)."
        )
    return {
        "acted": False,
        "action": "frame_repair_stub_enabled_but_unimplemented",
        "finding": finding,
    }
