"""G24a/G24b: cross-press violation memory + writer escalation ladder.

G24a: today's failure mode - both CVA-01 residue entries invented the
number "ten" on every one of 4+ SEPARATE presses, because each press starts
blind. The in-run EDIT loop already carries violations within one press;
nothing carried them ACROSS presses. This persists each failed attempt's
BLOCKING referee warnings per machine (videos.script_validation.
machine_script_attempts.<machine>, bounded to the last 2 attempts, cleared
on pass) and injects the most recent attempt's warnings verbatim into the
next writer prompt.

G24b: after 2 consecutive rejections for the same machine, the next press
escalates to a stronger writer model (reusing the existing provider-
branching precedent, claude_model_for_direct_client) and logs exactly one
line. Same referee, no gate changes.

Both live in _run_static_script_hold's SHARED per-machine loop - the one
function both run_machine_script_block (single-machine) and the bulk hold
loop (target_machine=None) call - so one injection point covers both entry
points. run_machine_script_preview does NOT persist (its own documented
contract is "isolated... without touching production script rows or
status" - see its own regression tests), but it still READS whatever
memory the save/bulk paths wrote.

These tests are local/no-spend (fake Anthropic clients, no real API calls).
"""

import asyncio
import copy
import json

import pipeline_executor as pe


MACHINE = "Boeing XB-15"


# ---------------------------------------------------------------------------
# Shared fixture helpers (same shape as test_machine_documentary_hold.py's
# own - kept local per this test suite's own convention).
# ---------------------------------------------------------------------------

def _evidence_segments() -> list[dict]:
    rows = [
        ("E-PROBLEM", "original_problem", "Original problem claim grounded in the supplied source."),
        ("E-ROLE", "role_category", "Role category claim grounded in the supplied source."),
        ("E-DECISION", "engineering_decision", "Engineering decision claim grounded in the supplied source with wing, engine, tail, nose, and fuselage features."),
        ("E-TRADEOFF", "tradeoff", "Tradeoff claim grounded in the supplied source."),
        ("E-REALITY", "reality", "Reality claim grounded in the supplied source through its Cold War service period."),
        ("E-MEMORABLE", "memorable_fact", "Memorable fact claim grounded in the supplied source."),
    ]
    return [
        {
            "evidence_id": evidence_id, "kind": kind, "claim": claim, "source_excerpt": claim,
            "source_url": f"https://airandspace.si.edu/test/{kind}", "source_title": "Test source",
            "locator": f"S{index}-E1", "numeric_tokens": [], "confidence": "high",
        }
        for index, (evidence_id, kind, claim) in enumerate(rows, start=1)
    ]


def _valid_research_card(machine: str, segments=None) -> dict:
    evidence = segments if segments is not None else _evidence_segments()
    return {
        "unit": machine,
        "engineering_thesis": f"{machine} mattered because its design promise had to survive real operating limits.",
        "why_this_unit_deserves_a_paragraph": (
            f"{machine} deserves a paragraph because its problem exposed a tradeoff between design and reality."
        ),
        "surprising_fact": "Memorable fact claim grounded in the supplied source.",
        "source_notes": [f"{machine}-source"],
        "evidence_segments": evidence,
        "visual_identity": f"{machine} identified by its wing, engine, tail, nose, and fuselage features.",
        "visual_identity_evidence_ids": ["E-DECISION"],
        "timeframe": f"{machine} documented through its Cold War service period.",
        "timeframe_evidence_ids": ["E-REALITY"],
    }


