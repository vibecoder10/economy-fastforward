"""Run All must expose an incomplete stage rather than report completion."""
import asyncio
import sys
import types
from unittest.mock import AsyncMock, patch

import actions


def _build(*, thumbnail_result=None, saved_thumbnail=None, step_result=None,
           initial_status="ready_for_thumbnail", voice_result=None, voice_saved=True,
           preloop_missing=False, delivery_mode="render_only", delivered_result=None,
           continuous=False, kill_switch=False, script_result=None, factual_script_current=None, research_result=None):
    video = {"status": initial_status, "render_mode": "static_docu", "thumbnail_url": None}
    if factual_script_current is not None:
        video["research_payload"] = {"machine_script_contract": "factual_100_v1"}
        video["video_title"] = "Every British Aircraft Carrier Class Ever Built"
    if research_result is not None:
        video.setdefault("research_payload", {}).update({
            "unit_roster_validation": {"passed": True},
            "unit_research_hold_validation": {"units": [{"machine": "Majestic class", "passed": False}]},
        })
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

        async def run_research(self, _id):
            return research_result or {"status": "failed", "error": "Reached research before voice"}

        async def run_script(self, _id, **_kw):
            return script_result or {"status": "failed", "error": "Reached remaining script sections before voice"}

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
            video["status"] = args[0] if factual_script_current is not None else "complete"
        return "UPDATE 1"

    pe = types.ModuleType("pipeline_executor")
    pe.PipelineExecutor = lambda _tenant: Executor()
    pe._machine_documentary_hold_roster = lambda _v: ["Majestic class"]
    factual = types.ModuleType("factual_machine_pipeline")
    factual.factual_script_readiness = lambda _v, _r: factual_script_current
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
    with patch.dict(sys.modules, {"pipeline_executor": pe, "routes.pipeline": route, "generation_claims": claims, "queue_delivery": delivery, "autopilot_dial": dial, "factual_machine_pipeline": factual}), \
         patch.object(actions, "fetch_one", fetch), patch.object(actions, "execute", execute), \
         patch("asyncio.sleep", AsyncMock()):
        asyncio.run(actions.make_autobuild_step("tenant", "video", target="finish",
                    delivery_mode=delivery_mode, expected_channel_id="channel" if delivery_mode == "youtube_unlisted" else None)())
    if delivery_mode == "render_only":
        delivery.deliver_queue_video.assert_not_awaited()
    return statuses, advances, calls


def test_research_provider_limit_stops_before_roster_recovery():
    message = "Tavily is out of credits. Add credits, then resume; completed research is saved."
    statuses, advances, calls = _build(initial_status="idea_logged", factual_script_current=False, research_result={"status": "failed", "error": message})
    assert statuses[-1] == ("failed", message)
    assert advances == []
    assert calls == []


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


def test_partial_saved_script_does_not_skip_research_or_script_for_voice():
    for initial, expected in (
        ("idea_logged", "Reached research before voice"),
        ("ready_for_scripting", "Reached remaining script sections before voice"),
    ):
        statuses, advances, _ = _build(
            initial_status=initial, preloop_missing=True,
            voice_result=RuntimeError("Voice must not run for an incomplete script"),
        )
        assert statuses[-1] == ("failed", expected)
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


def test_script_pause_keeps_the_specific_reason_and_saved_progress():
    statuses, advances, _ = _build(initial_status="ready_for_scripting", script_result={
        "status":"paused", "message":"Video budget reached; completed sections are saved.",
    })
    assert statuses[-1] == ("completed", "Video budget reached; completed sections are saved.")
    assert not advances


def test_stale_factual_approval_returns_to_script_before_resumed_paid_work():
    for status, missing in [('ready_for_voice', True), ('ready_for_render', False)]:
        terminal, advances, next_calls = _build(
            initial_status=status, preloop_missing=missing, factual_script_current=False,
            voice_result=AssertionError('Stale topic approval must never reach narration'),
        )
        assert advances[0] == 'ready_for_scripting'
        assert terminal[-1] == ('failed', 'Reached remaining script sections before voice')
        assert next_calls == []


def test_cancelled_research_does_not_enter_roster_recovery():
    statuses, advances, _ = _build(initial_status='idea_logged', research_result={
        'status': 'cancelled', 'message': 'Stopped; completed sources are saved.',
    })
    assert statuses[-1] == ('cancelled', 'Stopped; completed sources are saved.')
    assert advances == []
