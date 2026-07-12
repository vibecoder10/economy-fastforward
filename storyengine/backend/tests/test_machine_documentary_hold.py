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


def _story_bundle(machine: str, words_per_sentence: int) -> str:
    rows = []
    for index, beat in enumerate(("problem", "decision", "tradeoff", "outcome")):
        first = machine if index == 0 else beat.capitalize()
        sentence = " ".join([first] + ["clear"] * (words_per_sentence - 1)) + "."
        rows.append({"beat": beat, "sentence": sentence, "used_evidence_ids": [f"E-{beat.upper()}"]})
    conclusion = " ".join(["Conclusion"] + ["clear"] * (words_per_sentence - 1)) + "."
    return json.dumps({"sentences": rows, "conclusion": {"sentence": conclusion}})


def _evidence_segments() -> list[dict]:
    kinds = {
        "problem": "design_problem",
        "decision": "engineering_response",
        "tradeoff": "tradeoff",
        "outcome": "operational_reality",
    }
    return [
        {
            "evidence_id": f"E-{beat.upper()}",
            "kind": kind,
            "claim": f"Atomic {beat} claim grounded in the supplied source.",
            "source_excerpt": f"Atomic {beat} claim grounded in the supplied source.",
            "source_url": f"https://example.test/{beat}",
            "source_title": "Test source",
            "locator": "",
            "numeric_tokens": [],
            "confidence": "high",
        }
        for beat, kind in kinds.items()
    ]


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
                "locator": f"S{index}-E1",
                "text": segment["source_excerpt"],
                "text_hash": "test",
            }
            for index, segment in enumerate(segments, start=1)
        ],
    }


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
        ],
    }

    _evidence, errors = pe._normalize_machine_evidence(card, "Boeing XB-15")

    assert errors == []


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

    assert any("word count 90" in warning for warning in validate("XB-15", _words("XB-15", 90)))
    assert validate("XB-15", _words("XB-15", 95)) == []
    assert validate("XB-15", _words("XB-15", 120)) == []
    assert any("word count 121" in warning for warning in validate("XB-15", _words("XB-15", 121)))
    two_paragraphs = _words("XB-15", 48) + "\n\n" + _words("XB-15", 47)
    assert "must be exactly one paragraph" in validate("XB-15", two_paragraphs)
    assert validate("B52", _words("B-52", 95)) == []


def test_meta_validator_does_not_match_as_an_ai_inside_was_an_aircraft():
    paragraph = (
        "The Air Force ordered Boeing to design a jet bomber in 1946 that could reach Moscow from American bases "
        "and return without refueling. Boeing's answer was an aircraft that traded speed for range. The B-52 "
        "Stratofortress first flew on April 15, 1952, powered by eight Pratt and Whitney J57 turbojets that burned "
        "fuel slowly enough to stay airborne for sixteen hours. It was subsonic by design. The Air Force had wanted "
        "a replacement by 1980. Instead, the B-52H models built between 1960 and 1962 are still flying combat missions "
        "today, now scheduled to remain in service until the 2050s. No strategic bomber has ever served longer. The "
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


def test_story_plan_locks_research_into_ordered_sentence_jobs():
    payload = {"unit_research_cards": [{
        "unit": "B-52",
        "design_problem": "problem evidence",
        "engineering_response": "decision evidence",
        "tradeoff": "tradeoff evidence",
        "actual_outcome": "outcome evidence",
        "engineering_thesis": "meaning evidence must not become a beat",
        "surprising_fact": "must not enter the plan",
        "evidence_segments": _evidence_segments(),
    }]}

    plan = pe._machine_story_plan(payload, "B-52")

    assert [beat["beat"] for beat in plan["beats"]] == ["problem", "decision", "tradeoff", "outcome"]
    assert [beat["evidence_ids"] for beat in plan["beats"]] == [
        ["E-PROBLEM"], ["E-DECISION"], ["E-TRADEOFF"], ["E-OUTCOME"]
    ]
    assert "must not enter the plan" not in json.dumps(plan)
    assert "meaning evidence must not become a beat" not in json.dumps(plan)
    assert plan["contract"]["maximum_numerical_details"] == 2
    assert plan["contract"]["evidence_sentences"] == 4
    assert "paragraph-derived" in plan["contract"]["conclusion"]


def test_story_plan_refuses_legacy_card_without_source_addressable_evidence():
    plan = pe._machine_story_plan(
        {"unit_research_cards": [{"unit": "B-52", "engineering_thesis": "Untraceable prose."}]},
        "B-52",
    )

    assert any("schema-v2" in error for error in plan["evidence_errors"])
    assert all(not beat["evidence_ids"] for beat in plan["beats"])


def test_story_plan_refuses_claims_that_add_facts_absent_from_source_excerpt():
    evidence = _evidence_segments()
    evidence[0]["claim"] = "Aliens conquered Europe with miraculous nuclear rockets."
    plan = pe._machine_story_plan({"unit_research_cards": [{"unit": "B-52", "evidence_segments": evidence}]}, "B-52")

    assert any("claim adds words absent from source_excerpt" in error for error in plan["evidence_errors"])


def test_story_sentence_validator_blocks_reordering_and_unsupported_numbers():
    payload = {"unit_research_cards": [{
        "unit": "B-52",
        "design_problem": "A long-range mission created a difficult fuel problem.",
        "engineering_response": "Designers favored efficient subsonic flight instead of maximum speed.",
        "tradeoff": "The bomber could not escape modern interceptors through speed alone.",
        "actual_outcome": "Its adaptable structure kept accepting new weapons and electronics.",
        "engineering_thesis": "Range and adaptability ultimately mattered more than outright speed.",
        "evidence_segments": _evidence_segments(),
    }]}
    plan = pe._machine_story_plan(payload, "B-52")
    rows = json.loads(_story_bundle("B-52", 19))["sentences"]
    rows[0]["beat"], rows[1]["beat"] = rows[1]["beat"], rows[0]["beat"]
    rows[2]["sentence"] = rows[2]["sentence"].replace("clear.", "clear 1967.")

    _, warnings = pe._validate_machine_story_sentences("B-52", plan, {"sentences": rows})

    assert any("exactly ordered" in warning for warning in warnings)
    assert any("unsupported numerical detail" in warning for warning in warnings)


def test_story_sentence_validator_blocks_lowercase_second_sentence_and_fabricated_claims():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    rows = json.loads(_story_bundle("B-52", 19))["sentences"]
    rows[0]["sentence"] = "B-52 word word word word word word word word. then aliens conquered Europe with miraculous rockets word word word word."

    _, warnings = pe._validate_machine_story_sentences("B-52", plan, {"sentences": rows})

    assert any("exactly one sentence" in warning for warning in warnings)
    assert any("outside its locked evidence vocabulary" in warning for warning in warnings)


def test_story_sentence_validator_assembles_four_evidence_jobs_plus_conclusion():
    payload = {"unit_research_cards": [{
        "unit": "B-52",
        "design_problem": "problem evidence",
        "engineering_response": "decision evidence",
        "tradeoff": "tradeoff evidence",
        "actual_outcome": "outcome evidence",
        "engineering_thesis": "meaning evidence",
        "evidence_segments": _evidence_segments(),
    }]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))

    paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert warnings == []
    assert pe._spoken_word_count(paragraph) == 95
    assert paragraph.count(".") == 5


