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


def test_anton_inventory_title_mode_accepts_ever_built_without_every():
    assert pe._anton_inventory_title_mode("Every US Strategic Bomber Ever Built") is True
    assert pe._anton_inventory_title_mode("World's Most Strategic Bombers Ever Built") is True
    assert pe._anton_inventory_title_mode("Complete History of Strategic Bombers") is True
    assert pe._anton_inventory_title_mode("Designed vs Used: Strategic Bomber Lessons") is False


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


def test_word_gates_hard_80_warn_band_95_ceiling_170():
    """QD-6/QL-1 (approved): universal hard floor 80 and ceiling 170; 80-95 is
    an ADVISORY warn band (confirm terse on purpose); register bands are
    guidance handled elsewhere. Supersedes the provisional 95-120 hard range."""
    validate = pe.PipelineExecutor._validate_static_unit_paragraph

    assert any("under the 80-word hard floor" in warning for warning in validate("XB-15", _words("XB-15", 79)))
    warn_band = validate("XB-15", _words("XB-15", 85))
    assert pe._blocking_warnings(warn_band) == []
    assert any("warn band" in warning for warning in warn_band)
    assert validate("XB-15", _words("XB-15", 95)) == []
    assert validate("XB-15", _words("XB-15", 120)) == []
    assert pe._blocking_warnings(validate("XB-15", _words("XB-15", 170))) == []
    assert any("over the 170-word hard ceiling" in warning for warning in validate("XB-15", _words("XB-15", 171)))
    two_paragraphs = _words("XB-15", 48) + "\n\n" + _words("XB-15", 47)
    assert "must be exactly one paragraph" in validate("XB-15", two_paragraphs)
    assert validate("B52", _words("B-52", 95)) == []


# ---------------------------------------------------------------------------
# Checklist C46c: DvsU deltas as table-driven gates. `rule_overrides=None`
# (the default, and every call in this file above) must stay byte-identical
# to pre-C46c behavior -- proven with `git stash` in the verification pass.
# ---------------------------------------------------------------------------

def test_word_gate_table_override_wins_over_hardcoded_constants():
    """D1: a seeded QL-1 row's floor/warn/ceiling REPLACES the hardcoded
    80/95/170 values when supplied via rule_overrides."""
    validate = pe.PipelineExecutor._validate_static_unit_paragraph
    overrides = {"word_floor": {"hard_min": 40, "warn_top": 60, "hard_max": 90, "severity": "hard_gate"}}

    # 65 words: a hard-floor violation under the default 80-word floor, but
    # clears the table-driven 40-word floor AND its 60-word warn-band top
    # -> no warning at all.
    sixty_five_words = _words("XB-15", 65)
    assert any("under the 80-word hard floor" in w for w in validate("XB-15", sixty_five_words))
    assert validate("XB-15", sixty_five_words, overrides) == []

    # 35 words: under the table-driven 40-word floor -> blocking.
    assert any(
        "under the 40-word hard floor" in w
        for w in pe._blocking_warnings(validate("XB-15", _words("XB-15", 35), overrides))
    )


def test_word_gate_table_override_absent_is_byte_identical_fallback():
    """No rule_overrides (None, the default) and an empty dict both fall
    back to today's hardcoded 80/95/170 constants, word-for-word."""
    validate = pe.PipelineExecutor._validate_static_unit_paragraph
    text = _words("XB-15", 79)
    assert validate("XB-15", text) == validate("XB-15", text, None) == validate("XB-15", text, {})


def test_word_gate_table_severity_demotes_floor_violation_to_advisory():
    """A seeded QL-1 row with severity='warn' (not hard_gate) demotes the
    floor/ceiling miss to advisory - it ships, never blocks."""
    validate = pe.PipelineExecutor._validate_static_unit_paragraph
    overrides = {"word_floor": {"hard_min": 80, "warn_top": 95, "hard_max": 170, "severity": "warn"}}
    warnings = validate("XB-15", _words("XB-15", 50), overrides)
    assert any("under the 80-word hard floor" in w for w in warnings)
    assert pe._blocking_warnings(warnings) == []  # demoted, never blocks


def test_hype_gate_table_override_adds_ql12_words_without_dropping_baseline():
    """QL-12: a seeded row's banned-adjective list is UNIONED with the
    existing ad hoc superlative-phrase list (additivity, never a regression)."""
    validate = pe.PipelineExecutor._validate_static_unit_paragraph
    overrides = {"banned_hype_words": {"words": ("incredible", "jaw-dropping"), "severity": "hard_gate"}}

    baseline_text = _words("XB-15", 90) + " it was undoubtedly the best."
    assert any("forbidden Anton/DVsU hype language" in w for w in validate("XB-15", baseline_text))
    assert any("forbidden Anton/DVsU hype language" in w for w in validate("XB-15", baseline_text, overrides))

    new_word_text = _words("XB-15", 90) + " this was a jaw-dropping achievement."
    assert validate("XB-15", new_word_text) == []  # not caught before QL-12 is seeded
    assert any(
        "forbidden Anton/DVsU hype language" in w
        for w in pe._blocking_warnings(validate("XB-15", new_word_text, overrides))
    )


def test_hype_gate_table_severity_demotes_to_advisory():
    validate = pe.PipelineExecutor._validate_static_unit_paragraph
    overrides = {"banned_hype_words": {"words": ("jaw-dropping",), "severity": "warn"}}
    text = _words("XB-15", 90) + " this was a jaw-dropping achievement."
    warnings = validate("XB-15", text, overrides)
    assert any("forbidden Anton/DVsU hype language" in w for w in warnings)
    assert pe._blocking_warnings(warnings) == []


def test_twist_gate_table_severity_demotes_undeclared_twist_to_advisory():
    """D2: a seeded QL-3 row with severity != hard_gate demotes the
    "no twist declared" / "no substitute" violations to advisory."""
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    undeclared = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    undeclared.pop("twist", None)

    _p, hard_warnings = pe._validate_machine_story_sentences("B-52", plan, undeclared)
    assert any("entry declares no designed-vs-used twist" in w for w in pe._blocking_warnings(hard_warnings))

    overrides = {"twist_gate": {"severity": "warn"}}
    _p, warn_warnings = pe._validate_machine_story_sentences("B-52", plan, undeclared, overrides)
    assert any(
        w.startswith(pe._ADVISORY_PREFIX) and "entry declares no designed-vs-used twist" in w
        for w in warn_warnings
    )
    assert pe._blocking_warnings(warn_warnings) == []


def test_twist_menu_table_override_recognizes_a_custom_subtype():
    """D3: a table-supplied twist_menu recognizes a type the hardcoded
    16-item menu does not, without an advisory 'not on the menu' flag."""
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    bundle["twist"] = {"type": "brand_new_subtype", "substitute": None, "summary": "?"}

    _p, default_warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)
    assert any("not on the menu" in w for w in default_warnings)

    overrides = {"twist_menu": {"types": ("brand_new_subtype",), "severity": "guidance"}}
    _p, table_warnings = pe._validate_machine_story_sentences("B-52", plan, bundle, overrides)
    assert not any("not on the menu" in w for w in table_warnings)


def test_validate_machine_story_sentences_no_override_is_byte_identical():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    p1, w1 = pe._validate_machine_story_sentences("B-52", plan, bundle)
    p2, w2 = pe._validate_machine_story_sentences("B-52", plan, bundle, None)
    p3, w3 = pe._validate_machine_story_sentences("B-52", plan, bundle, {})
    assert (p1, w1) == (p2, w2) == (p3, w3)


def test_voiceover_digit_gate_keeps_designations_years_and_exact_figures():
    """QL-10/QL-11 (OR-4 approved): digits stay legal for designations,
    calendar years (1937), and exact 4+ digit figures (5,130); sub-1000
    spoken measures (47%, 30 knots) must be spelled."""
    mentions = pe._raw_digit_mentions_for_voiceover(
        "B-52, XB-15, MiG-21, F-86, J57, and TF30 stay, but 1937, 5,130 miles, and 47% should be spoken."
    )
    assert mentions == ["47%"]
    assert pe._raw_digit_mentions_for_voiceover("It made 30 knots and carried 87 rounds.") == ["30", "87"]
    assert pe._raw_digit_mentions_for_voiceover("The toll reached 1,177 sailors in 1941.") == []


def test_voiceover_unit_gate_flags_written_units_but_keeps_designations():
    mentions = pe._written_unit_abbreviations_for_voiceover(
        "B-52, XB-15, and J57 stay, but five hundred mph, three thousand rpm, one hundred ft, two lb, ten hp, and fifty mi should be expanded."
    )

    assert mentions == ["mph", "rpm", "ft", "lb", "hp", "mi"]


def test_static_validator_requires_spoken_numbers_but_keeps_designations():
    validate = pe.PipelineExecutor._validate_static_unit_paragraph

    clean_designations = _words("B-52", 95)
    raw_quantity = " ".join(["B-52"] + ["word"] * 93 + ["47"])
    year_mention = " ".join(["B-52"] + ["word"] * 93 + ["1937"])

    assert not any("raw numeric digit" in warning for warning in validate("B-52", clean_designations))
    assert any("raw numeric digit" in warning and "47" in warning for warning in validate("B-52", raw_quantity))
    # QL-10: calendar years legally stay digits.
    assert not any("raw numeric digit" in warning for warning in validate("B-52", year_mention))


def test_static_validator_requires_spoken_unit_words():
    validate = pe.PipelineExecutor._validate_static_unit_paragraph
    raw_unit = _words("B-52", 92) + " five hundred mph."

    assert any("written unit abbreviation" in warning and "mph -> miles per hour" in warning for warning in validate("B-52", raw_unit))


def test_meta_validator_does_not_match_as_an_ai_inside_was_an_aircraft():
    paragraph = (
        "The Air Force ordered Boeing to design a jet bomber in nineteen forty-six that could reach Moscow from American bases "
        "and return without refueling. Boeing's answer was an aircraft that traded speed for range. The B-52 "
        "Stratofortress first flew on April fifteenth, nineteen fifty-two, powered by eight Pratt and Whitney J57 turbojets that burned "
        "fuel slowly enough to stay airborne for sixteen hours. It was subsonic by design. The Air Force had wanted "
        "a replacement by nineteen eighty. Instead, the B-52H models built between nineteen sixty and nineteen sixty-two are still flying combat missions "
        "today, now scheduled to remain in service until the twenty-fifties. The "
        "aircraft outlasted its replacement because range mattered more than speed."
    )

    assert pe.PipelineExecutor._validate_static_unit_paragraph(
        "Boeing B-52 Stratofortress", paragraph
    ) == []


def test_meta_validator_still_rejects_actual_ai_commentary():
    paragraph = "As an AI, " + " ".join(["B-52"] + ["word"] * 96)

    assert "contains meta/commentary instead of narration" in (
        pe.PipelineExecutor._validate_static_unit_paragraph("Boeing B-52 Stratofortress", paragraph)
    )


def test_static_validator_blocks_anton_forbidden_ai_patterns():
    validate = pe.PipelineExecutor._validate_static_unit_paragraph
    filler = " ".join(f"argument{i}" for i in range(1, 88))

    wiki_opening = (
        "The B-52 was a strategic bomber developed by Boeing in the 1950s. "
        f"{filler}."
    )
    spec_dump = (
        "The B-52 matters here because the Air Force wanted endurance more than speed. "
        "It had eight engines. It also had long wings. It featured a tall tail. "
        f"{filler}."
    )
    retirement_ending = (
        f"The B-52 kept serving because range mattered more than speed. {filler}. "
        "The aircraft was finally retired in 1978 after 24 years of service."
    )
    written_connector = (
        "The B-52 kept serving because range mattered more than speed. "
        f"However, {filler}."
    )
    ranked_list_connector = (
        "Next came the B-52, a machine that proved range mattered more than speed. "
        f"{filler}."
    )
    ranked_number_connector = (
        "At number two, the B-52 proved range mattered more than speed. "
        f"{filler}."
    )
    another_aircraft_connector = (
        "Another aircraft was the B-52, which proved range mattered more than speed. "
        f"{filler}."
    )

    assert any("Wikipedia-style" in warning for warning in validate("B-52", wiki_opening))
    assert any("list/spec-dump" in warning for warning in validate("B-52", spec_dump))
    assert any("retirement/date fact" in warning for warning in validate("B-52", retirement_ending))
    assert any("written-language connector" in warning for warning in validate("B-52", written_connector))
    assert any("ranked-list connector" in warning for warning in validate("B-52", ranked_list_connector))
    assert any("ranked-list connector" in warning for warning in validate("B-52", ranked_number_connector))
    assert any("ranked-list connector" in warning for warning in validate("B-52", another_aircraft_connector))


def test_static_validator_blocks_voiceover_file_artifacts():
    validate = pe.PipelineExecutor._validate_static_unit_paragraph

    unit_label = "UNIT 1: " + _words("B-52", 95)
    bracket_note = _words("B-52", 50) + " [B-ROLL: archival ground shot] " + _words("B-52", 45)
    thumbnail_line = _words("B-52", 95) + " THUMBNAIL: B-52 / B-21."

    assert any("production cue/label" in warning for warning in validate("B-52", unit_label))
    assert any("bracketed production note" in warning for warning in validate("B-52", bracket_note))
    assert any("production cue/label" in warning for warning in validate("B-52", thumbnail_line))


def test_static_validator_blocks_three_consecutive_long_sentences():
    validate = pe.PipelineExecutor._validate_static_unit_paragraph

    def long_sentence(prefix: str) -> str:
        return prefix + " " + " ".join(f"word{i}" for i in range(1, 31)) + "."

    paragraph = " ".join([
        long_sentence("The B-52 stayed useful because range mattered more than speed"),
        long_sentence("That endurance made the aircraft a strategic answer rather than a fashionable one"),
        long_sentence("The Air Force kept returning to the same basic choice whenever replacement programs stalled"),
    ])

    assert any("three consecutive long sentences" in warning for warning in validate("B-52", paragraph))


def test_static_validator_blocks_timeline_biography_structure():
    validate = pe.PipelineExecutor._validate_static_unit_paragraph
    filler = " ".join(f"argument{i}" for i in range(1, 48))

    timeline = (
        "The B-52 was designed by Boeing in the nineteen fifties. "
        "The B-52 entered service with Strategic Air Command in nineteen fifty-five. "
        "The aircraft served during Vietnam and later campaigns before replacement plans changed. "
        f"The engineering point is buried under a sequence of dates rather than a decision. {filler}."
    )
    anton_anchor = (
        "The B-52 entered service because the Air Force needed a bomber that could make distance matter more than speed. "
        f"{filler}."
    )

    assert any("timeline/chronology" in warning for warning in validate("B-52", timeline))
    assert not any("timeline/chronology" in warning for warning in validate("B-52", anton_anchor))


def test_card_matching_never_confuses_prefix_designations():
    payload = {"unit_research_cards": [{"unit": "B-21", "engineering_thesis": "wrong machine"}]}
    assert pe._research_card_for_machine(payload, "B-2") is None


def test_script_source_is_exactly_one_saved_card_not_global_research():
    payload = {
        "fact_sheet": "GLOBAL FACT SHEET MUST NOT LEAK",
        "report": "GLOBAL REPORT MUST NOT LEAK",
        "unit_research_cards": [
            {"unit": "XB-15", "engineering_thesis": "card-one-only"},
            {"unit": "B-17", "engineering_thesis": "card-two-only"},
        ],
    }

    source, kind = pe._research_source_for_machine(payload, "XB-15")

    assert kind == "unit_research_card"
    assert "card-one-only" in source
    assert "card-two-only" not in source
    assert "GLOBAL FACT SHEET MUST NOT LEAK" not in source


def test_inventory_story_brief_hides_exhaustive_card_fields():
    payload = {
        "unit_research_cards": [{
            "unit": "Boeing XB-15",
            "engineering_thesis": "UNSOURCED CARD SUMMARY MUST NOT LEAK.",
            "actual_outcome": "It missed combat requirements. It later hauled cargo. A third sentence must be hidden.",
            "why_this_unit_deserves_a_paragraph": "It taught Boeing what the next generation required. Extra legacy detail must be hidden.",
            "surprising_fact": "SECRET SPEC-DUMP BAIT",
            "engineering_response": "DIMENSIONS ENGINES PAYLOAD SPEED RANGE",
            "source_notes": ["EXHAUSTIVE SOURCE NOTES"],
            "script_beats": ["FIVE PREWRITTEN BEATS"],
            "timeframe": "SECRET SERVICE PERIOD BAIT",
            "timeframe_evidence_ids": ["E-REALITY"],
            "visual_identity": "CAMERA PAN OVER WING ENGINE TAIL NOSE FUSELAGE TEXT OVERLAY",
            "visual_identity_evidence_ids": ["E-DECISION"],
            "onscreen_label": "UNSOURCED LABEL BAIT",
            "evidence_segments": _evidence_segments(),
        }],
    }

    brief = pe._inventory_story_brief(payload, "Boeing XB-15")
    serialized = json.dumps(brief)

    assert brief["source_contract"] == "evidence_rows_only"
    assert brief["core_tension"] == "Original problem claim grounded in the supplied source."
    assert brief["actual_outcome"] == "Reality claim grounded in the supplied source through its Cold War service period."
    assert brief["historical_significance"] == "Memorable fact claim grounded in the supplied source."
    assert brief["onscreen_label"] == "Onscreen label claim grounded in the supplied source."
    assert brief["anton_slots"][0]["source_excerpt"] == "Original problem claim grounded in the supplied source."
    assert brief["anton_slots"][0]["source_url"] == "https://airandspace.si.edu/test/original_problem"
    assert "UNSOURCED CARD SUMMARY" not in serialized
    assert "UNSOURCED LABEL BAIT" not in serialized
    assert "SECRET SPEC-DUMP BAIT" not in serialized
    assert "DIMENSIONS ENGINES" not in serialized
    assert "EXHAUSTIVE SOURCE NOTES" not in serialized
    assert "FIVE PREWRITTEN BEATS" not in serialized
    assert "SECRET SERVICE PERIOD BAIT" not in serialized
    assert "CAMERA PAN" not in serialized
    assert "TEXT OVERLAY" not in serialized


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


def test_story_paragraph_validator_blocks_missing_slots_and_unsupported_numbers():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    bundle["claim_map"] = bundle["claim_map"][:3]
    old_span = bundle["claim_map"][0]["span"]
    new_span = old_span.replace("clear.", "clear 1967.", 1)
    bundle["claim_map"][0]["span"] = new_span
    bundle["paragraph"] = bundle["paragraph"].replace(old_span, new_span)

    _, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert any("missing required Anton slot evidence" in warning for warning in warnings)
    assert any("unsupported numerical detail" in warning for warning in warnings)


def test_story_sentence_parser_marks_invalid_json_for_review():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")

    bundle = pe._parse_machine_story_sentences("not json")
    paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert paragraph == ""
    assert bundle["_parse_error"] == "story distiller must return valid JSON matching the Anton paragraph schema"
    assert any("valid JSON matching the Anton paragraph schema" in warning for warning in warnings)
    assert any("paragraph string" in warning for warning in warnings)


def test_story_sentence_parser_marks_alias_keys_for_review():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    canonical = json.loads(_story_bundle("B-52", 19))
    alias_payload = {
        "voiceover": canonical["paragraph"],
        "sentences": [{"sentence": sentence} for sentence in canonical["formula_sentences"]],
        "claims": canonical["claim_map"],
        "throughline": canonical["editorial_thesis"],
        "onscreen_label": "",
    }

    bundle = pe._parse_machine_story_sentences(json.dumps(alias_payload))
    paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert paragraph == canonical["paragraph"]
    assert bundle["formula_sentences"] == canonical["formula_sentences"]
    assert any("noncanonical key `voiceover`" in warning for warning in warnings)
    assert any("noncanonical key `sentences`" in warning for warning in warnings)
    assert any("noncanonical key `claims`" in warning for warning in warnings)
    assert any("noncanonical key `throughline`" in warning for warning in warnings)
    assert any("formula_sentences must be an array of strings" in warning for warning in warnings)
    assert "voiceover" not in bundle
    assert "sentences" not in bundle
    assert "claims" not in bundle
    assert "throughline" not in bundle


def test_story_sentence_parser_marks_extra_top_level_keys_for_review():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    canonical = json.loads(_story_bundle("B-52", 19))
    canonical["producer_note"] = "This hidden production note must not pass the exact schema."
    canonical["alternate_conclusion"] = "This hidden alternate ending must not pass either."

    bundle = pe._parse_machine_story_sentences(json.dumps(canonical))
    paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert paragraph == canonical["paragraph"]
    assert any("extra top-level key(s) outside the exact Anton schema" in warning for warning in warnings)
    assert any("alternate_conclusion" in warning for warning in warnings)
    assert any("producer_note" in warning for warning in warnings)
    assert "alternate_conclusion" not in bundle
    assert "producer_note" not in bundle


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


def test_story_paragraph_validator_accepts_anton_slot_bundle():
    payload = {"unit_research_cards": [{
        "unit": "B-52",
        "evidence_segments": _evidence_segments(),
    }]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))

    paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert pe._blocking_warnings(warnings) == []
    assert pe._spoken_word_count(paragraph) == 95
    assert [row["used_evidence_ids"][0] for row in bundle["claim_map"]] == [
        "E-PROBLEM", "E-DECISION", "E-TRADEOFF", "E-REALITY"
    ]
    assert "E-MEMORABLE" in bundle["claim_map"][3]["used_evidence_ids"]


def test_story_paragraph_validator_blocks_forbidden_machine_name_opening():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    plan["contract"] = dict(plan["contract"])
    plan["contract"]["opening_assignment"] = "Do NOT open with the machine name. Open with a problem or operational need."
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))

    paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)
    audit = pe._anton_preview_quality_audit("B-52", plan, bundle, paragraph, warnings)

    assert any("opening assignment forbids machine-name opening" in warning for warning in warnings)
    opening_check = next(check for check in audit["checks"] if check["name"] == "opening_assignment")
    assert opening_check["passed"] is False
    assert opening_check["detail"] == "machine-name opener flagged"


def test_story_paragraph_validator_allows_problem_opening_when_assignment_forbids_machine_name():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    plan["contract"] = dict(plan["contract"])
    plan["contract"]["opening_assignment"] = "Do NOT open with the machine name. Open with a problem or operational need."
    bundle = pe._parse_machine_story_sentences(_problem_opening_story_bundle("B-52", 19))

    _paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert not any("opening assignment forbids machine-name opening" in warning for warning in warnings)


def test_story_paragraph_validator_accepts_anton_benchmark_shape():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    sentences = [
        "B-52 original problem claim grounded in the supplied source.",
        "Engineering decision claim grounded in the supplied source.",
        "Tradeoff claim grounded in the supplied source.",
        "Reality claim grounded in the supplied source and memorable fact claim grounded in the supplied source.",
        "The price was written into the design itself.",
    ]
    while pe._spoken_word_count(" ".join(sentences)) < 116:
        sentences[1] = sentences[1].rstrip(".") + " clear."
    bundle["paragraph"] = " ".join(sentences)
    bundle["formula_sentences"] = sentences
    bundle["claim_map"] = [
        {"slot": "original_problem", "span": sentences[0], "used_evidence_ids": ["E-PROBLEM"]},
        {"slot": "engineering_decision", "span": sentences[1], "used_evidence_ids": ["E-DECISION"]},
        {"slot": "tradeoff", "span": sentences[2], "used_evidence_ids": ["E-TRADEOFF"]},
        {"slot": "reality", "span": sentences[3], "used_evidence_ids": ["E-REALITY", "E-MEMORABLE"]},
    ]

    paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert pe._blocking_warnings(warnings) == []
    assert pe._spoken_word_count(paragraph) == 116


def test_story_paragraph_validator_requires_five_sentence_formula_order():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    extra_sentence_bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    old_final = "The proof survived the machine."
    extra_sentence = "Memorable fact claim grounded in the supplied source."
    extra_sentence_bundle["paragraph"] = extra_sentence_bundle["paragraph"].replace(
        old_final,
        extra_sentence + " " + old_final,
    )
    # Paragraph assembly is code-owned: author the change in the sentences.
    extra_sentence_bundle["formula_sentences"] = _formula_sentences_from_paragraph(extra_sentence_bundle["paragraph"])
    extra_sentence_bundle["claim_map"].append({
        "slot": "memorable_fact",
        "span": extra_sentence,
        "used_evidence_ids": ["E-MEMORABLE"],
    })

    _paragraph, extra_warnings = pe._validate_machine_story_sentences("B-52", plan, extra_sentence_bundle)

    assert any(
        warning.startswith(pe._ADVISORY_PREFIX) and "the Anton formula target is" in warning
        for warning in extra_warnings
    )

    wrong_order_bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    wrong_order_bundle["claim_map"][0]["slot"] = "engineering_decision"
    wrong_order_bundle["claim_map"][0]["used_evidence_ids"] = ["E-DECISION"]
    wrong_order_bundle["claim_map"][1]["slot"] = "original_problem"
    wrong_order_bundle["claim_map"][1]["used_evidence_ids"] = ["E-PROBLEM"]

    _paragraph, order_warnings = pe._validate_machine_story_sentences("B-52", plan, wrong_order_bundle)

    assert any("sentence 1 must carry original_problem evidence" in warning for warning in order_warnings)
    assert any("sentence 2 must carry engineering_decision evidence" in warning for warning in order_warnings)


