"""DVsU narration starts only from the reviewed saved machine script (dvsu_script_v2)."""
from __future__ import annotations

import types
from unittest.mock import AsyncMock

import pytest

import dvsu_script_v2
import pipeline_executor as pe


TENANT = "tenant-voice-gate"
VIDEO = "video-voice-gate"
ROSTER = ["SS-1 USS Holland", "SS-2 USS Plunger"]
BLOCKS = {
    ROSTER[0]: {"paragraph": "Reviewed Holland narration."},
    ROSTER[1]: {"paragraph": "Reviewed Plunger narration."},
}


def _video():
    return {
        "id": VIDEO,
        "status": "ready_for_voice",
        "render_mode": "static_docu",
        "research_payload": {},
        "script_validation": {"machine_script_blocks": BLOCKS},
    }


async def _run(monkeypatch, *, video, readiness=True, rows=None, roster=ROSTER):
    executor = object.__new__(pe.PipelineExecutor)
    executor.tenant_id = TENANT
    executor._pipeline = types.SimpleNamespace(run_voice_bot=AsyncMock())
    executor._ensure_initialized = AsyncMock()
    executor._get_video = AsyncMock(return_value=video)
    executor._log_activity = AsyncMock()
    entered = []

    def boundary(_video_id):
        entered.append("provider_boundary")
        raise RuntimeError("provider-boundary-sentinel")

    executor._load_idea_from_video = boundary
    monkeypatch.setattr(dvsu_script_v2, "script_readiness", lambda *_args: readiness)
    monkeypatch.setattr(pe, "_machine_documentary_hold_roster", lambda _video: roster)
    monkeypatch.setattr(pe, "fetch_all", AsyncMock(return_value=rows or []))
    return await executor.run_voice(VIDEO), executor, entered


@pytest.mark.asyncio
async def test_stale_script_readiness_blocks_voice_provider(monkeypatch):
    result, executor, entered = await _run(monkeypatch, video=_video(), readiness=False)

    assert result == {
        "status": "needs_review",
        "error": "Complete and review the saved machine script before generating voice.",
        "next_action": "complete_script",
        "stage": "script",
    }
    assert entered == []
    executor._pipeline.run_voice_bot.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [
    [],
    [{"scene": 1, "scene_text": "Wrong saved narration."}],
])
async def test_missing_or_mismatched_scenes_block_voice_provider(monkeypatch, rows):
    result, executor, entered = await _run(monkeypatch, video=_video(), rows=rows)

    assert result == {
        "status": "needs_review",
        "error": "Production scenes do not match the reviewed machine script.",
        "next_action": "save_reviewed_script",
        "stage": "script",
    }
    assert entered == []
    executor._pipeline.run_voice_bot.assert_not_awaited()


@pytest.mark.asyncio
async def test_exact_scenes_reach_provider_boundary(monkeypatch):
    rows = [{"scene": index, "scene_text": BLOCKS[machine]["paragraph"]}
            for index, machine in enumerate(ROSTER, 1)]
    result, executor, entered = await _run(monkeypatch, video=_video(), rows=rows)

    assert result == {"status": "failed", "error": "provider-boundary-sentinel"}
    assert entered == ["provider_boundary"]
    executor._pipeline.run_voice_bot.assert_not_awaited()


@pytest.mark.asyncio
async def test_video_without_a_locked_roster_retains_prior_provider_path(monkeypatch):
    """The gate is keyed on the roster, not on any contract flag: no roster, no gate."""
    result, executor, entered = await _run(monkeypatch, video=_video(), readiness=False, roster=[])

    assert result == {"status": "failed", "error": "provider-boundary-sentinel"}
    assert entered == ["provider_boundary"]
    executor._pipeline.run_voice_bot.assert_not_awaited()
