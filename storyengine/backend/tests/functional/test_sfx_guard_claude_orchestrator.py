"""Tests for the SFX guard's coverage of the ClaudeOrchestrator path
(claude_orchestrator.py) — the BLOCKER found in independent review
(2026-07-24): `ClaudeOrchestrator.execute()` mapped `"sound" ->
executor.run_sound_prompts` with no SFX check at all, reached from
`PipelineExecutor.run_next_step()` BEFORE `_run_next_step_status_map` (the
function the first pass patched) is ever consulted, whenever a tenant's
`claude_orchestration` vault flag is on. `_fallback_decision()` (used when
the live Claude API call itself fails) was equally blind.

Three layers, each tested here:
  1. `_build_context_prompt` — a nudge INSIDE the prompt Claude reads, telling
     it not to propose "sound" for a blocked video, with the render-path
     reason. Cost-saving, not enforcement (decide() is a real Claude API
     call - not exercised here; only the deterministic prompt-building
     logic is).
  2. `execute()` — the fail-fast layer every decision (from decide() OR from
     _fallback_decision()) converges on before `run_sound_prompts` is ever
     called. Delegates to the SAME `PipelineExecutor._skip_sound_stage` the
     status-map guard and run_sound_prompts/run_sound_effects's own inner
     guard use, so the video actually advances here too — not a dead-end
     "skip" that parks it.
  3. `_fallback_decision()` — deliberately UNCHANGED (still proposes
     skill_id="sound" for a blocked video when the status naively matches) —
     pinned here to prove execute() is what catches it, not a duplicate
     check inside the fallback itself (see that function's docstring for why).

The real backstop (pipeline_executor.run_sound_prompts/run_sound_effects's
own render_path_plays_sfx check) is covered in
tests/test_sfx_inner_guard_no_network.py — this file is about the
orchestrator layer specifically, so even if run_sound_prompts is called
directly (bypassing execute() somehow), that inner guard still holds.

No live DB, no live Claude API: claude_orchestrator.fetch_one is
monkeypatched; decide()'s actual anthropic.Anthropic() call is never
exercised (only _build_context_prompt, execute(), and _fallback_decision
are — all pure/DB-only, no LLM call).

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_sfx_guard_claude_orchestrator.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import claude_orchestrator as co_mod  # noqa: E402
from claude_orchestrator import ClaudeOrchestrator, Decision  # noqa: E402
import pipeline_executor as pe_mod  # noqa: E402
from pipeline_executor import PipelineExecutor  # noqa: E402

TENANT = "tenant-co-sfx"
VIDEO = "video-co-sfx"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _sfx_blocked_video(status: str = "ready_for_sound_design", **extra) -> dict:
    row = {
        "id": VIDEO, "status": status, "tenant_id": TENANT, "video_title": "Blocked Video",
        "custom_film_plan_id": None, "render_mode": None,
        "dialogue_audio": None, "dialogue_mode": "character_dialogue",
        "pipeline_stages": None,
    }
    row.update(extra)
    return row


def _legacy_video(status: str = "ready_for_sound_design", **extra) -> dict:
    row = {
        "id": VIDEO, "status": status, "tenant_id": TENANT, "video_title": "Legacy Video",
        "custom_film_plan_id": None, "render_mode": None,
        "dialogue_audio": None, "dialogue_mode": "narration_only",
        "pipeline_stages": None,
    }
    row.update(extra)
    return row


# =============================================================================
# 1. _build_context_prompt — the nudge inside the prompt
# =============================================================================

def test_build_context_prompt_warns_off_sound_for_blocked_video():
    orch = ClaudeOrchestrator(TENANT)
    video = _sfx_blocked_video()
    prompt = orch._build_context_prompt(video, "Available Skills:\n- sound: ...", [], [])
    assert 'Do NOT select skill_id "sound"' in prompt
    assert "character-dialogue" in prompt


def test_build_context_prompt_silent_for_legacy_video():
    orch = ClaudeOrchestrator(TENANT)
    video = _legacy_video()
    prompt = orch._build_context_prompt(video, "Available Skills:\n- sound: ...", [], [])
    assert "Do NOT select skill_id" not in prompt


# =============================================================================
# 2. execute() — the fail-fast layer every Decision converges on
# =============================================================================

class _FakeExecutor:
    """Stands in for PipelineExecutor in execute() — only the methods
    execute() actually touches need to exist. run_sound_prompts raises if
    called at all (the money-spend proof); _skip_sound_stage delegates to
    the REAL PipelineExecutor implementation (not reimplemented here) so
    this test exercises the actual skip-and-advance logic, not a stub of it.

    execute()'s `skill_to_method` dict literal accesses EVERY executor.*
    attribute up front (even the ones the current decision doesn't pick), so
    __getattr__ backstops any method name we didn't explicitly stub with a
    harmless no-op async callable — only the ones under test need real
    behavior.
    """
    def __init__(self, real: PipelineExecutor):
        self._real = real
        self.sound_prompts_called = False

    async def run_sound_prompts(self, video_id):
        self.sound_prompts_called = True
        raise AssertionError("run_sound_prompts must never be called for a blocked video via execute()")

    async def run_research(self, video_id):
        return {"status": "researching", "video_id": video_id}

    async def _skip_sound_stage(self, video_id, video, current_status, natural_next):
        return await self._real._skip_sound_stage(video_id, video, current_status, natural_next)

    def __getattr__(self, name):
        async def _noop(*a, **k):
            raise AssertionError(f"unexpected call to executor.{name} in this test")
        return _noop


def _patch_fetch_one(monkeypatch, video: dict):
    async def _fake_fetch_one(query, *args):
        return dict(video)
    monkeypatch.setattr(co_mod, "fetch_one", _fake_fetch_one)

    # execute()'s "decided" bot_activity log fires on EVERY invoke_skill
    # decision (blocked or not) — stub it too so tests that never touch the
    # skip path don't need DATABASE_URL.
    async def _fake_execute(query, *args):
        return "INSERT 0 1"
    monkeypatch.setattr(co_mod, "execute", _fake_execute)


def _patch_pe_execute(monkeypatch):
    """PipelineExecutor._skip_sound_stage (used by _FakeExecutor above)
    writes status via pipeline_executor.execute — stub it so no live DB is
    touched, and capture calls for assertions."""
    calls = []

    async def _fake_execute(query, *args):
        calls.append((query, args))
        return "UPDATE 1"

    monkeypatch.setattr(pe_mod, "execute", _fake_execute)
    return calls


def test_execute_refuses_sound_and_advances_status_for_blocked_video(monkeypatch):
    video = _sfx_blocked_video("ready_for_sound_design")
    _patch_fetch_one(monkeypatch, video)
    calls = _patch_pe_execute(monkeypatch)

    orch = ClaudeOrchestrator(TENANT)
    real_pe = PipelineExecutor(TENANT)
    fake_executor = _FakeExecutor(real_pe)

    decision = Decision(action="invoke_skill", skill_id="sound",
                        reasoning="test", confidence=0.95)

    result = _run(orch.execute(decision, VIDEO, executor=fake_executor))

    assert result.success is True
    assert fake_executor.sound_prompts_called is False
    assert result.execution_result.get("skipped_stage") == "sound"
    assert result.execution_result["status"] == "ready_for_video_scripts"
    status_updates = [c for c in calls if "UPDATE videos SET status" in c[0]]
    assert len(status_updates) == 1
    assert status_updates[0][1][0] == "ready_for_video_scripts"


def test_execute_refuses_sound_for_blocked_video_at_sound_effects_status(monkeypatch):
    video = _sfx_blocked_video("ready_for_sound_effects")
    _patch_fetch_one(monkeypatch, video)
    _patch_pe_execute(monkeypatch)

    orch = ClaudeOrchestrator(TENANT)
    real_pe = PipelineExecutor(TENANT)
    fake_executor = _FakeExecutor(real_pe)

    decision = Decision(action="invoke_skill", skill_id="sound",
                        reasoning="test", confidence=0.95)
    result = _run(orch.execute(decision, VIDEO, executor=fake_executor))

    assert fake_executor.sound_prompts_called is False
    assert result.execution_result["status"] == "ready_for_video_scripts"


def test_execute_still_runs_sound_for_legacy_video(monkeypatch):
    """Regression: the guard must not block a video whose render path DOES
    play sound effects."""
    video = _legacy_video("ready_for_sound_design")
    _patch_fetch_one(monkeypatch, video)

    orch = ClaudeOrchestrator(TENANT)

    class _AllowedExecutor:
        def __init__(self):
            self.called_with = None

        async def run_sound_prompts(self, video_id):
            self.called_with = video_id
            return {"status": "ready_for_sound_effects", "video_id": video_id}

        def __getattr__(self, name):
            async def _noop(*a, **k):
                raise AssertionError(f"unexpected call to executor.{name} in this test")
            return _noop

    executor = _AllowedExecutor()
    decision = Decision(action="invoke_skill", skill_id="sound",
                        reasoning="test", confidence=0.95)

    result = _run(orch.execute(decision, VIDEO, executor=executor))

    assert executor.called_with == VIDEO
    assert result.success is True
    assert result.execution_result["status"] == "ready_for_sound_effects"


def test_execute_unaffected_for_non_sound_skills_on_blocked_video(monkeypatch):
    """The guard is scoped to skill_id=="sound" only — a blocked video must
    still be able to run every other skill normally."""
    video = _sfx_blocked_video("ready_for_video_scripts")
    _patch_fetch_one(monkeypatch, video)

    orch = ClaudeOrchestrator(TENANT)
    real_pe = PipelineExecutor(TENANT)
    fake_executor = _FakeExecutor(real_pe)

    decision = Decision(action="invoke_skill", skill_id="research",
                        reasoning="test", confidence=0.95)
    result = _run(orch.execute(decision, VIDEO, executor=fake_executor))

    assert result.success is True
    assert result.execution_result["status"] == "researching"


# =============================================================================
# 3. _fallback_decision — deliberately unchanged, execute() catches it
# =============================================================================

def test_fallback_decision_still_proposes_sound_for_blocked_video():
    """Pins the documented design: _fallback_decision does NOT special-case
    a blocked video — it's purely status-driven, same as before this guard
    existed. execute() (tested above) is what actually catches it."""
    orch = ClaudeOrchestrator(TENANT)
    video = _sfx_blocked_video("ready_for_sound_design")

    class _FakeSkill:
        skill_id = "sound"
        estimated_cost = 0.05

    class _FakeRegistry:
        def get_skills_for_status(self, status):
            return [_FakeSkill()] if status == "ready_for_sound_design" else []

    orch._registry = _FakeRegistry()
    decision = orch._fallback_decision(video)

    assert decision.action == "invoke_skill"
    assert decision.skill_id == "sound"


def test_fallback_decision_then_execute_end_to_end_refuses_spend(monkeypatch):
    """The full path claude_orchestrator._run_next_step_claude actually
    exercises when the live Claude call raises: decide() catches the
    exception -> _fallback_decision(video) -> execute(decision, ...). Wire
    both real steps together and prove no spend happens."""
    video = _sfx_blocked_video("ready_for_sound_design")
    _patch_fetch_one(monkeypatch, video)
    _patch_pe_execute(monkeypatch)

    orch = ClaudeOrchestrator(TENANT)

    class _FakeSkill:
        skill_id = "sound"
        estimated_cost = 0.05

    class _FakeRegistry:
        def get_skills_for_status(self, status):
            return [_FakeSkill()]

    orch._registry = _FakeRegistry()

    real_pe = PipelineExecutor(TENANT)
    fake_executor = _FakeExecutor(real_pe)

    decision = orch._fallback_decision(video)
    assert decision.skill_id == "sound"  # confirms the fallback DID propose it

    result = _run(orch.execute(decision, VIDEO, executor=fake_executor))

    assert fake_executor.sound_prompts_called is False
    assert result.execution_result.get("skipped_stage") == "sound"
