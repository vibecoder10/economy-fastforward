import json
from pathlib import Path

import factual_machine_research as factual


def test_saved_roster_subjects_drop_only_naval_range_bookkeeping():
    fixture = Path(__file__).parent / "fixtures/research-roster-class-labels.json"
    labels = json.loads(fixture.read_text())
    subjects = [factual.factual_research_subject(label) for label in labels]

    assert len(subjects) == 20
    assert all("through" not in subject.casefold() for subject in subjects)
    assert "S-class" in subjects
    assert "Plunger class" in subjects
    assert "Albacore class" in subjects


def test_ranged_class_requires_class_phrase_or_named_member_with_exact_hull():
    plunger = "SS-2 through SS-8 Plunger class"
    s_class = "SS-105 through SS-162 S-class"

    assert factual.candidate_mentions_machine("The Plunger-class submarine was an early United States Navy design.", plunger)
    assert factual.candidate_mentions_machine("USS Plunger (SS-2) entered service in 1903 as a submarine.", plunger)
    assert not factual.candidate_mentions_machine("USS Other (SS-2) entered service in 1903 as a submarine.", plunger)
    assert not factual.candidate_mentions_machine("SS-2 entered service in 1903 as a submarine.", plunger)
    assert not factual.candidate_mentions_machine("USS Plunger entered service in 1903 as a submarine.", plunger)
    assert factual.candidate_mentions_machine("United States S-class submarines served through the interwar years.", s_class)
    assert not factual.candidate_mentions_machine("The crew moved through the harbor before the submarine sailed.", s_class)


def test_class_and_single_hull_guards_preserve_exact_identity():
    gato = "SS-212 through SS-284 Gato class"
    albacore = "AGSS-569 Albacore class"
    barracuda = "SS-163 through SS-165 Barracuda (V-1) class"
    holland = "SS-1 Holland class"

    assert factual.candidate_mentions_machine("The Gato-class submarine had a long Pacific war service.", gato)
    assert not factual.candidate_mentions_machine("The Balao-class submarine had a long Pacific war service.", gato)
    assert factual.candidate_mentions_machine("USS Albacore (AGSS-569) was an experimental research submarine.", albacore)
    assert not factual.candidate_mentions_machine("USS Other (AGSS-569) was an experimental research submarine.", albacore)
    assert not factual.candidate_mentions_machine("USS Albacore was an experimental research submarine.", albacore)
    assert factual.candidate_mentions_machine("The Barracuda (V-1) class consisted of fleet submarines.", barracuda)
    assert not factual.candidate_mentions_machine("USS Barracuda (V-2) (SS-163) consisted of fleet submarines.", barracuda)
    assert factual.candidate_mentions_machine("After Navy trials of Holland, the Navy purchased the submarine in 1900.", holland)
    assert not factual.candidate_mentions_machine("John Holland designed submarines in the 1870s.", holland)


def test_labels_with_a_trailing_parenthetical_still_match_their_class_or_named_boat():
    barracuda = "Barracuda class (V-1 group)"
    tang = "Tang class (SS-563)"
    nautilus = "USS Nautilus (SSN-571)"

    assert factual.candidate_mentions_machine("Regarding Barracuda class (V-1 group): The boats ran trials.", barracuda)
    assert factual.candidate_mentions_machine("The Barracuda-class boats were fleet submarines.", barracuda)
    assert not factual.candidate_mentions_machine("The Bass-class boats were fleet submarines.", barracuda)
    assert factual.candidate_mentions_machine("Regarding Tang class (SS-563): The boats ran trials.", tang)
    assert not factual.candidate_mentions_machine("The Balao-class boats ran trials.", tang)
    assert factual.candidate_mentions_machine("USS Nautilus (SSN-571) was the first nuclear submarine.", nautilus)
    assert not factual.candidate_mentions_machine("USS Seawolf was the second nuclear submarine.", nautilus)
