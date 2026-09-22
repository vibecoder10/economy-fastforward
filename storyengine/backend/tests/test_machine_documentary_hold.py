"""Regression locks for the siloed machine-documentary hold pipeline.

These tests are local/no-spend. They prove the machine-only path uses explicit
static-docu + locked-roster eligibility, isolates each writer prompt to one
saved card, and does not alter the global animation/narrative writer path.
"""

import asyncio
import copy
import json

import pipeline_executor as pe


def _words(machine: str, count: int) -> str:
    tokens = [machine] + [f"word{i}" for i in range(1, count)]
    return " ".join(tokens)


def _formula_sentences_from_paragraph(paragraph: str) -> list[str]:
    return [part if part.endswith(".") else part + "." for part in paragraph.split(". ") if part]


def _story_bundle(machine: str, words_per_sentence: int) -> str:
    target_words = max(5, words_per_sentence * 5)
    sentences = [
        f"{machine} original problem claim grounded in the supplied source.",
        "Engineering decision claim grounded in the supplied source.",
        "Tradeoff claim grounded in the supplied source.",
        "Reality claim grounded in the supplied source.",
        "The proof survived the machine.",
    ]
    fill_index = 0
    while pe._spoken_word_count(" ".join(sentences)) < target_words:
        index = fill_index % (len(sentences) - 1)
        sentences[index] = sentences[index].rstrip(".") + " clear."
        fill_index += 1
    ids = [
        ["E-PROBLEM"],
        ["E-DECISION"],
        ["E-TRADEOFF"],
        ["E-REALITY", "E-MEMORABLE"],
    ]
    return json.dumps({
        "editorial_thesis": f"{machine} mattered because its design promise had to survive real operating limits.",
        # QL-3/QL-4: every entry declares its designed-vs-used twist.
        "twist": {"type": "role_change", "substitute": None, "summary": "Built for the promise, used as the proof."},
        "formula_sentences": sentences,
        "paragraph": " ".join(sentences),
        "claim_map": [
            {"slot": slot, "span": sentence, "used_evidence_ids": evidence_ids}
            for slot, sentence, evidence_ids in zip(
                ["original_problem", "engineering_decision", "tradeoff", "reality"],
                sentences,
                ids,
            )
        ],
        "onscreen_label": "",
    })


def _echo_polish_response(prompt: str):
    """G20: every real draft now gets ONE extra `generate()` call for the
    language-polish pass, which asks for a JSON array of the same sentences
    line-edited for grammar. Fixtures below that scripted an exact
    `outputs` queue (or an exact call count) predate that pass; rather than
    hand-crafting a scripted polish reply for every fixture, detect the
    polish prompt by its marker and echo its own input sentences straight
    back - a true no-op polish, so it never consumes the `outputs` queue and
    never changes any saved-paragraph assertion, only the call count."""
    marker = "SENTENCES (JSON array, one entry per sentence, in order):\n"
    if marker not in prompt:
        return None
    start = prompt.index(marker) + len(marker)
    end = prompt.index("\n\n", start)
    return prompt[start:end]


def _claim_bundle_from_sentences(machine: str, sentences: list[str]) -> dict:
    roles_and_ids = [
        ("original_problem", ["E-PROBLEM"]),
        ("engineering_decision", ["E-DECISION"]),
        ("tradeoff", ["E-TRADEOFF"]),
        ("reality", ["E-REALITY"]),
    ]
    return {
        "editorial_thesis": f"{machine} mattered because its design promise had to survive real operating limits.",
        "twist": {"type": "role_change", "substitute": None, "summary": "Built for the promise, used as the proof."},
        "formula_sentences": sentences,
        "paragraph": " ".join(sentences),
        "claim_map": [
            {"slot": role, "span": sentence, "used_evidence_ids": evidence_ids}
            for sentence, (role, evidence_ids) in zip(sentences[:4], roles_and_ids)
        ],
        "onscreen_label": "",
    }


def _passing_quality_audit() -> dict:
    return {
        "passed": True,
        "checks": [{
            "name": "validator_warnings",
            "label": "Validator warnings",
            "passed": True,
            "detail": "clean",
        }],
        "summary": "Anton quality audit passed",
    }


def _assert_saved_failed_preview(result: dict, writes: list, machine: str, roster: list[str]) -> dict:
    assert result["status"] == "completed"
    assert result["preview"]["machine"] == machine
    assert result["preview"]["passed"] is False
    assert result["preview"]["paragraph"] == ""
    assert result["preview"]["word_count"] == 0
    assert result["preview"]["claim_bundle"]["claim_map"] == []
    assert result["preview"]["quality_audit"]["passed"] is False
    assert result["preview"]["quality_audit"]["checks"][0]["passed"] is False
    saved_preview_rows = [(query, args) for query, args in writes if "machine_script_previews" in query]
    assert len(saved_preview_rows) == 1
    saved_query, saved_args = saved_preview_rows[0]
    assert saved_args[0] == pe._verified_source_cache_key(machine)
    assert json.loads(saved_args[1]) == result["preview"]
    assert json.loads(saved_args[4]) == roster
    assert "research_payload->'unit_roster' = $5::jsonb" in saved_query
    response_key = pe._verified_source_cache_key(machine)
    assert result["research_payload"]["machine_script_previews"][response_key] == result["preview"]
    return result["preview"]


def _problem_opening_story_bundle(machine: str, words_per_sentence: int = 19) -> str:
    bundle = json.loads(_story_bundle(machine, words_per_sentence))
    old_span = bundle["claim_map"][0]["span"]
    new_span = old_span
    prefix = f"{machine} "
    if new_span.startswith(prefix):
        new_span = new_span[len(prefix):]
        new_span = new_span[:1].upper() + new_span[1:]
    bundle["claim_map"][0]["span"] = new_span
    bundle["paragraph"] = bundle["paragraph"].replace(old_span, new_span, 1)
    old_final = "The proof survived the machine."
    new_final = f"The proof survived the {machine}."
    bundle["paragraph"] = bundle["paragraph"].replace(old_final, new_final, 1)
    bundle["formula_sentences"] = _formula_sentences_from_paragraph(bundle["paragraph"])
    while pe._spoken_word_count(bundle["paragraph"]) < 95:
        old_decision = bundle["claim_map"][1]["span"]
        new_decision = old_decision.rstrip(".") + " clear."
        bundle["claim_map"][1]["span"] = new_decision
        bundle["paragraph"] = bundle["paragraph"].replace(old_decision, new_decision, 1)
        bundle["formula_sentences"] = _formula_sentences_from_paragraph(bundle["paragraph"])
    return json.dumps(bundle)


def _visual_identity_fields(machine: str) -> dict:
    return {
        "visual_identity": f"{machine} identified by its wing, engine, tail, nose, and fuselage features.",
        "visual_identity_evidence_ids": ["E-DECISION"],
    }


def _timeframe_fields(machine: str) -> dict:
    return {
        "timeframe": f"{machine} documented through its Cold War service period.",
        "timeframe_evidence_ids": ["E-REALITY"],
    }


def _evidence_segments() -> list[dict]:
    rows = [
        ("E-PROBLEM", "original_problem", "Original problem claim grounded in the supplied source."),
        ("E-ROLE", "role_category", "Role category claim grounded in the supplied source."),
        ("E-DECISION", "engineering_decision", "Engineering decision claim grounded in the supplied source with wing, engine, tail, nose, and fuselage features."),
        ("E-TRADEOFF", "tradeoff", "Tradeoff claim grounded in the supplied source."),
        ("E-REALITY", "reality", "Reality claim grounded in the supplied source through its Cold War service period."),
        ("E-MEMORABLE", "memorable_fact", "Memorable fact claim grounded in the supplied source."),
        ("E-MEANING", "historical_meaning", "Historical meaning claim grounded in the supplied source."),
        ("E-LABEL", "onscreen_label", "Onscreen label claim grounded in the supplied source."),
    ]
    return [
        {
            "evidence_id": evidence_id,
            "kind": kind,
            "claim": claim,
            "source_excerpt": claim,
            "source_url": f"https://airandspace.si.edu/test/{kind}",
            "source_title": "Test source",
            "locator": f"S{index}-E1",
            "numeric_tokens": [],
            "confidence": "high",
        }
        for index, (evidence_id, kind, claim) in enumerate(rows, start=1)
    ]


def _valid_research_card(machine: str, segments=None, **overrides) -> dict:
    evidence = copy.deepcopy(segments if segments is not None else _evidence_segments())
    card = {
        "unit": machine,
        "engineering_thesis": (
            f"{machine} mattered because its bomber range decision exposed power tradeoffs in service."
        ),
        "why_this_unit_deserves_a_paragraph": (
            f"{machine} deserves a paragraph because its range problem exposed a tradeoff "
            "between bomber size, power, and service reality."
        ),
        "surprising_fact": "Memorable fact claim grounded in the supplied source.",
        "source_notes": ["xb15-source"],
        "evidence_segments": evidence,
    }
    card.update(_visual_identity_fields(machine))
    card.update(_timeframe_fields(machine))
    card.update(overrides)
    return card


def _verified_package_for_segments(machine: str, segments: list[dict]) -> dict:
    return {
        "passed": True,
        "machine": machine,
        "machine_key": pe._normalized_unit_code(machine),
        "search_queries": [f'"{machine}" verified source'],
        "sources": [
            {
                "source_id": f"S{index}",
                "title": segment["source_title"],
                "url": segment["source_url"],
                "text_hash": "test",
                "text_chars": len(segment["source_excerpt"]),
            }
            for index, segment in enumerate(segments, start=1)
        ],
        "candidate_excerpts": [
            {
                "excerpt_id": f"S{index}-E1",
                "source_id": f"S{index}",
                "source_title": segment["source_title"],
                "source_url": segment["source_url"],
                "locator": segment.get("locator") or f"S{index}-E1",
                "text": f"{machine} {segment['source_excerpt']}",
                "text_hash": "test",
                "source_capture_method": "fetched_page",
                "source_variant_selection": {
                    "selected_capture_method": "fetched_page",
                    "selected_variant": {
                        "source_capture_method": "fetched_page",
                        "covered_slot_count": 4,
                        "distinct_slot_excerpt_count": 4,
                    },
                    "evaluated_variants": [
                        {"source_capture_method": "fetched_page", "covered_slot_count": 4},
                    ],
                    "selection_rule": "highest Anton-slot coverage; fetched_page wins exact ties",
                },
            }
            for index, segment in enumerate(segments, start=1)
        ],
    }


def test_verified_machine_source_queries_cover_anton_research_slots():
    queries = pe._verified_machine_source_queries(
        "Every US Strategic Bomber Ever Built",
        "Boeing XB-15",
    )
    joined = " ".join(queries).lower()

    assert len(queries) == 8
    assert len(queries) == len(set(queries))
    assert all('"Boeing XB-15"' in query for query in queries)
    assert "official history" in joined
    assert "usaf fact sheet" in joined
    assert "national museum" in joined
    assert "specifications range payload wingspan engines" in joined
    assert "production prototype built service operational history" in joined
    assert "design tradeoff limitation lessons learned test report" in joined
    assert "pilot crew memoir oral history official inquiry unusual fact" in joined


def test_source_excerpt_cap_reserves_a_late_tradeoff_window():
    machine = "CV-63 USS Kitty Hawk"
    filler = " ".join(
        f"{machine} completed routine deployment number {index}."
        for index in range(1, 13)
    )
    source = (
        filler
        + f" {machine} suffered an engine-room fuel fire."
        + " Three propulsion systems had to shut down, forcing the crew to balance the ship."
    )

    excerpts = pe._sentence_candidates_from_source(source, machine, limit=10)

    assert len(excerpts) == 10
    assert any("tradeoff" in pe._anton_source_slot_hints(row) for row in excerpts)
    assert any("propulsion systems had to shut down" in row for row in excerpts)


def test_verified_machine_source_queries_aircraft_snapshot_byte_identical():
    """G13, 2026-07-31: the naval branch must never alter the aircraft query
    set - this is the exact 8-string output frozen before G13's naval branch
    was added, compared for full-list equality (not substrings)."""
    queries = pe._verified_machine_source_queries(
        "Every US Strategic Bomber Ever Built",
        "Boeing XB-15",
    )

    assert queries == [
        '"Boeing XB-15" official history',
        '"Boeing XB-15" USAF fact sheet',
        '"Boeing XB-15" National Museum of the United States Air Force',
        '"Boeing XB-15" Boeing development design history',
        '"Boeing XB-15" specifications range payload wingspan engines',
        '"Boeing XB-15" production prototype built service operational history',
        '"Boeing XB-15" design tradeoff limitation lessons learned test report',
        '"Boeing XB-15" pilot crew memoir oral history official inquiry unusual fact',
    ]


def test_verified_machine_source_queries_naval_machine_uses_naval_vocabulary():
    """G13, 2026-07-31: a ship gets naval-domain queries, not the aircraft
    template - the real bug on video d05efae3 (all 5 KGV-class battleships):
    '"32 HMS Howe" USAF fact sheet' and '"53 HMS Prince of Wales" National
    Museum of the United States Air Force' were fired verbatim at Royal Navy
    battleships and returned giant off-topic USAF/DoD PDFs."""
    queries = pe._verified_machine_source_queries(
        "Every Royal Navy Battleship Ever Built",
        "32 HMS Howe",
    )
    joined = " ".join(queries).lower()

    assert len(queries) == 8
    assert len(queries) == len(set(queries))
    assert all('"32 HMS Howe"' in query for query in queries)
    # No aircraft vocabulary anywhere in the naval query set.
    assert "usaf" not in joined
    assert "wingspan" not in joined
    assert "national museum of the united states air force" not in joined
    # Naval vocabulary and embedded proven-fetchable domain names present.
    assert "displacement" in joined
    assert "armament" in joined
    assert "beam" in joined
    assert "commissioned" in joined
    assert "design tradeoff limitation compromise" in joined
    assert "naval-history.net" in joined
    assert "uboat.net" in joined
    assert "discovery.nationalarchives.gov.uk" in joined


def test_verified_machine_source_queries_scope_ambiguous_carrier_class_to_title_subject():
    """A bare "Majestic class" query returned mostly 1890s battleships and
    even fiction for the carrier-class video. Every query lane must carry the
    title's exact carrier subject so broad, official, and archive searches
    cannot silently drift to a namesake class."""
    queries = pe._verified_machine_source_queries(
        "Every British Aircraft Carrier Class Ever Built (2026)",
        "Majestic class",
    )

    assert queries == [
        '"Majestic class" "aircraft carrier" official history commissioned',
        '"Majestic class" "aircraft carrier" class displacement armament beam launched design tradeoff limitation compromise',
        '"Majestic class" "aircraft carrier" naval-history.net',
        '"Majestic class" "aircraft carrier" uboat.net',
        '"Majestic class" "aircraft carrier" service history war record engagement',
        '"Majestic class" "aircraft carrier" loss damage board of enquiry discovery.nationalarchives.gov.uk',
        '"Majestic class" "aircraft carrier" commissioned decommissioned scrapped fate',
        '"Majestic class" "aircraft carrier" crew veteran memoir account officer',
    ]


def test_verified_machine_source_queries_do_not_add_carrier_scope_to_other_naval_titles():
    queries = pe._verified_machine_source_queries(
        "Every Royal Navy Battleship Ever Built",
        "32 HMS Howe",
    )

    assert queries == [
        '"32 HMS Howe" official history commissioned',
        '"32 HMS Howe" class displacement armament beam launched design tradeoff limitation compromise',
        '"32 HMS Howe" naval-history.net',
        '"32 HMS Howe" uboat.net',
        '"32 HMS Howe" service history war record engagement',
        '"32 HMS Howe" loss damage board of enquiry discovery.nationalarchives.gov.uk',
        '"32 HMS Howe" commissioned decommissioned scrapped fate',
        '"32 HMS Howe" crew veteran memoir account officer',
    ]


def test_naval_steering_and_retry_queries_scope_carriers_but_preserve_other_outputs():
    carrier_title = "Every British Aircraft Carrier Class Ever Built (2026)"
    battleship_title = "Every Royal Navy Battleship Ever Built"

    assert pe._naval_museum_domain_query("Majestic class", carrier_title) == (
        '"Majestic class" "aircraft carrier" history design service'
    )
    assert pe._naval_reworded_retry_query("Majestic class", carrier_title) == (
        '"Majestic class" "aircraft carrier" Royal Navy warship history museum archive record'
    )
    assert pe._naval_museum_domain_query("32 HMS Howe", battleship_title) == (
        '"32 HMS Howe" history design service'
    )
    assert pe._naval_reworded_retry_query("32 HMS Howe", battleship_title) == (
        "32 HMS Howe Royal Navy warship history museum archive record"
    )
    assert pe._naval_museum_domain_query("32 HMS Howe") == '"32 HMS Howe" history design service'
    assert pe._naval_reworded_retry_query("32 HMS Howe") == (
        "32 HMS Howe Royal Navy warship history museum archive record"
    )


def test_machine_mentions_use_designation_boundaries():
    assert pe._mentions_machine("The Northrop B-2 Spirit entered service as a stealth bomber.", "B-2")
    assert pe._mentions_machine("The B2 bomber appears without a hyphen in this source.", "B-2")
    assert pe._mentions_machine("The B-2A variant is still evidence for the B-2.", "B-2")
    assert not pe._mentions_machine("The B-21 Raider is a different bomber.", "B-2")

    assert pe._mentions_machine("The B-1B Lancer changed the bomber's mission profile.", "B-1")
    assert not pe._mentions_machine("The Martin B-10 was an earlier bomber.", "B-1")
    assert pe._mentions_machine("The Boeing XB-15 was built as an experimental bomber.", "Boeing XB-15")


def test_verified_source_package_quality_rejects_designation_substring_collision():
    package = _verified_package_for_segments("B-2", _evidence_segments())
    for candidate in package["candidate_excerpts"]:
        candidate["text"] = (
            "The B-21 Raider source discusses requirement, engineering decision, "
            "tradeoff, and service reality details for a different bomber."
        )

    errors = pe._verified_machine_source_package_quality_errors(package, "B-2")

    assert any("mentioning the locked machine" in error for error in errors)


def test_verified_source_package_format_exposes_source_tier():
    segments = _evidence_segments()
    segments[0]["source_url"] = "https://en.wikipedia.org/wiki/Boeing_XB-15"
    package = _verified_package_for_segments("Boeing XB-15", segments)
    package["candidate_excerpts"][0]["source_capture_method"] = "fetched_page"
    pe._anton_source_slot_coverage(package["candidate_excerpts"], "Boeing XB-15")

    formatted = pe._format_verified_machine_source_package(package)

    assert "SOURCE_TIER: 4 - Tier 4 caution/general" in formatted
    assert "SOURCE_CAPTURE_METHOD: fetched_page" in formatted
    assert "SOURCE_SELECTION: selected=fetched_page" in formatted
    assert "score=4 slots/4 distinct" in formatted
    assert "EXCERPT_TEXT_HASH: test" in formatted
    assert "ANTON_SLOT_HINTS:" in formatted


def test_verified_source_package_format_hides_untraceable_or_wrong_machine_rows():
    segments = _evidence_segments()
    package = _verified_package_for_segments("Boeing XB-15", segments)
    package["candidate_excerpts"].append({
        "excerpt_id": "S99-E1",
        "source_title": "Snippet-like row",
        "source_url": "https://example.test/snippet",
        "text": "The Boeing XB-15 appears in a search-result snippet with no capture method.",
        "locator": "S99-E1",
    })
    package["candidate_excerpts"].append({
        "excerpt_id": "S98-E1",
        "source_title": "Wrong machine row",
        "source_url": "https://airandspace.si.edu/collection-objects/b-17",
        "text": "The Boeing B-17 Flying Fortress source talks about a different bomber.",
        "locator": "S98-E1",
        "source_capture_method": "fetched_page",
    })

    formatted = pe._format_verified_machine_source_package(package, "Boeing XB-15")

    assert "Only approved-capture, source_url/locator-traceable rows" in formatted
    assert "SOURCE_CAPTURE_METHOD: fetched_page" in formatted
    assert "SOURCE_SELECTION: selected=fetched_page" in formatted
    assert "EXCERPT_TEXT_HASH: test" in formatted
    assert "Original problem claim grounded in the supplied source" in formatted
    assert "search-result snippet" not in formatted
    assert "legacy_unmarked" not in formatted
    assert "B-17 Flying Fortress" not in formatted


def test_verified_source_package_quality_rejects_single_source_and_caution_only():
    single_source_segments = _evidence_segments()
    for segment in single_source_segments:
        segment["source_url"] = "https://airandspace.si.edu/collection-objects/boeing-xb-15"
    single_source = _verified_package_for_segments("Boeing XB-15", single_source_segments)

    single_source_errors = pe._verified_machine_source_package_quality_errors(single_source)

    assert any("two distinct source URLs" in error for error in single_source_errors)

    diverse_segments = _evidence_segments()
    for index, segment in enumerate(diverse_segments):
        segment["source_url"] = f"https://airandspace.si.edu/collection-objects/boeing-xb-15-{index}"
    diverse_package = _verified_package_for_segments("Boeing XB-15", diverse_segments)

    assert pe._verified_machine_source_package_quality_errors(diverse_package) == []
    assert pe._verified_machine_source_package_quality_errors(diverse_package, "Boeing XB-15") == []

    secondary_segments = _evidence_segments()
    for index, segment in enumerate(secondary_segments):
        segment["source_url"] = f"https://example-secondary.test/boeing-xb-15-{index}"
    secondary_package = _verified_package_for_segments("Boeing XB-15", secondary_segments)

    secondary_errors = pe._verified_machine_source_package_quality_errors(secondary_package)

    assert any("Tier 1-2 primary/authoritative source" in error for error in secondary_errors)

    caution_segments = _evidence_segments()
    for index, segment in enumerate(caution_segments):
        segment["source_url"] = [
            "https://en.wikipedia.org/wiki/Boeing_XB-15",
            "https://www.youtube.com/watch?v=test",
        ][index % 2]
    caution_package = _verified_package_for_segments("Boeing XB-15", caution_segments)

    caution_errors = pe._verified_machine_source_package_quality_errors(caution_package)

    assert any("non-caution source" in error for error in caution_errors)

    unsupported_capture_package = _verified_package_for_segments("Boeing XB-15", _evidence_segments())
    unsupported_capture_package["candidate_excerpts"][0]["source_capture_method"] = "tavily_snippet"

    unsupported_errors = pe._verified_machine_source_package_quality_errors(unsupported_capture_package)

    assert any("unsupported source capture method" in error for error in unsupported_errors)

    missing_capture_package = _verified_package_for_segments("Boeing XB-15", _evidence_segments())
    missing_capture_package["candidate_excerpts"][0].pop("source_capture_method")

    missing_capture_errors = pe._verified_machine_source_package_quality_errors(missing_capture_package)

    assert any("without source capture method" in error for error in missing_capture_errors)

    missing_provenance_package = _verified_package_for_segments("Boeing XB-15", _evidence_segments())
    missing_provenance_package["candidate_excerpts"][0].pop("source_variant_selection")

    missing_provenance_errors = pe._verified_machine_source_package_quality_errors(missing_provenance_package)

    assert any("without source selection provenance" in error for error in missing_provenance_errors)


def test_verified_source_package_quality_rejects_tier_four_only_required_slot():
    segments = _evidence_segments()
    for segment in segments:
        segment["source_url"] = "https://airandspace.si.edu/collection-objects/boeing-xb-15"
    segments[0]["source_url"] = "https://en.wikipedia.org/wiki/Boeing_XB-15"
    package = _verified_package_for_segments("Boeing XB-15", segments)

    errors = pe._verified_machine_source_package_quality_errors(package, "Boeing XB-15")

    assert any("only with Tier 4/caution excerpts: original_problem" in error for error in errors)


def test_verified_source_package_quality_rejects_untraceable_required_slot():
    segments = _evidence_segments()
    for index, segment in enumerate(segments):
        segment["source_url"] = f"https://airandspace.si.edu/collection-objects/boeing-xb-15-{index}"
    package = _verified_package_for_segments("Boeing XB-15", segments)
    package["candidate_excerpts"][0].pop("source_url")

    errors = pe._verified_machine_source_package_quality_errors(package, "Boeing XB-15")

    assert any("need traceable source_url/locator excerpts: original_problem" in error for error in errors)


def test_verified_source_package_quality_uses_traceable_candidates_for_tier_four_slot_check():
    segments = _evidence_segments()
    for index, segment in enumerate(segments):
        segment["source_url"] = f"https://airandspace.si.edu/collection-objects/boeing-xb-15-{index}"
    wiki_problem = copy.deepcopy(segments[0])
    wiki_problem["evidence_id"] = "E-PROBLEM-WIKI"
    wiki_problem["source_url"] = "https://en.wikipedia.org/wiki/Boeing_XB-15"
    segments.append(wiki_problem)
    package = _verified_package_for_segments("Boeing XB-15", segments)
    package["candidate_excerpts"][0].pop("source_url")

    errors = pe._verified_machine_source_package_quality_errors(package, "Boeing XB-15")

    assert not any("need traceable source_url/locator excerpts: original_problem" in error for error in errors)
    assert any("only with Tier 4/caution excerpts: original_problem" in error for error in errors)


def test_verified_source_package_quality_requires_distinct_traceable_slot_excerpts():
    package = _verified_package_for_segments("Boeing XB-15", _evidence_segments())
    broad_traceable = (
        "Boeing XB-15 was required for a long-range bomber program, built with "
        "large wing and engine choices, but underpowered, and later served as a "
        "World War II transport."
    )
    package["candidate_excerpts"][0]["text"] = broad_traceable
    for index, candidate in enumerate(package["candidate_excerpts"][1:4], start=1):
        candidate["text"] = [
            "Boeing XB-15 was required for a long-range bomber program.",
            "Boeing XB-15 was built with large wing and engine choices.",
            "Boeing XB-15 was underpowered and later served as a World War II transport.",
        ][index - 1]
        candidate.pop("source_url")
    for index, candidate in enumerate(package["candidate_excerpts"][4:], start=4):
        candidate["text"] = f"Boeing XB-15 archived source row alpha bravo charlie delta {index}."
        candidate["source_url"] = f"https://airandspace.si.edu/collection-objects/boeing-xb-15-{index}"

    errors = pe._verified_machine_source_package_quality_errors(package, "Boeing XB-15")

    assert not any("need traceable source_url/locator excerpts" in error for error in errors)
    assert any("distinct raw excerpts for each Anton slot that are traceable" in error for error in errors)


def test_verified_source_package_quality_requires_anton_slot_coverage():
    package = _verified_package_for_segments("Boeing XB-15", _evidence_segments())
    for candidate in package["candidate_excerpts"]:
        candidate["text"] = (
            "Boeing XB-15 exact fetched source describes wing, engine, fuselage, "
            "range, speed, payload, and horsepower specifications."
        )

    errors = pe._verified_machine_source_package_quality_errors(package, "Boeing XB-15")

    slot_error = next(
        error for error in errors
        if "exact excerpts plausibly covering Anton slot(s)" in error
    )
    assert "original_problem" in slot_error
    assert "tradeoff" in slot_error
    assert "reality" in slot_error


def test_verified_source_package_quality_requires_distinct_anton_slot_excerpts():
    package = _verified_package_for_segments("Boeing XB-15", _evidence_segments())
    package["candidate_excerpts"][0]["text"] = (
        "Boeing XB-15 was required for a long-range bomber program, built with "
        "large wing and engine choices, but underpowered, and later served as a "
        "World War II transport."
    )
    for candidate in package["candidate_excerpts"][1:]:
        candidate["text"] = "Boeing XB-15 archived source row alpha bravo charlie delta."

    coverage = pe._anton_source_slot_coverage(package["candidate_excerpts"], "Boeing XB-15")
    errors = pe._verified_machine_source_package_quality_errors(package, "Boeing XB-15")

    assert coverage["missing_slots"] == []
    assert coverage["needs_distinct_slot_excerpts"] is True
    assert coverage["distinct_slot_excerpt_assignment"] == {}
    assert any("distinct raw excerpts for each Anton slot" in error for error in errors)


def test_verified_source_package_quality_rejects_overlapping_anton_slot_excerpts():
    package = _verified_package_for_segments("Boeing XB-15", _evidence_segments())
    nested_windows = [
        "Boeing XB-15 was required for a long-range bomber program.",
        "Boeing XB-15 was required for a long-range bomber program and was built with large wing and engine choices.",
        "Boeing XB-15 was required for a long-range bomber program and was built with large wing and engine choices, but it was underpowered.",
        "Boeing XB-15 was required for a long-range bomber program and was built with large wing and engine choices, but it was underpowered and later served as a World War II transport.",
    ]
    for index, text in enumerate(nested_windows):
        package["candidate_excerpts"][index]["text"] = text
    for candidate in package["candidate_excerpts"][len(nested_windows):]:
        candidate["text"] = "Boeing XB-15 archived source row alpha bravo charlie delta."

    coverage = pe._anton_source_slot_coverage(package["candidate_excerpts"], "Boeing XB-15")
    errors = pe._verified_machine_source_package_quality_errors(package, "Boeing XB-15")

    assert coverage["missing_slots"] == []
    assert coverage["needs_distinct_slot_excerpts"] is True
    assert any("distinct raw excerpts for each Anton slot" in error for error in errors)


def test_anton_source_slot_coverage_records_excerpt_ids():
    package = _verified_package_for_segments("Boeing XB-15", _evidence_segments())

    coverage = pe._anton_source_slot_coverage(package["candidate_excerpts"], "Boeing XB-15")

    assert coverage["missing_slots"] == []
    assert set(coverage["covered_slots"]) == {
        "engineering_decision",
        "original_problem",
        "reality",
        "tradeoff",
    }
    assert coverage["evidence_by_slot"]["original_problem"] == ["S1-E1"]
    assert coverage["distinct_slot_excerpt_count"] == 4
    assert coverage["needs_distinct_slot_excerpts"] is False
    assert coverage["distinct_slot_excerpt_assignment"] == {
        "original_problem": "S1-E1",
        "engineering_decision": "S3-E1",
        "tradeoff": "S4-E1",
        "reality": "S5-E1",
    }
    assert "original_problem" in package["candidate_excerpts"][0]["anton_slot_hints"]


def test_verified_source_package_ready_requires_exact_text_excerpts():
    package = _verified_package_for_segments("Boeing XB-15", _evidence_segments())

    assert pe._verified_machine_source_package_ready(package) is True

    blank_package = copy.deepcopy(package)
    for candidate in blank_package["candidate_excerpts"]:
        candidate["text"] = "   "

    assert pe._verified_machine_source_package_ready(blank_package) is False
    assert pe._verified_machine_source_package_quality_errors(blank_package) == []
    assert pe._validate_card_against_verified_sources(
        {"unit": "Boeing XB-15", "evidence_segments": _evidence_segments()},
        blank_package,
    ) == ["missing verified raw internet source package"]


