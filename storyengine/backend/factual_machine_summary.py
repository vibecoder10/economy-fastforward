"""Small source-grounded writer for one locked DVsU machine.

This module deliberately has no dependency on the legacy Anton paragraph
validator.  It accepts the already-fetched ``candidate_excerpts`` package,
asks the initialized Anthropic wrapper for a short factual summary, validates
its mechanical provenance, and then asks the model for an independent factual
review using only the citations selected by the writer.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from factual_machine_research import (
    candidate_mentions_machine,
    factual_package_contract_warnings,
    useful_factual_candidates,
)


MAX_WORDS = 100
MAX_DRAFT_ATTEMPTS = 2
_DESIGNATION_RE = re.compile(r"\b[A-Z]{1,4}[\s.-]?\d{1,4}[A-Z]?\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])\d[\d,]*(?:\.\d+)?(?:st|nd|rd|th)?(?![A-Za-z0-9])")
_NUMBER_WORDS = {
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
    "nineteen", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
    "hundred", "thousand", "million", "billion", "dozen",
}


def _compact(value: Any) -> str:
    return " ".join(str(value or "").split())


def _package_identity_warnings(machine: str, source_package: Any) -> list[str]:
    if not _compact(machine):
        return ["Locked machine is required."]
    return [str(warning) for warning in factual_package_contract_warnings(machine, source_package)]


def _eligible_candidates(machine: str, source_package: dict) -> dict[str, dict]:
    registry = {
        _compact(row.get("source_id")): row
        for row in source_package.get("sources") or []
        if isinstance(row, dict) and _compact(row.get("source_id"))
    }
    eligible: dict[str, dict] = {}
    for raw in useful_factual_candidates(machine, source_package, limit=12):
        excerpt_id = _compact(raw.get("excerpt_id") or raw.get("locator"))
        source_id = _compact(raw.get("source_id"))
        url = _compact(raw.get("source_url"))
        locator = _compact(raw.get("locator") or excerpt_id)
        text = _compact(raw.get("text"))
        parsed_url = urlparse(url)
        if not (
            excerpt_id and url and locator and text
            and parsed_url.scheme in {"http", "https"} and parsed_url.netloc
            and candidate_mentions_machine(text, machine)
        ):
            continue
        registered = registry.get(source_id)
        if registry and (
            registered is None
            or _compact(registered.get("url")) != url
        ):
            continue
        eligible[excerpt_id] = dict(raw)
    return eligible


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w]+(?:[-'’][\w]+)*\b", str(text or ""), flags=re.UNICODE))


def _sentences(paragraph: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", paragraph.strip()) if part.strip()]


def _numeric_keys(text: str, machine: str) -> set[str]:
    scrubbed = str(text or "")
    for designation in _DESIGNATION_RE.findall(machine):
        scrubbed = re.sub(re.escape(designation), " ", scrubbed, flags=re.IGNORECASE)
    keys = {
        re.sub(r"(?:st|nd|rd|th)$", "", match.lower()).replace(",", "")
        for match in _NUMBER_RE.findall(scrubbed)
    }
    keys.update(
        word for word in re.findall(r"[A-Za-z]+", scrubbed.lower())
        if word in _NUMBER_WORDS
    )
    return keys


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


def _validate_draft(
    machine: str,
    raw: Any,
    candidates: dict[str, dict],
) -> tuple[dict, list[str], list[dict]]:
    parsed = _parse_json_object(raw)
    if parsed is None:
        return {"paragraph": "", "claim_map": []}, ["Writer returned invalid JSON."], []

    paragraph = _compact(parsed.get("paragraph"))
    raw_claim_map = parsed.get("claim_map")
    draft = {"paragraph": paragraph, "claim_map": raw_claim_map if isinstance(raw_claim_map, list) else []}
    warnings: list[str] = []
    sources: list[dict] = []
    source_keys: set[tuple[str, str]] = set()

    if not paragraph:
        warnings.append("Paragraph is required.")
    if _word_count(paragraph) > MAX_WORDS:
        warnings.append(f"Paragraph exceeds the {MAX_WORDS}-word hard cap; rewrite it without truncation.")
    if paragraph and not candidate_mentions_machine(paragraph, machine):
        warnings.append(f"Paragraph does not name the exact locked machine {machine}.")

    paragraph_sentences = _sentences(paragraph)
    if not isinstance(raw_claim_map, list) or not raw_claim_map:
        warnings.append("Every sentence needs a claim_map row with evidence.")
        raw_claim_map = []

    mapped_sentences: list[str] = []
    normalized_rows: list[dict] = []
    for index, row in enumerate(raw_claim_map, start=1):
        if not isinstance(row, dict):
            warnings.append(f"claim_map row {index} must be an object.")
            continue
        sentence = _compact(row.get("sentence"))
        if sentence not in paragraph_sentences:
            warnings.append(f"claim_map row {index} sentence is not an exact sentence in the paragraph.")
        else:
            mapped_sentences.append(sentence)
        citations = row.get("citations")
        if not isinstance(citations, list) or not citations:
            warnings.append(f"claim_map row {index} needs at least one citation.")
            citations = []
        normalized_citations: list[dict] = []
        cited_text: list[str] = []
        for citation_index, citation in enumerate(citations, start=1):
            if not isinstance(citation, dict):
                warnings.append(f"claim_map row {index} citation {citation_index} must be an object.")
                continue
            excerpt_id = _compact(citation.get("excerpt_id"))
            quote = str(citation.get("quote") or "")
            candidate = candidates.get(excerpt_id)
            if candidate is None:
                warnings.append(f"claim_map row {index} cites unknown or wrong-machine excerpt {excerpt_id or '(missing)'}.")
                continue
            candidate_text = str(candidate.get("text") or "")
            if not quote or quote not in candidate_text:
                warnings.append(
                    f"claim_map row {index} citation {excerpt_id} quote is not an exact substring of the fetched excerpt."
                )
                continue
            provenance = {
                "excerpt_id": excerpt_id,
                "source_id": _compact(candidate.get("source_id")),
                "source_title": _compact(candidate.get("source_title")),
                "source_url": _compact(candidate.get("source_url")),
                "locator": _compact(candidate.get("locator") or excerpt_id),
                "quote": quote,
                "source_capture_method": _compact(candidate.get("source_capture_method")),
            }
            normalized_citations.append(provenance)
            cited_text.append(quote)
            source_key = (excerpt_id, quote)
            if source_key not in source_keys:
                sources.append(dict(provenance))
                source_keys.add(source_key)
        if sentence and cited_text:
            unsupported_numbers = sorted(_numeric_keys(sentence, machine) - _numeric_keys(" ".join(cited_text), machine))
            if unsupported_numbers:
                warnings.append(
                    f"claim_map row {index} introduced unsupported numerical detail(s): "
                    + ", ".join(unsupported_numbers)
                )
        normalized_rows.append({"sentence": sentence, "citations": normalized_citations})

    if paragraph_sentences and (
        len(mapped_sentences) != len(paragraph_sentences)
        or sorted(mapped_sentences) != sorted(paragraph_sentences)
    ):
        warnings.append("claim_map must cover every paragraph sentence exactly once.")
    draft["claim_map"] = normalized_rows
    return draft, list(dict.fromkeys(warnings)), sources


def _evidence_payload(candidates: dict[str, dict]) -> list[dict]:
    return [
        {
            "excerpt_id": excerpt_id,
            "source_id": _compact(candidate.get("source_id")),
            "source_title": _compact(candidate.get("source_title")),
            "source_url": _compact(candidate.get("source_url")),
            "locator": _compact(candidate.get("locator") or excerpt_id),
            "source_capture_method": _compact(candidate.get("source_capture_method")),
            "text": str(candidate.get("text") or "").strip(),
        }
        for excerpt_id, candidate in candidates.items()
    ]


def _writer_prompt(machine: str, evidence: list[dict], prior_issues: list[str]) -> str:
    repair = ""
    if prior_issues:
        repair = (
            "\nThe previous draft failed for these exact reasons. Correct them without adding facts:\n"
            + "\n".join(f"- {issue}" for issue in prior_issues)
        )
    return (
        f"Write a concise factual voiceover summary about the exact locked machine: {machine}.\n"
        f"Use only the fetched excerpts in EVIDENCE. The paragraph must be {MAX_WORDS} words or fewer. "
        "There is no minimum length, sentence count, dramatic twist, narrative beat, memorable-fact, or closer requirement. "
        "Do not truncate a claim to meet the cap; choose fewer supported facts. Do not invent or infer dates, numbers, "
        "names, relationships, causes, or outcomes. Keep numeric wording exactly as it appears in evidence. "
        "Every paragraph sentence needs one claim_map row containing that exact sentence and one or more citations. "
        "Every citation must contain an excerpt_id from EVIDENCE and a verbatim quote copied as an exact substring of "
        "that excerpt. Do not return URLs; code attaches locked provenance.\n"
        "Return only JSON with this shape: "
        '{"paragraph":"...","claim_map":[{"sentence":"exact complete sentence.",'
        '"citations":[{"excerpt_id":"S1-E1","quote":"exact source substring"}]}]}.\n'
        + repair
        + "\nEVIDENCE:\n"
        + json.dumps(evidence, ensure_ascii=False)
    )


def _review_prompt(machine: str, draft: dict) -> str:
    return (
        f"Independently fact-check this summary about the exact locked machine {machine}. "
        "Use only the cited verbatim quotes supplied below. Check every sentence for factual entailment, correct entity "
        "attribution, machine/class/era identity, dates and numbers. Reject a sentence when a quote mentions the locked "
        "machine but actually attributes the event or property to another machine. Reject source disagreement or ambiguity "
        "rather than resolving it by guesswork. Style, sentence count, narrative shape, drama, and completeness are outside "
        "this review. Return only JSON: {\"passed\":true|false,\"issues\":[\"specific issue\"]}.\n"
        "DRAFT WITH LOCKED PROVENANCE:\n"
        + json.dumps(draft, ensure_ascii=False)
    )


def _failed_result(paragraph: str = "", claim_map: list | None = None, warnings: list[str] | None = None,
                   sources: list[dict] | None = None) -> dict:
    return {
        "paragraph": paragraph,
        "word_count": _word_count(paragraph),
        "passed": False,
        "warnings": warnings or [],
        "claim_map": claim_map or [],
        "sources": sources or [],
    }


async def generate_factual_machine_summary(
    machine: str,
    source_package: dict,
    anthropic_client: Any,
) -> dict:
    """Generate and independently verify one <=100-word factual summary.

    The initialized client is used through the same async ``generate`` wrapper
    and keyword conventions as ``PipelineExecutor._run_static_script_hold``.
    Provider exceptions intentionally propagate to the caller.  Writer or
    referee contract failures get one targeted rewrite, then return a reviewable
    ``passed=False`` result instead of looping indefinitely.
    """
    identity_warnings = _package_identity_warnings(machine, source_package)
    if identity_warnings:
        return _failed_result(warnings=identity_warnings)
    if anthropic_client is None:
        raise ValueError("anthropic_client is required")

    candidates = _eligible_candidates(machine, source_package)
    if not candidates:
        return _failed_result(warnings=[
            f"Verified source package has no traceable approved excerpts for the exact locked machine {machine}."
        ])
    evidence = _evidence_payload(candidates)
    prior_issues: list[str] = []
    latest = _failed_result()

    for _attempt in range(MAX_DRAFT_ATTEMPTS):
        raw_draft = await anthropic_client.generate(
            prompt=_writer_prompt(machine, evidence, prior_issues),
            system_prompt=(
                "You compile short machine-history summaries from locked evidence. "
                "Output only the requested JSON and never add outside knowledge."
            ),
            max_tokens=900,
            temperature=0.1,
        )
        draft, mechanical_warnings, sources = _validate_draft(machine, raw_draft, candidates)
        latest = _failed_result(
            paragraph=draft["paragraph"],
            claim_map=draft["claim_map"],
            warnings=mechanical_warnings,
            sources=sources,
        )
        if mechanical_warnings:
            prior_issues = mechanical_warnings
            continue

        review_payload = {
            "paragraph": draft["paragraph"],
            "claim_map": draft["claim_map"],
        }
        raw_review = await anthropic_client.generate(
            prompt=_review_prompt(machine, review_payload),
            system_prompt=(
                "You are an independent factual referee. Judge only whether cited quotes entail the exact claims about "
                "the locked subject. Output only the requested JSON."
            ),
            max_tokens=450,
            temperature=0.0,
        )
        review = _parse_json_object(raw_review)
        if review is None or not isinstance(review.get("passed"), bool):
            prior_issues = ["Independent factual review returned invalid JSON."]
            latest["warnings"] = prior_issues
            continue
        review_issues = [
            _compact(issue) for issue in review.get("issues") or []
            if _compact(issue)
        ]
        if not review["passed"] or review_issues:
            prior_issues = [f"Factual review: {issue}" for issue in review_issues]
            if not prior_issues:
                prior_issues = ["Factual review rejected the draft without a specific issue."]
            latest["warnings"] = prior_issues
            continue

        return {
            "paragraph": draft["paragraph"],
            "word_count": _word_count(draft["paragraph"]),
            "passed": True,
            "warnings": [],
            "claim_map": draft["claim_map"],
            "sources": sources,
        }

    return latest
