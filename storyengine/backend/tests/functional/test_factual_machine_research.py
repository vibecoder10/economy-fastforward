import asyncio
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


def test_factual_hold_guard_stops_before_any_provider_work_when_roster_changed():
    """The pre-flight guard re-reads the persisted roster; if it no longer
    matches the locked one, no provider call or checkpoint may happen.

    (This replaces the pre-v2 "wrong source blocks before assessment" test:
    Call 3 packages are built by dvsu_research_v2's adapter with the exact
    machine identity, and package-identity mismatches are covered by
    test_factual_contract_rejects_wrong_package_identity_and_mutated_claim.
    The old version only passed because the un-stubbed `_get_video` hit the
    database and failed.)"""
    executor, payload = _hold_case([MACHINE])
    moved_on = {"id": "video-1", "status": "idea_logged", "render_mode": "static_docu", "max_spend": None,
                "total_cost": 0, "research_payload": dict(
                    payload, unit_roster=[{"machine": "HMS Eagle", "act_number": 1}])}
    executor._get_video = AsyncMock(return_value=moved_on)
    runner = _packet_runner()

    with patch("dvsu_research_v2.run_machine_research_packet", runner):
        result = asyncio.run(executor._run_unit_research_hold(
            "video-1", TITLE, payload, [MACHINE], target_machine=MACHINE,
        ))

    runner.assert_not_awaited()
    executor._checkpoint_machine_raw_source_package.assert_not_awaited()
    executor._checkpoint_one_machine_research_result.assert_not_awaited()
    executor._upsert_machine_research_card.assert_not_awaited()
    assert result["machine_raw_source_packages"] == {}
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


# --- DVSU research v2 (Call 3) hold fixtures --------------------------------
# The target-machine path of `_run_unit_research_hold` no longer gathers
# Kie/Tavily sources, runs a claim-assessment model call or asks the summary
# writer (65545d8e, see dvsu_research_v2.py): it runs one Call-3 research packet
# and mechanically adapts it into the legacy card/package shapes. These
# fixtures fake only that one provider seam (`run_machine_research_packet`).

TITLE = "Every British Carrier"


@pytest.fixture(autouse=True)
def _no_cancel_registry(monkeypatch):
    monkeypatch.setattr("cancel_registry.is_cancel_requested", AsyncMock(return_value=False))


def _call3_packet(machine, *, act_number=1):
    """A complete Call-3 packet: the six search-grounded answers for one machine."""
    def slot(name, text, quote):
        return {"answer": text, "source_url": f"https://example.navy.mil/{name}", "quote": quote}
    return {
        "machine": machine, "act_number": act_number,
        "problem": slot("problem", "The Navy needed a vessel that could operate aircraft at sea.",
                        "The Navy needed a ship that could launch and recover aircraft at sea."),
        "design": slot("design", "The design used a full-length flight deck.",
                       "A full-length flight deck ran the whole length of the hull."),
        "trade_off": slot("tradeoff", "The flight deck reduced the armament that could be carried.",
                          "Carrying a flight deck cost the design most of its heavy armament."),
        "outcome_candidates": [
            {"fact": "The design entered service in wartime.",
             "source_url": "https://example.navy.mil/outcome1",
             "quote": "The design entered service during the war and flew combat patrols."},
            {"fact": "The design was retired after the conflict.",
             "source_url": "https://example.navy.mil/outcome2",
             "quote": "After the conflict the design was retired and sold for scrap."},
        ],
        "surprising_fact": slot("surprise", "Aircraft landed on it before the deck was finished.",
                                "Aircraft landed on the unfinished deck during early trials."),
        "contrast": slot("contrast", "A later carrier design replaced it entirely.",
                         "A later carrier design replaced it in the fleet entirely."),
    }


def _packet_runner(*, failing=(), packet=None):
    """Fake `run_machine_research_packet`: a complete packet per machine, or a
    transport failure for the machines named in `failing`."""
    async def run(_client, machine, act_number, _title, _shared_context, checkpoint_scope=None):
        if machine in failing:
            raise TimeoutError("gateway timeout")
        return packet(machine) if packet else _call3_packet(machine, act_number=act_number)
    return AsyncMock(side_effect=run)


def _hold_case(roster, *, raw_checkpoint=None):
    """An executor plus locked static-docu factual payload for `_run_unit_research_hold`."""
    payload = {
        "machine_script_contract": factual.FACTUAL_MACHINE_SCRIPT_CONTRACT,
        "machine_discovery_buckets": {},  # static-docu machine marker
        "unit_roster": [{"machine": name, "act_number": index} for index, name in enumerate(roster, start=1)],
        "shared_context": [],
        "machine_raw_source_packages": {},
        "unit_research_cards": [],
    }
    video = {"id": "video-1", "status": "idea_logged", "video_title": TITLE,
             "render_mode": "static_docu", "max_spend": None, "total_cost": 0}
    executor = object.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-1"
    executor._pipeline = SimpleNamespace(anthropic=None, should_cancel=AsyncMock(return_value=False))
    executor._get_video = AsyncMock(side_effect=lambda _video_id: dict(video, research_payload=dict(payload)))
    executor._load_machine_research_cards = AsyncMock(side_effect=lambda _video_id, current, _roster, **_kw: current)
    executor._checkpoint_machine_raw_source_package = AsyncMock(side_effect=raw_checkpoint or (lambda *_args: "UPDATE 1"))
    executor._checkpoint_one_machine_research_result = AsyncMock(return_value="UPDATE 1")
    executor._upsert_machine_research_card = AsyncMock()
    executor._log_activity = AsyncMock()
    executor._gather_verified_machine_source_package = AsyncMock(
        side_effect=AssertionError("legacy source capture must not run on the Call 3 path"))
    return executor, payload


