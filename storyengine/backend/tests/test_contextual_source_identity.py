import contextual_source_identity as identity


MACHINE = "SS-1 USS Holland"


def _candidate(excerpt_id, text, *, locked_machine=MACHINE, supplied_flag=None):
    row = {"excerpt_id": excerpt_id, "text": text, "_locked_machine": locked_machine}
    if supplied_flag is not None:
        row["identity_requires_review"] = supplied_flag
    return row


def test_contextual_named_excerpt_accepts_dotted_uss_complete_name_only():
    assert identity.contextual_named_excerpt("U.S.S. Holland began harbor trials.", MACHINE)
    assert identity.contextual_named_excerpt("U. S. S. Holland began harbor trials.", MACHINE)
    assert not identity.contextual_named_excerpt("Holland began harbor trials.", MACHINE)
    assert not identity.contextual_named_excerpt("John Holland designed submarines.", MACHINE)


def test_contextual_named_excerpt_rejects_wrong_or_competing_hulls_and_foreign_names():
    assert not identity.contextual_named_excerpt("USS Holland (SS-2) began harbor trials.", MACHINE)
    assert not identity.contextual_named_excerpt("USS Holland (SS 1) began harbor trials.", MACHINE)
    assert not identity.contextual_named_excerpt("USS Holland and USS Plunger began harbor trials.", MACHINE)
    assert not identity.contextual_named_excerpt("USS Holland and HMS Holland began harbor trials.", MACHINE)


def test_identity_review_binds_context_to_computed_flag_and_strict_same_claim_anchor():
    candidates = [
        _candidate("C", "U.S.S. Holland began harbor trials.", supplied_flag=False),
        _candidate("A", "USS Holland (SS-1) was purchased by the Navy.", supplied_flag=True),
    ]
    evidence = [
        {"excerpt_id": "C", "quote": "U.S.S. Holland began harbor trials."},
        {"excerpt_id": "A", "quote": "USS Holland (SS-1) was purchased by the Navy."},
    ]
    reviews = [{"excerpt_id": "C", "status": "same_machine", "anchor_excerpt_id": "A", "reason": "The exact hull anchor identifies the same vessel."}]
    assert identity.validate_identity_reviews(reviews, evidence, candidates) == reviews


def test_identity_review_rejects_missing_stale_or_non_strict_anchor():
    candidates = [
        _candidate("C", "USS Holland began harbor trials."),
        _candidate("A", "USS Holland (SS-1) was purchased by the Navy."),
        _candidate("O", "USS Plunger (SS-2) was commissioned."),
    ]
    evidence = [
        {"excerpt_id": "C", "quote": "USS Holland began harbor trials."},
        {"excerpt_id": "A", "quote": "USS Holland (SS-1) was purchased by the Navy."},
    ]
    assert identity.validate_identity_reviews([], evidence, candidates) is None
    assert identity.validate_identity_reviews(
        [{"excerpt_id": "C", "status": "same_machine", "anchor_excerpt_id": "O", "reason": "stale"}], evidence, candidates
    ) is None
    assert identity.validate_identity_reviews(
        [{"excerpt_id": "C", "status": "same_machine", "anchor_excerpt_id": "C", "reason": "self"}], evidence, candidates
    ) is None


def test_identity_reviews_reject_extra_when_no_contextual_evidence():
    candidates = [_candidate("A", "USS Holland (SS-1) was purchased by the Navy.")]
    evidence = [{"excerpt_id": "A", "quote": "USS Holland (SS-1) was purchased by the Navy."}]
    assert identity.validate_identity_reviews([], evidence, candidates) == []
    assert identity.validate_identity_reviews(
        [{"excerpt_id": "A", "status": "same_machine", "anchor_excerpt_id": "A", "reason": "extra"}], evidence, candidates
    ) is None