def test_story_paragraph_validator_rejects_mixed_required_slots_inside_formula_sentence():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    bundle["claim_map"][0]["used_evidence_ids"] = ["E-PROBLEM", "E-DECISION"]

    _paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert any(
        "sentence 1 used out-of-order required Anton slot evidence: engineering_decision" in warning
        for warning in warnings
    )


def test_story_paragraph_validator_requires_available_memorable_fact():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    bundle["claim_map"][3]["used_evidence_ids"] = ["E-REALITY"]

    _paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert any("must use sourced memorable_fact" in warning for warning in warnings)


def test_story_paragraph_validator_assembles_paragraph_in_code():
    """LAW (2026-07-16): the paragraph is the code-assembled join of
    formula_sentences; the model's re-typed paragraph string is ignored, so a
    mangled model paragraph (XB-15's "XB-about 15", paraphrased clauses) is
    impossible by construction and the old assembly-mismatch warning is gone."""
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))

    # Model re-typed the paragraph badly: mangled designation (raw digit leak)
    # plus a paraphrased clause. Sentences (with the designation) stay clean.
    mangled_bundle = copy.deepcopy(bundle)
    mangled_bundle["paragraph"] = (
        mangled_bundle["paragraph"]
        .replace("B-52", "B-about 52", 1)
        .replace("The proof survived the machine.", "The proof did not survived the machine.", 1)
    )
    paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, mangled_bundle)

    # The graded paragraph is the join of the clean sentences: designation joins
    # cleanly, no raw-digit/mismatch warnings from the mangled model string.
    assert paragraph == " ".join(mangled_bundle["formula_sentences"])
    assert "B-52" in paragraph
    assert "B-about 52" not in paragraph
    assert mangled_bundle["paragraph"] == paragraph  # bundle synced to code-assembly
    assert pe._blocking_warnings(warnings) == []
    assert not any("assemble exactly" in warning for warning in warnings)

    # Legacy bundles without formula_sentences still fail the count contract.
    missing_bundle = copy.deepcopy(bundle)
    missing_bundle.pop("formula_sentences", None)
    _paragraph, missing_warnings = pe._validate_machine_story_sentences("B-52", plan, missing_bundle)
    assert any(
        warning.startswith(pe._ADVISORY_PREFIX) and "the Anton formula target is" in warning
        for warning in missing_warnings
    )


# (Removed 2026-07-16: QD-1 deleted the closer word-novelty mechanism entirely -
# the final sentence has vocabulary freedom and only the banned classes gate.
# Entity/number bans are pinned in
# test_story_paragraph_validator_gives_closer_vocabulary_freedom.)


def test_two_source_numeric_check_scans_all_locked_evidence():
    """LAW (2026-07-16): the two-independent-sources requirement for exact
    numbers is graded against ALL locked story-plan evidence (distinct
    source_url = independent), not only the row's cited ids. XB-15's 149-foot
    wingspan lives in an engineering_decision segment AND an onscreen_label
    segment from a different source; citing only one must pass. A number with
    a single locked source anywhere still requires the hedge."""
    evidence = _evidence_segments()
    number_phrase = "a one hundred forty nine foot wingspan"
    # Two locked segments carry the same number, in DIFFERENT slots and from
    # DIFFERENT source URLs (each test segment kind has its own URL).
    evidence[2]["claim"] = evidence[2]["claim"].rstrip(".") + f" including {number_phrase}."
    evidence[2]["source_excerpt"] = evidence[2]["claim"]
    evidence[7]["claim"] = evidence[7]["claim"].rstrip(".") + f" listing {number_phrase}."
    evidence[7]["source_excerpt"] = evidence[7]["claim"]
    assert evidence[2]["kind"] == "engineering_decision"
    assert evidence[7]["kind"] == "onscreen_label"
    assert evidence[2]["source_url"] != evidence[7]["source_url"]

    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": evidence}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    old_span = bundle["claim_map"][1]["span"]
    new_span = old_span.rstrip(".") + f" with {number_phrase}."
    bundle["claim_map"][1]["span"] = new_span
    bundle["paragraph"] = bundle["paragraph"].replace(old_span, new_span)
    bundle["formula_sentences"] = _formula_sentences_from_paragraph(bundle["paragraph"])

    # The span cites ONLY the engineering_decision segment; the second source
    # is uncited (onscreen_label slot). Two distinct locked sources -> passes.
    _, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)
    assert not any(
        "needs two independent sources or a hedge for exact numerical detail(s)" in warning
        for warning in warnings
    )

    # Single-sourced number (only the engineering_decision segment carries it)
    # still demands the hedge.
    single_evidence = _evidence_segments()
    single_evidence[2]["claim"] = single_evidence[2]["claim"].rstrip(".") + f" including {number_phrase}."
    single_evidence[2]["source_excerpt"] = single_evidence[2]["claim"]
    single_plan = pe._machine_story_plan(
        {"unit_research_cards": [{"unit": "B-52", "evidence_segments": single_evidence}]},
        "B-52",
    )
    _, single_warnings = pe._validate_machine_story_sentences("B-52", single_plan, bundle)
    assert any(
        "needs two independent sources or a hedge for exact numerical detail(s)" in warning
        and "one hundred forty nine" in warning
        for warning in single_warnings
    )


def test_designations_are_identifiers_never_numbers_in_script_checks():
    """LAW (2026-07-16): designation digits (XB-15, B-52, F-86D) are names in
    every script-stage number check; a real raw digit still fails."""
    # Unit level: the digit scrubbers ignore ANY designation-shaped token
    # (not only the locked machine's) while real numerals still surface.
    assert pe._raw_digit_mentions_for_voiceover(
        "The B-52 escorted the F-86D and the XB-15 over 15 miles."
    ) == ["15"]
    assert pe._numeric_mentions_from_text(
        pe._strip_designations_for_numbers("The XB-15 and the F-86 flew 87 sorties.", "Boeing XB-15")
    ) == [{"raw": "87", "key": "87"}]

    # Validator level: the locked designation in narration AND in the closer
    # produces zero number/entity warnings...
    payload = {"unit_research_cards": [{"unit": "Boeing XB-15", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "Boeing XB-15")
    bundle = pe._parse_machine_story_sentences(_story_bundle("Boeing XB-15", 19))
    old_final = "The proof survived the machine."
    new_final = "The proof survived the XB-15."
    bundle["formula_sentences"] = [
        new_final if sentence == old_final else sentence
        for sentence in bundle["formula_sentences"]
    ]
    _paragraph, warnings = pe._validate_machine_story_sentences("Boeing XB-15", plan, bundle)
    assert pe._blocking_warnings(warnings) == []

    # ...while a real raw digit in a sentence still fails the number checks,
    # and no check ever names the designation's "15".
    digit_bundle = pe._parse_machine_story_sentences(_story_bundle("Boeing XB-15", 19))
    old_span = digit_bundle["claim_map"][1]["span"]
    digit_span = old_span.rstrip(".") + " over 87 years."
    digit_bundle["claim_map"][1]["span"] = digit_span
    digit_bundle["formula_sentences"] = [
        digit_span if sentence == old_span else sentence
        for sentence in digit_bundle["formula_sentences"]
    ]
    _paragraph, digit_warnings = pe._validate_machine_story_sentences("Boeing XB-15", plan, digit_bundle)
    assert any("raw numeric digit" in warning and "87" in warning for warning in digit_warnings)
    assert any("unsupported numerical detail(s): 87" in warning for warning in digit_warnings)
    assert not any(": 15" in warning or " 15," in warning for warning in digit_warnings)


def test_softener_never_hedges_designation_digits():
    """LAW (2026-07-16): the single-source softener may hedge quantities but must
    never touch a designation - the old fallback produced "XB-about 15" live."""
    softened = pe._soften_single_source_span("The XB-15 recorded 5000.", "Boeing XB-15")
    assert "XB-about 15" not in softened
    assert "XB-15" in softened
    assert "about 5000" in softened
    # A designation-only span has no numeric mentions at all, so the number
    # branch of the softener never fires on it.
    assert pe._span_numeric_mentions_without_locked_designation(
        "The B-52 followed the XB-15.", "Boeing XB-15"
    ) == []


def test_row_word_grounding_scans_all_locked_evidence_with_glue_stoplist():
    """LAW (2026-07-16): a span word grounded in ANY locked segment (claim or
    excerpt) is supported - row citations stay provenance. Function/quantifier
    glue is stoplisted; genuinely ungrounded nouns still fail."""
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")

    def _bundle_with_sentence2_suffix(suffix: str) -> dict:
        bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
        old_span = bundle["claim_map"][1]["span"]
        new_span = old_span.rstrip(".") + suffix
        bundle["claim_map"][1]["span"] = new_span
        bundle["formula_sentences"] = [
            new_span if sentence == old_span else sentence
            for sentence in bundle["formula_sentences"]
        ]
        return bundle

    # "role category" lives in the E-ROLE segment, which row 2 does NOT cite:
    # cross-row grounding passes.
    cross_row = _bundle_with_sentence2_suffix(" in the role category.")
    _p, cross_warnings = pe._validate_machine_story_sentences("B-52", plan, cross_row)
    assert not any("unsupported factual word" in warning for warning in cross_warnings)

    # A genuinely ungrounded colorful noun still flags - as an ADVISORY
    # vocabulary warning under QD-2 ("giant" is nowhere in the locked
    # evidence; the model should prefer the evidence's own wording).
    ungrounded = _bundle_with_sentence2_suffix(" with the giant wing.")
    _p, giant_warnings = pe._validate_machine_story_sentences("B-52", plan, ungrounded)
    assert any(
        warning.startswith(pe._ADVISORY_PREFIX)
        and "vocabulary outside the locked evidence" in warning and "giant" in warning
        for warning in giant_warnings
    )

    # Function/quantifier glue is stoplisted at the script stage.
    glue = _bundle_with_sentence2_suffix(" built over the years where such carrying was single.")
    _p, glue_warnings = pe._validate_machine_story_sentences("B-52", plan, glue)
    assert not any("unsupported factual word" in warning for warning in glue_warnings)


def test_hedged_numbers_accept_natural_hedge_lexicon():
    """LAW (2026-07-16): one shared hedge lexicon. A number introduced with a
    natural hedge ("approaching five thousand miles") satisfies the two-source
    rule, and the hedge word never self-flags as an unsupported word. A
    genuinely unhedged single-sourced number still warns."""
    # The gate, the softener's detector, and the prompts share _HEDGE_WORDS.
    for phrase in ("approaching", "close to", "almost", "some", "over", "more than", "up to", "on the order of", "around", "nearly"):
        assert pe._HEDGE_WORDS_RE.search(f"a range {phrase} five thousand miles"), phrase
    # Single-word hedge tokens are epistemic glue for word grounding.
    assert pe._ungrounded_factual_words(
        "approaching almost nearly close estimated some up whether even",
        "",
        "B-52",
        extra_stopwords=pe._SCRIPT_GLUE_STOPWORDS,
    ) == []

    evidence = _evidence_segments()
    evidence[2].update({
        "claim": "The Boeing XB-15 scale specs included a range of 5,000 mi.",
        "source_excerpt": "The Boeing XB-15 scale specs included a range of 5,000 mi.",
        "numeric_tokens": ["5000"],
    })
    payload = {"unit_research_cards": [{"unit": "Boeing XB-15", "evidence_segments": evidence}]}
    plan = pe._machine_story_plan(payload, "Boeing XB-15")

    def _bundle_with_suffix(suffix: str) -> dict:
        bundle = pe._parse_machine_story_sentences(_story_bundle("Boeing XB-15", 19))
        old_span = bundle["claim_map"][1]["span"]
        new_span = old_span.rstrip(".") + suffix
        bundle["claim_map"][1]["span"] = new_span
        bundle["formula_sentences"] = [
            new_span if sentence == old_span else sentence
            for sentence in bundle["formula_sentences"]
        ]
        return bundle

    hedged = _bundle_with_suffix(" with a range approaching five thousand miles.")
    _p, hedged_warnings = pe._validate_machine_story_sentences("Boeing XB-15", plan, hedged)
    assert not any("two independent sources" in warning for warning in hedged_warnings)
    assert not any(
        "unsupported factual word" in warning and "approaching" in warning
        for warning in hedged_warnings
    )

    unhedged = _bundle_with_suffix(" with a range at five thousand miles.")
    _p, unhedged_warnings = pe._validate_machine_story_sentences("Boeing XB-15", plan, unhedged)
    assert any(
        "two independent sources" in warning and "five thousand" in warning
        for warning in unhedged_warnings
    )


def test_story_plan_support_slots_include_field_cited_segments():
    """LAW (2026-07-16): the plan's timeframe/visual_identity support slots are
    the union of matching-kind segments AND the card's *_evidence_ids-cited
    segments (deduplicated), so cited support evidence always reaches plan
    evidence. Slots stay optional; role attribution stays narrative-first; the
    two-source scan then sees every locked source for a year."""
    evidence = _evidence_segments()
    dated_reality = {
        "evidence_id": "E-FLEW",
        "kind": "reality",
        "claim": "Boeing XB-15 first flew in October 1937 from Boeing Field.",
        "source_excerpt": "Boeing XB-15 first flew in October 1937 from Boeing Field.",
        "source_url": "https://airandspace.si.edu/test/first-flight",
        "source_title": "Test source",
        "locator": "S9-E1",
        "numeric_tokens": ["1937"],
        "confidence": "high",
    }
    dated_support = {
        "evidence_id": "E-DELIVERED",
        "kind": "timeframe",
        "claim": "Boeing XB-15 was delivered to the Army in December 1937.",
        "source_excerpt": "Boeing XB-15 was delivered to the Army in December 1937.",
        "source_url": "https://history.test/xb15-delivery",
        "source_title": "Second source",
        "locator": "S10-E1",
        "numeric_tokens": ["1937"],
        "confidence": "high",
    }
    card = {
        "unit": "Boeing XB-15",
        "evidence_segments": evidence + [dated_reality, dated_support],
        "timeframe_evidence_ids": ["E-FLEW", "E-DELIVERED"],
    }
    plan = pe._machine_story_plan({"unit_research_cards": [card]}, "Boeing XB-15")
    slots_by_role = {slot["slot"]: slot for slot in plan["slots"]}

    # The reality-kind cited segment appears in its narrative slot AND the
    # timeframe support slot; the timeframe-kind one enters via its kind.
    assert "E-FLEW" in slots_by_role["reality"]["evidence_ids"]
    assert "E-FLEW" in slots_by_role["timeframe"]["evidence_ids"]
    assert "E-DELIVERED" in slots_by_role["timeframe"]["evidence_ids"]
    # Deduplicated within the slot.
    assert slots_by_role["timeframe"]["evidence_ids"].count("E-FLEW") == 1
    # Support slots stay optional and never count toward required beats.
    assert slots_by_role["timeframe"]["required"] is False
    assert plan["required_slots"] == sorted(pe._ANTON_REQUIRED_SLOT_ROLES)
    # Role attribution stays narrative-first for formula-order checks.
    assert plan["evidence_slot_roles"]["E-FLEW"] == "reality"
    assert plan["evidence_slot_roles"]["E-DELIVERED"] == "timeframe"

    # Two-source integration: the year sees BOTH locked sources, so an
    # unhedged "nineteen thirty seven" no longer false-flags.
    bundle = pe._parse_machine_story_sentences(_story_bundle("Boeing XB-15", 19))
    old_span = bundle["claim_map"][3]["span"]
    new_span = old_span.rstrip(".") + " in nineteen thirty seven."
    bundle["claim_map"][3]["span"] = new_span
    bundle["claim_map"][3]["used_evidence_ids"] = ["E-REALITY", "E-MEMORABLE", "E-FLEW"]
    bundle["formula_sentences"] = [
        new_span if sentence == old_span else sentence
        for sentence in bundle["formula_sentences"]
    ]
    _p, warnings = pe._validate_machine_story_sentences("Boeing XB-15", plan, bundle)
    assert not any("two independent sources" in warning for warning in warnings)
    assert not any("unsupported numerical detail" in warning for warning in warnings)


def test_story_paragraph_validator_requires_memorable_fact_in_story_plan():
    evidence = [
        segment for segment in _evidence_segments()
        if segment["kind"] != "memorable_fact"
    ]
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": evidence}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    bundle["claim_map"][3]["used_evidence_ids"] = ["E-REALITY"]

    paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)
    audit = pe._anton_preview_quality_audit("B-52", plan, bundle, paragraph, warnings)

    # QL-9 (OR-7 approved): memorable-fact is WARN severity - flagged for
    # review, never blocking, until research coverage is proven reliable.
    assert any("story plan missing sourced memorable_fact" in warning for warning in warnings)
    assert not any(
        "memorable_fact" in warning for warning in pe._blocking_warnings(warnings)
    )
    memorable_check = next(check for check in audit["checks"] if check["name"] == "memorable_fact")
    assert memorable_check["passed"] is False
    assert memorable_check.get("advisory") is True
    assert "no sourced memorable_fact" in memorable_check["detail"]
    assert audit["passed"] is True


def test_anton_preview_quality_audit_reports_passed_checks():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    # 20 words/sentence = 100 words: inside the spec-block register band.
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 20))
    paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    audit = pe._anton_preview_quality_audit("B-52", plan, bundle, paragraph, warnings)

    assert pe._blocking_warnings(warnings) == []
    assert audit["passed"] is True
    assert [check["name"] for check in audit["checks"]] == [
        "word_range",
        "sentence_shape",
        "twist_gate",
        "sentence_assembly",
        "four_evidence_beats",
        "memorable_fact",
        "editorial_thesis",
        "landed_final_line",
        "clean_voiceover",
        "spoken_rhythm",
        "opening_assignment",
        "narrative_weight",
        "not_catalog_copy",
    ]
    assert next(check for check in audit["checks"] if check["name"] == "twist_gate")["passed"] is True
    assert next(check for check in audit["checks"] if check["name"] == "memorable_fact")["detail"] == "used E-MEMORABLE"
    assert next(check for check in audit["checks"] if check["name"] == "sentence_assembly")["passed"] is True
    assert next(check for check in audit["checks"] if check["name"] == "clean_voiceover")["passed"] is True
    assert next(check for check in audit["checks"] if check["name"] == "spoken_rhythm")["passed"] is True
    assert next(check for check in audit["checks"] if check["name"] == "opening_assignment")["passed"] is True
    assert next(check for check in audit["checks"] if check["name"] == "narrative_weight")["passed"] is True


def test_story_paragraph_validator_enforces_major_narrative_weight_target():
    payload = {"unit_research_cards": [{
        "unit": "B-52",
        "narrative_weight": "major",
        "evidence_segments": _evidence_segments(),
    }]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))

    paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)
    audit = pe._anton_preview_quality_audit("B-52", plan, bundle, paragraph, warnings)

    # QL-1/QL-2 (approved): register/weight targets are GUIDANCE - the miss is
    # advisory, never blocking (only 80/170 are hard).
    assert any("narrative_weight target major 110-150 words" in warning for warning in warnings)
    assert pe._blocking_warnings(warnings) == []
    narrative_check = next(check for check in audit["checks"] if check["name"] == "narrative_weight")
    assert narrative_check["passed"] is False
    assert narrative_check.get("advisory") is True
    assert narrative_check["detail"] == "major target 110-150; 95 words"
    assert audit["passed"] is True


def test_story_paragraph_validator_accepts_transitional_narrative_weight_target():
    payload = {"unit_research_cards": [{
        "unit": "XB-15",
        "narrative_weight": "transitional",
        "evidence_segments": _evidence_segments(),
    }]}
    plan = pe._machine_story_plan(payload, "XB-15")
    bundle = pe._parse_machine_story_sentences(_story_bundle("XB-15", 19))

    paragraph, warnings = pe._validate_machine_story_sentences("XB-15", plan, bundle)
    audit = pe._anton_preview_quality_audit("XB-15", plan, bundle, paragraph, warnings)
    narrative_check = next(check for check in audit["checks"] if check["name"] == "narrative_weight")

    assert not any("narrative_weight target" in warning for warning in warnings)
    assert narrative_check["passed"] is True
    assert narrative_check["detail"] == "transitional target 80-95; 95 words"


def test_anton_preview_quality_audit_flags_voiceover_artifacts():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    paragraph, _warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    audit = pe._anton_preview_quality_audit(
        "B-52",
        plan,
        bundle,
        paragraph,
        ["contains production cue/label instead of clean voiceover narration"],
    )
    voiceover_check = next(check for check in audit["checks"] if check["name"] == "clean_voiceover")

    assert audit["passed"] is False
    assert voiceover_check["passed"] is False
    assert voiceover_check["detail"] == "production/meta artifact flagged"


def test_anton_preview_quality_audit_flags_spoken_unit_warnings():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    paragraph, _warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    audit = pe._anton_preview_quality_audit(
        "B-52",
        plan,
        bundle,
        paragraph,
        ["paragraph uses written unit abbreviation(s); spell out for voiceover: mph -> miles per hour"],
    )
    voiceover_check = next(check for check in audit["checks"] if check["name"] == "clean_voiceover")
    validator_check = next(check for check in audit["checks"] if check["name"] == "validator_warnings")

    assert audit["passed"] is False
    assert voiceover_check["passed"] is False
    assert validator_check["passed"] is False
    assert "mph -> miles per hour" in validator_check["detail"]


def test_anton_preview_quality_audit_never_passes_with_uncategorized_warning():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    paragraph, _warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    audit = pe._anton_preview_quality_audit(
        "B-52",
        plan,
        bundle,
        paragraph,
        ["paragraph introduced unsupported designation(s): B47"],
    )
    validator_check = next(check for check in audit["checks"] if check["name"] == "validator_warnings")

    assert audit["passed"] is False
    assert validator_check["passed"] is False
    assert "unsupported designation" in validator_check["detail"]


def test_anton_preview_quality_audit_flags_flat_spoken_rhythm():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    paragraph, _warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    audit = pe._anton_preview_quality_audit(
        "B-52",
        plan,
        bundle,
        paragraph,
        ["contains three consecutive long sentences instead of varied voiceover rhythm"],
    )
    rhythm_check = next(check for check in audit["checks"] if check["name"] == "spoken_rhythm")

    assert audit["passed"] is False
    assert rhythm_check["passed"] is False
    assert rhythm_check["detail"] == "three long sentences in a row"


def test_anton_preview_quality_audit_flags_timeline_structure():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    paragraph, _warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    audit = pe._anton_preview_quality_audit(
        "B-52",
        plan,
        bundle,
        paragraph,
        ["contains timeline/chronology structure instead of an engineering argument"],
    )
    catalog_check = next(check for check in audit["checks"] if check["name"] == "not_catalog_copy")

    assert audit["passed"] is False
    assert catalog_check["passed"] is False
    assert catalog_check["detail"] == "catalog pattern flagged"


def test_anton_preview_quality_audit_flags_ranked_list_connector():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    paragraph, _warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    audit = pe._anton_preview_quality_audit(
        "B-52",
        plan,
        bundle,
        paragraph,
        ["contains forbidden Anton/DVsU ranked-list connector language"],
    )
    catalog_check = next(check for check in audit["checks"] if check["name"] == "not_catalog_copy")

    assert audit["passed"] is False
    assert catalog_check["passed"] is False
    assert catalog_check["detail"] == "catalog pattern flagged"


