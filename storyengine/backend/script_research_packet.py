"""Deterministic, bounded evidence packets for factual script generation."""
from __future__ import annotations

import hashlib
import json
from typing import Any

COMPILER_VERSION = 2
MAX_PACKET_BYTES = 32000
MAX_INPUT_TOKEN_UPPER_BOUND = 48000
MODEL_CONTEXT_TOKENS = 200000
PROMPT_RULES_VERSION = 4


class ScriptPacketError(ValueError):
    """A safe, actionable failure assembling or consuming a script packet."""


def _fail(message: str) -> None:
    raise ScriptPacketError(message)


def _canonical(value: Any) -> str:
    return json.dumps(_normalize(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


_UNORDERED_LIST_KEYS = {"sources", "candidate_excerpts", "claims", "evidence", "counterevidence"}


def _normalize(value: Any, key: str = "") -> Any:
    """Normalize evidence collections for hashing while retaining outline order."""
    if isinstance(value, dict):
        return {str(k): _normalize(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        rows = [_normalize(v) for v in value]
        if key in _UNORDERED_LIST_KEYS:
            return sorted(rows, key=lambda row: json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str))
        return rows
    return value


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text(value: Any, field: str, maximum: int, *, required: bool = True) -> str:
    if not isinstance(value, str):
        if required:
            _fail(f"Script packet {field} must be text.")
        return ""
    if len(value) > maximum:
        _fail(f"Script packet {field} exceeds its size limit.")
    if required and not value.strip():
        _fail(f"Script packet {field} is required.")
    return value


def _category(claim: dict) -> str:
    explicit = claim.get("category")
    allowed = {"identity", "purpose", "design", "service", "outcome", "other"}
    if isinstance(explicit, str) and explicit.strip().lower() in allowed:
        return explicit.strip().lower()
    value = (str(claim.get("claim") or "") + " " + str(claim.get("scope") or "")).lower()
    # Specific meanings win before the broad identity words that may co-occur.
    rules = (
        ("outcome", ("decommission", "scrap", "sunk", " lost", "retire", "museum")),
        ("purpose", ("designed", "intended", " role", "purpose")),
        ("design", ("engine", "hull", "armament", "power", "displacement", "speed", "range", "deck", "propulsion", "torpedo")),
        ("service", ("commission", "served", "operation", "patrol", "battle", " war", "deploy")),
        ("identity", ("type", "class", "named", "designated")),
    )
    for name, words in rules:
        if any(word in value for word in words):
            return name
    return "other"


_CATEGORY_ORDER = ("identity", "purpose", "design", "service", "outcome", "other")
_NARRATIVE_ROLES = ("intended_role", "design", "actual_use", "outcome")


def _narrative_roles(claim: dict) -> list[str]:
    """Return only the assessor's validated, writer-safe narrative roles."""
    raw = claim.get("narrative_roles")
    if not isinstance(raw, list):
        return []
    return sorted({role.strip() for role in raw
                   if isinstance(role, str) and role.strip() in _NARRATIVE_ROLES})


def _source_tier(candidate: dict) -> int:
    value = candidate.get("source_tier", 99)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 99


def _validate_outline(outline: Any) -> list[dict]:
    if outline is None:
        return []
    if not isinstance(outline, list) or len(outline) > 128:
        _fail("Script packet outline is invalid or too large.")
    rows = []
    for row in outline:
        if not isinstance(row, dict) or not isinstance(row.get("scene"), int):
            _fail("Script packet outline rows require integer scene and machine.")
        machine = _text(row.get("machine"), "outline machine", 240)
        rows.append({"scene": row["scene"], "machine": machine})
    return rows


def _briefing_paragraph(current_briefing: Any) -> str:
    if current_briefing is None:
        return ""
    if isinstance(current_briefing, str):
        return _text(current_briefing, "briefing paragraph", 2000, required=False)
    if isinstance(current_briefing, dict):
        return _text(current_briefing.get("paragraph", ""), "briefing paragraph", 2000, required=False)
    _fail("Script packet current briefing is invalid.")


def _assessment_valid(machine: str, package: dict, assessment: Any, subject_context: str) -> dict:
    if not isinstance(assessment, dict):
        _fail("Script packet requires a current assessed claim receipt.")
    # The caller has already run current_assessment. Do not revalidate it here:
    # compiler replay intentionally permits an equivalent package with reordered
    # source lists. Validate the receipt's identity and safe structural envelope.
    if (assessment.get("status") != "assessed" or assessment.get("machine") != machine
            or assessment.get("subject_context") != subject_context
            or not isinstance(assessment.get("source_fingerprint"), str)
            or not assessment.get("source_fingerprint")
            or not isinstance(assessment.get("claims"), list)):
        _fail("Script packet claim assessment is stale or invalid.")
    return assessment


def _fact_id(machine: str, claim: dict, evidence: list[dict]) -> str:
    basis = {"machine": machine, "claim": claim["claim"], "scope": claim["scope"],
             "evidence": sorted((item["excerpt_id"], item["quote"]) for item in evidence)}
    return "F" + _digest(basis)[:20]


def _evidence_rows(claim: dict, candidates: dict[str, dict]) -> list[dict]:
    raw_rows = claim.get("evidence")
    if not isinstance(raw_rows, list) or not raw_rows:
        _fail("Script packet supported claim lacks valid evidence.")
    rows: dict[tuple[str, str], dict] = {}
    for raw in raw_rows:
        if not isinstance(raw, dict):
            _fail("Script packet evidence is invalid.")
        excerpt_id = _text(raw.get("excerpt_id"), "evidence excerpt ID", 240)
        quote = _text(raw.get("quote"), "evidence quote", 12000)
        candidate = candidates.get(excerpt_id)
        if not isinstance(candidate, dict) or quote not in str(candidate.get("text") or ""):
            _fail("Script packet evidence quote does not match an eligible excerpt.")
        candidate_url = str(candidate.get("source_url") or "")
        supplied_url = raw.get("source_url")
        if supplied_url is not None and str(supplied_url) != candidate_url:
            _fail("Script packet evidence source URL does not match its eligible excerpt.")
        row = {
            "excerpt_id": excerpt_id, "quote": quote,
            "source_url": candidate_url,
            "source_id": str(candidate.get("source_id") or ""),
            "source_title": str(candidate.get("source_title") or ""),
            "locator": str(candidate.get("locator") or excerpt_id),
            "source_capture_method": str(candidate.get("source_capture_method") or ""),
            "source_tier": candidate.get("source_tier"),
        }
        rows[(excerpt_id, quote)] = row
    return [rows[key] for key in sorted(rows)]


def _excluded(receipt: dict) -> list[dict]:
    rows = []
    for index, claim in enumerate(receipt.get("claims") or [], 1):
        status = str(claim.get("status") or "")
        if status != "supported":
            rows.append({"assessment_claim_id": str(claim.get("id") or f"C{index}"),
                         "status": status, "reason_code": "assessment_" + (status or "invalid")})
    return sorted(rows, key=lambda item: (item["assessment_claim_id"], item["status"], item["reason_code"]))


def compile_script_packet(machine: Any, source_package: Any, assessment: Any, candidates: Any, *,
                          subject_context: Any = "", episode_outline: Any = None,
                          current_briefing: Any = None, model: Any = "") -> dict:
    """Compile supported claims and immutable excerpts into a bounded prompt payload."""
    machine = _text(machine, "machine", 240)
    subject_context = _text(subject_context, "subject context", 1000, required=False)
    model = _text(model, "model", 240, required=False)
    if not isinstance(source_package, dict) or not isinstance(candidates, dict):
        _fail("Script packet source package or eligible candidates is invalid.")
    receipt = _assessment_valid(machine, source_package, assessment, subject_context)
    outline, briefing = _validate_outline(episode_outline), _briefing_paragraph(current_briefing)
    package_digest = _digest(source_package)
    excluded = _excluded(receipt)
    supported = []
    for index, claim in enumerate(receipt.get("claims") or [], 1):
        if claim.get("status") != "supported":
            continue
        if not isinstance(claim.get("claim"), str) or not isinstance(claim.get("scope"), str):
            _fail("Script packet supported claim is invalid.")
        evidence = _evidence_rows(claim, candidates)
        supported.append({"fact_id": _fact_id(machine, claim, evidence),
                          "assessment_claim_id": str(claim.get("id") or f"C{index}"),
                          "category": _category(claim), "claim": claim["claim"], "scope": claim["scope"],
                          "evidence": evidence,
                          **({"narrative_roles": _narrative_roles(claim)} if "narrative_roles" in claim else {}),
                          "_tier": min(_source_tier(candidates[item["excerpt_id"]]) for item in evidence)})
    if not supported:
        _fail("Script packet requires at least one supported claim.")
    supported.sort(key=lambda row: (_CATEGORY_ORDER.index(row["category"]), row["_tier"], row["fact_id"], row["assessment_claim_id"]))
    # Identical claim/scope/evidence has one stable local fact. Keep the
    # lexical-lowest assessment ID so assessment-list reordering cannot change
    # the prompt or cache key, while retaining a compact audit receipt.
    unique: dict[str, dict] = {}
    duplicate_rows = []
    for row in supported:
        existing = unique.get(row["fact_id"])
        if existing is None or row["assessment_claim_id"] < existing["assessment_claim_id"]:
            if existing is not None:
                duplicate_rows.append({"assessment_claim_id": existing["assessment_claim_id"], "status": "supported", "reason_code": "duplicate_fact"})
            unique[row["fact_id"]] = row
        else:
            duplicate_rows.append({"assessment_claim_id": row["assessment_claim_id"], "status": "supported", "reason_code": "duplicate_fact"})
    supported = sorted(unique.values(), key=lambda row: (_CATEGORY_ORDER.index(row["category"]), row["_tier"], row["fact_id"], row["assessment_claim_id"]))
    excluded.extend(duplicate_rows)
    chosen, seen_categories = [], set()
    for row in supported:
        if row["category"] not in seen_categories:
            chosen.append(row); seen_categories.add(row["category"])
    for row in supported:
        if len(chosen) >= 12:
            break
        if row not in chosen:
            chosen.append(row)
    # Keep category representatives ahead of fillers for admission. The final
    # packet is sorted after selection for deterministic presentation.
    base = {"compiler_version": COMPILER_VERSION, "prompt_rules_version": PROMPT_RULES_VERSION,
            "model": model, "subject_context": subject_context, "machine": machine, "outline": outline,
            "current_briefing": briefing, "facts": [], "excluded_claims": excluded,
            "source_fingerprint": receipt["source_fingerprint"], "package_sha256": package_digest,
            # Reserve the final fixed-width fingerprint before admitting facts.
            "packet_fingerprint": "0" * 64}
    if len(_canonical(base).encode("utf-8")) > MAX_PACKET_BYTES:
        _fail("Script packet metadata exceeds the packet limit.")
    # Try every supported fact in priority order. An oversized fact never
    # consumes a selection slot, so a later compact fact can backfill it.
    prioritized = chosen + [row for row in supported if row not in chosen]
    for row_index, row in enumerate(prioritized):
        fact = {key: row[key] for key in ("fact_id", "assessment_claim_id", "category", "claim", "scope", "evidence", "narrative_roles") if key in row}
        future_limit = []
        if len(base["facts"]) + 1 == 12:
            future_limit = [{"assessment_claim_id": later["assessment_claim_id"], "status": "supported", "reason_code": "selection_limit"}
                            for later in prioritized[row_index + 1:]]
        trial_excluded = sorted(excluded + future_limit, key=lambda item: (item["assessment_claim_id"], item["status"], item["reason_code"]))
        trial = {**base, "facts": base["facts"] + [fact], "excluded_claims": trial_excluded}
        if len(_canonical(trial).encode("utf-8")) <= MAX_PACKET_BYTES:
            base["facts"].append(fact)
            if future_limit:
                excluded.extend(future_limit)
                base["excluded_claims"] = trial_excluded
                break
        else:
            excluded.append({"assessment_claim_id": row["assessment_claim_id"], "status": "supported", "reason_code": "fact_exceeds_packet_limit"})
            base["excluded_claims"] = sorted(excluded, key=lambda item: (item["assessment_claim_id"], item["status"], item["reason_code"]))
            if len(_canonical(base).encode("utf-8")) > MAX_PACKET_BYTES:
                _fail("Script packet metadata exceeds the packet limit.")
    if not base["facts"]:
        _fail("Script packet has no supported fact that fits the packet limit.")
    base["facts"].sort(key=lambda row: (_CATEGORY_ORDER.index(row["category"]),
                                         min(_source_tier(candidates[item["excerpt_id"]]) for item in row["evidence"]),
                                         row["fact_id"]))
    base["excluded_claims"] = sorted(excluded, key=lambda item: (item["assessment_claim_id"], item["status"], item["reason_code"]))
    fingerprint_input = {"packet": base, "assessment": receipt, "eligible_candidates": candidates,
                         "package_sha256": package_digest, "limits": {"max_packet_bytes": MAX_PACKET_BYTES,
                         "max_input_token_upper_bound": MAX_INPUT_TOKEN_UPPER_BOUND,
                         "model_context_tokens": MODEL_CONTEXT_TOKENS}}
    base["packet_fingerprint"] = _digest(fingerprint_input)
    if len(_canonical(base).encode("utf-8")) > MAX_PACKET_BYTES:
        _fail("Script packet metadata exceeds the packet limit.")
    return base


def materialize_script_draft(raw: Any, packet: Any) -> dict:
    if not isinstance(raw, dict) or not isinstance(packet, dict):
        _fail("Script draft or packet is invalid.")
    rows = raw.get("claim_map")
    if not isinstance(rows, list) or not rows:
        _fail("Script draft requires a nonempty claim map.")
    facts = {row.get("fact_id"): row for row in packet.get("facts") or [] if isinstance(row, dict)}
    output = []
    for raw_row in rows:
        if not isinstance(raw_row, dict) or not isinstance(raw_row.get("sentence"), str) or not raw_row["sentence"].strip():
            _fail("Script draft claim map row is invalid.")
        ids = raw_row.get("fact_ids")
        if (not isinstance(ids, list) or not ids or any(not isinstance(value, str) for value in ids)
                or len(set(ids)) != len(ids) or any(value not in facts for value in ids)):
            _fail("Script draft references an unknown or missing fact ID.")
        citations = {}
        for fact_id in sorted(ids):
            for evidence in facts[fact_id].get("evidence") or []:
                citations[(evidence["excerpt_id"], evidence["quote"])] = dict(evidence)
        output.append({"sentence": raw_row["sentence"], "fact_ids": list(ids),
                       "citations": [citations[key] for key in sorted(citations)]})
    return {"paragraph": raw.get("paragraph", ""), "claim_map": output}


def assert_request_budget(prompt: Any, system_prompt: Any, max_tokens: Any) -> dict:
    if not isinstance(prompt, str) or not isinstance(system_prompt, str) or not isinstance(max_tokens, int) or max_tokens < 0:
        _fail("Script request budget inputs are invalid.")
    upper = len((prompt + system_prompt).encode("utf-8")) + 1024
    if upper > MAX_INPUT_TOKEN_UPPER_BOUND or upper + max_tokens > MODEL_CONTEXT_TOKENS:
        _fail("Script request exceeds the conservative model input budget.")
    return {"method": "utf8_byte_upper_bound", "input_token_upper_bound": upper,
            "output_tokens_reserved": max_tokens, "context_limit": MODEL_CONTEXT_TOKENS}
