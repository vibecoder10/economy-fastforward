"""Strict named-submarine section-prefix recovery contracts."""
from __future__ import annotations

import pipeline_executor as pe
from factual_machine_research import candidate_mentions_machine
from factual_source_sections import anchored_section_prefix


MACHINE = "SS-2 USS Plunger"


def _candidates(section: str) -> list[str]:
    return pe._sentence_candidates_from_source(
        "Publisher section\n\n" + section, MACHINE, matcher=candidate_mentions_machine
    )


def test_anchor_keeps_contiguous_ss2_specifications_and_stops_before_foreign_ship():
    section = (
        "USS Plunger (SS-2) entered service after commissioning. "
        "Specifications list a gasoline engine, electric motors, and a torpedo tube. "
        "The boat tested its propulsion machinery during trials. "
        "USS Porpoise (SS-7) joined a different flotilla. "
        "She later operated with that flotilla."
    )

    prefix = anchored_section_prefix(section, MACHINE, candidate_mentions_machine)
    excerpts = _candidates(section)

    expected = (
        "USS Plunger (SS-2) entered service after commissioning. "
        "Specifications list a gasoline engine, electric motors, and a torpedo tube. "
        "The boat tested its propulsion machinery during trials."
    )
    assert prefix == expected
    assert prefix in excerpts
    assert "SS-7" not in prefix and "She later operated" not in prefix
    assert all("SS-7" not in excerpt and "She later operated" not in excerpt for excerpt in excerpts)


def test_long_prefix_ends_on_a_sentence_boundary_at_the_cap():
    section = "USS Plunger (SS-2) entered service. " + "Specifications record propulsion and ballast systems. " * 100
    assert len(section) > 3000

    prefix = anchored_section_prefix(section, MACHINE, candidate_mentions_machine)

    assert 45 <= len(prefix) <= 3000
    assert prefix.endswith(".")
    assert prefix in section
    assert section.startswith(prefix)


def test_wrong_ss179_or_no_identity_cannot_anchor():
    wrong_hull = "USS Plunger (SS-179) carried out trials. Specifications followed."
    no_identity = "The submarine carried out trials. Its propulsion machinery was tested."

    assert anchored_section_prefix(wrong_hull, MACHINE, candidate_mentions_machine) == ""
    assert _candidates(wrong_hull) == []
    assert anchored_section_prefix(no_identity, MACHINE, candidate_mentions_machine) == ""
    assert _candidates(no_identity) == []


def test_short_accepted_named_section_is_preserved_unchanged():
    section = (
        "USS Plunger (SS-2) entered service after commissioning. "
        "Specifications list gasoline propulsion and electric motors. "
        "The submarine conducted testing during trials."
    )

    excerpts = _candidates(section)

    assert section in excerpts


def test_foreign_opening_cannot_anchor_but_later_exact_target_owns_only_following_text():
    section = (
        "USS Porpoise (SS-7) operated with a flotilla. "
        "USS Plunger (SS-2) entered service after commissioning. "
        "Specifications list gasoline propulsion and electric motors. "
        "USS Shark (SS-8) later joined the flotilla. "
        "She remained with that other vessel."
    )

    prefix = anchored_section_prefix(section, MACHINE, candidate_mentions_machine)
    excerpts = _candidates(section)

    assert prefix == (
        "USS Plunger (SS-2) entered service after commissioning. "
        "Specifications list gasoline propulsion and electric motors."
    )
    assert prefix in excerpts
    assert "SS-7" not in prefix and "SS-8" not in prefix and "She remained" not in prefix


def test_explicit_rename_keeps_subject_header_but_does_not_authorize_other_alias_passages():
    section = (
        'USS Plunger (SS-2) was commissioned; Renamed USS A-1 in 1911. '
        'Specifications: gasoline engine and electric motors. '
        'USS A-1 later sailed elsewhere. '
        'She carried additional equipment.'
    )
    prefix = anchored_section_prefix(section, MACHINE, candidate_mentions_machine)
    assert prefix == section.split(' USS A-1 later')[0]
    assert 'electric motors' in prefix
    assert 'elsewhere' not in prefix
    foreign_hull = section.replace('Renamed USS A-1', 'Renamed USS A-1 (SS-7)')
    assert anchored_section_prefix(foreign_hull, MACHINE, candidate_mentions_machine) == ''
