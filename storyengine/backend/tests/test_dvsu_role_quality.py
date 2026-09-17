"""Offline narrative-role quality checks for saved DVSU research facts."""
from __future__ import annotations

import copy

from dvsu_script_brief import BRIEF_VERSION, build_dvsu_brief


def _packet(machine: str, facts: list[dict]) -> dict:
    return {"machine": machine, "subject_context": "offline role-quality regression", "facts": facts}


def test_saved_ss2_weak_labels_leave_intended_role_and_design_missing_without_losing_facts():
    packet = _packet("SS-2 USS Plunger", [
        {"fact_id": "C1", "claim": "USS Plunger (SS-2) was classified as an Adder Class Submarine Torpedo Boat.", "scope": "machine", "narrative_roles": ["intended_role"]},
        {"fact_id": "C2", "claim": "USS Plunger (SS-2) was built at Crescent Shipyard under subcontract from J.P. Holland's company.", "scope": "machine", "narrative_roles": ["design"]},
        {"fact_id": "C3", "claim": "USS Plunger (SS-2) had a displacement of 149 tons surfaced and 168 tons submerged.", "scope": "machine", "narrative_roles": ["design"]},
        {"fact_id": "C4", "claim": "USS Plunger (SS-2) conducted a demonstration dive with President Theodore Roosevelt aboard.", "scope": "machine", "narrative_roles": ["actual_use"]},
        {"fact_id": "C5", "claim": "USS Plunger (SS-2) was renamed USS A-1 on 17 November 1911.", "scope": "machine", "narrative_roles": ["actual_use"]},
        {"fact_id": "C6", "claim": "USS Plunger (SS-2) was authorized as an experimental target designated Target E.", "scope": "machine", "narrative_roles": ["actual_use"]},
        {"fact_id": "C7", "claim": "USS Plunger (SS-2) was struck from the Naval Register and sold for scrapping.", "scope": "machine", "narrative_roles": ["outcome"]},
    ])
    original = copy.deepcopy(packet)

    brief = build_dvsu_brief(packet)

    assert BRIEF_VERSION == 2
    assert brief["ready"] is False
    assert brief["missing_fields"] == ["intended_role", "design"]
    assert brief["fields"]["actual_use"] == ["C4", "C6"]
    assert brief["fields"]["outcome"] == ["C7"]
    assert {fact["fact_id"] for fact in brief["facts"]} == {fact["fact_id"] for fact in packet["facts"]}
    assert packet == original


def test_saved_holland_remains_ready_with_unchanged_facts():
    packet = _packet("SS-1 USS Holland", [
        {"fact_id": "C1", "claim": "Admiral Dewey attributed great value to USS Holland's type for harbor and coast defense.", "scope": "machine", "narrative_roles": ["intended_role"]},
        {"fact_id": "C2", "claim": "USS Holland incorporated dual propulsion systems and separate main and auxiliary ballast systems.", "scope": "machine", "narrative_roles": ["design"]},
        {"fact_id": "C3", "claim": "USS Holland's interior space was one contiguous compartment.", "scope": "machine", "narrative_roles": ["design"]},
        {"fact_id": "C4", "claim": "USS Holland had one reloadable bow torpedo tube carrying three torpedoes.", "scope": "machine", "narrative_roles": ["design"]},
        {"fact_id": "C5", "claim": "USS Holland spent most of her ten years in service at the U.S. Naval Academy as a training submarine.", "scope": "machine", "narrative_roles": ["actual_use"]},
        {"fact_id": "C6", "claim": "The U.S. Navy commissioned USS Holland in 1900, establishing the U.S. Submarine Force.", "scope": "machine", "narrative_roles": ["outcome"]},
    ])
    original = copy.deepcopy(packet)

    brief = build_dvsu_brief(packet)

    assert brief["ready"] is True
    assert brief["missing_fields"] == []
    assert brief["fields"]["intended_role"] == ["C1"]
    assert brief["fields"]["design"] == ["C2", "C3", "C4"]
    assert brief["fields"]["actual_use"] == ["C5"]
    assert packet == original


def test_negative_guards_apply_to_explicit_and_inferred_roles_without_removing_meaningful_evidence():
    facts = [
        {"fact_id": "E1", "claim": "Example was classified as a coastal class.", "scope": "machine", "narrative_roles": ["intended_role"]},
        {"fact_id": "E2", "claim": "Example was built at a shipyard under subcontract.", "scope": "machine", "narrative_roles": ["design"]},
        {"fact_id": "E3", "claim": "Example had a displacement of 149 tons.", "scope": "machine", "narrative_roles": ["design"]},
        {"fact_id": "E4", "claim": "Example was renamed A-1.", "scope": "machine", "narrative_roles": ["actual_use"]},
        {"fact_id": "E5", "claim": "Example was classified as a coastal class, built at a shipyard.", "scope": "intended role", "narrative_roles": ["intended_role"]},
        {"fact_id": "E6", "claim": "Example was classified as a coastal class.", "scope": "intended role", "narrative_roles": ["intended_role"]},
        {"fact_id": "I1", "claim": "Example was designed for harbor defense.", "scope": "machine"},
        {"fact_id": "I2", "claim": "Example had a displacement of 149 tons and separate ballast systems.", "scope": "machine"},
        {"fact_id": "I3", "claim": "Example was renamed A-1 and then served as a training submarine.", "scope": "machine"},
        {"fact_id": "O1", "claim": "Example was retired in 1920.", "scope": "outcome", "narrative_roles": ["outcome"]},
    ]

    brief = build_dvsu_brief({"machine": "Example", "facts": facts})

    assert brief["fields"] == {
        "intended_role": ["I1"],
        "design": ["I2"],
        "actual_use": ["I3"],
        "outcome": ["O1"],
    }
    assert "E5" not in brief["fields"]["intended_role"]  # class plus builder metadata is not a job
    assert "E6" not in brief["fields"]["intended_role"]  # a role-shaped scope cannot supply missing evidence
    assert {fact["fact_id"] for fact in brief["facts"]} == {fact["fact_id"] for fact in facts}
