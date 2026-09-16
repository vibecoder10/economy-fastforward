"""Offline integration coverage for assessed script-packet generation.

The client is a queue-only fake: these tests prove the bounded compiler path
without reaching a provider.
"""
import copy
import json
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import factual_machine_summary as summary
import factual_machine_pipeline as fp
import pipeline_executor as pe
import script_research_packet as packet_module
from research_claim_assessment import _assessed_receipt, _validated_claims


MACHINE = "SS-1 USS Holland"
OTHER_MACHINE = "SS-2 USS Plunger"
SUBJECT = "Every US Submarine Class Ever Built"
URL = "https://navy.example/holland"


class FakeClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _package():
    identity = "SS-1 USS Holland was the first commissioned submarine in the United States Navy."
    design = "SS-1 USS Holland used a gasoline engine for surface running and electric motors underwater."
    service = "SS-1 USS Holland served as a training vessel after commissioning in 1900."
    package = {
        "machine": MACHINE,
        "machine_key": "SS1",
        "sources": [{"source_id": "N1", "url": URL, "title": "Navy history"}],
        "candidate_excerpts": [
            {"excerpt_id": "E1", "source_id": "N1", "source_url": URL, "source_title": "Navy history",
             "source_tier": 1, "locator": "E1", "source_capture_method": "fetched_page", "text": identity},
            {"excerpt_id": "E2", "source_id": "N1", "source_url": URL, "source_title": "Navy history",
             "source_tier": 1, "locator": "E2", "source_capture_method": "fetched_page", "text": design},
            {"excerpt_id": "E3", "source_id": "N1", "source_url": URL, "source_title": "Navy history",
             "source_tier": 1, "locator": "E3", "source_capture_method": "fetched_page", "text": service},
        ],
    }
    claims = [
        {"id": "C1", "claim": "SS-1 USS Holland was the first commissioned submarine in the United States Navy.",
         "scope": "identity", "status": "supported", "reason": "exact", "evidence": [{"excerpt_id": "E1", "quote": identity}], "counterevidence": []},
        {"id": "C2", "claim": "SS-1 USS Holland used gasoline and electric propulsion.",
         "scope": "design", "status": "supported", "reason": "exact", "evidence": [{"excerpt_id": "E2", "quote": design}], "counterevidence": []},
        {"id": "C3", "claim": "SS-1 USS Holland served as a training vessel after commissioning in 1900.",
         "scope": "service", "status": "supported", "reason": "exact", "evidence": [{"excerpt_id": "E3", "quote": service}], "counterevidence": []},
        {"id": "C4", "claim": "SS-1 USS Holland was sunk in battle.", "scope": "outcome", "status": "insufficient",
         "reason": "no source", "evidence": [], "counterevidence": []},
    ]
    # Store the same normalized receipt shape produced by the assessor; the
    # packet compiler must only accept this current, traceable ledger.
    package["claim_assessment"] = _assessed_receipt(
        MACHINE, package, SUBJECT,
        _validated_claims(claims, summary._eligible_candidates(MACHINE, package, SUBJECT)),
    )
    return package


def _writer_response(fact_ids):
    sentence = "SS-1 USS Holland was the first commissioned submarine in the United States Navy."
    return json.dumps({"paragraph": sentence, "claim_map": [{"sentence": sentence, "fact_ids": [fact_ids[0]]}]})


def _fact_for_sentence(compiled):
    return next(row for row in compiled["facts"] if "first commissioned submarine" in row["claim"])


@pytest.fixture
def assessed_pipeline_state(monkeypatch):
    package = _package()
    video = {"video_title": SUBJECT, "status": "ready_for_scripting", "max_spend": None,
             "research_payload": {"machine_script_contract": fp.CONTRACT, "unit_roster": [MACHINE]},
             "script_validation": {}}
    ex = SimpleNamespace(tenant_id="tenant", _pipeline=SimpleNamespace(anthropic=object(), should_cancel=AsyncMock(return_value=False)))
    ex._get_video = AsyncMock(side_effect=lambda _video_id: copy.deepcopy(video))
    ex._log_activity = AsyncMock(); ex._log_transition = AsyncMock()
    ex._skip_disabled_next = lambda _video, status: status
    ex._db_write_missed = pe.PipelineExecutor._db_write_missed
    ex._run_unit_research_hold = None

    async def checkpoint(_video_id, key, block, _snapshot):
        video["research_payload"].setdefault("machine_script_previews", {})[key] = copy.deepcopy(block)
        return "UPDATE 1"
    async def save(**kwargs):
        block = {**kwargs["script_block"], "saved": True}
        video["script_validation"] = {"machine_script_blocks": {MACHINE: block}, "script_hold": {"passed": True, "completed_count": 1}}
        video["script"] = block["paragraph"]
        return block
    ex._checkpoint_machine_script_preview = AsyncMock(side_effect=checkpoint)
    ex._save_machine_script_block = AsyncMock(side_effect=save)
    monkeypatch.setattr(pe, "fetch_all", AsyncMock(return_value=[]))
    monkeypatch.setattr(pe, "execute", AsyncMock(return_value="UPDATE 1"))
    monkeypatch.setattr(pe, "_machine_documentary_hold_roster", lambda _video: [MACHINE])
    monkeypatch.setattr(pe, "_verified_source_package_for_machine", lambda *_args: package)
    return ex, video, package