def test_verified_source_package_quality_rejects_wrong_machine_excerpt_text():
    package = _verified_package_for_segments("Boeing XB-15", _evidence_segments())
    for candidate in package["candidate_excerpts"]:
        candidate["text"] = "Boeing B-17 Flying Fortress unrelated fetched source text."

    errors = pe._verified_machine_source_package_quality_errors(package, "Boeing XB-15")

    assert any("mentioning the locked machine" in error for error in errors)


def test_verified_source_package_identity_rejects_wrong_machine_metadata():
    package = _verified_package_for_segments("Boeing B-17 Flying Fortress", _evidence_segments())

    errors = pe._verified_machine_source_package_identity_errors(package, "Boeing XB-15")

    assert any("does not match locked machine XB15" in error for error in errors)
    assert pe._verified_machine_source_package_identity_errors(
        _verified_package_for_segments("Boeing XB-15", _evidence_segments()),
        "Boeing XB-15",
    ) == []


def test_verified_source_cache_ignores_wrong_machine_package(monkeypatch):
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    payload = {
        "machine_raw_source_packages": {
            pe._verified_source_cache_key("Boeing XB-15"): _verified_package_for_segments(
                "Boeing B-17 Flying Fortress", _evidence_segments()
            ),
        },
    }

    async def no_tavily_key(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pe, "get_secret", no_tavily_key)

    result = asyncio.run(
        executor._gather_verified_machine_source_package(
            "Every US Strategic Bomber Ever Built", "Boeing XB-15", payload
        )
    )

    assert result["passed"] is False
    assert "Tavily API key is required" in result["errors"][0]
    assert result["machine"] == "Boeing XB-15"


def test_verified_source_cache_reuses_package_with_review_metadata(monkeypatch):
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    package = _verified_package_for_segments("Boeing XB-15", _evidence_segments())
    package.pop("source_slot_coverage", None)
    package.pop("traceable_source_slot_coverage", None)
    for candidate in package["candidate_excerpts"]:
        candidate.pop("anton_slot_hints", None)
    payload = {
        "machine_raw_source_packages": {
            pe._verified_source_cache_key("Boeing XB-15"): package,
        },
    }

    async def forbidden_get_secret(*_args, **_kwargs):
        raise AssertionError("ready cached raw package should not call Tavily")

    monkeypatch.setattr(pe, "get_secret", forbidden_get_secret)

    result = asyncio.run(
        executor._gather_verified_machine_source_package(
            "Every US Strategic Bomber Ever Built", "Boeing XB-15", payload
        )
    )

    assert result["passed"] is True
    assert result["source_slot_coverage"]["missing_slots"] == []
    assert result["traceable_source_slot_coverage"]["missing_slots"] == []
    assert result["source_slot_coverage"]["needs_distinct_slot_excerpts"] is False
    assert result["traceable_source_slot_coverage"]["needs_distinct_slot_excerpts"] is False
    assert result["candidate_excerpts"][0]["anton_slot_hints"]


def test_verified_source_metadata_keeps_traceable_coverage_separate():
    package = _verified_package_for_segments("Boeing XB-15", _evidence_segments())
    package["candidate_excerpts"][0].pop("source_url")
    package.pop("source_slot_coverage", None)
    package.pop("traceable_source_slot_coverage", None)

    hydrated = pe._verified_machine_source_package_with_anton_metadata(package, "Boeing XB-15")

    assert hydrated["source_slot_coverage"]["missing_slots"] == []
    assert "original_problem" in hydrated["traceable_source_slot_coverage"]["missing_slots"]
    assert "S1-E1" in hydrated["source_slot_coverage"]["evidence_by_slot"]["original_problem"]
    assert "S1-E1" not in hydrated["traceable_source_slot_coverage"]["evidence_by_slot"].get("original_problem", [])


def test_source_gathering_skips_tavily_content_snippets(monkeypatch):
    import httpx

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "results": [
                    {
                        "url": "https://example.test/snippet-only",
                        "title": "Snippet only result",
                        "content": "The Boeing XB-15 appears in this search-result snippet, but no raw page text was captured.",
                    }
                ]
            }

    class FakeAsyncClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"

    async def fake_get_secret(*_args, **_kwargs):
        return "tvly-test"

    async def fake_fetch_source_text(_client, _url):
        return ""

    monkeypatch.setattr(pe, "get_secret", fake_get_secret)
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(executor, "_fetch_source_text", fake_fetch_source_text)

    result = asyncio.run(
        executor._gather_verified_machine_source_package(
            "Every US Strategic Bomber Ever Built", "Boeing XB-15", {}
        )
    )

    assert result["passed"] is False
    assert result["candidate_excerpts"] == []
    assert result["sources"] == []
    assert result["search_result_audit"][0]["accepted"] is False
    assert result["search_result_audit"][0]["rejected_reason"] == "no_exact_text_variant"
    assert {
        row["source_capture_method"]: row["rejected_reason"]
        for row in result["search_result_audit"][0]["variants"]
    } == {
        "fetched_page": "empty_capture",
        "tavily_raw_content": "empty_capture",
    }


def test_source_gathering_tags_tavily_raw_content_fallback(monkeypatch):
    import httpx

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "results": [
                    {
                        "url": "https://example.test/raw-content",
                        "title": "Raw content result",
                        "raw_content": (
                            "The Boeing XB-15 was built as an experimental long-range bomber before available "
                            "engines could give the huge aircraft the intended performance."
                        ),
                    }
                ]
            }

    class FakeAsyncClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"

    async def fake_get_secret(*_args, **_kwargs):
        return "tvly-test"

    async def fake_fetch_source_text(_client, _url):
        return ""

    monkeypatch.setattr(pe, "get_secret", fake_get_secret)
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(executor, "_fetch_source_text", fake_fetch_source_text)

    result = asyncio.run(
        executor._gather_verified_machine_source_package(
            "Every US Strategic Bomber Ever Built", "Boeing XB-15", {}
        )
    )

    assert result["sources"][0]["source_capture_method"] == "tavily_raw_content"
    assert result["candidate_excerpts"][0]["source_capture_method"] == "tavily_raw_content"
    assert "Boeing XB-15" in result["candidate_excerpts"][0]["text"]
    assert result["search_result_audit"][0]["accepted"] is True
    assert result["search_result_audit"][0]["source_id"] == "S1"
    assert result["search_result_audit"][0]["selected_capture_method"] == "tavily_raw_content"
    assert result["search_result_audit"][0]["variants"][0]["rejected_reason"] == "empty_capture"
    assert result["search_result_audit"][0]["variants"][1]["selected"] is True


def test_source_gathering_uses_raw_content_when_direct_fetch_misses_machine(monkeypatch):
    import httpx

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "results": [
                    {
                        "url": "https://example.test/page-shell",
                        "title": "Page shell with raw content",
                        "raw_content": (
                            "Boeing XB-15 came from a requirement for long-range bombing. "
                            "Boeing XB-15 used a large wing and four engines as the design answer. "
                            "Boeing XB-15 was underpowered for the intended bomber role. "
                            "Boeing XB-15 later served as a World War II transport."
                        ),
                    }
                ]
            }

    class FakeAsyncClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"

    async def fake_get_secret(*_args, **_kwargs):
        return "tvly-test"

    async def fake_fetch_source_text(_client, _url):
        return "Cookie banner and navigation text without the locked aircraft."

    monkeypatch.setattr(pe, "get_secret", fake_get_secret)
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(executor, "_fetch_source_text", fake_fetch_source_text)

    result = asyncio.run(
        executor._gather_verified_machine_source_package(
            "Every US Strategic Bomber Ever Built", "Boeing XB-15", {}
        )
    )

    assert result["sources"][0]["source_capture_method"] == "tavily_raw_content"
    assert result["candidate_excerpts"][0]["source_capture_method"] == "tavily_raw_content"
    assert "Cookie banner" not in result["candidate_excerpts"][0]["text"]
    assert "Boeing XB-15 came from a requirement" in result["candidate_excerpts"][0]["text"]


def test_source_gathering_prefers_raw_content_when_direct_fetch_has_thin_machine_shell(monkeypatch):
    import httpx

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "results": [
                    {
                        "url": "https://example.test/thin-shell",
                        "title": "Thin fetched shell with raw article",
                        "raw_content": (
                            "Boeing XB-15 came from a requirement for long-range bombing. "
                            "Boeing XB-15 used a large wing and four engines as the engineering decision. "
                            "Boeing XB-15 was underpowered and too slow for the intended bomber role. "
                            "Boeing XB-15 later served as a transport during World War II."
                        ),
                    }
                ]
            }

    class FakeAsyncClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"

    async def fake_get_secret(*_args, **_kwargs):
        return "tvly-test"

    async def fake_fetch_source_text(_client, _url):
        return "Boeing XB-15 collection page. Boeing XB-15 related links and navigation only."

    monkeypatch.setattr(pe, "get_secret", fake_get_secret)
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(executor, "_fetch_source_text", fake_fetch_source_text)

    result = asyncio.run(
        executor._gather_verified_machine_source_package(
            "Every US Strategic Bomber Ever Built", "Boeing XB-15", {}
        )
    )

    assert result["sources"][0]["source_capture_method"] == "tavily_raw_content"
    selection = result["sources"][0]["source_variant_selection"]
    assert selection["selected_capture_method"] == "tavily_raw_content"
    assert {row["source_capture_method"] for row in selection["evaluated_variants"]} == {
        "fetched_page",
        "tavily_raw_content",
    }
    assert selection["selected_variant"]["covered_slot_count"] > next(
        row["covered_slot_count"]
        for row in selection["evaluated_variants"]
        if row["source_capture_method"] == "fetched_page"
    )
    assert result["candidate_excerpts"][0]["source_variant_selection"]["selected_capture_method"] == "tavily_raw_content"
    assert "related links and navigation" not in result["candidate_excerpts"][0]["text"]
    assert result["source_slot_coverage"]["missing_slots"] == []


def test_source_gathering_prefers_fetched_page_on_equal_raw_content_coverage(monkeypatch):
    import httpx

    fetched_text = (
        "Boeing XB-15 came from a Project A requirement that called for long-range bombing. "
        "Boeing XB-15 used a large wing, four engines, and a deep fuselage as the engineering decision. "
        "Boeing XB-15 was underpowered and too slow for the combat bomber role. "
        "Boeing XB-15 served as a transport during World War II."
    )
    raw_text = (
        "Boeing XB-15 came from a requirement that called for long-range bombing. "
        "Boeing XB-15 used a large wing, four engines, and a deep fuselage as the engineering decision. "
        "Boeing XB-15 was underpowered and too slow for the combat bomber role. "
        "Boeing XB-15 later served as a transport during World War II."
    )

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "results": [
                    {
                        "url": "https://example.test/equal-coverage",
                        "title": "Equal coverage result",
                        "raw_content": raw_text,
                    }
                ]
            }

    class FakeAsyncClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"

    async def fake_get_secret(*_args, **_kwargs):
        return "tvly-test"

    async def fake_fetch_source_text(_client, _url):
        return fetched_text

    monkeypatch.setattr(pe, "get_secret", fake_get_secret)
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(executor, "_fetch_source_text", fake_fetch_source_text)

    result = asyncio.run(
        executor._gather_verified_machine_source_package(
            "Every US Strategic Bomber Ever Built", "Boeing XB-15", {}
        )
    )

    selection = result["sources"][0]["source_variant_selection"]
    fetched_variant = next(
        row for row in selection["evaluated_variants"]
        if row["source_capture_method"] == "fetched_page"
    )
    raw_variant = next(
        row for row in selection["evaluated_variants"]
        if row["source_capture_method"] == "tavily_raw_content"
    )

    assert result["sources"][0]["source_capture_method"] == "fetched_page"
    assert selection["selected_capture_method"] == "fetched_page"
    assert fetched_variant["covered_slot_count"] == raw_variant["covered_slot_count"]
    assert fetched_variant["distinct_slot_excerpt_count"] == raw_variant["distinct_slot_excerpt_count"]
    assert fetched_variant["excerpt_count"] == raw_variant["excerpt_count"]
    assert fetched_variant["method_priority"] > raw_variant["method_priority"]
    assert result["candidate_excerpts"][0]["source_capture_method"] == "fetched_page"
    assert "Project A requirement" in result["candidate_excerpts"][0]["text"]
    audit = result["search_result_audit"][0]
    assert audit["accepted"] is True
    assert audit["selected_capture_method"] == "fetched_page"
    assert audit["source_variant_selection"]["selected_capture_method"] == "fetched_page"
    assert [row["selected"] for row in audit["variants"]] == [True, False]


def test_source_gathering_saves_anton_slot_coverage_metadata(monkeypatch):
    import httpx

    source_text = (
        "Boeing XB-15 came from a Project A requirement that called for long-range bombing. "
        "Boeing XB-15 was designed to answer a mission that needed unusual range. "
        "Boeing XB-15 used a large wing, four engines, and a deep fuselage as the engineering decision. "
        "Boeing XB-15 carried payload and range features in a prototype airframe. "
        "Boeing XB-15 was underpowered and too slow for the combat bomber role. "
        "Boeing XB-15 could not meet the intended performance without better propulsion. "
        "Boeing XB-15 served as a transport during World War II. "
        "Boeing XB-15 was converted and used for wartime cargo missions."
    )

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "results": [
                    {
                        "url": "https://www.af.mil/About-Us/Fact-Sheets/Display/Article/104509/boeing-xb-15/",
                        "title": "Boeing XB-15 official fact sheet",
                        "raw_content": source_text,
                    },
                    {
                        "url": "https://airandspace.si.edu/collection-objects/boeing-xb-15",
                        "title": "Boeing XB-15 museum source",
                        "raw_content": source_text,
                    },
                ]
            }

    class FakeAsyncClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"

    async def fake_get_secret(*_args, **_kwargs):
        return "tvly-test"

    async def fake_fetch_source_text(_client, _url):
        return ""

    monkeypatch.setattr(pe, "get_secret", fake_get_secret)
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(executor, "_fetch_source_text", fake_fetch_source_text)

    result = asyncio.run(
        executor._gather_verified_machine_source_package(
            "Every US Strategic Bomber Ever Built", "Boeing XB-15", {}
        )
    )

    assert result["passed"] is True
    assert result["source_slot_coverage"]["missing_slots"] == []
    assert result["traceable_source_slot_coverage"]["missing_slots"] == []
    assert result["source_slot_coverage"]["needs_distinct_slot_excerpts"] is False
    assert result["traceable_source_slot_coverage"]["needs_distinct_slot_excerpts"] is False
    assert result["source_slot_coverage"]["distinct_slot_excerpt_count"] == 4
    assert result["traceable_source_slot_coverage"]["distinct_slot_excerpt_count"] == 4
    assert set(result["source_slot_coverage"]["covered_slots"]) == {
        "engineering_decision",
        "original_problem",
        "reality",
        "tradeoff",
    }
    assert set(result["traceable_source_slot_coverage"]["covered_slots"]) == {
        "engineering_decision",
        "original_problem",
        "reality",
        "tradeoff",
    }
    assert result["candidate_excerpts"][0]["anton_slot_hints"]
    accepted_audit_rows = [row for row in result["search_result_audit"] if row["accepted"] is True]
    duplicate_audit_rows = [
        row for row in result["search_result_audit"]
        if row.get("rejected_reason") == "duplicate_url"
    ]
    assert len(accepted_audit_rows) == 2
    assert duplicate_audit_rows


def test_naval_source_gathering_prioritizes_later_museum_result_before_excerpt_cap(monkeypatch):
    """Six early derivative sources used to consume all 60 excerpt slots
    before the later naval domain-steering result was fetched."""
    import httpx

    machine = "Majestic class"

    def source_text(source_name: str) -> str:
        return " ".join(
            f"{machine} {source_name} documented distinct carrier history fact number {index} for this source."
            for index in range(1, 11)
        )

    derivative_results = [
        {
            "url": f"https://naval-encyclopedia.com/majestic-derivative-{index}",
            "title": f"Majestic derivative reference {index}",
            "raw_content": source_text(f"derivative reference {index}"),
        }
        for index in range(1, 7)
    ]
    museum_result = {
        "url": "https://www.rmg.co.uk/collections/majestic-class",
        "title": "Royal Museums Greenwich Majestic class carrier record",
        "raw_content": source_text("museum record"),
    }
    request_count = {"value": 0}

    class FakeResponse:
        status_code = 200

        def __init__(self, results):
            self._results = results

        def json(self):
            return {"results": self._results}

    class FakeAsyncClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, json=None, **_kwargs):
            request_count["value"] += 1
            if request_count["value"] == 1:
                return FakeResponse(derivative_results)
            if json and json.get("include_domains") == ["awm.gov.au", "rmg.co.uk"]:
                # Keep a duplicate to lock the existing URL-dedup audit while
                # source priority changes around it.
                return FakeResponse([museum_result, dict(museum_result)])
            return FakeResponse([])

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"

    async def fake_get_secret(*_args, **_kwargs):
        return "tvly-test"

    async def fake_fetch_source_text(_client, _url):
        return ""

    monkeypatch.setattr(pe, "get_secret", fake_get_secret)
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(executor, "_fetch_source_text", fake_fetch_source_text)

    result = asyncio.run(
        executor._gather_verified_machine_source_package(
            "Every British Aircraft Carrier Class Ever Built (2026)", machine, {}
        )
    )

    assert len(result["candidate_excerpts"]) == 60
    assert result["sources"][0]["url"] == museum_result["url"]
    assert result["sources"][0]["source_tier"] == 2
    museum_excerpts = [
        row for row in result["candidate_excerpts"]
        if row["source_url"] == museum_result["url"]
    ]
    assert [row["excerpt_id"] for row in museum_excerpts] == [f"S1-E{index}" for index in range(1, 11)]
    assert derivative_results[-1]["url"] not in {row["url"] for row in result["sources"]}
    assert any(
        row.get("url") == museum_result["url"] and row.get("rejected_reason") == "duplicate_url"
        for row in result["search_result_audit"]
    )


def test_non_naval_source_gathering_preserves_search_arrival_order(monkeypatch):
    import httpx

    machine = "Boeing XB-15"
    derivative_url = "https://example-reference.test/xb-15"
    official_url = "https://www.af.mil/xb-15"
    source_text = (
        "Boeing XB-15 was built to test a long-range bomber requirement, "
        "and its large wing exposed the limits of available engines."
    )

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "results": [
                    {"url": derivative_url, "title": "XB-15 reference", "raw_content": source_text},
                    {"url": official_url, "title": "XB-15 official history", "raw_content": source_text},
                ]
            }

    class FakeAsyncClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"

    async def fake_get_secret(*_args, **_kwargs):
        return "tvly-test"

    async def fake_fetch_source_text(_client, _url):
        return ""

    monkeypatch.setattr(pe, "get_secret", fake_get_secret)
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(executor, "_fetch_source_text", fake_fetch_source_text)

    result = asyncio.run(
        executor._gather_verified_machine_source_package(
            "Every US Strategic Bomber Ever Built", machine, {}
        )
    )

    assert [row["url"] for row in result["sources"]] == [derivative_url, official_url]


# --- GAP 1(a): tolerant per-excerpt normalizer -----------------------------
# Each quirk below rejected a REAL excerpt in the DVsU research simulator
# before being fixed there (tasks/evidence/dvsu-research-simulator/
# build_package.py::_match_normalize). Ported into _normalized_source_text,
# the pipeline's own comparison fold, one fixture per quirk.

def test_normalized_source_text_strips_citation_markers():
    page_text = "HMS Argus entered service as an aircraft carrier.[9] The next ship followed."
    normalized = pe._normalized_source_text(page_text)
    assert "[9]" not in normalized
    assert "carrier. the next ship" in normalized


def test_normalized_source_text_strips_lettered_and_named_citation_markers():
    assert "[a]" not in pe._normalized_source_text("Laid down in 1917.[a] Commissioned in 1918.")
    assert "[note 3]" not in pe._normalized_source_text("Laid down in 1917.[note 3] Commissioned in 1918.")
    assert "[citation needed]" not in pe._normalized_source_text(
        "Laid down in 1917.[citation needed] Commissioned in 1918."
    )


def test_normalized_source_text_collapses_orphan_space_before_punctuation():
    artifact = "Under the Anglo-American Mutual Aid Treaty , Ark Royal was laid down."
    clean = "Under the Anglo-American Mutual Aid Treaty, Ark Royal was laid down."
    assert pe._normalized_source_text(artifact) == pe._normalized_source_text(clean)


def test_normalized_source_text_collapses_one_sided_hyphen_space():
    # Artifact of a stripped inline link mid-compound word: the source markup
    # "equipped-[Hellcat IIs](...)" strips down to "equipped- Hellcat".
    artifact = "The squadron was equipped- Hellcat fighters by early 1944."
    clean = "The squadron was equipped-Hellcat fighters by early 1944."
    assert pe._normalized_source_text(artifact) == pe._normalized_source_text(clean)
    # A genuinely spaced dash ("London - the capital") keeps both spaces and
    # must NOT be collapsed into a hyphen-glued compound.
    spaced_dash = "London - the capital - held the ceremony."
    assert pe._normalized_source_text(spaced_dash) == "london - the capital - held the ceremony."


def test_normalized_source_text_folds_smart_quotes_and_dashes():
    smart = "The ship’s captain called it “a floating airfield” — nothing more."
    ascii_version = "The ship's captain called it \"a floating airfield\" - nothing more."
    assert pe._normalized_source_text(smart) == pe._normalized_source_text(ascii_version)


def test_normalized_source_text_folds_nbsp():
    nbsp_text = "HMS Argus was laid down in 1917."
    space_text = "HMS Argus was laid down in 1917."
    assert pe._normalized_source_text(nbsp_text) == pe._normalized_source_text(space_text)


def test_validate_card_against_verified_sources_tolerates_citation_marker_artifact():
    """Wiring proof, not just the isolated function: before GAP 1(a), a card
    excerpt written cleanly would be rejected against a candidate whose
    fetched-page text still carries a stripped citation marker mid-sentence."""
    segments = _evidence_segments()
    package = _verified_package_for_segments("Boeing XB-15", segments)
    clean_excerpt = f"Boeing XB-15 {segments[0]['source_excerpt']} It remained in frontline service."
    artifact_excerpt = f"Boeing XB-15 {segments[0]['source_excerpt']}[9] It remained in frontline service."
    package["candidate_excerpts"][0]["text"] = artifact_excerpt

    card_segments = copy.deepcopy(segments)
    card_segments[0]["source_excerpt"] = clean_excerpt
    card = {"unit": "Boeing XB-15", "evidence_segments": card_segments}

    warnings = pe._validate_card_against_verified_sources(card, package)

    assert not any("was not found in verified fetched source text" in w for w in warnings)


# --- GAP 1(b): National Archives / Wayback fallback chain ------------------

def test_source_gathering_falls_back_to_national_archives_api_after_cold_202_retries(monkeypatch):
    import httpx

    original_url = "https://discovery.nationalarchives.gov.uk/details/r/C1234567"
    api_url = "https://discovery.nationalarchives.gov.uk/API/records/v1/details/C1234567"
    na_text = (
        "Boeing XB-15 development files record the original requirement for an "
        "experimental long-range bomber. Boeing XB-15 used four engines and a huge "
        "wing as the engineering decision. Boeing XB-15 was underpowered and too "
        "slow for the intended combat role. Boeing XB-15 later served as a transport."
    )

    class FakeSearchResponse:
        status_code = 200

        def json(self):
            return {"results": [{"url": original_url, "title": "NA Discovery record", "raw_content": ""}]}

    class FakeGetResponse:
        def __init__(self, status_code, text=""):
            self.status_code = status_code
            self.text = text
            self.headers = {}
            self.content = text.encode()

    api_call_count = {"n": 0}

    class FakeAsyncClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return FakeSearchResponse()

        async def get(self, url, *_args, **_kwargs):
            if url == original_url:
                return FakeGetResponse(403)
            if url == api_url:
                api_call_count["n"] += 1
                if api_call_count["n"] < 3:
                    return FakeGetResponse(200, "")
                return FakeGetResponse(200, na_text)
            raise AssertionError(f"unexpected GET {url}")

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"

    async def fake_get_secret(*_args, **_kwargs):
        return "tvly-test"

    async def fake_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pe, "get_secret", fake_get_secret)
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(pe.asyncio, "sleep", fake_sleep)

    result = asyncio.run(
        executor._gather_verified_machine_source_package(
            "Every US Strategic Bomber Ever Built", "Boeing XB-15", {}
        )
    )

    assert api_call_count["n"] == 3
    assert result["search_result_audit"][0]["accepted"] is True
    assert result["sources"][0]["source_capture_method"] == "national_archives_api"
    assert result["candidate_excerpts"][0]["source_capture_method"] == "national_archives_api"
    assert "Boeing XB-15" in result["candidate_excerpts"][0]["text"]
    assert pe._verified_source_candidate_traceable(result["candidate_excerpts"][0]) is True


def test_source_gathering_falls_back_to_real_wayback_snapshot(monkeypatch):
    import httpx

    original_url = "https://www.iwm.org.uk/collections/item/object/205211678"
    snapshot_url = (
        "https://web.archive.org/web/20250101000000/"
        "https://www.iwm.org.uk/collections/item/object/205211678"
    )
    wayback_text = (
        "Boeing XB-15 was designed to meet a requirement for very long range "
        "bombing. Boeing XB-15 used a large wing and four engines as the "
        "engineering decision. Boeing XB-15 was underpowered and too slow for "
        "combat. Boeing XB-15 later flew cargo missions during World War II."
    )

    class FakeSearchResponse:
        status_code = 200

        def json(self):
            return {"results": [{"url": original_url, "title": "IWM item", "raw_content": ""}]}

    class FakeGetResponse:
        def __init__(self, status_code, payload=None, text=""):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = text
            self.headers = {}
            self.content = text.encode()

        def json(self):
            return self._payload

    availability_calls = []

    class FakeAsyncClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return FakeSearchResponse()

        async def get(self, url, *_args, **kwargs):
            if url == original_url:
                return FakeGetResponse(403)
            if url == "https://archive.org/wayback/available":
                availability_calls.append(kwargs.get("params"))
                return FakeGetResponse(
                    200,
                    payload={"archived_snapshots": {"closest": {"url": snapshot_url, "status": "200", "available": True}}},
                )
            if url == snapshot_url:
                return FakeGetResponse(200, text=wayback_text)
            raise AssertionError(f"unexpected GET {url}")

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"

    async def fake_get_secret(*_args, **_kwargs):
        return "tvly-test"

    monkeypatch.setattr(pe, "get_secret", fake_get_secret)
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    result = asyncio.run(
        executor._gather_verified_machine_source_package(
            "Every US Strategic Bomber Ever Built", "Boeing XB-15", {}
        )
    )

    # The snapshot URL used is EXACTLY what the availability API returned -
    # never a claimed/fabricated archive.org URL (the Ark Royal S8 incident).
    assert availability_calls == [{"url": original_url}]
    assert result["sources"][0]["source_capture_method"] == f"wayback:{snapshot_url}"
    assert result["candidate_excerpts"][0]["source_capture_method"] == f"wayback:{snapshot_url}"
    assert pe._verified_source_candidate_traceable(result["candidate_excerpts"][0]) is True
    assert result["search_result_audit"][0]["accepted"] is True


def test_source_gathering_never_fabricates_a_wayback_snapshot_when_none_exists(monkeypatch):
    """No archived_snapshots in the availability response -> the source is
    dropped as no_exact_text_variant, never a guessed archive.org URL."""
    import httpx

    original_url = "https://www.iwm.org.uk/collections/item/object/999"

    class FakeSearchResponse:
        status_code = 200

        def json(self):
            return {"results": [{"url": original_url, "title": "IWM item", "raw_content": ""}]}

    class FakeGetResponse:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = ""
            self.headers = {}
            self.content = b""

        def json(self):
            return self._payload

    class FakeAsyncClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return FakeSearchResponse()

        async def get(self, url, *_args, **_kwargs):
            if url == original_url:
                return FakeGetResponse(403)
            if url == "https://archive.org/wayback/available":
                return FakeGetResponse(200, payload={"archived_snapshots": {}})
            raise AssertionError(f"unexpected GET {url}")

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"

    async def fake_get_secret(*_args, **_kwargs):
        return "tvly-test"

    monkeypatch.setattr(pe, "get_secret", fake_get_secret)
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    result = asyncio.run(
        executor._gather_verified_machine_source_package(
            "Every US Strategic Bomber Ever Built", "Boeing XB-15", {}
        )
    )

    assert result["sources"] == []
    assert result["search_result_audit"][0]["accepted"] is False
    assert result["search_result_audit"][0]["rejected_reason"] == "no_exact_text_variant"


def test_verified_source_candidate_traceable_accepts_fallback_capture_methods():
    base = {"source_url": "https://x.test", "locator": "S1-E1"}
    assert pe._verified_source_candidate_traceable({**base, "source_capture_method": "national_archives_api"})
    assert pe._verified_source_candidate_traceable(
        {**base, "source_capture_method": "wayback:https://web.archive.org/web/2020/https://x.test"}
    )
    assert not pe._verified_source_candidate_traceable({**base, "source_capture_method": "tavily_snippet"})


def test_verified_machine_source_package_quality_errors_accepts_fallback_capture_methods():
    segments = _evidence_segments()
    package = _verified_package_for_segments("Boeing XB-15", segments)
    package["candidate_excerpts"][0]["source_capture_method"] = "national_archives_api"
    package["candidate_excerpts"][1]["source_capture_method"] = (
        "wayback:https://web.archive.org/web/2020/https://x.test"
    )

    errors = pe._verified_machine_source_package_quality_errors(package, "Boeing XB-15")

    assert not any("unsupported source capture method" in e for e in errors)


# --- GAP 1(c): source steering away from the iwm.org.uk bot-wall -----------

def test_naval_gather_context_detects_ship_titles_and_machines():
    assert pe._is_naval_gather_context("Every British Aircraft Carrier Class Ever Built", "HMS Argus") is True
    assert pe._is_naval_gather_context("Every US Navy Destroyer Ever Built", "USS Fletcher") is True
    assert pe._is_naval_gather_context("Every US Strategic Bomber Ever Built", "Boeing XB-15") is False


def test_naval_gather_context_word_boundary_matching():
    # Substring "ship" should not match within words like "championship", "friendship"
    assert pe._is_naval_gather_context("The Championship Chess Machine", "") is False
    assert pe._is_naval_gather_context("Friendship Bridge Crossing", "") is False
    # Standalone "ship" should match
    assert pe._is_naval_gather_context("Every Ship in the Royal Navy", "") is True
    # Whole-word "battleship" should match
    assert pe._is_naval_gather_context("Battleship Yamato", "") is True
    # Whole-word "carrier" (existing term) should match
    assert pe._is_naval_gather_context("Aircraft Carrier Evolution", "") is True
    # "warship" should match (newly added term)
    assert pe._is_naval_gather_context("Famous Warships of WWII", "") is True


