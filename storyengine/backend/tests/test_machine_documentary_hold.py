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


def test_verified_source_package_format_exposes_source_tier():
    segments = _evidence_segments()
    segments[0]["source_url"] = "https://en.wikipedia.org/wiki/Boeing_XB-15"
    package = _verified_package_for_segments("Boeing XB-15", segments)
    package["candidate_excerpts"][0]["source_capture_method"] = "fetched_page"
    pe._anton_source_slot_coverage(package["candidate_excerpts"], "Boeing XB-15")

    formatted = pe._format_verified_machine_source_package(package)

    assert "SOURCE_TIER: 4 - Tier 4 caution/general" in formatted
    assert "SOURCE_CAPTURE_METHOD: fetched_page" in formatted
    assert "ANTON_SLOT_HINTS:" in formatted


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
    assert "related links and navigation" not in result["candidate_excerpts"][0]["text"]
    assert result["source_slot_coverage"]["missing_slots"] == []


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
    assert result["source_slot_coverage"]["needs_distinct_slot_excerpts"] is False
    assert result["source_slot_coverage"]["distinct_slot_excerpt_count"] == 4
    assert set(result["source_slot_coverage"]["covered_slots"]) == {
        "engineering_decision",
        "original_problem",
        "reality",
        "tradeoff",
    }
    assert result["candidate_excerpts"][0]["anton_slot_hints"]


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

    assert warnings == []


def test_required_anton_slots_accept_authoritative_source_support():
    segments = _evidence_segments()
    for segment in segments:
        segment["source_url"] = "https://airandspace.si.edu/collection-objects/boeing-xb-15"
    package = _verified_package_for_segments("Boeing XB-15", segments)
    card = {"unit": "Boeing XB-15", "evidence_segments": segments}

    warnings = pe._validate_card_against_verified_sources(card, package)

    assert warnings == []


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


def test_verified_card_validation_backfills_raw_excerpt_identity():
    segments = _evidence_segments()
    for segment in segments:
        segment["source_url"] = "https://airandspace.si.edu/collection-objects/boeing-xb-15"
    package = _verified_package_for_segments("Boeing XB-15", segments)
    package["candidate_excerpts"][0]["text_hash"] = "excerpt-hash-1"
    card = {"unit": "Boeing XB-15", "evidence_segments": segments}

    warnings = pe._validate_card_against_verified_sources(card, package)

    assert warnings == []
    assert segments[0]["source_excerpt_id"] == "S1-E1"
    assert segments[0]["source_id"] == "S1"
    assert segments[0]["source_excerpt_hash"] == "excerpt-hash-1"
    assert segments[0]["source_tier"] == 2
    assert segments[0]["source_tier_label"] == "Tier 2 museum/authoritative secondary"
    assert segments[0]["source_capture_method"] == "fetched_page"


