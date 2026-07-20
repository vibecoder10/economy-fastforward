"""Functional test for checklist C38 — create-surface convergence
(chat-primary).

Ryan's ruling (tasks/decisions.md, 2026-07-19 "C37 decisions"): the producer
chat plan is THE create door, the New Video form is the power-user door; the
other three create-ish surfaces (Model A Video, onboarding's create step,
FirstVideoFlow) must stop being independent implementations — no parallel
create logic, only thin wrappers into the two real doors.

The C38 TRACE (done before any code, see the chunk's report) found four of
the five surfaces ALREADY converged on `routes.videos.create_video`:
  - producer chat (`routes/chat.py`) already imports and calls it directly
    (see that file's own module docstring — "REUSES create_video").
  - the New Video form posts to it directly (`POST /api/videos`).
  - FirstVideoFlow and the New Video form share the exact same React Query
    mutation (`createMutation`, `mutationFn: createVideo`) in
    `frontend/src/app/pipeline/page.tsx` — pinned below by source read.
  - onboarding's create step has NO create-video code of its own at all;
    `routes/onboarding.py`'s own docstring says its steps are driven by
    `routes/chat.py`'s `_handle_onboarding` step machine, which funnels
    through the same chat -> create_video path.

The ONE genuine holdout was `routes/model_video.py::model_video` (Model A
Video): it ran its OWN `INSERT INTO videos` + its own
`check_plan_limits`/`increment_usage` calls, never touching create_video.
This chunk rewired it to build a `CreateVideoRequest(reference_url=...)`
with NO title and hand off to `routes.videos.create_video` — an omitted
title + a reference_url is exactly the "derive a brand-new idea from this
reference" shape create_video already had a `preserve_topic` branch for
(previously only reachable with `preserve_topic=True`, hardcoded). This test
pins that wiring behaviorally (not just by AST): the wrapper calls the real
`create_video`, with the right argument shape, and the endpoint file no
longer contains a second INSERT INTO videos.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c38_create_convergence.py -q
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import routes.videos as videos_route  # noqa: E402
import routes.model_video as mv  # noqa: E402
from models import CreateVideoRequest, VideoSummary  # noqa: E402


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _frontend_root() -> Path:
    return Path(__file__).resolve().parents[3] / "frontend"


class _FakeBackgroundTasks:
    def __init__(self):
        self.calls = []

    def add_task(self, fn, *a, **k):
        self.calls.append((fn, a, k))


# ---------------------------------------------------------------------------
# 1. Behavioral proof: Model A Video's endpoint calls the REAL create_video,
#    not a parallel INSERT — and passes the "derive a new idea" shape.
# ---------------------------------------------------------------------------

async def test_model_video_endpoint_delegates_to_create_video(monkeypatch):
    captured = {}

    async def _fake_create_video(body: CreateVideoRequest, background_tasks, tenant_id: str):
        captured["body"] = body
        captured["tenant_id"] = tenant_id
        captured["background_tasks"] = background_tasks
        return VideoSummary(id="video-c38", status="idea_logged")

    monkeypatch.setattr(videos_route, "create_video", _fake_create_video)

    bg = _FakeBackgroundTasks()
    request = mv.ModelVideoRequest(video_url="https://youtu.be/dQw4w9WgXcQ")
    result = await mv.model_video(request, bg, tenant_id="tenant-c38")

    assert "body" in captured, "model_video must call routes.videos.create_video"
    body = captured["body"]
    assert isinstance(body, CreateVideoRequest)
    # The load-bearing shape: NO title (so create_video derives a brand-new
    # idea instead of copying style onto an existing topic).
    assert not (body.title or "").strip(), (
        "Model A Video must omit title — a non-empty title flips create_video "
        "into preserve_topic=True (copy-style-onto-my-topic), which is the "
        "New Video form's clone path, not Model A Video's own shape"
    )
    assert body.reference_url == "https://youtu.be/dQw4w9WgXcQ"
    assert captured["tenant_id"] == "tenant-c38"
    assert captured["background_tasks"] is bg
    assert result.video_id == "video-c38"
    print("✅ test_model_video_endpoint_delegates_to_create_video")


async def test_model_video_rejects_bad_url_before_calling_create_video(monkeypatch):
    calls = []

    async def _boom(*a, **k):
        calls.append(1)
        raise AssertionError("create_video must not be called for an invalid URL")

    monkeypatch.setattr(videos_route, "create_video", _boom)

    from fastapi import HTTPException
    import pytest

    request = mv.ModelVideoRequest(video_url="not a youtube link")
    with pytest.raises(HTTPException) as exc:
        await mv.model_video(request, _FakeBackgroundTasks(), tenant_id="tenant-c38")
    assert exc.value.status_code == 400
    assert not calls
    print("✅ test_model_video_rejects_bad_url_before_calling_create_video")


# ---------------------------------------------------------------------------
# 2. create_video itself: no title + a reference_url derives a NEW idea
#    (preserve_topic=False); title + reference_url still copies style onto
#    the creator's own topic (preserve_topic=True) — the pre-existing
#    New Video form / chat clone behavior must be unchanged.
# ---------------------------------------------------------------------------

async def test_create_video_preserve_topic_flag_follows_title_presence(monkeypatch):
    """Reads create_video's source directly (same convention as
    test_plan_limits_enforcement_lock.py's AST checks) rather than running
    the full DB-backed function, since create_video has many fail-soft
    side-effect helpers that would need a large monkeypatch rig unrelated
    to what this chunk changed. What changed is narrow and textual: the
    `preserve_topic` value passed into `_run_modeling` must be the
    `is_modeled and bool(title)` expression, not a hardcoded True."""
    text = (_backend_root() / "routes" / "videos.py").read_text()
    assert "preserve_topic = is_modeled and bool(title)" in text, (
        "create_video no longer derives preserve_topic from whether a real "
        "title was given — Model A Video's 'derive a new idea' shape and "
        "the New Video form's 'copy style onto my topic' shape can no "
        "longer both reach this one function correctly."
    )
    # The background call must forward preserve_topic, not a literal True
    # (a literal True is exactly the bug this chunk fixed: it made
    # Model A Video's shape unreachable through create_video before C38).
    m = re.search(
        r"background_tasks\.add_task\(\s*\n\s*_run_modeling,.*?\n\s*\)",
        text, re.DOTALL,
    )
    assert m, "background_tasks.add_task(_run_modeling, ...) call not found"
    call_src = m.group(0)
    assert re.search(r",\s*preserve_topic\s*,", call_src), (
        f"_run_modeling call no longer forwards the preserve_topic variable: {call_src!r}"
    )
    print("✅ test_create_video_preserve_topic_flag_follows_title_presence")


def test_create_video_400s_when_neither_title_nor_reference_given():
    text = (_backend_root() / "routes" / "videos.py").read_text()
    assert 'if not title and not is_modeled:' in text, (
        "create_video must still refuse to silently create a titleless, "
        "non-modeled video — Title is required unless reference_url is set"
    )
    print("✅ test_create_video_400s_when_neither_title_nor_reference_given")


# ---------------------------------------------------------------------------
# 3. No orphaned second INSERT path: model_video.py must not INSERT INTO
#    videos anywhere anymore (grep-proof, per the chunk's explicit ask).
# ---------------------------------------------------------------------------

def test_model_video_has_no_second_insert_path():
    text = (_backend_root() / "routes" / "model_video.py").read_text()
    assert "INSERT INTO videos" not in text, (
        "routes/model_video.py must not INSERT INTO videos directly anymore "
        "— it must delegate to routes.videos.create_video (checklist C38)"
    )
    assert "from routes.videos import create_video" in text, (
        "routes/model_video.py's endpoint must import the canonical "
        "create_video function"
    )
    print("✅ test_model_video_has_no_second_insert_path")


# ---------------------------------------------------------------------------
# 4. Frontend: FirstVideoFlow and the New Video form share ONE mutation
#    (already converged pre-C38 — pinned here so it can't silently drift
#    into two separate create calls later).
# ---------------------------------------------------------------------------

def test_first_video_flow_and_new_video_form_share_one_mutation():
    text = (_frontend_root() / "src" / "app" / "pipeline" / "page.tsx").read_text()
    assert "mutationFn: createVideo" in text, (
        "the pipeline page's create mutation must call the canonical "
        "createVideo() API helper (POST /api/videos)"
    )
    # Both the New Video form's submit handler and FirstVideoFlow's
    # onCreateVideo callback must call the SAME createMutation.mutate —
    # not a second mutation/fetch of their own.
    assert text.count("createMutation.mutate(") >= 2, (
        "expected both the New Video form and FirstVideoFlow's "
        "handleFirstVideoCreate to call createMutation.mutate — if either "
        "now calls a different mutation/fetch, the two doors have drifted "
        "into parallel create logic again"
    )
    assert "onCreateVideo={handleFirstVideoCreate}" in text
    print("✅ test_first_video_flow_and_new_video_form_share_one_mutation")


def test_chat_producer_reuses_create_video():
    text = (_backend_root() / "routes" / "chat.py").read_text()
    assert "from routes.videos import create_video" in text, (
        "the chat producer must keep importing the canonical create_video "
        "— a chat flow that stops importing it may have grown its own "
        "parallel INSERT"
    )
    assert "INSERT INTO videos" not in text, (
        "routes/chat.py must not INSERT INTO videos directly — it must "
        "delegate to routes.videos.create_video"
    )
    print("✅ test_chat_producer_reuses_create_video")


def test_onboarding_has_no_create_video_logic_of_its_own():
    text = (_backend_root() / "routes" / "onboarding.py").read_text()
    assert "INSERT INTO videos" not in text, (
        "routes/onboarding.py must not gain its own video-create INSERT — "
        "the onboarding create step is driven entirely by routes/chat.py's "
        "_handle_onboarding step machine, which reuses create_video"
    )
    print("✅ test_onboarding_has_no_create_video_logic_of_its_own")


TESTS_ASYNC = [
    test_model_video_endpoint_delegates_to_create_video,
    test_model_video_rejects_bad_url_before_calling_create_video,
    test_create_video_preserve_topic_flag_follows_title_presence,
]
TESTS_SYNC = [
    test_create_video_400s_when_neither_title_nor_reference_given,
    test_model_video_has_no_second_insert_path,
    test_first_video_flow_and_new_video_form_share_one_mutation,
    test_chat_producer_reuses_create_video,
    test_onboarding_has_no_create_video_logic_of_its_own,
]


def main() -> int:
    import asyncio

    class _MonkeyPatch:
        """Minimal stand-in for pytest's monkeypatch fixture when run as a script."""

        def __init__(self):
            self._undo = []

        def setattr(self, obj, name, value):
            self._undo.append((obj, name, getattr(obj, name)))
            setattr(obj, name, value)

        def undo(self):
            for obj, name, value in reversed(self._undo):
                setattr(obj, name, value)

    failed = 0
    for t in TESTS_SYNC:
        try:
            t()
        except AssertionError as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
    for t in TESTS_ASYNC:
        mp = _MonkeyPatch()
        try:
            asyncio.run(t(mp))
        except AssertionError as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
        finally:
            mp.undo()
    total = len(TESTS_SYNC) + len(TESTS_ASYNC)
    print(f"\n{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
