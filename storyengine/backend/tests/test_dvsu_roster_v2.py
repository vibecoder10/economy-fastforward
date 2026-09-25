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
# The list (+ spares), then the story
# ---------------------------------------------------------------------------

def test_list_call_uses_web_search_and_splits_roster_from_spares():
    client = _Client(json.dumps({
        "roster": [{"machine": "M1", "reason": "r"}, {"machine": "M2", "reason": "r"}, {"machine": "M3", "reason": "r"}],
        "spares": [{"machine": "S1", "reason": "r"}, {"machine": "m2", "reason": "dup"}, "S2"],
        "shared_context": ["Fact A"],
    }))
    result = asyncio.run(v2._call_roster_list(client, "Title", None, 2))
    assert client.kwargs["tools"] == [{"type": "web_search_20250305", "name": "web_search", "max_uses": v2.CALL2_SEARCH_BUDGET}]
    assert client.kwargs["system_prompt"] == v2.CALL2_SYSTEM_PROMPT
    # The runtime count is Ryan's: a long list's tail becomes the first spares.
    assert result["machines"] == ["M1", "M2"]
    assert result["spares"] == ["M3", "S1", "S2"]
    assert result["shared_context"] == ["Fact A"]


def test_list_call_gateway_mode_guard_raises_without_calling_generate():
    client = _Client()
    client._gateway_mode = True

    async def _boom(**kwargs):
        raise AssertionError("generate() must not be called when _gateway_mode is True")
    client.generate = _boom  # type: ignore[assignment]
    with pytest.raises(ValueError):
        asyncio.run(v2._call_roster_list(client, "Title", None, 20))


def test_list_call_rejects_empty_roster_and_bad_json():
    with pytest.raises(ValueError):
        asyncio.run(v2._call_roster_list(_Client(json.dumps({"roster": [], "spares": ["S"]})), "Title", None, 20))
    with pytest.raises(ValueError):
        asyncio.run(v2._call_roster_list(_Client("not json at all"), "Title", None, 20))


def test_every_title_runs_list_then_story_and_keeps_spares():
    """2026-09-25 "Most Hated Helicopters": a thesis-first roster picked one-off
    prototypes nobody hated. Every title now picks the list first (Ryan)."""
    client = _Client(
        json.dumps({"roster": ["M1", "M2"], "spares": ["S1", "S2"], "shared_context": ["ctx"]}),
        json.dumps({"thesis": "T", "acts": [{"act_number": 1, "argument": "A1"}, {"act_number": 2, "argument": "A2"}],
                    "roster": [{"machine": "M2", "act_number": 2}, {"machine": "M1", "act_number": 1}],
                    "spares": [{"machine": "s1", "act_number": 2}]}),
    )
    # No Drive credentials are configured in this sandbox - this proves the
    # export failure never propagates out of run_thesis_roster_and_context.
    result = asyncio.run(v2.run_thesis_roster_and_context(client, "Most Hated Helicopters", checkpoint_scope=None, target_count=2))
    first, second = client.calls
    assert first["tools"] and not second.get("tools")
    assert "- S1" in second["prompt"] and "- S2" in second["prompt"]
    assert result["thesis"] == "T"
    assert result["unit_roster"] == [{"machine": "M1", "act_number": 1}, {"machine": "M2", "act_number": 2}]
    assert result["recommended_final_roster"] == ["M1", "M2"]
    assert result["roster_candidate_overflow"] == [{"machine": "S1", "act_number": 2}, {"machine": "S2"}]
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