def test_story_sentence_parser_canonicalizes_evidence_object_shape():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    canonical = json.loads(_story_bundle("B-52", 19))
    loose = {
        "machine": "B-52",
        "evidence": {row["beat"]: row["sentence"] for row in canonical["sentences"]},
        "conclusion": {"paragraph_derived_sentence": canonical["conclusion"]["sentence"]},
    }

    bundle = pe._parse_machine_story_sentences(json.dumps(loose))
    paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert warnings == []
    assert [row["beat"] for row in bundle["sentences"]] == ["problem", "decision", "tradeoff", "outcome"]
    assert bundle["conclusion"]["sentence"] == canonical["conclusion"]["sentence"]
    assert pe._spoken_word_count(paragraph) == 95


def test_story_sentence_parser_canonicalizes_top_level_beat_shape():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    canonical = json.loads(_story_bundle("B-52", 19))
    loose = {row["beat"]: row["sentence"] for row in canonical["sentences"]}
    loose["conclusion"] = {"sentence": canonical["conclusion"]["sentence"]}

    bundle = pe._parse_machine_story_sentences(json.dumps(loose))
    paragraph, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert warnings == []
    assert [row["beat"] for row in bundle["sentences"]] == ["problem", "decision", "tradeoff", "outcome"]
    assert pe._spoken_word_count(paragraph) == 95


def test_story_sentence_validator_blocks_conclusion_new_evidence_or_numbers():
    payload = {"unit_research_cards": [{"unit": "B-52", "evidence_segments": _evidence_segments()}]}
    plan = pe._machine_story_plan(payload, "B-52")
    bundle = pe._parse_machine_story_sentences(_story_bundle("B-52", 19))
    bundle["conclusion"] = {
        "sentence": "Conclusion clear clear clear clear clear clear clear clear clear clear clear clear clear clear clear clear clear 1967.",
        "used_evidence_ids": ["E-OUTCOME"],
    }

    _, warnings = pe._validate_machine_story_sentences("B-52", plan, bundle)

    assert any("conclusion must not declare used_evidence_ids" in warning for warning in warnings)
    assert any("conclusion introduced unsupported numerical detail" in warning for warning in warnings)