@pytest.mark.parametrize("machine", [
    MACHINE,
    "Wittemann-Lewis XNBL-1 Barling Bomber",
    "North American AJ Savage",
])
def test_targeted_factual_hold_researches_once_then_reuses_saved_card(machine):
    locked_roster = [machine] + [f"Pending factual machine {index}" for index in range(2, 21)]
    executor, payload = _hold_case(locked_roster)
    payload["unit_research_hold_validation"] = {
        "passed": False,
        "units": [
            {"machine": machine, "passed": False, "warnings": ["old Anton warning"]},
            {"machine": "Pending factual machine 2", "passed": False, "warnings": ["missing"]},
        ],
    }
    runner = _packet_runner()
    with patch("dvsu_research_v2.run_machine_research_packet", runner):
        first = asyncio.run(executor._run_unit_research_hold(
            "video-1", TITLE, payload, locked_roster, target_machine=machine,
        ))
        # A second targeted run finds the saved card fully current and must not
        # pay for Call 3 again (or checkpoint anything).
        second = asyncio.run(executor._run_unit_research_hold(
            "video-1", TITLE, first, locked_roster, target_machine=machine,
        ))

    assert runner.await_count == 1
    assert runner.await_args.args[1] == machine
    executor._gather_verified_machine_source_package.assert_not_awaited()
    assert executor._checkpoint_machine_raw_source_package.await_count == 1
    assert executor._checkpoint_one_machine_research_result.await_count == 1
    executor._upsert_machine_research_card.assert_awaited_once()

    card = pe._research_card_for_machine(second, machine)
    assert card["machine_research_contract"] == factual.FACTUAL_MACHINE_SCRIPT_CONTRACT
    assert card["research_summary"]["passed"] is True
    package = second["machine_raw_source_packages"][pe._verified_source_cache_key(machine)]
    assert package["claim_assessment"]["status"] == "assessed"
    assert card["claim_assessment"]["status"] == "assessed"
    validation = second["unit_research_hold_validation"]
    assert validation["target_machine_passed"] is True
    assert validation["passed"] is False
    assert len(validation["units"]) == 20


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


def test_factual_hold_persists_incomplete_packet_as_failed_summary():
    """A Call-3 packet missing an answer is saved with a failed, gap-naming
    research summary and a not-passed verdict - never presented as ready."""
    executor, payload = _hold_case([MACHINE])
    packet = _call3_packet(MACHINE)
    packet["trade_off"] = None
    runner = _packet_runner(packet=lambda _machine: packet)

    with patch("dvsu_research_v2.run_machine_research_packet", runner):
        result = asyncio.run(executor._run_unit_research_hold(
            "video-1", TITLE, payload, [MACHINE], target_machine=MACHINE,
        ))

    saved = pe._research_card_for_machine(result, MACHINE)["research_summary"]
    assert saved["passed"] is False
    assert "trade_off" in " ".join(saved["warnings"])
    validation = result["unit_research_hold_validation"]
    assert validation["passed"] is False
    assert validation["target_machine_passed"] is False
    verdict = executor._upsert_machine_research_card.await_args.args[4]
    assert verdict["passed"] is False and "trade_off" in " ".join(verdict["warnings"])
    executor._gather_verified_machine_source_package.assert_not_awaited()


def test_bulk_factual_hold_continues_after_one_transport_failure():
    roster = [MACHINE, "HMS Eagle", "HMS Hermes"]
    executor, payload = _hold_case(roster)
    runner = _packet_runner(failing={"HMS Eagle"})

    with patch("dvsu_research_v2.run_machine_research_packet", runner):
        result = asyncio.run(executor._run_unit_research_hold("video-1", TITLE, payload, roster))

    assert [call.args[1] for call in runner.await_args_list] == roster
    assert {card.get("machine") or card.get("unit") for card in result["unit_research_cards"]} == {MACHINE, "HMS Hermes"}
    failed = next(unit for unit in result["unit_research_hold_validation"]["units"] if unit["machine"] == "HMS Eagle")
    assert failed["passed"] is False
    assert "transport failure" in " ".join(failed["warnings"])
    for machine in (MACHINE, "HMS Hermes"):
        assert result["machine_raw_source_packages"][pe._verified_source_cache_key(machine)]["claim_assessment"]["status"] == "assessed"
    executor._gather_verified_machine_source_package.assert_not_awaited()


def test_bulk_factual_hold_stops_after_machine_two_checkpoint_conflict():
    roster = [MACHINE, "HMS Eagle", "HMS Hermes"]
    raw_checkpoints = []

    def raw_checkpoint(*_args):
        raw_checkpoints.append(1)
        # Each machine's Call-3 package is checkpointed once; refuse machine two's.
        return "UPDATE 0" if len(raw_checkpoints) == 2 else "UPDATE 1"

    executor, payload = _hold_case(roster, raw_checkpoint=raw_checkpoint)
    runner = _packet_runner()

    with patch("dvsu_research_v2.run_machine_research_packet", runner):
        result = asyncio.run(executor._run_unit_research_hold("video-1", TITLE, payload, roster))

    assert [call.args[1] for call in runner.await_args_list] == [MACHINE, "HMS Eagle"]
    assert len(raw_checkpoints) == 2
    assert "checkpoint refused" in " ".join(
        next(unit["warnings"] for unit in result["unit_research_hold_validation"]["units"] if unit["machine"] == "HMS Eagle")
    )
    # Machine one's card was saved; machine two's refused package never reached a card.
    assert executor._checkpoint_one_machine_research_result.await_count == 1
    assert {card.get("machine") or card.get("unit") for card in result["unit_research_cards"]} == {MACHINE}


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
