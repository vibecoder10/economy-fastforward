"""Exercise the real executor boundary: stale verdicts never force rediscovery
of a valid roster, while invalid saved rosters can actually be repaired."""
import asyncio
import copy
import json
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "skills/video-pipeline"))
import pipeline_executor as pe
import pytest


@pytest.fixture(autouse=True)
def _channel_contract_boundary(monkeypatch):
    monkeypatch.setattr(pe, "fetch_one", AsyncMock(return_value=None))
    monkeypatch.setattr(pe, "execute", AsyncMock(return_value="UPDATE 1"))
    monkeypatch.setattr("channel_format.apply_machine_script_contract", AsyncMock())
    monkeypatch.setattr("cancel_registry.is_cancel_requested", AsyncMock(return_value=False))
    monkeypatch.setattr("roster_coverage.audit_roster_coverage", AsyncMock(return_value={"passed": True, "findings": []}))


def _video():
    return {
        "id": "video", "status": "idea_logged", "render_mode": "static_docu", "video_length_minutes": 3,
        "video_title": "British carriers", "research_payload": {
            "machine_discovery_buckets": {},
            "unit_roster": [{"name": n} for n in ["Argus", "Hermes", "Eagle"]],
            "unit_roster_validation": {"passed": False, "warnings": ["old rule"]},
        },
    }


def _executor(video):
    ex = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    ex.tenant_id = "tenant"
    ex._ensure_initialized = AsyncMock()
    ex._get_video = AsyncMock(return_value=copy.deepcopy(video))
    ex._log_activity = AsyncMock()
    ex._load_prompt_overrides = AsyncMock()
    ex._pipeline = types.SimpleNamespace(anthropic=object(), airtable=object())
    return ex


def test_valid_saved_roster_resumes_without_discovery_even_with_stale_failure():
    ex = _executor(_video())
    ex.run_unit_research = AsyncMock(return_value={"status": "ready_for_scripting"})
    result = asyncio.run(ex.run_research("video"))
    assert result["status"] == "roster_ready"
    ex.run_unit_research.assert_not_awaited()
    ex._load_prompt_overrides.assert_not_awaited()


def test_invalid_saved_roster_reaches_corrective_discovery():
    video = _video()
    video["video_title"] = "Every British aircraft carrier ever built"
    video["research_payload"]["unit_roster"].append({
        "name": "CVA-01", "status": "cancelled", "built_count": "0 ships built",
    })
    ex = _executor(video)
    ex.run_unit_research = AsyncMock()
    discover = AsyncMock(return_value=None)
    module = types.ModuleType("research.agent")
    module.run_research = discover
    module.RESEARCH_SYSTEM_PROMPT = "Default research system"
    with patch.dict(sys.modules, {"research.agent": module}), patch.object(pe, "fetch_one", AsyncMock(return_value=None)):
        result = asyncio.run(ex.run_research("video"))
    assert result["status"] == "failed"  # empty discovery must not be accepted
    ex.run_unit_research.assert_not_awaited()
    discover.assert_awaited_once()
    assert "CVA-01" in discover.call_args.kwargs["context"]
    assert "Saved payload to reuse as source data" in discover.call_args.kwargs["context"]


def test_failed_legacy_coverage_is_retained_as_source_data_before_runtime_selection():
    video = _video()
    video["video_title"] = "Every British aircraft carrier ever built"
    ex = _executor(video)
    ex.run_unit_research = AsyncMock()
    discover = AsyncMock(return_value=None)
    module = types.ModuleType("research.agent")
    module.run_research = discover
    module.RESEARCH_SYSTEM_PROMPT = "Default research system"
    video["research_payload"]["independent_coverage_audit"] = {"passed": False, "findings": [{"candidate": "Activity", "problem": "Historical audit finding"}]}
    ex = _executor(video)
    ex.run_unit_research = AsyncMock()
    coverage = AsyncMock()
    with patch.dict(sys.modules, {"research.agent": module}), \
         patch.object(pe, "fetch_one", AsyncMock(return_value=None)), \
         patch.object(pe, "_roster_validation", return_value={"passed": True, "warnings": []}), \
         patch("roster_coverage.audit_roster_coverage", coverage):
        result = asyncio.run(ex.run_research("video"))
    assert result["status"] == "failed"
    ex.run_unit_research.assert_not_awaited()
    coverage.assert_not_awaited()
    assert "Activity" in discover.call_args.kwargs["context"]


