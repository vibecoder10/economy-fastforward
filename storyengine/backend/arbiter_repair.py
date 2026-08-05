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
  - MODEL_DEFECT -> the repair ladder below (freeze -> budget -> roll).
  - AUTHORING_DEFECT -> never repairs (the PROMPT/SPEC authored the flaw —
    redrawing the same spec would just reproduce it) and returns, no
    spend, no ratchet write here (see the ruling below for why).
  - TASTE_QUESTION -> never acts at all; returns card material for the
    Review feed (A7) — nothing wrong to remember, only a preference to
    surface to a human.

RULING (coordinator, same session as this chunk, resolving the question
this file originally flagged as open): fingerprint occurrences are
recorded at JUDGMENT TIME ONLY. A finding and its own immediate repair
are ONE occurrence of the mistake, not two — repairs are ACTIONS ON
findings, not findings themselves, so nothing in this module ever calls
``record_finding``. ``frame_arbiter.judge_board_sheet`` is the single
writer, for every classification, always. The second strike that crosses
the freeze is either the post-repair re-judge (``rejudge_board_after_
repair`` below, itself just another call into ``judge_board_sheet``)
still finding the SAME fingerprint, or that fingerprint recurring in some
later, unrelated judgment (another sheet/scene/batch) — never this
module's own bookkeeping. A6 inherits this as settled, not open.