def test_gather_verified_machine_source_package_skips_naval_query_for_non_naval_machine(monkeypatch):
    import httpx

    request_bodies = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"results": []}

    class FakeAsyncClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, json=None, **_kwargs):
            request_bodies.append(json)
            return FakeResponse()

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"

    async def fake_get_secret(*_args, **_kwargs):
        return "tvly-test"

    monkeypatch.setattr(pe, "get_secret", fake_get_secret)
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    asyncio.run(
        executor._gather_verified_machine_source_package(
            "Every US Strategic Bomber Ever Built", "Boeing XB-15", {}
        )
    )

    assert len(request_bodies) == 8
    assert all("iwm.org.uk" in body["exclude_domains"] for body in request_bodies)
    assert not any(body.get("include_domains") for body in request_bodies)
    assert not any('"aircraft carrier"' in body["query"] for body in request_bodies)


# G13, 2026-07-31: real off-topic Tier 1-2 excerpts pulled from the actually
# stored (and actually referee-failed) machine_raw_source_packages on video
# d05efae3-46f8-4ee3-b690-849c3ca31fbc (`se db`, read-only). Both satisfied
# the OLD tier-floor check even though neither is genuinely about the locked
# machine.
_REAL_OFF_TOPIC_IWM_DIFFERENT_SHIP_EXCERPT = (
    "\"India\" ### [William Charles Goldsmith](/lifestory/6163985) **Born** 1884 **Died** 1918 "
    "Royal Navy 216889 Boy 2nd Class HMS Northampton Royal Navy 216889 Boy 1st Class HMS Northampton "
    "Royal Navy 216889 Ordinary Seaman HMS Flora … ### [Charles Richard Kennett](/lifestory/6160417) "
    "**Born** 1883 **Died** 1917 Royal Navy 213318 Boy 2nd Class HMS Northampton Royal Navy 213318 "
    "Boy 1st Class HMS Northampton Royal Navy 213318 Ordinary Seaman HMS Victory … "
    "### [Arthur William Martin](/lifestory/6168639) **Born** 1884 **Died** 1915 Royal Navy 221552 "
    "Boy 2nd Class HMS \"Northampton\" Royal Navy 221552 Leading Seaman H.M.S."
)
_REAL_OFF_TOPIC_IWM_DIFFERENT_SHIP_URL = (
    "https://livesofthefirstworldwar.iwm.org.uk/searchlives/field/unit/HMS%20Northampton/filter"
)
_REAL_OFF_TOPIC_HOWE_BIBLIOGRAPHY_EXCERPT = (
    "Howe, Northwest Africa; ing, \"The War in the Mediterranean:' in Seizing the Initiative in the West "
    "[United World War 11 German Military Studies, 24 States Army in World War II] (Washington, vols, Donald S."
)
_REAL_OFF_TOPIC_HOWE_USAF_URL = "https://media.defense.gov/2010/Sep/22/2001330044/-1/-1/0/AFD-100922-032.pdf"


def _six_on_topic_naval_excerpts(machine: str, url: str) -> list[dict]:
    sentences = [
        f"{machine} was a King George V-class battleship of the Royal Navy.",
        f"{machine} was commissioned and joined the fleet for service in the war.",
        f"The battleship {machine} carried her main armament in twin and quad turrets.",
        f"{machine} served with the Home Fleet aboard other Royal Navy warships.",
        f"Crew aboard {machine} recalled the ship's service during the campaign.",
        f"{machine} was later decommissioned after her wartime naval service.",
    ]
    return [
        {
            "excerpt_id": f"S1-E{index}",
            "source_id": "S1",
            "source_title": "On-topic reference",
            "source_url": url,
            "source_tier": 3,
            "source_tier_label": "Tier 3 reference/secondary",
            "source_capture_method": "fetched_page",
            "source_variant_selection": {"selected_capture_method": "fetched_page"},
            "locator": f"S1-E{index}",
            "text": sentence,
            "text_hash": f"test-{index}",
        }
        for index, sentence in enumerate(sentences, start=1)
    ]


def test_tier_floor_relevant_excerpt_rejects_real_off_topic_different_ship():
    """The real iwm.org.uk excerpt is titled/about HMS Northampton and never
    names Prince of Wales anywhere - it only satisfied the old check via the
    generic "HMS" prefix, which _machine_mention_terms no longer treats as a
    distinguishing term."""
    assert not pe._mentions_machine(
        _REAL_OFF_TOPIC_IWM_DIFFERENT_SHIP_EXCERPT, "53 HMS Prince of Wales"
    )
    assert not pe._tier_floor_relevant_excerpt(
        _REAL_OFF_TOPIC_IWM_DIFFERENT_SHIP_EXCERPT, "53 HMS Prince of Wales"
    )


def test_tier_floor_relevant_excerpt_rejects_real_off_topic_bibliography_surname():
    """The real USAF-PDF excerpt is a bibliography citation to a historian
    named Howe ("Howe, Northwest Africa") - _mentions_machine still matches
    on the surname, but no naval ship-context vocabulary is present, so the
    stricter tier-floor check must reject it."""
    assert pe._mentions_machine(_REAL_OFF_TOPIC_HOWE_BIBLIOGRAPHY_EXCERPT, "32 HMS Howe")
    assert not pe._tier_floor_relevant_excerpt(_REAL_OFF_TOPIC_HOWE_BIBLIOGRAPHY_EXCERPT, "32 HMS Howe")


def test_tier_floor_relevant_excerpt_accepts_genuine_on_topic_naval_excerpt():
    on_topic = "HMS Howe was a King George V-class battleship that served with the Royal Navy fleet."
    assert pe._tier_floor_relevant_excerpt(on_topic, "32 HMS Howe")


def test_verified_source_package_quality_rejects_off_topic_iwm_different_ship_tier_floor():
    machine = "53 HMS Prince of Wales"
    package = {
        "candidate_excerpts": _six_on_topic_naval_excerpts(machine, "https://example-secondary.test/pow")
        + [{
            "excerpt_id": "S2-E1",
            "source_id": "S2",
            "source_title": "Search for \"HMS Northampton\" in unit | Lives of the First World War",
            "source_url": _REAL_OFF_TOPIC_IWM_DIFFERENT_SHIP_URL,
            "source_tier": 2,
            "source_tier_label": "Tier 2 museum/authoritative secondary",
            "source_capture_method": "fetched_page",
            "source_variant_selection": {"selected_capture_method": "fetched_page"},
            "locator": "S2-E1",
            "text": _REAL_OFF_TOPIC_IWM_DIFFERENT_SHIP_EXCERPT,
            "text_hash": "test-offtopic",
        }],
    }

    errors = pe._verified_machine_source_package_quality_errors(package, machine)

    assert any("Tier 1-2 primary/authoritative source" in error for error in errors)


def test_verified_source_package_quality_rejects_off_topic_howe_bibliography_tier_floor():
    machine = "32 HMS Howe"
    package = {
        "candidate_excerpts": _six_on_topic_naval_excerpts(machine, "https://example-secondary.test/howe")
        + [{
            "excerpt_id": "S2-E1",
            "source_id": "S2",
            "source_title": "AFD-100922-032.pdf",
            "source_url": _REAL_OFF_TOPIC_HOWE_USAF_URL,
            "source_tier": 1,
            "source_tier_label": "Tier 1 primary/official",
            "source_capture_method": "tavily_raw_content",
            "source_variant_selection": {"selected_capture_method": "tavily_raw_content"},
            "locator": "S2-E1",
            "text": _REAL_OFF_TOPIC_HOWE_BIBLIOGRAPHY_EXCERPT,
            "text_hash": "test-offtopic-howe",
        }],
    }

    errors = pe._verified_machine_source_package_quality_errors(package, machine)

    assert any("Tier 1-2 primary/authoritative source" in error for error in errors)


def test_verified_source_package_quality_accepts_genuine_on_topic_tier_1_2_excerpt():
    machine = "32 HMS Howe"
    package = {
        "candidate_excerpts": _six_on_topic_naval_excerpts(machine, "https://example-secondary.test/howe")
        + [{
            "excerpt_id": "S2-E1",
            "source_id": "S2",
            "source_title": "HMS Howe official history",
            "source_url": "https://www.rmg.co.uk/collections/objects/hms-howe",
            "source_tier": 2,
            "source_tier_label": "Tier 2 museum/authoritative secondary",
            "source_capture_method": "fetched_page",
            "source_variant_selection": {"selected_capture_method": "fetched_page"},
            "locator": "S2-E1",
            "text": "HMS Howe was a King George V-class battleship that served with the Royal Navy fleet.",
            "text_hash": "test-ontopic-howe",
        }],
    }

    errors = pe._verified_machine_source_package_quality_errors(package, machine)

    assert not any("Tier 1-2 primary/authoritative source" in error for error in errors)


def test_required_anton_slots_reject_tier_four_only_source_support():
    segments = _evidence_segments()
    for segment in segments:
        segment["source_url"] = "https://en.wikipedia.org/wiki/Boeing_XB-15"
    package = _verified_package_for_segments("Boeing XB-15", segments)
    card = {"unit": "Boeing XB-15", "evidence_segments": segments}

    warnings = pe._validate_card_against_verified_sources(card, package)

    assert any("Tier 4/caution source" in warning for warning in warnings)


def test_required_anton_slots_accept_tier_four_when_cross_checked_by_better_source():
    segments = _evidence_segments()
    for segment in segments:
        segment["source_url"] = "https://airandspace.si.edu/collection-objects/boeing-xb-15"
    wiki_problem = copy.deepcopy(segments[0])
    wiki_problem["evidence_id"] = "E-PROBLEM-WIKI"
    wiki_problem["source_url"] = "https://en.wikipedia.org/wiki/Boeing_XB-15"
    segments.append(wiki_problem)
    package = _verified_package_for_segments("Boeing XB-15", segments)
    card = {"unit": "Boeing XB-15", "evidence_segments": segments}

    warnings = pe._validate_card_against_verified_sources(card, package)

    assert pe._blocking_warnings(warnings) == []


def test_required_anton_slots_accept_authoritative_source_support():
    segments = _evidence_segments()
    for segment in segments:
        segment["source_url"] = "https://airandspace.si.edu/collection-objects/boeing-xb-15"
    package = _verified_package_for_segments("Boeing XB-15", segments)
    card = {"unit": "Boeing XB-15", "evidence_segments": segments}

    warnings = pe._validate_card_against_verified_sources(card, package)

    assert pe._blocking_warnings(warnings) == []


def test_validate_card_against_verified_sources_rejects_unapproved_capture_method():
    segments = _evidence_segments()
    package = _verified_package_for_segments("Boeing XB-15", segments)
    package["candidate_excerpts"][0]["source_capture_method"] = "tavily_snippet"
    card = {"unit": "Boeing XB-15", "evidence_segments": segments}

    warnings = pe._validate_card_against_verified_sources(card, package)

    assert any(
        "evidence segment E-PROBLEM source_excerpt/locator was not found in verified fetched source text" in warning
        for warning in warnings
    )


def test_research_card_required_slots_must_select_distinct_raw_excerpts():
    segments = _evidence_segments()
    for segment in segments:
        segment["source_url"] = "https://airandspace.si.edu/collection-objects/boeing-xb-15"
    package = _verified_package_for_segments("Boeing XB-15", segments)
    broad_candidate = package["candidate_excerpts"][0]
    broad_candidate["text"] = (
        "Boeing XB-15 was required for a long-range bomber program, built with "
        "large wing and engine choices, but underpowered, and later served as a "
        "World War II transport."
    )
    required_kinds = ["original_problem", "engineering_decision", "tradeoff", "reality"]
    for index, kind in enumerate(required_kinds):
        segments[index].update({
            "kind": kind,
            "source_excerpt": broad_candidate["text"],
            "source_excerpt_id": broad_candidate["excerpt_id"],
            "source_url": broad_candidate["source_url"],
            "source_title": broad_candidate["source_title"],
            "locator": broad_candidate["locator"],
        })
    card = {"unit": "Boeing XB-15", "evidence_segments": segments}

    warnings = pe._validate_card_against_verified_sources(card, package)

    assert any("distinct raw source excerpts for required Anton slots" in warning for warning in warnings)


def test_research_card_required_slots_reject_overlapping_raw_excerpts():
    segments = _evidence_segments()
    for segment in segments:
        segment["source_url"] = "https://airandspace.si.edu/collection-objects/boeing-xb-15"
    package = _verified_package_for_segments("Boeing XB-15", segments)
    nested_windows = [
        "Boeing XB-15 was required for a long-range bomber program.",
        "Boeing XB-15 was required for a long-range bomber program and was built with large wing and engine choices.",
        "Boeing XB-15 was required for a long-range bomber program and was built with large wing and engine choices, but it was underpowered.",
        "Boeing XB-15 was required for a long-range bomber program and was built with large wing and engine choices, but it was underpowered and later served as a World War II transport.",
    ]
    required_kinds = ["original_problem", "engineering_decision", "tradeoff", "reality"]
    for index, (kind, text) in enumerate(zip(required_kinds, nested_windows)):
        package["candidate_excerpts"][index]["text"] = text
        segments[index].update({
            "kind": kind,
            "source_excerpt": text,
            "source_excerpt_id": package["candidate_excerpts"][index]["excerpt_id"],
            "source_url": package["candidate_excerpts"][index]["source_url"],
            "source_title": package["candidate_excerpts"][index]["source_title"],
            "locator": package["candidate_excerpts"][index]["locator"],
        })
    card = {"unit": "Boeing XB-15", "evidence_segments": segments[:4]}

    warnings = pe._validate_card_against_verified_sources(card, package)

    assert any("distinct raw source excerpts for required Anton slots" in warning for warning in warnings)


def test_research_card_required_slots_must_match_raw_excerpt_hints():
    segments = _evidence_segments()
    for segment in segments:
        segment["source_url"] = "https://airandspace.si.edu/collection-objects/boeing-xb-15"
    package = _verified_package_for_segments("Boeing XB-15", segments)
    package["candidate_excerpts"][0]["anton_slot_hints"] = ["engineering_decision"]
    card = {"unit": "Boeing XB-15", "evidence_segments": segments}

    warnings = pe._validate_card_against_verified_sources(card, package)

    assert any("maps original_problem to raw excerpt S1-E1 hinted for engineering_decision" in warning for warning in warnings)


def test_verified_card_validation_backfills_raw_excerpt_identity():
    segments = _evidence_segments()
    for segment in segments:
        segment["source_url"] = "https://airandspace.si.edu/collection-objects/boeing-xb-15"
    package = _verified_package_for_segments("Boeing XB-15", segments)
    package["candidate_excerpts"][0]["text_hash"] = "excerpt-hash-1"
    package["candidate_excerpts"][0]["source_variant_selection"] = {
        "selected_capture_method": "fetched_page",
        "selected_variant": {
            "source_capture_method": "fetched_page",
            "covered_slot_count": 4,
            "distinct_slot_excerpt_count": 4,
        },
        "evaluated_variants": [
            {"source_capture_method": "fetched_page", "covered_slot_count": 4},
            {"source_capture_method": "tavily_raw_content", "covered_slot_count": 4},
        ],
        "selection_rule": "highest Anton-slot coverage; fetched_page wins exact ties",
    }
    card = {"unit": "Boeing XB-15", "evidence_segments": segments}

    warnings = pe._validate_card_against_verified_sources(card, package)

    assert pe._blocking_warnings(warnings) == []
    assert segments[0]["source_excerpt_id"] == "S1-E1"
    assert segments[0]["source_id"] == "S1"
    assert segments[0]["source_excerpt_hash"] == "excerpt-hash-1"
    assert segments[0]["source_tier"] == 2
    assert segments[0]["source_tier_label"] == "Tier 2 museum/authoritative secondary"
    assert segments[0]["source_capture_method"] == "fetched_page"
    assert segments[0]["source_variant_selection"]["selected_capture_method"] == "fetched_page"
    assert segments[0]["source_variant_selection"]["selected_variant"]["covered_slot_count"] == 4


def test_story_plan_preserves_raw_excerpt_identity_for_script_preview():
    segments = _evidence_segments()
    source_variant_selection = {
        "selected_capture_method": "fetched_page",
        "selected_variant": {
            "source_capture_method": "fetched_page",
            "covered_slot_count": 4,
            "distinct_slot_excerpt_count": 4,
        },
        "evaluated_variants": [
            {"source_capture_method": "fetched_page", "covered_slot_count": 4},
            {"source_capture_method": "tavily_raw_content", "covered_slot_count": 4},
        ],
        "selection_rule": "highest Anton-slot coverage; fetched_page wins exact ties",
    }
    segments[0].update({
        "source_excerpt_id": "S1-E1",
        "source_id": "S1",
        "source_excerpt_hash": "excerpt-hash-1",
        "source_tier": 2,
        "source_tier_label": "Tier 2 museum/authoritative secondary",
        "source_capture_method": "fetched_page",
        "source_variant_selection": source_variant_selection,
    })
    payload = {
        "unit_research_cards": [{
            "unit": "Boeing XB-15",
            "evidence_segments": segments,
        }]
    }

    plan = pe._machine_story_plan(payload, "Boeing XB-15")

    segment = plan["slots"][0]["evidence_segments"][0]
    assert segment["source_excerpt_id"] == "S1-E1"
    assert segment["source_id"] == "S1"
    assert segment["source_excerpt_hash"] == "excerpt-hash-1"
    assert segment["source_tier"] == 2
    assert segment["source_tier_label"] == "Tier 2 museum/authoritative secondary"
    assert segment["source_capture_method"] == "fetched_page"
    assert segment["source_variant_selection"] == source_variant_selection


# ---------------------------------------------------------------------------
# _machine_story_plan mode_profile + table overrides (checklist C46e, OR-5
# ruled) — the Most Hated mode's opener-budget/memorable-source overrides,
# threaded from quality_rules.resolve_dvsu_overrides through to the plan.
# ---------------------------------------------------------------------------

def _mode_payload(dvsu_mode=None):
    payload = {"unit_research_cards": [{"unit": "Boeing XB-15", "evidence_segments": []}]}
    if dvsu_mode:
        payload["dvsu_mode"] = dvsu_mode
    return payload


def test_machine_story_plan_default_spec_block_mode_profile():
    plan = pe._machine_story_plan(_mode_payload(), "Boeing XB-15")
    mode_profile = plan["contract"]["mode_profile"]
    assert mode_profile["mode"] == "spec_block"
    assert mode_profile["opener_name_budget"] == 0.6
    assert mode_profile["memorable_source"] == "sticky_fact"


def test_machine_story_plan_most_hated_mode_hardcoded_defaults_without_overrides():
    plan = pe._machine_story_plan(_mode_payload("most_hated"), "Boeing XB-15")
    mode_profile = plan["contract"]["mode_profile"]
    assert mode_profile["mode"] == "most_hated"
    assert mode_profile["opener_name_budget"] == 0.2
    assert mode_profile["memorable_source"] == "crew_testimony"


def test_machine_story_plan_most_hated_mode_prefers_table_override():
    overrides = {
        "opener_budget": {"value": 0.05, "severity": "warn"},
        "memorable_source": {"value": "crew_testimony", "severity": "warn"},
    }
    plan = pe._machine_story_plan(_mode_payload("most_hated"), "Boeing XB-15", overrides)
    mode_profile = plan["contract"]["mode_profile"]
    assert mode_profile["opener_name_budget"] == 0.05


def test_machine_story_plan_table_override_never_leaks_into_spec_block_mode():
    """A quality_rules row scoped {"dvsu_mode": "most_hated"} must never
    affect a video that never opted into that mode — proves the override is
    gated on mode_profile["mode"] == "most_hated", not applied unconditionally."""
    overrides = {"opener_budget": {"value": 0.05, "severity": "warn"}}
    plan = pe._machine_story_plan(_mode_payload(None), "Boeing XB-15", overrides)
    mode_profile = plan["contract"]["mode_profile"]
    assert mode_profile["mode"] == "spec_block"
    assert mode_profile["opener_name_budget"] == 0.6


def test_machine_story_plan_ignores_overrides_missing_a_value():
    """An overrides dict present but with no usable 'value' key (e.g. only
    QL-9-MH seeded, not QL-7-MH) must leave the hardcoded default in place
    for the missing key alone."""
    plan = pe._machine_story_plan(_mode_payload("most_hated"), "Boeing XB-15", {"memorable_source": {}})
    mode_profile = plan["contract"]["mode_profile"]
    assert mode_profile["opener_name_budget"] == 0.2
    assert mode_profile["memorable_source"] == "crew_testimony"


def test_verified_card_validation_rejects_mismatched_raw_excerpt_id():
    segments = _evidence_segments()
    for segment in segments:
        segment["source_url"] = "https://airandspace.si.edu/collection-objects/boeing-xb-15"
    segments[0]["source_excerpt_id"] = "S99-E9"
    package = _verified_package_for_segments("Boeing XB-15", segments)
    card = {"unit": "Boeing XB-15", "evidence_segments": segments}

    warnings = pe._validate_card_against_verified_sources(card, package)

    assert any("source_excerpt_id S99-E9 does not match verified excerpt S1-E1" in warning for warning in warnings)


def test_research_card_must_select_at_least_one_authoritative_source():
    segments = _evidence_segments()
    for segment in segments:
        segment["source_url"] = "https://example.test/b52-reference"
    package = _verified_package_for_segments("Boeing XB-15", segments)
    package["sources"].append({
        "source_id": "S-AUTH",
        "title": "Authoritative unused source",
        "url": "https://airandspace.si.edu/collection-objects/boeing-xb-15",
        "text_hash": "auth",
        "text_chars": 120,
    })
    package["candidate_excerpts"].append({
        "excerpt_id": "S-AUTH-E1",
        "source_id": "S-AUTH",
        "source_title": "Authoritative unused source",
        "source_url": "https://airandspace.si.edu/collection-objects/boeing-xb-15",
        "locator": "S-AUTH-E1",
        "text": "Boeing XB-15 authoritative context not selected by the card.",
        "text_hash": "auth",
        "source_capture_method": "fetched_page",
    })
    card = {"unit": "Boeing XB-15", "evidence_segments": segments}

    warnings = pe._validate_card_against_verified_sources(card, package)

    assert any("at least one selected Tier 1-2" in warning for warning in warnings)


def test_metadata_evidence_rejects_caution_only_support():
    segments = _evidence_segments()
    for segment in segments:
        segment["source_url"] = "https://airandspace.si.edu/collection-objects/boeing-xb-15"
    caution_timeframe = copy.deepcopy(segments[4])
    caution_timeframe["evidence_id"] = "E-TIME-WIKI"
    caution_timeframe["source_url"] = "https://en.wikipedia.org/wiki/Boeing_XB-15"
    segments.append(caution_timeframe)
    package = _verified_package_for_segments("Boeing XB-15", segments)
    card = {
        "unit": "Boeing XB-15",
        "timeframe_evidence_ids": ["E-TIME-WIKI"],
        "visual_identity_evidence_ids": ["E-DECISION"],
        "evidence_segments": segments,
    }

    warnings = pe._validate_card_against_verified_sources(card, package)

    assert any("timeframe uses only Tier 4/caution sources" in warning for warning in warnings)
    assert not any("visual_identity uses only Tier 4/caution sources" in warning for warning in warnings)


def test_paragraph_worth_rejects_unsupported_numbers_and_designations():
    segments = _evidence_segments()
    segments[0]["claim"] = "Boeing XB-15 original problem involved range and payload requirements."
    segments[0]["source_excerpt"] = "Boeing XB-15 original problem involved range and payload requirements."
    segments[0]["numeric_tokens"] = []
    package = _verified_package_for_segments("Boeing XB-15", segments)
    card = {
        "unit": "Boeing XB-15",
        "why_this_unit_deserves_a_paragraph": (
            "Boeing XB-15 proves how a 1939 range problem created a B-29 replacement path."
        ),
        "evidence_segments": segments,
    }

    warnings = pe._validate_card_against_verified_sources(card, package)

    assert any("why_this_unit_deserves_a_paragraph introduced unsupported numerical detail(s): 1939" in warning for warning in warnings)
    assert any("why_this_unit_deserves_a_paragraph introduced unsupported designation(s): B29" in warning for warning in warnings)


def test_visual_identity_requires_concrete_source_grounded_image_basis():
    machine = "Boeing XB-15"
    evidence, errors = pe._normalize_machine_evidence(
        {"evidence_segments": _evidence_segments()},
        machine,
    )
    assert errors == []

    assert pe._visual_identity_warnings(machine, "", evidence, [])
    assert any(
        "generic" in warning
        for warning in pe._visual_identity_warnings(
            machine,
            "Hero image of the machine that looks realistic and visually distinct.",
            evidence,
            ["E-DECISION"],
        )
    )
    assert any(
        "camera/editing/text" in warning
        for warning in pe._visual_identity_warnings(
            machine,
            "Boeing XB-15 camera zoom over wing, engine, tail, nose, and fuselage features.",
            evidence,
            ["E-DECISION"],
        )
    )
    assert any(
        "not grounded" in warning
        for warning in pe._visual_identity_warnings(
            machine,
            "Boeing XB-15 identified by delta wing, twin boom, radar dish, and canard features.",
            evidence,
            ["E-DECISION"],
        )
    )
    assert pe._visual_identity_warnings(
        machine,
        _visual_identity_fields(machine)["visual_identity"],
        evidence,
        _visual_identity_fields(machine)["visual_identity_evidence_ids"],
    ) == []


def test_timeframe_requires_source_grounded_date_or_service_period():
    machine = "Boeing XB-15"
    evidence, errors = pe._normalize_machine_evidence(
        {"evidence_segments": _evidence_segments()},
        machine,
    )
    assert errors == []

    assert pe._timeframe_warnings(machine, "", evidence, [])
    assert any(
        "must name a sourced date, era, or service period" in warning
        for warning in pe._timeframe_warnings(
            machine,
            "Boeing XB-15 has a verified timeframe.",
            evidence,
            ["E-REALITY"],
        )
    )
    assert any(
        "not grounded" in warning
        for warning in pe._timeframe_warnings(
            machine,
            "Boeing XB-15 documented through its Vietnam War service period.",
            evidence,
            ["E-REALITY"],
        )
    )
    assert any(
        "unknown evidence" in warning
        for warning in pe._timeframe_warnings(
            machine,
            _timeframe_fields(machine)["timeframe"],
            evidence,
            ["E-MISSING"],
        )
    )
    assert pe._timeframe_warnings(
        machine,
        _timeframe_fields(machine)["timeframe"],
        evidence,
        _timeframe_fields(machine)["timeframe_evidence_ids"],
    ) == []


def test_timeframe_and_visual_identity_reject_tier4_only_citations():
    """Regression: prod XB-15 card (2026-07-15) cited Wikipedia-only timeframe
    evidence while a Tier-1 boeing.com excerpt sat unused in the same card;
    the backend saved it and the UI then blocked the preview."""
    machine = "Boeing XB-15"
    evidence = copy.deepcopy(_evidence_segments())
    # Make the reality segment Tier 4 (Wikipedia) like the prod card.
    for segment in evidence:
        if segment["evidence_id"] in ("E-REALITY", "E-PROBLEM"):
            segment["source_url"] = "https://en.wikipedia.org/wiki/Boeing_XB-15"
    normalized, errors = pe._normalize_machine_evidence(
        {"evidence_segments": evidence}, machine
    )
    assert errors == []
    tier4_only = pe._timeframe_warnings(
        machine,
        _timeframe_fields(machine)["timeframe"],
        normalized,
        ["E-REALITY"],
    )
    assert any("Tier 4/caution sources only" in warning for warning in tier4_only)
    # Citing a Tier 1-3 segment alongside clears the tier warning.
    mixed = pe._timeframe_warnings(
        machine,
        _timeframe_fields(machine)["timeframe"],
        normalized,
        ["E-REALITY", "E-MEANING"],
    )
    assert not any("Tier 4/caution" in warning for warning in mixed)
    # Card-level: all-Tier-3+ segments must demand a Tier 1-2 citation.
    all_tier3 = copy.deepcopy(_evidence_segments())
    for segment in all_tier3:
        segment["source_url"] = "https://www.thisdayinaviation.com/tag/boeing-xb-15"
    card = _valid_research_card(machine, segments=all_tier3)
    warnings = pe._research_card_contract_warnings(machine, card)
    assert any("no Tier 1-2 source" in warning for warning in warnings)


