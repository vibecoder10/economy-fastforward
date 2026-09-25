"""DVSU research pipeline v2 - the roster list (+ spares, shared context), then thesis+acts.

Started from the "Call 1" and "Call 2" sections of
``storyengine/docs/dvsu-research-pipeline-v2-2026-09-18/DESIGN.md``, run in
the other order since 2026-09-25: the title picks the list first. Call 3
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

CALL1_SYSTEM_PROMPT = (
    "You are a documentary structure analyst for DvsU, an engineering-history channel. DvsU videos are "
    "not about machines - they are about one engineering argument, proven through a sequence of machines. "
    "War is the setting. Engineering is the story."
)

CALL2_SYSTEM_PROMPT = (
    "You research real named military machines using web search. You never invent a machine, a "
    "production number, or a date - every claim must trace to a search result. Output only the "
    "requested JSON."
)

# One search-enabled call discovers the whole list: wide enough for several
# searches while pinning down 20-25 distinct, sourced names in one pass.
CALL2_SEARCH_BUDGET = 15

# Extra machines picked with the list, best first. The photo gather swaps one
# in when a roster machine has no usable photo (static_docu.prefetch_roster_references).
SPARE_COUNT = 3


# ---------------------------------------------------------------------------
# The list first, the story second - for every title
# ---------------------------------------------------------------------------
# Story-first let the thesis bend the picks. 2026-09-24, "Every US Military
# Helicopter Ever Built": an Army-only thesis dropped the Marine CH-53/CH-46.
# 2026-09-25, "Most Hated Helicopters": the thesis picked one-off prototypes
# (HZ-1 Aerocycle, Rotodyne, Ka-22) nobody ever hated. The title alone picks
# the machines, then the story is written around them (Ryan). The count is
# the runtime Ryan set. Rules live here, in the input - no output checker.

def _roster_list_prompt(title: str, target_count: int) -> str:
    return (
        f'Video title: "{title}"\n'
        "\n"
        f"Using web search, pick exactly {target_count} real machines this title promises, plus {SPARE_COUNT} spares.\n"
        "The title alone decides which machines belong. Read every word of it:\n"
        "- Only the machine type the title names (a helicopter list has no tiltrotor or airplane). Only the\n"
        "  countries, services and eras the title names.\n"
        "- One entry per distinct class or type, named as the class or type (e.g. \"Ajax class\", \"UH-1\n"
        "  Iroquois\"; a one-ship class is named by its ship). Never list two ships of one class or two\n"
        "  variants of one type. For aircraft a type is its base design number: every version that shares\n"
        "  it is ONE type (AH-1 Cobra and AH-1W SuperCobra are one; UH-60 and SH-60 are one) - list it once.\n"
        "- If the title covers a whole category (every, all, ever built, complete), cover every part of it\n"
        "  the title names (e.g. \"military\" means every service, not one branch) and spread the picks\n"
        "  across its whole history, choosing the most significant members.\n"
        "- If the title ranks machines (most hated, worst, best, deadliest, fastest...), every pick must\n"
        "  earn that rank on the record: what its crews, the press, reports or the numbers said. Prefer\n"
        "  machines that entered service over one-off prototypes and test articles.\n"
        "- Leave out designs that were never built, unless the title is about never-built or cancelled\n"
        "  designs - then unbuilt designs are the subject.\n"
        "\n"
        f"Put the {target_count} picks in \"roster\", in chronological order of first flight or first commissioning.\n"
        f"Put the {SPARE_COUNT} next-best machines that follow the same rules in \"spares\", best first. No machine\n"
        "may appear twice. Give every entry a one-sentence \"reason\" it belongs, from your sources.\n"
        "\n"
        "Also note 3-5 facts you encounter that apply across MULTIPLE machines rather than one specific\n"
        "unit (a shared technological shift, a doctrine change, an external event that reframes several\n"
        "entries) - these will be given to the per-machine research step as background, so it isn't\n"
        "re-discovered for every machine.\n"
        "\n"
        "Return only JSON: {\"roster\": [{\"machine\": \"...\", \"reason\": \"...\"}, ...],\n"
        "\"spares\": [{\"machine\": \"...\", \"reason\": \"...\"}, ...], \"shared_context\": [\"...\", ...]}"
    )


def _story_for_roster_prompt(title: str, machines: list[str], spares: list[str] | None = None) -> str:
    listed = "\n".join(f"- {machine}" for machine in machines)
    spare_lines = ""
    if spares:
        spare_lines = (
            "\nThese spares may later replace a machine that has no usable photo. Assign each one to the\n"
            "act it would best prove, spelled exactly as listed, in \"spares\":\n"
            + "\n".join(f"- {spare}" for spare in spares) + "\n"
        )
    return (
        f'Video title: "{title}"\n'
        f"The video covers exactly these {len(machines)} machines, in chronological order:\n{listed}\n"
        "\n"
        "Formulate ONE thesis for this video - a single engineering argument these machines together prove.\n"
        "Strong theses read like: \"Britain kept cancelling the right tank and building the wrong one.\"\n"
        "The thesis must cover everything the title names - never a narrower slice of it. If the title says\n"
        "\"military\", the argument spans every service, not one branch.\n"
        "Then break that thesis into 4-7 acts. Each act is one sentence describing a distinct step in the\n"
        "argument, NOT a time period. Moving between acts should feel like the argument shifting, not a\n"
        "timeline advancing. Every act must be proven by machines on the list above.\n"
        "\n"
        "Assign every listed machine to exactly one act, spelled exactly as listed. Give every act a\n"
        "near-equal share (no act more than one machine above an even split). Keep chronological order\n"
        "within each act.\n"
        + spare_lines +
        "\n"
        "Return only JSON: {\"thesis\": \"...\", \"acts\": [{\"act_number\": 1, \"argument\": \"one sentence\"}, ...],\n"
        "\"roster\": [{\"machine\": \"...\", \"act_number\": 1}, ...], \"spares\": [{\"machine\": \"...\", \"act_number\": 1}, ...]}"
    )


def _names(raw: Any) -> list[str]:
    names: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        name = str((item.get("machine") if isinstance(item, dict) else item) or "").strip()
        if name and name.casefold() not in {n.casefold() for n in names}:
            names.append(name)
    return names


async def _call_roster_list(
    client: Any, title: str, checkpoint_scope: Optional[dict], target_count: int,
) -> dict:
    from shared.clients.anthropic_client import WEB_SEARCH_TOOL
    from orchestrator.pipeline_constants import Models
    from shared.json_utils import parse_json_response
    from shared.research_response import checkpoint_path, request_fingerprint

    if getattr(client, "_gateway_mode", False):
        raise ValueError(
            "Roster discovery needs a web-search capable research provider; this gateway cannot execute web search"
        )
    prompt = _roster_list_prompt(title, target_count)
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
        raise ValueError("Roster list call returned invalid JSON")
    listed = _names(raw.get("roster"))
    if not listed:
        raise ValueError("Roster list call returned no machines")
    # A long list keeps its tail as the first spares; the runtime count is Ryan's.
    machines = listed[:target_count]
    taken = {name.casefold() for name in machines}
    spares = [name for name in listed[target_count:] + _names(raw.get("spares")) if name.casefold() not in taken]
    return {"machines": machines, "spares": _names(spares),
            "shared_context": _normalize_shared_context(raw.get("shared_context"))}


async def _call_story_for_roster(
    client: Any, title: str, machines: list[str], checkpoint_scope: Optional[dict],
    spares: list[str] | None = None,
) -> dict:
    from shared.json_utils import parse_json_response
    from orchestrator.pipeline_constants import Models
    from shared.research_response import checkpoint_path, request_fingerprint

    prompt = _story_for_roster_prompt(title, machines, spares)
    system_prompt = CALL1_SYSTEM_PROMPT
    model = Models.CLAUDE_SONNET
    max_tokens = 3000
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
        raise ValueError("Story call returned invalid JSON")
    thesis = str(raw.get("thesis") or "").strip()
    acts = _normalize_acts(raw.get("acts"))
    if not thesis or not acts:
        raise ValueError("Story call returned no thesis or no acts")
    act_of = {
        row["machine"].casefold(): row["act_number"] for row in _normalize_roster(raw.get("roster"))
    }
    missing = [machine for machine in machines if machine.casefold() not in act_of]
    if missing:
        raise ValueError(f"Story call left machines without an act: {', '.join(missing)}")
    # The list call's names and chronological order are kept; the story call
    # only supplies each machine's act.
    roster = _normalize_roster([
        {"machine": machine, "act_number": act_of[machine.casefold()]} for machine in machines
    ])
    # A spare's act is only a swap preference: one the story left out stays
    # a spare with no act, still best-first.
    spare_act = {
        row["machine"].casefold(): row["act_number"] for row in _normalize_roster(raw.get("spares"))
    }
    spare_rows = []
    for spare in spares or []:
        row = {"machine": spare}
        if spare_act.get(spare.casefold()):
            row["act_number"] = spare_act[spare.casefold()]
        spare_rows.append(row)
    return {"thesis": thesis, "acts": acts, "roster": roster, "spares": spare_rows}


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
    anthropic_client: Any, title: str, checkpoint_scope: Optional[dict] = None, target_count: int = 20,
) -> dict:
    """The title picks the list (plus spares), then the story is written around it.

    Returns a draft shaped to slot directly into ``run_roster_selection``'s
    ``merged.update({key: value for key, value in draft.items() if key in
    selection_keys})`` pattern:
    ``{"thesis": str, "acts": [{"act_number": int, "argument": str}, ...],
    "unit_roster": [{"machine": str, "act_number": int}, ...],
    "shared_context": [str, ...]}``.
    ``unit_roster`` is sorted into act order. ``roster_candidate_overflow``
    holds the spares, best first, for the photo gather's swap.

    Also (fail-soft, never raises past this function) exports
    ``00-thesis-and-roster.md`` and ``01-shared-context.md`` to Google Drive
    per DESIGN.md's "Output file layout".
    """
    listed = await _call_roster_list(anthropic_client, title, checkpoint_scope, target_count)
    story = await _call_story_for_roster(
        anthropic_client, title, listed["machines"], checkpoint_scope, listed["spares"],
    )
    thesis_and_acts = {"thesis": story["thesis"], "acts": story["acts"]}
    roster_and_context = {"roster": story["roster"], "shared_context": listed["shared_context"]}
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
        "roster_candidate_overflow": story["spares"],
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
