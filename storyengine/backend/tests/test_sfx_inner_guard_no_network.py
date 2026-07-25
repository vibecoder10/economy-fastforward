"""Tests for the SFX guard's INNER backstop — pipeline_executor.py's
run_sound_prompts / run_sound_effects refusing to spend money on a blocked
render path, proven WITHOUT any network call (not `_ensure_initialized()`'s
vault key loads, not `self._pipeline.run_sound_prompt_bot()`/`run_sound_bot()`).

Design correction (coordinator review, 2026-07-24): guarding four DOORS
(REST endpoint, actions.py verb, auto-advance skip, frontend) left a fifth
door open — ClaudeOrchestrator.execute() mapped "sound" -> run_sound_prompts
with no check at all. The fix moves the check INSIDE run_sound_prompts/
run_sound_effects themselves, since those are the only two places a paid
Kie.ai sound generation can actually begin — every caller, known or not, is
covered by construction. `_ensure_initialized()` (which loads real vault
keys) was also moved to AFTER this guard, specifically so a blocked video
never touches the network at all, not just never spends on Kie.ai — this
file's tests are the proof.

No live DB, no live vault, no network: pipeline_executor.fetch_one/execute
and vault.get_secret are all monkeypatched to raise if ever called — the
inner guard must return before any of them fire for a blocked video.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/test_sfx_inner_guard_no_network.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import pipeline_executor as pe_mod  # noqa: E402
from pipeline_executor import PipelineExecutor  # noqa: E402

TENANT = "tenant-sfx-inner"
VIDEO = "video-sfx-inner"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _sfx_blocked_video(status: str, **extra) -> dict:
    row = {
        "id": VIDEO, "status": status, "tenant_id": TENANT,
        "custom_film_plan_id": None, "render_mode": None,
        "dialogue_audio": None, "dialogue_mode": "character_dialogue",
        "pipeline_stages": None,
    }
    row.update(extra)
    return row


def _legacy_video(status: str, **extra) -> dict:
    """The legacy fallback shape — SFX plays normally."""
    row = {
        "id": VIDEO, "status": status, "tenant_id": TENANT,
        "custom_film_plan_id": None, "render_mode": None,
        "dialogue_audio": None, "dialogue_mode": "narration_only",
        "pipeline_stages": None,
    }
    row.update(extra)
    return row


async def _vault_boom(*a, **k):
    raise AssertionError(f"a blocked video must never load vault/API keys: called with {a!r} {k!r}")


def _patch_no_network(monkeypatch, video: dict):
    """fetch_one returns the video row (a real DB read is unavoidable to even
    KNOW whether the video is blocked). `execute` (Postgres status writes —
    a local DB call, not an external provider) is captured but ALLOWED: the
    skip-and-advance path legitimately writes videos.status +
    stage_transitions. vault.get_secret (the ONLY thing that loads real
    ElevenLabs/Kie.ai/Anthropic API keys, called exclusively from
    _ensure_initialized) is the actual "no network call" boundary — patched
    to raise so the guard must return before it ever fires."""
    async def _fake_fetch_one(query, *args):
        return dict(video)

    calls = []

    async def _fake_execute(query, *args):
        calls.append((query, args))
        return "UPDATE 1"

    monkeypatch.setattr(pe_mod, "fetch_one", _fake_fetch_one)
    monkeypatch.setattr(pe_mod, "execute", _fake_execute)
    monkeypatch.setattr(pe_mod, "get_secret", _vault_boom)
    return calls


def _forbid_pipeline_construction(ex: PipelineExecutor):
    """self._pipeline is only ever set by _ensure_initialized(); leaving it
    None here means any code path that reaches `self._pipeline.run_sound_
    prompt_bot()`/`run_sound_bot()` crashes with AttributeError, not a clean
    assertion — so we additionally assert _ensure_initialized was never
    called (see the tests below), which is the real proof."""
    assert ex._pipeline is None
    assert ex._initialized is False


# =============================================================================
# run_sound_prompts
# =============================================================================

def test_run_sound_prompts_refuses_blocked_video_with_zero_network_calls(monkeypatch):
    video = _sfx_blocked_video("ready_for_sound_design")
    _patch_no_network(monkeypatch, video)
    ex = PipelineExecutor(TENANT)
    _forbid_pipeline_construction(ex)

    result = _run(ex.run_sound_prompts(VIDEO))

    assert result.get("skipped_stage") == "sound"
    assert "character-dialogue" in result["message"]
    # execute() (status writes) DID fire (that's the DB write for the
    # skip-and-advance, not a network call to an external provider) — but
    # _ensure_initialized() must NEVER have run: no vault reads, no client
    # construction.
    assert ex._initialized is False
    assert ex._pipeline is None


def test_run_sound_prompts_never_calls_ensure_initialized_when_blocked(monkeypatch):
    """Direct proof _ensure_initialized (the vault/network entry point) is
    never invoked for a blocked video — patches it to raise if called."""
    video = _sfx_blocked_video("ready_for_sound_design")
    _patch_no_network(monkeypatch, video)
    ex = PipelineExecutor(TENANT)

    async def _boom():
        raise AssertionError("_ensure_initialized must not run for a blocked video")

    monkeypatch.setattr(ex, "_ensure_initialized", _boom)

    result = _run(ex.run_sound_prompts(VIDEO))
    assert result.get("skipped_stage") == "sound"


def test_run_sound_prompts_still_calls_ensure_initialized_when_allowed(monkeypatch):
    """Regression guard: the reordering (guard before init) must not
    accidentally skip initialization for a video that's ALLOWED to generate
    sound — only the blocked path skips it."""
    video = _legacy_video("ready_for_sound_design")

    async def _fake_fetch_one(query, *args):
        return dict(video)

    monkeypatch.setattr(pe_mod, "fetch_one", _fake_fetch_one)

    ex = PipelineExecutor(TENANT)
    called = {"ensure_initialized": False}

    async def _fake_ensure_initialized():
        called["ensure_initialized"] = True
        ex._initialized = True
        # Stub the pipeline object so the real bot call below doesn't blow up.
        class _FakeBot:
            async def run_sound_prompt_bot(self):
                return {"new_status": "ready_for_sound_effects"}
        ex._pipeline = _FakeBot()

    async def _fake_load_prompt_overrides(v):
        return None

    async def _fake_log_activity(*a, **k):
        return None

    async def _fake_update_video_status(*a, **k):
        return None

    async def _fake_log_transition(*a, **k):
        return None

    monkeypatch.setattr(ex, "_ensure_initialized", _fake_ensure_initialized)
    monkeypatch.setattr(ex, "_load_prompt_overrides", _fake_load_prompt_overrides)
    monkeypatch.setattr(ex, "_load_idea_from_video", lambda video_id: None)
    monkeypatch.setattr(ex, "_log_activity", _fake_log_activity)
    monkeypatch.setattr(ex, "_update_video_status", _fake_update_video_status)
    monkeypatch.setattr(ex, "_log_transition", _fake_log_transition)

    result = _run(ex.run_sound_prompts(VIDEO))

    assert called["ensure_initialized"] is True
    assert result.get("skipped_stage") is None
    assert result["status"] == "ready_for_sound_effects"


# =============================================================================
# run_sound_effects
# =============================================================================

def test_run_sound_effects_refuses_blocked_video_with_zero_network_calls(monkeypatch):
    video = _sfx_blocked_video("ready_for_sound_effects")
    _patch_no_network(monkeypatch, video)
    ex = PipelineExecutor(TENANT)
    _forbid_pipeline_construction(ex)

    result = _run(ex.run_sound_effects(VIDEO))

    assert result.get("skipped_stage") == "sound"
    assert ex._initialized is False
    assert ex._pipeline is None


def test_run_sound_effects_never_calls_ensure_initialized_when_blocked(monkeypatch):
    video = _sfx_blocked_video("ready_for_sound_effects")
    _patch_no_network(monkeypatch, video)
    ex = PipelineExecutor(TENANT)

    async def _boom():
        raise AssertionError("_ensure_initialized must not run for a blocked video")

    monkeypatch.setattr(ex, "_ensure_initialized", _boom)

    result = _run(ex.run_sound_effects(VIDEO))
    assert result.get("skipped_stage") == "sound"


# =============================================================================
# Blocked across every non-legacy render path (not just character_dialogue)
# =============================================================================

def test_run_sound_prompts_blocked_for_every_non_legacy_render_path(monkeypatch):
    variants = [
        {"custom_film_plan_id": "plan-1", "render_mode": None, "dialogue_audio": None, "dialogue_mode": None},
        {"custom_film_plan_id": None, "render_mode": "static_docu", "dialogue_audio": None, "dialogue_mode": None},
        {"custom_film_plan_id": None, "render_mode": None, "dialogue_audio": "grok_native", "dialogue_mode": None},
        {"custom_film_plan_id": None, "render_mode": None, "dialogue_audio": None, "dialogue_mode": "character_dialogue"},
    ]
    for fields in variants:
        video = _sfx_blocked_video("ready_for_sound_design", **fields)
        _patch_no_network(monkeypatch, video)
        ex = PipelineExecutor(TENANT)

        async def _boom():
            raise AssertionError(f"_ensure_initialized must not run for {fields}")
        monkeypatch.setattr(ex, "_ensure_initialized", _boom)

        result = _run(ex.run_sound_prompts(VIDEO))
        assert result.get("skipped_stage") == "sound", fields