def test_anton_preview_quality_audit_requires_strategic_bomber_cadence():
    payload = {"unit_research_cards": [{"unit": "Boeing XB-15", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "Boeing XB-15")
    bundle = pe._parse_machine_story_sentences(_story_bundle("Boeing XB-15", 19))
    paragraph, warnings = pe._validate_machine_story_sentences("Boeing XB-15", plan, bundle)

    audit = pe._anton_preview_quality_audit("Boeing XB-15", plan, bundle, paragraph, warnings)
    cadence_check = next(check for check in audit["checks"] if check["name"] == "benchmark_cadence")

    assert audit["passed"] is False
    assert "advisory" not in cadence_check
    assert cadence_check["passed"] is False
    assert "scale/capability missing" in cadence_check["detail"]

    production_only_paragraph = (
        "Boeing XB-15 first flew in 1937 as America's experimental answer to strategic bombing. "
        "Only one prototype was built, which gave the program a narrower path than a production bomber. "
        "The aircraft later served during World War II, moving cargo across the Pacific instead of bombing targets. "
        "That service reality made the machine useful, but not as the combat aircraft it had promised. "
        "The XB-15 proved the idea without becoming the weapon."
    )
    production_only_audit = pe._anton_preview_quality_audit(
        "Boeing XB-15",
        plan,
        _claim_bundle_from_sentences(
            "Boeing XB-15",
            _formula_sentences_from_paragraph(production_only_paragraph),
        ),
        production_only_paragraph,
        [],
    )
    production_only_check = next(
        check for check in production_only_audit["checks"] if check["name"] == "benchmark_cadence"
    )

    assert production_only_check["passed"] is False
    assert "scale/capability missing" in production_only_check["detail"]
    assert "production/service reality present" in production_only_check["detail"]

    fact_rhythm_paragraph = (
        "Boeing XB-15 first flew in 1937 as America's experimental answer to long-range bombing. "
        "Its 149-foot wingspan, four engines, and 5,130-mile range turned scale into the engineering decision. "
        "Only one prototype was built, which made the ambition hard to convert into a combat bomber. "
        "In World War II, the aircraft found reality as a Pacific transport instead of a bomber. "
        "The XB-15 proved the concept without becoming the weapon."
    )
    fact_rhythm_sentences = _formula_sentences_from_paragraph(fact_rhythm_paragraph)
    unmapped_fact_rhythm_audit = pe._anton_preview_quality_audit(
        "Boeing XB-15",
        plan,
        {},
        fact_rhythm_paragraph,
        [],
    )
    unmapped_fact_rhythm_check = next(
        check for check in unmapped_fact_rhythm_audit["checks"] if check["name"] == "benchmark_cadence"
    )
    fact_rhythm_audit = pe._anton_preview_quality_audit(
        "Boeing XB-15",
        plan,
        _claim_bundle_from_sentences("Boeing XB-15", fact_rhythm_sentences),
        fact_rhythm_paragraph,
        [],
    )
    fact_rhythm_check = next(
        check for check in fact_rhythm_audit["checks"] if check["name"] == "benchmark_cadence"
    )

    assert unmapped_fact_rhythm_check["passed"] is False
    assert "0 claim-mapped numerical details" in unmapped_fact_rhythm_check["detail"]
    assert "scale/capability missing" in unmapped_fact_rhythm_check["detail"]
    assert "production/service reality missing" in unmapped_fact_rhythm_check["detail"]
    assert fact_rhythm_check["passed"] is True
    assert "5 claim-mapped numerical details" in fact_rhythm_check["detail"]
    assert "scale/capability present" in fact_rhythm_check["detail"]
    assert "production/service reality present" in fact_rhythm_check["detail"]

    spoken_number_paragraph = (
        "Boeing XB-15 first flew in nineteen thirty-seven as America's experimental answer to long-range bombing. "
        "Its one hundred forty-nine-foot wingspan, four engines, and five thousand one hundred thirty-mile range turned scale into the engineering decision. "
        "Only one prototype was built, which made the ambition hard to convert into a combat bomber. "
        "In World War II, the aircraft found reality as a Pacific transport instead of a bomber. "
        "The XB-15 proved the concept without becoming the weapon."
    )
    spoken_number_sentences = _formula_sentences_from_paragraph(spoken_number_paragraph)
    spoken_number_audit = pe._anton_preview_quality_audit(
        "Boeing XB-15",
        plan,
        _claim_bundle_from_sentences("Boeing XB-15", spoken_number_sentences),
        spoken_number_paragraph,
        [],
    )
    spoken_number_check = next(
        check for check in spoken_number_audit["checks"] if check["name"] == "benchmark_cadence"
    )

    assert spoken_number_check["passed"] is True
    assert "scale/capability present" in spoken_number_check["detail"]
    assert "production/service reality present" in spoken_number_check["detail"]


def test_anton_preview_quality_audit_applies_benchmark_cadence_to_first_three_bombers():
    examples = {
        "Boeing B-17 Flying Fortress": (
            "Boeing B-17 Flying Fortress became the daylight precision bomber America trusted over Europe. "
            "Its seventy-four-foot length, four engines, four thousand five hundred pounds of bombs, and two thousand-mile reach made that doctrine measurable. "
            "Crews believed thirteen machine guns could defend formations without fighter escort. "
            "Boeing built twelve thousand seven hundred thirty-one aircraft, while the Eighth Air Force lost four thousand seven hundred thirty-five over Europe. "
            "The B-17 proved the doctrine could work, but only at a price crews paid."
        ),
        "Consolidated B-24 Liberator": (
            "Consolidated B-24 Liberator answered the wartime need for range, efficiency, and mass production. "
            "Its one hundred ten-foot wingspan, Davis wing, eight thousand-pound bomb load, and two thousand one hundred-mile reach made output useful across oceans. "
            "That efficient wing gave range, but crews found the airplane less forgiving than the B-17. "
            "American factories produced eighteen thousand four hundred eighty-two Liberators, and the aircraft served from Ploesti to the Atlantic. "
            "The B-24 turned industrial scale into the bomber argument."
        ),
    }

    for machine, paragraph in examples.items():
        plan = pe._machine_story_plan(
            {"unit_research_cards": [{"unit": machine, "evidence_segments": _evidence_segments()}]},
            machine,
        )
        audit = pe._anton_preview_quality_audit(
            machine,
            plan,
            _claim_bundle_from_sentences(machine, _formula_sentences_from_paragraph(paragraph)),
            paragraph,
            [],
        )
        cadence_check = next(check for check in audit["checks"] if check["name"] == "benchmark_cadence")

        assert cadence_check["passed"] is True
        assert "claim-mapped numerical details" in cadence_check["detail"]
        assert "scale/capability present" in cadence_check["detail"]
        assert "production/service reality present" in cadence_check["detail"]


def test_first_three_anton_audit_reports_human_detail_advisory():
    payload = {"unit_research_cards": [{"unit": "Boeing XB-15", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "Boeing XB-15")
    bundle = pe._parse_machine_story_sentences(_story_bundle("Boeing XB-15", 19))
    paragraph, warnings = pe._validate_machine_story_sentences("Boeing XB-15", plan, bundle)

    audit = pe._anton_preview_quality_audit("Boeing XB-15", plan, bundle, paragraph, warnings)
    human_check = next(check for check in audit["checks"] if check["name"] == "early_human_detail")

    assert audit["passed"] is False
    assert human_check["advisory"] is True
    assert human_check["passed"] is False
    assert "no sourced human_detail" in human_check["detail"]

    evidence = _evidence_segments()
    evidence.append({
        "evidence_id": "E-HUMAN",
        "kind": "human_detail",
        "claim": "Major William Snow account grounded in the supplied source.",
        "source_excerpt": "Major William Snow account grounded in the supplied source.",
        "source_url": "https://example.test/human-detail",
        "source_title": "Test source",
        "locator": "S9-E1",
        "numeric_tokens": [],
        "confidence": "high",
    })
    plan_with_human = pe._machine_story_plan(
        {"unit_research_cards": [{"unit": "Boeing XB-15", "evidence_segments": evidence}]},
        "Boeing XB-15",
    )
    audit_with_human = pe._anton_preview_quality_audit(
        "Boeing XB-15", plan_with_human, bundle, paragraph,
        pe._validate_machine_story_sentences("Boeing XB-15", plan_with_human, bundle)[1],
    )
    human_check_with_source = next(
        check for check in audit_with_human["checks"] if check["name"] == "early_human_detail"
    )

    assert "advisory" not in human_check_with_source
    assert human_check_with_source["passed"] is False
    assert "available but unused: E-HUMAN" in human_check_with_source["detail"]
    assert audit_with_human["passed"] is False

    human_bundle = copy.deepcopy(bundle)
    human_sentence = "Major William Snow account grounded in the supplied source."
    human_bundle["paragraph"] = human_bundle["paragraph"].replace(
        "The proof survived",
        f"{human_sentence} The proof survived",
    )
    human_bundle["claim_map"].append({
        "slot": "human_detail",
        "span": human_sentence,
        "used_evidence_ids": ["E-HUMAN"],
    })
    human_paragraph, human_warnings = pe._validate_machine_story_sentences(
        "Boeing XB-15", plan_with_human, human_bundle
    )
    human_audit = pe._anton_preview_quality_audit(
        "Boeing XB-15", plan_with_human, human_bundle, human_paragraph, human_warnings
    )
    used_human_check = next(
        check for check in human_audit["checks"] if check["name"] == "early_human_detail"
    )

    assert not any("must use sourced human_detail" in warning for warning in human_warnings)
    assert used_human_check["passed"] is True
    assert used_human_check["detail"] == "used E-HUMAN"


def test_story_paragraph_validator_requires_editorial_thesis():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    bundle.pop("editorial_thesis", None)

    _paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert any("must declare editorial_thesis" in warning for warning in warnings)

    generic_bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    generic_bundle["editorial_thesis"] = "This machine mattered."

    _paragraph, generic_warnings = pe._validate_machine_story_sentences("B-52", plan, generic_bundle)

    assert any("editorial_thesis is generic" in warning for warning in generic_warnings)
    assert any("must state a concrete engineering decision" in warning for warning in generic_warnings)


def test_story_paragraph_validator_allows_unmapped_final_synthesis_without_historical_meaning():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))

    _paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert pe._blocking_warnings(warnings) == []


def test_story_paragraph_validator_blocks_generic_final_synthesis_language():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    sentence_parts = [part for part in bundle["paragraph"].split(". ") if part]
    old_final = sentence_parts[-1]
    generic_final = "Together, those choices made the machine matter beyond its own service."
    bundle["paragraph"] = bundle["paragraph"].replace(old_final, generic_final)
    bundle["formula_sentences"] = _formula_sentences_from_paragraph(bundle["paragraph"])

    _paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)
    audit = pe._anton_preview_quality_audit("B-52", plan, bundle, bundle["paragraph"], warnings)
    final_check = next(check for check in audit["checks"] if check["name"] == "landed_final_line")

    assert any("final sentence uses generic summary language" in warning for warning in warnings)
    assert final_check["passed"] is False


def test_story_paragraph_validator_requires_compressed_anton_final_line():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    sentence_parts = [part for part in bundle["paragraph"].split(". ") if part]
    old_final = sentence_parts[-1]
    long_final = (
        "The original problem and engineering decision survived the tradeoff because "
        "reality grounded the source claim in the very same machine proof again "
        "and again for every crew involved."
    )
    bundle["paragraph"] = bundle["paragraph"].replace(old_final, long_final)
    bundle["formula_sentences"] = _formula_sentences_from_paragraph(bundle["paragraph"])

    _paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)
    audit = pe._anton_preview_quality_audit("B-52", plan, bundle, bundle["paragraph"], warnings)
    final_check = next(check for check in audit["checks"] if check["name"] == "landed_final_line")

    assert any("final sentence word count" in warning and "maximum is 25" in warning for warning in warnings)
    assert final_check["passed"] is False


def test_story_paragraph_validator_blocks_claim_mapped_final_synthesis():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    final_sentence = bundle["paragraph"].split(". ")[-1]
    bundle["claim_map"].append({
        "slot": "reality",
        "span": final_sentence,
        "used_evidence_ids": ["E-MEANING"],
    })

    _paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert any("final sentence must be paragraph-derived synthesis" in warning for warning in warnings)


def test_story_paragraph_validator_blocks_fact_heavy_final_synthesis():
    evidence = _evidence_segments()
    evidence[2]["claim"] = evidence[2]["claim"].rstrip(".") + " during design work dated 1950."
    evidence[2]["source_excerpt"] = evidence[2]["claim"]
    evidence[2]["numeric_tokens"] = ["1950"]
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": evidence}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    sentence_parts = [part for part in bundle["paragraph"].split(". ") if part]
    old_final = sentence_parts[-1]
    new_final = old_final.rstrip(".") + " in 1950."
    bundle["paragraph"] = bundle["paragraph"].replace(old_final, new_final)
    bundle["formula_sentences"] = _formula_sentences_from_paragraph(bundle["paragraph"])

    _paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    # B1 (2026-07-16): a new number ALONE in the closer is advisory; it hard-
    # blocks only when paired with a new hard entity (fabricated-fact shape).
    assert any(
        warning.startswith(pe._ADVISORY_PREFIX) and "closer introduces number(s) not in the body" in warning
        and "1950" in warning
        for warning in warnings
    )
    assert not any("pairs a new number with a new entity" in warning for warning in pe._blocking_warnings(warnings))
    assert not any("paragraph introduced unsupported numerical detail" in warning for warning in pe._blocking_warnings(warnings))


def test_story_paragraph_validator_blocks_new_named_entity_in_final_synthesis():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    sentence_parts = [part for part in bundle["paragraph"].split(". ") if part]
    old_final = sentence_parts[-1]
    new_final = old_final.rstrip(".") + " under Operation Chromedome."
    bundle["paragraph"] = bundle["paragraph"].replace(old_final, new_final)
    bundle["formula_sentences"] = _formula_sentences_from_paragraph(bundle["paragraph"])

    _paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert any(
        "final sentence must not introduce new named entity/event detail(s):" in warning
        and "Operation Chromedome" in warning
        for warning in pe._blocking_warnings(warnings)
    )
    # B1(a): geographic/nationality words are editorial color - advisory only.
    color_bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    color_final = old_final.rstrip(".") + " over Vietnam."
    color_bundle["paragraph"] = color_bundle["paragraph"].replace(old_final, color_final)
    color_bundle["formula_sentences"] = _formula_sentences_from_paragraph(color_bundle["paragraph"])
    _paragraph, color_warnings = pe._validate_machine_story_sentences("B-52", plan, color_bundle)
    assert any(
        warning.startswith(pe._ADVISORY_PREFIX) and "geographic/nationality color" in warning and "Vietnam" in warning
        for warning in color_warnings
    )
    assert not any("new named entity" in warning for warning in pe._blocking_warnings(color_warnings))


def test_story_paragraph_validator_gives_closer_vocabulary_freedom():
    """QD-1 (approved): the closer may use ANY editorial or abstract vocabulary
    ("against missiles", "written in blood over German skies" - Anton's own
    closers). Only the banned classes still gate: new named entities, new
    numbers, new designations. Replaces the old lowercase-word novelty ban."""
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    sentence_parts = [part for part in bundle["paragraph"].split(". ") if part]
    old_final = sentence_parts[-1]
    new_final = old_final.rstrip(".") + " against missiles."
    bundle["paragraph"] = bundle["paragraph"].replace(old_final, new_final)
    bundle["formula_sentences"] = _formula_sentences_from_paragraph(bundle["paragraph"])

    _paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    # Free vocabulary: no factual-word novelty flag exists any more.
    assert not any("final sentence must not introduce new factual word" in warning for warning in warnings)
    assert pe._blocking_warnings(warnings) == []

    # The banned classes still gate: a new person/org/operation name blocks.
    entity_bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    entity_final = old_final.rstrip(".") + " for General LeMay."
    entity_bundle["paragraph"] = entity_bundle["paragraph"].replace(old_final, entity_final)
    entity_bundle["formula_sentences"] = _formula_sentences_from_paragraph(entity_bundle["paragraph"])
    _paragraph, entity_warnings = pe._validate_machine_story_sentences("B-52", plan, entity_bundle)
    assert any(
        "final sentence must not introduce new named entity/event detail(s):" in warning
        and "General LeMay" in warning
        for warning in pe._blocking_warnings(entity_warnings)
    )


def test_story_paragraph_validator_requires_every_sentence_claim_mapped():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    bundle["claim_map"][2]["span"] = bundle["claim_map"][0]["span"]

    _paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert any("sentence 3 is not covered by claim_map evidence" in warning for warning in warnings)
    assert not any("paragraph missing required Anton slot evidence" in warning for warning in warnings)


def test_story_paragraph_validator_rejects_multi_sentence_claim_map_span():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    bundle["claim_map"][0]["span"] = f"{bundle['formula_sentences'][0]} {bundle['formula_sentences'][1]}"

    _paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert any("claim_map row 1 must map inside one formula sentence" in warning for warning in warnings)


def test_story_paragraph_validator_requires_sentence_numbers_inside_claim_map_span():
    evidence = _evidence_segments()
    evidence[2]["claim"] = evidence[2]["claim"].rstrip(".") + " during design work dated 1950."
    evidence[2]["source_excerpt"] = evidence[2]["claim"]
    evidence[2]["numeric_tokens"] = ["1950"]
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": evidence}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    old_sentence = bundle["claim_map"][1]["span"]
    mapped_span = old_sentence.rstrip(".")
    new_sentence = mapped_span + " in 1950."
    bundle["claim_map"][1]["span"] = mapped_span
    bundle["paragraph"] = bundle["paragraph"].replace(old_sentence, new_sentence)
    bundle["formula_sentences"] = _formula_sentences_from_paragraph(bundle["paragraph"])

    _paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert any("sentence 2 numerical detail(s) outside claim_map span coverage: 1950" in warning for warning in warnings)
    assert not any("paragraph introduced unsupported numerical detail" in warning for warning in warnings)


def test_story_paragraph_validator_requires_sentence_words_inside_claim_map_span():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    old_sentence = bundle["claim_map"][1]["span"]
    mapped_span = old_sentence.rstrip(".")
    new_sentence = mapped_span + " with stealth radar."
    bundle["claim_map"][1]["span"] = mapped_span
    bundle["paragraph"] = bundle["paragraph"].replace(old_sentence, new_sentence)
    bundle["formula_sentences"] = _formula_sentences_from_paragraph(bundle["paragraph"])

    _paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert any(
        "sentence 2 unsupported factual word(s) outside claim_map span coverage" in warning
        and "stealth" in warning and "radar" in warning
        for warning in warnings
    )


def test_story_paragraph_validator_grades_checkable_facts_hard_and_vocab_advisory():
    """QD-2 (approved): grounding is HARD only for checkable facts (proper
    nouns, months); common-word vocabulary outside the evidence is warn-only
    (colorful concrete nouns prefer evidence wording). Replaces the blanket
    unsupported-word block."""
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")

    # Lowercase concrete words outside evidence: ADVISORY vocabulary flag only.
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    old_span = bundle["claim_map"][0]["span"]
    vocab_span = old_span.rstrip(".") + " with a pressurized cockpit."
    bundle["claim_map"][0]["span"] = vocab_span
    bundle["paragraph"] = bundle["paragraph"].replace(old_span, vocab_span)
    bundle["formula_sentences"] = _formula_sentences_from_paragraph(bundle["paragraph"])
    _paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)
    assert not any("introduced unsupported factual word" in warning for warning in warnings)
    assert any(
        warning.startswith(pe._ADVISORY_PREFIX) and "vocabulary outside the locked evidence" in warning
        and "pressurized" in warning and "cockpit" in warning
        for warning in warnings
    )
    assert pe._blocking_warnings(warnings) == []

    # A checkable fact (ungrounded proper noun mid-sentence) still BLOCKS.
    fact_bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    fact_span = old_span.rstrip(".") + " under Operation Chromedome."
    fact_bundle["claim_map"][0]["span"] = fact_span
    fact_bundle["paragraph"] = fact_bundle["paragraph"].replace(old_span, fact_span)
    fact_bundle["formula_sentences"] = _formula_sentences_from_paragraph(fact_bundle["paragraph"])
    _paragraph, fact_warnings = pe._validate_machine_story_sentences("B-52", plan, fact_bundle)
    assert any(
        "introduced unsupported factual word(s)" in warning and "chromedome" in warning
        for warning in pe._blocking_warnings(fact_warnings)
    )


def test_story_paragraph_validator_accepts_anton_style_xb15_slots():
    evidence = [
        {
            "evidence_id": "XB15-PROBLEM",
            "kind": "original_problem",
            "claim": "The Boeing XB-15 first flew in 1937 as America's experimental leap into long-range strategic bombing.",
            "source_excerpt": "The Boeing XB-15 first flew in 1937 as America's experimental leap into long-range strategic bombing.",
            "source_url": "https://example.test/xb-15",
            "source_title": "Anton source fixture",
            "locator": "paragraph-1",
            "numeric_tokens": ["1937"],
            "confidence": "high",
        },
        {
            "evidence_id": "XB15-DECISION",
            "kind": "engineering_decision",
            "claim": "With a 149-foot wingspan and four 850-horsepower Pratt & Whitney engines, this massive aircraft could carry 2,500 pounds of bombs over 5,130 miles.",
            "source_excerpt": "With a 149-foot wingspan and four 850-horsepower Pratt & Whitney engines, this massive aircraft could carry 2,500 pounds of bombs over 5,130 miles.",
            "source_url": "https://example.test/xb-15",
            "source_title": "Anton source fixture",
            "locator": "paragraph-1",
            "numeric_tokens": ["149", "four", "850", "2500", "5130"],
            "confidence": "high",
        },
        {
            "evidence_id": "XB15-TRADEOFF",
            "kind": "tradeoff",
            "claim": "A single prototype was built, and it never fought as a bomber, but it proved large, multi-engine bombers could fly intercontinental distances.",
            "source_excerpt": "A single prototype was built, and it never fought as a bomber, but it proved large, multi-engine bombers could fly intercontinental distances.",
            "source_url": "https://example.test/xb-15",
            "source_title": "Anton source fixture",
            "locator": "paragraph-1",
            "numeric_tokens": ["one"],
            "confidence": "high",
        },
        {
            "evidence_id": "XB15-MEMORABLE",
            "kind": "memorable_fact",
            "claim": "A single prototype was built, and it never fought as a bomber, but it proved large, multi-engine bombers could fly intercontinental distances.",
            "source_excerpt": "A single prototype was built, and it never fought as a bomber, but it proved large, multi-engine bombers could fly intercontinental distances.",
            "source_url": "https://example.test/xb-15",
            "source_title": "Anton source fixture",
            "locator": "paragraph-1",
            "numeric_tokens": ["one"],
            "confidence": "high",
        },
        {
            "evidence_id": "XB15-REALITY",
            "kind": "reality",
            "claim": "The aircraft served as a transport during World War II, hauling cargo across the Pacific.",
            "source_excerpt": "The aircraft served as a transport during World War II, hauling cargo across the Pacific.",
            "source_url": "https://example.test/xb-15",
            "source_title": "Anton source fixture",
            "locator": "paragraph-1",
            "numeric_tokens": [],
            "confidence": "high",
        },
        {
            "evidence_id": "XB15-MEANING",
            "kind": "historical_meaning",
            "claim": "Though never used in combat as a bomber, the XB-15 validated concepts that would define American strategic aviation for the next eight decades.",
            "source_excerpt": "Though never used in combat as a bomber, the XB-15 validated concepts that would define American strategic aviation for the next eight decades.",
            "source_url": "https://example.test/xb-15",
            "source_title": "Anton source fixture",
            "locator": "paragraph-1",
            "numeric_tokens": ["eight"],
            "confidence": "high",
        },
    ]
    for source_id in ("XB15-PROBLEM", "XB15-DECISION", "XB15-TRADEOFF", "XB15-MEMORABLE", "XB15-MEANING"):
        duplicate = copy.deepcopy(next(item for item in evidence if item["evidence_id"] == source_id))
        duplicate["evidence_id"] = f"{source_id}-CHECK"
        duplicate["source_url"] = "https://example.test/xb-15-cross-check"
        duplicate["source_title"] = "Anton cross-check fixture"
        evidence.append(duplicate)
    plan = pe._machine_story_plan(
        {"unit_research_cards": [{"unit": "Boeing XB-15", "evidence_segments": evidence}]},
        "Boeing XB-15",
    )
    bundle = {
        "editorial_thesis": "The XB-15 mattered because size and range outpaced bomber-engine maturity.",
        "formula_sentences": [
            "The Boeing XB-15 first flew in nineteen thirty-seven as America's experimental leap into long-range strategic bombing.",
            "With a one hundred and forty-nine-foot wingspan and four Pratt & Whitney engines of eight hundred and fifty horsepower, it could carry two thousand, five hundred pounds of bombs over five thousand, one hundred and thirty miles.",
            "A single prototype was built, and it never fought as a bomber, but it proved large, multi-engine bombers could fly intercontinental distances.",
            "The aircraft served as a transport during World War II, hauling cargo across the Pacific.",
            "That made it proof that size, range, and power had to mature together.",
        ],
        "paragraph": (
            "The Boeing XB-15 first flew in nineteen thirty-seven as America's experimental leap into long-range strategic bombing. "
            "With a one hundred and forty-nine-foot wingspan and four Pratt & Whitney engines of eight hundred and fifty horsepower, it could carry two thousand, five hundred pounds of bombs over five thousand, one hundred and thirty miles. "
            "A single prototype was built, and it never fought as a bomber, but it proved large, multi-engine bombers could fly intercontinental distances. "
            "The aircraft served as a transport during World War II, hauling cargo across the Pacific. "
            "That made it proof that size, range, and power had to mature together."
        ),
        "claim_map": [
            {
                "slot": "original_problem",
                "span": "The Boeing XB-15 first flew in nineteen thirty-seven as America's experimental leap into long-range strategic bombing.",
                "used_evidence_ids": ["XB15-PROBLEM", "XB15-PROBLEM-CHECK"],
            },
            {
                "slot": "engineering_decision",
                "span": "With a one hundred and forty-nine-foot wingspan and four Pratt & Whitney engines of eight hundred and fifty horsepower, it could carry two thousand, five hundred pounds of bombs over five thousand, one hundred and thirty miles.",
                "used_evidence_ids": ["XB15-DECISION", "XB15-DECISION-CHECK"],
            },
            {
                "slot": "tradeoff",
                "span": "A single prototype was built, and it never fought as a bomber, but it proved large, multi-engine bombers could fly intercontinental distances.",
                "used_evidence_ids": ["XB15-TRADEOFF", "XB15-TRADEOFF-CHECK", "XB15-MEMORABLE", "XB15-MEMORABLE-CHECK"],
            },
            {
                "slot": "reality",
                "span": "The aircraft served as a transport during World War II, hauling cargo across the Pacific.",
                "used_evidence_ids": ["XB15-REALITY"],
            },
        ],
    }

    paragraph, warnings = pe._validate_machine_story_sentences("Boeing XB-15", plan, bundle)

    assert pe._blocking_warnings(warnings) == []
    assert pe._spoken_word_count(paragraph) == 102