def _compiled_block(package, *, paragraph="SS-1 USS Holland was the first commissioned submarine in the United States Navy.", passed=True, warnings=None):
    packet = fp._expected_script_packet(MACHINE, package, SUBJECT, [{"scene": 1, "machine": MACHINE}], "")
    fact = _fact_for_sentence(packet)
    return {"passed": passed, "paragraph": paragraph, "word_count": len(paragraph.split()),
            "warnings": list(warnings or []), "claim_map": [{"sentence": paragraph, "fact_ids": [fact["fact_id"]], "citations": fact["evidence"]}],
            "sources": fact["evidence"], "review_context_version": summary.REVIEW_CONTEXT_VERSION,
            "subject_context": SUBJECT, "compiler_version": packet["compiler_version"],
            "packet_fingerprint": packet["packet_fingerprint"], "selected_fact_ids": [x["fact_id"] for x in packet["facts"]],
            "script_packet_receipt": {"compiler_version": packet["compiler_version"], "packet_fingerprint": packet["packet_fingerprint"]}}


@pytest.mark.asyncio
async def test_assessed_writer_locks_fact_ids_and_runs_independent_referee():
    package = _package()
    client = FakeClient(_writer_response(["ignored"]), json.dumps({"passed": True, "issues": []}))
    # Substitute the selected ID after compilation to retain a fake provider
    # response while exercising the full writer -> materializer -> referee path.
    from factual_machine_summary import _eligible_candidates
    from script_research_packet import compile_script_packet
    compiled = compile_script_packet(MACHINE, package, package["claim_assessment"],
        _eligible_candidates(MACHINE, package, SUBJECT), subject_context=SUBJECT,
        episode_outline=[{"scene": 1, "machine": MACHINE}, {"scene": 2, "machine": OTHER_MACHINE}],
        current_briefing="Holland opened the American submarine story.", model=summary._model_name())
    identity_fact = _fact_for_sentence(compiled)
    client.responses[0] = _writer_response([identity_fact["fact_id"]])
    result = await summary.generate_factual_machine_summary(MACHINE, package, client, subject_context=SUBJECT,
        episode_outline=compiled["outline"], current_briefing=compiled["current_briefing"], script_packet=compiled,
        research_briefings=[{"machine": OTHER_MACHINE, "paragraph": "SECRET OTHER-MACHINE RESEARCH DETAIL"}])
    assert result["passed"] is True
    assert result["claim_map"][0]["fact_ids"] == [identity_fact["fact_id"]]
    quote = result["claim_map"][0]["citations"][0]["quote"]
    assert any(quote in row["text"] for row in package["candidate_excerpts"])
    assert result["packet_fingerprint"] == compiled["packet_fingerprint"]
    assert len(client.calls) == 2
    assert "SECRET OTHER-MACHINE RESEARCH DETAIL" not in client.calls[0]["prompt"]
    assert "candidate_excerpts" not in client.calls[0]["prompt"]
    assert "SCRIPT PACKET" in client.calls[1]["prompt"]
    assert "SECRET OTHER-MACHINE RESEARCH DETAIL" not in client.calls[1]["prompt"]