def _verified_package_for_segments(machine: str, segments: list[dict]) -> dict:
    return {
        "passed": True, "machine": machine, "machine_key": pe._normalized_unit_code(machine),
        "search_queries": [f'"{machine}" verified source'],
        "sources": [
            {"source_id": f"S{index}", "title": segment["source_title"], "url": segment["source_url"],
             "text_hash": "test", "text_chars": len(segment["source_excerpt"])}
            for index, segment in enumerate(segments, start=1)
        ],
        "candidate_excerpts": [
            {
                "excerpt_id": f"S{index}-E1", "source_id": f"S{index}", "source_title": segment["source_title"],
                "source_url": segment["source_url"], "locator": segment.get("locator") or f"S{index}-E1",
                "text": f"{machine} {segment['source_excerpt']}", "text_hash": "test",
                "source_capture_method": "fetched_page",
                "source_variant_selection": {
                    "selected_capture_method": "fetched_page",
                    "selected_variant": {"source_capture_method": "fetched_page", "covered_slot_count": 4, "distinct_slot_excerpt_count": 4},
                    "evaluated_variants": [{"source_capture_method": "fetched_page", "covered_slot_count": 4}],
                    "selection_rule": "highest Anton-slot coverage; fetched_page wins exact ties",
                },
            }
            for index, segment in enumerate(segments, start=1)
        ],
    }


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
    ids = [["E-PROBLEM"], ["E-DECISION"], ["E-TRADEOFF"], ["E-REALITY", "E-MEMORABLE"]]
    return json.dumps({
        "editorial_thesis": f"{machine} mattered because its design promise had to survive real operating limits.",
        "twist": {"type": "role_change", "substitute": None, "summary": "Built for the promise, used as the proof."},
        "formula_sentences": sentences,
        "paragraph": " ".join(sentences),
        "claim_map": [
            {"slot": slot, "span": sentence, "used_evidence_ids": evidence_ids}
            for slot, sentence, evidence_ids in zip(
                ["original_problem", "engineering_decision", "tradeoff", "reality"], sentences, ids,
            )
        ],
        "onscreen_label": "",
    })


def _echo_polish_response(prompt: str):
    marker = "SENTENCES (JSON array, one entry per sentence, in order):\n"
    if marker not in prompt:
        return None
    start = prompt.index(marker) + len(marker)
    end = prompt.index("\n\n", start)
    return prompt[start:end]


def _passing_quality_audit() -> dict:
    return {
        "passed": True,
        "checks": [{"name": "validator_warnings", "label": "Validator warnings", "passed": True, "detail": "clean"}],
        "summary": "Anton quality audit passed",
    }


def _video(roster: list[str], script_validation: dict | None = None) -> dict:
    video = {
        "video_title": "Every US Strategic Bomber Ever Built",
        "render_mode": "static_docu",
        "research_payload": {
            "documentary_style": "designed_vs_used",
            "unit_roster": roster,
            "unit_research_cards": [_valid_research_card(machine) for machine in roster],
            "machine_raw_source_packages": {
                pe._verified_source_cache_key(machine): _verified_package_for_segments(machine, _evidence_segments())
                for machine in roster
            },
        },
    }
    if script_validation is not None:
        video["script_validation"] = script_validation
    return video


class RecordingAnthropicClient:
    """Records every call's prompt AND kwargs (model=...) - the escalation
    tests need to see which model id was actually passed."""

    def __init__(self, reply=None):
        self.calls = []
        self._reply = reply

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        echo = _echo_polish_response(kwargs["prompt"])
        if echo is not None:
            return echo
        if self._reply is not None:
            return self._reply
        return _story_bundle(MACHINE, 19)

    @property
    def prompts(self):
        return [call["prompt"] for call in self.calls]


# A fake class literally NAMED AnthropicDirectClient so
# _resolve_escalated_writer_model's type(client).__name__ check resolves the
# SAME branch the real direct-Anthropic path takes (every DVsU carrier-video
# run this whole loop has exercised uses exactly this client type).
class AnthropicDirectClient(RecordingAnthropicClient):
    pass


def _scaffold(monkeypatch, video, fake_anthropic):
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type(
        "FakePipeline", (), {"anthropic": fake_anthropic, "script_system_prompt": "ANTON TENANT SCRIPT CONTRACT"},
    )()
    writes = []

    async def fake_execute(query, *args, **_kwargs):
        writes.append((query, args))
        return None

    async def fake_fetch_all(query, *args, **_kwargs):
        if "script_validation FROM videos" in query:
            existing = video.get("script_validation")
            return [{"script_validation": existing if isinstance(existing, str) else json.dumps(existing or {})}]
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
    return executor, writes


# ---------------------------------------------------------------------------
# Pure-function unit tests (no I/O) - fast, precise.
# ---------------------------------------------------------------------------

def test_machine_script_attempt_state_reads_from_script_validation():
    video = _video([MACHINE], script_validation=json.dumps({
        "machine_script_attempts": {
            MACHINE: {"recent_blocking_warnings": [["claim_map row 4 introduced unsupported numerical detail(s): ten"]], "consecutive_rejections": 1},
        },
    }))
    state = pe._machine_script_attempt_state(video, MACHINE)
    assert state["consecutive_rejections"] == 1
    assert state["recent_blocking_warnings"] == [["claim_map row 4 introduced unsupported numerical detail(s): ten"]]

    # No entry at all -> {}, not an error.
    assert pe._machine_script_attempt_state(_video([MACHINE]), MACHINE) == {}
    assert pe._machine_script_attempt_state(_video([MACHINE]), "Some Other Machine") == {}