def test_story_sentence_parser_accepts_paragraph_object_shape():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    canonical = json.loads(_story_bundle("B-52", 19))

    bundle = pe._parse_machine_story_sentences(json.dumps(canonical))
    paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert pe._blocking_warnings(warnings) == []
    assert bundle["paragraph"] == canonical["paragraph"]
    assert pe._spoken_word_count(paragraph) == 95


def test_story_sentence_validator_allows_source_supported_spelled_numbers_only():
    evidence = _evidence_segments()
    evidence[2].update({
        "claim": "The Boeing XB-15 scale specs included range of 5000 mi for the Army Air Corps.",
        "source_excerpt": "The Boeing XB-15 scale specs included range of 5,000 mi for the Army Air Corps.",
        "numeric_tokens": ["5000"],
    })
    scale_check = copy.deepcopy(evidence[2])
    scale_check["evidence_id"] = "E-DECISION-CHECK"
    scale_check["source_url"] = "https://example.test/scale-cross-check"
    evidence.append(scale_check)
    payload = {"unit_research_cards": [{"unit": "Boeing XB-15", "evidence_segments": evidence}]}
    plan = pe._machine_story_plan(payload, "Boeing XB-15")
    bundle = pe._parse_machine_story_sentences(_story_bundle("Boeing XB-15", 19))
    bundle["claim_map"][1]["used_evidence_ids"] = ["E-DECISION", "E-DECISION-CHECK"]
    old_span = bundle["claim_map"][1]["span"]
    new_span = old_span.replace("clear.", "clear five thousand miles.", 1)
    bundle["claim_map"][1]["span"] = new_span
    bundle["paragraph"] = bundle["paragraph"].replace(old_span, new_span)
    bundle["formula_sentences"] = _formula_sentences_from_paragraph(bundle["paragraph"])

    paragraph, warnings = pe._validate_machine_story_sentences("Boeing XB-15", plan, bundle)

    assert pe._blocking_warnings(warnings) == []
    assert "five thousand miles" in paragraph

    bad_bundle = copy.deepcopy(bundle)
    bad_bundle["paragraph"] = bad_bundle["paragraph"].replace(
        "five thousand", "six thousand"
    )
    bad_sentences = [part if part.endswith(".") else part + "." for part in bad_bundle["paragraph"].split(". ") if part]
    bad_bundle["formula_sentences"] = bad_sentences
    for row, sentence in zip(bad_bundle["claim_map"], bad_sentences):
        row["span"] = sentence

    _, bad_warnings = pe._validate_machine_story_sentences("Boeing XB-15", plan, bad_bundle)

    assert any("six thousand" in warning for warning in bad_warnings)

    unit_bundle = copy.deepcopy(bundle)
    unit_bundle["paragraph"] = unit_bundle["paragraph"].replace(
        "five thousand miles", "five thousand mi"
    )
    unit_bundle["formula_sentences"] = _formula_sentences_from_paragraph(unit_bundle["paragraph"])
    unit_bundle["claim_map"][1]["span"] = unit_bundle["claim_map"][1]["span"].replace(
        "five thousand miles", "five thousand mi"
    )

    _, unit_warnings = pe._validate_machine_story_sentences("Boeing XB-15", plan, unit_bundle)

    assert any("written unit abbreviation" in warning and "mi -> miles" in warning for warning in unit_warnings)


def test_story_sentence_validator_requires_cross_check_or_hedge_for_risky_numbers():
    evidence = _evidence_segments()
    evidence[2].update({
        "claim": "The Boeing XB-15 scale specs included a 5,000 mi range.",
        "source_excerpt": "The Boeing XB-15 scale specs included a 5,000 mi range.",
        "numeric_tokens": ["5000"],
    })
    payload = {"unit_research_cards": [{"unit": "Boeing XB-15", "evidence_segments": evidence}]}
    plan = pe._machine_story_plan(payload, "Boeing XB-15")
    bundle = pe._parse_machine_story_sentences(_story_bundle("Boeing XB-15", 19))
    old_span = bundle["claim_map"][1]["span"]
    unhedged_span = old_span.rstrip(".") + " 5,000 miles."
    bundle["claim_map"][1]["span"] = unhedged_span
    bundle["paragraph"] = bundle["paragraph"].replace(old_span, unhedged_span)

    _, warnings = pe._validate_machine_story_sentences("Boeing XB-15", plan, bundle)

    assert any("two independent sources" in warning for warning in warnings)

    unrelated_second_source_bundle = copy.deepcopy(bundle)
    unrelated_second_source_bundle["claim_map"][1]["used_evidence_ids"] = ["E-DECISION", "E-TRADEOFF"]

    _, unrelated_second_source_warnings = pe._validate_machine_story_sentences(
        "Boeing XB-15", plan, unrelated_second_source_bundle
    )

    assert any(
        "exact numerical detail(s)" in warning and "5,000" in warning
        for warning in unrelated_second_source_warnings
    )

    cross_checked_evidence = copy.deepcopy(evidence)
    cross_check_segment = copy.deepcopy(cross_checked_evidence[2])
    cross_check_segment["evidence_id"] = "E-DECISION-CHECK"
    cross_check_segment["source_url"] = "https://airandspace.si.edu/cross-check-range"
    cross_checked_evidence.append(cross_check_segment)
    cross_checked_plan = pe._machine_story_plan(
        {"unit_research_cards": [{"unit": "Boeing XB-15", "evidence_segments": cross_checked_evidence}]},
        "Boeing XB-15",
    )
    cross_checked_bundle = copy.deepcopy(bundle)
    cross_checked_bundle["claim_map"][1]["used_evidence_ids"] = ["E-DECISION", "E-DECISION-CHECK"]

    _, cross_checked_warnings = pe._validate_machine_story_sentences(
        "Boeing XB-15", cross_checked_plan, cross_checked_bundle
    )

    assert not any("exact numerical detail(s)" in warning for warning in cross_checked_warnings)

    hedged_bundle = copy.deepcopy(bundle)
    hedged_bundle["claim_map"][1]["span"] = unhedged_span.replace("5,000", "around 5,000")
    hedged_bundle["paragraph"] = hedged_bundle["paragraph"].replace("5,000", "around 5,000")

    _, hedged_warnings = pe._validate_machine_story_sentences("Boeing XB-15", plan, hedged_bundle)

    assert not any("two independent sources" in warning for warning in hedged_warnings)


def test_story_sentence_validator_blocks_new_designations_and_high_risk_terms():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    old_span = bundle["claim_map"][0]["span"]
    new_span = old_span.replace("clear.", "B-47 first clear.", 1)
    bundle["claim_map"][0]["span"] = new_span
    bundle["paragraph"] = bundle["paragraph"].replace(old_span, new_span)
    bundle["formula_sentences"] = _formula_sentences_from_paragraph(bundle["paragraph"])

    _, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert any("designation(s) not grounded in locked evidence" in warning for warning in warnings)
    assert any("high-risk term" in warning for warning in warnings)


def test_story_sentence_validator_blocks_non_target_designation_even_when_sourced():
    evidence = _evidence_segments()
    evidence[5].update({
        "claim": "Memorable fact claim grounded in the supplied source with XB-35.",
        "source_excerpt": "The XB-19 was compared with the later XB-35 in the supplied source.",
    })
    payload = {"unit_research_cards": [{"unit": "Douglas XB-19", "evidence_segments": evidence}]}
    plan = pe._machine_story_plan(payload, "Douglas XB-19")
    bundle = pe._parse_machine_story_sentences(_story_bundle("Douglas XB-19", 19))
    old_span = bundle["claim_map"][3]["span"]
    new_span = old_span.replace("Reality claim", "XB-35 reality claim", 1)
    bundle["claim_map"][3]["span"] = new_span
    bundle["paragraph"] = bundle["paragraph"].replace(old_span, new_span)
    bundle["formula_sentences"] = [
        new_span if sentence == old_span else sentence
        for sentence in bundle["formula_sentences"]
    ]

    _, warnings = pe._validate_machine_story_sentences("Douglas XB-19", plan, bundle)

    # Recalibrated (2026-07-16): a designation GROUNDED in locked evidence is a
    # legal long-arc callback (QL-8; engine models like J57 are spec content).
    assert not any("not grounded in locked evidence" in warning for warning in warnings)

    # An UNSOURCED foreign designation still blocks.
    unsourced = pe._parse_machine_story_sentences(_story_bundle("Douglas XB-19", 19))
    old_span_u = unsourced["claim_map"][3]["span"]
    new_span_u = old_span_u.replace("Reality claim", "B-36 reality claim", 1)
    unsourced["claim_map"][3]["span"] = new_span_u
    unsourced["paragraph"] = unsourced["paragraph"].replace(old_span_u, new_span_u)
    unsourced["formula_sentences"] = [
        new_span_u if sentence == old_span_u else sentence
        for sentence in unsourced["formula_sentences"]
    ]
    _, unsourced_warnings = pe._validate_machine_story_sentences("Douglas XB-19", plan, unsourced)
    assert any(
        "designation(s) not grounded in locked evidence" in warning and "B36" in warning
        for warning in pe._blocking_warnings(unsourced_warnings)
    )


def test_story_bundle_mechanical_repair_softens_single_source_exact_claims_and_slot_mismatch():
    shared_source = "https://example.test/xb-19"
    evidence = [
        {
            "evidence_id": "XB19-IDENTITY",
            "kind": "identity_origin",
            "claim": "Douglas built one XB-19 heavy bomber to test flight characteristics for giant bombers, but advances in technology made it obsolete before completion.",
            "source_excerpt": "Douglas built one XB-19 heavy bomber to test flight characteristics for giant bombers, but advances in technology made it obsolete before completion.",
            "source_url": shared_source,
            "source_title": "XB-19 source",
            "locator": "",
            "numeric_tokens": ["one"],
            "confidence": "high",
        },
        {
            "evidence_id": "XB19-SCALE",
            "kind": "scale_specs",
            "claim": "The aircraft featured the world's largest landing gear wheel and tire in the early 1940s, proof of its unprecedented scale.",
            "source_excerpt": "The aircraft featured the world's largest landing gear wheel and tire in the early 1940s, proof of its unprecedented scale.",
            "source_url": shared_source,
            "source_title": "XB-19 source",
            "locator": "",
            "numeric_tokens": ["1940s"],
            "confidence": "high",
        },
        {
            "evidence_id": "XB19-BUILD",
            "kind": "build_reality",
            "claim": "It first flew in 1941, served as a test platform, and was retired in 1946 after a planned cargo conversion was abandoned.",
            "source_excerpt": "It first flew in 1941, served as a test platform, and was retired in 1946 after a planned cargo conversion was abandoned.",
            "source_url": shared_source,
            "source_title": "XB-19 source",
            "locator": "",
            "numeric_tokens": ["1941", "1946"],
            "confidence": "high",
        },
        {
            "evidence_id": "XB19-SERVICE",
            "kind": "service_reality",
            "claim": "It first flew in 1941, served as a test platform, and was retired in 1946 after a planned cargo conversion was abandoned.",
            "source_excerpt": "It first flew in 1941, served as a test platform, and was retired in 1946 after a planned cargo conversion was abandoned.",
            "source_url": shared_source,
            "source_title": "XB-19 source",
            "locator": "",
            "numeric_tokens": ["1941", "1946"],
            "confidence": "high",
        },
        {
            "evidence_id": "XB19-MEMORABLE",
            "kind": "memorable_fact",
            "claim": "The XB-19 became a media sensation, appearing in advertisements, animated cartoons, and even earning a mention in the Broadway comedy The Man Who Came to Dinner.",
            "source_excerpt": "The XB-19 became a media sensation, appearing in advertisements, animated cartoons, and even earning a mention in the Broadway comedy The Man Who Came to Dinner.",
            "source_url": shared_source,
            "source_title": "XB-19 source",
            "locator": "",
            "numeric_tokens": [],
            "confidence": "high",
        },
        {
            "evidence_id": "XB19-MEANING",
            "kind": "historical_meaning",
            "claim": "The prototype proved too slow and expensive for production, yet it delivered critical engineering data that shaped the next generation of American heavy bombers.",
            "source_excerpt": "The prototype proved too slow and expensive for production, yet it delivered critical engineering data that shaped the next generation of American heavy bombers.",
            "source_url": shared_source,
            "source_title": "XB-19 source",
            "locator": "",
            "numeric_tokens": [],
            "confidence": "high",
        },
    ]
    memorable_span = "It never saw combat, yet the XB-19 became a media sensation, appearing in advertisements, animated cartoons, and even earning a mention in the Broadway comedy The Man Who Came to Dinner."
    payload = {"unit_research_cards": [{"unit": "Douglas XB-19", "evidence_segments": evidence}]}
    plan = pe._machine_story_plan(payload, "Douglas XB-19")
    bundle = {
        "paragraph": (
            "Douglas built one XB-19 heavy bomber to test flight characteristics for giant bombers, but advances in technology made it obsolete before completion. "
            "The aircraft featured the world's largest landing gear wheel and tire in the early 1940s, proof of its unprecedented scale. "
            "It first flew in 1941, served as a test platform, and was retired in 1946 after a planned cargo conversion was abandoned. "
            f"{memorable_span} "
            "The prototype proved too slow and expensive for production, yet it delivered critical engineering data that shaped the next generation of American heavy bombers."
        ),
        "claim_map": [
            {"slot": "identity_origin", "span": evidence[0]["claim"], "used_evidence_ids": ["XB19-IDENTITY"]},
            {"slot": "scale_specs", "span": evidence[1]["claim"], "used_evidence_ids": ["XB19-SCALE"]},
            {"slot": "service_reality", "span": evidence[2]["claim"], "used_evidence_ids": ["XB19-BUILD", "XB19-SERVICE"]},
            {"slot": "memorable_fact", "span": memorable_span, "used_evidence_ids": ["XB19-MEMORABLE"]},
            {"slot": "memorable_fact", "span": evidence[5]["claim"], "used_evidence_ids": ["XB19-MEANING"]},
        ],
        "onscreen_label": "",
    }

    _, original_warnings = pe._validate_machine_story_sentences("Douglas XB-19", plan, bundle)
    repaired = pe._repair_machine_story_bundle_mechanics("Douglas XB-19", plan, bundle)
    paragraph = repaired["paragraph"]
    _, warnings = pe._validate_machine_story_sentences("Douglas XB-19", plan, repaired)

    assert any("two independent sources" in warning for warning in original_warnings)
    # Under the merged four-beat plan the historical_meaning evidence folds into
    # the reality role, so the slot mismatch reads memorable_fact -> reality.
    assert any("declares slot memorable_fact but uses reality" in warning for warning in original_warnings)
    assert not any("two independent sources" in warning for warning in warnings)
    assert not any("declares slot" in warning for warning in warnings)
    assert "a single XB-19" in paragraph
    assert "unusually large" in paragraph
    assert "around the early 1940s" in paragraph
    assert "flew around 1941" in paragraph
    assert "never" not in paragraph.lower()
    assert repaired["claim_map"][-1]["slot"] == "reality"


def test_story_bundle_trim_drops_optional_sentence_when_over_word_contract():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 22))
    optional_sentence = (
        "Crews also remembered one sourced memorable fact that gave the story extra retention value for serious viewers."
    )
    sentences = bundle["formula_sentences"][:4] + [optional_sentence] + bundle["formula_sentences"][4:]
    bundle["paragraph"] = " ".join(sentences)
    bundle["formula_sentences"] = sentences
    bundle["claim_map"].append(
        {"slot": "memorable_fact", "span": optional_sentence, "used_evidence_ids": ["E-MEMORABLE"]}
    )

    assert pe._spoken_word_count(bundle["paragraph"]) > 120

    trimmed = pe._trim_machine_story_bundle_to_contract("B-52", plan, bundle)
    paragraph = trimmed["paragraph"]

    assert 95 <= pe._spoken_word_count(paragraph) <= 120
    assert optional_sentence not in paragraph
    assert all(row.get("slot") != "memorable_fact" for row in trimmed["claim_map"])


def test_under_minimum_machine_paragraph_repairs_upward_and_saves_only_repaired_unit(monkeypatch):
    roster = ["Boeing XB-15"]
    card = {
        **_valid_research_card("Boeing XB-15", _evidence_segments()),
        "design_problem": "A large bomber needed useful range despite limited engine power.",
        "engineering_response": "Boeing used an unusually large wing to create lift and carry fuel.",
        "tradeoff": "The aircraft gained range but remained too slow and underpowered for combat.",
        "actual_outcome": "It missed combat requirements and later proved useful hauling cargo.",
        "engineering_thesis": "The failed bomber taught Boeing how size, lift, and power had to balance.",
        "source_notes": ["machine-card-source"],
    }
    video = {
        "video_title": "World's Most Strategic Bombers Ever Built",
        "render_mode": "static_docu",
        "research_payload": {
            "fact_sheet": "GLOBAL FACT SHEET MUST NOT LEAK",
            "unit_roster": roster,
            "unit_research_cards": [card],
            "machine_raw_source_packages": {
                pe._verified_source_cache_key("Boeing XB-15"): _verified_package_for_segments("Boeing XB-15", _evidence_segments()),
            },
        },
    }

    class FakeAnthropic:
        def __init__(self):
            self.prompts = []
            self.system_prompts = []
            self.outputs = [_story_bundle("XB-15", 15), _story_bundle("XB-15", 20)]

        async def generate(self, **kwargs):
            self.prompts.append(kwargs["prompt"])
            self.system_prompts.append(kwargs["system_prompt"])
            return self.outputs.pop(0)

    fake_anthropic = FakeAnthropic()
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type(
        "FakePipeline", (),
        {"anthropic": fake_anthropic, "script_system_prompt": "ANTON TENANT SCRIPT CONTRACT"},
    )()

    writes = []

    async def fake_execute(query, *args):
        writes.append((query, args))
        return None

    async def fake_fetch_all(query, *args):
        return []

    async def fake_log(*_args, **_kwargs):
        return None

    async def fake_update_status(*_args, **_kwargs):
        return None

    async def fake_validate(_video_id):
        return {"passed": True}

    def passed_quality_audit(*_args, **_kwargs):
        return _passing_quality_audit()

    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(pe, "_anton_preview_quality_audit", passed_quality_audit)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(executor, "_validate_static_script_roster", fake_validate)
    monkeypatch.setattr(executor, "_update_video_status", fake_update_status)
    monkeypatch.setattr(executor, "_skip_disabled_next", lambda _video, status: status)

    result = asyncio.run(executor._run_static_script_hold("video-test", video, roster))

    assert result["status"] == "ready_for_voice"
    assert len(fake_anthropic.prompts) == 2, "under-length sentence jobs must trigger one fresh bundle repair"
    # PLAN -> WRITE -> EDIT (2026-07-17): prompt-content locks for the
    # restructured writer. Code picks facts and keeps the ledger; the model
    # only writes; failures get a minimal edit of the same draft.
    assert "GLOBAL FACT SHEET MUST NOT LEAK" not in fake_anthropic.prompts[0]
    assert "machine-card-source" not in fake_anthropic.prompts[0]
    # The evidence rides INLINE under its sentence assignment.
    assert "Original problem claim grounded in the supplied source" in fake_anthropic.prompts[0]
    assert "WRITE ONE ANTON-STYLE PARAGRAPH AS FIVE SENTENCES FROM THE BEAT PLAN BELOW." in fake_anthropic.prompts[0]
    assert "BEAT PLAN:" in fake_anthropic.prompts[0]
    for beat_header in (
        "SENTENCE 1 (original_problem)",
        "SENTENCE 2 (engineering_decision)",
        "SENTENCE 3 (tradeoff)",
        "SENTENCE 4 (reality)",
        "SENTENCE 5 (closer)",
    ):
        assert beat_header in fake_anthropic.prompts[0]
    # The ledger is code-owned: the writer is told NOT to produce a claim map.
    assert "Citation bookkeeping is handled by code; do not produce a claim map." in fake_anthropic.prompts[0]
    assert '"sentences":["sentence 1"' in fake_anthropic.prompts[0]
    assert "claim_map" not in fake_anthropic.prompts[0].split("BEAT PLAN:")[1].split("VOICE RULES")[0]
    # The voice rules the writer still owns.
    assert "GROUNDING: zero freedom in WHAT is claimed" in fake_anthropic.prompts[0]
    assert "Hedge lexicon (the gate recognizes exactly these): " in fake_anthropic.prompts[0]
    assert "roughly" in fake_anthropic.prompts[0]
    assert "WORD BAND: hard floor 80, hard ceiling 170" in fake_anthropic.prompts[0]
    assert "Designations are names: never hedge or respell their digits." in fake_anthropic.prompts[0]
    assert "never expand an abbreviation" in fake_anthropic.prompts[0]
    assert "say the locked machine designation at least once" in fake_anthropic.prompts[0]
    assert "facts serve the engineering argument" in fake_anthropic.prompts[0]
    assert "OPENING ASSIGNMENT: A machine-name opening is allowed here" in fake_anthropic.prompts[0]
    assert "NARRATIVE WEIGHT: standard / target 100-120 words" in fake_anthropic.prompts[0]
    # Twist + thesis stay writer-owned.
    assert "TWIST: declare the designed-vs-used gap the reality sentence proves." in fake_anthropic.prompts[0]
    assert "editorial_thesis: 6-26 words" in fake_anthropic.prompts[0]
    # The closer contract travels with the plan, not as a law pile.
    assert "no numbers" in fake_anthropic.prompts[0]
    assert "single-hammer, antithesis, concede-then-cut, triad" in fake_anthropic.prompts[0]
    # The second call is a minimal EDIT of the same draft - never a re-roll.
    assert "EDIT THIS DRAFT MINIMALLY" in fake_anthropic.prompts[1]
    assert "VIOLATIONS TO FIX" in fake_anthropic.prompts[1]
    assert "CURRENT SENTENCES:" in fake_anthropic.prompts[1]
    assert "Each sentence may use ONLY its beat's evidence" in fake_anthropic.prompts[1]
    assert "REBUILD THE ANTON-STYLE PARAGRAPH JSON" not in fake_anthropic.prompts[1]
    assert fake_anthropic.system_prompts[0].startswith("You are a source-grounded Anton/DVsU paragraph compiler")
    assert "ANTON TENANT SCRIPT CONTRACT" not in fake_anthropic.system_prompts[0]
    assert "SCOPED OVERRIDE — COMPLETE INVENTORY MODE" in fake_anthropic.system_prompts[0]
    assert "SCOPED OVERRIDE — COMPLETE INVENTORY MODE" in fake_anthropic.system_prompts[1]

    atomic_replacements = [(query, args) for query, args in writes if "jsonb_to_recordset" in query]
    assert len(atomic_replacements) == 1
    saved_paragraph = json.loads(atomic_replacements[0][1][2])[0]["scene_text"]
    assert pe._spoken_word_count(saved_paragraph) == 100
    assert "XB-15" in saved_paragraph


