"""DVSU research pipeline v2 - Call 3 (per-machine 6-question research packet).

Implements, verbatim, the "Call 3" section of
``storyengine/docs/dvsu-research-pipeline-v2-2026-09-18/DESIGN.md``. Calls 1
and 2 (thesis+acts, roster+shared-context) live in ``dvsu_roster_v2.py`` -
see that module's docstring/patterns, which this module mirrors (prompt
constants, ``_normalize_*`` helpers, the checkpoint pattern, fail-soft Drive
export via ``asyncio.to_thread``).

Two locked rules from DESIGN.md, both enforced structurally here, not just by
prompt wording:

1. One targeted search per question slot - never one broad combined query.
   This module makes **six separate ``client.generate()`` calls** per
   machine, one per slot. It never merges them into a single request.
2. Primary/institutional sources preferred over Wikipedia; Wikipedia only as
   an absolute last resort. Stated in the shared system prompt below,
   verbatim from DESIGN.md.

This module also contains the legacy-shape adapter
(``adapt_packet_to_factual_card``) that translates one Call-3 packet into the
card/source-package shapes ``factual_machine_research.build_factual_evidence_card``,
``factual_card_contract_warnings``, ``machine_research_summary.research_summary_ready``
and ``dvsu_research_handoff.package_brief_warnings`` expect - see that
function's docstring for the full design rationale (this was the single
hardest part of this chunk; verified against the real functions, not
guessed - see ``tests/test_dvsu_research_v2.py``).
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

_PIPELINE_PATH = Path(__file__).parent.parent.parent / "skills" / "video-pipeline"
if str(_PIPELINE_PATH) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_PATH))

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Call 3 - Per-machine research packet (6 targeted searches, once per machine)
# ---------------------------------------------------------------------------

CALL3_SYSTEM_PROMPT = (
    "You research one specific named military machine using web search, for a documentary paragraph "
    "about the engineering decision it represents - not a biography of the machine. Every fact must "
    "trace to a search result; cite the source URL for each answer. Never invent a date, number, or "
    "quote. Prefer primary/institutional sources (official history offices, museums, established "
    "history publications) over Wikipedia; use Wikipedia only as a last resort. Output only the "
    "requested JSON."
)

# DESIGN.md: "small N" search budget per slot call (never one combined broad
# search across slots - that is a *separate* call per slot entirely; this
# budget only bounds how many searches ONE slot's own call may run, e.g. a
# primary search plus one follow-up replacing a Wikipedia result per the
# second locked rule).
CALL3_SEARCH_BUDGET_PER_SLOT = 3

_SLOT_ANSWER_SHAPE = '{"answer":"...","source_url":"...","quote":"..."}'


def _shared_context_block(shared_context: list[str]) -> str:
    if not shared_context:
        return ""
    lines = "\n".join(f"- {item}" for item in shared_context)
    return (
        "\nBackground facts already established for this video (do not re-discover these; use them "
        f"only as context for this one machine):\n{lines}\n"
    )


def _slot_preamble(machine: str, act_number: int, shared_context: list[str]) -> str:
    return (
        f'Machine: "{machine}" (act {act_number})\n'
        + _shared_context_block(shared_context)
    )


def _call3_problem_prompt(machine: str, act_number: int, shared_context: list[str]) -> str:
    return (
        _slot_preamble(machine, act_number, shared_context)
        + "\nRun ONE targeted web search for why the authority/need behind this machine wanted or needed "
        f'it - a query like "why did [need/authority] want/need {machine}". Find what situation or need '
        "required this machine. Prefer primary/institutional sources (official history offices, museums, "
        "established history publications) over Wikipedia; use Wikipedia only as a last resort, and "
        "replace it with a follow-up search if it is your only result.\n"
        f"Return only JSON: {_SLOT_ANSWER_SHAPE}"
    )


def _call3_design_prompt(machine: str, act_number: int, shared_context: list[str]) -> str:
    return (
        _slot_preamble(machine, act_number, shared_context)
        + "\nRun ONE targeted web search for the specific engineering decision or innovation made in "
        f'response to that need - a query like "{machine} design decision/innovation [specific feature]". '
        "Find the specific engineering decision. Prefer primary/institutional sources over Wikipedia; use "
        "Wikipedia only as a last resort, and replace it with a follow-up search if it is your only result.\n"
        f"Return only JSON: {_SLOT_ANSWER_SHAPE}"
    )


def _call3_trade_off_prompt(machine: str, act_number: int, shared_context: list[str]) -> str:
    return (
        _slot_preamble(machine, act_number, shared_context)
        + "\nRun ONE targeted web search for the trade-off or limitation that design decision cost - a "
        f'query like "{machine} limitation/trade-off [specific consequence]". Find what was sacrificed to '
        "get that design. Prefer primary/institutional sources over Wikipedia; use Wikipedia only as a "
        "last resort, and replace it with a follow-up search if it is your only result.\n"
        f"Return only JSON: {_SLOT_ANSWER_SHAPE}"
    )


def _call3_outcome_prompt(machine: str, act_number: int, shared_context: list[str]) -> str:
    return (
        _slot_preamble(machine, act_number, shared_context)
        + "\nRun ONE targeted web search for this machine's event/record/fate - a query like "
        f'"{machine} [event/record/fate]". Gather 2-4 candidate facts (a dated event, a production/scale '
        "number, a failure mode or operator account, its eventual fate). Do not pick just one in the "
        "search itself - surface several, let the writer choose later. Prefer primary/institutional "
        "sources over Wikipedia; use Wikipedia only as a last resort, and replace it with a follow-up "
        "search if it is your only result.\n"
        'Return only JSON: {"candidates":[{"fact":"...","source_url":"...","quote":"..."}, ...]} '
        "with 2-4 entries."
    )


def _call3_surprising_fact_prompt(machine: str, act_number: int, shared_context: list[str]) -> str:
    return (
        _slot_preamble(machine, act_number, shared_context)
        + "\nRun ONE targeted web search for an interesting or little-known fact about this machine - a "
        f'query like "{machine} interesting/little-known fact", or a more specific named-detail query once '
        "something promising turns up (e.g. a named person or incident mentioned in passing). Find one "
        "fact most viewers wouldn't already know. Prefer primary/institutional sources over Wikipedia; use "
        "Wikipedia only as a last resort, and replace it with a follow-up search if it is your only result.\n"
        f"Return only JSON: {_SLOT_ANSWER_SHAPE}"
    )


def _call3_contrast_prompt(machine: str, act_number: int, shared_context: list[str]) -> str:
    return (
        _slot_preamble(machine, act_number, shared_context)
        + "\nRun ONE targeted web search for the gap between what this machine was designed/intended for "
        f'and what actually happened, or how it is remembered now - a query like "{machine} intended vs '
        'actual / obsoleted / legacy". Prefer primary/institutional sources over Wikipedia; use Wikipedia '
        "only as a last resort, and replace it with a follow-up search if it is your only result.\n"
        f"Return only JSON: {_SLOT_ANSWER_SHAPE}"
    )


_SLOT_PROMPT_BUILDERS: dict[str, Any] = {
    "problem": _call3_problem_prompt,
    "design": _call3_design_prompt,
    "trade_off": _call3_trade_off_prompt,
    "outcome_candidates": _call3_outcome_prompt,
    "surprising_fact": _call3_surprising_fact_prompt,
    "contrast": _call3_contrast_prompt,
}

# Slot evaluation order is fixed so tests can assert exactly six calls in a
# known, stable sequence.
SLOT_ORDER = ("problem", "design", "trade_off", "outcome_candidates", "surprising_fact", "contrast")


def _normalize_answer_slot(raw: Any) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    answer = str(raw.get("answer") or "").strip()
    source_url = str(raw.get("source_url") or "").strip()
    quote = str(raw.get("quote") or "").strip()
    if not answer or not source_url or not quote:
        return None
    return {"answer": answer, "source_url": source_url, "quote": quote}


def _normalize_outcome_candidates(raw: Any) -> list[dict]:
    if isinstance(raw, dict):
        raw = raw.get("candidates")
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        fact = str(item.get("fact") or "").strip()
        source_url = str(item.get("source_url") or "").strip()
        quote = str(item.get("quote") or "").strip()
        if fact and source_url and quote:
            out.append({"fact": fact, "source_url": source_url, "quote": quote})
    return out[:4]


async def _call_one_slot(
    client: Any, slot: str, machine: str, act_number: int, shared_context: list[str],
    checkpoint_scope: Optional[dict],
) -> Any:
    from shared.clients.anthropic_client import WEB_SEARCH_TOOL
    from orchestrator.pipeline_constants import Models
    from shared.json_utils import parse_json_response
    from shared.research_response import checkpoint_path, request_fingerprint

    if getattr(client, "_gateway_mode", False):
        raise ValueError(
            "Per-machine research needs a web-search capable research provider; this gateway cannot execute web search"
        )

    prompt = _SLOT_PROMPT_BUILDERS[slot](machine, act_number, shared_context)
    system_prompt = CALL3_SYSTEM_PROMPT
    model = Models.CLAUDE_SONNET
    max_tokens = 1500
    temperature = 0.3
    tools = [dict(WEB_SEARCH_TOOL, max_uses=CALL3_SEARCH_BUDGET_PER_SLOT)]
    response = await client.generate(
        prompt=prompt, system_prompt=system_prompt, model=model,
        max_tokens=max_tokens, temperature=temperature, tools=tools, complete_response=True,
        checkpoint_path=checkpoint_path(checkpoint_scope, request_fingerprint(
            prompt=prompt, system_prompt=system_prompt, model=model,
            max_tokens=max_tokens, temperature=temperature, tools=tools,
        )),
    )
    raw = parse_json_response(response, default=None)
    if slot == "outcome_candidates":
        return _normalize_outcome_candidates(raw)
    return _normalize_answer_slot(raw)


async def run_machine_research_packet(
    anthropic_client: Any, machine: str, act_number: int, subject_context: str,
    shared_context: list[str], checkpoint_scope: Optional[dict] = None,
) -> dict:
    """Runs Call 3's 6 targeted searches for one machine, returns the packet dict.

    Six separate, narrowly-targeted ``client.generate()`` calls - never one
    combined broad search (DESIGN.md's first locked rule). ``subject_context``
    is the video title (kept for interface parity with
    ``research_claim_assessment.assess_verified_package``'s parameter name,
    though this call itself doesn't need it - it is accepted for symmetry and
    forward compatibility with callers that log/checkpoint by it).
    """
    shared_context = list(shared_context or [])
    results: dict[str, Any] = {}
    for slot in SLOT_ORDER:
        results[slot] = await _call_one_slot(
            anthropic_client, slot, machine, act_number, shared_context, checkpoint_scope,
        )

    for slot in ("problem", "design", "trade_off", "surprising_fact", "contrast"):
        if results.get(slot) is None:
            raise ValueError(f"Call 3 {slot!r} search for {machine!r} returned no usable answer")
    if len(results.get("outcome_candidates") or []) < 1:
        raise ValueError(f"Call 3 outcome search for {machine!r} returned no usable candidates")

    packet = {
        "machine": machine,
        "act_number": act_number,
        "problem": results["problem"],
        "design": results["design"],
        "trade_off": results["trade_off"],
        "outcome_candidates": results["outcome_candidates"],
        "surprising_fact": results["surprising_fact"],
        "contrast": results["contrast"],
    }
    await export_machine_packet_to_drive_fail_soft(subject_context, packet)
    return packet


# ---------------------------------------------------------------------------
# Legacy-shape adapter
# ---------------------------------------------------------------------------

# Maps each single-answer slot (and the outcome list) to the narrative role
# `dvsu_script_brief.py`'s compact-brief field-coverage uses
# (`intended_role`/`design`/`actual_use`/`outcome`). Per DESIGN.md's mapping
# of the 6-slot template onto the DvsU v3 style guide's own paragraph logic
# (Problem -> Design -> Trade-off -> Outcome): problem is the intended_role
# beat, design and trade_off are both design-consequence facts, outcome
# candidates and the contrast/legacy beat are both outcome facts.
# `surprising_fact` deliberately gets no role - it is its own beat in the v3
# spec, not one of the compact brief's 4 narrative categories, and
# `build_dvsu_brief` treats missing role coverage (e.g. no `actual_use` fact)
# as informational, never a readiness blocker (verified in
# tests/test_dvsu_research_v2.py).
_SLOT_NARRATIVE_ROLE = {
    "problem": "intended_role",
    "design": "design",
    "trade_off": "design",
    "outcome_candidates": "outcome",
    "surprising_fact": None,
    "contrast": "outcome",
}


def _candidate_text(machine: str, quote: str) -> str:
    """Embed the exact locked machine label verbatim ahead of the quote.

    ``factual_machine_research.candidate_mentions_machine`` (and the stricter
    named-submarine matcher it delegates to) requires the candidate's fetched
    *text* to literally contain the machine's identity - not just the
    citation being *about* that machine per Call 3's own prompt contract.
    Call 3's model-returned quotes are not guaranteed to spell the machine's
    full locked display name verbatim (a source might say "the boat" or use
    a different naming convention). Rather than depend on fragile per-format
    regex coverage across every roster identity shape (named submarine hull,
    aircraft designation, class label, ...), this adapter deterministically
    prepends the exact locked ``machine`` string to the quote before it
    becomes a candidate's ``text`` field. This is a bookkeeping label, not an
    edit to the quoted source content itself - the quote is preserved
    verbatim after it. Verified against every matcher branch in
    ``factual_machine_research.py`` in ``tests/test_dvsu_research_v2.py``.
    """
    return f"Regarding {machine}: {quote}".strip()


def _source_title_for(url: str) -> str:
    hostname = (urlparse(url).hostname or "").strip()
    return hostname or url


def _packet_citations(packet: dict) -> list[tuple[str, str, str, Optional[str]]]:
    """Flatten a Call-3 packet into ``(claim_text, source_url, quote, role)`` rows."""
    rows: list[tuple[str, str, str, Optional[str]]] = []
    for slot in ("problem", "design", "trade_off", "surprising_fact", "contrast"):
        entry = packet.get(slot)
        if isinstance(entry, dict) and entry.get("answer") and entry.get("source_url") and entry.get("quote"):
            rows.append((str(entry["answer"]), str(entry["source_url"]), str(entry["quote"]), _SLOT_NARRATIVE_ROLE[slot]))
    for entry in packet.get("outcome_candidates") or []:
        if isinstance(entry, dict) and entry.get("fact") and entry.get("source_url") and entry.get("quote"):
            rows.append((str(entry["fact"]), str(entry["source_url"]), str(entry["quote"]), _SLOT_NARRATIVE_ROLE["outcome_candidates"]))
    return rows


def _build_verified_source_package(machine: str, packet: dict, subject_context: str) -> dict:
    """Legacy ``machine_raw_source_packages[cache_key]`` shape from one Call-3 packet.

    ``sources``/``candidate_excerpts`` match what
    ``factual_machine_summary._eligible_candidates`` requires (registry
    cross-check by ``source_id`` and matching ``url``), and
    ``claim_assessment`` is a fully-formed, already-``supported`` receipt in
    ``research_claim_assessment._valid_receipt``'s exact expected shape - no
    LLM assessment call is made (see module docstring: Call 3's own
    search-grounded quote already IS the claim assessment, per DESIGN.md's
    "no separate roster-validation pass" philosophy extended to research).
    """
    from research_claim_assessment import assessment_fingerprint, _claims_fingerprint, _validated_claims
    from factual_machine_summary import _eligible_candidates

    sources: list[dict] = []
    excerpts: list[dict] = []
    raw_claims: list[dict] = []
    for index, (claim_text, source_url, quote, role) in enumerate(_packet_citations(packet), start=1):
        source_id = f"C3-{index}"
        excerpt_id = f"{source_id}-E1"
        text = _candidate_text(machine, quote)
        title = _source_title_for(source_url)
        sources.append({
            "source_id": source_id, "source_url": source_url, "url": source_url, "source_title": title,
        })
        excerpts.append({
            "excerpt_id": excerpt_id, "source_id": source_id, "source_url": source_url,
            "text": text, "locator": excerpt_id, "source_capture_method": "fetched_page",
            "source_title": title,
        })
        raw_claim = {
            "claim": claim_text, "scope": "machine", "status": "supported",
            "reason": "Call 3 targeted search citation",
            "evidence": [{"excerpt_id": excerpt_id, "quote": text}],
            "counterevidence": [],
        }
        if role:
            raw_claim["narrative_roles"] = [role]
        raw_claims.append(raw_claim)

    package: dict = {"machine": machine, "sources": sources, "candidate_excerpts": excerpts}
    candidates = dict(list(
        _eligible_candidates(machine, package, subject_context, include_identity_pending=True).items()
    )[:60])
    validated = _validated_claims(raw_claims, candidates, max_claims=12) or []
    receipt = {
        "version": 1, "status": "assessed", "machine": machine, "subject_context": str(subject_context or ""),
        "claims": validated, "probability": None, "provenance_status": "captured",
        "method": "model_source_assessment", "calibration": "not_calibrated",
        "source_fingerprint": assessment_fingerprint(machine, package, subject_context),
    }
    receipt["claims_fingerprint"] = _claims_fingerprint(validated)
    package["claim_assessment"] = receipt
    return package


def _mechanical_research_summary(machine: str, package: dict, packet: dict, subject_context: str) -> dict:
    """Build ``research_summary`` as a MECHANICAL concatenation of the 6 slots.

    This is deliberately NOT a drafted script paragraph and NOT an extra LLM
    call. The legacy ``research_summary.paragraph`` was written by
    ``factual_machine_summary.generate_factual_machine_summary(...,
    purpose="research")`` - exactly what Call 3 replaces per DESIGN.md ("no
    separate roster-validation pass... " extended here: paragraph-writing is
    Phase 2's job, explicitly out of scope for this chunk). What follows is a
    placeholder/display value only, so the existing Research tab UI
    (``ResearchTab.tsx``'s ``selectedSavedResearchSummaryReady``) has
    something coherent to show and its readiness gate
    (``machine_research_summary.research_summary_ready``) can pass - never
    mistake this for finished DvsU-style prose. Phase 2 (script-writing)
    replaces this with the real polished paragraph.
    """
    from research_claim_assessment import current_assessment
    from machine_research_summary import saved_research_summary

    assessment = current_assessment(machine, package, subject_context)
    claims = (assessment or {}).get("claims") or []
    sentences: list[str] = []
    claim_map: list[dict] = []
    sources: list[dict] = []
    seen_sources: set[tuple[str, str]] = set()
    for claim in claims:
        sentence = str(claim.get("claim") or "").strip()
        if not sentence:
            continue
        if not sentence.endswith((".", "!", "?")):
            sentence += "."
        sentences.append(sentence)
        evidence = (claim.get("evidence") or [{}])[0]
        source_url = str(evidence.get("source_url") or "")
        source_title = str(evidence.get("source_title") or "")
        claim_map.append({
            "sentence": sentence,
            "source_url": source_url,
            "source_title": source_title,
            "quote": str(evidence.get("quote") or ""),
        })
        key = (source_url, source_title)
        if source_url and key not in seen_sources:
            seen_sources.add(key)
            sources.append({"source_url": source_url, "source_title": source_title})

    paragraph = " ".join(sentences)
    result = {"paragraph": paragraph, "claim_map": claim_map, "sources": sources, "passed": bool(paragraph and claim_map and sources)}
    summary = saved_research_summary(machine, package, result, subject_context)

    required_slots = ("problem", "design", "trade_off", "surprising_fact", "contrast")
    missing = [slot for slot in required_slots if not isinstance(packet.get(slot), dict) or not packet[slot].get("answer") or not packet[slot].get("source_url")]
    if not (packet.get("outcome_candidates") or []):
        missing.append("outcome_candidates")
    if missing or not result["passed"]:
        summary["passed"] = False
        summary["warnings"] = list(dict.fromkeys(
            list(summary.get("warnings") or [])
            + [f"Call 3 packet is missing a usable {slot} answer" for slot in missing]
            + ([] if result["passed"] else ["Mechanical research summary paragraph could not be assembled from the Call 3 packet"])
        ))
    return summary


def adapt_packet_to_factual_card(
    machine: str, act_number: int, packet: dict, locked_roster_index: int, subject_context: str = "",
) -> dict:
    """Translate one Call-3 packet into the legacy card + source-package shapes.

    Deviates from the brief's suggested signature by taking ``subject_context``
    (the video title) - required by every downstream gate this card must
    satisfy (``research_claim_assessment.assessment_fingerprint``,
    ``machine_research_summary.research_summary_ready``,
    ``dvsu_research_handoff.package_brief_warnings``) - and by returning both
    the factual evidence card AND the legacy ``verified_source_package`` it
    was built from (the caller must persist the package into
    ``payload["machine_raw_source_packages"][cache_key]`` for
    ``package_brief_warnings`` to have something to read later; the brief's
    suggested signature/return only mentioned the card, but the package is
    inseparable from it in the legacy contract).

    Returns ``{"package": ..., "card": ...}``. The card matches
    ``factual_machine_research.build_factual_evidence_card``'s contract, plus
    a mechanically-assembled ``research_summary`` (see
    ``_mechanical_research_summary``) and a ``script_brief_readiness`` block
    mirroring the existing single-machine branch's own field of that name.
    ``card["readiness"]`` is deliberately NOT set here - that field is
    populated later, by a separate enrichment pass
    (``pipeline_executor.py`` around line 4476-4494) that reads the
    ``machine_research_cards.validation`` column written by
    ``PipelineExecutor._upsert_machine_research_card`` - not by anything in
    the card object itself. See this module's Step-0 findings quoted in the
    implementation report.
    """
    from factual_machine_research import build_factual_evidence_card, factual_card_contract_warnings
    from dvsu_research_handoff import package_brief_warnings

    package = _build_verified_source_package(machine, packet, subject_context)
    card = build_factual_evidence_card(machine, package)
    card["locked_roster_index"] = locked_roster_index
    card["research_summary"] = _mechanical_research_summary(machine, package, packet, subject_context)
    narrative_warnings = (
        package_brief_warnings(machine, package, subject_context)
        if not factual_card_contract_warnings(machine, card, package)
        else []
    )
    card["script_brief_readiness"] = {"passed": not narrative_warnings, "warnings": narrative_warnings}
    return {"package": package, "card": card}


# ---------------------------------------------------------------------------
# Drive export (DESIGN.md "Output file layout") - fail-soft, never blocks
# research generation. Mirrors dvsu_roster_v2.py's own export functions.
# ---------------------------------------------------------------------------


def _machine_slug(machine: str) -> str:
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", str(machine or "").strip().lower()).strip("-")
    return slug or "machine"


def _machine_packet_markdown(packet: dict) -> str:
    machine = str(packet.get("machine") or "")
    lines = [f"# {machine}", ""]

    def _slot(title: str, entry: Any) -> None:
        lines.append(f"## {title}")
        lines.append("")
        if isinstance(entry, dict) and entry.get("answer"):
            lines.append(entry["answer"])
            lines.append(f"Source: {entry.get('source_url', '')}")
            lines.append(f"> {entry.get('quote', '')}")
        else:
            lines.append("(none)")
        lines.append("")

    _slot("Problem", packet.get("problem"))
    _slot("Design", packet.get("design"))
    _slot("Trade-off", packet.get("trade_off"))
    lines.append("## Outcome candidates")
    lines.append("")
    outcomes = packet.get("outcome_candidates") or []
    if not outcomes:
        lines.append("(none)")
    for candidate in outcomes:
        if not isinstance(candidate, dict):
            continue
        lines.append(f"- {candidate.get('fact', '')}")
        lines.append(f"  Source: {candidate.get('source_url', '')}")
        lines.append(f"  > {candidate.get('quote', '')}")
    lines.append("")
    _slot("Surprising fact", packet.get("surprising_fact"))
    _slot("Contrast", packet.get("contrast"))
    return "\n".join(lines).rstrip() + "\n"


def _export_machine_packet_to_drive(video_title: str, packet: dict) -> dict:
    from shared.clients.google_client import GoogleClient

    client = GoogleClient(strict_folder=True)
    root = client.get_or_create_folder("StoryEngine Research")
    folder = client.get_or_create_folder(video_title or "Untitled", parent_id=root["id"])
    machines_folder = client.get_or_create_folder("machines", parent_id=folder["id"])
    machine_file = client.upload_file(
        _machine_packet_markdown(packet).encode("utf-8"),
        f"{_machine_slug(packet.get('machine', ''))}.md", machines_folder["id"], mime_type="text/markdown",
    )
    return {"folder_id": machines_folder["id"], "file_id": machine_file.get("id")}


async def export_machine_packet_to_drive_fail_soft(video_title: str, packet: dict) -> Optional[dict]:
    """Best-effort Drive export. Never allowed to block or fail research generation."""
    try:
        return await asyncio.to_thread(_export_machine_packet_to_drive, video_title, packet)
    except Exception as exc:  # noqa: BLE001 - intentional fail-soft boundary
        logger.warning(
            "DVSU machine packet Drive export failed for %r/%r: %s",
            video_title, packet.get("machine"), str(exc)[:240],
        )
        return None
