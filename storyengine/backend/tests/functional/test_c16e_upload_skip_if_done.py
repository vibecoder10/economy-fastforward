"""Tests for C16e (checklist Phase 1 chunk queue; found by C16d's S7-9
resumability pass, docs/failure-modes.md's "Per-Stage Resumability" table):
upload re-publish guard.

Before this fix, PipelineExecutor.run_upload() had NO re-invoke guard at
all — every call unconditionally ran the per-tenant native upload path (or
the legacy from-scratch bot), so a second invocation (a routine
status-machine resume, an arq retry, a chat "upload it" double-tap) minted
a genuine SECOND YouTube draft: recoverable (delete it in Studio) but messy,
and it burns ~1,600 of the 10,000/day YouTube API quota units for nothing.
Contrast: C16d already added this exact skip-if-done shape for the
thumbnail stage.

This pins the fix in three layers:

  1. `PipelineExecutor.run_upload(video_id, force=False)` — a
     `videos.youtube_url`/`youtube_video_id` already set + force=False skips
     entirely (proven by making the channel_profiles fetch_one call raise if
     reached, and by monkeypatching `youtube_publish.upload_video_to_youtube`
     to raise if called — the money/quota-safety assertion). Neither id set
     -> proceeds normally. force=True bypasses the guard even with an
     existing id/url — an explicit "redo it" always wins, same convention as
     run_clip_generation's/run_thumbnail's pre-existing `force` param.

  2. `actions.already_uploaded_reply(tenant_id, video_id)` — the shared
     helper: returns None when neither column is set, and a friendly
     message naming the existing URL (or id, if only that's set) otherwise.

  3. `routes/chat.py::_run_pending_action`'s "upload" verb — DELIBERATELY
     DIFFERENT from C16d's thumbnail verb (which always forces): an explicit
     chat "upload it" on an already-uploaded video ALSO skips (never
     forces), replying with the already-uploaded message BEFORE claiming a
     generation_claims lane or scheduling any background_tasks — a double-
     tap can never mint a second draft AND never wastes a claim/task on a
     no-op. A not-yet-uploaded video proceeds through the normal
     claim-then-schedule dispatch unchanged.

No network, no real DB: PipelineExecutor.__new__ skips __init__'s vault/env
loading (same technique as test_c16d_thumbnail_skip_if_done.py);
_ensure_initialized is skipped via _initialized = True; database module-level
names (fetch_one/execute) are monkeypatched on the pipeline_executor module
object itself. Chat-layer tests reuse the light module-stub pattern already
used by test_c16a_generation_claims.py/test_c15b_show_and_approve_scene.py.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c16e_upload_skip_if_done.py -q
"""
import asyncio
import os
import sys
import types
from unittest.mock import AsyncMock, patch

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import pipeline_executor as pe_mod  # noqa: E402
from pipeline_executor import PipelineExecutor  # noqa: E402
import youtube_publish  # noqa: E402

TENANT = "tenant-1"
VIDEO = "video-1"


def _video_row(**over):
    base = {
        "id": VIDEO, "status": "rendered", "youtube_url": None,
        "youtube_video_id": None, "seo_description": "Some SEO already saved.",
        "video_title": "Test Video",
    }
    base.update(over)
    return base


def _make_executor(monkeypatch, video_row, *, has_channel=True, boom_if_channel_queried=False):
    activity_calls = []

    async def fake_fetch_one(query, *args):
        if "FROM videos WHERE id" in query:
            return video_row
        if "FROM channel_profiles" in query:
            if boom_if_channel_queried:
                raise AssertionError(
                    "run_upload must not reach the channel_profiles lookup when "
                    "skip-if-done applies (force=False + youtube id/url already set)")
            return {"youtube_refresh_token": "fake-refresh-token"} if has_channel else None
        return None

    async def fake_execute(query, *args):
        return "OK"

    monkeypatch.setattr(pe_mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pe_mod, "execute", fake_execute)

    executor = PipelineExecutor.__new__(PipelineExecutor)
    executor.tenant_id = TENANT
    executor._initialized = True  # skip vault/env loading in _ensure_initialized
    executor._pipeline = None  # never touched if the guard/native path are wired right

    async def fake_log_activity(bot_name, video_id, status, message=None, cost=0):
        activity_calls.append((bot_name, video_id, status, message))

    executor._log_activity = fake_log_activity
    return executor, activity_calls


# ---------------------------------------------------------------------------
# 1. PipelineExecutor.run_upload — the executor-level guard
# ---------------------------------------------------------------------------

