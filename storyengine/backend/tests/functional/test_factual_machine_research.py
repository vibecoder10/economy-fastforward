import asyncio
import pytest
import sys
import types
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import patch


BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import factual_machine_research as factual
import pipeline_executor as pe
import actions


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
def test_targeted_factual_hold_reuses_small_cached_package_without_anthropic(machine, excerpt):
    package = _package(_candidate(text=excerpt), machine=machine)
    payload = {
        "machine_script_contract": factual.FACTUAL_MACHINE_SCRIPT_CONTRACT,
        "unit_roster": [machine, "HMS Eagle"],
        "machine_raw_source_packages": {pe._verified_source_cache_key(machine): package},
        "unit_research_hold_validation": {
            "passed": False,
            "units": [
                {"machine": machine, "passed": False, "warnings": ["old Anton warning"]},
                {"machine": "HMS Eagle", "passed": False, "warnings": ["missing"]},
            ],
        },
    }
    executor = object.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-1"
    executor._pipeline = SimpleNamespace(anthropic=None)
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

    result = asyncio.run(executor._run_unit_research_hold(
        "video-1", "Every British Carrier", payload, payload["unit_roster"], target_machine=machine,
    ))

    assert calls == {"gather": 0, "raw": 1, "card": 1, "upsert": 1}
    card = pe._research_card_for_machine(result, machine)
    assert card["machine_research_contract"] == factual.FACTUAL_MACHINE_SCRIPT_CONTRACT
    assert result["unit_research_hold_validation"]["target_machine_passed"] is True
    assert result["unit_research_hold_validation"]["passed"] is False


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
                return {"status": "ready_for_images", "render_mode": "static_docu"}
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

    with patch.object(actions, "fetch_one", fetch_one), \
         patch.object(actions, "execute", execute), \
         patch.dict(sys.modules, {"pipeline_executor": fake_pipeline, "routes.pipeline": fake_routes}), \
         patch("asyncio.sleep", fast_sleep):
        asyncio.run(actions.make_autobuild_step("tenant-1", "video-1", target="pictures")())

    assert holders[0].research_calls == 1
    assert not any(status == "failed" for status, _message in statuses)


def test_aircraft_designation_rejects_shared_nickname_and_nearby_variant():
    assert not factual.candidate_mentions_machine("The B-50 Superfortress flew.", "Boeing B-29 Superfortress")
    assert not factual.candidate_mentions_machine("The B-1A Lancer flew.", "Rockwell B-1B Lancer")
    assert not factual.candidate_mentions_machine("The XNBL-10 prototype flew.", "Wittemann-Lewis XNBL-1 Barling Bomber")
    assert not factual.candidate_mentions_machine("The YB-49 wing flew.", "Northrop YB-35")
    assert factual.candidate_mentions_machine("The P6M SeaMaster was built.", "Martin P6M SeaMaster")
