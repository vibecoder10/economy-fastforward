"""Strict class-context extraction for one named SS-family submarine."""
from __future__ import annotations

import re
from typing import Any

from factual_machine_research import named_submarine_target, _NAMED_SUBMARINE_HULL_RE


_CLASS_TITLE_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9 .,'’\-/]{0,80}?)(?:-class|\s+class)\b", re.I)
_DESIGN_MARKER_RE = re.compile(r"\b(?:design(?:ed|ing)?|construction|constructed|built|building|hull|engineering)\b", re.I)


def _compact(value: Any) -> str:
    return " ".join(str(value or "").split())


def _name_pattern(name: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", name)
    return (r"(?<![A-Za-z0-9])" + r"[\s._,'’\-–—/]+".join(map(re.escape, words))
            + r"(?![A-Za-z0-9])") if words else ""


def _class_title(section: str) -> bool:
    match = _CLASS_TITLE_RE.match(section)
    if not match:
        return False
    return 1 <= len(re.findall(r"[A-Za-z0-9]+", match.group(1))) <= 4


def _target_member_heading(section: str, machine: str) -> bool:
    target = named_submarine_target(machine)
    if not target:
        return False
    heading = _compact(section)[:200]
    # A table of contents may list every member; only a publisher member
    # heading that begins with the locked name can bind class context.
    if not re.match(r"^\s*(?:USS\s+)?" + _name_pattern(target["name"]), heading, re.I):
        return False
    allowed = {target["prefix"]}
    if target["prefix"] in {"SS", "AGSS"}:
        allowed.update({"SS", "AGSS"})
    for hull in _NAMED_SUBMARINE_HULL_RE.finditer(heading):
        if hull.group("prefix").upper() not in allowed or hull.group("number") != target["number"]:
            return False
    exact_hull = re.search(
        r"(?<![A-Za-z0-9])(?:" + "|".join(map(re.escape, sorted(allowed)))
        + r")[\s.\-‐‑–—]*" + re.escape(target["number"]) + r"(?![A-Za-z0-9])", heading, re.I,
    )
    submarine_number = (target["prefix"] in {"SS", "AGSS"} and re.search(
        r"\bSubmarine(?:\s+Torpedo\s+Boat)?\s+No\.?\s*" + re.escape(target["number"]) + r"\b", heading, re.I,
    ))
    for number in re.finditer(r"\bSubmarine(?:\s+Torpedo\s+Boat)?\s+No\.?\s*(\d+)\b", heading, re.I):
        if number.group(1) != target["number"]:
            return False
    return bool(exact_hull or submarine_number)


def class_context_candidate(text: Any, machine: str, max_chars: int = 8000) -> str:
    """Return one original, bounded class-to-member section range or empty text."""
    target = named_submarine_target(machine)
    if not target:
        return ""
    sections = [_compact(part) for part in str(text or "").split("\n\n")]
    sections = [section for section in sections if section]
    for member, section in enumerate(sections):
        if not _target_member_heading(section, machine):
            continue
        # Prefer the nearest qualifying publisher class heading before the
        # member. This excludes page chrome while preserving the original
        # contiguous class/design/member range.
        for start in range(member - 1, -1, -1):
            if not _class_title(sections[start]):
                continue
            if not any(_DESIGN_MARKER_RE.search(item) for item in sections[start + 1:member]):
                continue
            candidate = "\n\n".join(sections[start:member + 1])
            return candidate if len(candidate) <= max_chars else ""
    return ""


def is_verified_class_context(text: Any, machine: str, max_chars: int = 8000) -> bool:
    """Recompute the class-context contract from candidate text; never trust flags."""
    candidate = class_context_candidate(text, machine, max_chars=max_chars)
    return bool(candidate and candidate == str(text or "").strip())