def test_class_titled_video_roster_of_class_names_passes_structural_check(monkeypatch):
    """Regression test for the live-verification finding, 2026-09-19: a
    factual_100_v1 video titled "Every X Class Ever Built" (this channel's
    flagship format) with a roster of class-name entries (e.g. "Ajax class" -
    exactly DESIGN.md's own worked example) must NOT be rejected by the
    legacy roster_selection.selection_validation / representative_warnings
    checker, which enforces the OLD "exactly one named machine per class"
    policy and flags every entry containing the word "class" as invalid.
    Confirmed live against the real deployed code before this fix: a real
    20-entry submarine-class roster failed with 40 warnings ("choose one
    named machine, not a class" x20 + "record the selected machine's
    class_name" x20) despite being a perfectly valid roster.
    """
    import pipeline_executor as pe

    video = {
        "id": "v", "status": "idea_logged", "render_mode": "static_docu",
        "video_length_minutes": 20,
        "video_title": "Every US Submarine Class Ever Built (2026)",
        "research_payload": {"machine_script_contract": "factual_100_v1"},
    }
    ex = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    ex.tenant_id = "t"
    ex._get_video = AsyncMock(side_effect=lambda _: copy.deepcopy(video))
    ex._pipeline = SimpleNamespace(anthropic=object(), should_cancel=AsyncMock(return_value=False))
    ex._log_activity = AsyncMock()

    async def save(query, *args):
        video["research_payload"] = json.loads(args[0])
        return "UPDATE 1"
    monkeypatch.setattr(pe, "execute", save)
    monkeypatch.setattr(pe, "fetch_one", AsyncMock(return_value={"has_saved_work": False}))

    class_roster = [{"machine": f"{name} class", "act_number": 1} for name in (
        "Holland", "Adder", "F", "S", "Barracuda", "Porpoise", "Gato", "Balao", "Tench",
        "Guppy", "Tang", "Barbel", "Skate", "Skipjack", "George Washington", "Lafayette",
        "Ohio", "Permit", "Sturgeon", "Los Angeles",
    )]
    assert len(class_roster) == 20
    draft = {
        "thesis": "T", "acts": [{"act_number": 1, "argument": "A"}],
        "unit_roster": class_roster,
        "recommended_final_roster": [row["machine"] for row in class_roster],
        "shared_context": [],
    }
    monkeypatch.setattr(v2, "run_thesis_roster_and_context", AsyncMock(return_value=draft))

    result = asyncio.run(ex.run_roster_selection("v"))
    assert result["status"] == "roster_ready", result
    assert result["selected_count"] == 20
    saved = video["research_payload"]
    assert saved["roster_selection"]["status"] == "completed"
    assert saved["unit_roster_validation"]["passed"] is True
    assert saved["unit_roster_validation"]["warnings"] == []


def test_live_roster_gate_accepts_saved_v2_roster_without_independent_audit(monkeypatch):
    """Regression, 2026-09-21: production_guide showed "roster: not_started"
    (and run_unit_research / roster-images refused to run) for a v2 video whose
    roster was saved and completed. v2 deliberately skips the independent
    selection audit (see run_roster_selection's v2 branch), but
    _live_roster_gate demanded independent_selection_audit.passed for EVERY
    runtime selection, so a completed v2 roster could never pass the gate.
    Runs the real run_roster_selection to produce the payload, then feeds it to
    the gate the way production_guide and the Call 3 stage do."""
    import pipeline_executor as pe

    video = {
        "id": "v", "status": "idea_logged", "render_mode": "static_docu",
        "video_length_minutes": 20,
        "video_title": "Every US Submarine Class Ever Built (2026)",
        "research_payload": {"machine_script_contract": "factual_100_v1"},
    }
    ex = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    ex.tenant_id = "t"
    ex._get_video = AsyncMock(side_effect=lambda _: copy.deepcopy(video))
    ex._pipeline = SimpleNamespace(anthropic=object(), should_cancel=AsyncMock(return_value=False))
    ex._log_activity = AsyncMock()

    async def save(query, *args):
        video["research_payload"] = json.loads(args[0])
        return "UPDATE 1"
    monkeypatch.setattr(pe, "execute", save)
    monkeypatch.setattr(pe, "fetch_one", AsyncMock(return_value={"has_saved_work": False}))

    roster = [{"machine": f"Sub {n} class", "act_number": 1} for n in range(20)]
    draft = {
        "thesis": "T", "acts": [{"act_number": 1, "argument": "A"}],
        "unit_roster": roster,
        "recommended_final_roster": [row["machine"] for row in roster],
        "shared_context": [],
    }
    monkeypatch.setattr(v2, "run_thesis_roster_and_context", AsyncMock(return_value=draft))
    assert asyncio.run(ex.run_roster_selection("v"))["status"] == "roster_ready"

    payload = video["research_payload"]
    assert "independent_selection_audit" not in payload
    gate = pe._live_roster_gate(video, payload)
    assert gate["passed"] is True, gate.get("warnings")

    # The v2 exemption must not weaken the legacy path or real drift checks:
    # a settings change still reopens selection.
    drifted = dict(video, video_length_minutes=30)
    assert pe._live_roster_gate(drifted, payload)["passed"] is False