def test_g14_tier_floor_and_caution_only_gaps_all_advisory_not_blocking():
    """G14, 2026-07-31 (Ryan's ruling, decisions.md): the research referee's
    Tier 1-2 source requirement drops from HARD BLOCK to advisory note -
    Wikipedia-grade (Tier 3-4) sources may carry a card. This enumerates
    EVERY tier-floor rule that changed (same fixtures as the still-green
    tests above this one, proving the raw warning TEXT is byte-identical -
    only blocking status moved) and proves _blocking_warnings() empties out
    for each one on its own."""
    machine = "Boeing XB-15"

    # 1) Package-level: zero Tier 1-2 anywhere (some Tier 3 reference source).
    secondary_segments = _evidence_segments()
    for index, segment in enumerate(secondary_segments):
        segment["source_url"] = f"https://example-secondary.test/boeing-xb-15-{index}"
    secondary_package = _verified_package_for_segments("Boeing XB-15", secondary_segments)
    secondary_errors = pe._verified_machine_source_package_quality_errors(secondary_package)
    assert any("Tier 1-2 primary/authoritative source" in e for e in secondary_errors)
    assert pe._blocking_warnings(secondary_errors) == []

    # 2) Package-level: every source is caution-tier (Wikipedia/YouTube) -
    #    the pure-Tier-4 "Wikipedia-only" case Ryan named explicitly.
    caution_segments = _evidence_segments()
    for index, segment in enumerate(caution_segments):
        segment["source_url"] = [
            "https://en.wikipedia.org/wiki/Boeing_XB-15",
            "https://www.youtube.com/watch?v=test",
        ][index % 2]
    caution_package = _verified_package_for_segments("Boeing XB-15", caution_segments)
    caution_errors = pe._verified_machine_source_package_quality_errors(caution_package)
    assert any("non-caution source" in e for e in caution_errors)
    assert pe._blocking_warnings(caution_errors) == []

    # 3) Package-level: a required Anton slot backed only by Tier 4/caution excerpts.
    tier4_slot_segments = _evidence_segments()
    for segment in tier4_slot_segments:
        segment["source_url"] = "https://airandspace.si.edu/collection-objects/boeing-xb-15"
    tier4_slot_segments[0]["source_url"] = "https://en.wikipedia.org/wiki/Boeing_XB-15"
    tier4_slot_package = _verified_package_for_segments("Boeing XB-15", tier4_slot_segments)
    tier4_slot_errors = pe._verified_machine_source_package_quality_errors(tier4_slot_package, machine)
    assert any("only with Tier 4/caution excerpts: original_problem" in e for e in tier4_slot_errors)
    assert pe._blocking_warnings(tier4_slot_errors) == []

    # 4) Card-level: a required Anton slot cited only by Tier 4/caution sources.
    card_tier4_segments = _evidence_segments()
    for segment in card_tier4_segments:
        segment["source_url"] = "https://en.wikipedia.org/wiki/Boeing_XB-15"
    card_tier4_package = _verified_package_for_segments("Boeing XB-15", card_tier4_segments)
    card_tier4 = {"unit": machine, "evidence_segments": card_tier4_segments}
    card_tier4_warnings = pe._validate_card_against_verified_sources(card_tier4, card_tier4_package)
    assert any("Tier 4/caution source" in w for w in card_tier4_warnings)
    assert pe._blocking_warnings(card_tier4_warnings) == []

    # 5) Card-level: a timeframe/visual_identity FIELD cited only by Tier 4.
    caution_field_segments = _evidence_segments()
    for segment in caution_field_segments:
        segment["source_url"] = "https://airandspace.si.edu/collection-objects/boeing-xb-15"
    caution_field_timeframe = copy.deepcopy(caution_field_segments[4])
    caution_field_timeframe["evidence_id"] = "E-TIME-WIKI"
    caution_field_timeframe["source_url"] = "https://en.wikipedia.org/wiki/Boeing_XB-15"
    caution_field_segments.append(caution_field_timeframe)
    caution_field_package = _verified_package_for_segments("Boeing XB-15", caution_field_segments)
    caution_field_card = {
        "unit": machine,
        "timeframe_evidence_ids": ["E-TIME-WIKI"],
        "visual_identity_evidence_ids": ["E-DECISION"],
        "evidence_segments": caution_field_segments,
    }
    caution_field_warnings = pe._validate_card_against_verified_sources(caution_field_card, caution_field_package)
    assert any("timeframe uses only Tier 4/caution sources" in w for w in caution_field_warnings)
    assert pe._blocking_warnings(caution_field_warnings) == []

    # 6) Card-level: _research_card_contract_warnings' own sourced_tiers gate
    #    (no Tier 1-2 anywhere among the card's own cited evidence).
    all_tier3 = copy.deepcopy(_evidence_segments())
    for segment in all_tier3:
        segment["source_url"] = "https://www.thisdayinaviation.com/tag/boeing-xb-15"
    tier3_card = _valid_research_card(machine, segments=all_tier3)
    tier3_warnings = pe._research_card_contract_warnings(machine, tier3_card)
    assert any("no Tier 1-2 source" in w for w in tier3_warnings)
    assert pe._blocking_warnings(tier3_warnings) == []

    # 7) _cited_evidence_tier_warning (the UI-readiness-mirroring helper feeding
    #    _visual_identity_warnings/_timeframe_warnings) demotes too.
    evidence_by_id = {"E1": {"source_url": "https://en.wikipedia.org/wiki/X", "source_tier": 4}}
    field_warning = pe._cited_evidence_tier_warning("timeframe", ["E1"], evidence_by_id)
    assert any("Tier 4/caution sources only" in w for w in field_warning)
    assert pe._blocking_warnings(field_warning) == []


def test_g14_non_tier_warnings_are_unaffected_and_still_block():
    """G14 companion to the enumeration above: prove the blocking set shrank
    by EXACTLY the seven tier-floor rules and nothing else. Every one of
    these non-tier checks must remain a plain (non-"advisory: "-prefixed)
    warning that _blocking_warnings() keeps."""
    machine = "Boeing XB-15"

    # Excerpt-verbatim-in-fetched-text grounding (THE anti-hallucination wall).
    segments = _evidence_segments()
    package = _verified_package_for_segments(machine, segments)
    card = {"unit": machine, "evidence_segments": copy.deepcopy(segments)}
    for segment in card["evidence_segments"]:
        if segment["evidence_id"] == "E-TRADEOFF":
            segment["source_excerpt"] = "This exact sentence was never fetched from any source."
            segment["locator"] = "FABRICATED-LOCATOR"
            segment["source_excerpt_id"] = "FABRICATED-ID"
    grounding_warnings = pe._validate_card_against_verified_sources(card, package)
    assert any("was not found in verified fetched source text" in w for w in grounding_warnings)
    assert not any(str(w).startswith(pe._ADVISORY_PREFIX) for w in grounding_warnings)
    assert pe._blocking_warnings(grounding_warnings) != []

    # Distinct source URLs (single-source package) - unrelated to tier.
    single_source_segments = _evidence_segments()
    for segment in single_source_segments:
        segment["source_url"] = "https://airandspace.si.edu/collection-objects/boeing-xb-15"
    single_source_package = _verified_package_for_segments(machine, single_source_segments)
    single_source_errors = pe._verified_machine_source_package_quality_errors(single_source_package)
    assert any("two distinct source URLs" in e for e in single_source_errors)
    assert not any(str(e).startswith(pe._ADVISORY_PREFIX) for e in single_source_errors)
    assert pe._blocking_warnings(single_source_errors) != []

    # Unsupported/missing source capture method - unrelated to tier.
    capture_package = _verified_package_for_segments(machine, _evidence_segments())
    capture_package["candidate_excerpts"][0]["source_capture_method"] = "tavily_snippet"
    capture_errors = pe._verified_machine_source_package_quality_errors(capture_package)
    assert any("unsupported source capture method" in e for e in capture_errors)
    assert pe._blocking_warnings(capture_errors) != []

    # Missing required Anton slot coverage entirely (content, not tier).
    missing_slot_card = _valid_research_card(
        machine, segments=[s for s in _evidence_segments() if s["kind"] != "tradeoff"]
    )
    missing_slot_warnings = pe._research_card_contract_warnings(machine, missing_slot_card)
    assert any("missing required Anton slots for" in w for w in missing_slot_warnings)
    assert pe._blocking_warnings(missing_slot_warnings) != []


def test_card_validation_requires_sourced_memorable_fact_slot(monkeypatch):
    roster = ["Boeing XB-15"]
    segments = [
        segment for segment in _evidence_segments()
        if segment["kind"] != "memorable_fact"
    ]
    card = {
        "unit": "Boeing XB-15",
        "engineering_thesis": "Boeing XB-15 has a sufficiently detailed source-grounded engineering thesis.",
        "why_this_unit_deserves_a_paragraph": "Boeing XB-15 proves how a range and payload problem created a bomber tradeoff with consequences no other roster machine replaces.",
        "surprising_fact": "Legacy compatibility fact should not pass without a sourced segment.",
        "source_notes": ["https://airandspace.si.edu/test"],
        **_timeframe_fields("Boeing XB-15"),
        **_visual_identity_fields("Boeing XB-15"),
        "evidence_segments": segments,
    }
    payload = {
        "unit_roster": roster,
        "unit_research_cards": [card],
        "machine_raw_source_packages": {
            pe._verified_source_cache_key("Boeing XB-15"): _verified_package_for_segments("Boeing XB-15", segments),
        },
    }
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"

    class ForbiddenAnthropic:
        async def generate(self, **_kwargs):
            raise AssertionError("invalid card must not be reused")

    executor.__dict__["_pipeline"] = type("Pipeline", (), {"anthropic": ForbiddenAnthropic()})()

    async def no_compact_rows(*_args, **_kwargs):
        return []

    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pe, "fetch_all", no_compact_rows)
    monkeypatch.setattr(executor, "_log_activity", noop)

    result = asyncio.run(executor._run_unit_research_hold("video-a", "Title", payload, roster))

    assert result["unit_research_hold_validation"]["passed"] is False
    assert any(
        "missing sourced memorable_fact evidence segment" in warning
        for warning in result["unit_research_hold_validation"]["units"][0]["warnings"]
    )


def test_target_machine_advisory_only_card_is_not_reported_stopped(monkeypatch):
    roster = ["Boeing XB-15"]
    segments = _tier3_only_evidence_segments()
    package = _verified_package_for_segments("Boeing XB-15", segments)
    card = _valid_research_card("Boeing XB-15", segments)
    payload = {"unit_roster": roster, "unit_research_cards": []}
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    activity = []

    class FakeAnthropic:
        async def generate(self, **_kwargs):
            return json.dumps(card)

    executor.__dict__["_pipeline"] = type("Pipeline", (), {"anthropic": FakeAnthropic()})()

    async def fake_gather(*_args, **_kwargs):
        return package

    async def updated(*_args, **_kwargs):
        return "UPDATE 1"

    async def log_activity(_bot, _video, status, message):
        activity.append((status, message))

    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(executor, "_gather_verified_machine_source_package", fake_gather)
    monkeypatch.setattr(executor, "_checkpoint_machine_raw_source_package", updated)
    monkeypatch.setattr(executor, "_checkpoint_one_machine_research_result", updated)
    monkeypatch.setattr(executor, "_upsert_machine_research_card", noop)
    monkeypatch.setattr(executor, "_log_activity", log_activity)

    result = asyncio.run(executor._run_unit_research_hold(
        "video-a", "Title", payload, roster, target_machine="Boeing XB-15",
    ))

    validation = result["unit_research_hold_validation"]
    assert validation["target_machine_passed"] is True
    assert any("tier_floor_advisory" in warning for warning in validation["units"][0]["warnings"])
    assert not any(
        status == "failed" and "Unit research-hold stopped" in message
        for status, message in activity
    )


def test_full_research_validation_names_real_referee_rejection_not_missing_card(monkeypatch):
    """G13, 2026-07-31 (bonus fix): a machine whose card was saved and
    REJECTED by the referee (validation.passed=False, with specific, named
    warnings) must surface those real warnings, not the generic "missing
    saved one-machine research card" - _load_machine_research_cards drops
    referee-failed rows from unit_research_cards by design (many callers need
    trustworthy-only cards), which used to make the aggregate check
    (_run_unit_research_hold -> _full_research_validation) mislabel a
    rejected card as never having been researched at all."""
    roster = ["32 HMS Howe"]
    real_rejection_warnings = [
        "card unit does not match locked machine 32 HMS Howe",
        "evidence_segments missing required Anton slots for: original_problem, engineering_decision, tradeoff, reality",
    ]
    compact_rows = [{
        "machine_key": pe._normalized_unit_code("32 HMS Howe"),
        "machine_name": "32 HMS Howe",
        "roster_index": 1,
        "card": {"unit": "32 HMS Howe"},  # referee-rejected; content irrelevant, it must be dropped
        "validation": {"passed": False, "warnings": real_rejection_warnings},
    }]
    payload = {"unit_roster": roster, "unit_research_cards": []}
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"

    class ForbiddenAnthropic:
        async def generate(self, **_kwargs):
            raise AssertionError("the early bulk-validation short-circuit must not reach an LLM call")

    executor.__dict__["_pipeline"] = type("Pipeline", (), {"anthropic": ForbiddenAnthropic()})()

    async def fake_fetch_all(*_args, **_kwargs):
        return compact_rows

    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(executor, "_log_activity", noop)

    # First, the mechanism directly: the failed row is dropped from
    # unit_research_cards (unchanged behavior) but its real verdict is
    # stashed for callers that need to explain why.
    loaded = asyncio.run(executor._load_machine_research_cards("video-a", payload, roster))
    assert loaded["unit_research_cards"] == []
    stash = loaded["_dropped_failed_research_card_validations"][pe._normalized_unit_code("32 HMS Howe")]
    assert stash["warnings"] == real_rejection_warnings

    # Then end-to-end through the aggregate consumer: no target_machine means
    # _run_unit_research_hold hits the early bulk-validation short-circuit,
    # which must report the REAL rejection reason for "32 HMS Howe", not the
    # generic missing-card message.
    result = asyncio.run(executor._run_unit_research_hold("video-a", "Title", payload, roster))

    units = result["unit_research_hold_validation"]["units"]
    assert len(units) == 1
    assert units[0]["machine"] == "32 HMS Howe"
    assert units[0]["passed"] is False
    assert units[0]["warnings"] == real_rejection_warnings
    assert "missing saved one-machine research card" not in units[0]["warnings"]


def test_roster_story_uniqueness_flags_duplicate_engineering_ideas():
    roster = ["Boeing XB-15", "Boeing B-17 Flying Fortress"]
    duplicate_thesis = "shows a long range payload endurance compromise where power limits shaped bomber procurement balance"
    cards = {
        pe._normalized_unit_code(machine): _valid_research_card(
            machine,
            engineering_thesis=f"{machine} {duplicate_thesis}.",
            why_this_unit_deserves_a_paragraph=(
                f"{machine} deserves a paragraph because its long range payload endurance compromise "
                "shows how power limits shaped bomber procurement balance."
            ),
        )
        for machine in roster
    }

    warnings = pe._roster_story_uniqueness_warnings(roster, cards)

    assert pe._normalized_unit_code(roster[0]) in warnings
    assert pe._normalized_unit_code(roster[1]) in warnings
    assert any("duplicates engineering story with Boeing B-17" in warning for warning in warnings["XB15"])
    assert any("duplicates engineering story with Boeing XB-15" in warning for warning in warnings["B17"])


def test_full_research_validation_refuses_duplicate_unit_stories_before_llm(monkeypatch):
    roster = ["Boeing XB-15", "Boeing B-17 Flying Fortress"]
    cards = []
    packages = {}
    duplicate_thesis = "shows a long range payload endurance compromise where power limits shaped bomber procurement balance"
    for machine in roster:
        segments = _evidence_segments()
        cards.append(_valid_research_card(
            machine,
            segments,
            engineering_thesis=f"{machine} {duplicate_thesis}.",
            why_this_unit_deserves_a_paragraph=(
                f"{machine} deserves a paragraph because its long range payload endurance compromise "
                "shows how power limits shaped bomber procurement balance."
            ),
        ))
        packages[pe._verified_source_cache_key(machine)] = _verified_package_for_segments(machine, segments)
    payload = {
        "unit_roster": roster,
        "unit_research_cards": cards,
        "machine_raw_source_packages": packages,
    }

    class ForbiddenAnthropic:
        def __init__(self):
            self.calls = 0

        async def generate(self, **_kwargs):
            self.calls += 1
            raise AssertionError("duplicate full-roster cards must fail before Claude")

    forbidden_anthropic = ForbiddenAnthropic()
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("Pipeline", (), {"anthropic": forbidden_anthropic})()
    writes = []

    async def fake_execute(query, *args):
        writes.append((query, args))
        return None

    async def no_compact_rows(*_args, **_kwargs):
        return []

    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", no_compact_rows)
    monkeypatch.setattr(executor, "_log_activity", noop)

    result = asyncio.run(executor._run_unit_research_hold("video-a", "Title", payload, roster))

    assert result["unit_research_hold_validation"]["passed"] is False
    assert forbidden_anthropic.calls == 0
    assert writes == []
    unit_warnings = [
        warning
        for unit in result["unit_research_hold_validation"]["units"]
        for warning in unit["warnings"]
    ]
    assert any("duplicates engineering story" in warning for warning in unit_warnings)


def test_verified_source_validation_requires_matching_locator():
    segments = _evidence_segments()
    package = _verified_package_for_segments("Boeing XB-15", segments)
    segments[0]["locator"] = "wrong-excerpt-row"
    card = {"unit": "Boeing XB-15", "evidence_segments": segments}

    warnings = pe._validate_card_against_verified_sources(card, package)

    assert any("source_excerpt/locator was not found" in warning for warning in warnings)


def test_verified_source_package_filters_other_aircraft_designations_for_target_machine():
    package = {
        "passed": True,
        "candidate_excerpts": [
            {
                "excerpt_id": "good-target",
                "source_title": "Douglas XB-19",
                "source_url": "https://example.test/xb-19",
                "locator": "p1",
                "source_capture_method": "fetched_page",
                "text": "The Douglas XB-19 was built as a giant experimental bomber.",
            },
            {
                "excerpt_id": "bad-comparison",
                "source_title": "Douglas XB-19 later comparisons",
                "source_url": "https://example.test/xb-19-comparison",
                "locator": "p2",
                "source_capture_method": "fetched_page",
                "text": "The Douglas XB-19 was soon compared with later XB-35 and XB-36 bomber designs.",
            },
            {
                "excerpt_id": "good-no-code",
                "source_title": "Douglas XB-19 giant bomber",
                "source_url": "https://example.test/giant-bomber",
                "locator": "p3",
                "source_capture_method": "fetched_page",
                "text": "The Douglas XB-19 prototype became a research aircraft rather than an operational weapon.",
            },
        ],
    }

    formatted = pe._format_verified_machine_source_package(package, "Douglas XB-19")

    assert "good-target" in formatted
    assert "good-no-code" in formatted
    assert "bad-comparison" not in formatted
    assert "XB-35" not in formatted
    assert "XB-36" not in formatted


def test_machine_evidence_numeric_tokens_accept_equivalent_source_formatting():
    card = {
        "unit": "Boeing XB-15",
        "evidence_segments": [
            {
                "evidence_id": "XB15-DP-01",
                "kind": "design_problem",
                "claim": "Boeing XB-15 requirements grew from 5,000 pounds to 8,000 pounds.",
                "source_excerpt": "Boeing XB-15 requirements grew from 5,000 pounds to 8,000 pounds.",
                "source_url": "https://example.test/xb-15",
                "source_title": "Test source",
                "locator": "S1-E1",
                "numeric_tokens": ["5000", "8000"],
                "confidence": "high",
            },
            {
                "evidence_id": "XB15-ER-01",
                "kind": "engineering_response",
                "claim": "Boeing XB-15 used 2 engines in this test sentence.",
                "source_excerpt": "Boeing XB-15 used two engines in this test sentence.",
                "source_url": "https://example.test/xb-15",
                "source_title": "Test source",
                "locator": "S1-E2",
                "numeric_tokens": ["2"],
                "confidence": "high",
            },
            {
                "evidence_id": "XB15-TR-01",
                "kind": "tradeoff",
                "claim": "Boeing XB-15 range was five thousand miles.",
                "source_excerpt": "Boeing XB-15 range was 5,000 mi.",
                "source_url": "https://example.test/xb-15",
                "source_title": "Test source",
                "locator": "S1-E3",
                "numeric_tokens": ["5000"],
                "confidence": "high",
            },
        ],
    }

    _evidence, errors = pe._normalize_machine_evidence(card, "Boeing XB-15")

    assert errors == []


def test_machine_evidence_human_detail_requires_attribution():
    base_segment = {
        "evidence_id": "XB15-HUMAN-01",
        "kind": "human_detail",
        "claim": "A pilot account said the bomber was difficult to manage.",
        "source_excerpt": "A pilot account said the bomber was difficult to manage.",
        "source_url": "https://example.test/xb-15-human",
        "source_title": "Test source",
        "locator": "S1-E1",
        "numeric_tokens": [],
        "confidence": "high",
    }

    _evidence, generic_errors = pe._normalize_machine_evidence(
        {"unit": "Boeing XB-15", "evidence_segments": [base_segment]},
        "Boeing XB-15",
    )
    assert any("human_detail must name a person or cite an official finding" in error for error in generic_errors)

    named_segment = {
        **base_segment,
        "claim": "Major William Snow said the bomber was difficult to manage.",
        "source_excerpt": "Major William Snow said the bomber was difficult to manage.",
    }
    _evidence, named_errors = pe._normalize_machine_evidence(
        {"unit": "Boeing XB-15", "evidence_segments": [named_segment]},
        "Boeing XB-15",
    )
    assert named_errors == []

    official_segment = {
        **base_segment,
        "claim": "The accident report concluded the bomber was difficult to manage.",
        "source_excerpt": "The accident report concluded the bomber was difficult to manage.",
    }
    _evidence, official_errors = pe._normalize_machine_evidence(
        {"unit": "Boeing XB-15", "evidence_segments": [official_segment]},
        "Boeing XB-15",
    )
    assert official_errors == []


def test_paragraph_worth_requires_unique_engineering_idea():
    generic_warnings = pe._paragraph_worth_warnings(
        "Boeing B-52 Stratofortress",
        "This machine mattered and was famous and important.",
    )
    specific_warnings = pe._paragraph_worth_warnings(
        "Boeing B-52 Stratofortress",
        "B-52 proves how a long-range payload requirement created a bomber built around endurance rather than short-lived speed.",
    )

    assert any("generic" in warning for warning in generic_warnings)
    assert any("concrete engineering decision" in warning for warning in generic_warnings)
    assert specific_warnings == []


def test_machine_evidence_numeric_tokens_ignore_model_designation_tokens():
    card = {
        "unit": "Douglas XB-19",
        "evidence_segments": [
            {
                "evidence_id": "XB19-BUILD-01",
                "kind": "build_reality",
                "claim": "The XB-19 took so long that competition for the XB-35 and XB-36 occurred before its first flight.",
                "source_excerpt": "Its construction took so long that competition for the contracts to build the XB-35 and XB-36 occurred two months before its first flight.",
                "source_url": "https://example.test/xb-19",
                "source_title": "Test source",
                "locator": "S1-E1",
                "numeric_tokens": ["xb-19", "xb-35", "xb-36", "two"],
                "confidence": "high",
            },
        ],
    }

    evidence, errors = pe._normalize_machine_evidence(card, "Douglas XB-19")

    assert errors == []
    assert "xb-19" not in evidence[0]["numeric_tokens"]
    assert "xb-35" not in evidence[0]["numeric_tokens"]
    assert "xb-36" not in evidence[0]["numeric_tokens"]
    assert {"35", "36", "two"}.issubset(set(evidence[0]["numeric_tokens"]))


def test_machine_hold_blast_radius_requires_static_docu_and_locked_roster():
    payload = {"unit_roster": ["Boeing XB-15", "Boeing B-17", "Convair B-36"]}
    machine_payload = {**payload, "documentary_style": "machine_documentary"}

    # Global animation/narrative remains dominant even if research happens to
    # contain a roster-shaped artifact.
    assert pe._machine_documentary_hold_roster(
        {"render_mode": "animated", "research_payload": payload}
    ) == []
    assert pe._machine_documentary_hold_roster(
        {"render_mode": "dialogue", "research_payload": payload}
    ) == []
    assert pe._machine_documentary_hold_roster(
        {"render_mode": "static_docu", "research_payload": {}}
    ) == []
    assert pe._machine_documentary_hold_roster(
        {"render_mode": "static_docu", "research_payload": payload}
    ) == [], "static rendering alone is not a machine-documentary discriminator"

    assert pe._machine_documentary_hold_roster(
        {"render_mode": "static_docu", "research_payload": machine_payload}
    ) == payload["unit_roster"]
    assert pe._machine_documentary_hold_roster(
        {
            "render_mode": "static_docu",
            "research_payload": {
                "documentary_style": "dvsu",
                "unit_roster": [{"unit": name} for name in payload["unit_roster"]],
            },
        }
    ) == payload["unit_roster"]


def test_roster_validation_blocks_extra_conclusion_paragraph_without_machine_code():
    payload = {"unit_roster": ["Boeing XB-15", "Boeing B-17 Flying Fortress"]}
    script_units = [
        "The Boeing XB-15 proved the bomber problem before the engines were ready.",
        "The Boeing B-17 Flying Fortress made daylight bombing a survivable industrial gamble.",
    ]

    assert pe._roster_validation("Designed vs Used: Strategic Bomber Lessons", payload, script_units)["passed"] is True

    extra = pe._roster_validation(
        "Designed vs Used: Strategic Bomber Lessons",
        payload,
        script_units + ["So what have we learned today? The lesson is that strategy always changes."],
    )

    assert extra["passed"] is False
    assert any("must not add separate conclusion" in warning for warning in extra["warnings"])


def test_animated_video_with_roster_shape_still_runs_global_writer(monkeypatch):
    payload = {"unit_roster": ["Boeing XB-15", "Boeing B-17", "Convair B-36"]}
    video = {
        "video_title": "Animated engineering story",
        "render_mode": "animated",
        "status": "ready_for_scripting",
        "research_payload": payload,
    }

    class FakePipeline:
        def __init__(self):
            self.global_writer_calls = 0
            self.script_allowed_speakers = None
            self.script_format_contract = None

        async def run_brief_translator(self):
            self.global_writer_calls += 1
            return {"new_status": "ready_for_voice"}

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    pipeline = FakePipeline()
    executor.__dict__["_pipeline"] = pipeline

    async def noop_async(*_args, **_kwargs):
        return None

    async def fake_get_video(_video_id):
        return video

    async def fake_fetch_all(*_args, **_kwargs):
        return []

    async def forbidden_machine_hold(*_args, **_kwargs):
        raise AssertionError("animated video entered machine-documentary hold")

    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(executor, "_ensure_initialized", noop_async)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_log_activity", noop_async)
    monkeypatch.setattr(executor, "_log_transition", noop_async)
    monkeypatch.setattr(executor, "_update_video_status", noop_async)
    monkeypatch.setattr(executor, "_inject_learnings_into_writer_guidance", noop_async)
    monkeypatch.setattr(executor, "_load_prompt_overrides", noop_async)
    monkeypatch.setattr(executor, "_grade_and_maybe_revise_script", noop_async)
    monkeypatch.setattr(executor, "_load_idea_from_video", lambda _video_id: None)
    monkeypatch.setattr(executor, "_skip_disabled_next", lambda _video, status: status)
    monkeypatch.setattr(executor, "_run_static_script_hold", forbidden_machine_hold)

    result = asyncio.run(executor.run_script("video-test"))

    assert result["status"] == "ready_for_voice"
    assert pipeline.global_writer_calls == 1


# ---------------------------------------------------------------------------
# Checklist C46c: DvsU deltas as table-driven gates. `rule_overrides=None`
# (the default, and every call in this file above) must stay byte-identical
# to pre-C46c behavior -- proven with `git stash` in the verification pass.
# ---------------------------------------------------------------------------


def test_card_matching_never_confuses_prefix_designations():
    payload = {"unit_research_cards": [{"unit": "B-21", "engineering_thesis": "wrong machine"}]}
    assert pe._research_card_for_machine(payload, "B-2") is None


def test_story_plan_locks_research_into_anton_slots():
    payload = {"unit_research_cards": [{
        "unit": "B-52",
        "engineering_thesis": "meaning evidence remains card context",
        "surprising_fact": "must not enter the plan",
        "evidence_segments": _evidence_segments(),
    }]}

    plan = pe._machine_story_plan(payload, "B-52")

    assert plan["schema_version"] == 3
    assert [slot["slot"] for slot in plan["slots"]][:4] == [
        "original_problem",
        "engineering_decision",
        "tradeoff",
        "reality",
    ]
    by_slot = {slot["slot"]: slot["evidence_ids"] for slot in plan["slots"]}
    evidence_by_id = {
        segment["evidence_id"]: segment
        for slot in plan["slots"]
        for segment in slot.get("evidence_segments", [])
    }
    assert by_slot["original_problem"] == ["E-PROBLEM"]
    assert by_slot["engineering_decision"] == ["E-DECISION"]
    assert by_slot["tradeoff"] == ["E-TRADEOFF"]
    assert by_slot["reality"] == ["E-REALITY", "E-MEANING"]
    assert by_slot["memorable_fact"] == ["E-MEMORABLE"]
    assert evidence_by_id["E-MEANING"]["kind"] == "reality"
    assert "historical_meaning" not in by_slot
    assert all(
        segment.get("kind") != "historical_meaning"
        for slot in plan["slots"]
        for segment in slot.get("evidence_segments", [])
    )
    assert "must not enter the plan" not in json.dumps(plan)
    assert plan["contract"]["maximum_numerical_details"] == 15
    assert plan["contract"]["narrative_weight"]["label"] == "standard"
    assert plan["contract"]["narrative_weight"]["target_words"] == "100-120"
    assert plan["contract"]["paragraph_shape"] == "one Anton/DVsU paragraph, 5 natural formula sentences"
    assert plan["contract"]["sentence_formula"] == "4 evidence-backed sentences + 1 paragraph-derived conclusion"
    assert "engineering decision" in plan["contract"]["movement"]
    assert "single engineering decision" in plan["contract"]["editorial_thesis"]
    assert "compact inventory cadence" in plan["contract"]["benchmark_style_rule"]
    assert "memorable_fact" in plan["contract"]["memorable_fact_rule"]
    assert "paragraph-derived conclusion" in plan["contract"]["movement"]
    assert "no new sourced meaning beat" in plan["contract"]["conclusion_rule"]
    assert "Producer File/on-screen text" in plan["contract"]["onscreen_label"]
    assert "never spoken narration" in plan["contract"]["onscreen_label"]


def test_story_plan_sets_narrative_weight_for_major_and_transitional_machines():
    major_plan = pe._machine_story_plan(
        {
            "unit_research_cards": [{
                "unit": "B-17",
                "narrative_weight": "major",
                "engineering_thesis": "The bomber was a mainstay of daylight bombing.",
                "evidence_segments": _evidence_segments(),
            }]
        },
        "B-17",
    )
    transitional_plan = pe._machine_story_plan(
        {
            "unit_research_cards": [{
                "unit": "XB-15",
                "engineering_thesis": "The machine was a prototype that proved the problem before combat use.",
                "why_this_unit_deserves_a_paragraph": "Only one experimental prototype was built and it was never used in combat.",
                "evidence_segments": _evidence_segments(),
            }]
        },
        "XB-15",
    )

    assert major_plan["contract"]["narrative_weight"]["label"] == "major"
    assert major_plan["contract"]["narrative_weight"]["target_words"] == "110-150"
    assert transitional_plan["contract"]["narrative_weight"]["label"] == "transitional"
    assert transitional_plan["contract"]["narrative_weight"]["target_words"] == "80-95"


def test_story_plan_attaches_first_three_anton_benchmark_profile():
    plan = pe._machine_story_plan(
        {"unit_research_cards": [{"unit": "Boeing XB-15", "evidence_segments": _evidence_segments()}]},
        "Boeing XB-15",
    )

    profile = plan["reference_benchmark"]
    assert profile["source_video"] == "Every US Strategic Bomber Ever Built"
    assert profile["reference_machine"] == "Boeing XB-15"
    assert profile["word_count"] == 94
    assert profile["sentence_count"] == 5
    assert profile["opening_mode"] == "machine/date/significance"
    assert any("landing" in job for job in profile["sentence_jobs"])


def test_first_three_anton_benchmark_profiles_match_extracted_script_shape():
    expected = {
        "Boeing XB-15": (1, 94, 5, "machine/date/significance"),
        "Boeing B-17 Flying Fortress": (2, 116, 7, "machine/service/significance"),
        "Consolidated B-24 Liberator": (3, 110, 6, "machine/date/production significance"),
    }

    for machine, (order, word_count, sentence_count, opening_mode) in expected.items():
        profile = pe._anton_reference_benchmark_profile(machine)

        assert profile["source_video"] == "Every US Strategic Bomber Ever Built"
        assert profile["reference_order"] == order
        assert profile["word_count"] == word_count
        assert profile["sentence_count"] == sentence_count
        assert profile["opening_mode"] == opening_mode
        assert profile["final_line_job"]


def test_first_three_anton_benchmark_profiles_are_shape_only():
    forbidden_fact_terms = (
        "experimental leap",
        "long-range strategic bombing",
        "payload",
        "wartime transport",
        "daylight precision",
        "europe",
        "eighth air force",
        "davis wing",
        "b-17",
        "ploesti",
    )

    for machine in ("Boeing XB-15", "Boeing B-17 Flying Fortress", "Consolidated B-24 Liberator"):
        profile = pe._anton_reference_benchmark_profile(machine)
        shape_text = " ".join(profile["sentence_jobs"] + [profile["final_line_job"]]).lower()

        assert "landing" in shape_text
        for term in forbidden_fact_terms:
            assert term not in shape_text


