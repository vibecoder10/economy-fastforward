"""Run All must expose an incomplete stage rather than report completion."""
import asyncio
import sys
import types
from unittest.mock import AsyncMock, patch

import actions


def _build(*, thumbnail_result=None, saved_thumbnail=None, step_result=None,
           initial_status="ready_for_thumbnail", voice_result=None, voice_saved=True,
           preloop_missing=False, delivery_mode="render_only", delivered_result=None,
           continuous=False, kill_switch=False):
    video = {"status": initial_status, "render_mode": "static_docu", "thumbnail_url": None}
    statuses = []
    advances = []
    calls = []
    voice_calls = []

    class Executor:
        async def _get_video(self, _id):
            return dict(video)

        async def run_next_step(self, _id):
            calls.append(video["status"])
            return step_result or {"status": "needs_approval"}

        async def run_thumbnail(self, _id):
            if isinstance(thumbnail_result, Exception):
                raise thumbnail_result
            video["thumbnail_url"] = saved_thumbnail
            return thumbnail_result or {"status": "completed"}

        async def run_voice(self, _id, **_kw):
            voice_calls.append(_id)
            if isinstance(voice_result, Exception):
                raise voice_result
            return voice_result or {"status": "completed"}

    async def fetch(query, *_args):
        if "FROM production_queue" in query:
            return {"continuous": continuous}
        if "FROM scripts" in query:
            if (preloop_missing and not voice_calls) or (voice_calls and not voice_saved):
                return {"x": 1}
            return None
        return {**video, "pipeline_stages": None}

    async def execute(query, *args):
        if "UPDATE videos SET status=" in query:
            advances.append(args[0])
            video["status"] = "complete"
        return "UPDATE 1"

    pe = types.ModuleType("pipeline_executor")
    pe.PipelineExecutor = lambda _tenant: Executor()
    route = types.ModuleType("routes.pipeline")
    route._set_task_status = lambda _id, status, msg, **_kw: statuses.append((status, msg))
    route._clear_task_status = lambda *_a: None
    claims = types.ModuleType("generation_claims")
    claims.release = AsyncMock()
    delivery = types.ModuleType("queue_delivery")
    delivery.deliver_queue_video = AsyncMock(return_value=delivered_result or {"status": "completed"})
    dial = types.ModuleType("autopilot_dial")
    dial.get_autopilot_dial = AsyncMock(return_value=types.SimpleNamespace(kill_switch_tripped_at="now" if kill_switch else None))
    dial.check_weekly_budget = AsyncMock(return_value=(True, 0, None))
    with patch.dict(sys.modules, {"pipeline_executor": pe, "routes.pipeline": route, "generation_claims": claims, "queue_delivery": delivery, "autopilot_dial": dial}), \
         patch.object(actions, "fetch_one", fetch), patch.object(actions, "execute", execute), \
         patch("asyncio.sleep", AsyncMock()):
        asyncio.run(actions.make_autobuild_step("tenant", "video", target="finish",
                    delivery_mode=delivery_mode, expected_channel_id="channel" if delivery_mode == "youtube_unlisted" else None)())
    if delivery_mode == "render_only":
        delivery.deliver_queue_video.assert_not_awaited()
    return statuses, advances, calls


def test_failed_thumbnail_cannot_advance_to_render():
    statuses, advances, _ = _build(thumbnail_result={"status": "failed", "error": "Provider unavailable"})
    assert statuses[-1] == ("failed", "Provider unavailable")
    assert advances == []


def test_success_without_persisted_thumbnail_cannot_advance():
    statuses, advances, _ = _build()
    assert statuses[-1][0] == "failed"
    assert "saved image" in statuses[-1][1]
    assert advances == []


def test_thumbnail_exception_is_visible():
    statuses, advances, _ = _build(thumbnail_result=RuntimeError("timeout"))
    assert statuses[-1] == ("failed", "Thumbnail failed: timeout")
    assert advances == []


def test_saved_thumbnail_allows_advancement():
    _statuses, advances, _calls = _build(saved_thumbnail="https://example.test/thumb.jpg")
    assert advances


def test_review_failure_keeps_the_actual_reason():
    statuses, advances, calls = _build(step_result={"status": "needs_review", "message": "Wrong carrier identity"})
    assert statuses[-1] == ("failed", "Wrong carrier identity")
    assert advances == []
    assert len(calls) == 1


def test_no_progress_is_failure_not_completion():
    statuses, advances, calls = _build(step_result={"status": "completed"})
    assert statuses[-1][0] == "failed"
    assert "without advancing" in statuses[-1][1]
    assert advances == []
    assert len(calls) == 1


def test_voice_provider_failure_does_not_advance():
    statuses, advances, _ = _build(initial_status="ready_for_voice", voice_result={"status": "failed", "error": "Voice quota exhausted"})
    assert statuses[-1] == ("failed", "Narration failed: Voice quota exhausted")
    assert not advances


def test_voice_success_without_saved_audio_does_not_advance():
    statuses, advances, _ = _build(initial_status="ready_for_voice", voice_saved=False)
    assert statuses[-1][0] == "failed"
    assert "still missing" in statuses[-1][1]
    assert not advances


def test_resumed_finish_cannot_swallow_voice_exception():
    statuses, advances, _ = _build(preloop_missing=True, voice_result=RuntimeError("timeout"))
    assert statuses[-1] == ("failed", "Narration failed: timeout")
    assert not advances


def test_saved_voice_allows_advancement():
    statuses, advances, _ = _build(initial_status="ready_for_voice")
    assert advances


def test_rendered_video_requires_verified_unlisted_delivery_when_selected():
    statuses, advances, _ = _build(initial_status="rendered", delivery_mode="youtube_unlisted", delivered_result={"status": "failed", "error": "Channel readback mismatch"})
    assert statuses[-1] == ("failed", "Channel readback mismatch")
    assert not advances


def test_verified_unlisted_delivery_completes_without_new_render():
    statuses, advances, _ = _build(initial_status="rendered", delivery_mode="youtube_unlisted")
    assert statuses[-1][0] == "completed"
    assert "unlisted" in statuses[-1][1]
    assert not advances


def test_render_only_does_not_upload():
    statuses, advances, _ = _build(initial_status="rendered")
    assert statuses[-1][0] == "completed"
    assert not advances


def test_continuous_kill_switch_stops_before_resumed_voice_or_next_stage():
    statuses, advances, calls = _build(continuous=True, kill_switch=True, preloop_missing=True,
                                      voice_result=AssertionError("must not generate"))
    assert statuses[-1][0] == "failed"
    assert "kill switch" in statuses[-1][1]
    assert not advances
    assert not calls
