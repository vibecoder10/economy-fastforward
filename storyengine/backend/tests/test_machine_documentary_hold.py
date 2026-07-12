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


def test_ninety_word_machine_paragraph_repairs_upward_and_saves_only_repaired_unit(monkeypatch):
    roster = ["Boeing XB-15"]
    card = {
        "unit": "Boeing XB-15",
        "engineering_thesis": "A deliberately isolated machine-level thesis.",
        "surprising_fact": "The isolated fact used for this machine only.",
        "source_notes": ["machine-card-source"],
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
            self.outputs = [_words("XB-15", 90), _words("XB-15", 95)]

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
    assert len(fake_anthropic.prompts) == 2, "90 words must trigger one-machine repair"
    assert "GLOBAL FACT SHEET MUST NOT LEAK" not in fake_anthropic.prompts[0]
    assert "machine-card-source" not in fake_anthropic.prompts[0]
    assert "A deliberately isolated machine-level thesis." in fake_anthropic.prompts[0]
    assert "VIDEO THESIS / ARC" in fake_anthropic.prompts[0]
    assert "FORMAT MODE: COMPLETE INVENTORY" in fake_anthropic.prompts[0]
    assert "TARGET 105-110 words" in fake_anthropic.prompts[0]
    assert "no more than 5 factual story beats" in fake_anthropic.prompts[0]
    assert "at most 2 numerical details total" in fake_anthropic.prompts[0]
    assert "Remove the least important facts" in fake_anthropic.prompts[1]
    assert fake_anthropic.system_prompts[0].startswith("ANTON TENANT SCRIPT CONTRACT")
    assert "SCOPED OVERRIDE — COMPLETE INVENTORY MODE" in fake_anthropic.system_prompts[0]
    assert "SCOPED OVERRIDE — COMPLETE INVENTORY MODE" in fake_anthropic.system_prompts[1]
    assert "Omission is a feature" in fake_anthropic.system_prompts[0]
    assert "compact_editorial_brief" in fake_anthropic.prompts[0]
    assert "BAD PARAGRAPH" not in fake_anthropic.prompts[1]
    assert "rejected draft is deliberately hidden" in fake_anthropic.prompts[1]

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


def test_research_hold_processes_and_checkpoints_one_locked_machine_at_a_time(monkeypatch):
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

    cards = [
        {
            "unit": machine,
            "include": True,
            "engineering_thesis": f"{machine} demonstrates one specific engineering tradeoff.",
            "surprising_fact": f"A surprising isolated fact about {machine}.",
            "source_notes": [f"source for {machine}"],
        }
        for machine in roster_names
    ]

    class FakeAnthropic:
        def __init__(self):
            self.prompts = []
            self.outputs = [json.dumps(card) for card in cards]

        async def generate(self, **kwargs):
            self.prompts.append(kwargs["prompt"])
            return self.outputs.pop(0)

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

    assert len(fake_anthropic.prompts) == 3
    for index, (prompt, machine) in enumerate(zip(fake_anthropic.prompts, roster_names), start=1):
        assert f"LOCKED MACHINE {index} OF 3: {machine}" in prompt
        assert "The roster is locked. Do not add, remove, replace, or relitigate machines." in prompt

    checkpoints = [(query, args) for query, args in writes if "SET research_payload" in query]
    assert len(checkpoints) == 3
    compact_checkpoints = [(query, args) for query, args in writes if "INSERT INTO machine_research_cards" in query]
    assert len(compact_checkpoints) == 3
    assert all(args[:2] == ("tenant-test", "video-test") for _query, args in compact_checkpoints)
    assert [args[4] for _query, args in compact_checkpoints] == [1, 2, 3]
    assert [len(json.loads(args[0])["unit_research_cards"]) for _query, args in checkpoints] == [1, 2, 3]
    assert all(json.loads(args[0])["unit_roster"] == original_roster for _query, args in checkpoints)
    assert result["unit_roster"] == original_roster
    assert result["unit_research_hold_validation"]["passed"] is True


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
    card = {"unit": "B-52", "engineering_thesis": "A sufficiently detailed legacy engineering thesis.",
            "surprising_fact": "A fact", "source_notes": ["source"]}
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