def test_list_prompt_carries_the_title_rules():
    """Regression, 2026-09-24 "Every US Military Helicopter Ever Built": story-first
    let an Army-only thesis and a tiltrotor act bend the picks (V-22 in, CH-53 out,
    UH-60 + SH-60 both listed). 2026-09-25 "Most Hated Helicopters": prototypes in,
    service machines out. The rules go in the input, not a checker (Ryan)."""
    listing = v2._roster_list_prompt("Every US Military Helicopter Ever Built (2026)", 20)
    assert "Thesis" not in listing and "Acts" not in listing
    assert "pick exactly 20 real machines" in listing and "plus 3 spares" in listing
    assert "UH-60 and SH-60 are one" in listing
    assert "no tiltrotor" in listing
    assert "every service" in listing
    assert "most hated" in listing and "one-off prototypes" in listing
    assert "never-built or cancelled" in listing

    story = v2._story_for_roster_prompt("Every US Military Helicopter Ever Built (2026)", ["R-4 Hoverfly", "UH-1 Iroquois"])
    assert "exactly these 2 machines" in story and "- UH-1 Iroquois" in story
    assert "spelled exactly as listed" in story
    assert "near-equal share" in story
    assert "every service" in story


def test_complete_title_roster_never_resizes_the_runtime_ryan_set(monkeypatch):
    """Ryan, 2026-09-24: "if we say 20 min, we mean 20 minutes and 20" machines.
    An "every X" title used to resize the runtime to whatever the roster found
    (the 2026-09-23 rule, now reversed). The roster is asked for the target
    count and bounded to it; the saved length never changes."""
    import pipeline_executor as pe

    video = {
        "id": "v", "status": "idea_logged", "render_mode": "static_docu",
        "video_length_minutes": 20,
        "video_title": "Every US Battleship Class Ever Built (2026)",
        "research_payload": {"machine_script_contract": "factual_100_v1"},
    }
    ex = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    ex.tenant_id = "t"
    ex._get_video = AsyncMock(side_effect=lambda _: copy.deepcopy(video))
    ex._pipeline = SimpleNamespace(anthropic=object(), should_cancel=AsyncMock(return_value=False))
    ex._log_activity = AsyncMock()

    async def save(query, *args):
        if "video_length_minutes" in query:
            video["video_length_minutes"] = args[0]
        else:
            video["research_payload"] = json.loads(args[0])
        return "UPDATE 1"
    monkeypatch.setattr(pe, "execute", save)
    monkeypatch.setattr(pe, "fetch_one", AsyncMock(return_value={"has_saved_work": False}))

    roster = [{"machine": f"Class {n}", "act_number": 1} for n in range(23)]
    draft = {
        "thesis": "T", "acts": [{"act_number": 1, "argument": "A"}],
        "unit_roster": roster,
        "recommended_final_roster": [row["machine"] for row in roster],
        "shared_context": [],
    }
    monkeypatch.setattr(v2, "run_thesis_roster_and_context", AsyncMock(return_value=draft))

    result = asyncio.run(ex.run_roster_selection("v"))
    assert result == {"status": "roster_ready", "video_id": "v", "selected_count": 20}
    assert video["video_length_minutes"] == 20
    assert v2.run_thesis_roster_and_context.await_args.kwargs["target_count"] == 20
    payload = video["research_payload"]
    assert len(payload["unit_roster"]) == 20
    assert payload["roster_selection"]["target_count"] == 20
    assert pe._live_roster_gate(video, payload)["passed"] is True


