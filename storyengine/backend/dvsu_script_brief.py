"""Pure, compact DVSU writer briefs derived from selected script facts."""
from __future__ import annotations

import json
import re
from typing import Any


BRIEF_VERSION = 2
MIN_SCRIPT_WORDS = 80
TARGET_SCRIPT_WORDS = 100
MAX_SCRIPT_WORDS = 110
MAX_BRIEF_BYTES = 6000
EDITORIAL_VERSION = 2
_LEGACY_EDITORIAL_VERSION = 1


def script_editorial_ready(block: Any) -> bool:
    if not isinstance(block, dict):
        return False
    audit = block.get("editorial_review")
    if not isinstance(audit, dict):
        return False
    count = len(str(block.get("paragraph") or "").split())
    version = audit.get("version")
    required = (("design_intent", "actual_use", "consequence", "gap_or_supported_substitute", "verdict", "spoken_style")
                if version == _LEGACY_EDITORIAL_VERSION else ("evidence_led", "coherent", "spoken_style"))
    return bool(isinstance(audit, dict) and block.get("factual_passed") is True
                and block.get("editorial_review_version") == version
                and version in {_LEGACY_EDITORIAL_VERSION, EDITORIAL_VERSION} and audit.get("passed") is True
                and audit.get("issues") == [] and isinstance(audit.get("checks"), dict)
                and all(audit["checks"].get(name) is True for name in required)
                and MIN_SCRIPT_WORDS <= count <= MAX_SCRIPT_WORDS)

_FIELDS = ("intended_role", "design", "actual_use", "outcome")
_INTENDED_ROLE_RE = re.compile(
    r"\b(?:designed|intended|built|developed|created)\s+(?:to|for)\b|"
    r"\b(?:purpose|role)\s+(?:was|of)\b",
    re.I,
)
_DESIGN_RE = re.compile(
    r"\b(?:engine|motor|propulsion|hull|armament|armor|armour|displacement|"
    r"speed|range|deck|torpedo|boiler|turbine|diesel|electric|gasoline|"
    r"length|beam|draft|diameter|wingspan|weapon|gun|missile|battery)\b",
    re.I,
)
_ACTUAL_USE_RE = re.compile(
    r"\b(?:served|operated|patrolled|tested|conducted|"
    r"used\s+as|deployed|saw\s+service|took\s+part)\b",
    re.I,
)
_OUTCOME_RE = re.compile(
    r"\b(?:fate|retire(?:d|ment)?|decommission(?:ed|ing)?|scrap(?:ped)?|"
    r"sunk|lost|legacy|result(?:ed)?|successor|first[- ]of[- ]a[- ]kind|"
    r"preserved|museum|cancelled|withdrawn)\b",
    re.I,
)
_CLASSIFICATION_ONLY_RE = re.compile(
    r"\b(?:classified\s+as|classification\s+(?:was|is)|(?:is|was)\s+an?\s+\w+(?:[- ]\w+)*\s+class)\b",
    re.I,
)
_ROLE_PURPOSE_RE = re.compile(
    r"\b(?:designed|intended|built|developed|created)\s+(?:to|for)\b|"
    r"\b(?:job|purpose|mission|role)\s+(?:was|is|of|to|for)\b|"
    r"\btasked\s+(?:with|to|for)\b",
    re.I,
)
_BUILDER_ONLY_RE = re.compile(
    r"\b(?:built\s+(?:at|by)|builder|shipyard|shipbuilding|subcontract(?:or|ed)?|constructed\s+(?:at|by))\b",
    re.I,
)
_WEIGHT_ONLY_RE = re.compile(r"\b(?:displacement|weight|weighed|tons?)\b", re.I)
_ENGINEERING_CONFIGURATION_RE = re.compile(
    r"\b(?:engine|motor|propulsion|hull|armament|armor|armour|ballast|deck|torpedo|boiler|"
    r"turbine|diesel|electric|gasoline|weapon|gun|missile|battery|wingspan|diameter)\b",
    re.I,
)
_RENAME_ONLY_RE = re.compile(r"\b(?:renamed|re[- ]?designated|redesignated|redesignation|renumbered)\b", re.I)
_USE_CONTEXT_RE = re.compile(
    r"\b(?:served|operated|patrolled|tested|testing|conducted|used\s+as|deployed|saw\s+service|"
    r"took\s+part|training|trained|exercise(?:d)?|conversion|converted)\b",
    re.I,
)