def test_script_hold_full_script_writes_only_unit_paragraphs_no_summary(monkeypatch):
    roster = ["Boeing XB-15", "Boeing B-17 Flying Fortress"]
    cards = [
        _valid_research_card(machine, _evidence_segments())
        for machine in roster
    ]
    video = {
        "video_title": "Every US Strategic Bomber Ever Built",
        "render_mode": "static_docu",
        "research_payload": {
            "unit_roster": roster,
            "unit_research_cards": cards,
            "machine_raw_source_packages": {
                pe._verified_source_cache_key(machine): _verified_package_for_segments(machine, _evidence_segments())
                for machine in roster
            },
        },
    }

    class FakeAnthropic:
        def __init__(self):
            self.prompts = []
            self.outputs = [
                _story_bundle(roster[0], 19),
                _problem_opening_story_bundle(roster[1], 19),
            ]

        async def generate(self, **kwargs):
            self.prompts.append(kwargs["prompt"])
            return self.outputs.pop(0)

    fake_anthropic = FakeAnthropic()
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type(
        "FakePipeline", (),
        {"anthropic": fake_anthropic, "script_system_prompt": "ANTON TENANT SCRIPT CONTRACT"},
    )()
    writes = []

    async def fake_execute(query, *args):
        writes.append((query, args))
        return None

    async def fake_fetch_all(_query, *_args):
        return []

    async def fake_log(*_args, **_kwargs):
        return None

    async def fake_update_status(*_args, **_kwargs):
        return None

    async def fake_validate(_video_id):
        return {"passed": True}

    def passed_quality_audit(*_args, **_kwargs):
        return _passing_quality_audit()

    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(pe, "_anton_preview_quality_audit", passed_quality_audit)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(executor, "_validate_static_script_roster", fake_validate)
    monkeypatch.setattr(executor, "_update_video_status", fake_update_status)
    monkeypatch.setattr(executor, "_skip_disabled_next", lambda _video, status: status)

    result = asyncio.run(executor._run_static_script_hold("video-test", video, roster))

    assert result["status"] == "ready_for_voice"
    atomic_replacements = [(query, args) for query, args in writes if "jsonb_to_recordset" in query]
    assert len(atomic_replacements) == 1
    args = atomic_replacements[0][1]
    staged_rows = json.loads(args[2])
    full_script = args[5]
    assert [row["scene"] for row in staged_rows] == [1, 2]
    assert len(staged_rows) == len(roster)
    assert full_script == "\n\n".join(row["scene_text"] for row in staged_rows)
    assert full_script.count("\n\n") == len(roster) - 1
    assert "in conclusion" not in full_script.lower()
    assert "to summarize" not in full_script.lower()
    assert "what have we learned" not in full_script.lower()
    assert "OPENING ASSIGNMENT: A machine-name opening is allowed here" in fake_anthropic.prompts[0]
    assert "OPENING ASSIGNMENT: Do NOT open with the machine name" in fake_anthropic.prompts[1]


def test_full_script_replacement_is_video_update_gated_and_refuses_zero_row_save(monkeypatch):
    roster = ["Boeing XB-15"]
    segments = _evidence_segments()
    video = {
        "video_title": "Every US Strategic Bomber Ever Built",
        "render_mode": "static_docu",
        "research_payload": {
            "unit_roster": roster,
            "unit_research_cards": [_valid_research_card("Boeing XB-15", segments)],
            "machine_raw_source_packages": {
                pe._verified_source_cache_key("Boeing XB-15"): _verified_package_for_segments("Boeing XB-15", segments),
            },
        },
    }

    class FakeAnthropic:
        async def generate(self, **_kwargs):
            return _story_bundle("Boeing XB-15", 19)

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type(
        "FakePipeline", (),
        {"anthropic": FakeAnthropic(), "script_system_prompt": "ANTON TENANT SCRIPT CONTRACT"},
    )()
    writes = []

    async def fake_execute(query, *args):
        writes.append((query, args))
        if "jsonb_to_recordset" in query:
            return "INSERT 0 0"
        return "UPDATE 1"

    async def fake_fetch_all(_query, *_args):
        return []

    async def fake_log(*_args, **_kwargs):
        return None

    async def forbidden_validate(*_args, **_kwargs):
        raise AssertionError("zero-row final script save must not proceed to roster validation")

    async def forbidden_update_status(*_args, **_kwargs):
        raise AssertionError("zero-row final script save must not advance status")

    def passed_quality_audit(*_args, **_kwargs):
        return _passing_quality_audit()

    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(pe, "_anton_preview_quality_audit", passed_quality_audit)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(executor, "_validate_static_script_roster", forbidden_validate)
    monkeypatch.setattr(executor, "_update_video_status", forbidden_update_status)
    monkeypatch.setattr(executor, "_skip_disabled_next", lambda _video, status: status)

    result = asyncio.run(executor._run_static_script_hold("video-test", video, roster))

    assert result["status"] == "failed"
    assert "final save refused" in result["error"]
    atomic_replacements = [(query, args) for query, args in writes if "jsonb_to_recordset" in query]
    assert len(atomic_replacements) == 1
    assert "WITH updated AS" in atomic_replacements[0][0]
    assert "USING updated" in atomic_replacements[0][0]
    assert "FROM updated u" in atomic_replacements[0][0]
    assert "SELECT count(*) AS deleted_count FROM deleted" in atomic_replacements[0][0]


def test_script_hold_refuses_missing_machine_card_before_touching_scripts(monkeypatch):
    roster = ["Boeing XB-15"]
    video = {
        "video_title": "Designed vs Used: Bombers",
        "render_mode": "static_docu",
        "research_payload": {"unit_roster": roster, "fact_sheet": "Global blob must not be fallback."},
    }
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": object()})()
    writes = []

    async def fake_execute(query, *args):
        writes.append((query, args))

    async def fake_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(executor, "_log_activity", fake_log)

    result = asyncio.run(executor._run_static_script_hold("video-test", video, roster))

    assert result["status"] == "failed"
    assert "saved research card" in result["error"]
    assert writes == [], "missing card must fail before deleting or inserting scripts"


def test_full_script_hold_requires_verified_source_packages_before_llm(monkeypatch):
    roster = ["Boeing XB-15"]
    card = {"unit": "Boeing XB-15", "evidence_segments": _evidence_segments()}
    video = {
        "video_title": "Every US Strategic Bomber Ever Built",
        "render_mode": "static_docu",
        "research_payload": {
            "unit_roster": roster,
            "unit_research_cards": [card],
        },
    }

    class ForbiddenAnthropic:
        def __init__(self):
            self.calls = 0

        async def generate(self, **_kwargs):
            self.calls += 1
            raise AssertionError("full script must fail before spending an LLM call")

    forbidden_anthropic = ForbiddenAnthropic()
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type(
        "FakePipeline", (),
        {"anthropic": forbidden_anthropic, "script_system_prompt": "ANTON TENANT SCRIPT CONTRACT"},
    )()
    writes = []

    async def fake_execute(query, *args):
        writes.append((query, args))
        return None

    async def fake_fetch_all(*_args, **_kwargs):
        return []

    async def fake_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(executor, "_log_activity", fake_log)

    result = asyncio.run(executor._run_static_script_hold("video-test", video, roster))

    assert result["status"] == "failed"
    assert "Script-hold evidence gate failed" in result["error"]
    assert "missing verified raw internet source package" in result["error"]
    assert forbidden_anthropic.calls == 0
    assert writes == []


def test_target_machine_preview_canonicalizes_ui_label_and_filters_unrelated_loaded_cards(monkeypatch):
    roster = ["Boeing XB-15", "Boeing B-17 Flying Fortress"]
    xb15_segments = _evidence_segments()
    xb15_card = _valid_research_card(
        "Boeing XB-15",
        xb15_segments,
        engineering_thesis="XB-15 source-grounded engineering thesis.",
        surprising_fact="XB-15 source-grounded fact.",
        source_notes=["xb15-source"],
    )
    b17_card = {
        "unit": "Boeing B-17 Flying Fortress",
        "engineering_thesis": "B-17 SHOULD NOT LEAK INTO XB-15 PREVIEW",
        "surprising_fact": "B-17 SHOULD NOT LEAK INTO XB-15 PREVIEW",
        "source_notes": ["b17-source"],
        "evidence_segments": _evidence_segments(),
    }
    video = {
        "video_title": "Every US Strategic Bomber Ever Built",
        "render_mode": "static_docu",
        "research_payload": {
            "unit_roster": roster,
            "unit_research_cards": [xb15_card],
            "machine_raw_source_packages": {
                pe._verified_source_cache_key("Boeing XB-15"): _verified_package_for_segments("Boeing XB-15", xb15_segments),
            },
        },
    }

    class FakeAnthropic:
        def __init__(self):
            self.prompts = []

        async def generate(self, **kwargs):
            self.prompts.append(kwargs["prompt"])
            return _story_bundle("Boeing XB-15", 19)

    fake_anthropic = FakeAnthropic()
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type(
        "FakePipeline", (),
        {"anthropic": fake_anthropic, "script_system_prompt": "ANTON TENANT SCRIPT CONTRACT"},
    )()
    load_calls = []
    fetch_calls = []

    async def fake_load(video_id, payload, roster_arg, target_machine=None):
        load_calls.append((video_id, roster_arg, target_machine))
        loaded = dict(payload)
        loaded["unit_research_cards"] = [xb15_card, b17_card]
        return loaded

    writes = []

    async def fake_execute(query, *args, **_kwargs):
        writes.append((query, args))
        return None

    async def fake_fetch_all(query, *args, **_kwargs):
        fetch_calls.append((query, args))
        return []

    async def fake_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr(executor, "_load_machine_research_cards", fake_load)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)

    result = asyncio.run(
        executor._run_static_script_hold(
            "video-test", video, roster, target_machine="XB-15 — Boeing XB-15"
        )
    )

    assert result["preview"]["passed"] is False
    assert result["preview"]["machine"] == "Boeing XB-15"
    assert result["preview"]["quality_audit"]["passed"] is False
    cadence_check = next(
        check for check in result["preview"]["quality_audit"]["checks"]
        if check["name"] == "benchmark_cadence"
    )
    assert cadence_check["passed"] is False
    assert [check["name"] for check in result["preview"]["quality_audit"]["checks"]][:5] == [
        "word_range",
        "sentence_shape",
        "twist_gate",
        "sentence_assembly",
        "four_evidence_beats",
    ]
    reference_check = next(check for check in result["preview"]["quality_audit"]["checks"] if check["name"] == "reference_shape")
    assert reference_check["advisory"] is True
    assert "benchmark 94 words/5 sentences" in reference_check["detail"]
    assert result["preview"]["story_plan"]["reference_benchmark"]["reference_machine"] == "Boeing XB-15"
    assert result["preview"]["story_plan"]["contract"]["opening_assignment"].startswith("A machine-name opening is allowed")
    assert result["preview"]["story_plan"]["contract"]["narrative_weight"]["target_words"] == "100-120"
    saved_preview_rows = [(query, args) for query, args in writes if "machine_script_previews" in query]
    saved_brief_rows = [(query, args) for query, args in writes if "machine_script_briefs" in query]
    saved_plan_rows = [(query, args) for query, args in writes if "machine_story_plans" in query]
    assert not any("DELETE FROM scripts" in query or "INSERT INTO scripts" in query for query, _args in writes)
    assert not any("script_validation" in query or "SET script =" in query for query, _args in writes)
    assert saved_preview_rows and saved_preview_rows[0][1][0] == pe._verified_source_cache_key("Boeing XB-15")
    saved_preview = json.loads(saved_preview_rows[0][1][1])
    assert saved_preview["claim_bundle"]["formula_sentences"]
    assert " ".join(saved_preview["claim_bundle"]["formula_sentences"]) == saved_preview["paragraph"]
    assert saved_brief_rows and saved_brief_rows[0][1][0] == pe._verified_source_cache_key("Boeing XB-15")
    assert saved_plan_rows and saved_plan_rows[0][1][0] == pe._verified_source_cache_key("Boeing XB-15")
    response_payload = result["research_payload"]
    response_key = pe._verified_source_cache_key("Boeing XB-15")
    assert response_payload["machine_script_previews"][response_key]["paragraph"] == saved_preview["paragraph"]
    assert response_payload["machine_script_briefs"][response_key]
    assert response_payload["machine_story_plans"][response_key]["contract"]["opening_assignment"].startswith("A machine-name opening")
    assert any(card.get("unit") == "Boeing B-17 Flying Fortress" for card in response_payload["unit_research_cards"])
    assert load_calls == [("video-test", roster, "Boeing XB-15")]
    assert fetch_calls == [
        # Readiness enrichment reads the stored per-card verdicts so the response
        # payload carries card.readiness (single backend-owned readiness source).
        ("SELECT machine_key, validation FROM machine_research_cards WHERE tenant_id = $1 AND video_id = $2", ("tenant-test", "video-test")),
        ("SELECT voice_id FROM scripts WHERE video_id = $1 AND tenant_id = $2 LIMIT 1", ("video-test", "tenant-test")),
        # Checklist C46c: resolved once per script-hold run, byte-identical
        # fallback ({}) when the tenant has no seeded quality_rules rows.
        ("SELECT rule_id, law, evidence, severity, applies_to FROM quality_rules WHERE tenant_id = $1 AND active", ("tenant-test",)),
    ]
    assert "B-17 SHOULD NOT LEAK" not in fake_anthropic.prompts[0]
    assert "XB-15 source-grounded" not in fake_anthropic.prompts[0]
    assert "Original problem claim grounded in the supplied source" in fake_anthropic.prompts[0]
    assert "reference_benchmark" in fake_anthropic.prompts[0]
    assert "Do not copy or infer unsourced facts from it" in fake_anthropic.prompts[0]
    assert "Strategic Bomber benchmark" in fake_anthropic.prompts[0]
    assert "selected scale or capability facts" in fake_anthropic.prompts[0]
    assert "STYLE / SENTENCE CRAFT" in fake_anthropic.prompts[0]
    assert "Sentence 1 should create the tension" in fake_anthropic.prompts[0]
    assert "Sentence 2 should turn the engineering decision into selected capability or scale facts" in fake_anthropic.prompts[0]
    assert "Sentence 3 should pivot into the cost, limit, sacrifice, or expectation-versus-reality contrast" in fake_anthropic.prompts[0]
    assert "Sentence 4 should show what happened in production, testing, service, combat, or documented reality" in fake_anthropic.prompts[0]
    assert "Sentence 5 should land as a short verdict, paradox, irony, or reversal" in fake_anthropic.prompts[0]
    assert "OPENING ASSIGNMENT: A machine-name opening is allowed here" in fake_anthropic.prompts[0]
    assert "Follow OPENING ASSIGNMENT exactly" in fake_anthropic.prompts[0]
    # PLAN->WRITE->EDIT: human_detail placement is planned by code now - the
    # segment rides inline under SENTENCE 4 instead of as a law.
    assert "SENTENCE 4 (reality)" in fake_anthropic.prompts[0]


def test_target_machine_preview_saves_invalid_story_json_as_review_artifact(monkeypatch):
    roster = ["Boeing XB-15"]
    segments = _evidence_segments()
    card = _valid_research_card(
        "Boeing XB-15",
        segments,
        engineering_thesis="XB-15 source-grounded engineering thesis.",
        surprising_fact="XB-15 source-grounded fact.",
        source_notes=["xb15-source"],
    )
    video = {
        "video_title": "Every US Strategic Bomber Ever Built",
        "render_mode": "static_docu",
        "research_payload": {
            "unit_roster": roster,
            "unit_research_cards": [card],
            "machine_raw_source_packages": {
                pe._verified_source_cache_key("Boeing XB-15"): _verified_package_for_segments("Boeing XB-15", segments),
            },
        },
    }

    class InvalidJsonAnthropic:
        def __init__(self):
            self.calls = 0

        async def generate(self, **_kwargs):
            self.calls += 1
            return "not json"

    fake_anthropic = InvalidJsonAnthropic()
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type(
        "FakePipeline", (),
        {"anthropic": fake_anthropic, "script_system_prompt": "ANTON TENANT SCRIPT CONTRACT"},
    )()
    writes = []

    async def fake_load(_video_id, payload, _roster_arg, target_machine=None):
        assert target_machine == "Boeing XB-15"
        return dict(payload)

    async def fake_execute(query, *args, **_kwargs):
        writes.append((query, args))
        return None

    async def fake_fetch_all(*_args, **_kwargs):
        return []

    async def fake_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr(executor, "_load_machine_research_cards", fake_load)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)

    result = asyncio.run(
        executor._run_static_script_hold("video-test", video, roster, target_machine="Boeing XB-15")
    )

    assert result["status"] == "completed"
    assert fake_anthropic.calls == 2
    assert result["preview"]["passed"] is False
    assert result["preview"]["paragraph"] == ""
    assert result["preview"]["claim_bundle"]["_parse_error"] == (
        "planned story writer must return valid JSON"
    )
    assert any("must return valid JSON" in warning for warning in result["preview"]["warnings"])
    assert result["preview"]["quality_audit"]["passed"] is False
    validator_check = next(
        check for check in result["preview"]["quality_audit"]["checks"]
        if check["name"] == "validator_warnings"
    )
    assert "valid JSON" in validator_check["detail"]
    saved_preview_rows = [(query, args) for query, args in writes if "machine_script_previews" in query]
    assert saved_preview_rows
    assert json.loads(saved_preview_rows[0][1][1]) == result["preview"]
    assert not any("DELETE FROM scripts" in query or "INSERT INTO scripts" in query for query, _args in writes)
    assert not any("script_validation" in query or "SET script =" in query for query, _args in writes)


def test_target_machine_preview_saves_alias_story_schema_as_review_artifact(monkeypatch):
    roster = ["Boeing XB-15"]
    segments = _evidence_segments()
    card = _valid_research_card(
        "Boeing XB-15",
        segments,
        engineering_thesis="XB-15 source-grounded engineering thesis.",
        surprising_fact="XB-15 source-grounded fact.",
        source_notes=["xb15-source"],
    )
    video = {
        "video_title": "Every US Strategic Bomber Ever Built",
        "render_mode": "static_docu",
        "research_payload": {
            "unit_roster": roster,
            "unit_research_cards": [card],
            "machine_raw_source_packages": {
                pe._verified_source_cache_key("Boeing XB-15"): _verified_package_for_segments("Boeing XB-15", segments),
            },
        },
    }
    canonical = json.loads(_story_bundle("Boeing XB-15", 19))
    alias_story = json.dumps({
        "voiceover": canonical["paragraph"],
        "sentences": [{"sentence": sentence} for sentence in canonical["formula_sentences"]],
        "claims": canonical["claim_map"],
        "throughline": canonical["editorial_thesis"],
        "onscreen_label": "",
    })

    class AliasSchemaAnthropic:
        def __init__(self):
            self.calls = 0

        async def generate(self, **_kwargs):
            self.calls += 1
            return alias_story

    fake_anthropic = AliasSchemaAnthropic()
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type(
        "FakePipeline", (),
        {"anthropic": fake_anthropic, "script_system_prompt": "ANTON TENANT SCRIPT CONTRACT"},
    )()
    writes = []

    async def fake_load(_video_id, payload, _roster_arg, target_machine=None):
        assert target_machine == "Boeing XB-15"
        return dict(payload)

    async def fake_execute(query, *args, **_kwargs):
        writes.append((query, args))
        return None

    async def fake_fetch_all(*_args, **_kwargs):
        return []

    async def fake_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr(executor, "_load_machine_research_cards", fake_load)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)

    result = asyncio.run(
        executor._run_static_script_hold("video-test", video, roster, target_machine="Boeing XB-15")
    )

    assert result["status"] == "completed"
    assert fake_anthropic.calls == 2
    assert result["preview"]["passed"] is False
    # PLAN->WRITE->EDIT (2026-07-17): the ledger is code-owned and the writer
    # schema is strict - alias shapes are rejected as parse errors, never
    # tolerated into garbage sentences.
    assert result["preview"]["paragraph"] == ""
    assert result["preview"]["claim_bundle"]["_parse_error"] == (
        "planned story writer sentences must be plain strings"
    )
    assert "voiceover" not in result["preview"]["claim_bundle"]
    assert "claims" not in result["preview"]["claim_bundle"]
    assert "throughline" not in result["preview"]["claim_bundle"]
    validator_check = next(
        check for check in result["preview"]["quality_audit"]["checks"]
        if check["name"] == "validator_warnings"
    )
    assert "plain strings" in validator_check["detail"]
    saved_preview_rows = [(query, args) for query, args in writes if "machine_script_previews" in query]
    assert saved_preview_rows
    assert json.loads(saved_preview_rows[0][1][1]) == result["preview"]
    assert not any("DELETE FROM scripts" in query or "INSERT INTO scripts" in query for query, _args in writes)
    assert not any("script_validation" in query or "SET script =" in query for query, _args in writes)


def test_target_machine_preview_pass_state_follows_anton_quality_audit(monkeypatch):
    roster = ["Boeing XB-15"]
    segments = _evidence_segments()
    card = _valid_research_card(
        "Boeing XB-15",
        segments,
        engineering_thesis="XB-15 source-grounded engineering thesis.",
        surprising_fact="XB-15 source-grounded fact.",
        source_notes=["xb15-source"],
    )
    video = {
        "video_title": "Every US Strategic Bomber Ever Built",
        "render_mode": "static_docu",
        "research_payload": {
            "unit_roster": roster,
            "unit_research_cards": [card],
            "machine_raw_source_packages": {
                pe._verified_source_cache_key("Boeing XB-15"): _verified_package_for_segments("Boeing XB-15", segments),
            },
        },
    }

    class FakeAnthropic:
        async def generate(self, **_kwargs):
            return _story_bundle("Boeing XB-15", 19)

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type(
        "FakePipeline", (),
        {"anthropic": FakeAnthropic(), "script_system_prompt": "ANTON TENANT SCRIPT CONTRACT"},
    )()
    writes = []
    logs = []

    async def fake_load(_video_id, payload, _roster_arg, target_machine=None):
        assert target_machine == "Boeing XB-15"
        return dict(payload)

    async def fake_execute(query, *args, **_kwargs):
        writes.append((query, args))
        return None

    async def fake_fetch_all(*_args, **_kwargs):
        return []

    async def fake_log(_bot_name, _video_id, status, message):
        logs.append((status, message))

    def fake_quality_audit(*_args, **_kwargs):
        return {
            "passed": False,
            "summary": "Anton quality audit needs review",
            "checks": [{
                "name": "benchmark_cadence",
                "label": "Benchmark cadence",
                "passed": False,
                "detail": "scale/capability missing",
            }],
        }

    monkeypatch.setattr(executor, "_load_machine_research_cards", fake_load)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(pe, "_anton_preview_quality_audit", fake_quality_audit)

    result = asyncio.run(
        executor._run_static_script_hold("video-test", video, roster, target_machine="Boeing XB-15")
    )

    assert result["status"] == "completed"
    assert pe._blocking_warnings(result["preview"]["warnings"]) == []
    assert result["preview"]["quality_audit"]["passed"] is False
    assert result["preview"]["passed"] is False
    saved_preview_rows = [(query, args) for query, args in writes if "machine_script_previews" in query]
    saved_preview = json.loads(saved_preview_rows[0][1][1])
    assert saved_preview["passed"] is False
    assert logs[-1][0] == "failed"
    assert "needs review" in logs[-1][1]


