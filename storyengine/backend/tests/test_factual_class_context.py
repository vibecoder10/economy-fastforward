"""Bounded class-context evidence contracts for named submarines."""
from __future__ import annotations

from copy import deepcopy

from factual_class_context import class_context_candidate, is_verified_class_context
from factual_machine_summary import _eligible_candidates
import pipeline_executor as pe
from research_claim_assessment import _assessed_receipt, _validated_claims


MACHINE = "SS-2 USS Plunger"
URL = "https://example.org/a-class"


def _context(member: str = "Plunger/A-1 (Submarine No. 2)", extra: str = "") -> str:
    return "\n\n".join((
        "A-class submarines",
        "The class was designed for harbor defense and its construction used an early gasoline-electric arrangement.",
        member + " was a member of the class." + extra,
    ))


PUBLISHER_SECTION_FIXTURE = "\n\n".join((
    "A-class From Example Publisher",
    "Contents 1 Design Notes 2 Plunger/A-1 (Submarine No. 2) 3 Adder/A-2 (Submarine No. 3)",
    "Design Notes These harbor defense submarines were the first production class ordered by the Navy.",
    "Fulton (Prototype) The prototype tested equipment before the production class.",
    "Plunger/A-1 (Submarine No. 2) Builder and photo caption for the target member. See more A-1 photos",
    "Adder/A-2 (Submarine No. 3) NEXT_SIBLING_ONLY",
))


def _tabular_context(*, row: str = "SS2 Plunger, A1", technical: bool = True,
                     history: bool = True, extra: str = "") -> str:
    sections = [
        '"A" submarines (1903)',
        "Ships No Name Yard No Builder " + row,
    ]
    if technical:
        sections.append("Technical data Machinery gasoline engine / electric motor")
    if history:
        sections.append("Project history These submarines were intended for port defense.")
    sections.append("Naval service NEXT_SERVICE_ONLY")
    return "\n\n".join(sections) + extra


def test_class_context_is_contiguous_original_text_with_target_member_and_design_marker():
    source = _context()
    candidate = class_context_candidate(source, MACHINE)

    assert candidate == source
    assert is_verified_class_context(candidate, MACHINE)
    assert "harbor defense" in candidate
    assert "Submarine No. 2" in candidate
    assert len(candidate) <= 8000


def test_class_context_rejects_wrong_member_missing_membership_and_foreign_target_hull():
    assert class_context_candidate(_context("Grayling (Submarine No. 209)"), MACHINE) == ""
    assert class_context_candidate("\n\n".join(("A-class submarines", "The class was designed for harbor defense.", "Member list follows.")), MACHINE) == ""
    assert class_context_candidate(_context("Plunger (SS-7)"), MACHINE) == ""
    assert class_context_candidate(_context("Plunger (Submarine No. 2, formerly Submarine No. 7)"), MACHINE) == ""


def test_class_context_rejects_over_cap_without_truncating():
    source = _context(extra=" " + ("construction detail " * 500))
    assert len(source) > 8000
    assert class_context_candidate(source, MACHINE) == ""


def test_tabular_class_context_is_exact_bounded_and_excludes_following_service():
    source = _tabular_context()
    candidate = class_context_candidate(source, MACHINE)
    assert candidate == "\n\n".join(source.split("\n\n")[:-1])
    assert "Ships No Name" in candidate and "Technical data" in candidate
    assert "intended for port defense" in candidate
    assert "NEXT_SERVICE_ONLY" not in candidate
    assert is_verified_class_context(candidate, MACHINE)


def test_tabular_class_context_rejects_wrong_hull_name_or_missing_required_structure():
    assert class_context_candidate(_tabular_context(row="SS3 Plunger, A2"), MACHINE) == ""
    assert class_context_candidate(_tabular_context(row="SS2 Plunger, A1 SS3 Plunger, A2"), MACHINE) == ""
    assert class_context_candidate(_tabular_context(row="SS2 Grayling, A1"), MACHINE) == ""
    assert class_context_candidate(_tabular_context(technical=False), MACHINE) == ""
    assert class_context_candidate(_tabular_context(history=False), MACHINE) == ""
    assert class_context_candidate("Ships No Name SS2 Plunger, A1\n\nTechnical data\n\nProject history intended port defense", MACHINE) == ""
    assert class_context_candidate(_tabular_context(row="SS2 Plunger, " + ("x" * 8000)), MACHINE) == ""


def test_tabular_context_does_not_cross_another_class_or_service_boundary():
    cross_class = "\n\n".join((
        '"A" submarines (1903)', "Ships No Name SS2 Plunger, A1",
        '"B" submarines (1905)', "Technical data gasoline engine",
        "Project history intended for port defense.",
    ))
    after_service = "\n\n".join((
        '"A" submarines (1903)', "Ships No Name SS2 Plunger, A1",
        "Naval service target operations.", "Technical data gasoline engine",
        "Project history intended for port defense.",
    ))
    assert class_context_candidate(cross_class, MACHINE) == ""
    assert class_context_candidate(after_service, MACHINE) == ""