def _compact_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _role_is_usable(role: str, text: str) -> bool:
    """Reject only role labels attached to an otherwise non-narrative fact."""
    if role == "intended_role":
        return not (_CLASSIFICATION_ONLY_RE.search(text) and not _ROLE_PURPOSE_RE.search(text))
    if role == "design":
        configuration = bool(_ENGINEERING_CONFIGURATION_RE.search(text))
        return not ((_BUILDER_ONLY_RE.search(text) or _WEIGHT_ONLY_RE.search(text)) and not configuration)
    if role == "actual_use":
        return not (_RENAME_ONLY_RE.search(text) and not _USE_CONTEXT_RE.search(text))
    return True


def _roles(fact: dict[str, Any]) -> list[str]:
    claim = str(fact.get("claim") or "")
    text = f"{claim} {fact.get('scope') or ''}"
    explicit = fact.get("narrative_roles")
    if isinstance(explicit, list):
        validated = sorted({role for role in explicit if isinstance(role, str) and role in _FIELDS})
        return [role for role in validated if _role_is_usable(role, claim)]
    inferred = []
    if _INTENDED_ROLE_RE.search(text):
        inferred.append("intended_role")
    if _DESIGN_RE.search(text):
        inferred.append("design")
    if _ACTUAL_USE_RE.search(text):
        inferred.append("actual_use")
    if _OUTCOME_RE.search(text):
        inferred.append("outcome")
    return [role for role in inferred if _role_is_usable(role, claim)]


def build_dvsu_brief(packet: Any) -> dict:
    """Project a selected packet to the sole factual payload a DVSU writer needs."""
    if not isinstance(packet, dict):
        raise ValueError("DVSU brief requires a script packet object.")
    machine = packet.get("machine")
    if not isinstance(machine, str) or not machine.strip():
        raise ValueError("DVSU brief requires a machine.")
    subject_context = packet.get("subject_context", "")
    if not isinstance(subject_context, str):
        raise ValueError("DVSU brief subject context must be text.")
    raw_facts = packet.get("facts")
    if not isinstance(raw_facts, list):
        raise ValueError("DVSU brief facts must be a list.")

    facts: list[dict[str, str]] = []
    assignments = {field: [] for field in _FIELDS}
    seen_ids: set[str] = set()
    for raw in raw_facts:
        if not isinstance(raw, dict):
            raise ValueError("DVSU brief fact must be an object.")
        fact_id, claim, scope = raw.get("fact_id"), raw.get("claim"), raw.get("scope")
        if not all(isinstance(value, str) and value.strip() for value in (fact_id, claim, scope)):
            raise ValueError("DVSU brief fact requires fact_id, claim, and scope text.")
        if fact_id in seen_ids:
            raise ValueError("DVSU brief fact IDs must be unique.")
        seen_ids.add(fact_id)
        facts.append({"fact_id": fact_id, "claim": claim, "scope": scope})
        for field in _roles(raw):
            assignments[field].append(fact_id)

    facts.sort(key=lambda fact: fact["fact_id"])
    fields = {field: sorted(assignments[field]) for field in _FIELDS}
    # Narrative categories help a writer find useful coverage, but absence of
    # one is not an evidence failure. A nonempty selected packet is sufficient.
    missing_narrative_roles = [field for field in _FIELDS if not fields[field]]
    missing_fields = [] if facts else ["supported_facts"]
    brief = {
        "version": BRIEF_VERSION,
        "machine": machine,
        "subject_context": subject_context,
        "fields": fields,
        "facts": facts,
        "ready": bool(facts) and not missing_fields,
        "missing_fields": missing_fields,
        "missing_narrative_roles": missing_narrative_roles,
    }
    if len(_compact_json(brief)) > MAX_BRIEF_BYTES:
        brief["ready"] = False
        brief["missing_fields"] = sorted(set(missing_fields + ["compact_brief_budget"]))
    return brief


def brief_warnings(brief: Any) -> list[str]:
    """Return targeted research requests for an incomplete compact writer brief."""
    if not isinstance(brief, dict):
        return ["DVSU brief is invalid; request targeted research before script writing."]
    missing = brief.get("missing_fields")
    if not isinstance(missing, list):
        return ["DVSU brief is invalid; request targeted research before script writing."]
    warnings = []
    for field in _FIELDS:
        if field in missing:
            warnings.append(f"Missing {field} evidence; request targeted research for {field}.")
    if "compact_brief_budget" in missing:
        warnings.append("Compact DVSU brief exceeds its byte budget; request targeted research with fewer, tighter supported facts.")
    for field in missing:
        if field not in _FIELDS and field != "compact_brief_budget":
            warnings.append(f"DVSU brief requires {field}; review the saved research before script writing.")
    if brief.get("ready") is not True and not warnings:
        warnings.append("DVSU brief is not ready; review the saved research before script writing.")
    return warnings