def test_ninety_word_machine_paragraph_repairs_upward_and_saves_only_repaired_unit(monkeypatch):
    roster = ["Boeing XB-15"]
    card = {
        "unit": "Boeing XB-15",
        "design_problem": "A large bomber needed useful range despite limited engine power.",
        "engineering_response": "Boeing used an unusually large wing to create lift and carry fuel.",
        "tradeoff": "The aircraft gained range but remained too slow and underpowered for combat.",
        "actual_outcome": "It missed combat requirements and later proved useful hauling cargo.",
        "engineering_thesis": "The failed bomber taught Boeing how size, lift, and power had to balance.",
        "source_notes": ["machine-card-source"],
        "evidence_segments": _evidence_segments(),
    }
    video = {
        "video_title": "Every US Strategic Bomber Ever Built",
        "render_mode": "static_docu",
        "research_payload": {
            "fact_sheet": "GLOBAL FACT SHEET MUST NOT LEAK",
            "unit_roster": roster,
            "unit_research_cards": [card],
        },
    }

    class FakeAnthropic:
        def __init__(self):
            self.prompts = []
            self.system_prompts = []
            self.outputs = [_story_bundle("XB-15", 18), _story_bundle("XB-15", 19)]

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

    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(executor, "_validate_static_script_roster", fake_validate)
    monkeypatch.setattr(executor, "_update_video_status", fake_update_status)
    monkeypatch.setattr(executor, "_skip_disabled_next", lambda _video, status: status)

    result = asyncio.run(executor._run_static_script_hold("video-test", video, roster))

    assert result["status"] == "ready_for_voice"
    assert len(fake_anthropic.prompts) == 2, "under-length sentence jobs must trigger one fresh bundle repair"
    assert "GLOBAL FACT SHEET MUST NOT LEAK" not in fake_anthropic.prompts[0]
    assert "machine-card-source" not in fake_anthropic.prompts[0]
    assert "Atomic problem claim grounded in the supplied source" in fake_anthropic.prompts[0]
    assert "DISTILL FOUR LOCKED RESEARCH BEATS" in fake_anthropic.prompts[0]
    assert '"beat": "problem"' in fake_anthropic.prompts[0]
    assert "one complete spoken sentence per evidence beat, 19-24 words each" in fake_anthropic.prompts[0]
    assert '"conclusion":{"sentence":"..."}' in fake_anthropic.prompts[0]
    assert "conclusion has no used_evidence_ids" in fake_anthropic.prompts[0]
    assert "at most two numerical details" in fake_anthropic.prompts[0]
    assert "REBUILD THE FOUR-EVIDENCE-SENTENCE JSON BUNDLE" in fake_anthropic.prompts[1]
    assert fake_anthropic.system_prompts[0].startswith("ANTON TENANT SCRIPT CONTRACT")
    assert "SCOPED OVERRIDE — COMPLETE INVENTORY MODE" in fake_anthropic.system_prompts[0]
    assert "SCOPED OVERRIDE — COMPLETE INVENTORY MODE" in fake_anthropic.system_prompts[1]
    assert "Omission is a feature" in fake_anthropic.system_prompts[0]
    assert "LOCKED STORY PLAN" in fake_anthropic.prompts[0]
    assert "rejected draft is hidden" in fake_anthropic.prompts[1]

    atomic_replacements = [(query, args) for query, args in writes if "jsonb_to_recordset" in query]
    assert len(atomic_replacements) == 1
    saved_paragraph = json.loads(atomic_replacements[0][1][2])[0]["scene_text"]
    assert pe._spoken_word_count(saved_paragraph) == 95
    assert "XB-15" in saved_paragraph


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


def test_script_generation_exception_preserves_existing_script_rows(monkeypatch):
    roster = ["Boeing XB-15"]
    video = {
        "video_title": "Designed vs Used: Bombers",
        "render_mode": "static_docu",
        "research_payload": {
            "unit_roster": roster,
            "unit_research_cards": [{"unit": "Boeing XB-15"}],
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
        "evidence_segments": b52_segments,
    }

    class FakeAnthropic:
        def __init__(self):
            self.prompts = []

        async def generate(self, **kwargs):
            self.prompts.append(kwargs["prompt"])
            return json.dumps(b52_card)

    fake_anthropic = FakeAnthropic()
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": fake_anthropic})()
    fetch_calls = []

    async def fake_execute(*_args, **_kwargs):
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
    assert "EXACT_TEXT: Atomic problem claim grounded in the supplied source." in prompt
    assert "XB-15 leak" not in prompt
    assert "B-36 leak" not in prompt
    assert result["unit_research_hold_validation"]["passed"] is True
    assert result["unit_research_hold_validation"]["target_machine"] == "Boeing B-52 Stratofortress"


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

    async def fake_execute(*_args, **_kwargs):
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


def test_research_hold_contract_persists_each_card_and_never_reopens_roster():
    source = open(pe.__file__, encoding="utf-8").read()
    hold = source[source.index("async def _run_unit_research_hold"):source.index("async def _resplit_static_scenes")]

    assert "The roster is locked. Do not add, remove, replace, or relitigate machines." in hold
    assert "SET research_payload" in hold
    assert "locked_roster_snapshot" in hold


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
            "surprising_fact": "A fact", "source_notes": ["source"], "evidence_segments": _evidence_segments()}
    payload = {"unit_roster": roster, "unit_research_cards": [card]}
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
