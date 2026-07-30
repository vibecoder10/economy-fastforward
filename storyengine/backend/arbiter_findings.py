"""Per-instance Frame Arbiter findings (D8 chunk 3b, found by D8-3).

D8-3 built the Review feed's Findings tab (routes/review.py get_findings)
honestly reporting that only two tables were real: arbiter_fingerprints
(migration 139, A2) — a CLASS of defect, not a single frame/panel — and
generation_ledger's frame_qa rows (migration 140, A1) — spend, not content.
frame_arbiter.py's own judge calls (judge_frame / judge_scene_batch /
judge_board_sheet) return a per-instance "findings" list every single time
they run, but nothing ever wrote it anywhere. This module is that missing
write path: migrations/146_arbiter_findings.sql's table, plus the one thin
function (record_finding_instances) that shapes a judge call's findings list
into rows for it.

Field names are copied verbatim from the finding dicts frame_arbiter.py
actually returns — see that module's docstring and this migration's own
comment for the full mapping. Two identity vocabularies (`image_index` for
the frame/scene_batch stations, `panel` for the board station) are folded
into one generic `reference` TEXT column, tagged by `station` — see
_reference_and_label below, the one place that mapping happens.

Advisory only, mirroring task_store.db_persist_task's own "all failures are
swallowed" contract: the caller (frame_arbiter_hook.run_after_storyboard_
sheet) must NEVER have a persistence failure here break the storyboard
stage or skip the freeze/budget logic that already runs around the judge
call. record_finding_instances therefore catches its own exceptions
per-row (one malformed finding never blocks the rest of the batch) and
never raises — same as the hook's own try/except at its call site in
pipeline_executor.PipelineExecutor.run_storyboard_sheet.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from database import execute

logger = logging.getLogger(__name__)

# Mirrors frame_arbiter.py's own _ALL_VERDICTS / arbiter_fingerprints.
# CLASSIFICATIONS union — the table's CHECK constraint accepts the same
# four values parse_verdict can ever produce (the three defect buckets plus
# OK, frame_arbiter.NO_FINDING).
_VALID_CLASSIFICATIONS = {"MODEL_DEFECT", "AUTHORING_DEFECT", "TASTE_QUESTION", "OK"}

_VALID_STATIONS = {"frame", "scene_batch", "board"}


def _reference_and_label(station: str, finding: dict) -> tuple[str, Optional[str]]:
    """The one place the two per-station identity vocabularies
    (frame_arbiter.judge_frame/judge_scene_batch's `image_index`+`shot_type`
    vs. judge_board_sheet's `panel`+`label`) get folded into this table's
    generic `reference`/`label` columns — no third vocabulary invented."""
    if station == "board":
        return f"panel {finding.get('panel')}", finding.get("label")
    return f"image_index {finding.get('image_index')}", finding.get("shot_type")


def _finding_cost(finding: dict, call_cost: Optional[float]) -> Optional[float]:
    """judge_frame's finding dict carries its OWN `cost` (one vision call per
    frame). judge_scene_batch/judge_board_sheet's per-finding dicts do not —
    their cost is call-level (one call judges every frame/panel at once, see
    those functions' own ledger-write comments) and is passed down as
    `call_cost` by the caller instead. Per-finding cost wins when present."""
    own_cost = finding.get("cost")
    return own_cost if own_cost is not None else call_cost


async def record_finding_instances(
    tenant_id: Any,
    video_id: Any,
    scene: Optional[int],
    station: str,
    findings: list[dict],
    *,
    call_cost: Optional[float] = None,
    image_url: Optional[str] = None,
) -> list[dict]:
    """Writes one `arbiter_findings` row per JUDGED entry in `findings`.

    `findings` is exactly the list frame_arbiter.judge_frame/judge_scene_
    batch/judge_board_sheet already returns — an entry with `skipped: True`
    (a download/vision/parse failure, or a budget refusal) carries no
    classification and is NOT a delivered judgment, so it is skipped here
    too, never persisted as a fabricated verdict (the same fail-closed law
    frame_arbiter.py itself follows). Every other entry (OK included — an
    OK verdict is still a real, delivered judgment, not just the three
    defect buckets) gets one row.

    station must be one of frame_arbiter.py's three judge functions'-worth
    of identity: 'frame' (judge_frame), 'scene_batch' (judge_scene_batch),
    'board' (judge_board_sheet) — an unrecognized station raises ValueError
    at the top (a caller bug, not a runtime data problem, so this one fails
    loud rather than swallowing it like the per-row writes below).

    Never raises past this function — a bad individual finding dict (a
    caller bug, a shape change upstream) is logged and skipped, and any
    write failure for one row does not stop the rest of the batch. Returns
    the list of finding dicts that were actually written, for callers/tests
    that want to assert on them.
    """
    if station not in _VALID_STATIONS:
        raise ValueError(f"invalid station: {station!r} (must be one of {sorted(_VALID_STATIONS)})")

    written: list[dict] = []
    for finding in findings or []:
        if not finding or finding.get("skipped"):
            continue  # no delivered judgment here — nothing to persist
        classification = (finding.get("classification") or "").strip().upper()
        if classification not in _VALID_CLASSIFICATIONS:
            logger.warning(
                "arbiter_findings: skipping finding with unrecognized classification %r "
                "(tenant=%s video=%s scene=%s station=%s)",
                finding.get("classification"), tenant_id, video_id, scene, station,
            )
            continue
        reference, label = _reference_and_label(station, finding)
        try:
            await execute(
                """INSERT INTO arbiter_findings
                     (tenant_id, video_id, scene, station, reference, label, image_url,
                      classification, failure_class, rule_id, fingerprint_key,
                      rubric_level, decisive_prompt_fragment, description,
                      new_vs_previous, cost)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)""",
                tenant_id, video_id, scene, station, reference, label, image_url,
                classification, finding.get("failure_class"), finding.get("rule_id"),
                finding.get("rule_id") or finding.get("failure_class"),
                finding.get("rubric_level"), finding.get("decisive_prompt_fragment"),
                finding.get("description"), finding.get("new_vs_previous"),
                _finding_cost(finding, call_cost),
            )
            written.append(finding)
        except Exception:  # noqa: BLE001 - advisory persistence, never blocks the caller
            logger.exception(
                "arbiter_findings: failed to persist finding (tenant=%s video=%s scene=%s "
                "station=%s reference=%s) — continuing, this must never fail the stage",
                tenant_id, video_id, scene, station, reference,
            )
    return written