class _FakeDrive:
    """Records the kwargs of every Drive files().create/list/update call."""

    def __init__(self):
        self.calls = []

    def files(self):
        return self

    def _record(self, op, kwargs):
        self.calls.append((op, kwargs))
        return SimpleNamespace(execute=lambda: {"id": "new-id", "name": "n", "mimeType": "m", "files": []})

    def create(self, **kw): return self._record("create", kw)
    def list(self, **kw): return self._record("list", kw)
    def update(self, **kw): return self._record("update", kw)


def test_google_client_folder_and_upload_calls_are_shared_drive_aware():
    """Regression, 2026-09-21: the client passed no supportsAllDrives /
    includeItemsFromAllDrives, so a Shared Drive folder was invisible to
    search and 404'd on create/upload - the DVSU export could only ever land
    in My Drive."""
    from shared.clients.google_client import GoogleClient

    client = GoogleClient(client_id="i", client_secret="s", refresh_token="r", parent_folder_id="root")
    fake = _FakeDrive()
    client._services.drive = fake

    client.search_folder("StoryEngine Research", parent_id="p")
    client.search_file("a.md", "p")
    client.create_folder("t", parent_id="p")
    client.upload_file(b"x", "a.md", "p", mime_type="text/markdown", check_existing=False)

    ops = [op for op, _ in fake.calls]
    assert ops == ["list", "list", "create", "create"]
    for op, kw in fake.calls:
        assert kw.get("supportsAllDrives") is True, (op, kw)
        if op == "list":
            assert kw.get("includeItemsFromAllDrives") is True, kw


def test_research_root_folder_pins_by_id_else_falls_back_to_name_lookup(monkeypatch):
    client = SimpleNamespace(get_or_create_folder=lambda name, parent_id=None: {"id": "by-name", "name": name})

    monkeypatch.delenv("DVSU_RESEARCH_DRIVE_FOLDER_ID", raising=False)
    assert v2.research_root_folder(client) == {"id": "by-name", "name": "StoryEngine Research"}

    monkeypatch.setenv("DVSU_RESEARCH_DRIVE_FOLDER_ID", "  1cPXLQN1  ")
    assert v2.research_root_folder(client) == {"id": "1cPXLQN1"}


def test_both_drive_exports_write_under_the_pinned_root(monkeypatch):
    import sys
    import dvsu_research_v2 as research_v2

    made, uploads = [], []

    class FakeClient:
        def __init__(self, **kw): pass
        def get_or_create_folder(self, name, parent_id=None):
            made.append((name, parent_id))
            return {"id": f"id:{name}"}
        def upload_file(self, content, name, folder_id, mime_type=None):
            uploads.append(folder_id)
            return {"id": "f"}

    monkeypatch.setitem(sys.modules, "shared.clients.google_client",
                        SimpleNamespace(GoogleClient=FakeClient))
    monkeypatch.setenv("DVSU_RESEARCH_DRIVE_FOLDER_ID", "PINNED")

    out = v2._export_thesis_roster_to_drive("Vid", {"thesis": "T", "acts": [], "unit_roster": []})
    assert ("Vid", "PINNED") in made and ("StoryEngine Research", None) not in made
    assert out["folder_id"] == "id:Vid"

    made.clear()
    research_v2._export_machine_packet_to_drive("Vid", {"machine": "Ajax class"})
    assert made[0] == ("Vid", "PINNED")
    assert all(name != "StoryEngine Research" for name, _ in made)


def test_story_call_that_drops_a_machine_fails_closed():
    client = _Client(json.dumps({"thesis": "T", "acts": [{"act_number": 1, "argument": "A"}],
                                 "roster": [{"machine": "R-4 Hoverfly", "act_number": 1}]}))
    with pytest.raises(ValueError, match="UH-1 Iroquois"):
        asyncio.run(v2._call_story_for_roster(client, "Every X", ["R-4 Hoverfly", "UH-1 Iroquois"], None))
