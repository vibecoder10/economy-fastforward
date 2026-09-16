import asyncio
import json
import pytest
import sys
import types
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, patch


BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import factual_machine_research as factual
import pipeline_executor as pe
import actions


@pytest.mark.parametrize("status", [432, 433])
def test_source_gather_stops_on_first_tavily_account_limit(status):
    import httpx
    from unittest.mock import AsyncMock
    from error_utils import humanize_error
    executor = object.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-1"
    response = httpx.Response(status, json={"detail": {"error": "Plan limit exceeded"}})
    with patch.object(pe, "get_secret", AsyncMock(return_value="test-key")), \
         patch.object(httpx.AsyncClient, "post", AsyncMock(return_value=response)) as post:
        with pytest.raises(RuntimeError, match="Tavily.*credits") as raised:
            asyncio.run(executor._gather_verified_machine_source_package(
                "Every US Strategic Bomber Ever Built", "Rockwell B-1B Lancer", {},
            ))
    assert post.await_count == 1
    assert "Tavily" in humanize_error(raised.value)
    assert "saved" in humanize_error(raised.value)


MACHINE = "I-49 HMS Argus"


def _candidate(*, text="HMS Argus entered service in 1918.", url="https://example.test/argus"):
    return {
        "excerpt_id": "S1-E1",
        "source_id": "S1",
        "source_title": "HMS Argus record",
        "source_url": url,
        "source_capture_method": "fetched_page",
        "locator": "S1-E1; paragraph 2",
        "text": text,
    }


def _package(*candidates, machine=MACHINE):
    return {
        "passed": False,  # legacy six-excerpt readiness is intentionally irrelevant here
        "machine": machine,
        "machine_key": pe._verified_source_cache_key(machine),
        "candidate_excerpts": list(candidates or [_candidate()]),
    }


def _assessment_client():
    """Return a controlled assessor that grounds its one claim in prompt evidence."""
    async def generate(*, prompt, **_kwargs):
        evidence = json.loads(prompt.split("EVIDENCE:\n", 1)[1])
        candidate = evidence[0]
        return json.dumps({"claims": [{
            "claim": "The cited source records a fact about the locked machine.",
            "scope": "exact locked machine source record",
            "status": "supported",
            "reason": "The supplied excerpt directly names the locked machine.",
            "evidence": [{"excerpt_id": candidate["excerpt_id"], "quote": candidate["text"]}],
            "counterevidence": [],
        }]})
    return SimpleNamespace(generate=AsyncMock(side_effect=generate))


def test_factual_card_copies_only_traceable_exact_machine_excerpts():
    package = _package(
        _candidate(),
        _candidate(text="HMS Eagle entered service in 1924.", url="https://example.test/eagle"),
        {**_candidate(text="HMS Argus had a flush deck."), "source_capture_method": "search_snippet"},
    )

    card = factual.build_factual_evidence_card(MACHINE, package)

    assert card["machine_research_contract"] == factual.FACTUAL_MACHINE_SCRIPT_CONTRACT
    assert [segment["source_excerpt"] for segment in card["evidence_segments"]] == [
        "HMS Argus entered service in 1918.",
    ]
    assert card["evidence_segments"][0]["claim"] == card["evidence_segments"][0]["source_excerpt"]
    assert card["evidence_segments"][0]["numeric_tokens"] == ["1918"]
    assert factual.factual_card_contract_warnings(MACHINE, card, package) == []
    assert pe._research_card_contract_warnings(
        MACHINE, card, package, require_source_package=True,
    ) == []


def test_factual_contract_rejects_wrong_package_identity_and_mutated_claim():
    wrong_package = _package(_candidate(), machine="HMS Eagle")
    assert "identity" in " ".join(factual.factual_package_contract_warnings(MACHINE, wrong_package))

    package = _package(_candidate())
    card = factual.build_factual_evidence_card(MACHINE, package)
    card["evidence_segments"][0]["claim"] = "HMS Argus entered service in 1917."
    warnings = factual.factual_card_contract_warnings(MACHINE, card, package)
    assert any("not an exact fetched excerpt" in warning for warning in warnings)