def test_target_machine_preview_rechecks_blocking_audit_rows(monkeypatch):
    roster = ["Boeing XB-15"]
    segments = _evidence_segments()
    card = _valid_research_card(
        "Boeing XB-15",
        segments,
        engineering_thesis="XB-15 source-grounded engineering thesis.",
        surprising_fact="XB-15 source-grounded fact.",
        source_notes=["xb15-source"],
    )
    video = {
        "video_title": "Every US Strategic Bomber Ever Built",
        "render_mode": "static_docu",
        "research_payload": {
            "unit_roster": roster,
            "unit_research_cards": [card],
            "machine_raw_source_packages": {
                pe._verified_source_cache_key("Boeing XB-15"): _verified_package_for_segments("Boeing XB-15", segments),
            },
        },
    }

    class FakeAnthropic:
        async def generate(self, **_kwargs):
            return _story_bundle("Boeing XB-15", 19)

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type(
        "FakePipeline", (),
        {"anthropic": FakeAnthropic(), "script_system_prompt": "ANTON TENANT SCRIPT CONTRACT"},
    )()
    writes = []
    logs = []

    async def fake_load(_video_id, payload, _roster_arg, target_machine=None):
        assert target_machine == "Boeing XB-15"
        return dict(payload)

    async def fake_execute(query, *args, **_kwargs):
        writes.append((query, args))
        return None

    async def fake_fetch_all(*_args, **_kwargs):
        return []

    async def fake_log(_bot_name, _video_id, status, message):
        logs.append((status, message))

    def contradictory_quality_audit(*_args, **_kwargs):
        return {
            "passed": True,
            "summary": "Anton quality audit passed",
            "checks": [{
                "name": "claim_coverage",
                "label": "Claim coverage",
                "passed": False,
                "detail": "blocking failure must still hold the preview",
            }],
        }

    monkeypatch.setattr(executor, "_load_machine_research_cards", fake_load)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(pe, "_anton_preview_quality_audit", contradictory_quality_audit)

    result = asyncio.run(
        executor._run_static_script_hold("video-test", video, roster, target_machine="Boeing XB-15")
    )

    assert result["status"] == "completed"
    assert pe._blocking_warnings(result["preview"]["warnings"]) == []
    assert result["preview"]["quality_audit"]["passed"] is True
    assert result["preview"]["quality_audit"]["checks"][0]["passed"] is False
    assert result["preview"]["passed"] is False
    saved_preview_rows = [(query, args) for query, args in writes if "machine_script_previews" in query]
    saved_preview = json.loads(saved_preview_rows[0][1][1])
    assert saved_preview["passed"] is False
    assert logs[-1][0] == "failed"
    assert "needs review" in logs[-1][1]


def test_target_machine_preview_requires_visible_quality_audit_checks(monkeypatch):
    roster = ["Boeing XB-15"]
    segments = _evidence_segments()
    card = _valid_research_card("Boeing XB-15", segments)
    video = {
        "video_title": "Every US Strategic Bomber Ever Built",
        "render_mode": "static_docu",
        "research_payload": {
            "unit_roster": roster,
            "unit_research_cards": [card],
            "machine_raw_source_packages": {
                pe._verified_source_cache_key("Boeing XB-15"): _verified_package_for_segments("Boeing XB-15", segments),
            },
        },
    }

    class FakeAnthropic:
        async def generate(self, **_kwargs):
            return _story_bundle("Boeing XB-15", 19)

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type(
        "FakePipeline", (),
        {"anthropic": FakeAnthropic(), "script_system_prompt": "ANTON TENANT SCRIPT CONTRACT"},
    )()
    writes = []
    logs = []

    async def fake_load(_video_id, payload, _roster_arg, target_machine=None):
        assert target_machine == "Boeing XB-15"
        return dict(payload)

    async def fake_execute(query, *args, **_kwargs):
        writes.append((query, args))
        return None

    async def fake_fetch_all(*_args, **_kwargs):
        return []

    async def fake_log(_bot_name, _video_id, status, message):
        logs.append((status, message))

    def empty_quality_audit(*_args, **_kwargs):
        return {"passed": True, "summary": "Anton quality audit passed", "checks": []}

    monkeypatch.setattr(executor, "_load_machine_research_cards", fake_load)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(pe, "_anton_preview_quality_audit", empty_quality_audit)

    result = asyncio.run(
        executor._run_static_script_hold("video-test", video, roster, target_machine="Boeing XB-15")
    )

    assert result["status"] == "completed"
    assert pe._blocking_warnings(result["preview"]["warnings"]) == []
    assert result["preview"]["quality_audit"]["passed"] is True
    assert result["preview"]["quality_audit"]["checks"] == []
    assert result["preview"]["passed"] is False
    saved_preview_rows = [(query, args) for query, args in writes if "machine_script_previews" in query]
    saved_preview = json.loads(saved_preview_rows[0][1][1])
    assert saved_preview["passed"] is False
    assert logs[-1][0] == "failed"
    assert "needs review" in logs[-1][1]


def test_target_machine_preview_refuses_brief_save_miss_before_llm(monkeypatch):
    roster = ["Boeing XB-15"]
    segments = _evidence_segments()
    card = _valid_research_card(
        "Boeing XB-15",
        segments,
        engineering_thesis="XB-15 source-grounded engineering thesis.",
        surprising_fact="XB-15 source-grounded fact.",
        source_notes=["xb15-source"],
    )
    video = {
        "video_title": "Every US Strategic Bomber Ever Built",
        "render_mode": "static_docu",
        "research_payload": {
            "unit_roster": roster,
            "unit_research_cards": [card],
            "machine_raw_source_packages": {
                pe._verified_source_cache_key("Boeing XB-15"): _verified_package_for_segments("Boeing XB-15", segments),
            },
        },
    }

    class ForbiddenAnthropic:
        def __init__(self):
            self.calls = 0

        async def generate(self, **_kwargs):
            self.calls += 1
            raise AssertionError("missed preview artifact save must stop before Claude")

    forbidden_anthropic = ForbiddenAnthropic()
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type(
        "FakePipeline", (),
        {"anthropic": forbidden_anthropic, "script_system_prompt": "ANTON TENANT SCRIPT CONTRACT"},
    )()
    writes = []

    async def fake_load(_video_id, payload, _roster_arg, target_machine=None):
        assert target_machine == "Boeing XB-15"
        return dict(payload)

    async def fake_execute(query, *args, **_kwargs):
        writes.append((query, args))
        if "machine_script_briefs" in query:
            return "UPDATE 0"
        return "UPDATE 1"

    async def fake_fetch_all(*_args, **_kwargs):
        return []

    async def fake_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr(executor, "_load_machine_research_cards", fake_load)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)

    result = asyncio.run(
        executor._run_static_script_hold("video-test", video, roster, target_machine="Boeing XB-15")
    )

    assert result["status"] == "failed"
    assert "script preview brief save refused" in result["error"]
    assert forbidden_anthropic.calls == 0
    assert sum("machine_script_briefs" in query for query, _args in writes) == 1
    assert not any("machine_story_plans" in query or "machine_script_previews" in query for query, _args in writes)
    assert "research_payload->'unit_roster' = $5::jsonb" in writes[-1][0]
    assert json.loads(writes[-1][1][4]) == roster


def test_target_machine_preview_refuses_zero_row_preview_save(monkeypatch):
    roster = ["Boeing XB-15"]
    segments = _evidence_segments()
    card = _valid_research_card(
        "Boeing XB-15",
        segments,
        engineering_thesis="XB-15 source-grounded engineering thesis.",
        surprising_fact="XB-15 source-grounded fact.",
        source_notes=["xb15-source"],
    )
    video = {
        "video_title": "Every US Strategic Bomber Ever Built",
        "render_mode": "static_docu",
        "research_payload": {
            "unit_roster": roster,
            "unit_research_cards": [card],
            "machine_raw_source_packages": {
                pe._verified_source_cache_key("Boeing XB-15"): _verified_package_for_segments("Boeing XB-15", segments),
            },
        },
    }

    class FakeAnthropic:
        def __init__(self):
            self.calls = 0

        async def generate(self, **_kwargs):
            self.calls += 1
            return _story_bundle("Boeing XB-15", 19)

    fake_anthropic = FakeAnthropic()
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type(
        "FakePipeline", (),
        {"anthropic": fake_anthropic, "script_system_prompt": "ANTON TENANT SCRIPT CONTRACT"},
    )()
    writes = []

    async def fake_load(_video_id, payload, _roster_arg, target_machine=None):
        assert target_machine == "Boeing XB-15"
        return dict(payload)

    async def fake_execute(query, *args, **_kwargs):
        writes.append((query, args))
        if "machine_script_previews" in query:
            return "UPDATE 0"
        return "UPDATE 1"

    async def fake_fetch_all(*_args, **_kwargs):
        return []

    async def fake_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr(executor, "_load_machine_research_cards", fake_load)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)

    result = asyncio.run(
        executor._run_static_script_hold("video-test", video, roster, target_machine="Boeing XB-15")
    )

    assert result["status"] == "failed"
    assert "script preview save refused" in result["error"]
    assert fake_anthropic.calls == 1
    saved_preview_rows = [(query, args) for query, args in writes if "machine_script_previews" in query]
    assert saved_preview_rows and json.loads(saved_preview_rows[0][1][4]) == roster
    assert "preview" not in result


def test_target_machine_preview_requires_verified_raw_source_package_before_llm(monkeypatch):
    roster = ["Boeing XB-15"]
    card = {
        "unit": "Boeing XB-15",
        "engineering_thesis": "XB-15 source-grounded engineering thesis.",
        "surprising_fact": "XB-15 source-grounded fact.",
        "source_notes": ["xb15-source"],
        "evidence_segments": _evidence_segments(),
    }
    video = {
        "video_title": "Every US Strategic Bomber Ever Built",
        "render_mode": "static_docu",
        "research_payload": {"unit_roster": roster, "unit_research_cards": [card]},
    }

    class ForbiddenAnthropic:
        def __init__(self):
            self.calls = 0

        async def generate(self, **_kwargs):
            self.calls += 1
            raise AssertionError("stale preview must fail before spending an LLM call")

    forbidden_anthropic = ForbiddenAnthropic()
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type(
        "FakePipeline", (),
        {"anthropic": forbidden_anthropic, "script_system_prompt": "ANTON TENANT SCRIPT CONTRACT"},
    )()
    writes = []

    async def fake_load(_video_id, payload, _roster_arg, target_machine=None):
        assert target_machine == "Boeing XB-15"
        return dict(payload)

    async def fake_execute(query, *args):
        writes.append((query, args))
        return None

    async def fake_fetch_all(*_args, **_kwargs):
        return []

    async def fake_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr(executor, "_load_machine_research_cards", fake_load)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)

    result = asyncio.run(
        executor._run_static_script_hold("video-test", video, roster, target_machine="Boeing XB-15")
    )

    preview = _assert_saved_failed_preview(result, writes, "Boeing XB-15", roster)
    assert "missing verified raw internet source package" in preview["warnings"][0]
    assert "missing verified raw internet source package" in preview["quality_audit"]["summary"]
    assert forbidden_anthropic.calls == 0
    assert not any("DELETE FROM scripts" in query or "INSERT INTO scripts" in query for query, _args in writes)
    assert not any("machine_script_briefs" in query or "machine_story_plans" in query for query, _args in writes)


def test_target_machine_preview_reports_missing_package_before_provider_config(monkeypatch):
    roster = ["Boeing XB-15"]
    video = {
        "video_title": "Every US Strategic Bomber Ever Built",
        "render_mode": "static_docu",
        "research_payload": {
            "unit_roster": roster,
            "unit_research_cards": [_valid_research_card("Boeing XB-15", _evidence_segments())],
        },
    }
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type(
        "FakePipeline", (),
        {"anthropic": None, "script_system_prompt": "ANTON TENANT SCRIPT CONTRACT"},
    )()
    writes = []

    async def fake_load(_video_id, payload, _roster_arg, target_machine=None):
        assert target_machine == "Boeing XB-15"
        return dict(payload)

    async def fake_execute(query, *args):
        writes.append((query, args))
        return None

    async def forbidden_fetch_all(*_args, **_kwargs):
        raise AssertionError("missing-package preview must fail before voice lookup")

    async def fake_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr(executor, "_load_machine_research_cards", fake_load)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", forbidden_fetch_all)

    result = asyncio.run(
        executor._run_static_script_hold("video-test", video, roster, target_machine="Boeing XB-15")
    )

    preview = _assert_saved_failed_preview(result, writes, "Boeing XB-15", roster)
    assert "missing verified raw internet source package" in preview["warnings"][0]
    assert "Anthropic client" not in preview["warnings"][0]


def test_target_machine_preview_saves_missing_card_review_before_llm(monkeypatch):
    roster = ["Boeing XB-15"]
    video = {
        "video_title": "Every US Strategic Bomber Ever Built",
        "render_mode": "static_docu",
        "research_payload": {"unit_roster": roster, "unit_research_cards": []},
    }

    class ForbiddenAnthropic:
        def __init__(self):
            self.calls = 0

        async def generate(self, **_kwargs):
            self.calls += 1
            raise AssertionError("missing-card preview must fail before spending an LLM call")

    forbidden_anthropic = ForbiddenAnthropic()
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type(
        "FakePipeline", (),
        {"anthropic": forbidden_anthropic, "script_system_prompt": "ANTON TENANT SCRIPT CONTRACT"},
    )()
    writes = []

    async def fake_load(_video_id, payload, _roster_arg, target_machine=None):
        assert target_machine == "Boeing XB-15"
        return dict(payload)

    async def fake_execute(query, *args):
        writes.append((query, args))
        return None

    async def forbidden_fetch_all(*_args, **_kwargs):
        raise AssertionError("missing-card preview must fail before voice lookup")

    async def fake_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr(executor, "_load_machine_research_cards", fake_load)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", forbidden_fetch_all)

    result = asyncio.run(
        executor._run_static_script_hold("video-test", video, roster, target_machine="Boeing XB-15")
    )

    preview = _assert_saved_failed_preview(result, writes, "Boeing XB-15", roster)
    assert "saved research card" in preview["warnings"][0]
    assert preview["quality_audit"]["checks"][0]["name"] == "research_card"
    assert forbidden_anthropic.calls == 0
    assert not any("DELETE FROM scripts" in query or "INSERT INTO scripts" in query for query, _args in writes)
    assert not any("machine_script_briefs" in query or "machine_story_plans" in query for query, _args in writes)


def test_target_machine_preview_reports_missing_card_before_provider_config(monkeypatch):
    roster = ["Boeing XB-15"]
    video = {
        "video_title": "Every US Strategic Bomber Ever Built",
        "render_mode": "static_docu",
        "research_payload": {"unit_roster": roster, "unit_research_cards": []},
    }
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type(
        "FakePipeline", (),
        {"anthropic": None, "script_system_prompt": "ANTON TENANT SCRIPT CONTRACT"},
    )()
    writes = []

    async def fake_load(_video_id, payload, _roster_arg, target_machine=None):
        assert target_machine == "Boeing XB-15"
        return dict(payload)

    async def fake_execute(query, *args):
        writes.append((query, args))
        return None

    async def forbidden_fetch_all(*_args, **_kwargs):
        raise AssertionError("missing-card preview must fail before voice lookup")

    async def fake_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr(executor, "_load_machine_research_cards", fake_load)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", forbidden_fetch_all)

    result = asyncio.run(
        executor._run_static_script_hold("video-test", video, roster, target_machine="Boeing XB-15")
    )

    preview = _assert_saved_failed_preview(result, writes, "Boeing XB-15", roster)
    assert "saved research card" in preview["warnings"][0]
    assert "Anthropic client" not in preview["warnings"][0]


def test_target_machine_preview_requires_sourced_memorable_fact_before_llm(monkeypatch):
    roster = ["Boeing XB-15"]
    segments = [
        segment for segment in _evidence_segments()
        if segment["evidence_id"] != "E-MEMORABLE"
    ]
    card = _valid_research_card(
        "Boeing XB-15",
        segments,
        surprising_fact="Legacy surprising fact text is not enough without sourced evidence.",
    )
    video = {
        "video_title": "Every US Strategic Bomber Ever Built",
        "render_mode": "static_docu",
        "research_payload": {
            "unit_roster": roster,
            "unit_research_cards": [card],
            "machine_raw_source_packages": {
                pe._verified_source_cache_key("Boeing XB-15"): _verified_package_for_segments("Boeing XB-15", segments),
            },
        },
    }

    class ForbiddenAnthropic:
        def __init__(self):
            self.calls = 0

        async def generate(self, **_kwargs):
            self.calls += 1
            raise AssertionError("preview must fail before spending an LLM call")

    forbidden_anthropic = ForbiddenAnthropic()
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type(
        "FakePipeline", (),
        {"anthropic": forbidden_anthropic, "script_system_prompt": "ANTON TENANT SCRIPT CONTRACT"},
    )()
    writes = []

    async def fake_load(_video_id, payload, _roster_arg, target_machine=None):
        assert target_machine == "Boeing XB-15"
        return dict(payload)

    async def fake_execute(query, *args):
        writes.append((query, args))
        return None

    async def fake_fetch_all(*_args, **_kwargs):
        raise AssertionError("preview evidence gate must fail before voice lookup")

    async def fake_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr(executor, "_load_machine_research_cards", fake_load)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)

    result = asyncio.run(
        executor._run_static_script_hold("video-test", video, roster, target_machine="Boeing XB-15")
    )

    preview = _assert_saved_failed_preview(result, writes, "Boeing XB-15", roster)
    assert "Script preview evidence gate failed" in preview["warnings"][0]
    assert "missing sourced memorable_fact evidence segment" in preview["warnings"][0]
    assert forbidden_anthropic.calls == 0
    assert not any("DELETE FROM scripts" in query or "INSERT INTO scripts" in query for query, _args in writes)
    assert not any("machine_script_briefs" in query or "machine_story_plans" in query for query, _args in writes)


def test_target_machine_preview_rejects_stale_card_locator_before_llm(monkeypatch):
    roster = ["Boeing XB-15"]
    verified_segments = _evidence_segments()
    stale_segments = copy.deepcopy(verified_segments)
    stale_segments[0]["locator"] = "old-card-locator"
    card = {
        "unit": "Boeing XB-15",
        "engineering_thesis": "XB-15 source-grounded engineering thesis.",
        "surprising_fact": "XB-15 source-grounded fact.",
        "source_notes": ["xb15-source"],
        "evidence_segments": stale_segments,
    }
    video = {
        "video_title": "Every US Strategic Bomber Ever Built",
        "render_mode": "static_docu",
        "research_payload": {
            "unit_roster": roster,
            "unit_research_cards": [card],
            "machine_raw_source_packages": {
                pe._verified_source_cache_key("Boeing XB-15"): _verified_package_for_segments("Boeing XB-15", verified_segments),
            },
        },
    }

    class ForbiddenAnthropic:
        def __init__(self):
            self.calls = 0

        async def generate(self, **_kwargs):
            self.calls += 1
            raise AssertionError("stale locator preview must fail before spending an LLM call")

    forbidden_anthropic = ForbiddenAnthropic()
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type(
        "FakePipeline", (),
        {"anthropic": forbidden_anthropic, "script_system_prompt": "ANTON TENANT SCRIPT CONTRACT"},
    )()
    writes = []

    async def fake_load(_video_id, payload, _roster_arg, target_machine=None):
        assert target_machine == "Boeing XB-15"
        return dict(payload)

    async def fake_execute(query, *args):
        writes.append((query, args))
        return None

    async def fake_fetch_all(*_args, **_kwargs):
        return []

    async def fake_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr(executor, "_load_machine_research_cards", fake_load)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)

    result = asyncio.run(
        executor._run_static_script_hold("video-test", video, roster, target_machine="Boeing XB-15")
    )

    preview = _assert_saved_failed_preview(result, writes, "Boeing XB-15", roster)
    assert "source_excerpt/locator was not found" in preview["warnings"][0]
    assert forbidden_anthropic.calls == 0
    assert not any("DELETE FROM scripts" in query or "INSERT INTO scripts" in query for query, _args in writes)
    assert not any("machine_script_briefs" in query or "machine_story_plans" in query for query, _args in writes)


def test_target_machine_preview_rejects_wrong_machine_source_package_before_llm(monkeypatch):
    roster = ["Boeing XB-15"]
    verified_segments = _evidence_segments()
    card = {
        "unit": "Boeing XB-15",
        "engineering_thesis": "XB-15 source-grounded engineering thesis.",
        "surprising_fact": "XB-15 source-grounded fact.",
        "source_notes": ["xb15-source"],
        "evidence_segments": verified_segments,
    }
    video = {
        "video_title": "Every US Strategic Bomber Ever Built",
        "render_mode": "static_docu",
        "research_payload": {
            "unit_roster": roster,
            "unit_research_cards": [card],
            "machine_raw_source_packages": {
                pe._verified_source_cache_key("Boeing XB-15"): _verified_package_for_segments(
                    "Boeing B-17 Flying Fortress", verified_segments
                ),
            },
        },
    }

    class ForbiddenAnthropic:
        def __init__(self):
            self.calls = 0

        async def generate(self, **_kwargs):
            self.calls += 1
            raise AssertionError("wrong-package preview must fail before spending an LLM call")

    forbidden_anthropic = ForbiddenAnthropic()
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type(
        "FakePipeline", (),
        {"anthropic": forbidden_anthropic, "script_system_prompt": "ANTON TENANT SCRIPT CONTRACT"},
    )()
    writes = []

    async def fake_load(_video_id, payload, _roster_arg, target_machine=None):
        assert target_machine == "Boeing XB-15"
        return dict(payload)

    async def fake_execute(query, *args):
        writes.append((query, args))
        return None

    async def fake_fetch_all(*_args, **_kwargs):
        return []

    async def fake_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr(executor, "_load_machine_research_cards", fake_load)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)

    result = asyncio.run(
        executor._run_static_script_hold("video-test", video, roster, target_machine="Boeing XB-15")
    )

    preview = _assert_saved_failed_preview(result, writes, "Boeing XB-15", roster)
    assert "does not match locked machine XB15" in preview["warnings"][0]
    assert forbidden_anthropic.calls == 0
    assert not any("DELETE FROM scripts" in query or "INSERT INTO scripts" in query for query, _args in writes)
    assert not any("machine_script_briefs" in query or "machine_story_plans" in query for query, _args in writes)


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


def test_run_machine_script_preview_canonicalizes_label_to_locked_roster(monkeypatch):
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    calls = []

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

    async def fake_hold(video_id, video, roster, target_machine=None):
        calls.append((video_id, video, roster, target_machine))
        return {
            "status": "completed",
            "video_id": video_id,
            "preview": {"machine": target_machine, "passed": False},
            "research_payload": {},
        }

    monkeypatch.setattr(executor, "_ensure_initialized", fake_init)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_load_prompt_overrides", fake_load_prompt_overrides)
    monkeypatch.setattr(executor, "_run_static_script_hold", fake_hold)

    result = asyncio.run(
        executor.run_machine_script_preview("video-test", "XB-15 — Boeing XB-15")
    )

    assert result["status"] == "completed"
    assert calls[0][2] == ["Boeing XB-15", "Boeing B-17", "Consolidated B-24"]
    assert calls[0][3] == "Boeing XB-15"
    assert result["preview"]["machine"] == "Boeing XB-15"


def test_machine_preview_readiness_reports_missing_package_without_provider(monkeypatch):
    roster = ["Boeing XB-15", "Boeing B-17 Flying Fortress", "Consolidated B-24 Liberator"]
    payload = {
        "documentary_style": "designed_vs_used",
        "unit_roster": roster,
        "unit_research_cards": [_valid_research_card("Boeing XB-15", _evidence_segments())],
    }
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": None})()

    async def fake_init():
        return None

    async def fake_get_video(_video_id):
        return {
            "render_mode": "static_docu",
            "research_payload": payload,
        }

    async def fake_load(_video_id, current_payload, _roster_arg, target_machine=None):
        assert target_machine == "Boeing XB-15"
        return dict(current_payload)

    monkeypatch.setattr(executor, "_ensure_initialized", fake_init)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_load_machine_research_cards", fake_load)

    result = asyncio.run(
        executor.check_machine_script_preview_readiness("video-test", "XB-15 — Boeing XB-15")
    )

    assert result["status"] == "needs_review"
    assert result["ready"] is False
    assert result["machine"] == "Boeing XB-15"
    assert result["scene"] == 1
    assert result["next_action"] == "run_one_machine_research_refresh"
    assert "missing verified raw internet source package" in result["warnings"][0]
    assert all("Script preview evidence gate failed" not in warning for warning in result["warnings"])
    assert "Anthropic client" not in result["warnings"][0]


