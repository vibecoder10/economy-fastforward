"""Evidence-candidate helpers for one locked DVsU machine's research package.

This module used to be the factual (``factual_100_v1``) paragraph writer and
its paid referee. Both were deleted 2026-09-21 - the only script writer is
``dvsu_script_v2.py``. What remains are the pure helpers the research side
still imports: ``_eligible_candidates`` (traceable excerpts for the exact
locked machine), ``_parse_json_object``, ``_model_name`` and
``REVIEW_CONTEXT_VERSION`` (read by ``machine_research_summary``).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.parse import urlparse

from factual_machine_research import candidate_mentions_machine


REVIEW_CONTEXT_VERSION = 6
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])\d[\d,]*(?:\.\d+)?(?:st|nd|rd|th)?(?![A-Za-z0-9])")


def _compact(value: Any) -> str:
    return " ".join(str(value or "").split())


def _eligible_candidates(machine: str, source_package: dict, subject_context: str = "", *,
                         include_identity_pending: bool = False) -> dict[str, dict]:
    from factual_machine_research import _candidate_traceable
    from contextual_source_identity import contextual_named_excerpt
    from factual_class_context import is_verified_class_context
    registry = {_compact(row.get("source_id")): row
                for row in source_package.get("sources") or []
                if isinstance(row, dict) and _compact(row.get("source_id"))}
    eligible, pending = {}, {}
    for raw in source_package.get("candidate_excerpts") or []:
        if not isinstance(raw, dict) or not _candidate_traceable(raw):
            continue
        excerpt_id = _compact(raw.get("excerpt_id") or raw.get("locator"))
        source_id = _compact(raw.get("source_id"))
        url, text = _compact(raw.get("source_url")), _compact(raw.get("text"))
        structural_text = str(raw.get("text") or "")
        parsed_url = urlparse(url)
        if not (excerpt_id and url and text and parsed_url.scheme in {"http", "https"} and parsed_url.netloc):
            continue
        registered = registry.get(source_id)
        if registry and (registered is None or _compact(registered.get("url")) != url):
            continue
        if is_verified_class_context(structural_text, machine):
            pending[excerpt_id] = {**raw, "identity_requires_review": True,
                                   "context_scope": "class_design", "_locked_machine": machine}
        elif candidate_mentions_machine(text, machine):
            eligible[excerpt_id] = {**raw, "identity_requires_review": False, "_locked_machine": machine}
        elif contextual_named_excerpt(text, machine):
            pending[excerpt_id] = {**raw, "identity_requires_review": True, "_locked_machine": machine}
    # A name-only source is never sufficient on its own. Assessment sees it
    # alongside exact-hull anchors; downstream writing requires its saved review.
    if eligible and pending:
        if include_identity_pending:
            eligible.update(pending)
        else:
            from research_claim_assessment import current_assessment
            assessment = current_assessment(machine, source_package, subject_context)
            approved = {review["excerpt_id"] for claim in (assessment or {}).get("claims", [])
                        if claim.get("status") == "supported"
                        for review in claim.get("identity_reviews", [])}
            eligible.update({key: row for key, row in pending.items() if key in approved})
    if re.search(r"\baircraft\s+carriers?\b", subject_context, re.I):
        # Require a source to identify its subject as a naval carrier. Keep
        # design/history excerpts from that same source, including conversions.
        # A battleship or fictional aerospace-carrier namesake is not evidence.
        carrier_pattern = r"\b(?:aircraft|escort|fleet|light|training|seaplane)\s+carriers?\b"
        carrier_urls = {
            _compact(row.get("source_url")) for row in eligible.values()
            if re.search(carrier_pattern, str(row.get("source_title") or "") + " " + str(row.get("text") or ""), re.I)
        }
        eligible = {key: row for key, row in eligible.items()
                    if _compact(row.get("source_url")) in carrier_urls}
    return eligible


def _sentences(paragraph: str) -> list[str]:
    # Keep the original text for exact citation matching. Protect abbreviation
    # periods only in a continuing phrase, not a sentence ending in "the U.S.".
    text = paragraph.strip()
    protected = {
        match.end() - 1
        for match in re.finditer(
            r"\b(?:U\.S\.|U\.K\.)(?=\s+(?:[a-z]|Air\b|Navy\b|Naval\b|Army\b|Marine\b|Space\b|Coast\b))",
            text,
        )
    }
    # Naval registry designations such as Submarine No. 105 continue before digits.
    protected.update(
        match.end() - 1 for match in re.finditer(r"\bNos?\.(?=\s+\d)", text)
    )
    # A middle initial in a name, such as Glenn L. Martin, is not a stop.
    protected.update(
        match.end(1) - 1
        for match in re.finditer(
            r"\b[A-Z][a-z]+\s+([A-Z]\.)(?=\s+(?!(?:It|He|She|They|The|This|That|These|Those)\b)[A-Z][a-z]+\b)",
            text,
        )
    )
    sentences = []
    start = 0
    for boundary in re.finditer(r"(?<=[.!?])\s+", text):
        if boundary.start() - 1 in protected:
            continue
        sentences.append(text[start:boundary.start()])
        start = boundary.end()
    if text[start:]:
        sentences.append(text[start:])
    return sentences


def _parse_json_object(raw: Any) -> dict | None:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(text[start : end + 1])
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    return parsed if isinstance(parsed, dict) else None


def _model_name() -> str:
    return os.getenv("CLAUDE_OPUS_MODEL", "claude-opus-4-5-20251101")