@pytest.mark.asyncio
async def test_unknown_fact_ids_are_blocked_before_referee():
    package = _package()
    bad = json.dumps({"paragraph": "SS-1 USS Holland was first.", "claim_map": [{"sentence": "SS-1 USS Holland was first.", "fact_ids": ["F-not-selected"]}]})
    client = FakeClient(bad, bad)
    result = await summary.generate_factual_machine_summary(MACHINE, package, client, subject_context=SUBJECT)
    assert result["passed"] is False
    assert any("unknown or missing fact ID" in warning for warning in result["warnings"])
    # Two bounded writer attempts, never a referee call.
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_writer_and_referee_budget_failures_do_not_call_provider(monkeypatch):
    package = _package()
    client = FakeClient()
    monkeypatch.setattr(packet_module, "MAX_INPUT_TOKEN_UPPER_BOUND", 1)
    writer = await summary.generate_factual_machine_summary(MACHINE, package, client, subject_context=SUBJECT)
    assert writer["passed"] is False
    assert client.calls == []

    # Compile after lowering the budget so packet identity remains current;
    # only the referee preflight may then reject it.
    from factual_machine_summary import _eligible_candidates
    from script_research_packet import compile_script_packet
    monkeypatch.setattr(packet_module, "MAX_INPUT_TOKEN_UPPER_BOUND", 1)
    compiled = compile_script_packet(MACHINE, package, package["claim_assessment"],
        _eligible_candidates(MACHINE, package, SUBJECT), subject_context=SUBJECT, model=summary._model_name())
    raw = _writer_response([_fact_for_sentence(compiled)["fact_id"]])
    reviewed = await summary.review_existing_factual_summary(MACHINE, package, client, raw,
        subject_context=SUBJECT, script_packet=compiled)
    assert reviewed["passed"] is False
    assert any("conservative model input budget" in warning for warning in reviewed["warnings"])
    assert client.calls == []


@pytest.mark.asyncio
async def test_rejected_referee_section_never_passes_and_retains_packet_receipt():
    package = _package()
    from factual_machine_summary import _eligible_candidates
    from script_research_packet import compile_script_packet
    compiled = compile_script_packet(MACHINE, package, package["claim_assessment"],
        _eligible_candidates(MACHINE, package, SUBJECT), subject_context=SUBJECT, model=summary._model_name())
    client = FakeClient(
        _writer_response([compiled["facts"][0]["fact_id"]]),
        json.dumps({"passed": False, "issues": ["unselected claim"], "rejected_sentences": []}),
        _writer_response([compiled["facts"][0]["fact_id"]]),
        json.dumps({"passed": False, "issues": ["unselected claim"], "rejected_sentences": []}),
    )
    result = await summary.generate_factual_machine_summary(MACHINE, package, client, subject_context=SUBJECT,
        script_packet=compiled)
    assert result["passed"] is False
    assert result["packet_fingerprint"] == compiled["packet_fingerprint"]
    assert len(client.calls) == 4


def test_compiler_referee_deduplicates_repeated_citation_registry_without_mutation():
    package = _package()
    candidate = package["candidate_excerpts"][0]
    citation = {"excerpt_id": candidate["excerpt_id"], "quote": candidate["text"],
                "source_url": candidate["source_url"], "source_title": candidate["source_title"],
                "locator": candidate["locator"]}
    draft = {"paragraph": "One. Two.", "claim_map": [
        {"sentence": "One.", "citations": [citation]},
        {"sentence": "Two.", "citations": [copy.deepcopy(citation)]},
    ]}
    original = copy.deepcopy(draft)
    prompt = summary._review_prompt(MACHINE, draft, [candidate], SUBJECT, package["claim_assessment"], {"facts": []})
    review_packet = json.loads(prompt.split("REVIEW PACKET:\n", 1)[1])
    registry = review_packet["citation_evidence_registry"]
    refs = review_packet["draft_with_locked_provenance"]["claim_map"]
    assert len(registry) == 1
    assert refs[0]["citations"] == refs[1]["citations"]
    assert refs[0]["citations"][0]["evidence_id"] == registry[0]["evidence_id"]
    assert review_packet["relevant_alternate_fetched_context"] == [candidate]
    assert draft == original


def _stored(block, package):
    return {**block, "machine": MACHINE, "scene": 1, "machine_script_contract": fp.CONTRACT,
            "source_fingerprint": fp.source_fingerprint(MACHINE, package), "saved": True}


