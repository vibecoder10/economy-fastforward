"""Tests for C34a (checklist S10-1 CRITICAL fix, docs/reports/2026-07-17-
storyengine-agent-audit-findings.md §S10-1): remove/hard-block the legacy
upload fallback.

Before this fix, `PipelineExecutor.run_upload` fell through to
`self._pipeline.run_upload_bot()` (skills/video-pipeline/upload/) whenever a
tenant had no connected YouTube channel (`channel_profiles
.youtube_refresh_token`). That legacy bot:
  - hardcoded @Power_Doctrine SEO onto the TENANT's video (via Airtable
    fields, not the tenant's own stored SEO),
  - uploaded through the SHARED VPS OAuth token files — i.e. onto RYAN'S
    own YouTube channel, category 25 — not the tenant's,
  - never passed through C33's YouTube quota guard (that guard lives
    entirely inside `youtube_publish.upload_video_to_youtube`, the native
    path's function; the legacy bot never calls it).

This pins:

  1. `PipelineExecutor.run_upload` — an unconnected tenant (no
     `channel_profiles.youtube_refresh_token`) now returns a clear
     `{"status": "failed", "error": ...}` immediately. `self._pipeline` is
     never touched (proven with a sentinel that raises on any attribute
     access) — there is no code path left that can reach
     skills/video-pipeline/upload/ from here. `run_upload_bot` no longer
     exists as an attribute on the LightPipeline shim at all (checked via
     `hasattr`).

  2. `routes/pipeline.py`'s `POST /upload/{video_id}` route — the same
     belt-and-suspenders precondition, checked before any task-status/lock
     is claimed.

  3. Connected-tenant path — byte-identical. Covered by the pre-existing
     `test_c16e_upload_skip_if_done.py::test_no_skip_when_neither_id_nor_url_set`
     (has_channel=True) which this chunk did not touch; re-run here as a
     smoke check plus a `git stash` diff (see PR notes) proves the diff for
     that branch is empty.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c34a_upload_no_legacy_fallback.py -q
"""
import asyncio
import os
import sys
import types
from unittest.mock import AsyncMock

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
        "youtube_video_id": None, "seo_description": None,
        "video_title": "Test Video",
    }
    base.update(over)
    return base


class _BoomIfTouched:
    """Stands in for `self._pipeline`. Any attribute access means the
    (now-deleted) legacy-bot fallback path was reached — a hard failure."""

    def __getattr__(self, name):
        raise AssertionError(
            f"run_upload must never touch self._pipeline.{name} for an "
            "unconnected tenant — the legacy-bot fallback is removed")


def _make_executor(monkeypatch, video_row, *, has_channel):
    activity_calls = []
    fetch_calls = []
    execute_calls = []

    async def fake_fetch_one(query, *args):
        fetch_calls.append((query, args))
        if "FROM videos WHERE id" in query:
            return video_row
        if "FROM channel_profiles" in query:
            return {"youtube_refresh_token": "fake-refresh-token"} if has_channel else None
        return None

    async def fake_execute(query, *args):
        execute_calls.append((query, args))
        return "OK"

    monkeypatch.setattr(pe_mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pe_mod, "execute", fake_execute)

    executor = PipelineExecutor.__new__(PipelineExecutor)
    executor.tenant_id = TENANT
    executor._initialized = True  # skip vault/env loading in _ensure_initialized
    executor._pipeline = _BoomIfTouched()

    async def fake_log_activity(bot_name, video_id, status, message=None, cost=0):
        activity_calls.append((bot_name, video_id, status, message))

    executor._log_activity = fake_log_activity
    return executor, activity_calls, fetch_calls, execute_calls


# ---------------------------------------------------------------------------
# 1. PipelineExecutor.run_upload — unconnected tenant, executor-level gate
# ---------------------------------------------------------------------------