def test_factual_hold_blocks_wrong_source_before_assessment_or_briefing():
    package = _package(_candidate(text="HMS Eagle entered service in 1924."))
    payload = {
        "machine_script_contract": factual.FACTUAL_MACHINE_SCRIPT_CONTRACT,
        "unit_roster": [MACHINE],
        "machine_raw_source_packages": {pe._verified_source_cache_key(MACHINE): package},
        "unit_research_cards": [],
    }
    executor = object.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-1"
    client = _assessment_client()
    executor._pipeline = SimpleNamespace(anthropic=client)
    executor._load_machine_research_cards = AsyncMock(side_effect=lambda *_args, **_kwargs: payload)
    executor._gather_verified_machine_source_package = AsyncMock(return_value=package)
    executor._checkpoint_machine_raw_source_package = AsyncMock(return_value="UPDATE 1")
    executor._checkpoint_one_machine_research_result = AsyncMock(return_value="UPDATE 1")
    executor._upsert_machine_research_card = AsyncMock()
    executor._log_activity = AsyncMock()
    writer = AsyncMock(side_effect=AssertionError("bad source must stop before briefing"))

    with patch("factual_machine_summary.generate_factual_machine_summary", writer):
        result = asyncio.run(executor._run_unit_research_hold(
            "video-1", "Every British Carrier", payload, [MACHINE], target_machine=MACHINE,
        ))

    assert client.generate.await_count == 0
    assert writer.await_count == 0
    assert result["machine_raw_source_packages"][pe._verified_source_cache_key(MACHINE)]["candidate_excerpts"] == package["candidate_excerpts"]
    assert result["unit_research_hold_validation"]["target_machine_passed"] is False


def test_machine_match_requires_full_distinctive_name_and_prefers_source_diversity():
    assert factual.candidate_mentions_machine("HMS Queen Elizabeth entered service.", "HMS Queen Elizabeth")
    assert not factual.candidate_mentions_machine("HMS Queen Mary entered service in 1918.", "94 HMS Queen Elizabeth (1918)")
    assert not factual.candidate_mentions_machine("RMS Pretoria Castle was a passenger ship.", MACHINE)

    first = _candidate(text="HMS Argus entered service in 1918.")
    same_page = {**_candidate(text="HMS Argus later served as a training ship."), "excerpt_id": "S1-E2"}
    other_page = _candidate(
        text="HMS Argus had a full-length flight deck.", url="https://other.test/argus",
    )
    selected = factual.useful_factual_candidates(MACHINE, _package(first, same_page, other_page))
    assert [row["source_url"] for row in selected[:2]] == [
        "https://example.test/argus", "https://other.test/argus",
    ]