def test_legacy_assessed_saved_block_without_packet_fingerprint_regenerates(assessed_pipeline_state, monkeypatch):
    ex, video, package = assessed_pipeline_state
    legacy = _stored(_compiled_block(package, paragraph=" ".join(["legacy"] * 80)), package)
    legacy.pop("packet_fingerprint"); legacy.pop("compiler_version")
    video["script_validation"] = {"machine_script_blocks": {MACHINE: legacy}}
    writer = AsyncMock(return_value=_compiled_block(package))
    monkeypatch.setattr(summary, "generate_factual_machine_summary", writer)
    result = asyncio.run(fp.run_factual_script_hold(ex, "video", video, [MACHINE]))
    assert result["status"] == "completed"
    writer.assert_awaited_once()
    saved = video["script_validation"]["machine_script_blocks"][MACHINE]
    assert saved["packet_fingerprint"] == fp._expected_script_packet(MACHINE, package, SUBJECT, [{"scene": 1, "machine": MACHINE}], "")["packet_fingerprint"]


def test_matching_passed_preview_promotes_and_reuses_without_provider(assessed_pipeline_state, monkeypatch):
    ex, video, package = assessed_pipeline_state
    preview = _stored(_compiled_block(package), package)
    video["research_payload"]["machine_script_previews"] = {pe._verified_source_cache_key(MACHINE): preview}
    writer = AsyncMock(); reviewer = AsyncMock()
    monkeypatch.setattr(summary, "generate_factual_machine_summary", writer)
    monkeypatch.setattr(summary, "review_existing_factual_summary", reviewer)
    first = asyncio.run(fp.run_factual_script_hold(ex, "video", video, [MACHINE]))
    assert first["status"] == "completed"
    writer.assert_not_awaited(); reviewer.assert_not_awaited()
    assert ex._save_machine_script_block.await_count == 1
    again = asyncio.run(fp.run_factual_script_hold(ex, "video", video, [MACHINE]))
    assert again["status"] == "completed"
    writer.assert_not_awaited(); reviewer.assert_not_awaited()


def test_matching_failed_preview_is_writer_repair_input_over_old_saved(assessed_pipeline_state, monkeypatch):
    ex, video, package = assessed_pipeline_state
    old = _stored(_compiled_block(package, paragraph=" ".join(["old"] * 80)), package)
    old["packet_fingerprint"] = "older-packet"
    failed = _stored(_compiled_block(package, paragraph="Preview repair prose.", passed=False, warnings=["preview warning"]), package)
    video["script_validation"] = {"machine_script_blocks": {MACHINE: old}}
    video["research_payload"]["machine_script_previews"] = {pe._verified_source_cache_key(MACHINE): failed}
    writer = AsyncMock(return_value=_compiled_block(package))
    monkeypatch.setattr(summary, "generate_factual_machine_summary", writer)
    result = asyncio.run(fp.run_factual_script_hold(ex, "video", video, [MACHINE]))
    assert result["status"] == "completed"
    previous = writer.await_args.kwargs["previous_summary"]
    assert previous["paragraph"] == "Preview repair prose."
    assert previous["warnings"] == ["preview warning"]


def test_current_accepted_saved_block_wins_over_failed_preview_without_provider(assessed_pipeline_state, monkeypatch):
    ex, video, package = assessed_pipeline_state
    saved = _stored(_compiled_block(package), package)
    failed = _stored(_compiled_block(package, paragraph="Newer preview failure.", passed=False, warnings=["preview warning"]), package)
    video["script_validation"] = {"machine_script_blocks": {MACHINE: saved}}
    video["research_payload"]["machine_script_previews"] = {pe._verified_source_cache_key(MACHINE): failed}
    writer = AsyncMock(); reviewer = AsyncMock()
    monkeypatch.setattr(summary, "generate_factual_machine_summary", writer)
    monkeypatch.setattr(summary, "review_existing_factual_summary", reviewer)
    result = asyncio.run(fp.run_factual_script_hold(ex, "video", video, [MACHINE]))
    assert result["status"] == "completed"
    writer.assert_not_awaited(); reviewer.assert_not_awaited()


def test_model_change_invalidates_compiled_saved_block(assessed_pipeline_state, monkeypatch):
    ex, video, package = assessed_pipeline_state
    video["script_validation"] = {"machine_script_blocks": {MACHINE: _stored(_compiled_block(package), package)}}
    monkeypatch.setenv("CLAUDE_OPUS_MODEL", "different-test-model")
    assert fp.factual_script_readiness(video, [MACHINE]) is False
    writer = AsyncMock(return_value=_compiled_block(package))
    monkeypatch.setattr(summary, "generate_factual_machine_summary", writer)
    result = asyncio.run(fp.run_factual_script_hold(ex, "video", video, [MACHINE]))
    assert result["status"] == "completed"
    writer.assert_awaited_once()