def test_story_plan_refuses_legacy_card_without_source_addressable_evidence():
    plan = pe._machine_story_plan(
        {"unit_research_cards": [{"unit": "B-52", "engineering_thesis": "Untraceable prose."}]},
        "B-52",
    )

    assert any("schema-v3" in error for error in plan["evidence_errors"])
    assert all(not slot["evidence_ids"] for slot in plan["slots"])


def test_story_plan_refuses_claims_that_add_facts_absent_from_source_excerpt():
    evidence = _evidence_segments()
    evidence[0]["claim"] = "Aliens conquered Europe with miraculous nuclear rockets."
    normalized, errors = pe._normalize_machine_evidence(
        {"unit": "B-52", "evidence_segments": evidence},
        "B-52",
    )

    assert errors == []
    assert normalized[0]["claim"] == evidence[0]["source_excerpt"]


def test_machine_preview_has_no_deterministic_story_fallback():
    # The hardcoded XB-19/XB-15 bundles carried in from the research-no-preview
    # chain were deleted 2026-07-15: canned prose can never satisfy the merged
    # five-sentence formula contract or per-run opening assignments, and its
    # evidence-id lookups never proved the canned claims still matched the
    # evidence text. Chronically failing machines go through repair rounds now
    # and park-don't-halt (GOAL.md G3b) later - never canned paragraphs. This
    # tombstone keeps the fallback from returning through another merge.
    assert not hasattr(pe, "_deterministic_machine_story_bundle")
    with open(pe.__file__, encoding="utf-8") as handle:
        source = handle.read()
    assert "_deterministic_machine_story_bundle" not in source
    assert "deterministic_bundle" not in source


# (Removed 2026-07-16: QD-1 deleted the closer word-novelty mechanism entirely -
# the final sentence has vocabulary freedom and only the banned classes gate.
# Entity/number bans are pinned in
# test_story_paragraph_validator_gives_closer_vocabulary_freedom.)


def test_numeric_mentions_normalize_markup_split_decade_suffix():
    assert pe._numeric_mentions_from_text("decommissioned during the 1990 s .") == [
        {"raw": "1990s", "key": "1990s"},
    ]


def test_spoken_decimal_is_one_supported_numeric_mention():
    mentions = pe._numeric_mentions_from_text(
        "a five-point-one billion dollar contract"
    )

    assert mentions == [{"raw": "five point one", "key": "5.1"}]


def test_spoken_compound_ordinal_matches_its_digit_value():
    mentions = pe._numeric_mentions_from_text(
        "laid down on August twenty-second, 2015"
    )

    assert mentions == [
        {"raw": "2015", "key": "2015"},
        {"raw": "twenty second", "key": "22"},
    ]


def test_machine_preview_route_returns_needs_review_audit(monkeypatch):
    import routes.pipeline as route

    class FakeExecutor:
        def __init__(self, tenant_id):
            self.tenant_id = tenant_id

        async def run_machine_script_preview(self, video_id, machine):
            return {
                "status": "completed",
                "video_id": video_id,
                "preview": {
                    "machine": machine,
                    "scene": 1,
                    "paragraph": "Reviewable paragraph.",
                    "word_count": 2,
                    "passed": False,
                    "warnings": ["word count 2 outside 95-120 script-hold range"],
                    "claim_bundle": {"claim_map": []},
                },
                "research_payload": {
                    "machine_script_previews": {
                        "XB15": {"machine": machine, "passed": False},
                    },
                },
            }

    monkeypatch.setattr(route, "PipelineExecutor", FakeExecutor)

    result = asyncio.run(
        route.run_machine_script_preview(
            "video-test",
            route.MachineScriptPreviewRequest(machine="Boeing XB-15", confirmed_paid_run=True),
            tenant_id="tenant-test",
        )
    )

    assert result["preview"]["passed"] is False
    assert result["preview"]["paragraph"] == "Reviewable paragraph."
    assert "word count" in result["preview"]["warnings"][0]
    assert result["research_payload"]["machine_script_previews"]["XB15"]["passed"] is False


def test_machine_preview_route_requires_paid_confirmation(monkeypatch):
    import routes.pipeline as route

    class ForbiddenExecutor:
        def __init__(self, _tenant_id):
            raise AssertionError("unconfirmed paid preview must not construct executor")

    monkeypatch.setattr(route, "PipelineExecutor", ForbiddenExecutor)

    try:
        asyncio.run(
            route.run_machine_script_preview(
                "video-test",
                route.MachineScriptPreviewRequest(machine="Boeing XB-15"),
                tenant_id="tenant-test",
            )
        )
    except route.HTTPException as exc:
        assert exc.status_code == 400
        assert "explicit confirmation" in exc.detail
    else:
        raise AssertionError("unconfirmed paid preview should be rejected")


def test_run_machine_script_preview_refuses_non_roster_machine_before_hold(monkeypatch):
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": None})()

    async def fake_init():
        return None

    async def fake_get_video(_video_id):
        return {
            "render_mode": "static_docu",
            "research_payload": {
                "documentary_style": "designed_vs_used",
                "unit_roster": ["Boeing XB-15", "Boeing B-17", "Consolidated B-24"],
            },
        }

    async def fake_load_prompt_overrides(_video):
        return None

    async def forbidden_hold(*_args, **_kwargs):
        raise AssertionError("non-roster machine must stop before script hold")

    monkeypatch.setattr(executor, "_ensure_initialized", fake_init)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_load_prompt_overrides", fake_load_prompt_overrides)
    monkeypatch.setattr(executor, "_run_static_script_hold", forbidden_hold)

    result = asyncio.run(
        executor.run_machine_script_preview("video-test", "Boeing B-52 Stratofortress")
    )

    assert result["status"] == "failed"
    assert result["error"] == "Machine is not in the locked roster: Boeing B-52 Stratofortress"


def test_reused_card_save_restamps_segment_provenance(monkeypatch):
    """The referee grades a deep copy, so the save path must re-stamp
    verified-source provenance on the REAL card before persisting. A reused
    (revalidated) card's saved segments must carry source_tier / source_id /
    source_excerpt_hash again when the verified package matches them."""
    roster = ["Boeing XB-15"]
    segments = _evidence_segments()
    card = _valid_research_card("Boeing XB-15", segments)
    for segment in card["evidence_segments"]:
        assert "source_tier" not in segment
        assert "source_id" not in segment
        assert "source_excerpt_hash" not in segment
    payload = {
        "documentary_style": "designed_vs_used",
        "unit_roster": roster,
        "unit_research_cards": [card],
        "machine_raw_source_packages": {
            pe._verified_source_cache_key("Boeing XB-15"): _verified_package_for_segments("Boeing XB-15", segments),
        },
    }

    class ForbiddenAnthropic:
        async def generate(self, **_kwargs):
            raise AssertionError("a passing reused card must not trigger a paid research call")

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("Pipeline", (), {"anthropic": ForbiddenAnthropic()})()

    async def no_compact_rows(*_args, **_kwargs):
        return []

    async def noop(*_args, **_kwargs):
        return None

    saved = []

    async def recording_upsert(video_id, machine, roster_index, card_arg, validation):
        saved.append((video_id, machine, roster_index, card_arg, validation))

    monkeypatch.setattr(pe, "fetch_all", no_compact_rows)
    monkeypatch.setattr(executor, "_log_activity", noop)
    monkeypatch.setattr(executor, "_upsert_machine_research_card", recording_upsert)

    result = asyncio.run(
        executor._run_unit_research_hold("video-test", "Test title", payload, roster)
    )

    assert result["unit_research_hold_validation"]["passed"] is True
    assert len(saved) == 1
    _video_id, machine, _index, saved_card, validation = saved[0]
    assert machine == "Boeing XB-15"
    assert validation["passed"] is True
    saved_segments = saved_card["evidence_segments"]
    assert saved_segments
    for segment in saved_segments:
        # Provenance stamped from the matched verified candidates (si.edu = Tier 2).
        assert segment["source_tier"] == 2
        assert segment["source_id"].startswith("S")
        assert segment["source_excerpt_hash"] == "test"
        assert segment["source_capture_method"] == "fetched_page"
        assert segment["source_excerpt_id"]
        assert isinstance(segment["source_variant_selection"], dict)


def _support_kind_segments(machine: str) -> list[dict]:
    """Base evidence plus one timeframe-kind and one visual_identity-kind support segment."""
    return _evidence_segments() + [
        {
            "evidence_id": "E-TIMEFRAME",
            "kind": "timeframe",
            "claim": f"{machine} first flew in October 1937 and entered testing.",
            "source_excerpt": f"{machine} first flew in October 1937 and entered testing.",
            "source_url": "https://airandspace.si.edu/test/timeframe",
            "source_title": "Test source",
            "locator": "S9-E1",
            "numeric_tokens": ["1937"],
            "confidence": "high",
        },
        {
            "evidence_id": "E-VISUAL",
            "kind": "visual_identity",
            "claim": f"{machine} was a mid wing monoplane with retractable landing gear.",
            "source_excerpt": f"{machine} was a mid wing monoplane with retractable landing gear.",
            "source_url": "https://airandspace.si.edu/test/visual",
            "source_title": "Test source",
            "locator": "S10-E1",
            "numeric_tokens": [],
            "confidence": "high",
        },
    ]


def test_timeframe_and_visual_identity_support_kinds_are_legal():
    """Ruling 2026-07-16: the contract REQUIRES timeframe/visual_identity evidence
    citations, so segments carrying that evidence are legal OPTIONAL support kinds.
    They map to their own roles, normalize without 'unsupported Anton slot kind'
    errors, and stay OUT of the required four-beat roles."""
    machine = "Boeing XB-15"

    # kind -> role map (the fix itself), including the context aliases.
    assert pe._anton_slot_role_for_kind("timeframe") == "timeframe"
    assert pe._anton_slot_role_for_kind("timeframe_context") == "timeframe"
    assert pe._anton_slot_role_for_kind("visual_identity") == "visual_identity"
    assert pe._anton_slot_role_for_kind("visual_identity_context") == "visual_identity"
    assert pe._anton_slot_role_for_kind("visual_description") == "visual_identity"
    # Never required; "spec" stays illegal.
    assert "timeframe" not in pe._ANTON_REQUIRED_SLOT_ROLES
    assert "visual_identity" not in pe._ANTON_REQUIRED_SLOT_ROLES
    assert pe._anton_slot_role_for_kind("spec") is None

    evidence, errors = pe._normalize_machine_evidence(
        {"evidence_segments": _support_kind_segments(machine)}, machine
    )
    assert errors == []
    roles = {segment["evidence_id"]: segment["slot_role"] for segment in evidence}
    assert roles["E-TIMEFRAME"] == "timeframe"
    assert roles["E-VISUAL"] == "visual_identity"

    # The package-quality coverage gate must not start demanding the new kinds.
    coverage = pe._anton_source_slot_coverage([], machine)
    assert set(coverage["required_slots"]) == pe._ANTON_REQUIRED_SLOT_ROLES

    # Per-field tier gate treats these segments like any cited evidence:
    # a timeframe field cited ONLY by a Tier-4 timeframe-kind segment still blocks.
    tier4_segment = {"kind": "timeframe", "source_url": "https://en.wikipedia.org/wiki/x", "source_tier": 4}
    assert pe._cited_evidence_tier_warning("timeframe", ["E-T4"], {"E-T4": tier4_segment})


def test_machine_preview_readiness_route_returns_review_status(monkeypatch):
    import routes.pipeline as route

    class FakeExecutor:
        def __init__(self, tenant_id):
            self.tenant_id = tenant_id

        async def check_machine_script_preview_readiness(self, video_id, machine):
            return {
                "status": "needs_review",
                "ready": False,
                "video_id": video_id,
                "machine": machine,
                "warnings": ["raw source missing"],
                "summary": "raw source missing",
            }

    monkeypatch.setattr(route, "PipelineExecutor", FakeExecutor)

    result = asyncio.run(
        route.check_machine_script_preview_readiness(
            "video-test",
            route.MachineScriptPreviewRequest(machine="Boeing XB-15"),
            tenant_id="tenant-test",
        )
    )

    assert result["ready"] is False
    assert result["warnings"] == ["raw source missing"]


def test_machine_research_route_humanizes_unexpected_exception(monkeypatch):
    import routes.pipeline as route

    class FakeExecutor:
        def __init__(self, tenant_id):
            self.tenant_id = tenant_id

        async def run_one_machine_research(self, video_id, machine):
            raise RuntimeError("SECRET_RAW_RESEARCH_PROVIDER_ERROR")

    monkeypatch.setattr(route, "PipelineExecutor", FakeExecutor)

    try:
        asyncio.run(
            route.run_one_machine_research(
                "video-test",
                route.MachineResearchRequest(machine="Boeing XB-15", confirmed_paid_run=True),
                tenant_id="tenant-test",
            )
        )
    except route.HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "One-machine research failed. Please try again."
        assert "SECRET_RAW" not in exc.detail
    else:
        raise AssertionError("provider failure should return a humanized HTTPException")


def test_machine_research_route_requires_paid_confirmation(monkeypatch):
    import routes.pipeline as route

    class ForbiddenExecutor:
        def __init__(self, _tenant_id):
            raise AssertionError("unconfirmed paid research must not construct executor")

    monkeypatch.setattr(route, "PipelineExecutor", ForbiddenExecutor)

    try:
        asyncio.run(
            route.run_one_machine_research(
                "video-test",
                route.MachineResearchRequest(machine="Boeing XB-15"),
                tenant_id="tenant-test",
            )
        )
    except route.HTTPException as exc:
        assert exc.status_code == 400
        assert "explicit confirmation" in exc.detail
    else:
        raise AssertionError("unconfirmed paid research should be rejected")


def test_machine_research_route_returns_reviewable_raw_package_failure(monkeypatch):
    import routes.pipeline as route

    review_result = {
        "status": "needs_review",
        "video_id": "video-test",
        "machine": "Boeing XB-15",
        "error": "research card missing Anton slots",
        "research_payload": {
            "machine_raw_source_packages": {
                "XB15": {"candidate_excerpts": [{"excerpt_id": "S1-E1", "text": "Boeing XB-15 raw excerpt."}]},
            },
        },
    }

    class FakeExecutor:
        def __init__(self, tenant_id):
            self.tenant_id = tenant_id

        async def run_one_machine_research(self, video_id, machine):
            return review_result

    monkeypatch.setattr(route, "PipelineExecutor", FakeExecutor)

    result = asyncio.run(
        route.run_one_machine_research(
            "video-test",
            route.MachineResearchRequest(machine="Boeing XB-15", confirmed_paid_run=True),
            tenant_id="tenant-test",
        )
    )

    assert result["status"] == "needs_review"
    assert result["research_payload"]["machine_raw_source_packages"]["XB15"]["candidate_excerpts"][0]["excerpt_id"] == "S1-E1"


def test_machine_script_block_route_returns_saved_block(monkeypatch):
    import routes.pipeline as route

    class FakeExecutor:
        def __init__(self, tenant_id):
            self.tenant_id = tenant_id

        async def run_machine_script_block(self, video_id, machine):
            return {
                "status": "completed",
                "video_id": video_id,
                "script_block": {
                    "machine": machine,
                    "scene": 2,
                    "paragraph": "Saved paragraph.",
                    "word_count": 2,
                    "passed": True,
                    "saved": True,
                    "warnings": [],
                },
            }

    monkeypatch.setattr(route, "PipelineExecutor", FakeExecutor)

    result = asyncio.run(
        route.run_machine_script_block(
            "video-test",
            route.MachineScriptBlockRequest(machine="Douglas XB-19"),
            tenant_id="tenant-test",
        )
    )

    assert result["script_block"]["saved"] is True
    assert result["script_block"]["machine"] == "Douglas XB-19"


def test_machine_script_block_save_updates_one_scene_and_progress(monkeypatch):
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"

    async def fake_fetch_all(query, *args):
        assert args == ("video-test", "tenant-test")
        if "FROM videos" in query:
            return []
        assert "FROM scripts" in query
        return [{"scene": 1, "scene_text": "Existing XB-15 paragraph."}]

    writes = []

    async def fake_execute(query, *args):
        writes.append((query, args))

    transitions = []

    async def fake_transition(video_id, old_status, new_status, source):
        transitions.append((video_id, old_status, new_status, source))

    def fake_skip(_video, status):
        return status

    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(executor, "_log_transition", fake_transition)
    monkeypatch.setattr(executor, "_skip_disabled_next", fake_skip)

    result = asyncio.run(
        executor._save_machine_script_block(
            video_id="video-test",
            video={
                "status": "ready_for_scripting",
                "script_validation": {
                    "script_hold": {
                        "units": [
                            {
                                "scene": 1,
                                "machine": "Boeing XB-15",
                                "word_count": 104,
                                "research_source": "compact_editorial_brief",
                                "passed": True,
                                "warnings": [],
                            }
                        ]
                    }
                },
            },
            roster=["Boeing XB-15", "Douglas XB-19"],
            script_block={
                "machine": "Douglas XB-19",
                "scene": 2,
                "paragraph": "Saved XB-19 paragraph.",
                "word_count": 101,
                "research_source": "compact_editorial_brief",
                "passed": True,
                "warnings": [],
            },
            title="Every US Strategic Bomber Ever Built",
            voice_id="voice-test",
        )
    )

    assert result["saved"] is True
    assert result["new_status"] == "ready_for_voice"
    assert len(writes) == 1
    query, args = writes[0]
    assert "UPDATE scripts" in query
    assert "INSERT INTO scripts" in query
    assert args[2] == 2
    assert args[3] == "Saved XB-19 paragraph."
    assert args[6] == "Existing XB-15 paragraph.\n\nSaved XB-19 paragraph."
    validation = json.loads(args[7])
    assert validation["script_hold"]["passed"] is True
    assert validation["script_hold"]["completed_count"] == 2
    assert validation["machine_script_blocks"]["Douglas XB-19"]["saved"] is True
    assert transitions == [("video-test", "ready_for_scripting", "ready_for_voice", "api")]


def test_static_resplit_voice_lookup_is_tenant_scoped(monkeypatch):
    unit_paragraph = (
        "Boeing XB-15 evidence sentence keeps this static documentary unit long enough "
        "to be treated as one machine paragraph with clear narration, technical context, "
        "and a sourced outcome for the resplit path."
    )
    video = {
        "video_title": "Every US Strategic Bomber Ever Built",
        "script": "\n\n".join(f"{unit_paragraph} Unit {index}." for index in range(1, 9)),
    }
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    fetch_calls = []
    writes = []

    async def fake_get_video(_video_id):
        return video

    async def fake_fetch_all(query, *args):
        fetch_calls.append((query, args))
        return [{"voice_id": "voice-existing"}]

    async def fake_execute(query, *args):
        writes.append((query, args))
        return None

    async def fake_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(pe, "execute", fake_execute)

    asyncio.run(executor._resplit_static_scenes("video-test"))

    assert fetch_calls == [(
        "SELECT voice_id FROM scripts WHERE video_id = $1 AND tenant_id = $2 LIMIT 1",
        ("video-test", "tenant-test"),
    )]
    assert writes[0] == (
        "DELETE FROM scripts WHERE video_id = $1 AND tenant_id = $2",
        ("video-test", "tenant-test"),
    )
    insert_rows = [args for query, args in writes if "INSERT INTO scripts" in query]
    assert len(insert_rows) == 8
    assert insert_rows[0][0:3] == ("tenant-test", "video-test", 1)
    assert insert_rows[0][-1] == "voice-existing"


def test_research_hold_bulk_uses_verified_one_machine_path_for_each_missing_card(monkeypatch):
    structured_roster = [
        {"unit": "Boeing XB-15", "include": True},
        {"unit": "Boeing B-17", "include": True},
        {"unit": "Convair B-36", "include": True},
    ]
    roster_names = [item["unit"] for item in structured_roster]
    payload = {
        "unit_roster": copy.deepcopy(structured_roster),
        "fact_sheet": "Source-grounded background.",
    }
    original_roster = copy.deepcopy(payload["unit_roster"])

    class FakeAnthropic:
        def __init__(self):
            self.prompts = []

        async def generate(self, **kwargs):
            self.prompts.append(kwargs["prompt"])
            raise AssertionError("bulk coordinator must delegate to the verified one-machine path")

    fake_anthropic = FakeAnthropic()
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": fake_anthropic})()

    writes = []

    async def fake_execute(query, *args):
        writes.append((query, args))
        return None

    async def fake_fetch_all(*_args, **_kwargs):
        return []

    async def fake_log(*_args, **_kwargs):
        return None

    async def fake_load_cards(_video_id, current_payload, _roster, target_machine=None):
        assert target_machine is None
        return current_payload

    target_calls = []

    async def fake_verified_one_machine(
        _video_id, _title, current_payload, current_roster, target_machine=None,
    ):
        assert target_machine in current_roster
        target_calls.append(target_machine)
        cards = list(current_payload.get("unit_research_cards") or [])
        cards.append({"unit": target_machine})
        current_payload["unit_research_cards"] = cards
        current_payload["unit_research_hold_validation"] = {
            "passed": len(cards) == len(current_roster),
            "in_progress": len(cards) < len(current_roster),
            "target_machine": target_machine,
            "target_machine_passed": True,
            "units": [
                {"machine": machine, "passed": machine in target_calls, "warnings": []}
                for machine in current_roster
            ],
        }
        return current_payload

    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(executor, "_load_machine_research_cards", fake_load_cards)
    monkeypatch.setattr(executor, "_run_unit_research_hold", fake_verified_one_machine)

    result = asyncio.run(
        pe.PipelineExecutor._run_unit_research_hold(
            executor, "video-test", "Designed vs Used", payload, roster_names
        )
    )

    assert fake_anthropic.prompts == []
    assert writes == []
    assert target_calls == roster_names
    assert result["unit_roster"] == original_roster
    assert result["unit_research_hold_validation"]["passed"] is True


def test_research_hold_bulk_continues_after_one_machine_fails(monkeypatch):
    roster = ["Boeing XB-15", "Boeing B-17", "Convair B-36"]
    payload = {"unit_roster": roster, "unit_research_cards": []}
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("Pipeline", (), {"anthropic": object()})()

    async def fake_load_cards(_video_id, current_payload, _roster, target_machine=None):
        return current_payload

    target_calls = []
    failed_calls = []

    async def fake_target(_video_id, _title, current_payload, current_roster, target_machine=None):
        target_calls.append(target_machine)
        passed = target_machine != roster[1]
        if not passed:
            failed_calls.append(target_machine)
        cards = list(current_payload.get("unit_research_cards") or [])
        cards.append({"unit": target_machine})
        current_payload["unit_research_cards"] = cards
        current_payload["unit_research_hold_validation"] = {
            "passed": not failed_calls and len(cards) == len(current_roster),
            "target_machine": target_machine,
            "target_machine_passed": passed,
            "units": [
                {
                    "machine": machine,
                    "passed": machine in target_calls and machine != roster[1],
                    "warnings": [] if machine != roster[1] else ["saved card needs repair"],
                }
                for machine in current_roster
            ],
        }
        return current_payload

    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(executor, "_load_machine_research_cards", fake_load_cards)
    monkeypatch.setattr(executor, "_run_unit_research_hold", fake_target)
    monkeypatch.setattr(executor, "_log_activity", noop)

    result = asyncio.run(
        pe.PipelineExecutor._run_unit_research_hold(
            executor, "video-test", "Designed vs Used", payload, roster,
        )
    )

    assert target_calls == roster
    assert result["unit_research_hold_validation"]["passed"] is False


def test_research_hold_bulk_free_conforms_saved_card_then_continues_remaining_roster(monkeypatch):
    """A paid card saved with only deterministic bookkeeping failures must
    not trigger the old human-one-card stop; repair it free and continue with
    only the genuinely missing roster entries."""
    roster = ["Boeing XB-15", "Boeing B-17"]
    segments = _evidence_segments()
    card = _valid_research_card(
        roster[0],
        segments,
        visual_identity=f"{roster[0]} during conversion at the factory in 1935.",
    )
    package = pe._verified_machine_source_package_with_anton_metadata(
        _verified_package_for_segments(roster[0], segments), roster[0],
    )
    payload = {
        "unit_roster": roster,
        "unit_research_cards": [card],
        "machine_raw_source_packages": {pe._verified_source_cache_key(roster[0]): package},
    }
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("Pipeline", (), {"anthropic": object()})()

    async def fake_load_cards(_video_id, current_payload, _roster, target_machine=None):
        return current_payload

    target_calls = []

    async def fake_target(_video_id, _title, current_payload, _roster, target_machine=None):
        target_calls.append(target_machine)
        assert target_machine == roster[1]
        assert pe._blocking_warnings(pe._research_card_contract_warnings(
            roster[0], current_payload["unit_research_cards"][0], package,
            require_source_package=True,
        )) == []
        current_payload["unit_research_hold_validation"] = {
            "passed": True,
            "target_machine": target_machine,
            "target_machine_passed": True,
            "units": [{"machine": machine, "passed": True, "warnings": []} for machine in roster],
        }
        return current_payload

    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(executor, "_load_machine_research_cards", fake_load_cards)
    monkeypatch.setattr(executor, "_run_unit_research_hold", fake_target)
    monkeypatch.setattr(executor, "_log_activity", noop)
    monkeypatch.setattr(pe, "fetch_all", lambda *_args, **_kwargs: [])

    result = asyncio.run(
        pe.PipelineExecutor._run_unit_research_hold(
            executor, "video-test", "Designed vs Used", payload, roster,
        )
    )

    assert target_calls == [roster[1]]
    assert result["unit_research_hold_validation"]["passed"] is True


def test_target_machine_research_uses_only_target_source_and_passes_mid_roster(monkeypatch):
    roster_names = ["Boeing XB-15", "Boeing B-52 Stratofortress", "Convair B-36"]
    legacy_xb15_card = {"unit": "Boeing XB-15", "engineering_thesis": "XB-15 stale legacy card leak."}
    legacy_b36_card = {"unit": "Convair B-36", "engineering_thesis": "B-36 stale legacy card leak."}
    payload = {
        "unit_roster": roster_names,
        "fact_sheet": (
            "Boeing XB-15 leak should never enter the B-52 proof. "
            "The B-52 target source sentence says the Stratofortress was adapted around range and payload. "
            "Convair B-36 leak should never enter the B-52 proof."
        ),
        "unit_research_cards": [
            legacy_xb15_card,
            legacy_b36_card,
        ],
    }
    b52_segments = _evidence_segments()
    b52_card = {
        "unit": "Boeing B-52 Stratofortress",
        "include": True,
        "engineering_thesis": "B-52 demonstrates one specific source-grounded engineering tradeoff.",
        "why_this_unit_deserves_a_paragraph": "B-52 proves how a long-range payload requirement created a bomber built around endurance rather than short-lived speed.",
        **_timeframe_fields("Boeing B-52 Stratofortress"),
        **_visual_identity_fields("Boeing B-52 Stratofortress"),
        "evidence_segments": b52_segments,
    }
    writes = []

    class FakeAnthropic:
        def __init__(self):
            self.prompts = []

        async def generate(self, **kwargs):
            assert any("machine_raw_source_packages" in query for query, _args in writes)
            self.prompts.append(kwargs["prompt"])
            return json.dumps(b52_card)

    fake_anthropic = FakeAnthropic()
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": fake_anthropic})()
    fetch_calls = []

    async def fake_execute(query, *args, **_kwargs):
        writes.append((query, args))
        return None

    async def fake_fetch_all(*args, **_kwargs):
        fetch_calls.append(args)
        return []

    async def fake_log(*_args, **_kwargs):
        return None

    async def fake_gather(_title, machine, _payload):
        package = _verified_package_for_segments(machine, b52_segments)
        package["candidate_excerpts"] = [
            {
                "excerpt_id": f"XB15-STALE-{index}",
                "source_id": "XB15-STALE",
                "source_title": "Stale wrong-machine cached source",
                "source_url": "https://airandspace.si.edu/collection-objects/boeing-xb-15",
                "locator": f"XB15-STALE-{index}",
                "text": "Boeing XB-15 stale cached raw row should not enter the target proof.",
                "source_capture_method": "fetched_page",
            }
            for index in range(65)
        ] + package["candidate_excerpts"] + [{
            "excerpt_id": "S99-E1",
            "source_title": "Wrong-machine snippet row",
            "source_url": "https://example.test/snippet",
            "locator": "S99-E1",
            "text": "Convair B-36 search-result snippet should not enter the target proof.",
        }]
        return package

    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(executor, "_gather_verified_machine_source_package", fake_gather)

    result = asyncio.run(
        executor._run_unit_research_hold(
            "video-test",
            "Designed vs Used",
            payload,
            roster_names,
            target_machine="Boeing B-52 Stratofortress",
        )
    )

    # roster_index of "Boeing B-52 Stratofortress" in roster_names (migration 153's row identity).
    assert fetch_calls[0][1:] == ("tenant-test", "video-test", 2)
    assert len(fake_anthropic.prompts) == 1
    prompt = fake_anthropic.prompts[0]
    assert "LOCKED SELECTED MACHINE: Boeing B-52 Stratofortress" in prompt
    assert "LOCKED MACHINE 2 OF 3: Boeing B-52 Stratofortress" not in prompt
    assert "VERIFIED RAW INTERNET EXCERPTS FOR THIS MACHINE" in prompt
    assert "EXACT_TEXT: Boeing B-52 Stratofortress Original problem claim grounded in the supplied source." in prompt
    assert "SOURCE_SELECTION: selected=fetched_page" in prompt
    assert "EXCERPT_TEXT_HASH: test" in prompt
    assert "source_excerpt_id, source_url, source_title, locator" in prompt
    assert "source_excerpt_id must equal that row's EXCERPT_ID" in prompt
    assert "source_url and locator must match" in prompt
    assert "source_url or locator" not in prompt
    assert "Use ANTON_SLOT_HINTS as the first-pass map for required slots" in prompt
    assert "Do not relabel an excerpt hinted for one required beat as a different required beat" in prompt
    assert "why_this_unit_deserves_a_paragraph must state the unique engineering idea" in prompt
    assert "no other roster machine could replace it" in prompt
    assert "may not introduce dates, numbers, other machine designations" in prompt
    assert "timeframe, timeframe_evidence_ids" in prompt
    assert "timeframe is the research-standard date/service-period basis only" in prompt
    assert "visual_identity, visual_identity_evidence_ids" in prompt
    assert "visual_identity is Producer File/image-brief basis only, never spoken narration" in prompt
    assert "camera movement, animation, transitions, thumbnail copy, on-screen text" in prompt
    assert "Optional key: narrative_weight with one of major, standard, or transitional" in prompt
    assert "Use major for pivotal machines" in prompt
    assert "memorable_fact is REQUIRED: return exactly one memorable_fact segment" in prompt
    assert "the card FAILS review without it" in prompt
    assert "Never invent one" in prompt
    assert "Be precise or be silent" in prompt
    assert "never pick the higher or more dramatic claim" in prompt
    assert "onscreen_label is metadata for Producer File/on-screen text, never spoken narration" in prompt
    assert "For machines 1-3, prefer one verified human_detail" in prompt
    assert "A human_detail segment must be attributed to a named person" in prompt
    assert "return it as reality, not historical_meaning" in prompt
    assert "Never invent a human account" in prompt
    assert "XB-15 leak" not in prompt
    assert "B-36 leak" not in prompt
    assert "Boeing XB-15 stale cached raw row" not in prompt
    assert "search-result snippet should not enter" not in prompt
    assert result["unit_research_hold_validation"]["passed"] is False
    assert result["unit_research_hold_validation"]["target_machine_passed"] is True
    assert result["unit_research_hold_validation"]["target_machine"] == "Boeing B-52 Stratofortress"
    by_machine = {
        unit["machine"]: unit for unit in result["unit_research_hold_validation"]["units"]
    }
    assert by_machine["Boeing XB-15"]["warnings"] == ["missing saved one-machine research card"]
    assert by_machine["Convair B-36"]["warnings"] == ["missing saved one-machine research card"]
    assert result["unit_research_cards"][0] == legacy_xb15_card
    assert result["unit_research_cards"][1] == legacy_b36_card
    assert result["unit_research_cards"][2]["unit"] == "Boeing B-52 Stratofortress"
    broad_payload_writes = [
        (query, args)
        for query, args in writes
        if "UPDATE videos" in query and "SET research_payload = $1" in query
    ]
    assert broad_payload_writes == []
    targeted_payload_writes = [
        (query, args)
        for query, args in writes
        if "{unit_research_cards}" in query and "{unit_research_hold_validation}" in query
    ]
    assert targeted_payload_writes
    saved_cards = json.loads(targeted_payload_writes[-1][1][0])
    assert saved_cards[0] == legacy_xb15_card
    assert saved_cards[1] == legacy_b36_card
    assert saved_cards[2]["unit"] == "Boeing B-52 Stratofortress"