def test_story_plan_preserves_raw_excerpt_identity_for_script_preview():
    segments = _evidence_segments()
    segments[0].update({
        "source_excerpt_id": "S1-E1",
        "source_id": "S1",
        "source_excerpt_hash": "excerpt-hash-1",
        "source_tier": 2,
        "source_tier_label": "Tier 2 museum/authoritative secondary",
        "source_capture_method": "fetched_page",
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


def test_hard_word_bounds_are_95_through_120_inclusive():
    validate = pe.PipelineExecutor._validate_static_unit_paragraph

    assert any("word count 94" in warning for warning in validate("XB-15", _words("XB-15", 94)))
    assert validate("XB-15", _words("XB-15", 95)) == []
    assert validate("XB-15", _words("XB-15", 120)) == []
    assert any("word count 121" in warning for warning in validate("XB-15", _words("XB-15", 121)))
    two_paragraphs = _words("XB-15", 48) + "\n\n" + _words("XB-15", 47)
    assert "must be exactly one paragraph" in validate("XB-15", two_paragraphs)
    assert validate("B52", _words("B-52", 95)) == []


def test_voiceover_digit_gate_keeps_designations_but_flags_quantities():
    mentions = pe._raw_digit_mentions_for_voiceover(
        "B-52, XB-15, MiG-21, F-86, J57, and TF30 stay, but 1937, 5,130 miles, and 47% should be spoken."
    )

    assert mentions == ["1937", "5,130", "47%"]


def test_voiceover_unit_gate_flags_written_units_but_keeps_designations():
    mentions = pe._written_unit_abbreviations_for_voiceover(
        "B-52, XB-15, and J57 stay, but five hundred mph, three thousand rpm, one hundred ft, two lb, ten hp, and fifty mi should be expanded."
    )

    assert mentions == ["mph", "rpm", "ft", "lb", "hp", "mi"]


def test_static_validator_requires_spoken_numbers_but_keeps_designations():
    validate = pe.PipelineExecutor._validate_static_unit_paragraph

    clean_designations = _words("B-52", 95)
    raw_quantity = " ".join(["B-52"] + ["word"] * 93 + ["1937"])

    assert not any("raw numeric digit" in warning for warning in validate("B-52", clean_designations))
    assert any("raw numeric digit" in warning and "1937" in warning for warning in validate("B-52", raw_quantity))


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
            "engineering_thesis": "The central size-versus-power tension.",
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
        }],
    }

    brief = pe._inventory_story_brief(payload, "Boeing XB-15")
    serialized = json.dumps(brief)

    assert brief["core_tension"] == "The central size-versus-power tension."
    assert brief["actual_outcome"] == "It missed combat requirements. It later hauled cargo."
    assert brief["historical_significance"] == "It taught Boeing what the next generation required."
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
    assert by_slot["original_problem"] == ["E-PROBLEM"]
    assert by_slot["engineering_decision"] == ["E-DECISION"]
    assert by_slot["tradeoff"] == ["E-TRADEOFF"]
    assert by_slot["reality"] == ["E-REALITY", "E-MEANING"]
    assert by_slot["memorable_fact"] == ["E-MEMORABLE"]
    assert "historical_meaning" not in by_slot
    assert "must not enter the plan" not in json.dumps(plan)
    assert plan["contract"]["maximum_numerical_details"] == 8
    assert plan["contract"]["narrative_weight"]["label"] == "standard"
    assert plan["contract"]["narrative_weight"]["target_words"] == "100-112"
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
    assert major_plan["contract"]["narrative_weight"]["target_words"] == "112-120"
    assert transitional_plan["contract"]["narrative_weight"]["label"] == "transitional"
    assert transitional_plan["contract"]["narrative_weight"]["target_words"] == "95-103"


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


def test_machine_preview_has_no_deterministic_story_fallback():
    source = open(pe.__file__, encoding="utf-8").read()

    assert "_deterministic_machine_story_bundle" not in source
    assert "deterministic_bundle" not in source
    assert "emergency repair for known XB-15" not in source


def test_story_paragraph_validator_accepts_anton_slot_bundle():
    payload = {"unit_research_cards": [{
        "unit": "B-52",
        "evidence_segments": _evidence_segments(),
    }]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))

    paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert warnings == []
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

    assert warnings == []
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
    extra_sentence_bundle["claim_map"].append({
        "slot": "memorable_fact",
        "span": extra_sentence,
        "used_evidence_ids": ["E-MEMORABLE"],
    })

    _paragraph, extra_warnings = pe._validate_machine_story_sentences("B-52", plan, extra_sentence_bundle)

    assert any("paragraph must follow Anton formula" in warning for warning in extra_warnings)

    wrong_order_bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    wrong_order_bundle["claim_map"][0]["slot"] = "engineering_decision"
    wrong_order_bundle["claim_map"][0]["used_evidence_ids"] = ["E-DECISION"]
    wrong_order_bundle["claim_map"][1]["slot"] = "original_problem"
    wrong_order_bundle["claim_map"][1]["used_evidence_ids"] = ["E-PROBLEM"]

    _paragraph, order_warnings = pe._validate_machine_story_sentences("B-52", plan, wrong_order_bundle)

    assert any("sentence 1 must carry original_problem evidence" in warning for warning in order_warnings)
    assert any("sentence 2 must carry engineering_decision evidence" in warning for warning in order_warnings)


def test_story_paragraph_validator_requires_available_memorable_fact():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    bundle["claim_map"][3]["used_evidence_ids"] = ["E-REALITY"]

    _paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert any("must use sourced memorable_fact" in warning for warning in warnings)