@pytest.mark.parametrize("machine,excerpt", [
    (MACHINE, "HMS Argus entered service in 1918."),
    ("Wittemann-Lewis XNBL-1 Barling Bomber", "The XNBL-1 first flew in 1923."),
    ("North American AJ Savage", "The AJ Savage was designed as a carrier-based bomber."),
])
@pytest.mark.parametrize("kie_receipt", [False, True])
def test_targeted_factual_hold_assesses_small_cached_package_then_reuses_it(machine, excerpt, kie_receipt):
    package = _package(_candidate(text=excerpt), machine=machine)
    if kie_receipt:
        package["source_discovery_requests"] = [
            {"provider": "kie", "model": "gpt-5-2", "request_id": "search-123", "credits_consumed": 0.32},
            {"provider": "kie", "model": "gpt-5-2", "request_id": "search-123", "credits_consumed": 0.32},
            {"provider": "kie", "model": "gpt-5-2", "request_id": "search-124", "credits_consumed": 0.16},
        ]
    from factual_machine_summary import REVIEW_CONTEXT_VERSION
    from machine_research_summary import saved_research_summary
    card = factual.build_factual_evidence_card(machine, package)
    sentence = excerpt
    card["research_summary"] = saved_research_summary(machine, package, {
        "passed": True,
        "paragraph": sentence,
        "claim_map": [{"sentence": sentence, "citations": [{"excerpt_id": "S1-E1"}]}],
        "sources": [{"excerpt_id": "S1-E1", "source_url": "https://example.test/argus"}],
        "review_context_version": REVIEW_CONTEXT_VERSION,
    }, "Every British Carrier")
    locked_roster = [machine] + [f"Pending factual machine {index}" for index in range(2, 21)]
    payload = {
        "machine_script_contract": factual.FACTUAL_MACHINE_SCRIPT_CONTRACT,
        "unit_roster": locked_roster,
        "machine_raw_source_packages": {pe._verified_source_cache_key(machine): package},
        "unit_research_cards": [card],
        "unit_research_hold_validation": {
            "passed": False,
            "units": [
                {"machine": machine, "passed": False, "warnings": ["old Anton warning"]},
                {"machine": "Pending factual machine 2", "passed": False, "warnings": ["missing"]},
            ],
        },
    }
    executor = object.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-1"
    client = _assessment_client()
    executor._pipeline = SimpleNamespace(anthropic=client)
    calls = {"gather": 0, "raw": 0, "card": 0, "upsert": 0}

    async def load_cards(_self, _video_id, current_payload, _roster, target_machine=None):
        return current_payload

    async def gather(_self, _title, _machine, _payload):
        calls["gather"] += 1
        raise AssertionError("valid factual cache should be reused despite legacy passed=False")

    async def checkpoint_raw(_self, *_args):
        calls["raw"] += 1
        return "UPDATE 1"

    async def checkpoint_card(_self, *_args):
        calls["card"] += 1
        return "UPDATE 1"

    async def upsert(_self, *_args):
        calls["upsert"] += 1

    async def log(_self, *_args, **_kwargs):
        return None

    executor._load_machine_research_cards = MethodType(load_cards, executor)
    executor._gather_verified_machine_source_package = MethodType(gather, executor)
    executor._checkpoint_machine_raw_source_package = MethodType(checkpoint_raw, executor)
    executor._checkpoint_one_machine_research_result = MethodType(checkpoint_card, executor)
    executor._upsert_machine_research_card = MethodType(upsert, executor)
    executor._log_activity = MethodType(log, executor)

    generated = {
        "passed": True,
        "paragraph": sentence,
        "claim_map": [{"sentence": sentence, "citations": [{"excerpt_id": "S1-E1"}]}],
        "sources": [{"excerpt_id": "S1-E1", "source_url": "https://example.test/argus"}],
        "review_context_version": REVIEW_CONTEXT_VERSION,
    }
    writer = AsyncMock(return_value=generated)
    with patch("generation_ledger.record_ledger_entry", AsyncMock()) as ledger, \
         patch("factual_machine_summary.generate_factual_machine_summary", writer):
        result = asyncio.run(executor._run_unit_research_hold(
            "video-1", "Every British Carrier", payload, locked_roster, target_machine=machine,
        ))
    assert ledger.await_count == (2 if kie_receipt else 0)
    if kie_receipt:
        assert [call.kwargs["kie_task_id"] for call in ledger.await_args_list] == ["search-123", "search-124"]
        assert ledger.await_args_list[0].kwargs["actual_cost"] == pytest.approx(0.0016)

    assert calls == {"gather": 0, "raw": 2, "card": 1, "upsert": 1}
    assert client.generate.await_count == 1
    assert writer.await_count == 1
    card = pe._research_card_for_machine(result, machine)
    assert card["machine_research_contract"] == factual.FACTUAL_MACHINE_SCRIPT_CONTRACT
    assert result["machine_raw_source_packages"][pe._verified_source_cache_key(machine)]["claim_assessment"]["status"] == "assessed"
    assert card["claim_assessment"]["status"] == "assessed"
    assert result["unit_research_hold_validation"]["target_machine_passed"] is True
    assert result["unit_research_hold_validation"]["passed"] is False
    assert len(result["unit_research_hold_validation"]["units"]) == 20