Repair ladder order still matters and is unit-tested (see
tests/functional/test_d5_a5_repair.py): FREEZE is checked before BUDGET,
so a frozen fingerprint never consumes budget quota just to be told no —
consistent with DoC #3's "checked BEFORE any paid call fires, never
audited after" law applying to the freeze gate too. Only after both gates
clear does the sheet re-roll fire. The ledger write (real dollars spent
on the redraw) still happens on a successful roll — that is metering
money spent, a completely different bookkeeping axis from the
fingerprint ratchet this module now stays out of entirely.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from arbiter_fingerprints import fingerprint_key, is_frozen
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
    """Real reroll call — goes through ``PipelineExecutor.run_storyboard_sheet``
    (pipeline_executor.py), the SAME judged-road wrapper
    ``POST /api/pipeline/storyboard-images/{video_id}?scene=N&beat=M``
    calls (routes/pipeline.py's ``run_storyboard_images`` handler), called
    DIRECTLY here, never over HTTP. Lazy import mirrors that route's own
    convention (the import lives inside its background-task closure, not
    at module top) so importing arbiter_repair never pulls in
    pipeline_executor's own (heavier) import graph for a caller who only
    wants the pure decision-ladder logic (e.g. every test in
    tests/functional/test_d5_a5_repair.py).

    D15-4: this used to call ``scripts.coverage_to_app.
    generate_storyboard_sheet_for_scene`` directly, bypassing the wrapper.
    Routed through the wrapper instead because ``beat`` is ALWAYS non-None
    here (see below) and ``run_storyboard_sheet``'s own Frame Arbiter hook
    guard (pipeline_executor.py, the ``if (scene is not None and beat is
    None and not plan_only ...)`` condition right after the underlying call)
    only fires the hook when ``beat is None`` — so a beat-scoped repair call
    can NEVER re-trigger ``run_after_storyboard_sheet`` and loop back into
    this same repair ladder. Proven directly (not just inferred from
    reading the guard) by
    tests/functional/test_d15_4_arbiter_repair_routing.py, which drives a
    REAL beat-scoped call through this function with the arbiter flag
    scoped in and asserts the hook is never awaited — same call-tracking
    approach test_d15_3_wrapper_param_forwarding.py's own beat-scoped test
    uses, since the hook call is wrapped in a try/except inside
    run_storyboard_sheet that a boom-on-call assertion would get silently
    swallowed by. Going through the wrapper also picks up its static_docu
    guard for free (a MODEL_DEFECT finding could only ever exist for a
    video that already generates generic storyboard sheets, so this is a
    belt-and-suspenders safety net, not a behavior change for any real
    finding).

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
    from pipeline_executor import PipelineExecutor

    return await PipelineExecutor(tenant_id).run_storyboard_sheet(
        video_id, scene=scene, beat=beat, plan_only=False, progress=progress,
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

    This function NEVER calls ``record_finding`` (see the module docstring's
    RULING) — it only decides whether to spend, spends or doesn't, and
    returns. The fingerprint ratchet is judge_board_sheet's job alone, at
    judgment time, both for the original finding and for the post-repair
    re-judgment (``rejudge_board_after_repair`` below).

    All DB/network boundaries are dependency-injected (same convention
    ``judge_board_sheet``/``judge_frame`` already use) so every test in
    tests/functional/test_d5_a5_repair.py runs at $0 with no live DB.

    Returns one of these shapes (``acted`` means "money moved / a real
    reroll fired"):
      - TASTE_QUESTION:      {"acted": False, "action": "card", "card": {...}}
      - AUTHORING_DEFECT:    {"acted": False, "action": "no_repair", "reason": "authoring_defect"}
      - missing sheet_index: {"acted": False, "action": "missing_sheet_index"}
      - frozen fingerprint:  {"acted": False, "action": "frozen", "fingerprint": "..."}
      - budget breach:       {"acted": False, "action": "budget_refused", "breach": {...}}
      - reroll failure:      {"acted": False, "action": "reroll_failed", "reroll_result": {...}}
      - repaired:            {"acted": True, "action": "repaired", "reroll_result": {...}}
      - anything else:       {"acted": False, "action": "none", "reason": "..."}
    """
    classification = str(finding.get("classification") or "").strip().upper()
    failure_class = finding.get("failure_class")
    rule_id = finding.get("rule_id")
    beat = sheet_index if sheet_index is not None else finding.get("sheet_index")

    # TASTE_QUESTION: never acts.
    if classification == "TASTE_QUESTION":
        return {"acted": False, "action": "card", "reason": "taste_question", "card": _card_material(finding)}

    # AUTHORING_DEFECT: never repairs (the SPEC authored the flaw, not the
    # pixels). Already recorded by judge_board_sheet at judgment time —
    # this module writes nothing, ever (see the RULING above).
    if classification == "AUTHORING_DEFECT":
        return {"acted": False, "action": "no_repair", "reason": "authoring_defect"}

    if classification != "MODEL_DEFECT":
        # Includes NO_FINDING/"OK" (should never reach this function from a
        # real caller — only classified defects do) and any unrecognized
        # value: fails closed to "did nothing", never guesses a bucket.
        return {"acted": False, "action": "none", "reason": f"unrecognized_classification:{classification!r}"}

    if beat is None:
        return {"acted": False, "action": "missing_sheet_index", "reason": "no sheet_index to re-roll"}

    # =========================================================================
    # MODEL_DEFECT repair ladder: FREEZE -> BUDGET -> ROLL.
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
    #    the underlying function, never HTTP. No record_finding call here or
    #    after — the ratchet only moves through judge_board_sheet, via the
    #    post-repair rejudge_board_after_repair below.
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

    return {"acted": True, "action": "repaired", "reroll_result": reroll_result}


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

    This is where the SECOND strike actually happens, per the module
    docstring's RULING: the original finding was strike one (recorded by
    judge_board_sheet at judgment time); repair_board_finding's own reroll
    recorded nothing. If THIS re-judgment still comes back MODEL_DEFECT on
    the SAME fingerprint, judge_board_sheet's own (already-existing)
    record_finding_fn call records that as the fingerprint's second
    occurrence — which is what crosses the freeze threshold. If the
    re-judgment comes back clean (OK), judge_board_sheet never calls
    record_finding_fn at all (an OK verdict isn't one of A2's three defect
    buckets) and the fingerprint stays at one occurrence, unfrozen.

    This function does not decide anything and does not loop: it calls
    ``judge_fn`` exactly once and returns whatever it returns. The "no
    third roll" guarantee is structural, not a check written here — any
    LATER call to ``repair_board_finding`` for a fingerprint that just
    crossed the freeze here is what actually gets turned away (step 1 of
    its ladder). This function never calls ``repair_board_finding``
    itself, by design — chaining a third roll would require this function
    to do so, and it structurally cannot.

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