def test_live_incremental_gate_cannot_erase_failed_or_stale_coverage():
    from roster_coverage import VERSION, coverage_fingerprint
    video = _video()
    payload = video["research_payload"]
    payload["independent_coverage_audit"] = {
        "version": VERSION, "fingerprint": coverage_fingerprint(video["video_title"], payload), "passed": False,
    }
    assert not pe._live_roster_gate(video, payload)["passed"]
    payload["independent_coverage_audit"]["passed"] = True
    assert pe._live_roster_gate(video, payload)["passed"]
    payload["unit_roster"].append({"name": "Courageous"})
    assert not pe._live_roster_gate(video, payload)["passed"]


def test_resume_persists_current_gate_and_bootstraps_missing_hold():
    video = _video()
    ex = _executor(video)

    async def hold(_id, _title, payload, roster):
        assert payload["unit_roster_validation"]["passed"] is True
        payload["unit_research_hold_validation"] = {
            "passed": False, "units": [{"machine": n, "passed": False} for n in roster],
        }
        return payload

    ex._run_unit_research_hold = AsyncMock(side_effect=hold)
    saved = AsyncMock(return_value="UPDATE 1")
    workspace = types.ModuleType("drive_workspace")
    workspace.sync_video_workspace_fail_soft = AsyncMock()
    with patch.object(pe, "execute", saved), patch.dict(sys.modules, {"drive_workspace": workspace}):
        result = asyncio.run(ex.run_unit_research("video"))
    assert result["status"] == "failed"  # cards still pending, no fake advancement
    persisted = json.loads(saved.call_args.args[1])
    assert persisted["unit_roster_validation"]["passed"] is True
    assert len(persisted["unit_research_hold_validation"]["units"]) == 3
    assert saved.call_args.args[2] == "idea_logged"



@pytest.mark.parametrize("title", ["Every British aircraft carrier ever built", "Every US Strategic Bomber Ever Built (2026)"])
def test_same_locked_policy_reaches_initial_discovery_and_autonomous_repair(title):
    from roster_coverage import selection_scope_policy
    video = _video()
    video["video_title"] = title
    video["research_payload"] = {}
    ex = _executor(video)
    ex.run_unit_research = AsyncMock()
    discover = AsyncMock(side_effect=[copy.deepcopy(video["research_payload"]), ValueError("stop after repair dispatch")])
    module = types.ModuleType("research.agent")
    module.run_research = discover
    module.RESEARCH_SYSTEM_PROMPT = "Default research system"
    coverage = AsyncMock(return_value={"passed": False, "findings": [{"candidate": "Campania", "problem": "Fix exact era and landing-deck qualification"}]})
    with patch.dict(sys.modules, {"research.agent": module}), \
         patch.object(pe, "fetch_one", AsyncMock(return_value=None)), \
         patch.object(pe, "_roster_validation", return_value={"passed": True, "complete_title": True, "warnings": []}), \
         patch("roster_coverage.audit_roster_selection", coverage):
        result = asyncio.run(ex.run_research("video"))
    assert result["status"] == "failed"
    assert discover.await_count == 2
    policy = selection_scope_policy(video["video_title"])
    for call in discover.await_args_list:
        assert policy in call.kwargs["context"]
        assert call.kwargs["selection_settings"]["target_count"] == 3
        assert "system_prompt_override" not in call.kwargs
    ex.run_unit_research.assert_not_awaited()