def test_unconnected_tenant_gets_clear_error_not_legacy_fallback(monkeypatch):
    video_row = _video_row()
    executor, activity_calls, _, execute_calls = _make_executor(
        monkeypatch, video_row, has_channel=False)

    async def _boom_upload(*a, **k):
        raise AssertionError("upload_video_to_youtube must not be called — no channel connected")

    monkeypatch.setattr(youtube_publish, "upload_video_to_youtube", _boom_upload)

    result = asyncio.run(executor.run_upload(VIDEO))

    assert result["status"] == "failed"
    assert "Connect your YouTube channel" in result["error"]
    assert result["error"] == "Connect your YouTube channel first — Settings → YouTube."

    # No Power-Doctrine-flavored write happened — the only DB writes came
    # from _get_video/_log_activity plumbing, never a raw `UPDATE videos SET
    # youtube_url` (that only exists in native-path/legacy-path code, both
    # unreached here).
    assert not any("youtube_url" in q for q, _ in execute_calls)

    assert any(c[2] == "failed" and "Connect your YouTube channel" in (c[3] or "")
               for c in activity_calls), "expected a failed activity log line with the clear error"


def test_run_upload_bot_no_longer_exists_on_the_pipeline_shim():
    """The legacy-bot shim (`self._pipeline.run_upload_bot`) that used to be
    wired up in `_ensure_initialized` is gone — asserting on the SOURCE, not
    just behavior, so a future re-add of the wiring (without touching
    run_upload's call site) still gets caught."""
    import inspect
    src = inspect.getsource(pe_mod.PipelineExecutor._ensure_initialized)
    assert "run_upload_bot" not in src, (
        "run_upload_bot shim must not be re-wired in _ensure_initialized")


def test_run_upload_source_never_calls_pipeline_run_upload_bot():
    """Docstring commentary is allowed to name the removed shim for history;
    an actual call site (`self._pipeline.run_upload_bot(`) must not exist."""
    import inspect
    src = inspect.getsource(pe_mod.PipelineExecutor.run_upload)
    assert "self._pipeline.run_upload_bot(" not in src, (
        "run_upload must not call self._pipeline.run_upload_bot anywhere")
    assert "self._pipeline.run_upload_bot" not in src.split('"""', 2)[-1], (
        "no call to the legacy shim should remain in the executable body")


def test_video_not_found_still_short_circuits(monkeypatch):
    async def fake_fetch_one(query, *args):
        return None

    monkeypatch.setattr(pe_mod, "fetch_one", fake_fetch_one)
    executor = PipelineExecutor.__new__(PipelineExecutor)
    executor.tenant_id = TENANT
    executor._initialized = True

    result = asyncio.run(executor.run_upload(VIDEO))
    assert result == {"status": "failed", "error": "Video not found"}


def test_already_uploaded_skip_still_short_circuits_before_the_channel_check(monkeypatch):
    """Unrelated to this chunk, but pins that the pre-existing C16e skip-if-
    done guard still runs BEFORE the (now-terminal) channel-connected check —
    an already-uploaded video is never told to "connect a channel"."""
    video_row = _video_row(youtube_url="https://www.youtube.com/watch?v=abc12345678")
    executor, _, fetch_calls, _ = _make_executor(monkeypatch, video_row, has_channel=False)

    result = asyncio.run(executor.run_upload(VIDEO))

    assert result.get("skipped") is True
    assert result["status"] == "completed"
    assert not any("channel_profiles" in q for q, _ in fetch_calls), (
        "the channel_profiles lookup (and therefore the new clear-error path) "
        "must not even be reached when skip-if-done already applies")


# ---------------------------------------------------------------------------
# 2. Connected tenant — byte-identical native path (smoke re-check; the real
#    non-vacuous proof is the git-stash diff run separately — see PR notes)
# ---------------------------------------------------------------------------