def test_story_paragraph_validator_requires_formula_sentence_assembly():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))

    missing_bundle = copy.deepcopy(bundle)
    missing_bundle.pop("formula_sentences", None)
    _paragraph, missing_warnings = pe._validate_machine_story_sentences("B-52", plan, missing_bundle)

    mismatch_bundle = copy.deepcopy(bundle)
    mismatch_bundle["formula_sentences"] = list(mismatch_bundle["formula_sentences"])
    mismatch_bundle["formula_sentences"][1] = "This sentence does not assemble into the paragraph."
    _paragraph, mismatch_warnings = pe._validate_machine_story_sentences("B-52", plan, mismatch_bundle)

    assert any("formula_sentences must contain 5 assembled sentences" in warning for warning in missing_warnings)
    assert any("formula_sentences must assemble exactly into paragraph" in warning for warning in mismatch_warnings)


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

    assert any("story plan missing sourced memorable_fact" in warning for warning in warnings)
    assert audit["passed"] is False
    memorable_check = next(check for check in audit["checks"] if check["name"] == "memorable_fact")
    assert memorable_check["passed"] is False
    assert "no sourced memorable_fact" in memorable_check["detail"]


def test_anton_preview_quality_audit_reports_passed_checks():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    audit = pe._anton_preview_quality_audit("B-52", plan, bundle, paragraph, warnings)

    assert warnings == []
    assert audit["passed"] is True
    assert [check["name"] for check in audit["checks"]] == [
        "word_range",
        "sentence_shape",
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

    assert any("narrative_weight target major 112-120 words" in warning for warning in warnings)
    narrative_check = next(check for check in audit["checks"] if check["name"] == "narrative_weight")
    assert audit["passed"] is False
    assert narrative_check["passed"] is False
    assert narrative_check["detail"] == "major target 112-120; 95 words"


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
    assert narrative_check["detail"] == "transitional target 95-103; 95 words"


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
        {},
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
    fact_rhythm_audit = pe._anton_preview_quality_audit(
        "Boeing XB-15",
        plan,
        {},
        fact_rhythm_paragraph,
        [],
    )
    fact_rhythm_check = next(
        check for check in fact_rhythm_audit["checks"] if check["name"] == "benchmark_cadence"
    )

    assert fact_rhythm_check["passed"] is True
    assert "scale/capability present" in fact_rhythm_check["detail"]
    assert "production/service reality present" in fact_rhythm_check["detail"]

    spoken_number_paragraph = (
        "Boeing XB-15 first flew in nineteen thirty-seven as America's experimental answer to long-range bombing. "
        "Its one hundred forty-nine-foot wingspan, four engines, and five thousand one hundred thirty-mile range turned scale into the engineering decision. "
        "Only one prototype was built, which made the ambition hard to convert into a combat bomber. "
        "In World War II, the aircraft found reality as a Pacific transport instead of a bomber. "
        "The XB-15 proved the concept without becoming the weapon."
    )
    spoken_number_audit = pe._anton_preview_quality_audit(
        "Boeing XB-15",
        plan,
        {},
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
        audit = pe._anton_preview_quality_audit(machine, plan, {}, paragraph, [])
        cadence_check = next(check for check in audit["checks"] if check["name"] == "benchmark_cadence")

        assert cadence_check["passed"] is True
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

    assert warnings == []


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
        "reality grounded the source claim in the same machine proof again."
    )
    bundle["paragraph"] = bundle["paragraph"].replace(old_final, long_final)
    bundle["formula_sentences"] = _formula_sentences_from_paragraph(bundle["paragraph"])

    _paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)
    audit = pe._anton_preview_quality_audit("B-52", plan, bundle, bundle["paragraph"], warnings)
    final_check = next(check for check in audit["checks"] if check["name"] == "landed_final_line")

    assert any("final sentence word count" in warning and "maximum is 18" in warning for warning in warnings)
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
    evidence[2]["numeric_tokens"] = ["1950"]
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": evidence}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    sentence_parts = [part for part in bundle["paragraph"].split(". ") if part]
    old_final = sentence_parts[-1]
    new_final = old_final.rstrip(".") + " in 1950."
    bundle["paragraph"] = bundle["paragraph"].replace(old_final, new_final)

    _paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert any("final sentence must be paragraph-derived synthesis without new numerical detail" in warning for warning in warnings)
    assert not any("paragraph introduced unsupported numerical detail" in warning for warning in warnings)