def test_tabular_context_is_pending_until_exact_anchor_review():
    context = class_context_candidate(_tabular_context(), MACHINE)
    assert context
    package = _package()
    package["candidate_excerpts"][0]["text"] = context
    pending = _eligible_candidates(MACHINE, package, include_identity_pending=True)
    assert pending["S1-E1"]["identity_requires_review"] is True
    raw = [{
        "claim": "The A class was intended for port defense.", "scope": "class", "status": "supported", "reason": "quoted project history",
        "narrative_roles": ["intended_role"],
        "evidence": [{"excerpt_id": "S1-E1", "quote": context}, {"excerpt_id": "S1-E2", "quote": "USS Plunger (SS-2) was commissioned as the named submarine."}],
        "counterevidence": [],
        "identity_reviews": [{"excerpt_id": "S1-E1", "status": "same_machine", "anchor_excerpt_id": "S1-E2", "reason": "The same claim has an exact SS-2 anchor."}],
    }]
    assert _validated_claims(raw, pending)


def _package():
    context = _context()
    return {
        "sources": [{"source_id": "S1", "url": URL}],
        "candidate_excerpts": [
            {"excerpt_id": "S1-E1", "source_id": "S1", "source_url": URL, "source_title": "A class", "locator": "S1-E1", "source_capture_method": "fetched_page", "text": context},
            {"excerpt_id": "S1-E2", "source_id": "S1", "source_url": URL, "source_title": "A class", "locator": "S1-E2", "source_capture_method": "fetched_page", "text": "USS Plunger (SS-2) was commissioned as the named submarine."},
        ],
    }


def test_class_context_is_pending_until_same_claim_exact_anchor_review():
    package = _package()
    pending = _eligible_candidates(MACHINE, package, include_identity_pending=True)
    delivered = _eligible_candidates(MACHINE, package)
    assert pending["S1-E1"]["identity_requires_review"] is True
    assert pending["S1-E1"]["context_scope"] == "class_design"
    assert "S1-E1" not in delivered and "S1-E2" in delivered

    raw = [{
        "claim": "The A class was designed for harbor defense.", "scope": "class", "status": "supported", "reason": "quoted class design context",
        "narrative_roles": ["intended_role", "design"],
        "evidence": [{"excerpt_id": "S1-E1", "quote": _context()}, {"excerpt_id": "S1-E2", "quote": "USS Plunger (SS-2) was commissioned as the named submarine."}],
        "counterevidence": [],
        "identity_reviews": [{"excerpt_id": "S1-E1", "status": "same_machine", "anchor_excerpt_id": "S1-E2", "reason": "The same claim includes the exact SS-2 anchor."}],
    }]
    claims = _validated_claims(raw, pending)
    assert claims and claims[0]["evidence"][0]["context_scope"] == "class_design"

    raw[0]["narrative_roles"] = ["actual_use"]
    assert _validated_claims(raw, pending) is None
    raw[0]["narrative_roles"] = ["outcome"]
    assert _validated_claims(raw, pending) is None
    missing_review = deepcopy(raw)
    missing_review[0]["narrative_roles"] = ["intended_role"]
    missing_review[0].pop("identity_reviews")
    assert _validated_claims(missing_review, pending) is None
    rejected = deepcopy(raw)
    rejected[0]["status"] = "insufficient"
    rejected[0]["narrative_roles"] = ["actual_use"]
    rejected[0].pop("identity_reviews")
    assert _validated_claims(rejected, pending)

    no_anchor = {**package, "candidate_excerpts": package["candidate_excerpts"][:1]}
    no_anchor_pending = _eligible_candidates(MACHINE, no_anchor, include_identity_pending=True)
    assert _validated_claims(missing_review, no_anchor_pending) is None

    package["claim_assessment"] = _assessed_receipt(MACHINE, package, "", claims)
    reviewed = _eligible_candidates(MACHINE, package)
    assert "S1-E1" in reviewed and reviewed["S1-E1"]["identity_requires_review"] is True


def test_publisher_sections_use_member_heading_not_contents_entry():
    source = PUBLISHER_SECTION_FIXTURE
    candidate = class_context_candidate(source, MACHINE)

    assert candidate
    assert candidate.startswith("A-class From Example Publisher")
    assert "Design Notes" in candidate
    assert "harbor defense submarines" in candidate
    assert candidate.endswith("See more A-1 photos")
    assert "NEXT_SIBLING_ONLY" not in candidate
    assert candidate in source
    assert is_verified_class_context(candidate, MACHINE)

    package = {
        "sources": [{"source_id": "P", "url": URL}],
        "candidate_excerpts": [
            {"excerpt_id": "P-CONTEXT", "source_id": "P", "source_url": URL, "source_title": "Pigboats", "locator": "P-CONTEXT", "source_capture_method": "fetched_page", "text": candidate},
            {"excerpt_id": "P-ANCHOR", "source_id": "P", "source_url": URL, "source_title": "Pigboats", "locator": "P-ANCHOR", "source_capture_method": "fetched_page", "text": "USS Plunger (SS-2) is an exact named-hull anchor."},
        ],
    }
    pending = _eligible_candidates(MACHINE, package, include_identity_pending=True)
    normal = _eligible_candidates(MACHINE, package)
    assert pending["P-CONTEXT"]["identity_requires_review"] is True
    assert "P-CONTEXT" not in normal and "P-ANCHOR" in normal


def test_factual_discovery_admits_only_verified_class_context_before_extraction():
    assert pe._factual_discovery_capture_match(
        PUBLISHER_SECTION_FIXTURE, MACHINE, lambda text, machine: False
    ) is True
    wrong_member = PUBLISHER_SECTION_FIXTURE.replace(
        "Plunger/A-1 (Submarine No. 2) Builder", "Grayling/A-1 (Submarine No. 209) Builder"
    )
    assert pe._factual_discovery_capture_match(wrong_member, MACHINE, lambda text, machine: False) is False
