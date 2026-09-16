"""Small, versioned contract for runtime-sized documentary roster selection."""
import hashlib
import json
import math
import re
from typing import Any


VERSION = 1
REPRESENTATIVE_POLICY = "one_named_machine_per_class_v1"


def representative_policy() -> str:
    return (
        "For class-based selections, choose exactly one real named machine from each selected class. "
        "Any source-verified member is acceptable; do not compare or rank sister machines. "
        "Put the individual machine name in name and its single designation in designation; "
        "put the class label in class_name. Never use a class label, hull-number range, or list "
        "as the machine identity. Retain class-wide counts/ranges only as class metadata. "
        "Verify the chosen machine belongs to that class and meets the title eligibility. "
        "Do not select two machines from the same class. Research and images must match the chosen machine."
    )


def representative_warnings(title: str, roster: list) -> list[str]:
    class_based = bool(re.search(r"\bclass(?:es)?\b", title, re.I)) or any(
        isinstance(row, dict) and (row.get("class_name") or re.search(r"\bclass(?:es)?\b", str(row.get("name", "")), re.I))
        for row in roster
    )
    if not class_based:
        return []
    warnings = []
    seen = set()
    for row in roster:
        if not isinstance(row, dict):
            warnings.append("Class selections require a named machine with class_name metadata")
            continue
        name = str(row.get("name") or row.get("title") or "").strip()
        designation = str(row.get("designation") or row.get("code") or "").strip()
        class_name = str(row.get("class_name") or "").strip()
        if not name or re.search(r"\bclass(?:es)?\b", name, re.I):
            warnings.append(f"{name or designation}: choose one named machine, not a class")
        if re.search(r"\b(?:through|to)\b|[,;/+]|\d\s*[-–—]\s*(?:[A-Za-z]+-?)?\d", designation, re.I):
            warnings.append(f"{designation}: choose one machine designation, not a range or list")
        if not class_name:
            warnings.append(f"{name}: record the selected machine's class_name")
        else:
            key = re.sub(r"[\W_]+", " ", class_name.casefold()).strip()
            key = re.sub(r"\s+class$", "", key)
            if key in seen:
                warnings.append(f"{class_name}: select only one machine per class")
            seen.add(key)
    return warnings


def selection_subject(title: str) -> str:
    """Separate title quantity wording from the factual eligibility subject."""
    return re.sub(r"^(?:every|all(?: of)?(?: the)?)\s+", "", str(title).strip(), flags=re.I)


def selection_source_data(payload: dict) -> dict:
    """Reuse evidence without importing previous exhaustive-writing instructions."""
    roster = payload.get("unit_roster") or []
    if not roster:
        for old in reversed(payload.get("roster_selection_history") or []):
            roster = (old.get("payload") or {}).get("unit_roster") or []
            if roster:
                break
    return {"candidate_entries": roster, "source_bibliography": payload.get("source_bibliography") or ""}


def bound_selection_candidates(draft: dict, target: int) -> dict:
    """Apply application-owned count to provider-ordered candidates before audit.

    Keep surplus candidates as evidence. Never fill an undersized list or accept
    any entry here: the independent factual audit still checks the entire result.
    """
    result = dict(draft)
    rows = result.get("unit_roster")
    if isinstance(rows, list) and len(rows) > target:
        result["roster_candidate_overflow"] = rows[target:]
        result["unit_roster"] = rows[:target]
        result["recommended_final_roster"] = [_display_name(row) for row in rows[:target]]
    return result


def selection_target(duration_minutes: Any, minutes_per_machine: Any = 1) -> int:
    """Return the requested number of sections; reject unusable pacing inputs."""
    try:
        duration = float(duration_minutes)
        pacing = float(minutes_per_machine)
    except (TypeError, ValueError) as exc:
        raise ValueError("duration and minutes_per_machine must be finite positive numbers") from exc
    if not (math.isfinite(duration) and math.isfinite(pacing)) or duration <= 0 or pacing <= 0:
        raise ValueError("duration and minutes_per_machine must be finite positive numbers")
    return max(1, math.floor(duration / pacing + 0.5))


