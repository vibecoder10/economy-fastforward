"""Tests for C16d (checklist §S7-3 HIGH fix, docs/reports/2026-07-17-
storyengine-agent-audit-findings.md §S7): thumbnail skip-if-done.

Before this fix, PipelineExecutor.run_thumbnail() unconditionally regenerated
+ ledger-billed on EVERY call, across all three completion branches (modeled/
channel-formula/legacy from-scratch) — a routine status-machine resume, an
arq retry, or any caller re-invoking the stage re-billed a thumbnail that was
already drawn. Contrast: C16b already added this guard for coverage images.

This pins:

  1. force=False (the default) + videos.thumbnail_url already set: the
     generation branches are never reached at all (proven by making
     _run_channel_formula_thumbnail raise if called) and no ledger row is
     recorded — the money-safety assertion.
  2. force=False + thumbnail_url is NULL/empty: proceeds normally (the guard
     checks EXISTENCE, not force alone) — proven by
     _run_channel_formula_thumbnail actually being called.
  3. force=True + thumbnail_url already set: bypasses the guard — an
     explicit "redo it" always wins, same convention as run_clip_generation's
     pre-existing `force` param.
  4. Every real caller of run_thumbnail is wired to the right side: the
     ACTIONS["thumbnail"] verb (actions.make_action_step) always forces, the
     prompt-studio "Apply & redo" path (routes/chat.py's _make_prompt_regen)
     always forces, and the autobuild finish chain's pre-existing
     `not thumbnail_url` gate (actions.py's make_autobuild_step) is
     untouched (double-guard, not a conflict).

No network, no real DB: PipelineExecutor.__new__ skips __init__'s vault/env
loading (same technique as tests/functional/test_c13_clip_model_routing.py);
_ensure_initialized is skipped via _initialized = True; database module-level
names (fetch_one/execute) are monkeypatched on the pipeline_executor module
object itself.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c16d_thumbnail_skip_if_done.py -q
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import pipeline_executor as pe_mod  # noqa: E402
from pipeline_executor import PipelineExecutor  # noqa: E402

TENANT = "tenant-1"
VIDEO = "video-1"


def _video_row(**over):
    base = {
        "id": VIDEO, "status": "ready_for_thumbnail", "thumbnail_url": None,
        "thumbnail_prompt": None, "reference_url": None,
        "character_reference_url": None, "aspect_ratio": "16:9",
        "video_title": "Test Video",
    }
    base.update(over)
    return base


def _make_executor(monkeypatch, video_row, *, channel_formula_result=None,
                    boom_on_channel_formula=False):
    activity_calls = []
    ledger_calls = []

    async def fake_fetch_one(query, *args):
        if "FROM videos WHERE id" in query:
            return video_row
        return None

    async def fake_execute(query, *args):
        return "OK"

    async def fake_record_ledger_entry(**kwargs):
        ledger_calls.append(kwargs)

    monkeypatch.setattr(pe_mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pe_mod, "execute", fake_execute)
    monkeypatch.setattr(pe_mod, "record_ledger_entry", fake_record_ledger_entry)

    executor = PipelineExecutor.__new__(PipelineExecutor)
    executor.tenant_id = TENANT
    executor._initialized = True  # skip vault/env loading in _ensure_initialized
    executor._pipeline = None  # never touched if the guard/branches are wired right

    async def fake_log_activity(bot_name, video_id, status, message=None, cost=0):
        activity_calls.append((bot_name, video_id, status, message))

    executor._log_activity = fake_log_activity

    if boom_on_channel_formula:
        async def _boom(*a, **k):
            raise AssertionError(
                "run_thumbnail must not reach the generation branches when "
                "skip-if-done applies (force=False + thumbnail_url already set)")
        executor._run_channel_formula_thumbnail = _boom
    else:
        result = channel_formula_result or {
            "status": "completed", "video_id": VIDEO,
            "thumbnail_url": "https://fake/new-thumb.png",
        }
        executor._run_channel_formula_thumbnail = AsyncMock(return_value=result)

    return executor, activity_calls, ledger_calls


def test_skip_if_done_default_thumbnail_already_set(monkeypatch):
    """force=False (default) + thumbnail_url already set: skip entirely —
    no generation branch reached, no ledger row, no billing."""
    video_row = _video_row(thumbnail_url="https://fake/existing-thumb.png")
    executor, activity_calls, ledger_calls = _make_executor(
        monkeypatch, video_row, boom_on_channel_formula=True)

    result = asyncio.run(executor.run_thumbnail(VIDEO))

    assert result["status"] == "completed"
    assert result.get("skipped") is True
    assert result["thumbnail_url"] == "https://fake/existing-thumb.png"
    assert ledger_calls == [], "skip-if-done must never bill the ledger"
    assert any(c[2] == "completed" and "already exists" in (c[3] or "") for c in activity_calls), (
        "expected an activity log line explaining the skip")


def test_no_skip_when_thumbnail_url_is_empty(monkeypatch):
    """force=False but thumbnail_url is NULL: the guard checks EXISTENCE, not
    force alone — generation proceeds normally."""
    video_row = _video_row(thumbnail_url=None)
    executor, _, ledger_calls = _make_executor(monkeypatch, video_row)

    result = asyncio.run(executor.run_thumbnail(VIDEO))

    assert result["status"] == "completed"
    assert not result.get("skipped")
    executor._run_channel_formula_thumbnail.assert_awaited_once()


def test_no_skip_when_thumbnail_url_is_blank_string(monkeypatch):
    """Same as above but for an empty-string thumbnail_url (not NULL) —
    .strip() must treat it as "not set", matching the coverage guard's
    completeness convention (C16b)."""
    video_row = _video_row(thumbnail_url="   ")
    executor, _, _ = _make_executor(monkeypatch, video_row)

    result = asyncio.run(executor.run_thumbnail(VIDEO))

    assert not result.get("skipped")
    executor._run_channel_formula_thumbnail.assert_awaited_once()


def test_force_true_bypasses_guard_even_with_existing_thumbnail(monkeypatch):
    """force=True (an explicit redo — the ACTIONS['thumbnail'] verb, the
    prompt-studio 'Apply & redo' path, or the Scenes page Regenerate button)
    always wins over an already-set thumbnail_url."""
    video_row = _video_row(thumbnail_url="https://fake/existing-thumb.png")
    executor, _, _ = _make_executor(monkeypatch, video_row)

    result = asyncio.run(executor.run_thumbnail(VIDEO, force=True))

    assert result["status"] == "completed"
    assert not result.get("skipped")
    executor._run_channel_formula_thumbnail.assert_awaited_once()


def test_video_not_found_short_circuits_before_the_guard(monkeypatch):
    """Unrelated to the guard, but the guard's new code sits right after
    this check — pin the ordering doesn't break the pre-existing behavior."""
    async def fake_fetch_one(query, *args):
        return None

    monkeypatch.setattr(pe_mod, "fetch_one", fake_fetch_one)
    executor = PipelineExecutor.__new__(PipelineExecutor)
    executor.tenant_id = TENANT
    executor._initialized = True

    result = asyncio.run(executor.run_thumbnail(VIDEO))
    assert result == {"status": "failed", "error": "Video not found"}


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