def test_skip_if_done_default_youtube_url_already_set(monkeypatch):
    """force=False (default) + youtube_url already set: skip entirely — the
    channel_profiles lookup (and therefore the real upload client) is never
    reached, no second draft, zero quota burn."""
    video_row = _video_row(youtube_url="https://www.youtube.com/watch?v=abc12345678")
    executor, activity_calls = _make_executor(monkeypatch, video_row, boom_if_channel_queried=True)

    async def _boom_upload(*a, **k):
        raise AssertionError("upload_video_to_youtube must not be called when skip-if-done applies")

    monkeypatch.setattr(youtube_publish, "upload_video_to_youtube", _boom_upload)

    result = asyncio.run(executor.run_upload(VIDEO))

    assert result["status"] == "completed"
    assert result.get("skipped") is True
    assert result["youtube_url"] == "https://www.youtube.com/watch?v=abc12345678"
    assert any(c[2] == "completed" and "Already uploaded" in (c[3] or "") for c in activity_calls), (
        "expected an activity log line explaining the skip")


def test_skip_if_done_default_youtube_video_id_already_set(monkeypatch):
    """Same guard, but only youtube_video_id is set (the column the native
    upload path always writes, even if youtube_url were ever missing) —
    the guard checks EITHER column, not just youtube_url."""
    video_row = _video_row(youtube_video_id="abc12345678", youtube_url=None)
    executor, _ = _make_executor(monkeypatch, video_row, boom_if_channel_queried=True)

    async def _boom_upload(*a, **k):
        raise AssertionError("upload_video_to_youtube must not be called when skip-if-done applies")

    monkeypatch.setattr(youtube_publish, "upload_video_to_youtube", _boom_upload)

    result = asyncio.run(executor.run_upload(VIDEO))

    assert result.get("skipped") is True
    assert result["youtube_video_id"] == "abc12345678"


def test_no_skip_when_neither_id_nor_url_set(monkeypatch):
    """force=False but neither column is set: the guard checks EXISTENCE, not
    force alone — the real upload path proceeds normally."""
    video_row = _video_row(youtube_url=None, youtube_video_id=None)
    executor, _ = _make_executor(monkeypatch, video_row, has_channel=True)

    fake_upload = AsyncMock(return_value={
        "youtube_video_id": "new12345678",
        "youtube_url": "https://www.youtube.com/watch?v=new12345678",
        "channel": "Test Channel",
    })
    monkeypatch.setattr(youtube_publish, "upload_video_to_youtube", fake_upload)

    result = asyncio.run(executor.run_upload(VIDEO))

    assert not result.get("skipped")
    assert result["status"] == "uploaded_draft"
    fake_upload.assert_awaited_once()


def test_no_skip_when_url_is_blank_string(monkeypatch):
    """Same as above but for an empty-string youtube_url (not NULL) —
    .strip() must treat it as "not set", matching C16d's completeness
    convention exactly."""
    video_row = _video_row(youtube_url="   ", youtube_video_id="")
    executor, _ = _make_executor(monkeypatch, video_row, has_channel=True)

    fake_upload = AsyncMock(return_value={
        "youtube_video_id": "new12345678",
        "youtube_url": "https://www.youtube.com/watch?v=new12345678",
    })
    monkeypatch.setattr(youtube_publish, "upload_video_to_youtube", fake_upload)

    result = asyncio.run(executor.run_upload(VIDEO))

    assert not result.get("skipped")
    fake_upload.assert_awaited_once()


def test_force_true_bypasses_guard_even_with_existing_youtube_id(monkeypatch):
    """force=True (an explicit, deliberate re-upload) always wins over an
    already-set youtube_url/youtube_video_id — the ONLY way to bypass the
    guard, mirroring run_thumbnail's/run_clip_generation's force convention."""
    video_row = _video_row(youtube_url="https://www.youtube.com/watch?v=abc12345678",
                           youtube_video_id="abc12345678")
    executor, _ = _make_executor(monkeypatch, video_row, has_channel=True)

    fake_upload = AsyncMock(return_value={
        "youtube_video_id": "second12345",
        "youtube_url": "https://www.youtube.com/watch?v=second12345",
    })
    monkeypatch.setattr(youtube_publish, "upload_video_to_youtube", fake_upload)

    result = asyncio.run(executor.run_upload(VIDEO, force=True))

    assert not result.get("skipped")
    assert result["status"] == "uploaded_draft"
    fake_upload.assert_awaited_once()


def test_video_not_found_short_circuits_before_the_guard(monkeypatch):
    """Unrelated to the guard, but the guard's new code sits right after
    this check — pin the ordering doesn't break the pre-existing behavior."""
    async def fake_fetch_one(query, *args):
        return None

    monkeypatch.setattr(pe_mod, "fetch_one", fake_fetch_one)
    executor = PipelineExecutor.__new__(PipelineExecutor)
    executor.tenant_id = TENANT
    executor._initialized = True

    result = asyncio.run(executor.run_upload(VIDEO))
    assert result == {"status": "failed", "error": "Video not found"}