def test_violation_memory_prompt_block_names_warnings_verbatim():
    state = {"recent_blocking_warnings": [
        ["claim_map row 4 introduced unsupported numerical detail(s): ten"],
    ]}
    block = pe._violation_memory_prompt_block(state)
    assert "YOUR PREVIOUS DRAFT WAS REJECTED FOR:" in block
    assert "claim_map row 4 introduced unsupported numerical detail(s): ten" in block
    assert "Do not repeat these mistakes" in block


def test_violation_memory_prompt_block_empty_when_nothing_recorded():
    assert pe._violation_memory_prompt_block({}) == ""
    assert pe._violation_memory_prompt_block({"recent_blocking_warnings": []}) == ""


def test_violation_memory_prompt_block_bounded_to_last_two_attempts():
    state = {"recent_blocking_warnings": [
        ["attempt 1 violation"], ["attempt 2 violation"], ["attempt 3 violation"],
    ]}
    block = pe._violation_memory_prompt_block(state)
    # The helper's own slice is defensive (the persist function is what
    # actually enforces the bound on write) - either way, "attempt 1" must
    # never surface once 3+ have been recorded.
    assert "attempt 1 violation" not in block
    assert "attempt 2 violation" in block
    assert "attempt 3 violation" in block


def test_resolve_escalated_writer_model_for_anthropic_direct_client():
    from orchestrator.pipeline_constants import Models
    model = pe._resolve_escalated_writer_model(AnthropicDirectClient())
    assert model == Models.CLAUDE_OPUS


def test_resolve_escalated_writer_model_for_kie_wrapped_client():
    from shared.channel_profile import CLAUDE_MODELS

    class SomeKieClient:
        pass

    model = pe._resolve_escalated_writer_model(SomeKieClient())
    assert model == CLAUDE_MODELS["kie"]["smart"]


# ---------------------------------------------------------------------------
# _persist_machine_script_attempt_state: the async DB read-modify-write.
# ---------------------------------------------------------------------------

def test_persist_attempt_state_records_blocking_warnings_on_fail(monkeypatch):
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    stored = {"script_validation": json.dumps({})}
    writes = []

    async def fake_fetch_all(query, *_args):
        return [{"script_validation": stored["script_validation"]}]

    async def fake_execute(query, *args):
        writes.append((query, args))
        stored["script_validation"] = args[0]

    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(pe, "execute", fake_execute)

    asyncio.run(executor._persist_machine_script_attempt_state(
        "video-test", MACHINE, ["claim_map row 4 introduced unsupported numerical detail(s): ten"], False,
    ))

    validation = json.loads(stored["script_validation"])
    entry = validation["machine_script_attempts"][MACHINE]
    assert entry["consecutive_rejections"] == 1
    assert entry["recent_blocking_warnings"] == [["claim_map row 4 introduced unsupported numerical detail(s): ten"]]


def test_persist_attempt_state_clears_on_pass(monkeypatch):
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    stored = {"script_validation": json.dumps({
        "machine_script_attempts": {
            MACHINE: {"recent_blocking_warnings": [["invented ten"]], "consecutive_rejections": 2},
        },
    })}

    async def fake_fetch_all(query, *_args):
        return [{"script_validation": stored["script_validation"]}]

    async def fake_execute(query, *args):
        stored["script_validation"] = args[0]

    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(pe, "execute", fake_execute)

    asyncio.run(executor._persist_machine_script_attempt_state("video-test", MACHINE, [], True))

    validation = json.loads(stored["script_validation"])
    assert MACHINE not in validation.get("machine_script_attempts", {})


def test_persist_attempt_state_bounds_to_last_two_attempts(monkeypatch):
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    stored = {"script_validation": json.dumps({
        "machine_script_attempts": {
            MACHINE: {"recent_blocking_warnings": [["attempt 1"], ["attempt 2"]], "consecutive_rejections": 2},
        },
    })}

    async def fake_fetch_all(query, *_args):
        return [{"script_validation": stored["script_validation"]}]

    async def fake_execute(query, *args):
        stored["script_validation"] = args[0]

    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(pe, "execute", fake_execute)

    asyncio.run(executor._persist_machine_script_attempt_state("video-test", MACHINE, ["attempt 3"], False))

    entry = json.loads(stored["script_validation"])["machine_script_attempts"][MACHINE]
    assert entry["recent_blocking_warnings"] == [["attempt 2"], ["attempt 3"]]
    assert entry["consecutive_rejections"] == 3