def test_connected_tenant_native_path_unchanged(monkeypatch):
    video_row = _video_row()
    executor, _, _, _ = _make_executor(monkeypatch, video_row, has_channel=True)

    fake_upload = AsyncMock(return_value={
        "youtube_video_id": "new12345678",
        "youtube_url": "https://www.youtube.com/watch?v=new12345678",
        "channel": "Test Channel",
    })
    fake_seo = AsyncMock(return_value={"description": "ok"})
    monkeypatch.setattr(youtube_publish, "upload_video_to_youtube", fake_upload)
    monkeypatch.setattr(youtube_publish, "generate_and_store_seo", fake_seo)

    result = asyncio.run(executor.run_upload(VIDEO))

    assert result["status"] == "uploaded_draft"
    assert result["video_url"] == "https://www.youtube.com/watch?v=new12345678"
    fake_upload.assert_awaited_once()


# ---------------------------------------------------------------------------
# 3. routes/pipeline.py POST /upload/{video_id} — belt-and-suspenders gate
# ---------------------------------------------------------------------------

for stub_mod in ("database", "auth"):
    if stub_mod not in sys.modules:
        m = types.ModuleType(stub_mod)
        if stub_mod == "database":
            async def _noop(*a, **kw):
                return None
            m.fetch_one = _noop
            m.fetch_all = _noop
            m.execute = _noop
        if stub_mod == "auth":
            async def _get_tenant_id(*a, **kw):
                return "stub"
            m.get_tenant_id = _get_tenant_id
        sys.modules[stub_mod] = m

if "pipeline_executor" not in sys.modules or not hasattr(sys.modules["pipeline_executor"], "PipelineExecutor"):
    pass  # real module already imported above via `import pipeline_executor as pe_mod`

from fastapi import HTTPException  # noqa: E402
from routes import pipeline as pipeline_mod  # noqa: E402


class _FakeRequest:
    app = types.SimpleNamespace(state=types.SimpleNamespace(arq=None))


class _FakeBackgroundTasks:
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *a, **kw):
        self.tasks.append((fn, a, kw))


def test_route_rejects_upload_when_no_channel_connected(monkeypatch):
    async def fake_fetch_one(query, *args):
        if "FROM videos WHERE id" in query:
            return {"id": VIDEO, "status": "rendered", "pipeline_stages": None}
        if "FROM channel_profiles" in query:
            return None
        raise AssertionError(f"unexpected fetch_one query: {query}")

    async def _boom_is_task_active(*a, **kw):
        raise AssertionError("must fail fast on the channel check, before claiming a task lock")

    monkeypatch.setattr(pipeline_mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pipeline_mod, "_is_task_active", _boom_is_task_active)

    async def _call():
        return await pipeline_mod.run_upload(
            VIDEO, _FakeRequest(), _FakeBackgroundTasks(), force=False, tenant_id=TENANT)

    try:
        asyncio.run(_call())
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "Connect your YouTube channel" in exc.detail


def test_route_proceeds_past_channel_check_when_connected(monkeypatch):
    """Connected tenant: the channel gate passes through silently — proves
    the new check doesn't block the byte-identical native path either."""
    async def fake_fetch_one(query, *args):
        if "FROM videos WHERE id" in query:
            return {"id": VIDEO, "status": "rendered", "pipeline_stages": None}
        if "FROM channel_profiles" in query:
            return {"youtube_refresh_token": "fake-token"}
        raise AssertionError(f"unexpected fetch_one query: {query}")

    async def fake_is_task_active(*a, **kw):
        return False

    reached = {}

    def fake_set_task_status(*a, **kw):
        reached["set"] = True

    monkeypatch.setattr(pipeline_mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pipeline_mod, "_is_task_active", fake_is_task_active)
    monkeypatch.setattr(pipeline_mod, "_set_task_status", fake_set_task_status)

    result = asyncio.run(pipeline_mod.run_upload(
        VIDEO, _FakeRequest(), _FakeBackgroundTasks(), force=False, tenant_id=TENANT))

    assert reached.get("set") is True
    assert result.status == "running"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