# ---------------------------------------------------------------------------
# 2. actions.already_uploaded_reply — the shared chat-layer helper
# ---------------------------------------------------------------------------

def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


async def _boom(*a, **k):
    raise AssertionError("pure tests must not touch runtime services")


_stub("vault", get_secret=_boom)
_PIPELINE_ROOT = os.path.abspath(os.path.join(_BACKEND, "..", "..", "skills", "video-pipeline"))
if _PIPELINE_ROOT not in sys.path:
    sys.path.insert(0, _PIPELINE_ROOT)

import actions  # noqa: E402
import routes.chat as chat  # noqa: E402


def test_already_uploaded_reply_none_when_neither_set():
    async def fake_fetch_one(query, *a):
        return {"youtube_url": None, "youtube_video_id": None}

    with patch.object(actions, "fetch_one", fake_fetch_one):
        reply = asyncio.run(actions.already_uploaded_reply(TENANT, VIDEO))
    assert reply is None


def test_already_uploaded_reply_names_the_url():
    async def fake_fetch_one(query, *a):
        return {"youtube_url": "https://www.youtube.com/watch?v=abc12345678", "youtube_video_id": "abc12345678"}

    with patch.object(actions, "fetch_one", fake_fetch_one):
        reply = asyncio.run(actions.already_uploaded_reply(TENANT, VIDEO))
    assert reply is not None
    assert "https://www.youtube.com/watch?v=abc12345678" in reply
    assert "second draft" in reply


def test_already_uploaded_reply_falls_back_to_id_when_url_missing():
    async def fake_fetch_one(query, *a):
        return {"youtube_url": None, "youtube_video_id": "abc12345678"}

    with patch.object(actions, "fetch_one", fake_fetch_one):
        reply = asyncio.run(actions.already_uploaded_reply(TENANT, VIDEO))
    assert reply is not None
    assert "abc12345678" in reply


# ---------------------------------------------------------------------------
# 3. routes/chat.py::_run_pending_action — the "upload" verb's chat dispatch
# ---------------------------------------------------------------------------

class _FakeBackgroundTasks:
    def __init__(self):
        self.calls = []

    def add_task(self, fn, *a, **k):
        self.calls.append((fn, a, k))


def test_upload_verb_double_tap_returns_already_uploaded_reply_no_dispatch():
    """The explicit-verb double-tap path: verb='upload' on an already-uploaded
    video returns the friendly reply and schedules NOTHING — no
    generation_claims.acquire() call, no background_tasks.add_task() call."""
    bg = _FakeBackgroundTasks()
    pending = {"verb": "upload"}
    acquire_mock = AsyncMock(return_value=True)

    async def fake_already_uploaded_reply(tenant_id, video_id):
        return ("This video's already uploaded to YouTube as an unlisted draft. "
                "It's here: https://www.youtube.com/watch?v=abc12345678")

    with patch.object(chat, "_already_uploaded_reply", fake_already_uploaded_reply), \
         patch.object(chat, "generation_claims", types.SimpleNamespace(
             acquire=acquire_mock, stage_for_verb=lambda v: "main")):
        line = asyncio.run(chat._run_pending_action(TENANT, VIDEO, pending, bg))

    assert bg.calls == [], "a double-tap on an already-uploaded video must not schedule anything"
    acquire_mock.assert_not_called()
    assert "already uploaded" in line
    assert "abc12345678" in line


def test_upload_verb_not_yet_uploaded_dispatches_normally():
    """A genuinely not-yet-uploaded video's 'upload' verb proceeds through the
    normal claim-then-schedule dispatch, unchanged by this chunk."""
    bg = _FakeBackgroundTasks()
    pending = {"verb": "upload"}
    acquire_mock = AsyncMock(return_value=True)
    fake_step_factory = lambda *a, **k: "sentinel-upload-callable"  # noqa: E731

    async def fake_already_uploaded_reply(tenant_id, video_id):
        return None

    with patch.object(chat, "_already_uploaded_reply", fake_already_uploaded_reply), \
         patch.object(chat, "_make_copilot_step", fake_step_factory), \
         patch.object(chat, "generation_claims", types.SimpleNamespace(
             acquire=acquire_mock, stage_for_verb=lambda v: "main")):
        line = asyncio.run(chat._run_pending_action(TENANT, VIDEO, pending, bg))

    assert len(bg.calls) == 1
    assert bg.calls[0][0] == "sentinel-upload-callable"
    acquire_mock.assert_awaited_once_with(TENANT, VIDEO, "main", claimed_by="chat:upload")
    assert "uploading to YouTube" in line


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
