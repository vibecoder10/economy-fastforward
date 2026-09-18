"""Unit tests for dvsu_roster_v2 (DVSU research pipeline v2, Call 1 + Call 2)
and for pipeline_executor.run_roster_selection's factual_100_v1 contract gate.

Mocking pattern mirrors tests/test_runtime_roster_selection.py and
tests/test_roster_stage_integration.py: a trivial hand-rolled client with an
async ``generate(self, **kwargs)`` that captures kwargs and returns a JSON
string - never a mock of the Anthropic SDK itself.
"""
import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import dvsu_roster_v2 as v2


class _Client:
    """Captures the kwargs of the last generate() call; returns queued responses."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.kwargs = None
        self.calls = []

    async def generate(self, **kwargs):
        self.kwargs = kwargs
        self.calls.append(kwargs)
        return self._responses.pop(0)


# ---------------------------------------------------------------------------
# Call 1 - thesis + acts
# ---------------------------------------------------------------------------

def test_call1_thesis_and_acts_no_search_and_parses_json():
    client = _Client(json.dumps({
        "thesis": "The Navy kept solving last decade's problem.",
        "acts": [{"act_number": 1, "argument": "First act."}, {"act_number": 2, "argument": "Second act."}],
    }))
    result = asyncio.run(v2._call_thesis_and_acts(client, "Every Widget Ever Built", None))
    assert result["thesis"] == "The Navy kept solving last decade's problem."
    assert result["acts"] == [
        {"act_number": 1, "argument": "First act."},
        {"act_number": 2, "argument": "Second act."},
    ]
    assert "tools" not in client.kwargs
    assert client.kwargs["system_prompt"] == v2.CALL1_SYSTEM_PROMPT
    assert 'Video title: "Every Widget Ever Built"' in client.kwargs["prompt"]


def test_call1_rejects_missing_thesis_or_empty_acts():
    empty_thesis = _Client(json.dumps({"thesis": "", "acts": [{"act_number": 1, "argument": "x"}]}))
    with pytest.raises(ValueError):
        asyncio.run(v2._call_thesis_and_acts(empty_thesis, "Title", None))
    no_acts = _Client(json.dumps({"thesis": "T", "acts": []}))
    with pytest.raises(ValueError):
        asyncio.run(v2._call_thesis_and_acts(no_acts, "Title", None))
    not_json = _Client("not json at all")
    with pytest.raises(ValueError):
        asyncio.run(v2._call_thesis_and_acts(not_json, "Title", None))


# ---------------------------------------------------------------------------
# Call 2 - roster + shared context
# ---------------------------------------------------------------------------

def test_call2_roster_and_shared_context_uses_web_search_tool_and_sorts_by_act():
    client = _Client(json.dumps({
        "roster": [{"machine": "HMS Later", "act_number": 2}, {"machine": "HMS Earlier", "act_number": 1}],
        "shared_context": ["Fact A", "Fact B"],
    }))
    acts = [{"act_number": 1, "argument": "First act."}, {"act_number": 2, "argument": "Second act."}]
    result = asyncio.run(v2._call_roster_and_shared_context(client, "Title", "Thesis text", acts, None))
    assert client.kwargs["tools"] == [{"type": "web_search_20250305", "name": "web_search", "max_uses": v2.CALL2_SEARCH_BUDGET}]
    assert client.kwargs["system_prompt"] == v2.CALL2_SYSTEM_PROMPT
    assert '"Thesis text"' in client.kwargs["prompt"]
    assert "1. First act." in client.kwargs["prompt"] and "2. Second act." in client.kwargs["prompt"]
    # Grouped by act, act order preserved regardless of the model's own order.
    assert result["roster"] == [{"machine": "HMS Earlier", "act_number": 1}, {"machine": "HMS Later", "act_number": 2}]
    assert result["shared_context"] == ["Fact A", "Fact B"]


def test_call2_gateway_mode_guard_raises_without_calling_generate():
    client = _Client()
    client._gateway_mode = True

    async def _boom(**kwargs):
        raise AssertionError("generate() must not be called when _gateway_mode is True")
    client.generate = _boom  # type: ignore[assignment]
    with pytest.raises(ValueError):
        asyncio.run(v2._call_roster_and_shared_context(
            client, "Title", "Thesis", [{"act_number": 1, "argument": "a"}], None,
        ))


def test_call2_rejects_empty_roster():
    client = _Client(json.dumps({"roster": [], "shared_context": []}))
    with pytest.raises(ValueError):
        asyncio.run(v2._call_roster_and_shared_context(
            client, "Title", "Thesis", [{"act_number": 1, "argument": "a"}], None,
        ))


# ---------------------------------------------------------------------------
# Combined Call 1 + Call 2 merge shape
# ---------------------------------------------------------------------------

def test_run_thesis_roster_and_context_merges_calls_and_is_drive_fail_soft():
    client = _Client(
        json.dumps({"thesis": "T", "acts": [{"act_number": 1, "argument": "A1"}, {"act_number": 2, "argument": "A2"}]}),
        json.dumps({"roster": [{"machine": "M2", "act_number": 2}, {"machine": "M1", "act_number": 1}],
                    "shared_context": ["ctx"]}),
    )
    # No Drive credentials are configured in this sandbox - this proves the
    # export failure never propagates out of run_thesis_roster_and_context.
    result = asyncio.run(v2.run_thesis_roster_and_context(client, "Every Widget", checkpoint_scope=None))
    assert result["thesis"] == "T"
    assert result["acts"] == [{"act_number": 1, "argument": "A1"}, {"act_number": 2, "argument": "A2"}]
    assert result["unit_roster"] == [{"machine": "M1", "act_number": 1}, {"machine": "M2", "act_number": 2}]
    assert result["recommended_final_roster"] == ["M1", "M2"]
    assert result["shared_context"] == ["ctx"]


def test_drive_export_fail_soft_swallows_google_client_construction_failure():
    # GoogleClient() raises ValueError with no OAuth env configured (see
    # google_client.py). export_thesis_roster_to_drive_fail_soft must catch
    # that and return None, never raise.
    draft = {"thesis": "T", "acts": [{"act_number": 1, "argument": "A"}],
              "unit_roster": [{"machine": "M1", "act_number": 1}], "shared_context": []}
    result = asyncio.run(v2.export_thesis_roster_to_drive_fail_soft("Some Title", draft))
    assert result is None


# ---------------------------------------------------------------------------
# pipeline_executor.run_roster_selection contract gate
# ---------------------------------------------------------------------------

@pytest.fixture
def gate_stage(monkeypatch):
    import pipeline_executor as pe

    events = []

    def _make(contract):
        initial = {
            "machine_discovery_buckets": {},
            "unit_roster": [{"name": f"Candidate {i}"} for i in range(58)],
            "fact_sheet": "original retained facts",
            "unit_roster_validation": {"passed": False},
        }
        if contract is not None:
            initial["machine_script_contract"] = contract
        video = {"id": "v", "status": "idea_logged", "render_mode": "static_docu",
                  "video_length_minutes": 20, "video_title": "Every Widget Ever Built",
                  "research_payload": initial}
        ex = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
        ex.tenant_id = "t"
        ex._get_video = AsyncMock(side_effect=lambda _: copy.deepcopy(video))
        ex._pipeline = SimpleNamespace(anthropic=object(), should_cancel=AsyncMock(return_value=False))
        ex._log_activity = AsyncMock(side_effect=lambda *a: events.append(a))

        async def save(query, *args):
            payload = json.loads(args[0])
            video["research_payload"] = payload
            return "UPDATE 1"
        monkeypatch.setattr(pe, "execute", save)
        monkeypatch.setattr(pe, "fetch_one", AsyncMock(return_value={"has_saved_work": False}))
        return ex, video

    return _make, events


def test_non_factual_contract_uses_unchanged_legacy_path(gate_stage, monkeypatch):
    """A video WITHOUT machine_script_contract == 'factual_100_v1' must still
    go through the old research.agent.run_research + roster_coverage.audit_roster_selection
    path, and must NEVER call the new dvsu_roster_v2 module."""
    import research.agent as research
    import roster_coverage as coverage

    make, events = gate_stage
    ex, video = make("factual_machine_v1")  # NOT factual_100_v1 - the old/other contract

    selected = {
        "unit_roster": [{"name": f"Candidate {i}", "status": "production", "built_count": "1 unit completed"} for i in range(20)],
        "recommended_final_roster": [f"Candidate {i}" for i in range(20)],
        "roster_contract": "CONFIRMED",
    }
    legacy_research = AsyncMock(return_value=selected)
    monkeypatch.setattr(research, "run_research", legacy_research)
    legacy_audit = AsyncMock(return_value={"passed": True, "findings": [], "sources": [
        {"url": "https://history.navy.mil/a"}, {"url": "https://archives.gov/b"},
    ]})
    monkeypatch.setattr(coverage, "audit_roster_selection", legacy_audit)

    async def _must_not_be_called(*a, **k):
        raise AssertionError("dvsu_roster_v2 must not run for a non-factual_100_v1 contract")
    monkeypatch.setattr(v2, "run_thesis_roster_and_context", _must_not_be_called)

    result = asyncio.run(ex.run_roster_selection("v"))
    assert result["status"] == "roster_ready", result
    legacy_research.assert_awaited_once()
    legacy_audit.assert_awaited_once()
    assert video["research_payload"]["roster_selection"]["status"] == "completed"
    assert len(video["research_payload"]["unit_roster"]) == 20


def test_factual_100_v1_contract_uses_new_dvsu_v2_path(gate_stage, monkeypatch):
    """A video WITH machine_script_contract == 'factual_100_v1' must use the
    new dvsu_roster_v2 path and must NEVER call the old research.agent path
    or roster_coverage.audit_roster_selection (design explicitly drops the
    audit/repair loop)."""
    import research.agent as research
    import roster_coverage as coverage

    make, events = gate_stage
    ex, video = make("factual_100_v1")

    draft = {
        "thesis": "The thesis.",
        "acts": [{"act_number": 1, "argument": "Only act."}],
        "unit_roster": [{"machine": f"M{i}", "act_number": 1} for i in range(20)],
        "recommended_final_roster": [f"M{i}" for i in range(20)],
        "shared_context": ["shared fact"],
    }
    new_call = AsyncMock(return_value=draft)
    monkeypatch.setattr(v2, "run_thesis_roster_and_context", new_call)

    async def _must_not_be_called(*a, **k):
        raise AssertionError("legacy research.agent.run_research must not run for factual_100_v1")
    monkeypatch.setattr(research, "run_research", _must_not_be_called)

    async def _audit_must_not_be_called(*a, **k):
        raise AssertionError("roster_coverage.audit_roster_selection must not run for the DVSU v2 path")
    monkeypatch.setattr(coverage, "audit_roster_selection", _audit_must_not_be_called)

    result = asyncio.run(ex.run_roster_selection("v"))
    assert result["status"] == "roster_ready", result
    assert result["selected_count"] == 20
    new_call.assert_awaited_once()
    assert new_call.await_args.kwargs["checkpoint_scope"] == {"tenant_id": "t", "video_id": "v"}
    saved = video["research_payload"]
    assert saved["thesis"] == "The thesis."
    assert saved["acts"] == [{"act_number": 1, "argument": "Only act."}]
    assert saved["shared_context"] == ["shared fact"]
    assert saved["roster_selection"]["status"] == "completed"
    assert saved["research_phase"] == "roster_complete"
    assert "independent_audit" not in saved["roster_selection"]
    assert len(saved["unit_roster"]) == 20


def test_factual_100_v1_contract_saves_needs_review_on_structural_failure(gate_stage, monkeypatch):
    """No retry round-trip on structural failure - save needs_review and stop."""
    import research.agent as research

    make, events = gate_stage
    ex, video = make("factual_100_v1")

    # Fewer machines than the runtime target (20 for a 20-minute video at
    # the default 1 min/machine pacing) - selection_validation must fail.
    draft = {
        "thesis": "T", "acts": [{"act_number": 1, "argument": "A"}],
        "unit_roster": [{"machine": "M1", "act_number": 1}],
        "recommended_final_roster": ["M1"],
        "shared_context": [],
    }
    new_call = AsyncMock(return_value=draft)
    monkeypatch.setattr(v2, "run_thesis_roster_and_context", new_call)
    legacy_research = AsyncMock(side_effect=AssertionError("must not retry via the legacy path either"))
    monkeypatch.setattr(research, "run_research", legacy_research)

    result = asyncio.run(ex.run_roster_selection("v"))
    assert result["status"] == "failed"
    assert result["roster_selection_failed"] is True
    new_call.assert_awaited_once()  # generated exactly once - no paid retry
    saved = video["research_payload"]
    assert saved["roster_selection"]["status"] == "needs_review"
    assert saved["unit_roster_validation"]["passed"] is False
