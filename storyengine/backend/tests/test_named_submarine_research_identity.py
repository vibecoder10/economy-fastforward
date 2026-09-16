import factual_machine_research as factual
import pipeline_executor as pipeline


SUBMARINES = [
    "SS-1 USS Holland", "SS-2 USS Plunger", "SS-105 USS S-1",
    "SS-163 USS Barracuda", "SS-212 USS Gato", "SS-285 USS Balao",
    "SS-417 USS Tench", "SS-563 USS Tang", "AGSS-569 USS Albacore",
    "SS-580 USS Barbel", "SSN-571 USS Nautilus", "SSN-585 USS Skipjack",
    "SSN-593 USS Thresher", "SSN-637 USS Sturgeon",
    "SSN-688 USS Los Angeles", "SSN-21 USS Seawolf", "SSN-774 USS Virginia",
    "SSBN-598 USS George Washington", "SSBN-608 USS Ethan Allen",
    "SSBN-616 USS Lafayette",
]


def _candidate(text):
    return {
        "excerpt_id": "e1", "locator": "p1", "text": text,
        "source_url": "https://history.example/source", "source_capture_method": "fetched_page",
    }


def test_all_accepted_named_submarines_require_name_and_exact_hull():
    for target in SUBMARINES:
        parsed = factual.named_submarine_target(target)
        assert parsed is not None, target
        text = f"USS {parsed['name']} ({parsed['prefix']} {parsed['number']}) was commissioned by the Navy."
        assert factual.candidate_mentions_machine(text, target), target


def test_named_submarine_rejects_wrong_hull_even_with_exact_name():
    assert not factual.candidate_mentions_machine("USS Tang (SS-306) was underway.", "SS-563 USS Tang")
    assert not factual.candidate_mentions_machine("USS Seawolf (SSN-575) was underway.", "SSN-21 USS Seawolf")
    assert not factual.candidate_mentions_machine("USS S-1 (SS-2) was underway.", "SS-105 USS S-1")
    assert factual.candidate_mentions_machine("USS Albacore (SS-569) was a research submarine.", "AGSS-569 USS Albacore")


def test_named_submarine_card_captures_unassessed_claim_assessment():
    package = {"candidate_excerpts": [_candidate("USS Nautilus (SSN-571) was commissioned in 1954.")],
               "claim_assessment": {"status": "needs_review", "conflicts": ["date disagreement"]}}
    card = factual.build_factual_evidence_card("SSN-571 USS Nautilus", package)
    assert card["confidence"] == "unassessed"
    assert card["provenance_status"] == "captured"
    assert card["claim_assessment"] == package["claim_assessment"]
    assert card["evidence_segments"][0]["confidence"] == "unassessed"
    assert card["evidence_segments"][0]["provenance_status"] == "captured"


def test_named_submarine_joins_refuse_stale_class_cards_and_packages():
    target = "SS-212 USS Gato"
    stale = "SS-212 USS Gato class"
    payload = {"unit_research_cards": [{"unit": stale, "marker": "stale"}]}
    assert pipeline._research_card_for_machine(payload, target) is None
    payload["unit_research_cards"].append({"unit": target, "marker": "current"})
    assert pipeline._research_card_for_machine(payload, target)["marker"] == "current"

    stale_package = {"machine": stale, "candidate_excerpts": []}
    assert pipeline._verified_source_package_for_machine(
        {"machine_raw_source_packages": {"SS-212 USS Gato": stale_package}}, target
    ) is None
    current_package = {"machine": target, "candidate_excerpts": []}
    assert pipeline._verified_source_package_for_machine(
        {"machine_raw_source_packages": {"SS212": current_package}}, target
    ) is current_package


def test_named_submarine_roster_slot_refuses_stale_class_but_tolerates_punctuation():
    roster = ["SS-212 USS Gato"]
    assert pipeline._roster_index_for_identity(roster, "SS-212 USS Gato class") is None
    assert pipeline._roster_index_for_identity(roster, "SS 212 USS Gato") == 1
    assert pipeline._locked_roster_item_for_machine(roster, "SS-212 USS Gato class") is None


def test_generic_aircraft_and_class_identity_behavior_remains_available():
    assert factual.candidate_mentions_machine("The B-52 Stratofortress entered service.", "B-52 Stratofortress")
    assert factual.candidate_mentions_machine("The Gato-class submarine served in the Pacific.", "SS-212 through SS-284 Gato class")
    assert pipeline._roster_index_for_identity(["B-52 Stratofortress"], "B-52") == 1
