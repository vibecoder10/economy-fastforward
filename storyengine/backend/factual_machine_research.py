"""Deterministic evidence cards for short factual machine summaries.

This opt-in contract copies verified fetched excerpts into a compact card. It
does not turn model-written claims into evidence and does not impose the Anton
story-beat contract used by legacy Designed vs Used videos.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


FACTUAL_MACHINE_SCRIPT_CONTRACT = "factual_100_v1"
_APPROVED_CAPTURE_METHODS = {"fetched_page", "tavily_raw_content", "national_archives_api"}
_GENERIC_IDENTITY_WORDS = {
    "boeing", "consolidated", "convair", "douglas", "northrop", "lockheed", "martin",
    "hms", "uss", "hmas", "hmcs", "hmnzs", "hmis", "rfa", "sms", "ijn", "rms", "ins",
    "class", "the",
}
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])(?:\d[\d,]*(?:\.\d+)?(?:%|st|nd|rd|th)?)(?![A-Za-z0-9])")
_NAMED_SUBMARINE_HULL_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<prefix>AGSS|SSBN|SSGN|SSN|SSG|SS)[\s\-]?(?P<number>\d+)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_NAMED_SUBMARINE_TARGET_RE = re.compile(
    r"^\s*(?:AGSS|SSBN|SSGN|SSN|SSG|SS)[\s\-]?\d+(?:\s+|\s*[-–—]\s*)USS\s+(?P<name>[A-Za-z0-9][A-Za-z0-9 .,'’\-–—/]*)\s*$",
    re.IGNORECASE,
)


def _words(value: Any) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(value or "").casefold())


def _identity_key(value: Any) -> str:
    return "".join(_words(value))


def named_submarine_target(machine: Any) -> dict[str, str] | None:
    """Parse one exact USS submarine target, never a class or hull range.

    The factual evidence contract needs a stricter path for the runtime's
    named-submarine roster: a target is a single SS-family hull plus its full
    USS name.  Class/range display labels retain the existing class matcher.
    """
    raw = " ".join(str(machine or "").split())
    if not raw or re.search(r"\b(?:class|through|range)\b", raw, re.IGNORECASE):
        return None
    hulls = list(_NAMED_SUBMARINE_HULL_RE.finditer(raw))
    target = _NAMED_SUBMARINE_TARGET_RE.fullmatch(raw)
    if len(hulls) != 1 or target is None:
        return None
    name = target.group("name").strip()
    name_key = _identity_key(name)
    if not name_key:
        return None
    hull = hulls[0]
    return {
        "prefix": hull.group("prefix").upper(),
        "number": hull.group("number"),
        "name": name,
        "name_key": name_key,
    }


def _named_submarine_excerpt_matches(text: Any, target: dict[str, str]) -> bool:
    """Require the complete submarine name and its target hull in one excerpt."""
    source = str(text or "")
    name_words = re.findall(r"[A-Za-z0-9]+", target["name"])
    if not name_words:
        return False
    name_pattern = r"(?<![A-Za-z0-9])" + r"[\s._,'’\-–—/]*".join(
        re.escape(word) for word in name_words
    ) + r"(?![A-Za-z0-9])"
    if not re.search(name_pattern, source, re.IGNORECASE):
        return False
    prefixes = ("AGSS", "SS") if target["prefix"] in {"AGSS", "SS"} else (target["prefix"],)
    prefix_pattern = "|".join(re.escape(prefix) for prefix in prefixes)
    hull_pattern = (
        r"(?<![A-Za-z0-9])(?:" + prefix_pattern + r")[\s.\-‐‑–—]*"
        + re.escape(target["number"]) + r"(?![A-Za-z0-9])"
    )
    return bool(re.search(hull_pattern, source, re.IGNORECASE))


_NAVAL_HULL_PREFIX_RE = re.compile(
    r"^(?:(?:AGSS|SSBN|SSGN|SSN|SS)-?\d+\+?)(?:\s*(?:,|through|to|range)\s*(?:(?:AGSS|SSBN|SSGN|SSN|SS)-?\d+\+?)?)*\s+",
    re.IGNORECASE,
)


def factual_research_subject(machine: Any) -> str:
    """Return a searchable factual subject without changing locked identity.

    Documentary roster display names can begin with a naval hull range.  That
    range is useful bookkeeping, but it is not normally repeated in source
    prose about the class.  Remove only that syntactic prefix; retain the
    actual class/variant words, including single-letter class names.
    """
    raw = str(machine or "").strip()
    return _NAVAL_HULL_PREFIX_RE.sub("", raw).strip() or raw


def _matches_designation(text: str, machine: str) -> bool:
    """True only for a complete designation from the locked display name."""
    for code in re.findall(r"\b(?:AGSS|SSBN|SSGN|SSN|SS)-?\d+\+?\b", machine, re.I):
        pieces = re.findall(r"[A-Za-z]+|[0-9]+", code.rstrip("+"))
        pattern = r"(?<![a-z0-9])" + r"[\s.\-‐‑–—]*".join(re.escape(piece) for piece in pieces) + r"(?![a-z0-9])"
        if re.search(pattern, text, re.I):
            return True
    return False


def _matches_class_subject(text: str, subject: str) -> bool:
    """Match a meaningful class phrase, never a bare class/range token."""
    words = _words(subject)
    if len(words) < 2 or words[-1] != "class" or all(word in {"class", "through"} for word in words):
        return False
    pattern = r"(?<![a-z0-9])" + r"[^a-z0-9]+".join(re.escape(word) for word in words) + r"(?![a-z0-9])"
    return bool(re.search(pattern, text, re.I))


def _matches_class_lead_with_designation(text: str, machine: str, subject: str) -> bool:
    """Require both the distinctive lead-vessel name and a locked hull code."""
    lead_words = _words(re.sub(r"\bclass\b", "", subject, flags=re.I))
    if not lead_words or not _matches_designation(text, machine):
        return False
    lead = r"[^a-z0-9]+".join(re.escape(word) for word in lead_words)
    return bool(re.search(r"(?<![a-z0-9])" + lead + r"(?![a-z0-9])", text, re.I))


def _matches_single_hull_lead(text: str, machine: str, subject: str) -> bool:
    """Accept a named lead vessel only for a single locked hull identity.

    Some historic one-boat source pages call the vessel by its name rather than
    repeat its hull code or class label.  Keep this narrow: range labels never
    use it, and the same sentence must tie the name to a Navy submarine event.
    """
    hulls = re.findall(r"\b(?:AGSS|SSBN|SSGN|SSN|SS)-?\d+\b", machine, re.I)
    lead_words = _words(re.sub(r"\bclass\b", "", subject, flags=re.I))
    if len(hulls) != 1 or not lead_words:
        return False
    lead = r"[\s.\-‐‑–—']+".join(re.escape(word) for word in lead_words)
    name = re.compile(r"(?<![a-z0-9])" + lead + r"(?![a-z0-9])", re.I)
    vessel_event = re.compile(
        r"\b(?:navy\s+(?:trials|purchased|commissioned)|"
        r"(?:trials|modifications)\s+(?:to|of)|"
        r"purchased\s+(?:the\s+)?submarine|"
        r"commissioned\s+(?:the\s+)?submarine)\b",
        re.I,
    )
    return any(
        name.search(sentence)
        and "submarine" in sentence.casefold()
        and vessel_event.search(sentence)
        for sentence in re.split(r"[.!?;]+", text)
    )


def is_factual_machine_contract(payload: Any) -> bool:
    return isinstance(payload, dict) and payload.get("machine_script_contract") == FACTUAL_MACHINE_SCRIPT_CONTRACT


def _candidate_traceable(candidate: Any) -> bool:
    if not isinstance(candidate, dict):
        return False
    method = str(candidate.get("source_capture_method") or "").strip()
    hostname = (urlparse(str(candidate.get("source_url") or "")).hostname or "").lower()
    # Fetching an AI-generated encyclopedia does not turn its generated prose
    # into independent historical evidence. Apply this to old cached packets too.
    if hostname == "grokipedia.com" or hostname.endswith(".grokipedia.com"):
        return False
    return bool(
        str(candidate.get("excerpt_id") or "").strip()
        and str(candidate.get("text") or "").strip()
        and str(candidate.get("source_url") or "").strip()
        and str(candidate.get("locator") or candidate.get("excerpt_id") or "").strip()
        and (method in _APPROVED_CAPTURE_METHODS or method.startswith("wayback:"))
    )


def candidate_mentions_machine(text: Any, machine: Any) -> bool:
    """Match exact aircraft designations or distinctive vessel names."""
    raw_machine = str(machine or "").strip()
    source_text = str(text or "")
    submarine = named_submarine_target(raw_machine)
    if submarine:
        return _named_submarine_excerpt_matches(source_text, submarine)
    subject = factual_research_subject(raw_machine)
    # Class display labels with naval range bookkeeping require the actual
    # class phrase, or both a distinctive lead-vessel name and exact hull.
    # Do this before the legacy named-vessel guard, whose ordered-token fallback would otherwise
    # require source prose to repeat words such as "through".
    if re.search(r"\bclass\b", subject, re.I):
        return (_matches_class_subject(source_text, subject)
                or _matches_class_lead_with_designation(source_text, raw_machine, subject)
                or _matches_single_hull_lead(source_text, raw_machine, subject))
    # Match aircraft designations before nickname tokenization. Dropping the
    # digit in XNBL-1 made the old phrase impossible to find; using only
    # Superfortress admitted B-50 evidence for a B-29. Named ships retain
    # their name guard: a matching pennant number is never enough.
    named_ship = re.search(r"\b(?:HMS|USS|HMAS|HMCS|HMNZS|HMIS|RFA|SMS|IJN|RMS|INS|class)\b", raw_machine, re.I)
    if not named_ship:
        designations = re.findall(r"\b[A-Z]{1,4}[-‐‑–—]?\d{1,4}[A-Z]?\b", raw_machine, re.I)
        if designations:
            for code in designations:
                pieces = re.findall(r"[A-Za-z]+|[0-9]+", code)
                pattern = r"(?<![a-z0-9])" + r"[\s.\-‐‑–—]*".join(re.escape(piece) for piece in pieces) + r"(?![a-z0-9])"
                if re.search(pattern, source_text, re.I):
                    return True
            return False
        # Some early naval aircraft use a letter-only type plus a nickname.
        # Keep BOTH, rather than deleting the short type token (AJ Savage).
        short_type = re.match(
            r"^(?:North American|General Dynamics|Northrop Grumman|Boeing|Martin|Douglas|Convair|Rockwell)\s+([A-Z]{1,3})\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)$",
            raw_machine,
        )
        if short_type:
            label = short_type.group(1) + " " + short_type.group(2)
            phrase = r"(?<![a-z0-9])" + r"[\s.\-']+".join(re.escape(word) for word in label.split()) + r"(?![a-z0-9])"
            return bool(re.search(phrase, source_text, re.I))
    tokens = [
        word for word in _words(raw_machine)
        if len(word) >= 3 and word not in _GENERIC_IDENTITY_WORDS and not word.isdigit()
    ]
    # Hull/pennant and roster-order numbers disambiguate metadata but do not
    # substitute for the vessel name. A page about another 1918 ship must not
    # become evidence for HMS Eagle merely because the label carries 1918.
    tokens = [token for token in tokens if not re.fullmatch(r"[a-z]{1,3}\d{1,4}", token)]
    if tokens:
        phrase = r"(?<![a-z0-9])" + r"[\s.\-']+".join(re.escape(token) for token in tokens) + r"(?![a-z0-9])"
        return bool(re.search(phrase, str(text or ""), flags=re.IGNORECASE))
    # Aircraft/program labels may consist solely of an alphanumeric
    # designation after the manufacturer is removed.
    designation = re.search(r"\b[A-Z]{1,4}-?\d{1,4}[A-Z]?\b", raw_machine, flags=re.IGNORECASE)
    if not designation:
        return False
    pieces = re.findall(r"[a-z0-9]+", designation.group(0).casefold())
    pattern = r"(?<![a-z0-9])" + r"[\s.\-]*".join(re.escape(piece) for piece in pieces) + r"(?![a-z0-9])"
    return bool(re.search(pattern, str(text or ""), flags=re.IGNORECASE))


def useful_factual_candidates(machine: str, package: Any, *, limit: int = 8) -> list[dict]:
    if not isinstance(package, dict):
        return []
    eligible: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for candidate in package.get("candidate_excerpts") or []:
        if not _candidate_traceable(candidate):
            continue
        text = str(candidate.get("text") or "").strip()
        if not candidate_mentions_machine(text, machine):
            continue
        key = (str(candidate.get("source_url") or "").strip(), text.casefold())
        if key in seen:
            continue
        seen.add(key)
        eligible.append(candidate)
    bounded = max(1, min(int(limit), 12))
    # Prefer independent source URLs before taking a second excerpt from the
    # same page. This keeps a small factual card useful for cross-checking.
    accepted: list[dict] = []
    used_urls: set[str] = set()
    for candidate in eligible:
        url = str(candidate.get("source_url") or "").strip()
        if url in used_urls:
            continue
        accepted.append(candidate)
        used_urls.add(url)
        if len(accepted) >= bounded:
            return accepted
    for candidate in eligible:
        if candidate in accepted:
            continue
        accepted.append(candidate)
        if len(accepted) >= bounded:
            break
    return accepted


def factual_package_contract_warnings(machine: str, package: Any) -> list[str]:
    if not isinstance(package, dict):
        return ["missing verified factual source package"]
    if _identity_key(package.get("machine")) != _identity_key(machine):
        return ["verified factual source package identity does not match the locked machine"]
    if not useful_factual_candidates(machine, package):
        return ["verified factual source package has no traceable exact-machine excerpts"]
    return []


def _numeric_tokens(text: str) -> list[str]:
    return list(dict.fromkeys(match.group(0) for match in _NUMBER_RE.finditer(text)))


def build_factual_evidence_card(machine: str, package: Any) -> dict:
    """Build a card only from exact retrieved candidate rows."""
    segments = []
    for index, candidate in enumerate(useful_factual_candidates(machine, package), start=1):
        text = str(candidate.get("text") or "").strip()
        excerpt_id = str(candidate.get("excerpt_id") or "").strip()
        segments.append({
            "evidence_id": f"FACT-{index}",
            "kind": "factual_source",
            "claim": text,
            "source_excerpt": text,
            "source_excerpt_id": excerpt_id,
            "source_id": str(candidate.get("source_id") or "").strip(),
            "source_url": str(candidate.get("source_url") or "").strip(),
            "source_title": str(candidate.get("source_title") or "").strip(),
            "source_capture_method": str(candidate.get("source_capture_method") or "").strip(),
            "locator": str(candidate.get("locator") or excerpt_id).strip(),
            "numeric_tokens": _numeric_tokens(text),
            "confidence": "unassessed",
            "provenance_status": "captured",
        })
    card = {
        "schema_version": 3,
        "machine_research_contract": FACTUAL_MACHINE_SCRIPT_CONTRACT,
        "unit": machine,
        "include": True,
        "confidence": "unassessed",
        "provenance_status": "captured",
        "evidence_segments": segments,
    }
    if isinstance(package, dict) and isinstance(package.get("claim_assessment"), dict):
        card["claim_assessment"] = dict(package["claim_assessment"])
    return card


def factual_card_contract_warnings(machine: str, card: Any, package: Any) -> list[str]:
    warnings = factual_package_contract_warnings(machine, package)
    if not isinstance(card, dict):
        return warnings + ["missing factual evidence card"]
    if card.get("machine_research_contract") != FACTUAL_MACHINE_SCRIPT_CONTRACT:
        warnings.append("factual evidence card contract marker is missing")
    if _identity_key(card.get("unit")) != _identity_key(machine):
        warnings.append("factual evidence card identity does not match the locked machine")
    candidates = {
        str(row.get("excerpt_id") or "").strip(): row
        for row in useful_factual_candidates(machine, package, limit=12)
    }
    segments = card.get("evidence_segments")
    if not isinstance(segments, list) or not segments:
        warnings.append("factual evidence card has no source excerpts")
        return list(dict.fromkeys(warnings))
    for index, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict):
            warnings.append(f"factual evidence segment {index} is not an object")
            continue
        excerpt_id = str(segment.get("source_excerpt_id") or "").strip()
        candidate = candidates.get(excerpt_id)
        exact_text = str((candidate or {}).get("text") or "").strip()
        claim = str(segment.get("claim") or "").strip()
        excerpt = str(segment.get("source_excerpt") or "").strip()
        if not candidate or claim != exact_text or excerpt != exact_text:
            warnings.append(f"factual evidence segment {index} is not an exact fetched excerpt")
            continue
        if str(segment.get("source_url") or "").strip() != str(candidate.get("source_url") or "").strip():
            warnings.append(f"factual evidence segment {index} source URL does not match its fetched excerpt")
        if str(segment.get("locator") or "").strip() != str(candidate.get("locator") or excerpt_id).strip():
            warnings.append(f"factual evidence segment {index} locator does not match its fetched excerpt")
        if list(segment.get("numeric_tokens") or []) != _numeric_tokens(exact_text):
            warnings.append(f"factual evidence segment {index} numeric metadata does not match its fetched excerpt")
    return list(dict.fromkeys(warnings))