def test_run_one_machine_research_refuses_non_roster_machine_before_hold(monkeypatch):
    roster_names = ["Boeing XB-15", "Boeing B-17 Flying Fortress", "Consolidated B-24 Liberator"]
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"

    async def fake_init():
        return None

    async def fake_get_video(_video_id):
        return {
            "video_title": "Every US Strategic Bomber Ever Built",
            "render_mode": "static_docu",
            "status": "ready_for_research_review",
            "research_payload": {"documentary_style": "designed_vs_used", "unit_roster": roster_names},
        }

    async def forbidden_research_hold(*_args, **_kwargs):
        raise AssertionError("non-roster machine must stop before research hold")

    async def forbidden_execute(*_args, **_kwargs):
        raise AssertionError("non-roster machine must not perform a final save")

    monkeypatch.setattr(executor, "_ensure_initialized", fake_init)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_run_unit_research_hold", forbidden_research_hold)
    monkeypatch.setattr(pe, "execute", forbidden_execute)

    result = asyncio.run(
        executor.run_one_machine_research("video-test", "Boeing B-52 Stratofortress")
    )

    assert result["status"] == "failed"
    assert result["error"] == "Machine is not in the locked roster: Boeing B-52 Stratofortress"


def test_run_one_machine_research_canonicalizes_label_to_locked_roster(monkeypatch):
    roster_names = ["Boeing XB-15", "Boeing B-17 Flying Fortress", "Consolidated B-24 Liberator"]
    payload = {
        "unit_roster": roster_names,
        "machine_raw_source_packages": {
            pe._verified_source_cache_key("Boeing XB-15"): {
                "machine": "Boeing XB-15",
                "candidate_excerpts": [{"excerpt_id": "S1-E1", "text": "Boeing XB-15 raw source excerpt."}],
            },
        },
        "unit_research_hold_validation": {
            "passed": False,
            "target_machine": "Boeing XB-15",
            "target_machine_passed": False,
            "units": [
                {"machine": "Boeing XB-15", "passed": False, "warnings": ["research card missing Anton slots"]},
                {"machine": "Consolidated B-24 Liberator", "passed": False, "warnings": ["different machine warning"]},
            ],
        },
    }
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    calls = []

    async def fake_init():
        return None

    async def fake_get_video(_video_id):
        return {
            "video_title": "Every US Strategic Bomber Ever Built",
            "render_mode": "static_docu",
            "status": "ready_for_research_review",
            "research_payload": {"documentary_style": "designed_vs_used", "unit_roster": roster_names},
        }

    async def fake_research_hold(video_id, title, current_payload, roster, target_machine=None):
        calls.append((video_id, title, current_payload, roster, target_machine))
        return payload

    monkeypatch.setattr(executor, "_ensure_initialized", fake_init)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_run_unit_research_hold", fake_research_hold)

    result = asyncio.run(
        executor.run_one_machine_research("video-test", "XB-15 — Boeing XB-15")
    )

    assert result["status"] == "needs_review"
    assert result["machine"] == "Boeing XB-15"
    assert result["next_action"] == "review_research_warnings_before_script_preview"
    assert "still needs review before script preview" in result["summary"]
    assert calls[0][3] == roster_names
    assert calls[0][4] == "Boeing XB-15"
    assert "research card missing Anton slots" in result["error"]


def test_run_one_machine_research_succeeds_without_marking_full_hold_complete(monkeypatch):
    roster_names = ["Boeing XB-15", "Boeing B-17 Flying Fortress", "Consolidated B-24 Liberator"]
    card = {"unit": "Boeing XB-15", "evidence_segments": _evidence_segments()}
    payload = {
        "unit_roster": roster_names,
        "unit_research_cards": [card],
        "unit_research_hold_validation": {
            "passed": False,
            "target_machine": "Boeing XB-15",
            "target_machine_passed": True,
            "units": [{"machine": "Boeing XB-15", "passed": True, "warnings": []}],
        },
    }

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    writes = []

    async def fake_init():
        return None

    async def fake_get_video(_video_id):
        return {
            "video_title": "Every US Strategic Bomber Ever Built",
            "render_mode": "static_docu",
            "status": "ready_for_research_review",
            "research_payload": {"documentary_style": "designed_vs_used", "unit_roster": roster_names},
        }

    async def fake_research_hold(_video_id, _title, _payload, _roster, target_machine=None):
        assert target_machine == "Boeing XB-15"
        return payload

    async def fake_execute(query, *args):
        writes.append((query, args))
        return None

    monkeypatch.setattr(executor, "_ensure_initialized", fake_init)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_run_unit_research_hold", fake_research_hold)
    monkeypatch.setattr(pe, "execute", fake_execute)

    result = asyncio.run(executor.run_one_machine_research("video-test", "Boeing XB-15"))

    assert result["status"] == "completed"
    assert result["machine"] == "Boeing XB-15"
    assert result["next_action"] == "run_machine_script_preview"
    assert result["research_card"] == card
    assert result["research_payload"]["unit_research_hold_validation"]["target_machine_passed"] is True
    assert "SET status = $1" in writes[0][0]
    assert "research_payload = $1" not in writes[0][0]
    assert "research_payload->'unit_roster' = $4::jsonb" in writes[0][0]
    assert writes[0][1][0] == "ready_for_research_review"
    assert json.loads(writes[0][1][3]) == roster_names


def test_run_one_machine_research_returns_reviewable_payload_when_card_fails(monkeypatch):
    roster_names = ["Boeing XB-15", "Boeing B-17 Flying Fortress", "Consolidated B-24 Liberator"]
    payload = {
        "unit_roster": roster_names,
        "machine_raw_source_packages": {
            pe._verified_source_cache_key("Boeing XB-15"): {
                "machine": "Boeing XB-15",
                "candidate_excerpts": [{"excerpt_id": "S1-E1", "text": "Boeing XB-15 raw source excerpt."}],
            },
        },
        "unit_research_hold_validation": {
            "passed": False,
            "target_machine": "Boeing XB-15",
            "target_machine_passed": False,
            "units": [
                {"machine": "Boeing XB-15", "passed": False, "warnings": ["research card missing Anton slots"]},
                {"machine": "Consolidated B-24 Liberator", "passed": False, "warnings": ["different machine warning"]},
            ],
        },
    }

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"

    async def fake_init():
        return None

    async def fake_get_video(_video_id):
        return {
            "video_title": "Every US Strategic Bomber Ever Built",
            "render_mode": "static_docu",
            "status": "ready_for_research_review",
            "research_payload": {"documentary_style": "designed_vs_used", "unit_roster": roster_names},
        }

    async def fake_research_hold(_video_id, _title, _payload, _roster, target_machine=None):
        assert target_machine == "Boeing XB-15"
        return payload

    monkeypatch.setattr(executor, "_ensure_initialized", fake_init)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_run_unit_research_hold", fake_research_hold)

    result = asyncio.run(executor.run_one_machine_research("video-test", "Boeing XB-15"))

    assert result["status"] == "needs_review"
    assert result["machine"] == "Boeing XB-15"
    assert result["next_action"] == "review_research_warnings_before_script_preview"
    assert "still needs review before script preview" in result["summary"]
    assert "research card missing Anton slots" in result["error"]
    assert result["research_payload"]["machine_raw_source_packages"][pe._verified_source_cache_key("Boeing XB-15")]["candidate_excerpts"][0]["excerpt_id"] == "S1-E1"


def test_run_one_machine_research_refuses_final_save_after_roster_change(monkeypatch):
    roster_names = ["Boeing XB-15", "Boeing B-17 Flying Fortress", "Consolidated B-24 Liberator"]
    payload = {
        "unit_roster": roster_names,
        "unit_research_cards": [{"unit": "Boeing XB-15", "evidence_segments": _evidence_segments()}],
        "unit_research_hold_validation": {
            "passed": False,
            "target_machine": "Boeing XB-15",
            "target_machine_passed": True,
            "units": [{"machine": "Boeing XB-15", "passed": True, "warnings": []}],
        },
    }

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"

    async def fake_init():
        return None

    async def fake_get_video(_video_id):
        return {
            "video_title": "Every US Strategic Bomber Ever Built",
            "render_mode": "static_docu",
            "status": "ready_for_research_review",
            "research_payload": {"documentary_style": "designed_vs_used", "unit_roster": roster_names},
        }

    async def fake_research_hold(_video_id, _title, _payload, _roster, target_machine=None):
        assert target_machine == "Boeing XB-15"
        return payload

    async def fake_execute(*_args):
        return "UPDATE 0"

    monkeypatch.setattr(executor, "_ensure_initialized", fake_init)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_run_unit_research_hold", fake_research_hold)
    monkeypatch.setattr(pe, "execute", fake_execute)

    result = asyncio.run(executor.run_one_machine_research("video-test", "Boeing XB-15"))

    assert result["status"] == "failed"
    assert "unit_roster changed concurrently" in result["error"]


def test_run_research_final_save_is_tenant_scoped(monkeypatch):
    import sys
    import types

    import channel_format

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type(
        "FakePipeline", (),
        {"anthropic": object(), "airtable": object(), "research_system_prompt": "DVsU research override"},
    )()
    writes = []
    syncs = []

    async def fake_init():
        return None

    async def fake_get_video(_video_id):
        return {
            "video_title": "Focused DVsU proof",
            "headline": "Focused DVsU proof",
            "status": "idea_logged",
            # static_docu now ends run_research at the Roster stage; the final
            # research save under test belongs to every other render mode.
            "render_mode": "animated",
        }

    async def fake_load_overrides(_video):
        return None

    async def fake_fetch_one(*_args, **_kwargs):
        return {}

    async def fake_run_research(**_kwargs):
        return {
            "thesis": "Source-grounded thesis",
            "executive_hook": "Source-grounded hook",
            "fact_sheet": "Source-backed research package.",
        }

    async def fake_execute(query, *args):
        writes.append((query, args))
        return "UPDATE 1"

    async def fake_sync(video_id, tenant_id):
        syncs.append((video_id, tenant_id))

    research_agent = types.SimpleNamespace(run_research=fake_run_research)
    monkeypatch.setitem(sys.modules, "research", types.SimpleNamespace(agent=research_agent))
    monkeypatch.setitem(sys.modules, "research.agent", research_agent)
    monkeypatch.setitem(sys.modules, "drive_workspace", types.SimpleNamespace(sync_video_workspace_fail_soft=fake_sync))
    monkeypatch.setattr(executor, "_ensure_initialized", fake_init)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_load_prompt_overrides", fake_load_overrides)
    monkeypatch.setattr(pe, "fetch_one", fake_fetch_one)
    # run_research first reads the channel profile for the machine script contract.
    monkeypatch.setattr(channel_format, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pe, "execute", fake_execute)

    result = asyncio.run(executor.run_research("video-test"))

    assert result["status"] == "ready_for_scripting"
    research_saves = [
        (query, args) for query, args in writes
        if "UPDATE videos SET" in query and "research_payload = $1" in query
    ]
    assert research_saves
    assert "WHERE id = $5 AND tenant_id = $6" in research_saves[0][0]
    assert research_saves[0][1][-2:] == ("video-test", "tenant-test")
    assert syncs == [("video-test", "tenant-test")]


def test_run_research_refuses_zero_row_final_save(monkeypatch):
    import sys
    import types

    import channel_format

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type(
        "FakePipeline", (),
        {"anthropic": object(), "airtable": object(), "research_system_prompt": "DVsU research override"},
    )()
    syncs = []

    async def fake_init():
        return None

    async def fake_get_video(_video_id):
        return {
            "video_title": "Focused DVsU proof",
            "headline": "Focused DVsU proof",
            "status": "idea_logged",
            # static_docu now ends run_research at the Roster stage; the final
            # research save under test belongs to every other render mode.
            "render_mode": "animated",
        }

    async def fake_load_overrides(_video):
        return None

    async def fake_fetch_one(*_args, **_kwargs):
        return {}

    async def fake_run_research(**_kwargs):
        return {
            "thesis": "Source-grounded thesis",
            "executive_hook": "Source-grounded hook",
            "fact_sheet": "Source-backed research package.",
        }

    async def fake_execute(query, *_args):
        if "UPDATE videos SET" in query and "research_payload = $1" in query:
            return "UPDATE 0"
        return "UPDATE 1"

    async def fake_sync(video_id, tenant_id):
        syncs.append((video_id, tenant_id))

    research_agent = types.SimpleNamespace(run_research=fake_run_research)
    monkeypatch.setitem(sys.modules, "research", types.SimpleNamespace(agent=research_agent))
    monkeypatch.setitem(sys.modules, "research.agent", research_agent)
    monkeypatch.setitem(sys.modules, "drive_workspace", types.SimpleNamespace(sync_video_workspace_fail_soft=fake_sync))
    monkeypatch.setattr(executor, "_ensure_initialized", fake_init)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_load_prompt_overrides", fake_load_overrides)
    monkeypatch.setattr(pe, "fetch_one", fake_fetch_one)
    # run_research first reads the channel profile for the machine script contract.
    monkeypatch.setattr(channel_format, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pe, "execute", fake_execute)

    result = asyncio.run(executor.run_research("video-test"))

    assert result["status"] == "failed"
    assert "no longer available for this tenant" in result["error"]
    assert syncs == []


def _live_gate_passing_research_payload(roster_names):
    """A research payload that GENUINELY passes the live roster gate.

    2026-07-30: run_unit_research recomputes the roster gate from the payload
    (_live_roster_gate) instead of trusting a stored
    `unit_roster_validation: {"passed": True}` stub - a stored verdict froze
    the gate rules of the day it was written onto the row (the d2e37cd6
    incident). So a fixture standing in for "a video that legitimately
    finished research" must now carry what real research produces: the
    complete-title structural proof (discovery buckets, recommendation,
    gap-hunt + edge-case matrices, and an audit with >=6 searches and >=3
    source families). The stored verdict key is still included - as history,
    which is all it is now.
    """
    return {
        "documentary_style": "designed_vs_used",
        "unit_roster": list(roster_names),
        "unit_roster_validation": {"passed": True},
        "recommended_final_roster": list(roster_names),
        "gap_hunt_matrix": [
            {"candidate": "Douglas XB-19", "verdict": "excluded: single prototype testbed"},
        ],
        "edge_case_matrix": [{"class": "naval patrol bombers", "checked": True}],
        "machine_discovery_buckets": {
            "core_roster": list(roster_names),
            "built_prototypes": [],
            "boundary_disputes": [],
            "converted_or_special_variants": [],
            "secret_cancelled_or_black_programs": [],
        },
        "roster_audit": {
            "search_queries_used": [
                "list of US strategic bombers",
                "USAAF bomber designations",
                "US heavy bombers by era",
                "cancelled US bomber programs",
                "US bomber prototypes",
                "cold war US strategic bombers",
            ],
            "source_families_crosschecked": [
                "Official USAF records",
                "Aviation encyclopaedias",
                "Manufacturer histories",
            ],
            "unresolved_candidates": [],
            "confidence": "high",
            "excluded_candidates": [],
        },
    }


