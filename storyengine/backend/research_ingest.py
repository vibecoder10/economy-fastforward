"""External-submission ingest gate for RESEARCH (checklist C47 ingest half —
decisions.md 2026-07-19 "MCP economics" entry: the connected agent does
research on the user's Claude subscription and hands StoryEngine the
RESULT, instead of StoryEngine spending its own paid `research` verb to
produce it).

Mirrors ``user_script.accept_external_script`` (C46d)'s shape exactly —
same module-per-domain layering, same "shape-validate, gate, save-and-
advance-honestly, never silently rewrite the submission" posture — but for
``videos.research_payload`` instead of ``videos.script``:

  1. **Shape validation** (``_validate_research_shape``): the payload must be
     the same dict shape ``pipeline_executor.run_research`` itself produces
     and every downstream reader (``_roster_validation``,
     ``enrich_research_payload_readiness``, ``_machine_bucket_summary``,
     ``_run_unit_research_hold``) already assumes without re-checking —
     list-typed keys must actually be lists, dict-typed keys must actually be
     dicts. A malformed submission fails HERE with a concrete field name,
     not later as an opaque ``AttributeError`` deep in a pipeline stage that
     assumed a well-formed payload.

  2. **The SAME roster gate ``run_research`` applies before saving**
     (``pipeline_executor._roster_validation``, reused verbatim — not
     reimplemented): a complete-title (documentary/roster) video whose
     submitted research doesn't clear the deterministic roster-completeness
     checks is REJECTED, with the exact same warnings/gaps a real research
     run would have surfaced, so the submitting agent can fix its own
     research and resubmit — same "reject with a concrete list, no silent
     server-side rewrite" contract ``accept_external_script`` uses for
     scripts.

  3. **Scope boundary, stated plainly**: this does NOT run
     ``PipelineExecutor._run_unit_research_hold`` — the expensive per-machine
     LIVE source-fetch/verification pass ``run_research`` runs AFTER the
     roster gate for machine-documentary videos. That step re-fetches and
     re-verifies sources over the network; it is a distinct, separately
     billable action, not a shape or gate check. An externally-submitted
     payload is trusted the same way a creator's own verbatim script is
     trusted by ``set_user_script`` — accepted on the strength of the roster
     gate's deterministic checks, not re-verified fact by fact. If that
     trust posture turns out to be wrong in practice, running the hold step
     against a submitted payload is a follow-up, not silently done here.

  4. **Save + advance**: on a pass, writes ``research_payload``/``thesis``/
     ``executive_hook``/``status``/``research_skipped`` through the EXACT
     SAME UPDATE ``run_research`` itself issues (checklist's "same validated
     store+advance paths run_research uses").

Attribution note: unlike ``videos.script_source`` (script_source =
'agent_submitted' distinguishes an external script from a platform-generated
one forever, in a real column), ``research_payload`` has no sibling
provenance column — this module logs the submitting ``source`` string
(caller attribution) rather than persisting it, an honest gap flagged here
rather than invented a new schema column past this chunk's "no new logic"
scope.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from database import execute, fetch_one

logger = logging.getLogger(__name__)

# Keys pipeline_executor.py's own readers (`_roster_validation`,
# `enrich_research_payload_readiness`, `_machine_bucket_summary`,
# `_run_unit_research_hold`) immediately iterate/index as a list — a caller
# handing back a dict or a string here would crash one of those readers with
# an opaque error deep inside a later pipeline stage instead of here.
_LIST_KEYS = (
    "unit_roster", "unit_research_cards", "machine_research_cards",
    "research_cards", "recommended_final_roster", "gap_hunt_matrix",
    "edge_case_matrix", "operator_decision_points",
)
# Keys those same readers immediately treat as a mapping (``.get``/``.values``).
_DICT_KEYS = ("machine_discovery_buckets", "roster_audit", "machine_raw_source_packages")


def _validate_research_shape(payload: Any) -> None:
    """Raises ``ValueError`` with a concrete field name on the first shape
    problem found. A payload with none of the optional roster/card keys at
    all is still valid — most videos aren't machine-roster documentaries;
    ``run_research`` itself never requires them either."""
    if not isinstance(payload, dict) or not payload:
        raise ValueError("payload must be a non-empty object")
    for key in _LIST_KEYS:
        if key in payload and payload[key] is not None and not isinstance(payload[key], list):
            raise ValueError(f"{key} must be a list when present")
    for key in _DICT_KEYS:
        if key in payload and payload[key] is not None and not isinstance(payload[key], dict):
            raise ValueError(f"{key} must be an object when present")


async def accept_submitted_research(
    tenant_id, video_id: str, payload: dict, *, source: str = "agent_submitted",
) -> dict:
    """Ingest gate for an EXTERNALLY-SUBMITTED research payload — the
    ``submit_research`` MCP tool's implementation.

    Returns a dict:
      - reject: ``{"accepted": False, "reason": "roster_gate_failed",
        "warnings": [...], "gaps": [...]}``
      - accept: ``{"accepted": True, "status": <new video status>,
        "headline": ..., "roster_check": {...}}``

    Raises ``ValueError`` on a missing video or an unusable payload shape.
    """
    video = await fetch_one(
        "SELECT * FROM videos WHERE id = $1 AND tenant_id = $2 AND deleted_at IS NULL",
        video_id, tenant_id,
    )
    if not video:
        raise ValueError("Video not found")

    _validate_research_shape(payload)

    topic = video.get("video_title") or video.get("headline") or ""
    from pipeline_executor import _roster_validation

    roster_check = _roster_validation(topic, payload, video_length_minutes=video.get("video_length_minutes"))
    if roster_check.get("complete_title") and not roster_check.get("passed"):
        logger.info(
            "[research_ingest] rejected submission for video %s from %s — roster gate failed",
            video_id, source,
        )
        return {
            "accepted": False,
            "reason": "roster_gate_failed",
            "warnings": roster_check.get("warnings", []),
            "gaps": roster_check.get("gaps", []),
        }

    payload = dict(payload)
    payload["unit_roster_validation"] = roster_check
    next_status = "ready_for_scripting"

    from pipeline_executor import PipelineExecutor

    save_result = await execute(
        """UPDATE videos SET
               research_payload = $1,
               thesis = $2,
               executive_hook = $3,
               status = $4,
               research_skipped = FALSE,
               updated_at = now()
           WHERE id = $5 AND tenant_id = $6""",
        json.dumps(payload),
        payload.get("thesis", ""),
        payload.get("executive_hook", ""),
        next_status,
        video_id, tenant_id,
    )
    if PipelineExecutor._db_write_missed(save_result):
        raise ValueError("Video not found")

    logger.info("[research_ingest] accepted submission for video %s from %s", video_id, source)

    # C3: same roster-time reference prefetch hook run_research (the paid
    # verb) fires on its own success path — this is the free submit_research
    # ingest's equivalent seam. Fire-and-forget; never blocks/fails the
    # accept response.
    from static_docu import dispatch_roster_prefetch
    dispatch_roster_prefetch(video, video_id, tenant_id)

    return {
        "accepted": True,
        "status": next_status,
        "headline": payload.get("headline"),
        "roster_check": roster_check,
    }