def selection_settings(duration_minutes: Any, minutes_per_machine: Any = 1) -> dict:
    target = selection_target(duration_minutes, minutes_per_machine)
    return {
        "version": VERSION,
        "duration_minutes": float(duration_minutes),
        "minutes_per_machine": float(minutes_per_machine),
        "target_count": target,
    }


def selection_fingerprint(title: str, payload: dict) -> str:
    settings = (payload.get("roster_selection") or {}).get("settings")
    from roster_coverage import selection_scope_policy, SELECTION_AUDIT_VERSION
    material = {
        "audit_version": SELECTION_AUDIT_VERSION,
        "representative_policy": REPRESENTATIVE_POLICY,
        "eligibility_policy": selection_scope_policy(title),
        "version": VERSION,
        "title": title,
        "settings": settings,
        "roster": payload.get("unit_roster"),
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def is_runtime_selection(payload: dict) -> bool:
    selection = payload.get("roster_selection") if isinstance(payload, dict) else None
    return isinstance(selection, dict) and selection.get("version") == VERSION and isinstance(selection.get("settings"), dict)


def _display_name(item: Any) -> str:
    if isinstance(item, dict):
        nested = item.get("unit") or item.get("machine")
        if nested and not (item.get("name") or item.get("title") or item.get("designation") or item.get("code")):
            return _display_name(nested)
        name = str(item.get("name") or item.get("title") or "").strip()
        designation = str(item.get("designation") or item.get("code") or "").strip()
        if name and designation and designation.lower() not in name.lower():
            return f"{designation} {name}".strip()
        return name or designation
    return str(item or "").strip()


def selection_validation(title: str, payload: dict) -> dict:
    """Structural-only gate: count, identity, built contradiction and recommendation.

    Completeness, omission matrices, and discovery quotas deliberately do not belong
    to a runtime selection contract.
    """
    selection = payload.get("roster_selection") if isinstance(payload, dict) else {}
    settings = selection.get("settings") if isinstance(selection, dict) else {}
    try:
        target = selection_target(settings.get("duration_minutes"), settings.get("minutes_per_machine"))
    except ValueError as exc:
        return {"passed": False, "warnings": [str(exc)], "roster_count": 0}
    roster = payload.get("unit_roster") if isinstance(payload.get("unit_roster"), list) else []
    names = []
    duplicates = []
    seen = set()
    for item in roster:
        name = _display_name(item)
        key = re.sub(r"\s+", " ", name).casefold()
        if not name:
            duplicates.append("blank roster entry")
        elif key in seen:
            duplicates.append(name)
        seen.add(key)
        names.append(name)
    recommended = payload.get("recommended_final_roster")
    warnings = representative_warnings(title, roster)
    if len(names) != target:
        warnings.append(f"selected roster has {len(names)} entries; runtime target is exactly {target}")
    if duplicates:
        warnings.extend(duplicates)
    recommended_names = [str(item or "").strip() for item in recommended] if isinstance(recommended, list) else []
    if not isinstance(recommended, list) or len(recommended) != target:
        warnings.append("recommended_final_roster must match the selected runtime roster")
    elif not all(
        recommendation.casefold() in {name.casefold(), _bare.casefold()}
        for recommendation, name, _bare in zip(
            recommended_names, names,
            [str(item.get("name") or item.get("title") or "").strip() if isinstance(item, dict) else str(item or "").strip() for item in roster],
        )
    ):
        warnings.append("recommended_final_roster must contain the selected runtime roster in the same order")
    return {"passed": not warnings, "warnings": warnings, "hard_warnings": list(warnings),
            "complete_title": True, "roster_count": len(names), "target_count": target, "roster": names}
