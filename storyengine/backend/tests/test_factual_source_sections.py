"""Regression coverage for heading-bounded factual source recovery."""

from pathlib import Path

import pytest

import pipeline_executor as pe
from factual_machine_research import candidate_mentions_machine
from factual_source_sections import has_foreign_ship, html_visible_sections, verified_archive_url


FIXTURE = Path(__file__).parent / "fixtures" / "holland-source-section.html"
HOLLAND = "SS 1 USS Holland"
TRAINING = (
    "USS Holland spent most of her ten years in service at the U.S. Naval Academy "
    "as a training submarine."
)


def _normalized(value: str) -> str:
    return pe._normalized_source_text(value)


def test_captured_holland_section_recovers_training_as_exact_source_text():
    raw_html = FIXTURE.read_text(encoding="utf-8")
    source = pe._html_to_visible_text(raw_html, preserve_sections=True)

    excerpts = pe._sentence_candidates_from_source(
        source, HOLLAND, matcher=candidate_mentions_machine
    )

    training = _normalized(TRAINING)
    assert any(training in _normalized(excerpt) for excerpt in excerpts)
    assert all(_normalized(excerpt) in _normalized(source) for excerpt in excerpts)


def test_heading_sections_prevent_next_foreign_ship_from_bleeding_into_holland():
    raw_html = FIXTURE.read_text(encoding="utf-8")
    source = pe._html_to_visible_text(raw_html, preserve_sections=True)

    assert "John Philip Holland" in source
    assert "\n\nForeign ship" in source
    assert html_visible_sections(raw_html) == source

    excerpts = pe._sentence_candidates_from_source(
        source, HOLLAND, matcher=candidate_mentions_machine
    )
    assert excerpts
    assert all(
        "HMS Example" not in excerpt
        and "P 99" not in excerpt
        and "USS Other" not in excerpt
        and "SS 77" not in excerpt
        for excerpt in excerpts
    )


def test_wrong_hull_is_rejected_even_when_the_ship_name_matches():
    source = (
        "John Philip Holland\n"
        "USS Holland (SS 2) completed trials as a different submarine."
    )

    assert has_foreign_ship(source, HOLLAND)
    assert pe._sentence_candidates_from_source(
        source, HOLLAND, matcher=candidate_mentions_machine
    ) == []


def test_long_named_section_keeps_bounded_contiguous_prefix_and_short_windows():
    sentences = [
        f"USS Holland (SS 1) completed Navy trials as a submarine in documented phase {index}."
        for index in range(1, 80)
    ]
    source = "Page introduction\n\nJohn Philip Holland " + " ".join(sentences)
    assert len(source) > 3000

    excerpts = pe._sentence_candidates_from_source(
        source, HOLLAND, matcher=candidate_mentions_machine
    )

    assert excerpts
    assert all(len(excerpt) <= 3000 for excerpt in excerpts)
    long_prefixes = [excerpt for excerpt in excerpts if len(excerpt) > 720]
    assert len(long_prefixes) == 1
    assert long_prefixes[0] in source
    assert long_prefixes[0].endswith('.')
    assert source not in excerpts


def test_legacy_aircraft_sentence_path_is_unchanged_without_strict_matcher():
    sentence = "The B-2 served the U.S. Air Force as a strategic bomber for decades."
    source = sentence + " It entered service later."

    excerpts = pe._sentence_candidates_from_source(source, "B-2")

    assert sentence in excerpts


ORIGINAL_URL = "https://example.org/history/holland?source=museum"
VALID_SNAPSHOT = {
    "available": True,
    "status": "200",
    "url": "http://web.archive.org/web/20260916123456id_/https://example.org/history/holland?source=museum",
}


def test_verified_archive_url_accepts_the_same_real_source_and_prefers_https():
    assert verified_archive_url(VALID_SNAPSHOT, ORIGINAL_URL) == (
        "https://web.archive.org/web/20260916123456id_/https://example.org/history/holland?source=museum"
    )


@pytest.mark.parametrize(
    "snapshot",
    [
        {**VALID_SNAPSHOT, "available": False},
        {"status": "200", "url": VALID_SNAPSHOT["url"]},
        {**VALID_SNAPSHOT, "url": VALID_SNAPSHOT["url"].replace("web.archive.org", "archive.example.org")},
        {**VALID_SNAPSHOT, "url": VALID_SNAPSHOT["url"].replace("holland?source=museum", "other")},
        {**VALID_SNAPSHOT, "url": VALID_SNAPSHOT["url"].replace("20260916123456", "2026091612345x")},
    ],
)
def test_verified_archive_url_rejects_unverified_or_malformed_snapshots(snapshot):
    assert verified_archive_url(snapshot, ORIGINAL_URL) == ""