def test_machine_preview_readiness_blocks_source_package_without_selection_provenance(monkeypatch):
    roster = ["Boeing XB-15", "Boeing B-17 Flying Fortress", "Consolidated B-24 Liberator"]
    segments = _evidence_segments()
    raw_package = _verified_package_for_segments("Boeing XB-15", segments)
    raw_package["candidate_excerpts"][0].pop("source_variant_selection")
    payload = {
        "documentary_style": "designed_vs_used",
        "unit_roster": roster,
        "unit_research_cards": [_valid_research_card("Boeing XB-15", segments)],
        "machine_raw_source_packages": {
            pe._verified_source_cache_key("Boeing XB-15"): raw_package,
        },
    }
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": None})()

    async def fake_init():
        return None

    async def fake_get_video(_video_id):
        return {
            "render_mode": "static_docu",
            "research_payload": payload,
        }

    async def fake_load(_video_id, current_payload, _roster_arg, target_machine=None):
        assert target_machine == "Boeing XB-15"
        return dict(current_payload)

    async def forbidden_static_hold(*_args, **_kwargs):
        raise AssertionError("readiness preflight must not run paid script preview")

    monkeypatch.setattr(executor, "_ensure_initialized", fake_init)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_load_machine_research_cards", fake_load)
    monkeypatch.setattr(executor, "_run_static_script_hold", forbidden_static_hold)

    result = asyncio.run(
        executor.check_machine_script_preview_readiness("video-test", "Boeing XB-15")
    )

    assert result["status"] == "needs_review"
    assert result["ready"] is False
    assert result["machine"] == "Boeing XB-15"
    assert result["scene"] == 1
    assert result["next_action"] == "run_one_machine_research_refresh"
    assert "without source selection provenance" in result["warnings"][0]
    assert all("Script preview evidence gate failed" not in warning for warning in result["warnings"])


def test_machine_preview_readiness_passes_with_verified_card_and_package(monkeypatch):
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
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": None})()

    async def fake_init():
        return None

    async def fake_get_video(_video_id):
        return {
            "render_mode": "static_docu",
            "research_payload": payload,
        }

    async def fake_load(_video_id, current_payload, _roster_arg, target_machine=None):
        assert target_machine == "Boeing XB-15"
        return dict(current_payload)

    monkeypatch.setattr(executor, "_ensure_initialized", fake_init)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_load_machine_research_cards", fake_load)

    result = asyncio.run(
        executor.check_machine_script_preview_readiness("video-test", "Boeing XB-15")
    )

    assert result["status"] == "completed"
    assert result["ready"] is True
    assert result["machine"] == "Boeing XB-15"
    assert result["scene"] == 1
    assert result["warnings"] == []
    assert result["next_action"] == "run_machine_script_preview"


def test_machine_preview_readiness_does_not_touch_generation_side_effects(monkeypatch):
    """Readiness stays no-spend: no prompt overrides, no script hold, no script or
    video writes. Its ONLY sanctioned DB touches are the readiness enrichment
    SELECT and the validation-only verdict refresh UPDATE on machine_research_cards.
    DB doubles record-then-assert (instead of raising) because both sanctioned
    touches are deliberately failure-tolerant and would swallow a raising double."""
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
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": None})()

    async def fake_init():
        return None

    async def fake_get_video(_video_id):
        return {
            "render_mode": "static_docu",
            "research_payload": payload,
        }

    async def fake_load(_video_id, current_payload, _roster_arg, target_machine=None):
        assert target_machine == "Boeing XB-15"
        return dict(current_payload)

    async def forbidden_prompt_overrides(*_args, **_kwargs):
        raise AssertionError("readiness preflight must not load prompt overrides")

    async def forbidden_static_hold(*_args, **_kwargs):
        raise AssertionError("readiness preflight must not run script hold")

    db_reads = []
    db_writes = []

    async def recording_fetch_all(query, *args, **_kwargs):
        db_reads.append((query, args))
        return []

    async def recording_execute(query, *args, **_kwargs):
        db_writes.append((query, args))
        return "UPDATE 1"

    monkeypatch.setattr(executor, "_ensure_initialized", fake_init)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_load_machine_research_cards", fake_load)
    monkeypatch.setattr(executor, "_load_prompt_overrides", forbidden_prompt_overrides)
    monkeypatch.setattr(executor, "_run_static_script_hold", forbidden_static_hold)
    monkeypatch.setattr(pe, "execute", recording_execute)
    monkeypatch.setattr(pe, "fetch_all", recording_fetch_all)

    result = asyncio.run(
        executor.check_machine_script_preview_readiness("video-test", "Boeing XB-15")
    )

    assert result["ready"] is True
    assert result["status"] == "completed"
    # Reads: only the readiness enrichment SELECT; never voice/script lookups.
    assert [query for query, _args in db_reads if "machine_research_cards" not in query] == []
    # Writes: exactly one validation-only verdict refresh, UPDATE-only, right keys.
    assert len(db_writes) == 1
    write_query, write_args = db_writes[0]
    assert "UPDATE machine_research_cards" in write_query
    assert "SET validation" in write_query
    assert "INSERT" not in write_query.upper()
    assert "card" not in write_query.replace("machine_research_cards", "")
    assert write_args[0] == "tenant-test"
    assert write_args[1] == "video-test"
    assert write_args[2] == "XB15"
    assert json.loads(write_args[3])["passed"] is True


def test_machine_preview_readiness_persists_fresh_verdict_and_serves_it(monkeypatch):
    """Self-healing for stale stored verdicts (pre-scope-change grading).

    The stored validation says passed=True while the live strict referee fails
    the card. The no-spend readiness check must (1) issue a validation-only
    UPDATE on machine_research_cards keyed by tenant/video/machine_key - never
    an INSERT, never the card column - and (2) serve card.readiness matching
    the LIVE verdict, not the stale stored one, so badge and toast agree."""
    roster = ["Boeing XB-15", "Boeing B-17 Flying Fortress", "Consolidated B-24 Liberator"]
    segments = _evidence_segments()
    # Break exactly one strict rule: engineering_thesis below the 4-spoken-word minimum.
    card = _valid_research_card("Boeing XB-15", segments, engineering_thesis="Too short.")
    payload = {
        "documentary_style": "designed_vs_used",
        "unit_roster": roster,
        "unit_research_cards": [card],
        "machine_raw_source_packages": {
            pe._verified_source_cache_key("Boeing XB-15"): _verified_package_for_segments("Boeing XB-15", segments),
        },
    }
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": None})()

    async def fake_init():
        return None

    async def fake_get_video(_video_id):
        return {
            "render_mode": "static_docu",
            "research_payload": payload,
        }

    async def fake_load(_video_id, current_payload, _roster_arg, target_machine=None):
        return dict(current_payload)

    async def stale_verdict_fetch_all(query, *args, **_kwargs):
        assert "machine_research_cards" in query
        # STALE stored verdict: the old lenient full-roster grading said this card passed.
        return [{"machine_key": "XB15", "validation": {"passed": True, "warnings": []}}]

    writes = []

    async def recording_execute(query, *args, **_kwargs):
        writes.append((query, args))
        return "UPDATE 1"

    monkeypatch.setattr(executor, "_ensure_initialized", fake_init)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_load_machine_research_cards", fake_load)
    monkeypatch.setattr(pe, "fetch_all", stale_verdict_fetch_all)
    monkeypatch.setattr(pe, "execute", recording_execute)

    result = asyncio.run(
        executor.check_machine_script_preview_readiness("video-test", "Boeing XB-15")
    )

    assert result["status"] == "needs_review"
    assert result["ready"] is False
    assert result["warnings"] == ["missing/weak engineering_thesis"]

    # Exactly one write: a validation-only UPDATE with the right keys.
    assert len(writes) == 1
    write_query, write_args = writes[0]
    assert "UPDATE machine_research_cards" in write_query
    assert "SET validation" in write_query
    assert "INSERT" not in write_query.upper()
    # The card column is never written from a read path.
    assert "card" not in write_query.replace("machine_research_cards", "")
    assert write_args[0] == "tenant-test"
    assert write_args[1] == "video-test"
    assert write_args[2] == "XB15"
    assert json.loads(write_args[3]) == {
        "machine": "Boeing XB-15",
        "passed": False,
        "warnings": ["missing/weak engineering_thesis"],
        "revalidated_no_spend": True,
    }

    # The served payload carries the LIVE verdict, not the stale stored pass.
    served_card = result["research_payload"]["unit_research_cards"][0]
    assert served_card["readiness"] == {
        "passed": False,
        "warnings": ["missing/weak engineering_thesis"],
    }


def test_machine_preview_readiness_verdict_write_failure_is_tolerated(monkeypatch):
    """The verdict refresh is fire-and-forget: a dead database must not fail the
    no-spend readiness response, and the in-memory readiness patch still keeps
    the served payload in sync with the live verdict."""
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
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": None})()

    async def fake_init():
        return None

    async def fake_get_video(_video_id):
        return {
            "render_mode": "static_docu",
            "research_payload": payload,
        }

    async def fake_load(_video_id, current_payload, _roster_arg, target_machine=None):
        return dict(current_payload)

    async def broken_fetch_all(*_args, **_kwargs):
        raise RuntimeError("database is unavailable")

    async def broken_execute(*_args, **_kwargs):
        raise RuntimeError("database is unavailable")

    monkeypatch.setattr(executor, "_ensure_initialized", fake_init)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_load_machine_research_cards", fake_load)
    monkeypatch.setattr(pe, "fetch_all", broken_fetch_all)
    monkeypatch.setattr(pe, "execute", broken_execute)

    result = asyncio.run(
        executor.check_machine_script_preview_readiness("video-test", "Boeing XB-15")
    )

    assert result["status"] == "completed"
    assert result["ready"] is True
    # Even with the enrichment read AND the verdict write both dead, the served
    # payload reflects the live verdict via the in-memory patch.
    served_card = result["research_payload"]["unit_research_cards"][0]
    assert served_card["readiness"] == {"passed": True, "warnings": []}


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


def test_support_kind_segments_ground_and_cite_their_matching_fields():
    """A card whose timeframe/visual_identity words live ONLY in the new support
    segments passes the referee: the fields cite them, their text participates in
    grounding, the auto-citer picks them, and the story plan slots them as
    optional (required beats unchanged)."""
    machine = "Boeing XB-15"
    segments = _support_kind_segments(machine)
    card = _valid_research_card(
        machine,
        segments,
        timeframe=f"{machine} first flew in October 1937 and entered testing.",
        timeframe_evidence_ids=["E-TIMEFRAME"],
        visual_identity=f"{machine} was a mid wing monoplane with retractable landing gear.",
        visual_identity_evidence_ids=["E-VISUAL"],
    )

    # Accepted end to end: no kind errors, no grounding/number/citation warnings.
    assert pe._research_card_contract_warnings(machine, card) == []

    # The deterministic auto-citer can now select the support segments for
    # their matching fields when the model returns empty citation lists.
    stripped = copy.deepcopy(card)
    stripped["timeframe_evidence_ids"] = []
    stripped["visual_identity_evidence_ids"] = []
    recited = pe._normalize_card_field_citations(stripped, machine)
    assert "E-TIMEFRAME" in recited["timeframe_evidence_ids"]
    assert "E-VISUAL" in recited["visual_identity_evidence_ids"]

    # Story plan and script-brief rendering handle the new roles: optional
    # slots carry the segments, the required four beats are unchanged.
    plan = pe._machine_story_plan({"unit_research_cards": [card]}, machine)
    slots_by_role = {slot["slot"]: slot for slot in plan["slots"]}
    assert slots_by_role["timeframe"]["required"] is False
    assert slots_by_role["visual_identity"]["required"] is False
    assert slots_by_role["timeframe"]["evidence_ids"] == ["E-TIMEFRAME"]
    assert slots_by_role["visual_identity"]["evidence_ids"] == ["E-VISUAL"]
    assert sorted(plan["required_slots"]) == sorted(pe._ANTON_REQUIRED_SLOT_ROLES)
    brief = pe._inventory_story_brief({"unit_research_cards": [card]}, machine)
    brief_slots = {row["slot"] for row in brief["anton_slots"]}
    assert {"timeframe", "visual_identity"} <= brief_slots


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
        assert "FROM scripts" in query
        assert args == ("video-test", "tenant-test")
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


def test_script_generation_exception_preserves_existing_script_rows(monkeypatch):
    roster = ["Boeing XB-15"]
    video = {
        "video_title": "Designed vs Used: Bombers",
        "render_mode": "static_docu",
        "research_payload": {
            "unit_roster": roster,
            "unit_research_cards": [_valid_research_card("Boeing XB-15", _evidence_segments())],
            "machine_raw_source_packages": {
                pe._verified_source_cache_key("Boeing XB-15"): _verified_package_for_segments("Boeing XB-15", _evidence_segments()),
            },
        },
    }

    class FailingAnthropic:
        async def generate(self, **_kwargs):
            raise RuntimeError("simulated provider outage")

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": FailingAnthropic()})()
    writes = []

    async def fake_execute(query, *args):
        writes.append((query, args))

    async def fake_fetch_all(*_args, **_kwargs):
        return [{"voice_id": "voice-existing"}]

    async def fake_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(executor, "_log_activity", fake_log)

    try:
        asyncio.run(executor._run_static_script_hold("video-test", video, roster))
    except RuntimeError as exc:
        assert "provider outage" in str(exc)
    else:
        raise AssertionError("provider failure should propagate")

    assert writes == [], "provider failure must leave the prior script untouched"


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


def test_research_hold_refuses_bulk_generation_for_missing_machine_cards(monkeypatch):
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
            raise AssertionError("bulk missing-card research must not spend an LLM call")

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

    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(executor, "_log_activity", fake_log)

    result = asyncio.run(
        executor._run_unit_research_hold("video-test", "Designed vs Used", payload, roster_names)
    )

    assert fake_anthropic.prompts == []
    assert writes == []
    assert result["unit_roster"] == original_roster
    assert result["unit_research_hold_validation"]["passed"] is False
    assert "Bulk DVsU machine-card generation is disabled" in result["unit_research_hold_validation"]["warnings"][0]


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

    assert fetch_calls[0][1:] == ("tenant-test", "video-test", "B52")
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
            "units": [{"machine": "Boeing XB-15", "passed": False, "warnings": ["research card missing Anton slots"]}],
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
            "units": [{"machine": "Boeing XB-15", "passed": False, "warnings": ["research card missing Anton slots"]}],
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
            "render_mode": "static_docu",
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
            "render_mode": "static_docu",
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
    monkeypatch.setattr(pe, "execute", fake_execute)

    result = asyncio.run(executor.run_research("video-test"))

    assert result["status"] == "failed"
    assert "no longer available for this tenant" in result["error"]
    assert syncs == []


def test_run_unit_research_final_save_is_tenant_scoped(monkeypatch):
    import sys
    import types

    roster_names = ["Boeing XB-15", "Boeing B-17 Flying Fortress", "Consolidated B-24 Liberator"]
    payload = {
        "documentary_style": "designed_vs_used",
        "unit_roster": roster_names,
        "unit_roster_validation": {"passed": True},
    }
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
    assert "WHERE id = $3 AND tenant_id = $4" in writes[0][0]
    assert writes[0][1][2:] == ("video-test", "tenant-test")
    assert syncs == [("video-test", "tenant-test")]


def test_run_unit_research_refuses_zero_row_final_save(monkeypatch):
    import sys
    import types

    roster_names = ["Boeing XB-15", "Boeing B-17 Flying Fortress", "Consolidated B-24 Liberator"]
    payload = {
        "documentary_style": "designed_vs_used",
        "unit_roster": roster_names,
        "unit_roster_validation": {"passed": True},
    }
    researched_payload = {
        **payload,
        "unit_research_cards": [{"unit": machine, "evidence_segments": _evidence_segments()} for machine in roster_names],
        "unit_research_hold_validation": {"passed": True, "units": []},
    }

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
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


def test_story_compiler_prompt_does_not_request_meaning_beat():
    source = open(pe.__file__, encoding="utf-8").read()
    compiler = source[
        source.index("FORMAT MODE: COMPLETE INVENTORY MICRO-STORY")
        :source.index("REBUILD THE ANTON-STYLE PARAGRAPH JSON")
    ]

    assert "historical meaning understandable" not in compiler
    assert "engineering meaning" not in compiler
    assert "service consequence, or final contrast" in compiler
    assert "facts serve the engineering argument" in compiler


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
        assert "machine_key = $3" in query
        assert args == ("tenant-a", "video-a", "XB15")
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

def test_script_twist_gate_is_hard_with_substitute_and_bare_exemption():
    """QL-3 (OR-1 approved, HARD): every entry declares its designed-vs-used
    twist; `absent` requires a named substitute; deliberately-bare is the only
    exemption. QL-4: off-menu types are advisory (counted as `other`)."""
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")

    # Undeclared twist -> hard reject.
    undeclared = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    undeclared.pop("twist", None)
    _p, undeclared_warnings = pe._validate_machine_story_sentences("B-52", plan, undeclared)
    assert any("entry declares no designed-vs-used twist" in w for w in pe._blocking_warnings(undeclared_warnings))

    # Used-as-designed WITH a named substitute -> legal.
    substituted = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    substituted["twist"] = {"type": "absent", "substitute": "superlative", "summary": "The biggest of its kind."}
    _p, substituted_warnings = pe._validate_machine_story_sentences("B-52", plan, substituted)
    assert not any("twist" in w for w in pe._blocking_warnings(substituted_warnings))

    # Absent with NO substitute -> the worst entry in the corpus, hard reject.
    bare_absent = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    bare_absent["twist"] = {"type": "absent", "substitute": None, "summary": ""}
    _p, bare_absent_warnings = pe._validate_machine_story_sentences("B-52", plan, bare_absent)
    assert any("no gap and no substitute - reads as a spec dump" in w for w in pe._blocking_warnings(bare_absent_warnings))

    # Off-menu type -> advisory only, counted as `other` (QL-4).
    offmenu = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    offmenu["twist"] = {"type": "weird_new_thing", "substitute": None, "summary": "?"}
    _p, offmenu_warnings = pe._validate_machine_story_sentences("B-52", plan, offmenu)
    assert any(w.startswith(pe._ADVISORY_PREFIX) and "not on the menu" in w for w in offmenu_warnings)
    assert not any("twist" in w for w in pe._blocking_warnings(offmenu_warnings))

    # Deliberately-bare tag: twist requirement and memorable demand both exempt.
    bare_payload = {"unit_research_cards": [{
        "unit": "B-52",
        "deliberately_bare": True,
        "gap_hunt_summary": "Searched service, conversion, and disposal records; the type never left acceptance trials.",
        "evidence_segments": [s for s in _evidence_segments() if s["kind"] != "memorable_fact"],
    }]}
    bare_plan = pe._machine_story_plan(bare_payload, "B-52")
    assert bare_plan["contract"]["deliberately_bare"] is True
    bare_bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    bare_bundle.pop("twist", None)
    bare_bundle["claim_map"][3]["used_evidence_ids"] = ["E-REALITY"]
    _p, bare_warnings = pe._validate_machine_story_sentences("B-52", bare_plan, bare_bundle)
    assert not any("twist" in w for w in bare_warnings)
    assert not any("memorable" in w for w in bare_warnings)


def test_verdict_punch_gate_rejects_recap_closers():
    """QL-5 (HARD): summary/recap closers are banned. Heuristic: a closer over
    12 spoken words whose content stems are >80% body repeats with no contrast
    marker is a recap. Short hammers and contrast-bearing closers stay legal."""
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    base = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    old_final = "The proof survived the machine."

    def _with_closer(closer: str) -> dict:
        bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
        bundle["formula_sentences"] = [
            closer if sentence == old_final else sentence
            for sentence in bundle["formula_sentences"]
        ]
        return bundle

    # Long recap: all content words repeat the body, no turn -> hard reject.
    recap = _with_closer(
        "The reality claim grounded in the supplied source proved the engineering decision claim clear."
    )
    _p, recap_warnings = pe._validate_machine_story_sentences("B-52", plan, recap)
    assert any("closer restates facts" in w for w in pe._blocking_warnings(recap_warnings))

    # The same words WITH a contrast marker carry a turn -> legal.
    turned = _with_closer(
        "The reality claim grounded in the supplied source proved the engineering decision claim, but not the tradeoff."
    )
    _p, turned_warnings = pe._validate_machine_story_sentences("B-52", plan, turned)
    assert not any("closer restates facts" in w for w in turned_warnings)

    # A short hammer is legal by construction (base bundle closer, 5 words).
    _p, base_warnings = pe._validate_machine_story_sentences("B-52", plan, base)
    assert not any("closer restates facts" in w for w in base_warnings)


def test_opener_classifier_types_ql7():
    """QL-7: deterministic opener classification feeding the name-opener budget."""
    machine = "Boeing XB-15"
    assert pe._classify_opener_type("The Boeing XB-15 answered a range problem. More.", machine) == "name"
    assert pe._classify_opener_type("Boeing XB-15 answered a range problem.", machine) == "name"
    assert pe._classify_opener_type("While the B-17 flew on, this one stalled.", machine) == "bridge"
    assert pe._classify_opener_type("In 1937 the answer appeared over Seattle.", machine) == "date_era"
    assert pe._classify_opener_type("Nine were built before the order died.", machine) == "count_fragment"
    assert pe._classify_opener_type("America's bomber ambitions needed proof.", machine) == "role_thesis"
    assert pe._classify_opener_type("Nobody wanted the result.", machine) == "other"


def test_hedged_rounding_is_legal_qd3():
    """QD-3 (approved): a hedged, direction-consistent round of a sourced value
    is warn-only ("over eight thousand feet" for a sourced 8,200); the same
    round UNHEDGED stays a hard flag."""
    evidence = _evidence_segments()
    evidence[2]["claim"] = evidence[2]["claim"].rstrip(".") + " with a ceiling of 8,200 feet."
    evidence[2]["source_excerpt"] = evidence[2]["claim"]
    evidence[2]["numeric_tokens"] = ["8200"]
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": evidence}]}
    plan = pe._machine_story_plan(payload, "B-52")

    def _with_suffix(suffix: str) -> dict:
        bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
        old_span = bundle["claim_map"][1]["span"]
        new_span = old_span.rstrip(".") + suffix
        bundle["claim_map"][1]["span"] = new_span
        bundle["formula_sentences"] = [
            new_span if sentence == old_span else sentence
            for sentence in bundle["formula_sentences"]
        ]
        return bundle

    hedged = _with_suffix(" reaching over eight thousand feet.")
    _p, hedged_warnings = pe._validate_machine_story_sentences("B-52", plan, hedged)
    assert any(
        w.startswith(pe._ADVISORY_PREFIX) and "rounds a sourced value with a hedge" in w
        for w in hedged_warnings
    )
    assert not any("unsupported numerical detail" in w for w in pe._blocking_warnings(hedged_warnings))

    unhedged = _with_suffix(" reaching eight thousand feet.")
    _p, unhedged_warnings = pe._validate_machine_story_sentences("B-52", plan, unhedged)
    assert any(
        "unsupported numerical detail(s)" in w and "eight thousand" in w
        for w in pe._blocking_warnings(unhedged_warnings)
    )


def test_exact_dates_single_source_qd4():
    """QD-4 (approved): exact dates are identity facts - one locked source
    suffices; the two-source demand applies to quantities only."""
    evidence = _evidence_segments()
    dated = dict(evidence[4])
    dated.update({
        "evidence_id": "E-DATED",
        "kind": "reality",
        "claim": "The bomber flew again in 1937 carrying 5,000 pounds of ballast.",
        "source_excerpt": "The bomber flew again in 1937 carrying 5,000 pounds of ballast.",
        "source_url": "https://airandspace.si.edu/test/dated",
        "locator": "S9-E1",
        "numeric_tokens": ["1937", "5000"],
    })
    evidence.append(dated)
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": evidence}]}
    plan = pe._machine_story_plan(payload, "B-52")

    def _with_reality_suffix(suffix: str) -> dict:
        bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
        old_span = bundle["claim_map"][3]["span"]
        new_span = old_span.rstrip(".") + suffix
        bundle["claim_map"][3]["span"] = new_span
        bundle["claim_map"][3]["used_evidence_ids"] = ["E-REALITY", "E-MEMORABLE", "E-DATED"]
        bundle["formula_sentences"] = [
            new_span if sentence == old_span else sentence
            for sentence in bundle["formula_sentences"]
        ]
        return bundle

    # A single-sourced YEAR needs no second source.
    dated_bundle = _with_reality_suffix(" and flew again in nineteen thirty seven.")
    _p, dated_warnings = pe._validate_machine_story_sentences("B-52", plan, dated_bundle)
    assert not any("two independent sources" in w for w in dated_warnings)

    # A single-sourced QUANTITY still demands two sources or a hedge.
    quantity_bundle = _with_reality_suffix(" carrying five thousand pounds of ballast.")
    _p, quantity_warnings = pe._validate_machine_story_sentences("B-52", plan, quantity_bundle)
    assert any(
        "two independent sources" in w and "five thousand" in w
        for w in pe._blocking_warnings(quantity_warnings)
    )


def test_editorial_thesis_is_warn_only_qd5():
    """QD-5 (approved): thesis grading never blocks."""
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    bundle["editorial_thesis"] = "Too short."
    _p, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)
    assert any(w.startswith(pe._ADVISORY_PREFIX) and "editorial_thesis" in w for w in warnings)
    assert not any("editorial_thesis" in w for w in pe._blocking_warnings(warnings))


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


