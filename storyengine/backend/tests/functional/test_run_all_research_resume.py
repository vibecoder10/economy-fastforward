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


def _video():
    return {
        "id": "video", "status": "idea_logged", "render_mode": "static_docu",
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
    assert result["status"] == "ready_for_scripting"
    ex.run_unit_research.assert_awaited_once_with("video")
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
    with patch.dict(sys.modules, {"research.agent": module}), patch.object(pe, "fetch_one", AsyncMock(return_value=None)):
        result = asyncio.run(ex.run_research("video"))
    assert result["status"] == "failed"  # empty discovery must not be accepted
    ex.run_unit_research.assert_not_awaited()
    discover.assert_awaited_once()
    assert "CVA-01" in discover.call_args.kwargs["context"]
    assert "CORRECT THE EXISTING ROSTER" in discover.call_args.kwargs["context"]


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