def test_factual_resume_skips_old_g8_anton_surgical_prepass():
    statuses = []
    holders = []

    class Executor:
        def __init__(self, _tenant_id):
            self.reads = 0
            self.research_calls = 0
            holders.append(self)

        async def _get_video(self, _video_id):
            self.reads += 1
            if self.reads > 1:
                return {"id": "video-1", "status": "ready_for_images", "render_mode": "static_docu"}
            return {
                "status": "idea_logged",
                "render_mode": "static_docu",
                "max_spend": None,
                "total_cost": 0,
                "research_payload": {
                    "machine_script_contract": factual.FACTUAL_MACHINE_SCRIPT_CONTRACT,
                    "unit_roster": [MACHINE],
                    "unit_roster_validation": {"passed": True},
                    "unit_research_hold_validation": {
                        "passed": False,
                        "units": [{"machine": MACHINE, "passed": False}],
                    },
                },
            }

        async def _load_machine_repair_context(self, *_args):
            raise AssertionError("factual resume must not enter old Anton saved-card repair")

        async def run_research(self, _video_id):
            self.research_calls += 1
            return {"status": "ready_for_scripting"}

    fake_pipeline = types.ModuleType("pipeline_executor")
    fake_pipeline.PipelineExecutor = Executor
    fake_routes = types.ModuleType("routes.pipeline")
    fake_routes._set_task_status = lambda _video, status, message, tenant_id=None: statuses.append((status, message))
    fake_routes._clear_task_status = lambda *_args, **_kwargs: None

    async def fetch_one(_query, *_args):
        return None

    async def execute(_query, *_args):
        return "UPDATE 1"

    async def fast_sleep(*_args, **_kwargs):
        return None

    async def no_image_recheck(*_args, **_kwargs):
        return False

    with patch.object(actions, "_static_image_coverage_missing", no_image_recheck), \
         patch.object(actions, "_factual_image_recheck_needed", no_image_recheck), \
         patch.object(actions, "fetch_one", fetch_one), \
         patch.object(actions, "execute", execute), \
         patch.dict(sys.modules, {"pipeline_executor": fake_pipeline, "routes.pipeline": fake_routes}), \
         patch("asyncio.sleep", fast_sleep):
        asyncio.run(actions.make_autobuild_step("tenant-1", "video-1", target="pictures")())

    assert holders[0].research_calls == 1
    assert not any(status == "failed" for status, _message in statuses), statuses


def test_factual_hold_persists_malformed_generator_success_as_failed_summary():
    package = _package(_candidate())
    payload = {
        "machine_script_contract": factual.FACTUAL_MACHINE_SCRIPT_CONTRACT,
        "unit_roster": [MACHINE],
        "machine_raw_source_packages": {pe._verified_source_cache_key(MACHINE): package},
        "unit_research_cards": [],
    }
    executor = object.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-1"
    client = _assessment_client()
    executor._pipeline = SimpleNamespace(anthropic=client)

    async def load_cards(_self, _video_id, current_payload, _roster, target_machine=None):
        return current_payload

    async def checkpoint(*_args):
        return "UPDATE 1"

    async def noop(*_args, **_kwargs):
        return None

    executor._load_machine_research_cards = MethodType(load_cards, executor)
    executor._checkpoint_machine_raw_source_package = MethodType(checkpoint, executor)
    executor._checkpoint_one_machine_research_result = MethodType(checkpoint, executor)
    executor._upsert_machine_research_card = MethodType(noop, executor)
    executor._log_activity = MethodType(noop, executor)

    malformed = {"passed": True, "paragraph": "HMS Argus entered service in 1918.", "claim_map": [], "sources": []}
    with patch("factual_machine_summary.generate_factual_machine_summary", AsyncMock(return_value=malformed)):
        result = asyncio.run(executor._run_unit_research_hold(
            "video-1", "Every British Carrier", payload, [MACHINE], target_machine=MACHINE,
        ))
    saved = pe._research_card_for_machine(result, MACHINE)["research_summary"]
    assert saved["passed"] is False
    assert "claims or citations" in " ".join(saved["warnings"])
    assert client.generate.await_count == 1
    assert result["machine_raw_source_packages"][pe._verified_source_cache_key(MACHINE)]["claim_assessment"]["status"] == "assessed"
    assert result["unit_research_hold_validation"]["passed"] is False