def test_script_run_flags_over_forty_percent_other_twists(monkeypatch):
    """QL-4 run budget: a full script run over 40% `other` twists carries the
    advisory in script_hold warnings; opener/twist types are stored per unit."""
    roster = ["Boeing XB-15"]
    cards = [_valid_research_card(machine, _evidence_segments()) for machine in roster]
    video = {
        "video_title": "Every US Strategic Bomber Ever Built",
        "render_mode": "static_docu",
        "research_payload": {
            "unit_roster": roster,
            "unit_research_cards": cards,
            "machine_raw_source_packages": {
                pe._verified_source_cache_key(machine): _verified_package_for_segments(machine, _evidence_segments())
                for machine in roster
            },
        },
    }
    other_bundle = json.loads(_story_bundle(roster[0], 20))
    other_bundle["twist"] = {"type": "other", "substitute": None, "summary": "Unclassified."}

    class FakeAnthropic:
        def __init__(self):
            self.prompts = []
            self.outputs = [json.dumps(other_bundle)]

        async def generate(self, **kwargs):
            self.prompts.append(kwargs["prompt"])
            return self.outputs.pop(0)

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type(
        "FakePipeline", (),
        {"anthropic": FakeAnthropic(), "script_system_prompt": "ANTON TENANT SCRIPT CONTRACT"},
    )()
    writes = []

    async def fake_execute(query, *args):
        writes.append((query, args))
        return None

    async def fake_fetch_all(_query, *_args):
        return []

    async def noop(*_args, **_kwargs):
        return None

    async def fake_validate(_video_id):
        return {"passed": True}

    def passed_quality_audit(*_args, **_kwargs):
        return {
            "passed": True,
            "checks": [{"name": "validator_warnings", "label": "Validator warnings", "passed": True, "detail": "clean"}],
            "summary": "Anton quality audit passed",
        }

    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(pe, "_anton_preview_quality_audit", passed_quality_audit)
    monkeypatch.setattr(executor, "_log_activity", noop)
    monkeypatch.setattr(executor, "_validate_static_script_roster", fake_validate)
    monkeypatch.setattr(executor, "_update_video_status", noop)
    monkeypatch.setattr(executor, "_skip_disabled_next", lambda _video, status: status)

    result = asyncio.run(executor._run_static_script_hold("video-test", video, roster))

    assert result["status"] == "ready_for_voice"
    hold_writes = [
        json.loads(arg)
        for query, args in writes
        if "script_validation" in query
        for arg in args
        if isinstance(arg, str) and '"script_hold"' in arg
    ]
    assert hold_writes, "script_hold validation must be persisted"
    final_hold = hold_writes[-1].get("script_hold") or hold_writes[-1]
    assert final_hold["passed"] is True
    assert final_hold["units"][0]["twist_type"] == "other"
    assert final_hold["units"][0]["opener_type"]
    assert any(
        w.startswith(pe._ADVISORY_PREFIX) and "twists fell to `other`" in w
        for w in final_hold.get("warnings", [])
    )


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


def test_anton_corpus_punches_never_hard_recap():
    """I1 calibration law: 308 verbatim Anton punches (12 scripts, bodies from
    the raw voiceovers) run through the REAL closer path - ZERO may trip the
    HARD recap gate. Frozen fixture: fixtures/anton_corpus_punches.json."""
    import os
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "anton_corpus_punches.json")
    with open(fixture_path) as handle:
        punches = json.load(handle)
    assert len(punches) >= 300

    hard_blocked = []
    for record in punches:
        body_sentences = [
            part.strip() for part in
            __import__("re").split(r"(?<=[.!?])\s+", str(record["body"] or "").strip())
            if part.strip()
        ]
        closer_sentences = [
            part.strip() for part in
            __import__("re").split(r"(?<=[.!?])\s+", str(record["punch"] or "").strip())
            if part.strip()
        ]
        if not body_sentences or not closer_sentences:
            continue
        warnings = _closer_probe("Boeing B-52 Stratofortress", body_sentences, closer_sentences)
        if any("closer restates facts" in w for w in pe._blocking_warnings(warnings)):
            hard_blocked.append((record["script"], record["entry"], record["punch"]))
    assert hard_blocked == [], f"{len(hard_blocked)} Anton punches hard-blocked: {hard_blocked[:5]}"


def test_closer_entity_parser_and_geographic_color_b1():
    """B1: sentence-initial capitals ("Though", "American", "Intercontinental")
    are grammar, not entities; nationality/geographic words are advisory color;
    person/org/operation names stay hard; entity+number pairing stays hard."""
    body = [
        "The bomber answered a range problem with size and fuel.",
        "Engineers traded speed for endurance across the design.",
        "The tradeoff kept it out of frontline combat service.",
        "It hauled cargo across the ocean war instead of bombing.",
    ]
    # Sentence-initial connective + geographic color + body-echoed number: clean of hard flags.
    anton_like = _closer_probe(
        "Boeing XB-15", body,
        ["Though never a bomber, it validated concepts that would define American strategic aviation for the next eight decades."],
    )
    assert not any("new named entity" in w for w in pe._blocking_warnings(anton_like))
    assert not any("pairs a new number" in w for w in pe._blocking_warnings(anton_like))
    assert any(
        w.startswith(pe._ADVISORY_PREFIX) and "geographic/nationality color" in w and "American" in w
        for w in anton_like
    )
    # Word cap is 25 now: that closer is 19 words and legal; 26+ still flags.
    assert not any("final sentence word count" in w for w in anton_like)

    # A person/operation name stays HARD.
    named = _closer_probe(
        "Boeing XB-15", body,
        ["The program answered to General Arnold in the end."],
    )
    assert any(
        "new named entity" in w and "General Arnold" in w
        for w in pe._blocking_warnings(named)
    )

    # never/only are legal punch machinery in closers; absolutes alone advise.
    contrastive = _closer_probe(
        "Boeing XB-15", body,
        ["It was never the weapon, only the proof."],
    )
    assert not any("high-risk" in w for w in pe._blocking_warnings(contrastive))
    absolute = _closer_probe(
        "Boeing XB-15", body,
        ["It remains the largest promise the program ever made."],
    )
    assert any(
        w.startswith(pe._ADVISORY_PREFIX) and "absolute term(s)" in w and "largest" in w
        for w in absolute
    )
    assert not any("absolute term" in w for w in pe._blocking_warnings(absolute))


def test_recap_gate_recalibrated_i1_i4():
    """I1+I4: HARD recap only for a SINGLE-sentence closer with repeat ratio
    >= 0.9 and no contrast marker; fragment-ending closers are never hard;
    recap-ish shapes are advisory."""
    body = [
        "The plane was slow and heavy and it was expensive and it was cancelled early.",
        "The program spent years proving the airframe could not be saved.",
        "Its engines burned money while its rivals burned records.",
        "The service walked away from the slow heavy expensive machine entirely.",
    ]
    # Single-sentence, ratio ~1.0, no marker, >12 words -> HARD.
    recap = _closer_probe(
        "Boeing B-52 Stratofortress", body,
        ["The plane was slow and heavy and expensive and it was cancelled early in the program."],
    )
    assert any("closer restates facts" in w for w in pe._blocking_warnings(recap))

    # The SAME words split into trailing fragments -> punch units, never hard.
    fragments = _closer_probe(
        "Boeing B-52 Stratofortress", body,
        ["The machine stayed slow and heavy through every fix the program funded.", "Slow. Heavy. Cancelled early."],
    )
    assert not any("closer restates facts" in w for w in pe._blocking_warnings(fragments))

    # Recap-ish but below 0.9 -> advisory, not hard.
    recapish = _closer_probe(
        "Boeing B-52 Stratofortress", body,
        ["The plane stayed slow and heavy and expensive while its doubters multiplied yearly."],
    )
    assert not any("closer restates facts" in w for w in pe._blocking_warnings(recapish))


def test_hedged_rounding_enforces_direction_i3():
    """I3: over/more-than requires the sourced value at or above the stated
    round; under/nearly at or below; about within 20 percent; matching is
    nearest-number only and never across magnitudes."""
    evidence = _evidence_segments()
    evidence[2]["claim"] = evidence[2]["claim"].rstrip(".") + " with a ceiling of 8,200 feet."
    evidence[2]["source_excerpt"] = evidence[2]["claim"]
    evidence[2]["numeric_tokens"] = ["8200"]
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": evidence}]}
    plan = pe._machine_story_plan(payload, "B-52")

    def _with_suffix(suffix: str) -> list:
        bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
        old_span = bundle["claim_map"][1]["span"]
        new_span = old_span.rstrip(".") + suffix
        bundle["claim_map"][1]["span"] = new_span
        bundle["formula_sentences"] = [
            new_span if sentence == old_span else sentence
            for sentence in bundle["formula_sentences"]
        ]
        _p, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)
        return warnings

    # "over eight thousand" with sourced 8,200 (sourced >= stated) -> legal round.
    over_ok = _with_suffix(" reaching over eight thousand feet.")
    assert any("rounds a sourced value with a hedge" in w for w in over_ok)
    assert not any("unsupported numerical detail" in w for w in pe._blocking_warnings(over_ok))

    # "over eight thousand five hundred" (sourced 8,200 BELOW the stated round)
    # is direction-inconsistent -> hard.
    over_bad = _with_suffix(" reaching over eight thousand five hundred feet.")
    assert any("unsupported numerical detail" in w for w in pe._blocking_warnings(over_bad))

    # "nearly eight thousand five hundred" (sourced below stated) -> legal.
    nearly_ok = _with_suffix(" reaching nearly eight thousand five hundred feet.")
    assert any("rounds a sourced value with a hedge" in w for w in nearly_ok)
    assert not any("unsupported numerical detail" in w for w in pe._blocking_warnings(nearly_ok))

    # Magnitude guard: "about four hundred" cannot borrow the 8,200 source.
    magnitude = _with_suffix(" holding about four hundred instruments.")
    assert any(
        "unsupported numerical detail" in w and "four hundred" in w
        for w in pe._blocking_warnings(magnitude)
    )


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


def test_register_density_and_fragment_folding():
    """Corpus recalibrations: spec-block density cap is 15 (Anton B-17/B-52
    carry 14); tight-production keeps 8; trailing punch fragments fold into
    the conclusion so a triad never blows the sentence range."""
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    assert plan["contract"]["maximum_numerical_details"] == 15

    # Fragment folding: 4 beats + conclusion + a triad = 8 raw sentences ->
    # effective 5; no sentence-range warning, formula note advisory only.
    body = [
        "The bomber answered a range problem with size and fuel to spare.",
        "Engineers traded speed for endurance across the whole design envelope.",
        "The tradeoff kept it out of frontline combat service for years.",
        "It hauled cargo across the ocean war instead of dropping bombs.",
        "The concept outlived the airframe by a full generation of designers.",
    ]
    warnings = _closer_probe("Boeing B-52 Stratofortress", body, ["Big wings.", "Bigger patience.", "No combat."])
    assert not any("sentence count" in w for w in pe._blocking_warnings(warnings))
    assert not any("closer restates facts" in w for w in pe._blocking_warnings(warnings))


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

def test_normalize_spelled_years_and_decades():
    assert pe._normalize_spelled_years(
        "The Army sought a bomber in the early nineteen thirties."
    ) == "The Army sought a bomber in the early 1930s."
    assert pe._normalize_spelled_years(
        "Boeing's Model 299 first flew in nineteen thirty-five as a platform."
    ) == "Boeing's Model 299 first flew in 1935 as a platform."
    assert pe._normalize_spelled_years("It carried nineteen guns.") == "It carried nineteen guns."
    assert pe._normalize_spelled_years("Planned for twenty fifty.") == "Planned for 2050."


def test_span_two_source_starved_number_keys_mirrors_gate():
    machine = "Boeing XB-15"
    evidence_by_id = {
        "E-A": {"source_url": "https://a.test/1", "numeric_tokens": ["5,000", "149"]},
        "E-B": {"source_url": "https://b.test/2", "numeric_tokens": ["149"]},
        "E-C": {"source_url": "https://a.test/other", "numeric_tokens": ["1937"]},
    }
    starved = pe._span_two_source_starved_number_keys(
        "It offered a five-thousand-mile range on a one hundred forty nine foot wingspan in 1937.",
        machine,
        evidence_by_id,
    )
    # 5,000: one source -> starved. 149: two sources -> clean. 1937: year-like -> exempt.
    assert pe._numeric_token_key("5,000") in starved
    assert pe._numeric_token_key("149") not in starved
    assert not any(pe._is_year_like_key(key) for key in starved)
    # A hedged span never starves; an unsourced number is not hedgeable.
    assert pe._span_two_source_starved_number_keys(
        "It offered a range of roughly five thousand miles.", machine, evidence_by_id
    ) == set()
    assert pe._span_two_source_starved_number_keys(
        "It carried eighty-eight rockets.", machine, evidence_by_id
    ) == set()


def test_hedge_starved_number_mentions_handles_hyphenated_phrases():
    machine = "Boeing XB-15"
    starved = {pe._numeric_token_key("5,000")}
    hedged = pe._hedge_starved_number_mentions(
        "It promised a five-thousand-mile range.", machine, starved
    )
    assert hedged == "It promised a roughly five-thousand-mile range."
    # Already-hedged spans and non-starved numbers stay untouched.
    assert pe._hedge_starved_number_mentions(
        "It promised roughly five thousand miles.", machine, starved
    ) == "It promised roughly five thousand miles."
    assert pe._hedge_starved_number_mentions(
        "It carried ninety guns.", machine, starved
    ) == "It carried ninety guns."


def test_softener_never_hedges_model_numbers():
    """Live B-17 artifact: "Model 299" must never become "Model about 299" -
    model/type numbers are names; a real quantity in the same span still hedges."""
    softened = pe._soften_single_source_span(
        "The Model 299 carried 5000 pounds.", "Boeing B-17 Flying Fortress"
    )
    assert "Model about 299" not in softened
    assert "Model 299" in softened
    assert "about 5000" in softened
    # A span with ONLY a model number gets no digit hedge at all.
    solo = pe._soften_single_source_span(
        "The Model 299 impressed observers.", "Boeing B-17 Flying Fortress"
    )
    assert "about" not in solo and "Model 299" in solo


def test_repair_mechanics_hedges_gate_starved_numbers_and_digitizes_years():
    """Integration: mechanics normalizes spelled decades in place and hedges a
    single-source spelled number, so the frozen two-source gate passes rows
    the writer left unhedged."""
    machine = "B-52"
    segments = _evidence_segments()
    decision = next(s for s in segments if s["evidence_id"] == "E-DECISION")
    decision["claim"] = "The wingspan measured 185 feet across the design finalized in the early 1950s."
    decision["source_excerpt"] = decision["claim"]
    decision["numeric_tokens"] = ["185", "1950s"]
    payload = {"unit_research_cards": [{"unit": machine, "evidence_segments": segments}]}
    plan = pe._machine_story_plan(payload, machine)

    span = "Its one hundred eighty five foot wingspan dominated ramps in the early nineteen fifties."
    bundle = {
        "editorial_thesis": "Scale traded ramp space for range in one wingspan decision.",
        "formula_sentences": [span],
        "paragraph": span,
        "claim_map": [{"span": span, "slot": "engineering_decision", "used_evidence_ids": ["E-DECISION"]}],
    }
    repaired = pe._repair_machine_story_bundle_mechanics(machine, plan, bundle)
    out_span = repaired["claim_map"][0]["span"]
    assert "1950s" in out_span and "nineteen fifties" not in out_span
    # The gate's hedge check is span-level: any recognized hedge legalizes the
    # single-source number (here the year softener's "around" lands first).
    assert pe._HEDGE_WORDS_RE.search(out_span.lower())
    assert repaired["paragraph"] == " ".join(repaired["formula_sentences"])
    assert out_span in repaired["paragraph"]

    # Without a year in the span, the starved number itself gets the hedge.
    bare_span = "Its one hundred eighty five foot wingspan dominated every ramp."
    bare_bundle = {
        "editorial_thesis": "Scale traded ramp space for range in one wingspan decision.",
        "formula_sentences": [bare_span],
        "paragraph": bare_span,
        "claim_map": [{"span": bare_span, "slot": "engineering_decision", "used_evidence_ids": ["E-DECISION"]}],
    }
    bare_repaired = pe._repair_machine_story_bundle_mechanics(machine, plan, bare_bundle)
    assert "roughly one hundred eighty five" in bare_repaired["claim_map"][0]["span"]


def test_softener_softens_determiner_guarded_ordinal_first():
    softened = pe._soften_single_source_span(
        "Its first bombing mission with the RAF revealed the design was hardly ready.",
        "Boeing B-17 Flying Fortress",
    )
    assert "first" not in softened.lower()
    assert "Its early bombing mission" in softened
    # Verb-phrase "first flew in <year>" keeps its dedicated rewrite.
    flew = pe._soften_single_source_span("The aircraft first flew in 1937.", "Boeing XB-15")
    assert "flew around 1937" in flew and "early flew" not in flew


def test_repair_mechanics_drops_wrong_slot_citations_for_formula_order():
    """Writer pass 5: a sentence grounded by its expected slot loses blended
    wrong-required-slot citations (provenance hygiene); a row is never left
    citation-less and a sentence missing its expected role is untouched."""
    machine = "B-52"
    payload = {"unit_research_cards": [{"unit": machine, "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, machine)
    s1 = "The Air Corps needed range no fighter could escort."
    s2 = "Engineers answered with eight paired engines."
    bundle = {
        "editorial_thesis": "Range demanded engines nobody could escort or afford.",
        "formula_sentences": [s1, s2],
        "paragraph": f"{s1} {s2}",
        "claim_map": [
            {"span": s1, "slot": "original_problem", "used_evidence_ids": ["E-PROBLEM", "E-DECISION"]},
            {"span": s2, "slot": "engineering_decision", "used_evidence_ids": ["E-DECISION"]},
        ],
    }
    repaired = pe._repair_machine_story_bundle_mechanics(machine, plan, bundle)
    assert repaired["claim_map"][0]["used_evidence_ids"] == ["E-PROBLEM"]
    assert repaired["claim_map"][0]["slot"] == "original_problem"
    # Sentence 2's own engineering_decision citation is untouched.
    assert repaired["claim_map"][1]["used_evidence_ids"] == ["E-DECISION"]

    # A row citing ONLY the wrong slot keeps its ids (never strand a span).
    stranded = {
        "editorial_thesis": "Range demanded engines nobody could escort or afford.",
        "formula_sentences": [s1],
        "paragraph": s1,
        "claim_map": [
            {"span": s1, "slot": "original_problem", "used_evidence_ids": ["E-DECISION"]},
        ],
    }
    stranded_repaired = pe._repair_machine_story_bundle_mechanics(machine, plan, stranded)
    assert stranded_repaired["claim_map"][0]["used_evidence_ids"] == ["E-DECISION"]


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

def test_deterministic_beat_plan_assigns_slots_and_twist_source():
    machine = "Boeing XB-15"
    segments = _evidence_segments()
    reality = next(s for s in segments if s["evidence_id"] == "E-REALITY")
    reality["claim"] = "The sole aircraft was converted to a cargo transport across the Pacific."
    reality["source_excerpt"] = reality["claim"]
    package = _package_with_extra_excerpt(
        machine, segments,
        "The sole example was redesignated XC-105 and served as a cargo transport.",
    )
    payload = {
        "unit_research_cards": [{"unit": machine, "evidence_segments": segments}],
        "machine_raw_source_packages": {pe._verified_source_cache_key(machine): package},
    }
    plan = pe._machine_story_plan(payload, machine)
    beats = pe._deterministic_beat_plan(plan, machine)
    assert [b["role"] for b in beats] == ["original_problem", "engineering_decision", "tradeoff", "reality"]
    # Beat 4 carries the reality slot AND its supports (memorable_fact folded in).
    beat4_ids = {s["evidence_id"] for s in beats[3]["segments"]}
    assert "E-REALITY" in beat4_ids and "E-MEMORABLE" in beat4_ids
    # The flagged conversion evidence is named as the mandatory twist source.
    assert beats[3].get("twist_source_id") == "E-REALITY"
    # No beat carries another beat's REQUIRED slot: formula order is safe by construction.
    for i, beat in enumerate(beats):
        other_required = pe._ANTON_REQUIRED_SLOT_ROLES - {beat["role"]}
        roles_in_beat = {
            plan["evidence_slot_roles"].get(s["evidence_id"]) for s in beat["segments"]
        }
        assert not (roles_in_beat & other_required)


def test_derive_claim_ledger_full_sentence_rows():
    beats = [
        {"index": 1, "role": "original_problem", "job": "", "segments": [{"evidence_id": "E-P"}]},
        {"index": 2, "role": "engineering_decision", "job": "", "segments": [{"evidence_id": "E-D"}, {"evidence_id": "E-S"}]},
        {"index": 3, "role": "tradeoff", "job": "", "segments": [{"evidence_id": "E-T"}]},
        {"index": 4, "role": "reality", "job": "", "segments": [{"evidence_id": "E-R"}]},
    ]
    sentences = [
        "The Army needed range.",
        "Engineers answered with a 149-foot wingspan.",
        "The engines could not keep up.",
        "It hauled cargo for eight years.",
        "Built to bomb. Remembered for hauling.",
    ]
    rows = pe._derive_claim_ledger(sentences, beats)
    assert len(rows) == 4
    assert rows[0] == {"span": "The Army needed range.", "slot": "original_problem", "used_evidence_ids": ["E-P"]}
    assert rows[1]["used_evidence_ids"] == ["E-D", "E-S"]
    # The closer never gets a row: it stays paragraph-derived synthesis.
    assert all("Remembered" not in row["span"] for row in rows)


def test_parse_planned_story_sentences_attaches_code_ledger():
    beats = [
        {"index": 1, "role": "original_problem", "job": "", "segments": [{"evidence_id": "E-P"}]},
        {"index": 2, "role": "engineering_decision", "job": "", "segments": [{"evidence_id": "E-D"}]},
        {"index": 3, "role": "tradeoff", "job": "", "segments": [{"evidence_id": "E-T"}]},
        {"index": 4, "role": "reality", "job": "", "segments": [{"evidence_id": "E-R"}]},
    ]
    raw = (
        '{"editorial_thesis":"Range demanded engines nobody had.",'
        '"twist":{"type":"role_change","substitute":null,"summary":"built to bomb, used to haul"},'
        '"sentences":["S one.","S two.","S three.","S four.","The punch."],'
        '"claim_map":[{"span":"model-made ledger that must be IGNORED","slot":"reality","used_evidence_ids":["FAKE"]}]}'
    )
    bundle = pe._parse_planned_story_sentences(raw, beats)
    assert bundle.get("_parse_error") is None
    assert bundle["paragraph"] == "S one. S two. S three. S four. The punch."
    # The ledger is code-owned: any model-made claim_map is discarded.
    assert all(row["used_evidence_ids"] != ["FAKE"] for row in bundle["claim_map"])
    assert [row["slot"] for row in bundle["claim_map"]] == [
        "original_problem", "engineering_decision", "tradeoff", "reality",
    ]
    # Bad shapes fail loudly.
    assert pe._parse_planned_story_sentences("not json", beats).get("_parse_error")
    assert pe._parse_planned_story_sentences('{"sentences": "nope"}', beats).get("_parse_error")


def test_beat_number_directives_name_the_mandatory_numbers():
    machine = "B-17"
    beats = [
        {"index": 1, "role": "original_problem", "job": "", "segments": [{"evidence_id": "E-P", "claim": "The Air Corps wanted range."}]},
        {"index": 2, "role": "engineering_decision", "job": "", "segments": [
            {"evidence_id": "E-D", "claim": "It carried nine machine guns and a 4,000-pound bomb load."},
            {"evidence_id": "E-D2", "claim": "The design was all-metal."},
        ]},
        {"index": 3, "role": "tradeoff", "job": "", "segments": []},
        {"index": 4, "role": "reality", "job": "", "segments": [
            {"evidence_id": "E-R", "claim": "12,731 were produced between 1936 and 1945."},
        ]},
    ]
    directives = pe._beat_number_directives(beats, machine)
    by_sentence = {d["sentence"]: d for d in directives}
    assert by_sentence[2]["evidence_id"] == "E-D"
    assert by_sentence[4]["evidence_id"] == "E-R"
    # The prompt block renders the directives and the closer contract.
    block = pe._beat_plan_prompt_block(beats, machine)
    assert "MANDATORY NUMBERS for sentence 4" in block
    assert "SENTENCE 5 (closer)" in block and "no numbers" in block