def test_story_paragraph_validator_blocks_new_named_entity_in_final_synthesis():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    sentence_parts = [part for part in bundle["paragraph"].split(". ") if part]
    old_final = sentence_parts[-1]
    new_final = old_final.rstrip(".") + " over Vietnam."
    bundle["paragraph"] = bundle["paragraph"].replace(old_final, new_final)

    _paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert any("final sentence must not introduce new named entity/event detail(s): Vietnam" in warning for warning in warnings)
    assert not any("paragraph introduced unsupported numerical detail" in warning for warning in warnings)


def test_story_paragraph_validator_blocks_new_lowercase_fact_in_final_synthesis():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    sentence_parts = [part for part in bundle["paragraph"].split(". ") if part]
    old_final = sentence_parts[-1]
    new_final = old_final.rstrip(".") + " against missiles."
    bundle["paragraph"] = bundle["paragraph"].replace(old_final, new_final)

    _paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert any(
        "final sentence must not introduce new factual word(s)" in warning and "missiles" in warning
        for warning in warnings
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
    evidence[2]["numeric_tokens"] = ["1950"]
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": evidence}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    old_sentence = bundle["claim_map"][1]["span"]
    mapped_span = old_sentence.rstrip(".")
    new_sentence = mapped_span + " in 1950."
    bundle["claim_map"][1]["span"] = mapped_span
    bundle["paragraph"] = bundle["paragraph"].replace(old_sentence, new_sentence)

    _paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert any("sentence 2 numerical detail(s) outside claim_map span coverage: 1950" in warning for warning in warnings)
    assert not any("paragraph introduced unsupported numerical detail" in warning for warning in warnings)


def test_story_paragraph_validator_blocks_unsupported_factual_words_in_claim_span():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    old_span = bundle["claim_map"][0]["span"]
    new_span = old_span.rstrip(".") + " with a pressurized cockpit."
    bundle["claim_map"][0]["span"] = new_span
    bundle["paragraph"] = bundle["paragraph"].replace(old_span, new_span)

    _paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert any("unsupported factual word(s)" in warning for warning in warnings)
    assert any("pressurized" in warning and "cockpit" in warning for warning in warnings)


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

    assert warnings == []
    assert pe._spoken_word_count(paragraph) == 102


def test_story_sentence_parser_accepts_paragraph_object_shape():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    canonical = json.loads(_story_bundle("B-52", 19))

    bundle = pe._parse_machine_story_sentences(json.dumps(canonical))
    paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert warnings == []
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

    assert warnings == []
    assert "five thousand miles" in paragraph

    bad_bundle = copy.deepcopy(bundle)
    bad_bundle["paragraph"] = bad_bundle["paragraph"].replace(
        "five thousand", "six thousand"
    )
    bad_sentences = [part if part.endswith(".") else part + "." for part in bad_bundle["paragraph"].split(". ") if part]
    for row, sentence in zip(bad_bundle["claim_map"], bad_sentences):
        row["span"] = sentence

    _, bad_warnings = pe._validate_machine_story_sentences("Boeing XB-15", plan, bad_bundle)

    assert any("six thousand" in warning for warning in bad_warnings)

    unit_bundle = copy.deepcopy(bundle)
    unit_bundle["paragraph"] = unit_bundle["paragraph"].replace(
        "five thousand miles", "five thousand mi"
    )
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

    _, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert any("unsupported designation" in warning for warning in warnings)
    assert any("high-risk term" in warning for warning in warnings)


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
            self.outputs = [_story_bundle("XB-15", 17), _story_bundle("XB-15", 19)]

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
        return {"passed": True, "checks": [], "summary": "Anton quality audit passed"}

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
    assert "GLOBAL FACT SHEET MUST NOT LEAK" not in fake_anthropic.prompts[0]
    assert "machine-card-source" not in fake_anthropic.prompts[0]
    assert "Original problem claim grounded in the supplied source" in fake_anthropic.prompts[0]
    assert "WRITE ONE ANTON-STYLE PARAGRAPH" in fake_anthropic.prompts[0]
    assert '"editorial_thesis":"single engineering decision or contrast"' in fake_anthropic.prompts[0]
    assert '"formula_sentences":["original_problem sentence","engineering_decision sentence","tradeoff sentence","reality sentence","paragraph-derived conclusion"]' in fake_anthropic.prompts[0]
    assert "formula_sentences must contain those exact five final sentences in order" in fake_anthropic.prompts[0]
    assert "editorial_thesis must be 6-26 words" in fake_anthropic.prompts[0]
    assert "OPENING ASSIGNMENT: A machine-name opening is allowed here" in fake_anthropic.prompts[0]
    assert "Follow OPENING ASSIGNMENT exactly" in fake_anthropic.prompts[0]
    assert "NARRATIVE WEIGHT: standard / target 100-112 words" in fake_anthropic.prompts[0]
    assert "Follow NARRATIVE WEIGHT as the target inside the hard range" in fake_anthropic.prompts[0]
    for required_slot in ["original_problem", "engineering_decision", "tradeoff", "reality"]:
        assert required_slot in fake_anthropic.prompts[0]
    assert "original_problem, engineering_decision, tradeoff, and reality" in fake_anthropic.prompts[0]
    assert "at least one claim_map row must use a memorable_fact evidence ID" in fake_anthropic.prompts[0]
    assert "final sentence is editorial synthesis from the assembled paragraph only" in fake_anthropic.prompts[0]
    assert "Do not include it in claim_map" in fake_anthropic.prompts[0]
    assert "No orphan facts" in fake_anthropic.prompts[1]
    assert "95-120 words, exactly 5 natural sentences" in fake_anthropic.prompts[0]
    assert "4 evidence-backed sentences + 1 paragraph-derived conclusion" in fake_anthropic.prompts[0]
    assert "Use at most 8 numerical details total" in fake_anthropic.prompts[0]
    assert "both contain that exact numeric detail" in fake_anthropic.prompts[0]
    assert "final sentence must be 18 words or fewer" in fake_anthropic.prompts[0]
    assert "End with a short verdict" in fake_anthropic.prompts[0]
    assert "Avoid written-language connector sentence starts" in fake_anthropic.prompts[0]
    assert "Do not use ranked-list connectors" in fake_anthropic.prompts[0]
    assert "Use voice-ready spoken number words" in fake_anthropic.prompts[0]
    assert "Spell unit abbreviations like mph, rpm, ft, lb, mi, and hp into spoken words" in fake_anthropic.prompts[0]
    assert "Keep designations/model names like B-52, XB-15, and F-86 as designations" in fake_anthropic.prompts[0]
    assert "Vary sentence length for spoken delivery. Do not write three long sentences in a row" in fake_anthropic.prompts[0]
    assert "Do not write a chronological biography" in fake_anthropic.prompts[0]
    assert "No citations, headings, markdown, commentary, unit labels, act labels, b-roll cues, thumbnail lines, bracketed production notes" in fake_anthropic.prompts[0]
    assert "REBUILD THE ANTON-STYLE PARAGRAPH JSON" in fake_anthropic.prompts[1]
    assert '"editorial_thesis":"single engineering decision or contrast"' in fake_anthropic.prompts[1]
    assert '"formula_sentences":["original_problem sentence","engineering_decision sentence","tradeoff sentence","reality sentence","paragraph-derived conclusion"]' in fake_anthropic.prompts[1]
    assert "formula_sentences must contain those exact five final sentences in order" in fake_anthropic.prompts[1]
    assert "OPENING ASSIGNMENT: A machine-name opening is allowed here" in fake_anthropic.prompts[1]
    assert "Follow OPENING ASSIGNMENT exactly" in fake_anthropic.prompts[1]
    assert "NARRATIVE WEIGHT: standard / target 100-112 words" in fake_anthropic.prompts[1]
    assert "Follow NARRATIVE WEIGHT as the target" in fake_anthropic.prompts[1]
    assert "Remove written-language connector sentence starts" in fake_anthropic.prompts[1]
    assert "Remove ranked-list connectors" in fake_anthropic.prompts[1]
    assert "No markdown, labels, b-roll cues, thumbnail lines, or bracketed production notes" in fake_anthropic.prompts[1]
    assert "Vary sentence length for spoken delivery; do not write three long sentences in a row" in fake_anthropic.prompts[1]
    assert "Do not write a chronological biography" in fake_anthropic.prompts[1]
    assert "Introduce no unsupported claims" in fake_anthropic.prompts[1]
    assert "Use at most 8 numerical details total" in fake_anthropic.prompts[1]
    assert "both contain that exact numeric detail" in fake_anthropic.prompts[1]
    assert "Spell unit abbreviations like mph, rpm, ft, lb, mi, and hp into spoken words" in fake_anthropic.prompts[1]
    assert "use at least one memorable_fact evidence ID" in fake_anthropic.prompts[1]
    assert "Do not include it in claim_map" in fake_anthropic.prompts[1]
    assert "18 words or fewer" in fake_anthropic.prompts[1]
    assert fake_anthropic.system_prompts[0].startswith("You are a source-grounded Anton/DVsU paragraph compiler")
    assert "ANTON TENANT SCRIPT CONTRACT" not in fake_anthropic.system_prompts[0]
    assert "SCOPED OVERRIDE — COMPLETE INVENTORY MODE" in fake_anthropic.system_prompts[0]
    assert "SCOPED OVERRIDE — COMPLETE INVENTORY MODE" in fake_anthropic.system_prompts[1]
    assert "Omission is a feature" in fake_anthropic.system_prompts[0]
    assert "Use a sourced memorable_fact when the story plan provides one" in fake_anthropic.system_prompts[0]
    assert "LOCKED STORY PLAN" in fake_anthropic.prompts[0]
    assert "rejected draft is hidden" in fake_anthropic.prompts[1]

    atomic_replacements = [(query, args) for query, args in writes if "jsonb_to_recordset" in query]
    assert len(atomic_replacements) == 1
    saved_paragraph = json.loads(atomic_replacements[0][1][2])[0]["scene_text"]
    assert pe._spoken_word_count(saved_paragraph) == 95
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
        return {"passed": True, "checks": [], "summary": "Anton quality audit passed"}

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
        return {"passed": True, "checks": [], "summary": "Anton quality audit passed"}

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
    assert [check["name"] for check in result["preview"]["quality_audit"]["checks"]][:4] == [
        "word_range",
        "sentence_shape",
        "sentence_assembly",
        "four_evidence_beats",
    ]
    reference_check = next(check for check in result["preview"]["quality_audit"]["checks"] if check["name"] == "reference_shape")
    assert reference_check["advisory"] is True
    assert "benchmark 94 words/5 sentences" in reference_check["detail"]
    assert result["preview"]["story_plan"]["reference_benchmark"]["reference_machine"] == "Boeing XB-15"
    assert result["preview"]["story_plan"]["contract"]["opening_assignment"].startswith("A machine-name opening is allowed")
    assert result["preview"]["story_plan"]["contract"]["narrative_weight"]["target_words"] == "100-112"
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
    assert load_calls == [("video-test", roster, "Boeing XB-15")]
    assert fetch_calls == [("SELECT voice_id FROM scripts WHERE video_id = $1 AND tenant_id = $2 LIMIT 1", ("video-test", "tenant-test"))]
    assert "B-17 SHOULD NOT LEAK" not in fake_anthropic.prompts[0]
    assert "XB-15 source-grounded" not in fake_anthropic.prompts[0]
    assert "Original problem claim grounded in the supplied source" in fake_anthropic.prompts[0]
    assert "reference_benchmark" in fake_anthropic.prompts[0]
    assert "Do not copy or infer unsourced facts from it" in fake_anthropic.prompts[0]
    assert "Strategic Bomber benchmark" in fake_anthropic.prompts[0]
    assert "selected scale/spec facts" in fake_anthropic.prompts[0]
    assert "OPENING ASSIGNMENT: A machine-name opening is allowed here" in fake_anthropic.prompts[0]
    assert "Follow OPENING ASSIGNMENT exactly" in fake_anthropic.prompts[0]
    assert "If the plan provides a human_detail slot for one of the first three benchmark machines" in fake_anthropic.prompts[0]


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
    assert result["preview"]["warnings"] == []
    assert result["preview"]["quality_audit"]["passed"] is False
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

    assert result["status"] == "failed"
    assert "missing verified raw internet source package" in result["error"]
    assert forbidden_anthropic.calls == 0
    assert writes == []


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

    assert result["status"] == "failed"
    assert "Script preview evidence gate failed" in result["error"]
    assert "missing sourced memorable_fact evidence segment" in result["error"]
    assert forbidden_anthropic.calls == 0
    assert writes == []


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

    assert result["status"] == "failed"
    assert "source_excerpt/locator was not found" in result["error"]
    assert forbidden_anthropic.calls == 0
    assert writes == []


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

    assert result["status"] == "failed"
    assert "does not match locked machine XB15" in result["error"]
    assert forbidden_anthropic.calls == 0
    assert writes == []


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
            }

    monkeypatch.setattr(route, "PipelineExecutor", FakeExecutor)

    result = asyncio.run(
        route.run_machine_script_preview(
            "video-test",
            route.MachineScriptPreviewRequest(machine="Boeing XB-15"),
            tenant_id="tenant-test",
        )
    )

    assert result["preview"]["passed"] is False
    assert result["preview"]["paragraph"] == "Reviewable paragraph."
    assert "word count" in result["preview"]["warnings"][0]


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
                route.MachineResearchRequest(machine="Boeing XB-15"),
                tenant_id="tenant-test",
            )
        )
    except route.HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "One-machine research failed. Please try again."
        assert "SECRET_RAW" not in exc.detail
    else:
        raise AssertionError("provider failure should return a humanized HTTPException")


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
    payload = {
        "unit_roster": roster_names,
        "fact_sheet": (
            "Boeing XB-15 leak should never enter the B-52 proof. "
            "The B-52 target source sentence says the Stratofortress was adapted around range and payload. "
            "Convair B-36 leak should never enter the B-52 proof."
        ),
        "unit_research_cards": [
            {"unit": "Boeing XB-15", "engineering_thesis": "XB-15 stale legacy card leak."},
            {"unit": "Convair B-36", "engineering_thesis": "B-36 stale legacy card leak."},
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
        return _verified_package_for_segments(machine, b52_segments)

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
    assert "LOCKED MACHINE 2 OF 3: Boeing B-52 Stratofortress" in prompt
    assert "VERIFIED RAW INTERNET EXCERPTS FOR THIS MACHINE" in prompt
    assert "EXACT_TEXT: Boeing B-52 Stratofortress Original problem claim grounded in the supplied source." in prompt
    assert "source_excerpt_id, source_url, source_title, locator" in prompt
    assert "source_excerpt_id must equal that row's EXCERPT_ID" in prompt
    assert "source_url and locator must match" in prompt
    assert "source_url or locator" not in prompt
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
    assert "memorable_fact should be returned when the verified excerpts support" in prompt
    assert "never invent one" in prompt
    assert "Be precise or be silent" in prompt
    assert "never pick the higher or more dramatic claim" in prompt
    assert "onscreen_label is metadata for Producer File/on-screen text, never spoken narration" in prompt
    assert "For machines 1-3, prefer one verified human_detail" in prompt
    assert "A human_detail segment must be attributed to a named person" in prompt
    assert "return it as reality, not historical_meaning" in prompt
    assert "Never invent a human account" in prompt
    assert "XB-15 leak" not in prompt
    assert "B-36 leak" not in prompt
    assert result["unit_research_hold_validation"]["passed"] is False
    assert result["unit_research_hold_validation"]["target_machine_passed"] is True
    assert result["unit_research_hold_validation"]["target_machine"] == "Boeing B-52 Stratofortress"


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
    assert result["research_card"] == card
    assert json.loads(writes[0][1][0])["unit_research_hold_validation"]["passed"] is False
    assert "research_payload->'unit_roster' = $5::jsonb" in writes[0][0]
    assert json.loads(writes[0][1][4]) == roster_names


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


def test_target_machine_research_requires_verified_source_package_before_llm(monkeypatch):
    roster_names = ["Boeing XB-15", "Boeing B-52 Stratofortress", "Convair B-36"]
    payload = {"unit_roster": roster_names}

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
    assert result["unit_research_hold_validation"]["warnings"] == ["no verified excerpts"]
    assert any("machine_raw_source_packages" in query for query, _args in writes)
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
    assert "two distinct source URLs" in result["unit_research_hold_validation"]["warnings"][0]
    assert any("machine_raw_source_packages" in query for query, _args in writes)
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
    assert by_slot["original_problem"] == ["E-PROBLEM"]
    assert by_slot["engineering_decision"] == ["E-DECISION"]
    assert by_slot["tradeoff"] == ["E-TRADEOFF"]
    assert by_slot["reality"] == ["E-REALITY", "E-MEANING"]
    assert "historical_meaning" not in by_slot


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
