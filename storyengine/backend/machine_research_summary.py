"""Versioned factual research briefings stored on one machine research card."""
from __future__ import annotations

from typing import Any

from factual_machine_pipeline import source_fingerprint
from factual_machine_summary import REVIEW_CONTEXT_VERSION


RESEARCH_SUMMARY_VERSION = 2


def is_recoverable_research_error(exc: BaseException, _source_wrapper_depth: int = 0) -> bool:
    """Return true only for bounded per-machine transport outages.

    Account, credit, rate-limit, database, and programming failures deliberately
    remain chain-wide stops.
    """
    # Source discovery deliberately wraps fetch failures so its caller can
    # retain provenance. Unwrap only that known wrapper, and only two links,
    # never arbitrary errors (which could hide a database/programming stop).
    try:
        from factual_source_search import SourceDiscoveryError
        if (isinstance(exc, SourceDiscoveryError) and exc.__cause__ is not None
                and _source_wrapper_depth < 2):
            return is_recoverable_research_error(exc.__cause__, _source_wrapper_depth + 1)
    except ImportError:
        pass
    try:
        import httpx
        if isinstance(exc, (TimeoutError, ConnectionError, httpx.TransportError)):
            return True
    except ImportError:
        if isinstance(exc, (TimeoutError, ConnectionError)):
            return True
    try:
        import anthropic
        timeout_or_connection = tuple(item for item in (
            getattr(anthropic, "APITimeoutError", None),
            getattr(anthropic, "APIConnectionError", None),
        ) if isinstance(item, type))
        if timeout_or_connection and isinstance(exc, timeout_or_connection):
            return True
        status_error = getattr(anthropic, "APIStatusError", None)
        return bool(
            isinstance(status_error, type) and isinstance(exc, status_error)
            and isinstance(getattr(exc, "status_code", None), int)
            and exc.status_code >= 500
        )
    except ImportError:
        return False


def research_summary_ready(
    machine: str,
    package: Any,
    summary: Any,
    subject_context: str = "",
) -> bool:
    """True only for a current passed briefing for this exact source package.

    ``summary`` is deliberately the card's ``research_summary`` object, never
    the enclosing card.  That prevents readiness from accidentally accepting an
    excerpt-only factual card or recursively grading card fields as a summary.
    """
    if not isinstance(summary, dict):
        return False
    from research_claim_assessment import current_assessment, has_supported_claim
    assessment = current_assessment(machine, package, subject_context)
    return (
        summary.get("schema_version") == RESEARCH_SUMMARY_VERSION
        and summary.get("passed") is True
        and bool(str(summary.get("paragraph") or "").strip())
        and isinstance(summary.get("claim_map"), list)
        and bool(summary.get("claim_map"))
        and isinstance(summary.get("sources"), list)
        and bool(summary.get("sources"))
        and summary.get("review_context_version") == REVIEW_CONTEXT_VERSION
        and summary.get("subject_context") == str(subject_context or "")
        and summary.get("source_fingerprint") == source_fingerprint(machine, package)
        and assessment is not None and has_supported_claim(assessment)
        and summary.get("claim_assessment") == assessment
    )


def saved_research_summary(
    machine: str,
    package: Any,
    result: Any,
    subject_context: str = "",
) -> dict:
    """Shape a generated/reviewed result for storage on a factual card."""
    result = result if isinstance(result, dict) else {}
    from research_claim_assessment import current_assessment
    assessment = current_assessment(machine, package, subject_context)
    return {
        "schema_version": RESEARCH_SUMMARY_VERSION,
        "paragraph": str(result.get("paragraph") or "").strip(),
        "claim_map": list(result.get("claim_map") or []),
        "sources": list(result.get("sources") or []),
        "passed": result.get("passed") is True,
        "warnings": [str(w) for w in (result.get("warnings") or []) if str(w).strip()],
        "subject_context": str(subject_context or ""),
        "source_fingerprint": source_fingerprint(machine, package),
        "review_context_version": result.get("review_context_version", REVIEW_CONTEXT_VERSION),
        "claim_assessment": assessment,
    }