# ---------------------------------------------------------------------------
# End-to-end: the injection actually reaches the real writer prompt, on
# BOTH entry points that share _run_static_script_hold's per-machine loop.
# ---------------------------------------------------------------------------

def test_single_machine_press_injects_violation_memory_and_escalates(monkeypatch, caplog):
    """(1) verbatim injection; (4) escalation resolves + logs after 2
    consecutive rejections; (6) single-machine entry point (run_machine_
    script_block's own path: target_machine + save_target_script) gets it."""
    roster = [MACHINE]
    prior_warning = "claim_map row 4 introduced unsupported numerical detail(s): ten"
    video = _video(roster, script_validation=json.dumps({
        "machine_script_attempts": {
            MACHINE: {"recent_blocking_warnings": [[prior_warning]], "consecutive_rejections": 2},
        },
    }))
    fake_anthropic = AnthropicDirectClient()
    executor, writes = _scaffold(monkeypatch, video, fake_anthropic)

    import logging
    with caplog.at_level(logging.WARNING, logger="pipeline_executor"):
        result = asyncio.run(
            executor._run_static_script_hold(
                "video-test", video, roster, target_machine=MACHINE, save_target_script=True,
            )
        )

    assert result["status"] == "completed"
    # Injection reached the REAL first-pass write prompt, verbatim.
    first_write_prompt = fake_anthropic.prompts[0]
    assert "YOUR PREVIOUS DRAFT WAS REJECTED FOR:" in first_write_prompt
    assert prior_warning in first_write_prompt

    # Escalation: 2 consecutive rejections recorded -> this press's writer
    # calls use the escalated model.
    from orchestrator.pipeline_constants import Models
    assert fake_anthropic.calls[0].get("model") == Models.CLAUDE_OPUS
    escalation_lines = [r.message for r in caplog.records if r.message.startswith("[script]")]
    assert any(
        f"machine={MACHINE}" in msg and f"escalated_model={Models.CLAUDE_OPUS}" in msg and "reason=two_rejections" in msg
        for msg in escalation_lines
    ), escalation_lines


def test_bulk_hold_loop_injects_violation_memory_for_same_machine(monkeypatch):
    """(6) the bulk _run_static_script_hold loop (target_machine=None) gets
    the SAME injection - proof that both entry points share one code path."""
    roster = [MACHINE]
    prior_warning = "claim_map row 4 introduced unsupported numerical detail(s): ten"
    video = _video(roster, script_validation=json.dumps({
        "machine_script_attempts": {
            MACHINE: {"recent_blocking_warnings": [[prior_warning]], "consecutive_rejections": 0},
        },
    }))
    fake_anthropic = RecordingAnthropicClient()
    executor, writes = _scaffold(monkeypatch, video, fake_anthropic)

    result = asyncio.run(executor._run_static_script_hold("video-test", video, roster))

    assert result["status"] == "ready_for_voice"
    assert "YOUR PREVIOUS DRAFT WAS REJECTED FOR:" in fake_anthropic.prompts[0]
    assert prior_warning in fake_anthropic.prompts[0]
    # 0 consecutive rejections recorded - no escalation this press.
    assert "model" not in fake_anthropic.calls[0]


def test_pass_clears_attempt_memory_end_to_end(monkeypatch):
    """(2) warnings cleared on pass; (5) counter resets on pass - proven
    through the real save path, not just the persist helper directly."""
    roster = [MACHINE]
    video = _video(roster, script_validation=json.dumps({
        "machine_script_attempts": {
            MACHINE: {"recent_blocking_warnings": [["some prior violation"]], "consecutive_rejections": 1},
        },
    }))
    fake_anthropic = RecordingAnthropicClient()
    executor, writes = _scaffold(monkeypatch, video, fake_anthropic)

    result = asyncio.run(
        executor._run_static_script_hold(
            "video-test", video, roster, target_machine=MACHINE, save_target_script=True,
        )
    )

    assert result["status"] == "completed"
    assert result["script_block"]["passed"] is True
    # The clearing write happened AFTER _save_machine_script_block's own
    # write - find the LAST script_validation write and confirm it has no
    # entry for this machine.
    validation_writes = [
        json.loads(args[0]) for query, args in writes
        if "UPDATE videos SET script_validation" in query and args and isinstance(args[0], str)
    ]
    assert validation_writes, "no script_validation write observed"
    last_validation = validation_writes[-1]
    assert MACHINE not in last_validation.get("machine_script_attempts", {})