def test_repair_receives_same_draft_and_all_gates_before_research_handoff():
    """Real executor: structural failure must not defer coverage until repair is spent."""
    video = _video()
    video['video_title'] = 'Every US Strategic Bomber Ever Built (2026)'
    video['research_payload'] = {}
    ex = _executor(video)
    ex._log_transition = AsyncMock()
    draft = {'unit_roster': [{'name': 'B-47'}, {'name': 'A-3'}], 'roster_contract': {'status': 'DRAFT'}}
    repaired = {'machine_discovery_buckets': {}, 'unit_roster': [{'name': 'B-47'}, {'name': 'A-3'}, {'name': 'A-5'}], 'roster_contract': {'status': 'CONFIRMED'}}
    async def discover(**kw):
        if discover_mock.await_count == 1:
            return copy.deepcopy(draft)
        assert 'A-5' in kw['context'], 'Coverage feedback never reached corrective discovery'
        assert 'DRAFT:' in kw['context']
        assert json.dumps(draft['unit_roster']) in kw['context']
        return copy.deepcopy(repaired)
    discover_mock = AsyncMock(side_effect=discover)
    module = types.ModuleType('research.agent')
    module.run_research = discover_mock
    module.RESEARCH_SYSTEM_PROMPT = 'Research'
    async def coverage(_client, _title, payload, **kwargs):
        passed = len(payload['unit_roster']) == 3
        return {'passed': passed, 'findings': [] if passed else [{'candidate': 'A-5', 'problem': 'Replacement fits title; existing item does not', 'source_url': 'https://www.history.navy.mil/a5'}]}
    def gate(_title, payload, **kwargs):
        passed = payload['roster_contract']['status'] == 'CONFIRMED'
        return {'passed': passed, 'roster_count':len(payload['unit_roster']), 'complete_title': True, 'warnings': [] if passed else ['Draft boundary unresolved']}
    async def hold(_id, _title, payload, roster):
        assert 'A-5' in roster
        payload['unit_research_hold_validation'] = {'passed': True}
        return payload
    ex._run_unit_research_hold = AsyncMock(side_effect=hold)
    workspace = types.ModuleType('drive_workspace')
    workspace.sync_video_workspace_fail_soft = AsyncMock()
    with patch.dict(sys.modules, {'research.agent': module, 'drive_workspace': workspace}), \
         patch.object(pe, 'fetch_one', AsyncMock(return_value=None)), \
         patch.object(pe, 'execute', AsyncMock(return_value='UPDATE 1')), \
         patch.object(pe, '_roster_validation', side_effect=gate), \
         patch('roster_coverage.audit_roster_selection', side_effect=coverage), \
         patch('static_docu.dispatch_roster_prefetch'):
        result = asyncio.run(ex.run_research('video'))
    assert result['status'] == 'roster_ready', result
    assert discover_mock.await_count == 2
    ex._run_unit_research_hold.assert_not_awaited()


def test_locked_research_arms_cancellation_and_preserves_saved_checkpoint():
    video = _video()
    ex = _executor(video)
    async def hold(_id, _title, payload, roster):
        assert await ex._pipeline.should_cancel() is True
        payload['unit_research_hold_validation'] = {'passed': False}
        return payload
    ex._run_unit_research_hold = AsyncMock(side_effect=hold)
    workspace = types.ModuleType('drive_workspace')
    workspace.sync_video_workspace_fail_soft = AsyncMock()
    saved = AsyncMock(return_value='UPDATE 1')
    with patch('cancel_registry.is_cancel_requested', AsyncMock(return_value=True)), \
         patch.object(pe, 'execute', saved), patch.dict(sys.modules, {'drive_workspace': workspace}):
        result = asyncio.run(ex.run_unit_research('video'))
    assert result['status'] == 'cancelled'
    assert saved.call_args.args[2] == 'idea_logged'