def test_bulk_factual_hold_continues_after_one_transport_failure():
    roster = [MACHINE, "HMS Eagle", "HMS Hermes"]
    payload = {
        "machine_script_contract": factual.FACTUAL_MACHINE_SCRIPT_CONTRACT,
        "unit_roster": roster,
        "machine_raw_source_packages": {},
        "unit_research_cards": [],
    }
    executor = object.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-1"
    async def should_cancel():
        return False

    client = _assessment_client()
    executor._pipeline = SimpleNamespace(anthropic=client, should_cancel=should_cancel)
    attempted = []

    async def get_video(_self, _video_id):
        return {"max_spend": None, "total_cost": 0}

    async def load_cards(_self, _video_id, current_payload, _roster, target_machine=None):
        return current_payload

    async def gather(_self, _title, machine, _payload):
        attempted.append(machine)
        if machine == "HMS Eagle":
            raise TimeoutError("gateway timeout")
        return _package(_candidate(text=f"{machine} entered service in 1918."), machine=machine)

    async def checkpoint(*_args):
        return "UPDATE 1"

    async def noop(*_args, **_kwargs):
        return None

    executor._get_video = MethodType(get_video, executor)
    executor._load_machine_research_cards = MethodType(load_cards, executor)
    executor._gather_verified_machine_source_package = MethodType(gather, executor)
    executor._checkpoint_machine_raw_source_package = MethodType(checkpoint, executor)
    executor._checkpoint_one_machine_research_result = MethodType(checkpoint, executor)
    executor._upsert_machine_research_card = MethodType(noop, executor)
    executor._log_activity = MethodType(noop, executor)

    complete = {
        "passed": True, "paragraph": "A sourced research briefing.",
        "claim_map": [{"sentence": "A sourced research briefing.", "citations": [{"excerpt_id": "S1-E1"}]}],
        "sources": [{"excerpt_id": "S1-E1", "source_url": "https://example.test/argus"}],
    }
    with patch("factual_machine_summary.generate_factual_machine_summary", AsyncMock(return_value=complete)):
        result = asyncio.run(executor._run_unit_research_hold("video-1", "Every British Carrier", payload, roster))
    assert attempted == roster
    assert {card.get("machine") or card.get("unit") for card in result["unit_research_cards"]} == {MACHINE, "HMS Hermes"}
    failed = next(unit for unit in result["unit_research_hold_validation"]["units"] if unit["machine"] == "HMS Eagle")
    assert failed["passed"] is False
    assert "transport failure" in " ".join(failed["warnings"])
    assert client.generate.await_count == 2
    for machine in (MACHINE, "HMS Hermes"):
        assert result["machine_raw_source_packages"][pe._verified_source_cache_key(machine)]["claim_assessment"]["status"] == "assessed"


