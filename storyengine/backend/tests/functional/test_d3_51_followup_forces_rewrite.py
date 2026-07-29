"""Tests for D3-51: a confirmed chat follow-up edit must force run_script's
real rewrite path, never the "supplied script verbatim" shortcut.

Proven live on prod 2026-07-28, video 686b4651-e495-44be-baf6-97fc6dd527e9:
a chat follow-up edit ("add dialogue between the elites and Nyla...") was
confirmed by the user. The confirm POST correctly appended the change onto
videos.writer_guidance (routes/chat.py's _apply_followup_edit /
actions.apply_followup_edit — verified in DB). One second later,
PipelineExecutor.run_script's

    if (video.get("script_source") or "generated") == "user_supplied" \\
            and (video.get("script") or "").strip():

guard fired anyway (bot_activity row 42a1f495: bot_name="Script Bot",
status="completed", message="Using your supplied script verbatim", cost=0)
and the scripts rows were never touched — the user's confirmed, paid
rewrite request was silently discarded while the bot reported success.

Fix: run_script gained a `force_rewrite` kwarg that turns the guard's
condition into "... and not force_rewrite". actions.make_action_step
threads it to run_script's kwargs, and routes/chat.py's _run_pending_action
sets it True exactly when this dispatch just applied a follow-up edit
(cfg["edit"] and pending["change"] — the same condition that writes the
guidance in the first place). A plain re-run with no pending change (the
ordinary queue/autopilot pass-through the guard exists for) leaves
force_rewrite False and is byte-for-byte unaffected.

This file pins two things at the PipelineExecutor.run_script level:

  1. force_rewrite=True + script_source='user_supplied' + a non-empty
     script: the shortcut is NEVER taken (no "verbatim" activity log, no
     early-return "completed") — the run reaches the real generation call
     (self._pipeline.run_brief_translator). Zero paid/LLM calls: the
     translator is a stub that returns an error immediately, proving only
     that the real path was REACHED, not exercising real generation.
  2. force_rewrite=False (the default — every existing caller before this
     fix, and every plain re-run after it): the exact same video takes the
     verbatim shortcut untouched — self._pipeline.run_brief_translator is a
     tripwire that raises AssertionError if ever called, proving generation
     is never reached for the ordinary case this guard exists to serve.

No network, no real DB: PipelineExecutor.__new__ skips __init__'s vault/env
loading (same technique as tests/functional/test_c16d_thumbnail_skip_if_
done.py); _ensure_initialized is skipped via _initialized = True; database
module-level names (fetch_one/fetch_all/execute) are monkeypatched on the
pipeline_executor module object itself. Instance methods this test doesn't
care about (_load_prompt_overrides, _inject_learnings_into_writer_guidance,
_load_idea_from_video) are stubbed directly — they do their own DB/identity
work that is orthogonal to the guard this fix changes.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_d3_51_followup_forces_rewrite.py -q
"""
import asyncio
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import pipeline_executor as pe_mod  # noqa: E402
from pipeline_executor import PipelineExecutor  # noqa: E402

TENANT = "tenant-1"
VIDEO = "video-1"


def _user_supplied_video_row(**over):
    """A video that genuinely counts as 'supplied' — script_source ==
    'user_supplied' and a non-empty script — the exact shape that made
    video 686b4651-e495-44be-baf6-97fc6dd527e9 take the shortcut."""
    base = {
        "id": VIDEO,
        "status": "ready_for_scripting",
        "script_source": "user_supplied",
        "script": "EXT. FACTORY - DAY\n\nThe elites survey the floor in silence.",
        "research_payload": None,
        "source": None,
        "script_system_prompt": None,
        "render_mode": None,
        "pipeline_stages": None,
        "skip_voice": False,
        "video_title": "Test Video",
        "headline": None,
    }
    base.update(over)
    return base


def _make_executor(monkeypatch, video_row, *, run_brief_translator):
    activity_calls = []
    executed_calls = []

    async def fake_fetch_one(query, *args):
        if "FROM videos WHERE id" in query:
            return video_row
        return None

    async def fake_fetch_all(query, *args):
        # The LOCKED-cast query in run_script — no locked cast for this test.
        return []

    async def fake_execute(query, *args):
        executed_calls.append((query, args))
        return "OK"

    monkeypatch.setattr(pe_mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pe_mod, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(pe_mod, "execute", fake_execute)

    executor = PipelineExecutor.__new__(PipelineExecutor)
    executor.tenant_id = TENANT
    executor._initialized = True  # skip vault/env loading in _ensure_initialized

    async def fake_log_activity(bot_name, video_id, status, message=None, cost=0):
        activity_calls.append((bot_name, video_id, status, message))

    executor._log_activity = fake_log_activity
    # Orthogonal to this fix's guard — stub out so this test only exercises
    # the shortcut-vs-rewrite branch, not prompt-override/identity/learning
    # plumbing that has its own tests.
    executor._load_prompt_overrides = AsyncMock(return_value=None)
    executor._inject_learnings_into_writer_guidance = AsyncMock(return_value=None)
    executor._load_idea_from_video = MagicMock(return_value=None)
    executor._pipeline = types.SimpleNamespace(run_brief_translator=run_brief_translator)

    return executor, activity_calls, executed_calls


def test_force_rewrite_bypasses_verbatim_shortcut_on_confirmed_change(monkeypatch):
    """force_rewrite=True (set by actions.make_action_step only when a chat
    follow-up edit was just applied) must skip the verbatim shortcut
    entirely and reach the real generation call — the D3-51 fix."""
    video_row = _user_supplied_video_row()
    # Stub the real generation entry point: returning an "error" short-
    # circuits run_script's own `if result.get("error"): raise ...` a few
    # lines later, which the outer except turns into a clean "failed"
    # result — proving the call happened without touching any real LLM.
    translator = AsyncMock(return_value={"error": "TEST_SENTINEL_REACHED_REWRITE"})
    executor, activity_calls, _ = _make_executor(
        monkeypatch, video_row, run_brief_translator=translator)

    result = asyncio.run(executor.run_script(VIDEO, force_rewrite=True))

    translator.assert_awaited_once()
    assert result["status"] == "failed"
    assert result["error"] == "TEST_SENTINEL_REACHED_REWRITE"
    assert not any(
        c[2] == "completed" and "verbatim" in (c[3] or "").lower()
        for c in activity_calls
    ), "force_rewrite=True must never log the verbatim-shortcut success line"


def test_plain_rerun_still_takes_verbatim_path_untouched(monkeypatch):
    """force_rewrite defaults to False — the ordinary re-run / queue /
    autopilot pass-through case this guard exists for is byte-for-byte
    unaffected: the verbatim shortcut fires, generation is never reached."""
    video_row = _user_supplied_video_row()

    async def _boom(*a, **k):
        raise AssertionError(
            "run_script must not reach real generation when force_rewrite "
            "is False and the video is genuinely user_supplied verbatim")

    executor, activity_calls, executed_calls = _make_executor(
        monkeypatch, video_row, run_brief_translator=_boom)

    result = asyncio.run(executor.run_script(VIDEO))  # force_rewrite omitted -> False

    assert result["video_id"] == VIDEO
    assert result["status"] != "failed"
    assert any(
        c[2] == "completed" and "verbatim" in (c[3] or "").lower()
        for c in activity_calls
    ), "expected the 'Using your supplied script verbatim' activity line"
    # The shortcut's own status-advance path ran (real _update_video_status /
    # _log_transition, both of which only call the stubbed `execute`) —
    # confirms this branch's side effects are untouched by the fix.
    assert any("UPDATE videos SET status" in q for q, _ in executed_calls)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
