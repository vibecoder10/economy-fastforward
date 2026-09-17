"""Narrow identity checks for contextual named-submarine excerpts.

This module deliberately separates a source passage that names the locked boat
without its hull number from the existing strict identity matcher.  A
contextual match is never an identity proof: it must be paired with a reviewed
strict anchor from the same claim.
"""
from __future__ import annotations

import re
from typing import Any

from factual_machine_research import candidate_mentions_machine, named_submarine_target


_SS_HULL_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<prefix>AGSS|SSBN|SSGN|SSN|SSG|SS)"
    r"[\s.\-‐‑–—]*(?P<number>\d+)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_FOREIGN_NAVAL_RE = re.compile(r"(?<![A-Za-z0-9])(?:HMS|HMAS|IJN|HNLMS)\b", re.IGNORECASE)


def _uss_prefix_pattern() -> str:
    """USS with conventional, dotted, and spaced spellings."""
    return r"(?<![A-Za-z0-9])U\s*\.?\s*S\s*\.?\s*S\.?"


def _name_pattern(name: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", name)
    if not words:
        return ""
    return r"(?<![A-Za-z0-9])" + r"[\s._,'’\-–—/]+".join(
        re.escape(word) for word in words
    ) + r"(?![A-Za-z0-9])"


def contextual_named_excerpt(text: Any, machine: Any) -> bool:
    """Whether *text* is a carefully bounded contextual name-only excerpt.

    Exact named-submarine evidence continues through ``candidate_mentions_machine``.
    This accepts only the remaining case where a complete USS name is present,
    all SS-family designations agree with the locked boat, and no competing
    naval identity appears in the passage.
    """
    source = str(text or "")
    target = named_submarine_target(machine)
    if not source or target is None or candidate_mentions_machine(source, machine):
        return False
    if _FOREIGN_NAVAL_RE.search(source):
        return False

    name = _name_pattern(target["name"])
    if not name:
        return False
    uss = _uss_prefix_pattern()
    target_mention = re.compile(uss + r"\s+" + name, re.IGNORECASE)
    if not target_mention.search(source):
        return False

    # A second USS name is competing evidence.  Treat any USS prefix that is
    # not immediately followed by the full locked name as another vessel.
    for match in re.finditer(uss, source, re.IGNORECASE):
        if not re.match(r"\s+" + name, source[match.end():], re.IGNORECASE):
            return False

    allowed_prefixes = {target["prefix"]}
    if target["prefix"] in {"SS", "AGSS"}:
        allowed_prefixes.update({"SS", "AGSS"})
    for hull in _SS_HULL_RE.finditer(source):
        if hull.group("prefix").upper() not in allowed_prefixes or hull.group("number") != target["number"]:
            return False
    return True


def _candidate_rows(candidates: Any) -> dict[str, dict] | None:
    values = candidates.values() if isinstance(candidates, dict) else candidates
    if not isinstance(values, (list, tuple)) and not hasattr(values, "__iter__"):
        return None
    rows: dict[str, dict] = {}
    for candidate in values:
        if not isinstance(candidate, dict):
            return None
        excerpt_id = candidate.get("excerpt_id")
        locked_machine = candidate.get("_locked_machine")
        if not isinstance(excerpt_id, str) or not excerpt_id.strip() or not isinstance(locked_machine, str) or not locked_machine.strip():
            return None
        excerpt_id = excerpt_id.strip()
        if excerpt_id in rows:
            return None
        text = str(candidate.get("text") or "")
        # Do not trust a model- or cache-supplied flag.  This is recomputed
        # from the locked identity every time a review is accepted.
        rows[excerpt_id] = {
            "candidate": candidate,
            "locked_machine": locked_machine,
            "identity_requires_review": contextual_named_excerpt(text, locked_machine),
        }
    return rows


def _evidence_rows(evidence: Any, candidates: dict[str, dict]) -> list[dict] | None:
    if not isinstance(evidence, list):
        return None
    output: list[dict] = []
    for row in evidence:
        # Assessment quote rows also carry source URL/title/locator metadata.
        # Identity binding uses the already-normalized excerpt_id and quote,
        # without making callers strip that provenance first.
        if not isinstance(row, dict):
            return None
        excerpt_id, quote = row.get("excerpt_id"), row.get("quote")
        if not isinstance(excerpt_id, str) or not isinstance(quote, str):
            return None
        excerpt_id, quote = excerpt_id.strip(), quote.strip()
        if not excerpt_id or not quote or excerpt_id not in candidates:
            return None
        output.append({"excerpt_id": excerpt_id, "quote": quote})
    return output


def validate_identity_reviews(raw: Any, evidence: Any, candidates: Any) -> list[dict] | None:
    """Validate model identity judgments against same-claim strict anchors.

    ``raw`` is the list returned by the model for ``identity_reviews``.  The
    function returns normalized reviews only after binding them to recomputed
    contextual flags and actual strict identity text in ``evidence``.
    """
    candidate_rows = _candidate_rows(candidates)
    if candidate_rows is None:
        return None
    evidence_rows = _evidence_rows(evidence, candidate_rows)
    if evidence_rows is None:
        return None
    contextual_ids = {
        row["excerpt_id"] for row in evidence_rows
        if candidate_rows[row["excerpt_id"]]["identity_requires_review"]
    }
    if isinstance(raw, dict):
        raw = raw.get("identity_reviews")
    if not isinstance(raw, list):
        return None
    if not contextual_ids:
        return [] if not raw else None
    if len(raw) != len(contextual_ids):
        return None

    evidence_by_id = {row["excerpt_id"]: row for row in evidence_rows}
    normalized: list[dict] = []
    reviewed_ids: set[str] = set()
    for review in raw:
        if not isinstance(review, dict) or set(review) != {
            "excerpt_id", "status", "anchor_excerpt_id", "reason"
        }:
            return None
        excerpt_id = review.get("excerpt_id")
        anchor_id = review.get("anchor_excerpt_id")
        reason = review.get("reason")
        if (not isinstance(excerpt_id, str) or not isinstance(anchor_id, str) or not isinstance(reason, str)
                or review.get("status") != "same_machine"):
            return None
        excerpt_id, anchor_id, reason = excerpt_id.strip(), anchor_id.strip(), reason.strip()
        if (excerpt_id not in contextual_ids or excerpt_id in reviewed_ids or not reason or len(reason) > 1500
                or anchor_id not in evidence_by_id or anchor_id == excerpt_id):
            return None
        anchor = candidate_rows[anchor_id]
        if anchor["identity_requires_review"]:
            return None
        if not candidate_mentions_machine(evidence_by_id[anchor_id]["quote"], anchor["locked_machine"]):
            return None
        reviewed_ids.add(excerpt_id)
        normalized.append({
            "excerpt_id": excerpt_id,
            "status": "same_machine",
            "anchor_excerpt_id": anchor_id,
            "reason": reason,
        })
    if reviewed_ids != contextual_ids:
        return None
    return normalized