def test_bulk_factual_hold_stops_after_machine_two_checkpoint_conflict():
    roster = [MACHINE, "HMS Eagle", "HMS Hermes"]
    payload = {"machine_script_contract": factual.FACTUAL_MACHINE_SCRIPT_CONTRACT,
               "unit_roster": roster, "machine_raw_source_packages": {}, "unit_research_cards": []}
    executor = object.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-1"
    async def should_cancel(): return False
    client = _assessment_client()
    executor._pipeline = SimpleNamespace(anthropic=client, should_cancel=should_cancel)
    attempted, raw_checkpoints = [], []
    async def get_video(_self, _video_id): return {"max_spend": None, "total_cost": 0}
    async def load(_self, _video_id, value, _roster, target_machine=None): return value
    async def gather(_self, _title, machine, _payload):
        attempted.append(machine)
        return _package(_candidate(text=f"{machine} entered service in 1918."), machine=machine)
    async def raw_checkpoint(_self, *_args):
        raw_checkpoints.append(1)
        return "UPDATE 0" if len(raw_checkpoints) == 3 else "UPDATE 1"
    async def checkpoint(*_args): return "UPDATE 1"
    async def noop(*_args, **_kwargs): return None
    executor._get_video = MethodType(get_video, executor)
    executor._load_machine_research_cards = MethodType(load, executor)
    executor._gather_verified_machine_source_package = MethodType(gather, executor)
    executor._checkpoint_machine_raw_source_package = MethodType(raw_checkpoint, executor)
    executor._checkpoint_one_machine_research_result = MethodType(checkpoint, executor)
    executor._upsert_machine_research_card = MethodType(noop, executor)
    executor._log_activity = MethodType(noop, executor)
    valid = {"passed": True, "paragraph": "Briefing.",
             "claim_map": [{"sentence": "Briefing.", "citations": [{"excerpt_id": "S1-E1"}]}],
             "sources": [{"excerpt_id": "S1-E1", "source_url": "https://example.test/argus"}]}
    with patch("factual_machine_summary.generate_factual_machine_summary", AsyncMock(return_value=valid)):
        result = asyncio.run(executor._run_unit_research_hold("video-1", "Every British Carrier", payload, roster))
    assert attempted == [MACHINE, "HMS Eagle"]
    assert len(raw_checkpoints) == 3
    assert client.generate.await_count == 1
    assert "checkpoint refused" in " ".join(
        next(unit["warnings"] for unit in result["unit_research_hold_validation"]["units"] if unit["machine"] == "HMS Eagle")
    )


def test_run_unit_research_names_stale_summary_pending_despite_true_verdict(monkeypatch):
    from unittest.mock import AsyncMock
    payload = {"machine_script_contract": factual.FACTUAL_MACHINE_SCRIPT_CONTRACT,
               "unit_roster": [MACHINE], "unit_research_cards": [],
               "unit_research_hold_validation": {"passed": True, "units": [{"machine": MACHINE, "passed": True, "warnings": []}]}}
    video = {"video_title": "Every British Carrier", "status": "idea_logged", "research_payload": payload}
    executor = object.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-1"
    executor._pipeline = SimpleNamespace(should_cancel=AsyncMock(return_value=False))
    async def noop(*_args, **_kwargs): return None
    async def get_video(_self, _video_id): return video
    async def hold(_self, _video_id, _title, value, _roster): return value
    executor._ensure_initialized = MethodType(noop, executor)
    executor._install_cancel_support = MethodType(noop, executor)
    executor._get_video = MethodType(get_video, executor)
    executor._run_unit_research_hold = MethodType(hold, executor)
    executor._log_activity = MethodType(noop, executor)
    monkeypatch.setattr(pe, "_live_roster_gate", lambda *_: {"passed": True})
    monkeypatch.setattr(pe, "_machine_documentary_hold_roster", lambda *_: [MACHINE])
    monkeypatch.setattr(pe, "execute", AsyncMock(return_value="UPDATE 1"))
    monkeypatch.setattr("drive_workspace.sync_video_workspace_fail_soft", AsyncMock())
    result = asyncio.run(executor.run_unit_research("video-1"))
    assert result["status"] == "needs_review"
    assert result["error"] == f"{MACHINE}: factual research summary pending"
    status_save = next(call for call in pe.execute.await_args_list if "status = $2" in call.args[0])
    assert status_save.args[2] == "idea_logged"


def test_aircraft_designation_rejects_shared_nickname_and_nearby_variant():
    assert not factual.candidate_mentions_machine("The B-50 Superfortress flew.", "Boeing B-29 Superfortress")
    assert not factual.candidate_mentions_machine("The B-1A Lancer flew.", "Rockwell B-1B Lancer")
    assert not factual.candidate_mentions_machine("The XNBL-10 prototype flew.", "Wittemann-Lewis XNBL-1 Barling Bomber")
    assert not factual.candidate_mentions_machine("The YB-49 wing flew.", "Northrop YB-35")
    assert factual.candidate_mentions_machine("The P6M SeaMaster was built.", "Martin P6M SeaMaster")