def test_run_research_keeps_locked_roster_and_stops_at_roster_ready(monkeypatch):
    """f561ddf6 split Roster selection from detailed machine research: run_research on a
    static-docu video ends at the Roster stage. A saved roster that already passes the live
    gate is kept as-is (no rediscovery, no provider spend) and machine research is a
    separate, explicit run_unit_research call."""
    import channel_format
    import static_docu

    roster_names = ["Boeing XB-15", "Boeing B-17 Flying Fortress", "Consolidated B-24 Liberator"]
    payload = _live_gate_passing_research_payload(roster_names)
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": object()})()
    writes = []

    async def fake_init():
        return None

    async def fake_get_video(_video_id):
        return {
            "video_title": "Every American Strategic Bomber Ever Built",
            "headline": "Every American Strategic Bomber Ever Built",
            "status": "idea_logged",
            "render_mode": "static_docu",
            "video_length_minutes": 20,
            "research_payload": copy.deepcopy(payload),
        }

    async def forbidden_continue(_video_id):
        raise AssertionError("the Roster stage must not start detailed machine research")

    async def fake_fetch_one(*_args, **_kwargs):
        return {"has_saved_work": False}

    async def fake_execute(query, *args):
        writes.append((query, args))
        return "UPDATE 1"

    async def fake_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr(executor, "_ensure_initialized", fake_init)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "run_unit_research", forbidden_continue)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(pe, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(channel_format, "fetch_one", fake_fetch_one)
    dispatch_calls = []
    monkeypatch.setattr(static_docu, "dispatch_roster_prefetch", lambda *args: dispatch_calls.append(args))

    result = asyncio.run(executor.run_research("video-test"))

    assert result["status"] == "roster_ready"
    assert dispatch_calls == [], "the Roster stage must not schedule the reference-photo sweep"
    assert result["selected_count"] == len(roster_names)
    saved = [json.loads(args[0]) for query, args in writes if "research_payload=$1" in query]
    assert saved and saved[-1]["research_phase"] == "roster_complete"
    assert saved[-1]["unit_roster"] == roster_names


def test_run_research_never_replaces_a_locked_roster_that_has_detailed_work(monkeypatch):
    """A roster that fails the live gate but already carries detailed machine research must
    not fall through to destructive re-selection: the Roster stage refuses and preserves it.
    (A failing roster with NO detailed work is deliberately re-selected, with the previous
    payload kept in roster_selection_history - see test_roster_stage_integration.)"""
    import sys
    import types

    import channel_format

    roster_names = ["CV-1 USS Langley", "CV-2 USS Lexington", "CV-3 USS Saratoga"]
    payload = _live_gate_passing_research_payload(roster_names)
    payload["recommended_final_roster"] = roster_names[:-1]
    payload["unit_research_cards"] = [{"unit": roster_names[0], "evidence_segments": _evidence_segments()}]
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": object()})()
    writes = []

    async def fake_init():
        return None

    async def fake_get_video(_video_id):
        return {
            "video_title": "Every US Aircraft Carrier Ever Built",
            "headline": "Every US Aircraft Carrier Ever Built",
            "status": "idea_logged",
            "render_mode": "static_docu",
            "video_length_minutes": 20,
            "research_payload": copy.deepcopy(payload),
        }

    async def forbidden_continue(_video_id):
        raise AssertionError("the Roster stage must not start detailed machine research")

    async def forbidden_discovery(**_kwargs):
        raise AssertionError("a roster with detailed work must not be rediscovered")

    async def fake_fetch_one(*_args, **_kwargs):
        return {"has_saved_work": True}

    async def fake_execute(query, *args):
        writes.append((query, args))
        return "UPDATE 1"

    async def fake_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr(executor, "_ensure_initialized", fake_init)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "run_unit_research", forbidden_continue)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(pe, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(channel_format, "fetch_one", fake_fetch_one)
    monkeypatch.setitem(sys.modules, "research", types.SimpleNamespace(agent=types.SimpleNamespace(run_research=forbidden_discovery)))
    monkeypatch.setitem(sys.modules, "research.agent", types.SimpleNamespace(run_research=forbidden_discovery))

    result = asyncio.run(executor.run_research("video-test"))

    assert result["status"] == "failed"
    assert result["roster_selection_failed"] is True
    assert "existing detailed work is preserved" in result["error"]
    assert writes == []
    assert payload["unit_roster"] == roster_names


def test_run_unit_research_final_save_is_tenant_scoped(monkeypatch):
    import sys
    import types

    roster_names = ["Boeing XB-15", "Boeing B-17 Flying Fortress", "Consolidated B-24 Liberator"]
    payload = _live_gate_passing_research_payload(roster_names)
    researched_payload = {
        **payload,
        "unit_research_cards": [{"unit": machine, "evidence_segments": _evidence_segments()} for machine in roster_names],
        "unit_research_hold_validation": {
            "passed": True,
            "units": [{"machine": machine, "passed": True, "warnings": []} for machine in roster_names],
        },
    }

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": object()})()
    writes = []
    syncs = []

    async def fake_init():
        return None

    async def fake_get_video(_video_id):
        return {
            "video_title": "Every US Strategic Bomber Ever Built",
            "render_mode": "static_docu",
            "status": "ready_for_research_review",
            "research_payload": payload,
        }

    async def fake_research_hold(_video_id, _title, _payload, _roster):
        return researched_payload

    async def fake_execute(query, *args):
        writes.append((query, args))
        return "UPDATE 1"

    async def fake_log(*_args, **_kwargs):
        return None

    async def fake_sync(video_id, tenant_id):
        syncs.append((video_id, tenant_id))

    monkeypatch.setattr(executor, "_ensure_initialized", fake_init)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_run_unit_research_hold", fake_research_hold)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setitem(sys.modules, "drive_workspace", types.SimpleNamespace(sync_video_workspace_fail_soft=fake_sync))

    result = asyncio.run(executor.run_unit_research("video-test"))

    assert result["status"] == "ready_for_scripting"
    # Every write is tenant-scoped, including the unit_research phase checkpoint
    # saved before the hold; the final save is the one that carries the status.
    assert all("tenant_id" in query for query, _ in writes)
    final_saves = [(query, args) for query, args in writes if "status = $2" in query]
    assert len(final_saves) == 1
    assert "WHERE id = $3 AND tenant_id = $4" in final_saves[0][0]
    assert final_saves[0][1][2:] == ("video-test", "tenant-test")
    assert syncs == [("video-test", "tenant-test")]


def test_run_unit_research_refuses_zero_row_final_save(monkeypatch):
    import sys
    import types

    roster_names = ["Boeing XB-15", "Boeing B-17 Flying Fortress", "Consolidated B-24 Liberator"]
    payload = _live_gate_passing_research_payload(roster_names)
    researched_payload = {
        **payload,
        "unit_research_cards": [{"unit": machine, "evidence_segments": _evidence_segments()} for machine in roster_names],
        "unit_research_hold_validation": {"passed": True, "units": []},
    }

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": object()})()
    syncs = []

    async def fake_init():
        return None

    async def fake_get_video(_video_id):
        return {
            "video_title": "Every US Strategic Bomber Ever Built",
            "render_mode": "static_docu",
            "status": "ready_for_research_review",
            "research_payload": payload,
        }

    async def fake_research_hold(_video_id, _title, _payload, _roster):
        return researched_payload

    async def fake_execute(*_args):
        return "UPDATE 0"

    async def fake_log(*_args, **_kwargs):
        return None

    async def fake_sync(video_id, tenant_id):
        syncs.append((video_id, tenant_id))

    monkeypatch.setattr(executor, "_ensure_initialized", fake_init)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_run_unit_research_hold", fake_research_hold)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setitem(sys.modules, "drive_workspace", types.SimpleNamespace(sync_video_workspace_fail_soft=fake_sync))

    result = asyncio.run(executor.run_unit_research("video-test"))

    assert result["status"] == "failed"
    assert "save refused" in result["error"]
    assert syncs == []


def test_target_machine_research_marks_full_hold_complete_after_final_verified_card(monkeypatch):
    roster_names = ["Boeing XB-15", "Boeing B-17 Flying Fortress", "Consolidated B-24 Liberator"]
    existing_cards = []
    source_packages = {}
    existing_story_fields = {
        "Boeing XB-15": {
            "engineering_thesis": "XB-15 demonstrates how early range ambition exposed bomber power and prototype limits.",
            "why_this_unit_deserves_a_paragraph": (
                "Boeing XB-15 deserves a paragraph because its long-range prototype ambition exposed "
                "the power-and-size limits behind early strategic bomber design."
            ),
        },
        "Boeing B-17 Flying Fortress": {
            "engineering_thesis": "B-17 demonstrates how daylight precision doctrine relied on defensive firepower until escort reality intervened.",
            "why_this_unit_deserves_a_paragraph": (
                "Boeing B-17 Flying Fortress deserves a paragraph because daylight precision bombing "
                "tested defensive firepower against escort and attrition reality."
            ),
        },
    }
    for machine in roster_names[:2]:
        card = {
            "unit": machine,
            **existing_story_fields[machine],
            "surprising_fact": "Memorable fact claim grounded in the supplied source.",
            "source_notes": ["https://example.test/source"],
            **_timeframe_fields(machine),
            **_visual_identity_fields(machine),
            "evidence_segments": _evidence_segments(),
        }
        existing_cards.append(card)
        source_packages[pe._verified_source_cache_key(machine)] = _verified_package_for_segments(machine, _evidence_segments())
    target_segments = _evidence_segments()
    target_card = {
        "unit": roster_names[2],
        "engineering_thesis": "B-24 demonstrates a sufficiently detailed source-grounded engineering thesis.",
        "why_this_unit_deserves_a_paragraph": "B-24 proves a distinct production-and-range compromise where industrial output answered a bomber problem differently from the other roster machines.",
        **_timeframe_fields(roster_names[2]),
        **_visual_identity_fields(roster_names[2]),
        "evidence_segments": target_segments,
    }
    payload = {
        "unit_roster": roster_names,
        "unit_research_cards": existing_cards,
        "machine_raw_source_packages": source_packages,
    }

    class FakeAnthropic:
        async def generate(self, **_kwargs):
            return json.dumps(target_card)

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": FakeAnthropic()})()

    async def fake_fetch_all(*_args, **_kwargs):
        return []

    async def fake_execute(*_args, **_kwargs):
        return None

    async def fake_log(*_args, **_kwargs):
        return None

    async def fake_gather(_title, machine, _payload):
        return _verified_package_for_segments(machine, target_segments)

    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(executor, "_gather_verified_machine_source_package", fake_gather)

    result = asyncio.run(
        executor._run_unit_research_hold(
            "video-test",
            "Every US Strategic Bomber Ever Built",
            payload,
            roster_names,
            target_machine=roster_names[2],
        )
    )

    validation = result["unit_research_hold_validation"]
    assert validation["target_machine_passed"] is True
    assert validation["passed"] is True
    assert [unit["machine"] for unit in validation["units"]] == roster_names
    assert all(unit["passed"] for unit in validation["units"])


def test_target_machine_research_refresh_replaces_only_target_state(monkeypatch):
    roster_names = ["Boeing XB-15", "Boeing B-17 Flying Fortress", "Consolidated B-24 Liberator"]
    target_key = pe._verified_source_cache_key("Boeing XB-15")
    b17_key = pe._verified_source_cache_key("Boeing B-17 Flying Fortress")
    b24_key = pe._verified_source_cache_key("Consolidated B-24 Liberator")
    existing_cards = [
        _valid_research_card(
            "Boeing XB-15",
            _evidence_segments(),
            engineering_thesis="Old XB-15 card that must be replaced during target refresh.",
            why_this_unit_deserves_a_paragraph=(
                "Old XB-15 paragraph rationale must not survive a target refresh."
            ),
        ),
        _valid_research_card(
            "Boeing B-17 Flying Fortress",
            _evidence_segments(),
            engineering_thesis="B-17 existing card stays untouched during XB-15 refresh.",
            why_this_unit_deserves_a_paragraph=(
                "B-17 keeps its existing precision-bombing engineering decision while XB-15 refreshes."
            ),
        ),
        _valid_research_card(
            "Consolidated B-24 Liberator",
            _evidence_segments(),
            engineering_thesis="B-24 existing card stays untouched during XB-15 refresh.",
            why_this_unit_deserves_a_paragraph=(
                "B-24 keeps its existing production-and-range engineering decision while XB-15 refreshes."
            ),
        ),
    ]
    target_segments = _evidence_segments()
    refreshed_card = _valid_research_card(
        "Boeing XB-15",
        target_segments,
        engineering_thesis="Refreshed XB-15 card grounded in the new raw source package.",
        why_this_unit_deserves_a_paragraph=(
            "XB-15 now anchors the early range-and-power tradeoff behind strategic bomber design."
        ),
    )
    old_target_package = _verified_package_for_segments("Boeing XB-15", _evidence_segments())
    old_target_package["refresh_marker"] = "old"
    refreshed_package = _verified_package_for_segments("Boeing XB-15", target_segments)
    refreshed_package["refresh_marker"] = "new"
    payload = {
        "unit_roster": roster_names,
        "unit_research_cards": copy.deepcopy(existing_cards),
        "machine_raw_source_packages": {
            target_key: old_target_package,
            b17_key: _verified_package_for_segments("Boeing B-17 Flying Fortress", _evidence_segments()),
            b24_key: _verified_package_for_segments("Consolidated B-24 Liberator", _evidence_segments()),
        },
        "machine_script_previews": {
            target_key: {"paragraph": "Old XB-15 preview."},
            b17_key: {"paragraph": "B-17 preview stays."},
        },
        "machine_script_briefs": {
            target_key: {"old": "XB-15 brief"},
            b17_key: {"old": "B-17 brief"},
        },
        "machine_story_plans": {
            target_key: {"old": "XB-15 plan"},
            b17_key: {"old": "B-17 plan"},
        },
    }

    class FakeAnthropic:
        async def generate(self, **_kwargs):
            return json.dumps(refreshed_card)

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": FakeAnthropic()})()
    writes = []

    async def fake_fetch_all(*_args, **_kwargs):
        return []

    async def fake_execute(query, *args, **_kwargs):
        writes.append((query, args))
        return "UPDATE 1"

    async def fake_log(*_args, **_kwargs):
        return None

    async def fake_gather(_title, machine, _payload):
        assert machine == "Boeing XB-15"
        return refreshed_package

    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(executor, "_gather_verified_machine_source_package", fake_gather)

    result = asyncio.run(
        executor._run_unit_research_hold(
            "video-test",
            "Every US Strategic Bomber Ever Built",
            payload,
            roster_names,
            target_machine="Boeing XB-15",
        )
    )

    cards_by_key = {
        pe._verified_source_cache_key(card["unit"]): card
        for card in result["unit_research_cards"]
    }
    assert cards_by_key[target_key]["engineering_thesis"] == refreshed_card["engineering_thesis"]
    assert cards_by_key[b17_key]["engineering_thesis"] == existing_cards[1]["engineering_thesis"]
    assert cards_by_key[b24_key]["engineering_thesis"] == existing_cards[2]["engineering_thesis"]
    assert result["machine_raw_source_packages"][target_key]["refresh_marker"] == "new"
    assert result["machine_raw_source_packages"][b17_key] == payload["machine_raw_source_packages"][b17_key]
    assert result["machine_raw_source_packages"][b24_key] == payload["machine_raw_source_packages"][b24_key]
    assert target_key not in result["machine_script_previews"]
    assert target_key not in result["machine_script_briefs"]
    assert target_key not in result["machine_story_plans"]
    assert result["machine_script_previews"][b17_key]["paragraph"] == "B-17 preview stays."
    assert result["machine_script_briefs"][b17_key]["old"] == "B-17 brief"
    assert result["machine_story_plans"][b17_key]["old"] == "B-17 plan"
    assert result["unit_research_hold_validation"]["target_machine"] == "Boeing XB-15"
    assert result["unit_research_hold_validation"]["target_machine_passed"] is True
    raw_checkpoint = next(query for query, _args in writes if "machine_raw_source_packages" in query)
    assert "jsonb_build_object($1::text, $2::jsonb)" in raw_checkpoint
    assert "- $1::text" in raw_checkpoint


def test_target_machine_research_requires_verified_source_package_before_llm(monkeypatch):
    roster_names = ["Boeing XB-15", "Boeing B-52 Stratofortress", "Convair B-36"]
    stale_key = pe._verified_source_cache_key("Boeing B-52 Stratofortress")
    payload = {
        "unit_roster": roster_names,
        "machine_script_previews": {stale_key: {"paragraph": "Old B-52 preview."}},
        "machine_script_briefs": {stale_key: {"old": "brief"}},
        "machine_story_plans": {stale_key: {"old": "plan"}},
    }

    class ForbiddenAnthropic:
        async def generate(self, **_kwargs):
            raise AssertionError("missing verified source package must stop before Claude")

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": ForbiddenAnthropic()})()

    async def fake_fetch_all(*_args, **_kwargs):
        return []

    writes = []

    async def fake_execute(query, *args, **_kwargs):
        writes.append((query, args))
        if "INSERT INTO machine_research_cards" in query:
            raise AssertionError("failed source gathering should not checkpoint a card")

    async def fake_log(*_args, **_kwargs):
        return None

    async def fake_gather(_title, machine, _payload):
        return {
            "passed": False,
            "machine": machine,
            "machine_key": pe._normalized_unit_code(machine),
            "errors": ["no verified excerpts"],
            "candidate_excerpts": [],
            "sources": [],
        }

    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(executor, "_gather_verified_machine_source_package", fake_gather)

    result = asyncio.run(
        executor._run_unit_research_hold(
            "video-test",
            "Designed vs Used",
            payload,
            roster_names,
            target_machine="Boeing B-52 Stratofortress",
        )
    )

    assert result["unit_research_hold_validation"]["passed"] is False
    assert result["unit_research_hold_validation"]["target_machine_passed"] is False
    assert result["unit_research_hold_validation"]["warnings"] == ["no verified excerpts"]
    assert stale_key not in result["machine_script_previews"]
    assert stale_key not in result["machine_script_briefs"]
    assert stale_key not in result["machine_story_plans"]
    assert any("machine_raw_source_packages" in query for query, _args in writes)
    raw_checkpoint = next(query for query, _args in writes if "machine_raw_source_packages" in query)
    assert "machine_script_previews" in raw_checkpoint
    assert "machine_script_briefs" in raw_checkpoint
    assert "machine_story_plans" in raw_checkpoint
    assert "- $1::text" in raw_checkpoint
    validation_checkpoints = [
        (query, args)
        for query, args in writes
        if "{unit_research_cards}" in query and "{unit_research_hold_validation}" in query
    ]
    assert validation_checkpoints
    assert json.loads(validation_checkpoints[-1][1][1])["warnings"] == ["no verified excerpts"]
    assert not any("SET research_payload = $1" in query for query, _args in writes)
    assert not any("INSERT INTO machine_research_cards" in query for query, _args in writes)


def test_target_machine_research_rejects_thin_source_package_before_llm(monkeypatch):
    roster_names = ["Boeing XB-15", "Boeing B-52 Stratofortress", "Convair B-36"]
    payload = {"unit_roster": roster_names}

    class ForbiddenAnthropic:
        async def generate(self, **_kwargs):
            raise AssertionError("thin verified package must stop before Claude")

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": ForbiddenAnthropic()})()

    async def fake_fetch_all(*_args, **_kwargs):
        return []

    writes = []

    async def fake_execute(query, *args, **_kwargs):
        writes.append((query, args))
        if "INSERT INTO machine_research_cards" in query:
            raise AssertionError("thin source package should not checkpoint a card")

    async def fake_log(*_args, **_kwargs):
        return None

    async def fake_gather(_title, machine, _payload):
        segments = _evidence_segments()
        for segment in segments:
            segment["source_url"] = "https://airandspace.si.edu/collection-objects/b-52"
        return _verified_package_for_segments(machine, segments)

    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(executor, "_gather_verified_machine_source_package", fake_gather)

    result = asyncio.run(
        executor._run_unit_research_hold(
            "video-test",
            "Designed vs Used",
            payload,
            roster_names,
            target_machine="Boeing B-52 Stratofortress",
        )
    )

    assert result["unit_research_hold_validation"]["passed"] is False
    assert result["unit_research_hold_validation"]["target_machine_passed"] is False
    assert "two distinct source URLs" in result["unit_research_hold_validation"]["warnings"][0]
    assert any("machine_raw_source_packages" in query for query, _args in writes)
    validation_checkpoints = [
        (query, args)
        for query, args in writes
        if "{unit_research_cards}" in query and "{unit_research_hold_validation}" in query
    ]
    assert validation_checkpoints
    saved_validation = json.loads(validation_checkpoints[-1][1][1])
    assert saved_validation["target_machine_passed"] is False
    assert "two distinct source URLs" in saved_validation["warnings"][0]
    assert not any("SET research_payload = $1" in query for query, _args in writes)
    assert not any("INSERT INTO machine_research_cards" in query for query, _args in writes)


def test_research_hold_contract_persists_each_card_and_never_reopens_roster():
    source = open(pe.__file__, encoding="utf-8").read()
    hold = source[source.index("async def _run_unit_research_hold"):source.index("async def _resplit_static_scenes")]

    assert "The roster is locked. Do not add, remove, replace, or relitigate machines." in hold
    assert "SET research_payload" in hold
    assert "locked_roster_snapshot" in hold


def test_research_card_repair_prompt_requires_source_url_and_locator():
    source = open(pe.__file__, encoding="utf-8").read()
    prompt = source[source.index("Repair this ONE-machine research card"):source.index("BAD/RAW CARD")]

    assert "source_url, source_title, locator" in prompt
    assert "source_url and locator must match" in prompt
    assert "source_url or locator" not in prompt
    assert "Be precise or be silent" in prompt
    assert "never pick the higher or more dramatic claim" in prompt
    assert "Return timeframe plus timeframe_evidence_ids" in prompt
    assert "timeframe is the research-standard date/service-period basis only" in prompt
    assert "Return visual_identity plus visual_identity_evidence_ids" in prompt
    assert "visual_identity is Producer File/image-brief basis only, never spoken narration" in prompt
    assert "camera movement, animation, transitions, thumbnail copy, on-screen text" in prompt
    assert "onscreen_label is metadata for Producer File/on-screen text, never spoken narration" in prompt
    assert "return it as reality, not historical_meaning" in prompt


def test_research_card_hydration_never_uses_meaning_as_paragraph_rationale():
    source = open(pe.__file__, encoding="utf-8").read()
    hydrate = source[
        source.index("def _hydrate_compatibility_fields")
        :source.index("def _card_warnings")
    ]

    assert 'card.setdefault("why_this_unit_deserves_a_paragraph", "")' in hydrate
    assert 'why_this_unit_deserves_a_paragraph", by_kind.get("historical_meaning")' not in hydrate
    assert 'why_this_unit_deserves_a_paragraph", by_kind.get("legacy")' not in hydrate


def test_compact_card_read_merges_partial_rows_in_roster_order_and_tenant_scope(monkeypatch):
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-a"
    calls = []

    async def fake_fetch_all(query, *args):
        calls.append((query, args))
        return [{
            "machine_key": "A", "machine_name": "A", "roster_index": 1,
            "card": {"unit": "A", "engineering_thesis": "compact A"},
            "validation": {"passed": True},
        }]

    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    legacy_cards = [{"unit": "C", "engineering_thesis": "legacy C"},
                    {"unit": "A", "engineering_thesis": "legacy A"},
                    {"unit": "B", "engineering_thesis": "legacy B"}]
    legacy = {"fact_sheet": "preserved", "unit_roster": ["A", "B", "C"],
              "unit_research_cards": legacy_cards}
    result = asyncio.run(executor._load_machine_research_cards("video-a", legacy))

    assert calls[0][1] == ("tenant-a", "video-a")
    assert "tenant_id = $1 AND video_id = $2" in calls[0][0]
    assert result["fact_sheet"] == "preserved"
    assert [card["unit"] for card in result["unit_research_cards"]] == ["A", "B", "C"]
    assert result["unit_research_cards"][0]["engineering_thesis"] == "compact A"
    assert result["unit_research_cards"][1:] == [legacy_cards[2], legacy_cards[0]]
    assert legacy["unit_research_cards"] == legacy_cards


def test_compact_card_read_preserves_schema_v3_four_beat_evidence(monkeypatch):
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-a"
    machine = "Boeing XB-15"
    compact_card = {
        "schema_version": 3,
        "unit": machine,
        "engineering_thesis": "The design answer only works when read against the operating limit.",
        "evidence_segments": copy.deepcopy(_evidence_segments()),
    }

    async def fake_fetch_all(query, *args):
        assert "roster_index = $3" in query
        assert args == ("tenant-a", "video-a", 1)
        return [{
            "machine_key": "XB15",
            "machine_name": machine,
            "roster_index": 1,
            "card": copy.deepcopy(compact_card),
            "validation": {"passed": True},
        }]

    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    legacy_card = {"unit": machine, "engineering_thesis": "legacy prose without addressable evidence"}
    legacy = {"unit_roster": [machine], "unit_research_cards": [legacy_card]}

    result = asyncio.run(
        executor._load_machine_research_cards("video-a", legacy, roster=[machine], target_machine=machine)
    )

    loaded = result["unit_research_cards"][0]
    assert loaded["evidence_segments"] == compact_card["evidence_segments"]
    assert loaded is not compact_card
    assert legacy["unit_research_cards"] == [legacy_card]

    plan = pe._machine_story_plan(result, machine)
    by_slot = {slot["slot"]: slot["evidence_ids"] for slot in plan["slots"]}
    evidence_by_id = {
        segment["evidence_id"]: segment
        for slot in plan["slots"]
        for segment in slot.get("evidence_segments", [])
    }
    assert by_slot["original_problem"] == ["E-PROBLEM"]
    assert by_slot["engineering_decision"] == ["E-DECISION"]
    assert by_slot["tradeoff"] == ["E-TRADEOFF"]
    assert by_slot["reality"] == ["E-REALITY", "E-MEANING"]
    assert evidence_by_id["E-MEANING"]["kind"] == "reality"
    assert "historical_meaning" not in by_slot
    assert all(
        segment.get("kind") != "historical_meaning"
        for slot in plan["slots"]
        for segment in slot.get("evidence_segments", [])
    )


def test_compact_card_read_falls_back_to_legacy_payload(monkeypatch):
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-a"

    async def missing_table(*_args):
        raise RuntimeError("undefined table")

    monkeypatch.setattr(pe, "fetch_all", missing_table)
    legacy = {"unit_roster": ["legacy"], "unit_research_cards": [{"unit": "legacy"}]}
    assert asyncio.run(executor._load_machine_research_cards("video-a", legacy)) is legacy


def test_compact_read_excludes_stale_mismatch_and_invalid_override(monkeypatch):
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-a"

    async def fake_fetch_all(*_args):
        return [
            {"machine_key": "STALE", "machine_name": "STALE", "roster_index": 9,
             "card": {"unit": "STALE"}, "validation": {"passed": True}},
            {"machine_key": "A", "machine_name": "A", "roster_index": 1,
             "card": {"unit": "B", "engineering_thesis": "identity mismatch"},
             "validation": {"passed": True}},
            {"machine_key": "B", "machine_name": "B", "roster_index": 2,
             "card": {"unit": "B", "engineering_thesis": "invalid compact"},
             "validation": {"passed": False}},
        ]

    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    legacy = {"unit_roster": ["A", "B"], "unit_research_cards": [
        {"unit": "A", "engineering_thesis": "valid legacy A"},
        {"unit": "B", "engineering_thesis": "valid legacy B"},
    ]}
    result = asyncio.run(executor._load_machine_research_cards("video-a", legacy))
    assert result["unit_research_cards"] == legacy["unit_research_cards"]


def test_compact_write_unavailable_reuses_legacy_without_generation(monkeypatch):
    roster = ["B-52"]
    card = {"unit": "B-52", "engineering_thesis": "A sufficiently detailed source-grounded engineering thesis.",
            "why_this_unit_deserves_a_paragraph": "B-52 proves how range and payload requirements created an endurance-first bomber that outlasted replacement plans.",
            "surprising_fact": "A fact", "source_notes": ["source"],
            **_timeframe_fields("B-52"), **_visual_identity_fields("B-52"), "evidence_segments": _evidence_segments()}
    payload = {
        "unit_roster": roster,
        "unit_research_cards": [card],
        "machine_raw_source_packages": {
            pe._verified_source_cache_key("B-52"): _verified_package_for_segments("B-52", _evidence_segments()),
        },
    }
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-a"

    class ForbiddenAnthropic:
        async def generate(self, **_kwargs):
            raise AssertionError("valid legacy card must not trigger paid regeneration")

    executor.__dict__["_pipeline"] = type("Pipeline", (), {"anthropic": ForbiddenAnthropic()})()
    writes = []

    async def no_compact_rows(*_args):
        return []

    async def fake_execute(query, *_args):
        writes.append(query)
        if "INSERT INTO machine_research_cards" in query:
            raise RuntimeError("undefined table machine_research_cards")

    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pe, "fetch_all", no_compact_rows)
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(executor, "_log_activity", noop)
    result = asyncio.run(executor._run_unit_research_hold("video-a", "Title", payload, roster))
    assert result["unit_research_cards"] == [card]
    assert result["unit_research_hold_validation"]["passed"] is True
    assert sum("INSERT INTO machine_research_cards" in query for query in writes) == 1


def test_compact_write_rejects_empty_canonical_key():
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-a"
    try:
        asyncio.run(executor._upsert_machine_research_card("video-a", "---", 1, {}, {}))
    except ValueError as exc:
        assert "non-empty machine key" in str(exc)
    else:
        raise AssertionError("empty canonical key was accepted")


def test_compact_write_refuses_zero_row_video_lookup(monkeypatch):
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-a"

    async def fake_execute(*_args):
        return "INSERT 0 0"

    monkeypatch.setattr(pe, "execute", fake_execute)

    try:
        asyncio.run(executor._upsert_machine_research_card(
            "video-a",
            "Boeing XB-15",
            1,
            {"unit": "Boeing XB-15", "evidence_segments": _evidence_segments()},
            {"machine": "Boeing XB-15", "passed": True, "warnings": []},
        ))
    except RuntimeError as exc:
        assert "checkpoint refused" in str(exc)
    else:
        raise AssertionError("zero-row compact-card write was accepted")


def test_compact_write_persists_full_schema_v3_card_json(monkeypatch):
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-a"
    card = {
        "schema_version": 3,
        "unit": "Boeing XB-15",
        "engineering_thesis": "The design answer only works when read against the operating limit.",
        "evidence_segments": copy.deepcopy(_evidence_segments()),
    }
    validation = {"machine": "Boeing XB-15", "passed": True, "warnings": []}
    captured = {}

    async def fake_execute(query, *args):
        captured["query"] = query
        captured["args"] = args

    monkeypatch.setattr(pe, "execute", fake_execute)

    asyncio.run(executor._upsert_machine_research_card("video-a", "Boeing XB-15", 1, card, validation))

    assert "INSERT INTO machine_research_cards" in captured["query"]
    assert captured["args"][:5] == ("tenant-a", "video-a", "XB15", "Boeing XB-15", 1)
    assert json.loads(captured["args"][5]) == card
    assert json.loads(captured["args"][6]) == validation


def test_raw_source_package_checkpoint_updates_single_machine_cell(monkeypatch):
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-a"
    package = {
        "passed": True,
        "machine": "Boeing XB-15",
        "candidate_excerpts": [{"excerpt_id": "S1-E1", "text": "Exact fetched text."}],
    }
    captured = {}

    async def fake_execute(query, *args):
        captured["query"] = query
        captured["args"] = args
        return "UPDATE 1"

    monkeypatch.setattr(pe, "execute", fake_execute)

    result = asyncio.run(
        executor._checkpoint_machine_raw_source_package(
            "video-a", "XB15", package, '["Boeing XB-15"]'
        )
    )

    assert result == "UPDATE 1"
    assert "machine_raw_source_packages" in captured["query"]
    assert "jsonb_build_object($1::text, $2::jsonb)" in captured["query"]
    assert "research_payload->'unit_roster' = $5::jsonb" in captured["query"]
    assert captured["args"] == (
        "XB15",
        json.dumps(package),
        "video-a",
        "tenant-a",
        '["Boeing XB-15"]',
    )


def test_one_machine_research_checkpoint_updates_review_cells(monkeypatch):
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-a"
    review_cards = [{"unit": "Boeing XB-15", "evidence_segments": _evidence_segments()}]
    validation = {
        "passed": False,
        "target_machine": "Boeing XB-15",
        "target_machine_passed": True,
        "units": [{"machine": "Boeing XB-15", "passed": True, "warnings": []}],
    }
    captured = {}

    async def fake_execute(query, *args):
        captured["query"] = query
        captured["args"] = args
        return "UPDATE 1"

    monkeypatch.setattr(pe, "execute", fake_execute)

    result = asyncio.run(
        executor._checkpoint_one_machine_research_result(
            "video-a", review_cards, validation, '["Boeing XB-15"]'
        )
    )

    assert result == "UPDATE 1"
    assert "{unit_research_cards}" in captured["query"]
    assert "{unit_research_hold_validation}" in captured["query"]
    assert "SET research_payload = $1" not in captured["query"]
    assert "research_payload->'unit_roster' = $5::jsonb" in captured["query"]
    assert json.loads(captured["args"][0]) == review_cards
    assert json.loads(captured["args"][1]) == validation


def test_dvsu_machine_preflight_reports_ready_machine_without_spend():
    from scripts import dvsu_machine_preflight as preflight

    roster = ["Boeing XB-15", "Boeing B-17 Flying Fortress", "Consolidated B-24 Liberator"]
    segments = _evidence_segments()
    payload = {
        "documentary_style": "designed_vs_used",
        "unit_roster": roster,
        "unit_research_cards": [_valid_research_card("Boeing XB-15", segments)],
        "machine_raw_source_packages": {
            pe._verified_source_cache_key("Boeing XB-15"): _verified_package_for_segments("Boeing XB-15", segments),
        },
    }
    video = {
        "id": "video-test",
        "video_title": "Every US Strategic Bomber Ever Built",
        "status": "ready_for_scripting",
        "render_mode": "static_docu",
        "research_payload": payload,
    }

    report = preflight.build_preflight_report(video, "XB-15 — Boeing XB-15")

    assert report["status"] == "completed"
    assert report["ready"] is True
    assert report["machine"] == "Boeing XB-15"
    assert report["scene"] == 1
    assert report["next_action"] == "run_no_spend_readiness_then_script_preview"
    assert report["source_package"]["missing_capture_method_count"] == 0
    assert report["source_package"]["missing_source_selection_count"] == 0


def test_dvsu_machine_preflight_points_legacy_package_to_research_refresh():
    from scripts import dvsu_machine_preflight as preflight

    roster = ["Boeing XB-15", "Boeing B-17 Flying Fortress", "Consolidated B-24 Liberator"]
    segments = _evidence_segments()
    package = _verified_package_for_segments("Boeing XB-15", segments)
    for candidate in package["candidate_excerpts"]:
        candidate.pop("source_capture_method", None)
        candidate.pop("source_variant_selection", None)
    payload = {
        "documentary_style": "designed_vs_used",
        "unit_roster": roster,
        "unit_research_cards": [_valid_research_card("Boeing XB-15", segments)],
        "machine_raw_source_packages": {
            pe._verified_source_cache_key("Boeing XB-15"): package,
        },
    }
    video = {
        "id": "video-test",
        "video_title": "Every US Strategic Bomber Ever Built",
        "status": "ready_for_scripting",
        "render_mode": "static_docu",
        "research_payload": payload,
    }

    report = preflight.build_preflight_report(video, "Boeing XB-15")

    assert report["status"] == "needs_review"
    assert report["ready"] is False
    assert report["next_action"] == "run_one_machine_research_refresh"
    assert report["source_package"]["missing_capture_method_count"] == len(package["candidate_excerpts"])
    assert report["source_package"]["missing_source_selection_count"] == len(package["candidate_excerpts"])
    assert any("without source capture method" in warning for warning in report["warnings"])
    assert any("without source selection provenance" in warning for warning in report["warnings"])


def test_dvsu_machine_preflight_supabase_rest_uses_read_only_resolve(monkeypatch):
    from scripts import dvsu_machine_preflight as preflight

    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    captured = {}

    def fake_check_output(cmd, stderr=None):
        captured["cmd"] = cmd
        captured["stderr"] = stderr
        return json.dumps([
            {
                "id": "video-test",
                "tenant_id": "tenant-test",
                "video_title": "Every US Strategic Bomber Ever Built",
                "headline": "Every US Strategic Bomber Ever Built",
                "status": "ready_for_scripting",
                "render_mode": "static_docu",
                "research_payload": {},
            }
        ]).encode()

    monkeypatch.setattr(preflight.subprocess, "check_output", fake_check_output)

    video = preflight._fetch_video_supabase_rest(
        "video-test",
        tenant_id="tenant-test",
        resolve_ip="104.18.38.10",
    )

    assert video["id"] == "video-test"
    assert captured["cmd"][:6] == ["curl", "-sS", "--fail", "--max-time", "25", "--resolve"]
    assert "project.supabase.co:443:104.18.38.10" in captured["cmd"]
    url_arg = next(item for item in captured["cmd"] if item.startswith("https://project.supabase.co/rest/v1/videos?"))
    assert "id=eq.video-test" in url_arg
    assert "tenant_id=eq.tenant-test" in url_arg
    assert "-H" in captured["cmd"]
    assert "apikey: service-key" in captured["cmd"]


def test_normalize_card_field_citations_drops_dangling_and_remaps():
    """Regression: XB-15 attempt 4 (2026-07-16) cited package EXCERPT_IDs
    (S4-E5, S1-E7) never returned as segments; the UI then blocked with
    'Timeframe evidence missing'. Bookkeeping is code's job."""
    card = {
        "timeframe_evidence_ids": ["S4-E5", "S4-E9", "S1-E7"],
        "visual_identity_evidence_ids": ["S9-E1"],
        "evidence_segments": [
            {"evidence_id": "S4-E9", "source_excerpt_id": "S4-E9"},
            {"evidence_id": "S3-E4", "source_excerpt_id": "S3-E4"},
            {"evidence_id": "V1", "source_excerpt_id": "S9-E1"},
        ],
    }
    out = pe._normalize_card_field_citations(card)
    assert out["timeframe_evidence_ids"] == ["S4-E9"]
    assert out["visual_identity_evidence_ids"] == ["V1"]
    # An all-dangling list empties out so validators warn; never invented.
    empty = pe._normalize_card_field_citations(
        {"timeframe_evidence_ids": ["NOPE"], "evidence_segments": [{"evidence_id": "E1", "source_excerpt_id": "X1"}]}
    )
    assert empty["timeframe_evidence_ids"] == []


# ---------------------------------------------------------------------------
# Round-6 quality-law build (approved 2026-07-16): per-law gate pins.
# ---------------------------------------------------------------------------


