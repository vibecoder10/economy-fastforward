"""DVSU research pipeline v2 - Call 1 (thesis+acts) and Call 2 (roster+shared context).

Implements, verbatim, the "Call 1" and "Call 2" sections of
``storyengine/docs/dvsu-research-pipeline-v2-2026-09-18/DESIGN.md``. Call 3
(per-machine research packet) is a separate, later chunk and is not in this
module.

This replaces ``research/agent.py``'s roster-selection call *and*
``roster_coverage.audit_roster_selection``'s independent-audit/repair-loop
for videos on the ``factual_100_v1`` machine-script contract only - see
``pipeline_executor.py::run_roster_selection``'s contract gate
(``factual_machine_research.is_factual_machine_contract``). Do not modify
``research/agent.py`` here: it has other callers (the separate Airtable-
driven orchestrator pipeline) and still serves the non-factual-contract
fallback branch of ``run_roster_selection``.

Design intent (quoting DESIGN.md): "No separate roster-validation pass by
design - a machine that can't find real sources at Stage 3 is the
validation. This intentionally removes the current pipeline's separate
roster-coverage audit / repair-loop complexity." This module therefore never
calls ``roster_coverage.audit_roster_selection`` and never retries itself;
the caller runs the existing purely-structural
``roster_selection.selection_validation`` once against this module's output.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

# Same sys.path pattern as pipeline_executor.py - this module can be imported
# on its own (e.g. by tests) before pipeline_executor.py has run its own
# insert, and its lazily-imported `shared.*`/`orchestrator.*` dependencies
# live under skills/video-pipeline, not on the default path.
_PIPELINE_PATH = Path(__file__).parent.parent.parent / "skills" / "video-pipeline"
if str(_PIPELINE_PATH) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_PATH))

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Call 1 - Thesis + Acts (no search, cheap, once per video)
# ---------------------------------------------------------------------------

CALL1_SYSTEM_PROMPT = (
    "You are a documentary structure analyst for DvsU, an engineering-history channel. DvsU videos are "
    "not about machines - they are about one engineering argument, proven through a sequence of machines. "
    "War is the setting. Engineering is the story."
)


def _call1_user_prompt(title: str) -> str:
    return (
        f'Video title: "{title}"\n'
        "\n"
        "Formulate ONE thesis for this video - a single engineering argument the whole video will prove.\n"
        "Strong theses read like: \"Britain kept cancelling the right tank and building the wrong one.\"\n"
        "Then break that thesis into 4-7 acts. Each act is one sentence describing a distinct step in the\n"
        "argument, NOT a time period. Example acts: \"The missile replaces the gun.\" / \"The carrier becomes\n"
        "a country.\" Moving between acts should feel like the argument shifting, not a timeline advancing.\n"
        "\n"
        "Return only JSON: {\"thesis\": \"...\", \"acts\": [{\"act_number\": 1, \"argument\": \"one sentence\"}, ...]}"
    )


# ---------------------------------------------------------------------------
# Call 2 - Roster + shared context (1 search-enabled call, once per video)
# ---------------------------------------------------------------------------

CALL2_SYSTEM_PROMPT = (
    "You research real named military machines using web search. You never invent a machine, a "
    "production number, or a date - every claim must trace to a search result. Output only the "
    "requested JSON."
)

# DESIGN.md: "find 20-25 real, specifically-named machines" in ONE call. Not
# a per-machine budget (that's Call 3's job) - a budget wide enough for the
# model to run several searches while pinning down 20-25 distinct, sourced
# names in one pass. Picked from the middle of the brief's suggested 8-15
# range: this call does meaningfully more search work than
# roster_coverage.audit_roster_selection's identity-only check (which uses
# selection_search_budget's count+4, capped [12,40]) since it is discovering
# the roster, not just verifying one.
CALL2_SEARCH_BUDGET = 15


# "Every / all / ever built" titles promise the whole category. The thesis
# filter above ("keep only the stronger one") silently broke that promise on
# 2026-09-23: "Every US Battleship Class Ever Built" came back with five
# single Iowa-class ships and ~9 classes missing. For these titles the
# category sets the roster and the runtime follows it (run_roster_selection).
_COMPLETE_ROSTER_INSTRUCTIONS = (
    "This title promises EVERY member of its category, so completeness overrides the thesis filter.\n"
    "Using web search, list every real member of the category the title names - for a class title, every\n"
    "class, one entry per class, named as the class (e.g. \"Ajax class\"; a one-ship class is named by its\n"
    "ship). Never list two ships of the same class. Never drop a member because another proves the same\n"
    "point; leave one out only if the title itself excludes it (e.g. never built, when the title says\n"
    "\"ever built\"). There is no count limit - the video's runtime is sized to your list. Assign every\n"
    "machine to the act it best proves. Order machines chronologically within each act.\n"
)


def _call2_user_prompt(title: str, thesis: str, acts: list[dict]) -> str:
    from pipeline_executor import _title_needs_complete_roster

    act_lines = "\n".join(f"{act['act_number']}. {act['argument']}" for act in acts)
    if _title_needs_complete_roster(title):
        selection = _COMPLETE_ROSTER_INSTRUCTIONS
    else:
        selection = (
            "Using web search, find 20-25 real, specifically-named machines (not a category like \"destroyers\"\n"
            "or \"cruisers\" - one concrete named unit or named class, e.g. \"HMS Devastation\", \"Ajax class\") that\n"
            "together prove this thesis. Assign every machine to exactly one act - the machine must exist\n"
            "BECAUSE it proves that act's argument. If two machines would prove the same point, keep only the\n"
            "stronger one. Order machines chronologically within each act.\n"
        )
    return (
        f'Video title: "{title}"\n'
        f'Thesis: "{thesis}"\n'
        f"Acts:\n{act_lines}\n"
        "\n"
        + selection +
        "\n"
        "Also note 3-5 facts you encounter that apply across MULTIPLE machines rather than one specific\n"
        "unit (a shared technological shift, a doctrine change, an external event that reframes several\n"
        "entries) - these will be given to the per-machine research step as background, so it isn't\n"
        "re-discovered 20 times.\n"
        "\n"
        "Return only JSON: {\"roster\": [{\"machine\": \"...\", \"act_number\": 1}, ...],\n"
        "\"shared_context\": [\"...\", ...]}"
    )


def _normalize_acts(raw_acts: Any) -> list[dict]:
    if not isinstance(raw_acts, list):
        return []
    acts: list[dict] = []
    for index, item in enumerate(raw_acts, 1):
        if not isinstance(item, dict):
            continue
        argument = str(item.get("argument") or "").strip()
        if not argument:
            continue
        try:
            act_number = int(item.get("act_number"))
        except (TypeError, ValueError):
            act_number = index
        acts.append({"act_number": act_number, "argument": argument})
    return acts


def _normalize_roster(raw_roster: Any) -> list[dict]:
    if not isinstance(raw_roster, list):
        return []
    roster: list[dict] = []
    for item in raw_roster:
        if not isinstance(item, dict):
            continue
        machine = str(item.get("machine") or "").strip()
        if not machine:
            continue
        try:
            act_number = int(item.get("act_number"))
        except (TypeError, ValueError):
            act_number = 0
        roster.append({"machine": machine, "act_number": act_number})
    # DESIGN.md requires roster order to be act-order/chronological. Group by
    # act; a stable sort keeps each act's machines in the model's own
    # (already-chronological, per the prompt) order.
    roster.sort(key=lambda row: row["act_number"])
    return roster


def _normalize_shared_context(raw_context: Any) -> list[str]:
    if not isinstance(raw_context, list):
        return []
    return [str(item).strip() for item in raw_context if str(item or "").strip()]


async def _call_thesis_and_acts(client: Any, title: str, checkpoint_scope: Optional[dict]) -> dict:
    from shared.json_utils import parse_json_response
    from orchestrator.pipeline_constants import Models
    from shared.research_response import checkpoint_path, request_fingerprint

    prompt = _call1_user_prompt(title)
    system_prompt = CALL1_SYSTEM_PROMPT
    model = Models.CLAUDE_SONNET
    max_tokens = 1000
    temperature = 0.3
    response = await client.generate(
        prompt=prompt, system_prompt=system_prompt, model=model,
        max_tokens=max_tokens, temperature=temperature, complete_response=True,
        checkpoint_path=checkpoint_path(checkpoint_scope, request_fingerprint(
            prompt=prompt, system_prompt=system_prompt, model=model,
            max_tokens=max_tokens, temperature=temperature, tools=None,
        )),
    )
    raw = parse_json_response(response, default=None)
    if not isinstance(raw, dict):
        raise ValueError("Thesis/acts call returned invalid JSON")
    thesis = str(raw.get("thesis") or "").strip()
    acts = _normalize_acts(raw.get("acts"))
    if not thesis:
        raise ValueError("Thesis/acts call returned an empty thesis")
    if not acts:
        raise ValueError("Thesis/acts call returned no acts")
    return {"thesis": thesis, "acts": acts}


async def _call_roster_and_shared_context(
    client: Any, title: str, thesis: str, acts: list[dict], checkpoint_scope: Optional[dict],
) -> dict:
    from shared.clients.anthropic_client import WEB_SEARCH_TOOL
    from orchestrator.pipeline_constants import Models
    from shared.json_utils import parse_json_response
    from shared.research_response import checkpoint_path, request_fingerprint

    if getattr(client, "_gateway_mode", False):
        raise ValueError(
            "Roster discovery needs a web-search capable research provider; this gateway cannot execute web search"
        )

    prompt = _call2_user_prompt(title, thesis, acts)
    system_prompt = CALL2_SYSTEM_PROMPT
    model = Models.CLAUDE_SONNET
    max_tokens = 6000
    temperature = 0.4
    tools = [dict(WEB_SEARCH_TOOL, max_uses=CALL2_SEARCH_BUDGET)]
    response = await client.generate(
        prompt=prompt, system_prompt=system_prompt, model=model,
        max_tokens=max_tokens, temperature=temperature, tools=tools, complete_response=True,
        checkpoint_path=checkpoint_path(checkpoint_scope, request_fingerprint(
            prompt=prompt, system_prompt=system_prompt, model=model,
            max_tokens=max_tokens, temperature=temperature, tools=tools,
        )),
    )
    raw = parse_json_response(response, default=None)
    if not isinstance(raw, dict):
        raise ValueError("Roster/shared-context call returned invalid JSON")
    roster = _normalize_roster(raw.get("roster"))
    shared_context = _normalize_shared_context(raw.get("shared_context"))
    if not roster:
        raise ValueError("Roster/shared-context call returned no machines")
    return {"roster": roster, "shared_context": shared_context}


def validate_roster_structure(payload: dict, target_count: int) -> dict:
    """Purely structural gate for a v2 roster: right count, no duplicates.

    Deliberately does NOT call roster_selection.selection_validation /
    representative_warnings - that legacy checker enforces the OLD "exactly
    one named machine per class, recorded separately from class_name" policy,
    which directly conflicts with this pipeline's design: DESIGN.md's own
    Call 2 prompt allows and expects a roster entry to BE a class name (its
    worked example uses "Ajax class"). Confirmed live 2026-09-19: running the
    real deployed code against a real 20-class submarine roster, the old
    checker rejected every single entry ("choose one named machine, not a
    class") purely for containing the word "class" - which would block every
    "Every X Class Ever Built" video, this channel's flagship title format.
    Per DESIGN.md: "No separate roster-validation pass by design - a machine
    that can't find real sources at Stage 3 is the validation."
    """
    roster = payload.get("unit_roster") if isinstance(payload.get("unit_roster"), list) else []
    names: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for item in roster:
        if isinstance(item, dict):
            name = str(item.get("machine") or item.get("name") or item.get("title") or "").strip()
        else:
            name = str(item or "").strip()
        if not name:
            warnings.append("blank roster entry")
            continue
        key = re.sub(r"\s+", " ", name).casefold()
        if key in seen:
            warnings.append(f"duplicate roster entry: {name}")
        seen.add(key)
        names.append(name)
    if target_count is not None and len(names) != target_count:
        warnings.append(f"selected roster has {len(names)} entries; runtime target is exactly {target_count}")
    return {
        "passed": not warnings,
        "warnings": warnings,
        "hard_warnings": list(warnings),
        "soft_warnings": [],
        "needs_review": False,
        "complete_title": True,
        "roster_count": len(names),
        "target_count": target_count,
        "roster": names,
    }


async def run_thesis_roster_and_context(
    anthropic_client: Any, title: str, checkpoint_scope: Optional[dict] = None,
) -> dict:
    """Calls 1+2: thesis+acts, then roster+shared-context.

    Returns a draft shaped to slot directly into ``run_roster_selection``'s
    ``merged.update({key: value for key, value in draft.items() if key in
    selection_keys})`` pattern:
    ``{"thesis": str, "acts": [{"act_number": int, "argument": str}, ...],
    "unit_roster": [{"machine": str, "act_number": int}, ...],
    "shared_context": [str, ...]}``.
    ``unit_roster`` is sorted into act order.

    Also (fail-soft, never raises past this function) exports
    ``00-thesis-and-roster.md`` and ``01-shared-context.md`` to Google Drive
    per DESIGN.md's "Output file layout".
    """
    thesis_and_acts = await _call_thesis_and_acts(anthropic_client, title, checkpoint_scope)
    roster_and_context = await _call_roster_and_shared_context(
        anthropic_client, title, thesis_and_acts["thesis"], thesis_and_acts["acts"], checkpoint_scope,
    )
    roster = roster_and_context["roster"]
    draft = {
        "thesis": thesis_and_acts["thesis"],
        "acts": thesis_and_acts["acts"],
        "unit_roster": roster,
        # roster_selection.selection_validation requires recommended_final_roster
        # to already match unit_roster. roster_selection.bound_selection_candidates
        # (applied by the caller, after this returns) only (re)computes this
        # list when it truncates the roster down to the runtime target - a
        # roster at or under target would otherwise leave this unset. Set it
        # here so the structural check passes whether or not truncation runs.
        "recommended_final_roster": [row["machine"] for row in roster],
        "shared_context": roster_and_context["shared_context"],
    }
    await export_thesis_roster_to_drive_fail_soft(title, draft)
    return draft


# ---------------------------------------------------------------------------
# Drive export (DESIGN.md "Output file layout") - fail-soft, never blocks
# roster generation.
# ---------------------------------------------------------------------------


def _thesis_and_roster_markdown(title: str, draft: dict) -> str:
    lines = [f"# {title}", "", "## Thesis", "", str(draft.get("thesis") or ""), "", "## Acts", ""]
    for act in draft.get("acts") or []:
        lines.append(f"{act.get('act_number')}. {act.get('argument')}")
    lines += ["", "## Roster", ""]
    current_act = object()
    for row in draft.get("unit_roster") or []:
        act_number = row.get("act_number") if isinstance(row, dict) else None
        if act_number != current_act:
            lines.append(f"### Act {act_number}")
            current_act = act_number
        machine = row.get("machine") if isinstance(row, dict) else row
        lines.append(f"- {machine}")
    return "\n".join(lines).rstrip() + "\n"


def _shared_context_markdown(title: str, draft: dict) -> str:
    lines = [f"# {title} - Shared Context", ""]
    context = draft.get("shared_context") or []
    if not context:
        lines.append("(none)")
    else:
        lines.extend(f"- {item}" for item in context)
    return "\n".join(lines).rstrip() + "\n"


def research_root_folder(client) -> dict:
    """Drive root folder for DVSU research exports.

    ``DVSU_RESEARCH_DRIVE_FOLDER_ID`` pins it by ID - required to target a
    Shared Drive folder, which the name lookup below (scoped to
    GOOGLE_DRIVE_FOLDER_ID) can never reach. Unset keeps the old behavior.
    """
    pinned = os.getenv("DVSU_RESEARCH_DRIVE_FOLDER_ID", "").strip()
    if pinned:
        return {"id": pinned}
    return client.get_or_create_folder("StoryEngine Research")


def _export_thesis_roster_to_drive(title: str, draft: dict) -> dict:
    from shared.clients.google_client import GoogleClient

    client = GoogleClient(strict_folder=True)
    root = research_root_folder(client)
    folder = client.get_or_create_folder(title or "Untitled", parent_id=root["id"])
    thesis_roster_file = client.upload_file(
        _thesis_and_roster_markdown(title, draft).encode("utf-8"),
        "00-thesis-and-roster.md", folder["id"], mime_type="text/markdown",
    )
    shared_context_file = client.upload_file(
        _shared_context_markdown(title, draft).encode("utf-8"),
        "01-shared-context.md", folder["id"], mime_type="text/markdown",
    )
    return {
        "folder_id": folder["id"],
        "files": {
            "thesis_and_roster": thesis_roster_file.get("id"),
            "shared_context": shared_context_file.get("id"),
        },
    }


async def export_thesis_roster_to_drive_fail_soft(title: str, draft: dict) -> Optional[dict]:
    """Best-effort Drive export. Mirrors ``drive_workspace.sync_video_workspace_fail_soft``'s
    fail-soft convention (own pattern, not its Docs-API implementation):
    Drive is never allowed to block or fail roster generation - including
    when ``GoogleClient()`` construction itself fails (e.g. missing
    credentials in a sandbox/test environment).
    """
    try:
        return await asyncio.to_thread(_export_thesis_roster_to_drive, title, draft)
    except Exception as exc:  # noqa: BLE001 - intentional fail-soft boundary
        logger.warning("DVSU thesis/roster Drive export failed for %r: %s", title, str(exc)[:240])
        return None
