"""Bounded follow-up assessment for verified submarine class-design context."""
from __future__ import annotations

import os
from typing import Any

from factual_class_context import is_verified_class_context
from factual_machine_research import candidate_mentions_machine
from script_research_packet import assert_request_budget


CLASS_CONTEXT_REVIEW_VERSION = 1
_FOCUSED_SYSTEM = "You assess only supplied source evidence. Output only the requested JSON."


def _supported_roles(receipt: dict) -> set[str]:
    from dvsu_script_brief import _role_is_usable

    roles: set[str] = set()
    for claim in receipt.get("claims") or []:
        if not isinstance(claim, dict) or claim.get("status") != "supported":
            continue
        text = str(claim.get("claim") or "")
        for role in claim.get("narrative_roles") or []:
            if role in {"intended_role", "design"} and _role_is_usable(role, text):
                roles.add(role)
    return roles


def _selection(machine: str, receipt: dict, candidates: dict[str, dict]) -> tuple[list[str], str | None, list[str]]:
    missing = sorted({"intended_role", "design"} - _supported_roles(receipt))
    if not missing:
        return [], None, missing
    pending = sorted(
        excerpt_id for excerpt_id, row in candidates.items()
        if is_verified_class_context(row.get("text"), machine)
    )[:2]
    anchors = sorted(
        (
            (len(str(row.get("text") or "")), excerpt_id)
            for excerpt_id, row in candidates.items()
            if not row.get("identity_requires_review")
            and candidate_mentions_machine(str(row.get("text") or ""), machine)
        ),
    )
    return pending, (anchors[0][1] if anchors else None), missing


def _review(receipt: dict, *, fingerprint: str, candidate_ids: list[str], missing: list[str],
            status: str, warnings: list[str]) -> dict:
    return {
        **receipt,
        "class_context_review": {
            "version": CLASS_CONTEXT_REVIEW_VERSION,
            "source_fingerprint": fingerprint,
            "candidate_ids": candidate_ids,
            "missing_fields": missing,
            "status": status,
            "warnings": warnings,
        },
    }


def _focused_prompt(machine: str, candidates: dict[str, dict], subject_context: str, missing: list[str]) -> str:
    from research_claim_assessment import _prompt

    return (
        "FOCUSED CLASS-CONTEXT FOLLOW-UP. Assess only the supplied class-design context and exact-hull anchor. "
        f"The only missing DVSU fields are: {', '.join(missing)}. Return at most three claims. "
        f"Every supported claim must have a nonempty narrative_roles list that is a subset of exactly: {', '.join(missing)}. "
        "A class purpose or design may be supported only as scope 'class', with a class-context quote and the exact-hull "
        "anchor in the same claim plus identity_reviews. Keep the class qualifier. Classification or membership alone is no purpose. "
        "If this evidence cannot support a field, return insufficient or out_of_scope with its exact quote and reason.\n\n"
        + _prompt(machine, candidates, subject_context)
    )


def _promotable_claims(claims: list[dict], pending_ids: set[str], missing: set[str], limit: int) -> list[dict]:
    from dvsu_script_brief import _role_is_usable

    if limit <= 0:
        return []
    output = []
    for claim in claims:
        roles = set(claim.get("narrative_roles") or [])
        evidence_ids = {row.get("excerpt_id") for row in claim.get("evidence") or []}
        reviews = {row.get("excerpt_id") for row in claim.get("identity_reviews") or []}
        if (claim.get("status") == "supported" and claim.get("scope") == "class" and roles
                and all(_role_is_usable(role, str(claim.get("claim") or "")) for role in roles)
                and roles <= missing and evidence_ids & pending_ids and evidence_ids & reviews):
            output.append(claim)
        if len(output) == limit:
            break
    return output


async def assess_class_context_gap(machine: str, package: Any, current: dict, client: Any,
                                   subject_context: str, candidates: dict[str, dict]) -> dict:
    """Fill only missing class-level role fields, once per unchanged evidence receipt."""
    pending, anchor_id, missing = _selection(machine, current, candidates)
    if not pending or not anchor_id:
        return current
    fingerprint = str(current.get("source_fingerprint") or "")
    if not fingerprint:
        return current
    review = current.get("class_context_review")
    if (isinstance(review, dict) and review.get("version") == CLASS_CONTEXT_REVIEW_VERSION
            and review.get("source_fingerprint") == fingerprint):
        return current
    if client is None:
        return current
    selected_ids = [*pending, anchor_id]
    selected = {excerpt_id: candidates[excerpt_id] for excerpt_id in selected_ids}
    prompt = _focused_prompt(machine, selected, subject_context, missing)
    assert_request_budget(prompt, _FOCUSED_SYSTEM, 1800)
    raw = await client.generate(
        prompt=prompt, system_prompt=_FOCUSED_SYSTEM,
        model=os.getenv("CLAUDE_OPUS_MODEL", "claude-opus-4-5-20251101"), max_tokens=1800, temperature=0.0,
    )
    from factual_machine_summary import _parse_json_object
    from research_claim_assessment import _assessed_receipt, _eligible, _valid_receipt, _validated_claims

    claims = _validated_claims(((_parse_json_object(raw) or {}).get("claims")), selected, max_claims=3)
    promoted = _promotable_claims(claims or [], set(pending), set(missing), max(0, 15 - len(current.get("claims") or [])))
    if not promoted:
        warning = "Focused class-context assessment returned no promotable supported class claim."
        if claims is None:
            warning = "Focused class-context assessment returned invalid claim evidence."
        return _review(current, fingerprint=fingerprint, candidate_ids=pending, missing=missing,
                       status="completed_failure", warnings=[warning])
    combined = _validated_claims([*(current.get("claims") or []), *promoted],
                                 _eligible(machine, package, subject_context), max_claims=15)
    if not combined:
        return _review(current, fingerprint=fingerprint, candidate_ids=pending, missing=missing,
                       status="completed_failure", warnings=["Focused class-context claims failed combined receipt validation."])
    rebuilt = _assessed_receipt(machine, package, subject_context, combined)
    merged = {**current, **rebuilt}
    merged = _review(merged, fingerprint=fingerprint, candidate_ids=pending, missing=missing,
                     status="completed", warnings=[])
    valid = _valid_receipt(machine, package, merged, subject_context)
    if valid:
        return valid
    return _review(current, fingerprint=fingerprint, candidate_ids=pending, missing=missing,
                   status="completed_failure", warnings=["Focused class-context receipt failed structural validation."])