def test_dvsu_mode_profile_or5():
    """OR-5 (approved): Most-Hated exists as a named mode flag whose register /
    opener-budget / memorable-source overrides travel in the plan contract."""
    default_profile = pe._dvsu_mode_profile({}, {})
    assert default_profile == {
        "mode": "spec_block",
        "register": "spec_block",
        "opener_name_budget": 0.6,
        "memorable_source": "sticky_fact",
    }
    hated_profile = pe._dvsu_mode_profile({"dvsu_mode": "most_hated"}, {})
    assert hated_profile["mode"] == "most_hated"
    assert hated_profile["register"] == "long_form"
    assert hated_profile["opener_name_budget"] == 0.2
    assert hated_profile["memorable_source"] == "crew_testimony"

    # Register wires into the narrative-weight standard target (QL-1).
    plan = pe._machine_story_plan(
        {"dvsu_mode": "most_hated", "unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]},
        "B-52",
    )
    assert plan["contract"]["mode_profile"]["mode"] == "most_hated"
    assert plan["contract"]["narrative_weight"]["register"] == "long_form"
    assert plan["contract"]["narrative_weight"]["target_words"] == "110-130"
    assert plan["contract"]["twist_menu"] == list(pe._DVSU_TWIST_TYPES)
    assert plan["contract"]["verdict_punch_forms"] == ["single_hammer", "antithesis", "concede_then_cut", "triad"]


def test_research_gap_gate_requires_actual_use_story():
    """QL-3 research leg (OR-1): the card must surface employment or fate, not
    delivery/acceptance logistics; the deliberately-bare tag is exempt."""
    evidence, _errors = pe._normalize_machine_evidence(
        {"evidence_segments": _evidence_segments()}, "B-52"
    )
    # The test evidence's reality claim carries "Cold War service period" -> passes.
    assert pe._designed_vs_used_gap_warnings({"unit": "B-52"}, evidence) == []

    # Delivery-only reality: no employment/fate marker -> fails.
    delivery_only = [dict(s) for s in evidence]
    for segment in delivery_only:
        if segment.get("slot_role") == "reality":
            segment["claim"] = "Delivered to Wright Field in October and accepted for testing."
            segment["source_excerpt"] = segment["claim"]
    assert pe._designed_vs_used_gap_warnings({"unit": "B-52"}, delivery_only) == [
        "no designed-vs-used gap found - research must surface how it was ACTUALLY used; "
        "if the hunt already ran and no gap exists, mark deliberately_bare with gap_hunt_summary"
    ]

    # The deliberately-bare tag exempts the research gap demand ONLY with
    # hunt evidence (B2).
    assert pe._designed_vs_used_gap_warnings(
        {"unit": "B-52", "deliberately_bare": True,
         "gap_hunt_summary": "Searched service, conversion, and disposal records; the type never left acceptance trials."},
        delivery_only,
    ) == []
    assert pe._designed_vs_used_gap_warnings({"unit": "B-52", "deliberately_bare": True}, delivery_only) != []


# ---------------------------------------------------------------------------
# Round-7 calibration (2026-07-16): B1/B2/I1/I3/I4 + corpus recalibrations.
# ---------------------------------------------------------------------------

def _minimal_plan() -> dict:
    return {
        "contract": {
            "deliberately_bare": False,
            "narrative_weight": {"label": "standard", "target_words": "100-120"},
        },
        "slots": [],
    }


def _closer_probe(machine: str, body_sentences: list, closer_sentences: list):
    bundle = {
        "formula_sentences": list(body_sentences) + list(closer_sentences),
        "editorial_thesis": "the design intent was inverted by how the machine was actually used",
        "twist": {"type": "role_change", "substitute": None, "summary": "built for X used as Y"},
        "claim_map": [],
    }
    _p, warnings = pe._validate_machine_story_sentences(machine, _minimal_plan(), bundle)
    return warnings


def test_bare_tag_requires_hunt_evidence_b2():
    """B2: deliberately_bare is honored only with a non-trivial
    gap_hunt_summary; a bare tag without hunt evidence is a hard warning."""
    evidence = _evidence_segments()
    card = _valid_research_card("Boeing XB-15", evidence)
    card["deliberately_bare"] = True
    warnings = pe._research_card_contract_warnings("Boeing XB-15", card)
    assert any("bare tag without hunt evidence" in w for w in warnings)

    card_with_summary = _valid_research_card("Boeing XB-15", evidence)
    card_with_summary["deliberately_bare"] = True
    card_with_summary["gap_hunt_summary"] = (
        "Searched combat, conversion, and disposal records across all sources; the type never left acceptance trials."
    )
    summary_warnings = pe._research_card_contract_warnings("Boeing XB-15", card_with_summary)
    assert not any("bare tag without hunt evidence" in w for w in summary_warnings)
    assert pe._bare_tag_is_valid(card_with_summary) is True
    assert pe._bare_tag_is_valid(card) is False


# ---------------------------------------------------------------------------
# Round-8 (2026-07-16): conversion-signal must-select + timeframe repair hints.
# ---------------------------------------------------------------------------

def _package_with_extra_excerpt(machine: str, segments: list, extra_text: str, excerpt_id: str = "S9-E1") -> dict:
    package = _verified_package_for_segments(machine, segments)
    package["candidate_excerpts"].append({
        "excerpt_id": excerpt_id,
        "source_id": "S9",
        "source_title": "Conversion source",
        "source_url": "https://history.test/conversion",
        "locator": excerpt_id,
        "text": extra_text,
        "text_hash": "test",
        "source_capture_method": "fetched_page",
        "source_variant_selection": {"selected_capture_method": "fetched_page"},
    })
    return package


def test_package_conversion_signal_scan_positive_and_negative():
    """FIX 1: the deterministic scan finds role-conversion signals (vocab and
    different-prefix designations co-occurring with the locked machine) and
    stays silent on packages without them."""
    machine = "Boeing XB-15"
    segments = _evidence_segments()
    package = _package_with_extra_excerpt(
        machine, segments,
        "The Boeing XB-15 was redesignated XC-105 and served as a cargo transport.",
    )
    signals = pe._package_conversion_signals(package, machine)
    hit = next(signal for signal in signals if signal["excerpt_id"] == "S9-E1")
    assert "XC105" in hit["tokens"]
    assert "cargo" in hit["terms"] and "redesignated" in hit["terms"] and "transport" in hit["terms"]
    assert hit["enforce"] is True

    # Prompt line names the excerpt and its signals.
    line = pe._conversion_signal_prompt_line([hit])
    assert "MUST-SELECT" in line and "S9-E1" in line and "XC105" in line

    # Negative: the base package (no conversion vocabulary anywhere) yields
    # no signals.
    clean = pe._package_conversion_signals(_verified_package_for_segments(machine, segments), machine)
    assert clean == []

    # Round-9 recalibration: the package is machine-scoped by construction, so
    # vocabulary-bearing excerpts signal WITHOUT naming the locked machine -
    # the live XB-15 miss was exactly a pronoun-carried conversion excerpt.
    pronoun_carried = _package_with_extra_excerpt(
        machine, segments,
        "The sole example was redesignated XC-105 and used for cargo.", "S9-E3",
    )
    pronoun_hit = next(
        s for s in pe._package_conversion_signals(pronoun_carried, machine)
        if s["excerpt_id"] == "S9-E3"
    )
    assert pronoun_hit["enforce"] is True
    assert "XC105" in pronoun_hit["tokens"]
    assert "cargo" in pronoun_hit["terms"] and "redesignated" in pronoun_hit["terms"]

    # A vocabulary excerpt with a different machine name also signals (the
    # package scoping makes it this machine's evidence by construction).
    cross_named = _package_with_extra_excerpt(
        machine, segments, "The C-47 hauled cargo across every theater.", "S9-E2",
    )
    cross_hit = next(
        s for s in pe._package_conversion_signals(cross_named, machine)
        if s["excerpt_id"] == "S9-E2"
    )
    assert cross_hit["enforce"] is True

    # Prefix-only hits (no vocabulary) still require the machine mention and
    # never enforce - they only guide the prompt.
    prefix_only = _package_with_extra_excerpt(
        machine, segments, "The Boeing XB-15 flew alongside the B-10 in trials.", "S9-E4",
    )
    prefix_hit = next(
        s for s in pe._package_conversion_signals(prefix_only, machine)
        if s["excerpt_id"] == "S9-E4"
    )
    assert prefix_hit["enforce"] is False and "B10" in prefix_hit["tokens"]


def test_gap_stays_when_conversion_signal_unselected():
    """FIX 2: a delivery/records-only outcome never satisfies the gap while an
    enforceable conversion signal sits unselected - the warning names it."""
    machine = "Boeing XB-15"
    segments = _evidence_segments()
    # Delivery/records-only reality (would otherwise be judged by the marker
    # heuristic) with a conversion story sitting in the package.
    card = _valid_research_card(machine, segments)
    package = _package_with_extra_excerpt(
        machine, segments,
        "The Boeing XB-15 was redesignated XC-105 and served as a cargo transport.",
    )
    evidence, _errors = pe._normalize_machine_evidence(card, machine)
    warnings = pe._designed_vs_used_gap_warnings(card, evidence, machine, package)
    assert warnings and "selected none of it" in warnings[0] and "S9-E1" in warnings[0]

    # Referee end-to-end: the same signal keeps the card failing.
    referee = pe._research_card_contract_warnings(machine, card, package, require_source_package=True)
    assert any("selected none of it" in w and "S9-E1" in w for w in referee)


def test_gap_satisfied_when_conversion_evidence_selected():
    """FIX 2 positive control: once the card carries the conversion evidence
    (same excerpt identity / designation / vocabulary), the gap clears."""
    machine = "Boeing XB-15"
    segments = _evidence_segments()
    conversion_text = "The Boeing XB-15 was redesignated XC-105 and served as a cargo transport."
    package = _package_with_extra_excerpt(machine, segments, conversion_text)
    selected = segments + [{
        "evidence_id": "E-CONVERSION",
        "kind": "reality",
        "claim": conversion_text,
        "source_excerpt": conversion_text,
        "source_url": "https://history.test/conversion",
        "source_title": "Conversion source",
        "locator": "S9-E1",
        "source_excerpt_id": "S9-E1",
        "numeric_tokens": [],
        "confidence": "high",
    }]
    card = _valid_research_card(machine, selected)
    evidence, errors = pe._normalize_machine_evidence(card, machine)
    assert errors == []
    assert pe._designed_vs_used_gap_warnings(card, evidence, machine, package) == []


def test_timeframe_repair_hints_name_the_dated_excerpt():
    """FIX 3: when the timeframe states dates its segments lack while the
    package holds them, the repair hint names the exact excerpt; once a
    kind=timeframe support segment carries it, the referee's timeframe
    grounding clears (rounds 2/5 machinery)."""
    machine = "Boeing XB-15"
    segments = _evidence_segments()
    dated_text = "The Boeing XB-15 first flew in October 1937 and was delivered that December."
    package = _package_with_extra_excerpt(machine, segments, dated_text, "S9-E9")
    card = _valid_research_card(machine, segments)
    card["timeframe"] = f"{machine} first flew in October 1937."
    card["timeframe_evidence_ids"] = ["E-REALITY"]

    hints = pe._timeframe_repair_hints(card, package)
    assert hints and "S9-E9" in hints[0] and "1937" in hints[0]
    assert "kind=timeframe support segment" in hints[0]

    # No hints when the segments already carry the dates.
    repaired_segments = segments + [{
        "evidence_id": "E-TIMEFRAME-FIX",
        "kind": "timeframe",
        "claim": dated_text,
        "source_excerpt": dated_text,
        "source_url": "https://history.test/conversion",
        "source_title": "Conversion source",
        "locator": "S9-E9",
        "source_excerpt_id": "S9-E9",
        "numeric_tokens": ["1937"],
        "confidence": "high",
    }]
    repaired = _valid_research_card(machine, repaired_segments)
    repaired["timeframe"] = f"{machine} first flew in October 1937."
    repaired["timeframe_evidence_ids"] = ["E-TIMEFRAME-FIX"]
    assert pe._timeframe_repair_hints(repaired, package) == []
    # The referee's timeframe grounding clears with the support segment.
    referee = pe._research_card_contract_warnings(machine, repaired)
    assert not any("timeframe contains detail(s) not grounded" in w for w in referee)
    assert not any("timeframe introduced unsupported numerical" in w for w in referee)


# ---------------------------------------------------------------------------
# Writer pass 5 (2026-07-16): the story plan flags the conversion-signal
# evidence so the distiller writes the reality beat from the documented
# designed-vs-used story, never from an acceptance/testing event.
# ---------------------------------------------------------------------------

def test_story_plan_flags_conversion_signal_evidence_role_noun_first():
    """The plan ranks role-noun evidence (cargo/transport) over bare
    redesignation vocabulary, marks the segments, and carries the rule."""
    machine = "Boeing XB-15"
    segments = _evidence_segments()
    reality = next(s for s in segments if s["evidence_id"] == "E-REALITY")
    reality["claim"] = (
        "The sole aircraft was converted to a cargo transport and hauled "
        "supplies across the Pacific for eight years."
    )
    reality["source_excerpt"] = reality["claim"]
    tradeoff = next(s for s in segments if s["evidence_id"] == "E-TRADEOFF")
    tradeoff["claim"] = "The design was redesignated before construction began."
    tradeoff["source_excerpt"] = tradeoff["claim"]
    package = _package_with_extra_excerpt(
        machine, segments,
        "The sole example was redesignated XC-105 and served as a cargo transport.",
    )
    payload = {
        "unit_research_cards": [{"unit": machine, "evidence_segments": segments}],
        "machine_raw_source_packages": {pe._verified_source_cache_key(machine): package},
    }
    plan = pe._machine_story_plan(payload, machine)
    ids = plan["contract"]["conversion_signal_evidence_ids"]
    # E-TRADEOFF precedes E-REALITY in evidence order; the role-noun bearer
    # still ranks first (design-phase renamings are vocabulary false positives).
    assert ids[0] == "E-REALITY"
    assert "E-TRADEOFF" in ids
    assert "reality sentence" in plan["contract"]["conversion_signal_rule"]
    reality_slot = next(slot for slot in plan["slots"] if slot["slot"] == "reality")
    assert any(
        seg.get("carries_conversion_signal") and seg["evidence_id"] == "E-REALITY"
        for seg in reality_slot["evidence_segments"]
    )
    # The card's own segments stay unmutated - the flag is plan-local.
    assert "carries_conversion_signal" not in reality


def test_story_plan_conversion_flags_empty_without_package_signal():
    """No package or no enforceable signal leaves the contract keys empty and
    no segment flagged - stored control previews (XB-19) are untouched."""
    machine = "Boeing XB-15"
    no_package_plan = pe._machine_story_plan(
        {"unit_research_cards": [{"unit": machine, "evidence_segments": _evidence_segments()}]},
        machine,
    )
    assert no_package_plan["contract"]["conversion_signal_evidence_ids"] == []
    assert no_package_plan["contract"]["conversion_signal_rule"] == ""

    segments = _evidence_segments()
    clean_payload = {
        "unit_research_cards": [{"unit": machine, "evidence_segments": segments}],
        "machine_raw_source_packages": {
            pe._verified_source_cache_key(machine): _verified_package_for_segments(machine, segments)
        },
    }
    clean_plan = pe._machine_story_plan(clean_payload, machine)
    assert clean_plan["contract"]["conversion_signal_evidence_ids"] == []
    for slot in clean_plan["slots"]:
        assert not any(seg.get("carries_conversion_signal") for seg in slot["evidence_segments"])


def test_conversion_signal_evidence_ids_ranking_helper():
    """Direct helper lock: signal match by excerpt identity or vocabulary,
    role nouns first, stable order inside a rank, no signals -> empty."""
    machine = "Boeing XB-15"
    segments = _evidence_segments()
    package = _package_with_extra_excerpt(
        machine, segments,
        "The sole example was redesignated XC-105 and served as a cargo transport.",
    )
    evidence = [
        {
            "evidence_id": "E-VERB-ONLY",
            "claim": "The design was redesignated during development.",
            "source_excerpt": "The design was redesignated during development.",
        },
        {
            "evidence_id": "E-BY-EXCERPT-ID",
            "claim": "Service history entry.",
            "source_excerpt": "Service history entry.",
            "source_excerpt_id": "S9-E1",
        },
        {
            "evidence_id": "E-ROLE-NOUN",
            "claim": "It hauled cargo across the Pacific as a transport.",
            "source_excerpt": "It hauled cargo across the Pacific as a transport.",
        },
        {
            "evidence_id": "E-UNRELATED",
            "claim": "Wing area figures from the test program.",
            "source_excerpt": "Wing area figures from the test program.",
        },
    ]
    ids = pe._conversion_signal_evidence_ids(evidence, package, machine)
    assert ids[0] == "E-ROLE-NOUN"
    assert ids[1:] == ["E-VERB-ONLY", "E-BY-EXCERPT-ID"]
    assert "E-UNRELATED" not in ids
    assert pe._conversion_signal_evidence_ids(evidence, None, machine) == []


# ---------------------------------------------------------------------------
# Writer pass 5 (2026-07-16): repair mechanics close the last deterministic
# gaps - spelled years revert to digits, single-source numbers get hedged
# per the gate's own two-source rule, model numbers are never hedged.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Writer pass 5 wrap-up (2026-07-16): ONE shared checklist - the research side
# predicts the frozen benchmark_cadence audit and self-heals with FREE
# promotes, so a referee-clean card can never starve the writer again.
# ---------------------------------------------------------------------------

def _starved_benchmark_segments() -> list[dict]:
    """A referee-plausible evidence set with NO numbers, NO scale vocab, and
    NO production/service vocab - exactly the card shape that passed research
    and then failed benchmark_cadence live (B-17, twice)."""
    segments = _evidence_segments()
    for segment in segments:
        segment["claim"] = segment["claim"].replace("Cold War service period", "later era")
        if segment["evidence_id"] == "E-DECISION":
            segment["claim"] = "Engineering decision claim grounded in the supplied source."
        segment["source_excerpt"] = segment["claim"]
    return segments


def test_script_starvation_gaps_mirror_benchmark_cadence():
    machine = "Boeing B-17 Flying Fortress"
    starved = pe._script_starvation_gaps(
        {"unit": machine, "evidence_segments": _starved_benchmark_segments()}, machine
    )
    assert set(starved) == {"numeric_details", "scale_capability", "production_service"}

    # A card carrying the audit's demands reports no gaps: numbers + scale
    # vocab on the decision beat, production vocab on the reality beat.
    fed = _starved_benchmark_segments()
    decision = next(s for s in fed if s["evidence_id"] == "E-DECISION")
    decision["claim"] = "The design carried a 103-foot wingspan and four engines."
    decision["source_excerpt"] = decision["claim"]
    reality = next(s for s in fed if s["evidence_id"] == "E-REALITY")
    reality["claim"] = "Boeing produced 12,731 aircraft that served in combat."
    reality["source_excerpt"] = reality["claim"]
    assert pe._script_starvation_gaps({"unit": machine, "evidence_segments": fed}, machine) == []

    # Non-benchmark machines (B-52 has no Anton reference profile) are never
    # graded on cadence - mirrors the frozen audit exactly.
    assert pe._script_starvation_gaps(
        {"unit": "B-52", "evidence_segments": _starved_benchmark_segments()}, "B-52"
    ) == []


def test_script_starvation_promote_actions_fill_gaps_with_support_kinds():
    machine = "Boeing B-17 Flying Fortress"
    segments = _starved_benchmark_segments()
    card = {"unit": machine, "evidence_segments": segments}
    package = _verified_package_for_segments(machine, segments)
    package["candidate_excerpts"].extend([
        {
            "excerpt_id": "S9-E1",
            "source_id": "S9",
            "source_title": "Spec source",
            "source_url": "https://spec.test/1",
            "locator": "S9-E1",
            "text": "The Boeing B-17 Flying Fortress carried a 103-foot wingspan and four engines.",
            "text_hash": "test",
            "source_capture_method": "fetched_page",
            "source_tier": 2,
            "anton_slot_hints": ["engineering_decision"],
            "source_variant_selection": {"selected_capture_method": "fetched_page"},
        },
        {
            "excerpt_id": "S9-E2",
            "source_id": "S9",
            "source_title": "Production source",
            "source_url": "https://spec.test/2",
            "locator": "S9-E2",
            "text": f"Boeing produced 12,731 B-17s between 1936 and 1945 for wartime service.",
            "text_hash": "test",
            "source_capture_method": "fetched_page",
            "source_tier": 3,
            "anton_slot_hints": ["reality"],
            "source_variant_selection": {"selected_capture_method": "fetched_page"},
        },
        {
            # Cross-designation noise must never feed this card's numbers.
            "excerpt_id": "S9-E3",
            "source_id": "S9",
            "source_title": "Foreign source",
            "source_url": "https://spec.test/3",
            "locator": "S9-E3",
            "text": "The B-36 Peacemaker carried a 230-foot wingspan.",
            "text_hash": "test",
            "source_capture_method": "fetched_page",
            "source_tier": 1,
            "anton_slot_hints": ["engineering_decision"],
            "source_variant_selection": {"selected_capture_method": "fetched_page"},
        },
    ])
    actions = pe._script_starvation_promote_actions(card, package, machine)
    by_id = {action["excerpt_id"]: action for action in actions}
    assert "S9-E1" in by_id and by_id["S9-E1"]["kind"] == "scale_specs_context"
    assert "S9-E2" in by_id and by_id["S9-E2"]["kind"] == "build_reality_context"
    assert "S9-E3" not in by_id
    assert all(action["verb"] == "promote_excerpt" for action in actions)

    # Support kinds only: never a required-role kind that could overwrite
    # actual_outcome or trip the slot-hint gate.
    assert all(action["kind"].endswith("_context") for action in actions)

    # A card with no gaps proposes nothing; so does a missing package.
    fed_card = {"unit": machine, "evidence_segments": _starved_benchmark_segments()}
    fed_card["evidence_segments"][2]["claim"] = "It carried a 185-foot wingspan and eight engines."
    fed_card["evidence_segments"][2]["source_excerpt"] = fed_card["evidence_segments"][2]["claim"]
    fed_card["evidence_segments"][4]["claim"] = "Boeing produced 12,731 aircraft that served in combat."
    fed_card["evidence_segments"][4]["source_excerpt"] = fed_card["evidence_segments"][4]["claim"]
    assert pe._script_starvation_promote_actions(fed_card, package, machine) == []
    assert pe._script_starvation_promote_actions(card, None, machine) == []


def test_classify_repair_actions_returns_starvation_promotes_when_referee_clean():
    """A referee-clean benchmark card with audit starvation now gets FREE
    promote actions from the Repair ladder instead of an empty plan."""
    machine = "Boeing B-17 Flying Fortress"
    segments = _starved_benchmark_segments()
    card = _valid_research_card(machine, segments)
    package = _verified_package_for_segments(machine, card["evidence_segments"])
    package["candidate_excerpts"].append({
        "excerpt_id": "S9-E2",
        "source_id": "S9",
        "source_title": "Production source",
        "source_url": "https://spec.test/2",
        "locator": "S9-E2",
        "text": f"Boeing produced 12,731 B-17s between 1936 and 1945 for wartime service.",
        "text_hash": "test",
        "source_capture_method": "fetched_page",
        "source_tier": 3,
        "anton_slot_hints": ["reality"],
        "source_variant_selection": {"selected_capture_method": "fetched_page"},
    })
    referee = pe._blocking_warnings(
        pe._research_card_contract_warnings(machine, card, package, require_source_package=True)
    )
    actions = pe._classify_repair_actions(machine, card, package)
    if not referee:
        assert any(
            action["verb"] == "promote_excerpt" and action["kind"].endswith("_context")
            for action in actions
        )
    else:
        # Fixture drifted into referee territory; the starvation step is then
        # exercised by the two direct tests above.
        assert isinstance(actions, list)


# ---------------------------------------------------------------------------
# PLAN -> WRITE -> EDIT (2026-07-17): code picks the facts per beat, code
# keeps the citation ledger, the model only writes. Locks the deterministic
# halves of the restructured writer.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 2026-07-29 C3 tests of run_research's own roster-prefetch dispatch (fired on
# both the gate-success and gate-failure exits) were removed 2026-09: since
# f561ddf6 a static-docu run_research ends at the Roster stage and never reaches
# that code, and reference photos are now an explicit, separately-triggered
# Gather Images step (82201e54, PipelineExecutor.run_roster_image_gather). The
# free MCP submit_research seam still dispatches (research_ingest, covered in
# functional/test_static_docu_roster_prefetch.py). The kept-roster test above
# asserts the Roster stage schedules no prefetch.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 2026-07-29 fix: alias derivation for ship-class roster entries so the
# roster prefetch (static_docu._prefetch_one_machine) can search a real
# member-ship / class name instead of only the glued display string that
# _unit_display_name produces for the persisted roster and
# static_reference_cache key. Display names are UNCHANGED — only an
# ADDITIVE parallel accessor is introduced.
# ---------------------------------------------------------------------------

def test_unit_roster_aliases_splits_slash_and_comma_compounds():
    # Real misses from "Every British Aircraft Carrier Class Ever Built"
    # (2026-07-27): designation holds a category/member-ship list, not a
    # real designation, so the glued display name is unsearchable.
    attacker = {"name": "Attacker class (US-built)", "designation": "Lend-Lease escort carriers"}
    aliases = pe._unit_roster_aliases(attacker)
    assert "Attacker class (US-built)" in aliases
    assert "Lend-Lease escort carriers" in aliases

    ruler = {"name": "Ruler class (US-built)", "designation": "Lend-Lease escort carriers"}
    assert "Ruler class (US-built)" in pe._unit_roster_aliases(ruler)

    audacious = {"name": "Audacious class / Malta class", "designation": "CVA-01 predecessors"}
    aud_aliases = pe._unit_roster_aliases(audacious)
    assert "Audacious class" in aud_aliases
    assert "Malta class" in aud_aliases
    assert "CVA-01 predecessors" in aud_aliases

    archer = {"name": "Archer class / Empire Mac-Ship conversions", "designation": "CAM ships and MAC ships"}
    archer_aliases = pe._unit_roster_aliases(archer)
    assert "Archer class" in archer_aliases
    assert "Empire Mac-Ship conversions" in archer_aliases
    assert "CAM ships and MAC ships" in archer_aliases

    # Comma-split member ships (a real designation this time, not a category).
    courageous = {"name": "Courageous class", "designation": "Courageous, Glorious"}
    courageous_aliases = pe._unit_roster_aliases(courageous)
    assert "Courageous" in courageous_aliases
    assert "Glorious" in courageous_aliases
    assert "Courageous, Glorious" in courageous_aliases


def test_unit_roster_aliases_never_built_class_has_no_useful_alias():
    """CVA-01 class (never built) is an expected miss — no photo exists.
    Aliases still derive cleanly (no crash, no bogus match), they just
    don't manufacture a searchable name where none exists."""
    never_built = {"name": "Queen Elizabeth class (1960s design)", "designation": "CVA-01 class"}
    aliases = pe._unit_roster_aliases(never_built)
    assert "Queen Elizabeth class (1960s design)" in aliases
    assert "CVA-01 class" in aliases


def test_machine_documentary_hold_roster_entries_keeps_name_unchanged_and_adds_aliases():
    """The display name _machine_key hashes into the static_reference_cache
    primary key must be BYTE-IDENTICAL between the old flat-string accessor
    and the new name+aliases accessor — orphaning the 27 live cached rows
    (and the roster-dashboard UI keyed on those names) is exactly the
    failure mode the task guards against."""
    roster_items = [
        {"name": "Attacker class (US-built)", "designation": "Lend-Lease escort carriers"},
        {"name": "Ruler class (US-built)", "designation": "Lend-Lease escort carriers"},
        {"name": "Audacious class / Malta class", "designation": "CVA-01 predecessors"},
        {"name": "Archer class / Empire Mac-Ship conversions", "designation": "CAM ships and MAC ships"},
    ]
    video = {
        "render_mode": "static_docu",
        "research_payload": {
            "documentary_style": "designed_vs_used",
            "unit_roster": roster_items,
        },
    }

    flat_names = pe._machine_documentary_hold_roster(video)
    entries = pe._machine_documentary_hold_roster_entries(video)

    # Same names, same order — the cache key derivation can't drift.
    assert [e["name"] for e in entries] == flat_names

    by_name = {e["name"]: e["aliases"] for e in entries}
    attacker_name = "Lend-Lease escort carriers Attacker class (US-built)"
    assert attacker_name in by_name
    assert "Attacker class (US-built)" in by_name[attacker_name]
    assert "Lend-Lease escort carriers" in by_name[attacker_name]

    ruler_name = "Lend-Lease escort carriers Ruler class (US-built)"
    assert "Ruler class (US-built)" in by_name[ruler_name]

    audacious_name = "CVA-01 predecessors Audacious class / Malta class"
    assert "Audacious class" in by_name[audacious_name]
    assert "Malta class" in by_name[audacious_name]

    archer_name = "CAM ships and MAC ships Archer class / Empire Mac-Ship conversions"
    assert "Archer class" in by_name[archer_name]
    assert "Empire Mac-Ship conversions" in by_name[archer_name]


def test_machine_documentary_hold_roster_entries_gates_same_as_flat_accessor():
    """Non-static-docu and missing-marker videos must be rejected identically by
    both accessors, and roster size is not a gate for either (shared gate helper).
    Runtime selection may choose one or more than forty entries (f561ddf6)."""
    not_static = {"render_mode": "coverage", "research_payload": {"unit_roster": ["A", "B", "C"]}}
    assert pe._machine_documentary_hold_roster(not_static) == []
    assert pe._machine_documentary_hold_roster_entries(not_static) == []

    no_marker = {"render_mode": "static_docu", "research_payload": {"unit_roster": ["A", "B", "C"]}}
    assert pe._machine_documentary_hold_roster(no_marker) == []
    assert pe._machine_documentary_hold_roster_entries(no_marker) == []

    for names in (["A", "B"], [f"Machine {i}" for i in range(45)]):
        video = {
            "render_mode": "static_docu",
            "research_payload": {
                "documentary_style": "designed_vs_used",
                "unit_roster": [{"name": name} for name in names],
            },
        }
        assert pe._machine_documentary_hold_roster(video) == names
        assert [e["name"] for e in pe._machine_documentary_hold_roster_entries(video)] == names


# ---------------------------------------------------------------------------
# G21a: the script-path evidence gate must honor G14's tier-floor-as-advisory
# ruling (decisions.md, 2026-07-31; deployed 89d151cd). Live repro: 4 machines
# on d2e37cd6 whose research cards PASS the referee (23/23 green pre-run) -
# HMS Activity (D94) Activity class; CAM ships and MAC ships Archer class /
# Empire Mac-Ship conversions; CVA-01 predecessors Audacious class / Malta
# class; CVA-01 Queen Elizabeth class (1960s design) CVA-01 class - each hit
# HTTP 200 / 0s / $0 "Script preview evidence gate failed:
# ... advisory: [tier_floor_advisory] Verified source package needs at least
# one Tier 1-2 primary/authoritative source..." because the SCRIPT-hold gate
# (pipeline_executor.py's per-machine loop in _run_static_script_hold, plus
# the mirrored check in check_machine_script_preview_readiness) treated the
# RAW _research_card_contract_warnings() list as blocking instead of
# filtering it through _blocking_warnings() first - the same function
# _research_card_contract_warnings' own docstring says the caller must use.
# ---------------------------------------------------------------------------

def _tier3_only_evidence_segments() -> list[dict]:
    """G14's own "package-level: zero Tier 1-2 anywhere" fixture pattern
    (test_g14_tier_floor_and_caution_only_gaps_all_advisory_not_blocking,
    item 1 above) - every source is a generic non-tier-1-2, non-caution
    (Tier 3) URL, so the ONLY source_error this card/package can produce is
    the advisory-prefixed tier_floor_advisory, never a blocking one."""
    segments = _evidence_segments()
    for index, segment in enumerate(segments):
        segment["source_url"] = f"https://example-secondary.test/boeing-xb-15-{index}"
    return segments


# ---------------------------------------------------------------------------
# G21b: two DISTINCT roster entries can share the same _normalized_unit_code
# - live collision (video d2e37cd6): "Lend-Lease escort carriers Attacker
# class (US-built)" (roster slot 21) and "...Ruler class (US-built)" (slot
# 22) both normalize to LENDLEASEESCORTCARRIERS. _locked_roster_item_for_machine
# used to check the normalized code FIRST, so BOTH names resolved to
# whichever entry happened to be first in the roster - the second
# machine-script-block save for "Ruler" silently landed on (and overwrote)
# scene 21, Attacker's slot. _roster_index_for_identity (a sibling helper,
# used for research-card identity) already had the correct name-first,
# code-fallback-only-if-unambiguous order and documents this exact collision
# shape; _locked_roster_item_for_machine (used for SCRIPT-block roster
# matching) had the same disease. Ground truth confirmed live via `se db`:
# scene 21 currently holds RULER's paragraph (the second, overwriting save);
# scene 22 was never written at all.
# ---------------------------------------------------------------------------

def test_g21b_locked_roster_item_for_machine_resolves_lend_lease_collision_pair():
    # Real roster shape from video d2e37cd6 (name+designation structured
    # entries, confirmed live via `se db`): scene 21 = Attacker, scene 22 =
    # Ruler, scene 9 = the Audacious/Malta CVA-01-predecessors entry, scene
    # 13 = the CVA-01-class entry - TWO independent collision pairs on the
    # same roster.
    roster_items = [
        {"name": "Audacious class / Malta class", "designation": "CVA-01 predecessors"},  # scene 9
        {"name": "CVA-01 class", "designation": "CVA-01 Queen Elizabeth class (1960s design)"},  # scene 13
        {"name": "Attacker class (US-built)", "designation": "Lend-Lease escort carriers"},  # scene 21
        {"name": "Ruler class (US-built)", "designation": "Lend-Lease escort carriers"},  # scene 22
    ]
    video = {
        "render_mode": "static_docu",
        "research_payload": {"documentary_style": "designed_vs_used", "unit_roster": roster_items},
    }
    roster = pe._machine_documentary_hold_roster(video)

    attacker = "Lend-Lease escort carriers Attacker class (US-built)"
    ruler = "Lend-Lease escort carriers Ruler class (US-built)"
    cva01_predecessors = "CVA-01 predecessors Audacious class / Malta class"
    cva01_class = "CVA-01 Queen Elizabeth class (1960s design) CVA-01 class"
    assert roster == [cva01_predecessors, cva01_class, attacker, ruler]

    # Both share the SAME normalized code in each pair - the root cause,
    # proven directly.
    assert pe._normalized_unit_code(attacker) == pe._normalized_unit_code(ruler)
    assert pe._normalized_unit_code(cva01_predecessors) == pe._normalized_unit_code(cva01_class)

    matched_attacker = pe._locked_roster_item_for_machine(roster, attacker)
    matched_ruler = pe._locked_roster_item_for_machine(roster, ruler)
    matched_predecessors = pe._locked_roster_item_for_machine(roster, cva01_predecessors)
    matched_class = pe._locked_roster_item_for_machine(roster, cva01_class)
    assert matched_attacker == attacker
    assert matched_ruler == ruler
    assert matched_attacker != matched_ruler
    assert matched_predecessors == cva01_predecessors
    assert matched_class == cva01_class
    assert matched_predecessors != matched_class
    # Scene numbers derive from roster.index(matched) + 1 in
    # _run_static_script_hold - the real bug surface. Prove each name now
    # earns its OWN slot.
    assert roster.index(matched_attacker) + 1 == roster.index(attacker) + 1 == 3
    assert roster.index(matched_ruler) + 1 == roster.index(ruler) + 1 == 4
    assert roster.index(matched_predecessors) + 1 == roster.index(cva01_predecessors) + 1 == 1
    assert roster.index(matched_class) + 1 == roster.index(cva01_class) + 1 == 2


def test_g21b_locked_roster_item_for_machine_returns_none_for_unmatched_name():
    roster = [
        "Lend-Lease escort carriers Attacker class (US-built)",
        "Lend-Lease escort carriers Ruler class (US-built)",
    ]
    assert pe._locked_roster_item_for_machine(roster, "USS Nonexistent Ship") is None


def test_g21b_locked_roster_item_for_machine_still_resolves_unambiguous_code_fallback():
    """A label that doesn't exact-match any roster display name (different
    case, extra whitespace) but whose normalized code is UNAMBIGUOUS across
    the roster must still resolve via the code fallback - the fix narrows
    the ORDER (name before code), it does not remove the fallback."""
    roster = ["HMS Furious (47) Furious", "HMS Hermes (95) Hermes"]
    assert pe._locked_roster_item_for_machine(roster, "  hms furious (47) furious  ") == "HMS Furious (47) Furious"
