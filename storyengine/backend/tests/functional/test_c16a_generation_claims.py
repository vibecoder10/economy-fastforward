"""Tests for C16a (checklist §Phase 1 "C16a · S7-1+S7-6 fix: DB-backed
generation claim", docs/reports/2026-07-17-storyengine-agent-audit-findings.md
§S7-1 CRITICAL + §S7-6 MED).

Before this fix, routes/chat.py's `_handle_approve`/`_run_pending_action`
scheduled paid background work (`actions.make_autobuild_step`/
`make_action_step`) via a bare `background_tasks.add_task(...)` with ZERO
concurrency guard anywhere — a double-tap or a retried chat turn ran two
concurrent generation loops on the same video (double paid spend). The only
existing guard (`routes/pipeline.py`'s `_running_tasks`/`_side_lanes`
in-process dicts) is restart-fragile and chat never consulted it.

This pins the fix, `generation_claims.py` (a small DB table both chat and the
manual routes now consult):

  1. acquire()/release() basic cycle: a claim can be taken once, a second
     attempt for the SAME (tenant, video, stage) is denied, release() frees
     it, and a fresh acquire then succeeds.
  2. Stale-claim retake: a claim older than 2h is treated as abandoned and
     retaken by a fresh acquire (a crashed run must never wedge a video).
     A FRESH (<2h) claim is NOT retaken — this is the deny/wedge boundary.
  3. Lane semantics mirror routes/pipeline.py's in-process dict exactly:
     "main" is blocked by ANY other active stage (including a side lane);
     a side lane is blocked by "main" or itself, never by a DIFFERENT side
     lane (voice can run while thumbnail generates).
  4. Fail-CLOSED for spend: acquire() and is_blocked() both DENY (return
     False / True respectively — "busy") when the DB call itself raises.
     release() is fail-SOFT: it swallows the error and never raises.
  5. stage_for_verb(): the granularity mapping — voice/characters/thumbnail
     keep their own lane name, everything else (including "build") maps to
     "main".
  6. routes/chat.py's three paid dispatch sites (`_handle_approve`'s
     autobuild kickoff, `_run_pending_action`'s "build" verb, and
     `_run_pending_action`'s single-stage copilot verb) each: (a) call
     generation_claims.acquire() BEFORE scheduling, (b) do NOT call
     background_tasks.add_task when acquire() returns False, and (c) reply
     with the "already working on that" line instead — proven via a
     git-stash-sensitive non-vacuous assertion (add_task.assert_not_called).
  7. actions.py's make_action_step/make_autobuild_step release the claim in
     their `_run`'s finally block on BOTH the success path and when the
     executor raises — proven by driving `_run()` to completion against a
     fake PipelineExecutor that raises, and asserting release() still fired.

No live DB, no network: generation_claims.py's own asyncpg pool/connection
is replaced with a small in-memory fake (single-threaded, so it validates the
ACQUIRE LOGIC — stale-vs-fresh, cross-lane blocking, ON CONFLICT semantics —
faithfully; genuine TOCTOU-freedom under real concurrency rests on the
pg_advisory_xact_lock + single-transaction structure in the real SQL, which a
non-concurrent fake can't independently exercise). chat.py/actions.py tests
reuse the light module-stub pattern already used by test_c15a_plan_cost_quote.py
and test_autobuild_explicit_research_plan.py.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c16a_generation_claims.py -q
"""
import asyncio
import os
import sys
import time
import types
from unittest.mock import AsyncMock, patch

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


async def _boom(*a, **k):
    raise AssertionError("pure tests must not touch runtime services")


# generation_claims.py only does `import database` at module scope (resolves
# database.get_pool at CALL time) — a minimal stub is enough to import it.
_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom, get_pool=_boom)

import generation_claims  # noqa: E402


# =============================================================================
# Part 1 — generation_claims.py: fake asyncpg pool/connection
# =============================================================================

class _FakeConn:
    """A faithful-enough single-threaded stand-in for the asyncpg connection
    generation_claims.py drives: understands exactly the four query shapes
    the module issues (advisory lock no-op, stale sweep, active-stage read
    with/without the staleness filter, insert-if-absent, delete-by-stage)."""

    def __init__(self, store: dict, should_fail: bool = False):
        self.store = store  # (tenant_id, video_id, stage) -> claimed_at (epoch seconds)
        self.should_fail = should_fail

    def transaction(self):
        return _NullAsyncCtx()

    async def execute(self, query, *args):
        if self.should_fail:
            raise RuntimeError("simulated DB outage")
        if "pg_advisory_xact_lock" in query:
            return None  # no-op — a single-process fake needs no real locking
        if "stage = $3" in query:  # release(): DELETE ... AND stage = $3
            tenant_id, video_id, stage = args
            self.store.pop((tenant_id, video_id, stage), None)
            return "DELETE 1"
        if "claimed_at < now()" in query:  # acquire()'s stale sweep
            tenant_id, video_id = args
            cutoff = time.time() - generation_claims.STALE_HOURS * 3600
            for key in [k for k in self.store if k[0] == tenant_id and k[1] == video_id]:
                if self.store[key] < cutoff:
                    del self.store[key]
            return "DELETE 0"
        raise AssertionError(f"unexpected execute() query: {query!r}")

    async def fetch(self, query, *args):
        if self.should_fail:
            raise RuntimeError("simulated DB outage")
        tenant_id, video_id = args
        now = time.time()
        stale_filtered = "claimed_at > now()" in query  # is_blocked()'s own filter
        rows = []
        for (t, v, s), claimed_at in self.store.items():
            if t != tenant_id or v != video_id:
                continue
            if stale_filtered and (now - claimed_at) > generation_claims.STALE_HOURS * 3600:
                continue
            rows.append({"stage": s})
        return rows

    async def fetchrow(self, query, *args):
        if self.should_fail:
            raise RuntimeError("simulated DB outage")
        tenant_id, video_id, stage, claimed_by = args
        key = (tenant_id, video_id, stage)
        if key in self.store:  # ON CONFLICT DO NOTHING -> no row back
            return None
        self.store[key] = time.time()
        return {"stage": stage}


class _NullAsyncCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakePoolCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *a):
        return False


class _FakePool:
    def __init__(self, store, should_fail=False):
        self._store = store
        self._should_fail = should_fail

    def acquire(self):
        return _FakePoolCtx(_FakeConn(self._store, self._should_fail))


def _patch_pool(store: dict, should_fail: bool = False):
    """Context manager: routes generation_claims.database.get_pool() at every
    (acquire/release/is_blocked) call to a fresh _FakePool over `store`."""
    fake_pool = _FakePool(store, should_fail)

    async def _fake_get_pool():
        return fake_pool

    return patch.object(generation_claims.database, "get_pool", _fake_get_pool)


# --- 1. acquire/release basic cycle ------------------------------------------

async def test_acquire_then_deny_then_release_then_reacquire():
    store: dict = {}
    with _patch_pool(store):
        first = await generation_claims.acquire("t1", "v1", "main", claimed_by="test")
        assert first is True, "first acquire on a clear video must succeed"

        second = await generation_claims.acquire("t1", "v1", "main", claimed_by="test-retry")
        assert second is False, "a second acquire for the SAME stage while held must be denied"

        await generation_claims.release("t1", "v1", "main")

        third = await generation_claims.acquire("t1", "v1", "main", claimed_by="test-again")
        assert third is True, "acquire after release must succeed again"
    print("✅ test_acquire_then_deny_then_release_then_reacquire")


# --- 2. stale-vs-fresh retake -------------------------------------------------

async def test_stale_claim_over_2h_is_retaken():
    store: dict = {("t1", "v1", "main"): time.time() - (2.5 * 3600)}  # 2.5h old
    with _patch_pool(store):
        result = await generation_claims.acquire("t1", "v1", "main", claimed_by="new-run")
    assert result is True, "a claim older than 2h must be swept and retaken"
    print("✅ test_stale_claim_over_2h_is_retaken")


async def test_fresh_claim_under_2h_is_not_retaken():
    store: dict = {("t1", "v1", "main"): time.time() - (5 * 60)}  # 5 minutes old
    with _patch_pool(store):
        result = await generation_claims.acquire("t1", "v1", "main", claimed_by="double-tap")
    assert result is False, "a fresh (<2h) claim must NOT be retaken — this is the actual double-spend guard"
    print("✅ test_fresh_claim_under_2h_is_not_retaken")


# --- 3. lane semantics (mirrors routes/pipeline.py's in-process dict) --------

async def test_main_is_blocked_by_a_side_lane():
    store: dict = {("t1", "v1", "voice"): time.time()}
    with _patch_pool(store):
        result = await generation_claims.acquire("t1", "v1", "main", claimed_by="autobuild")
    assert result is False, "main must be blocked while ANY side lane (voice) is active"
    print("✅ test_main_is_blocked_by_a_side_lane")


async def test_side_lane_is_blocked_by_main():
    store: dict = {("t1", "v1", "main"): time.time()}
    with _patch_pool(store):
        result = await generation_claims.acquire("t1", "v1", "voice", claimed_by="voice-verb")
    assert result is False, "a side lane must be blocked while main is active"
    print("✅ test_side_lane_is_blocked_by_main")


async def test_independent_side_lanes_do_not_block_each_other():
    store: dict = {("t1", "v1", "thumbnail"): time.time()}
    with _patch_pool(store):
        result = await generation_claims.acquire("t1", "v1", "voice", claimed_by="voice-verb")
    assert result is True, "voice must be able to run while thumbnail is active — independent side lanes"
    print("✅ test_independent_side_lanes_do_not_block_each_other")


async def test_is_blocked_matches_acquire_lane_rules():
    store: dict = {("t1", "v1", "characters"): time.time()}
    with _patch_pool(store):
        assert await generation_claims.is_blocked("t1", "v1", "main") is True
        assert await generation_claims.is_blocked("t1", "v1", "characters") is True
        assert await generation_claims.is_blocked("t1", "v1", "voice") is False
        assert await generation_claims.is_blocked("t1", "v1", "thumbnail") is False
    print("✅ test_is_blocked_matches_acquire_lane_rules")


async def test_is_blocked_ignores_stale_rows():
    store: dict = {("t1", "v1", "main"): time.time() - (3 * 3600)}  # 3h old — stale
    with _patch_pool(store):
        result = await generation_claims.is_blocked("t1", "v1", "voice")
    assert result is False, "is_blocked must not treat a stale (>2h) row as active"
    print("✅ test_is_blocked_ignores_stale_rows")


# --- 4. fail-closed (acquire/is_blocked) vs fail-soft (release) -------------

async def test_acquire_fails_closed_on_db_error():
    store: dict = {}
    with _patch_pool(store, should_fail=True):
        result = await generation_claims.acquire("t1", "v1", "main", claimed_by="test")
    assert result is False, "acquire() must DENY (fail-closed) when the DB call itself errors"
    print("✅ test_acquire_fails_closed_on_db_error")


async def test_is_blocked_fails_closed_on_db_error():
    store: dict = {}
    with _patch_pool(store, should_fail=True):
        result = await generation_claims.is_blocked("t1", "v1", "main")
    assert result is True, "is_blocked() must treat the lane as BUSY (fail-closed) when the DB errors"
    print("✅ test_is_blocked_fails_closed_on_db_error")


async def test_release_fails_soft_on_db_error_never_raises():
    store: dict = {("t1", "v1", "main"): time.time()}
    with _patch_pool(store, should_fail=True):
        await generation_claims.release("t1", "v1", "main")  # must not raise
    print("✅ test_release_fails_soft_on_db_error_never_raises")


# --- 5. stage_for_verb granularity mapping -----------------------------------

def test_stage_for_verb_side_lanes_keep_own_name():
    assert generation_claims.stage_for_verb("voice") == "voice"
    assert generation_claims.stage_for_verb("characters") == "characters"
    assert generation_claims.stage_for_verb("thumbnail") == "thumbnail"
    print("✅ test_stage_for_verb_side_lanes_keep_own_name")


def test_stage_for_verb_everything_else_is_main():
    for verb in ("script", "storyboards", "images", "animate", "sound",
                 "render", "research", "upload", "build", None, "unknown_future_verb"):
        assert generation_claims.stage_for_verb(verb) == "main", f"{verb!r} should map to 'main'"
    print("✅ test_stage_for_verb_everything_else_is_main")


def _run(coro):
    return asyncio.run(coro)


def test_sync_wrappers_for_pure_functions_run_clean():
    # stage_for_verb is sync; the async tests above already run under
    # pytest-asyncio (asyncio_mode = auto in pytest.ini) — this just pins
    # that the module has no accidental import-time event-loop requirement.
    assert generation_claims.SIDE_LANES == frozenset({"voice", "characters", "environments", "thumbnail"})
    print("✅ test_sync_wrappers_for_pure_functions_run_clean")


# =============================================================================
# Part 2 — routes/chat.py: the three CHAT dispatch sites are gated
# =============================================================================

_stub("vault", get_secret=_boom)

import actions  # noqa: E402
import routes.chat as chat  # noqa: E402


class _FakeBackgroundTasks:
    def __init__(self):
        self.calls = []

    def add_task(self, fn, *a, **k):
        self.calls.append((fn, a, k))


class _FakeVideoSummary:
    id = "video-c16a"


async def test_handle_approve_denied_claim_does_not_schedule():
    """S7-1 site 1 (~L530-ish): _handle_approve must not schedule the
    autobuild chain when generation_claims.acquire() returns False, and must
    reply with the busy line instead."""
    bg = _FakeBackgroundTasks()
    spec = {"title": "My Video"}

    async def _fake_create_video(body, background_tasks, tenant_id):
        return _FakeVideoSummary()

    fake_videos_mod = types.ModuleType("routes.videos")
    fake_videos_mod.create_video = _fake_create_video

    async def _fake_fetch_one(query, *a):
        if "render_mode" in query:
            return {"render_mode": None}
        return None

    with patch.dict(sys.modules, {"routes.videos": fake_videos_mod}), \
         patch.object(chat, "fetch_one", _fake_fetch_one), \
         patch.object(chat, "_persist", AsyncMock()), \
         patch.object(chat, "generation_claims", types.SimpleNamespace(
             acquire=AsyncMock(return_value=False),
             stage_for_verb=generation_claims.stage_for_verb,
         )):
        resp = await chat._handle_approve(
            spec, "conv-1", "tenant-1", [], {}, bg,
        )

    assert bg.calls == [], "add_task must NOT be called when the claim is denied"
    assert resp.assistant_text == chat._ALREADY_WORKING_REPLY
    print("✅ test_handle_approve_denied_claim_does_not_schedule")


async def test_handle_approve_granted_claim_schedules_autobuild():
    """Note: _make_autobuild_step itself (a real actions.py factory with its
    own lazy imports of routes.pipeline/generation_claims) is replaced with a
    plain sentinel here — this test is scoped to chat.py's OWN gating logic
    (acquire-then-schedule), not actions.py's internals (covered in Part 3)."""
    bg = _FakeBackgroundTasks()
    spec = {"title": "My Video"}

    async def _fake_create_video(body, background_tasks, tenant_id):
        return _FakeVideoSummary()

    fake_videos_mod = types.ModuleType("routes.videos")
    fake_videos_mod.create_video = _fake_create_video

    async def _fake_fetch_one(query, *a):
        if "render_mode" in query:
            return {"render_mode": None}
        return None

    acquire_mock = AsyncMock(return_value=True)
    fake_step_factory = lambda *a, **k: "sentinel-run-callable"  # noqa: E731
    with patch.dict(sys.modules, {"routes.videos": fake_videos_mod}), \
         patch.object(chat, "fetch_one", _fake_fetch_one), \
         patch.object(chat, "_persist", AsyncMock()), \
         patch.object(chat, "_make_autobuild_step", fake_step_factory), \
         patch.object(chat, "generation_claims", types.SimpleNamespace(
             acquire=acquire_mock, stage_for_verb=generation_claims.stage_for_verb,
         )):
        resp = await chat._handle_approve(
            spec, "conv-1", "tenant-1", [], {}, bg,
        )

    assert len(bg.calls) == 1, "add_task must be called exactly once when the claim is granted"
    assert bg.calls[0][0] == "sentinel-run-callable"
    acquire_mock.assert_awaited_once_with("tenant-1", "video-c16a", "main", claimed_by="chat:approve")
    assert resp.video_id == "video-c16a"
    print("✅ test_handle_approve_granted_claim_schedules_autobuild")


async def test_run_pending_action_build_verb_denied_does_not_schedule():
    """S7-1 site 2 (~L691): the 'build' verb in _run_pending_action."""
    bg = _FakeBackgroundTasks()
    pending = {"verb": "build", "target": "pictures"}

    async def _fake_fetch_one(query, *a):
        return {"render_mode": None}

    with patch.object(chat, "fetch_one", _fake_fetch_one), \
         patch.object(chat, "generation_claims", types.SimpleNamespace(
             acquire=AsyncMock(return_value=False),
             stage_for_verb=generation_claims.stage_for_verb,
         )):
        line = await chat._run_pending_action("tenant-1", "video-1", pending, bg)

    assert bg.calls == [], "the 'build' verb must NOT schedule when the claim is denied"
    assert line == chat._ALREADY_WORKING_REPLY
    print("✅ test_run_pending_action_build_verb_denied_does_not_schedule")


async def test_run_pending_action_build_verb_granted_schedules():
    bg = _FakeBackgroundTasks()
    pending = {"verb": "build", "target": "finish"}
    acquire_mock = AsyncMock(return_value=True)
    fake_step_factory = lambda *a, **k: "sentinel-autobuild-callable"  # noqa: E731

    with patch.object(chat, "_make_autobuild_step", fake_step_factory), \
         patch.object(chat, "generation_claims", types.SimpleNamespace(
            acquire=acquire_mock, stage_for_verb=generation_claims.stage_for_verb)):
        line = await chat._run_pending_action("tenant-1", "video-1", pending, bg)

    assert len(bg.calls) == 1
    assert bg.calls[0][0] == "sentinel-autobuild-callable"
    acquire_mock.assert_awaited_once_with("tenant-1", "video-1", "main", claimed_by="chat:build:finish")
    assert "finishing your video" in line
    print("✅ test_run_pending_action_build_verb_granted_schedules")


async def test_run_pending_action_single_verb_denied_does_not_schedule():
    """S7-1 site 3 (~L697-698): a single-stage copilot verb (e.g. 'voice')."""
    bg = _FakeBackgroundTasks()
    pending = {"verb": "voice"}

    with patch.object(chat, "generation_claims", types.SimpleNamespace(
            acquire=AsyncMock(return_value=False),
            stage_for_verb=generation_claims.stage_for_verb)):
        line = await chat._run_pending_action("tenant-1", "video-1", pending, bg)

    assert bg.calls == [], "a denied single-stage verb must NOT schedule"
    assert line == chat._ALREADY_WORKING_REPLY
    print("✅ test_run_pending_action_single_verb_denied_does_not_schedule")


async def test_run_pending_action_single_verb_granted_uses_own_lane():
    """Granularity proof: 'voice' claims stage='voice' (its own independent
    lane), not 'main' — matches routes/pipeline.py's existing lane vocabulary
    so a manual voice click and a chat voice verb genuinely conflict."""
    bg = _FakeBackgroundTasks()
    pending = {"verb": "voice"}
    acquire_mock = AsyncMock(return_value=True)
    fake_step_factory = lambda *a, **k: "sentinel-voice-callable"  # noqa: E731

    with patch.object(chat, "_make_copilot_step", fake_step_factory), \
         patch.object(chat, "generation_claims", types.SimpleNamespace(
            acquire=acquire_mock, stage_for_verb=generation_claims.stage_for_verb)):
        line = await chat._run_pending_action("tenant-1", "video-1", pending, bg)

    assert len(bg.calls) == 1
    assert bg.calls[0][0] == "sentinel-voice-callable"
    acquire_mock.assert_awaited_once_with("tenant-1", "video-1", "voice", claimed_by="chat:voice")
    print("✅ test_run_pending_action_single_verb_granted_uses_own_lane")


async def test_run_pending_action_script_verb_uses_main_lane():
    """A verb with no independent side lane (e.g. 'script') claims 'main'."""
    bg = _FakeBackgroundTasks()
    pending = {"verb": "script"}
    acquire_mock = AsyncMock(return_value=True)
    fake_step_factory = lambda *a, **k: "sentinel-script-callable"  # noqa: E731

    with patch.object(chat, "_make_copilot_step", fake_step_factory), \
         patch.object(chat, "generation_claims", types.SimpleNamespace(
            acquire=acquire_mock, stage_for_verb=generation_claims.stage_for_verb)):
        await chat._run_pending_action("tenant-1", "video-1", pending, bg)

    acquire_mock.assert_awaited_once_with("tenant-1", "video-1", "main", claimed_by="chat:script")
    print("✅ test_run_pending_action_script_verb_uses_main_lane")


async def test_run_pending_action_runner_verb_bypasses_claim_untouched():
    """Runner verbs (approve_cast/lock/drive_sync/seo…) are explicitly out of
    scope for this chunk (S7-1 names only the autobuild/copilot dispatch) —
    pin that they're untouched: no acquire call, straight to the runner."""
    bg = _FakeBackgroundTasks()
    pending = {"verb": "lock"}
    acquire_mock = AsyncMock(return_value=True)
    runner_mock = AsyncMock(return_value="Locked.")

    with patch.object(chat, "generation_claims", types.SimpleNamespace(
            acquire=acquire_mock, stage_for_verb=generation_claims.stage_for_verb)), \
         patch.dict(chat._ACTION_RUNNERS, {"lock": runner_mock}):
        line = await chat._run_pending_action("tenant-1", "video-1", pending, bg)

    acquire_mock.assert_not_called()
    assert line == "Locked."
    print("✅ test_run_pending_action_runner_verb_bypasses_claim_untouched")


# =============================================================================
# Part 3 — actions.py: release happens on success AND on exception
# =============================================================================

class _FakeExecutorOK:
    async def run_voice(self, video_id, **kwargs):
        return {"status": "completed"}


class _FakeExecutorRaises:
    async def run_voice(self, video_id, **kwargs):
        raise RuntimeError("kie.ai timed out")


def _fake_pipeline_executor_module(executor_instance):
    mod = types.ModuleType("pipeline_executor")
    mod.PipelineExecutor = lambda tenant_id: executor_instance
    return mod


def _fake_routes_pipeline_module():
    mod = types.ModuleType("routes.pipeline")
    mod._set_task_status = lambda *a, **k: None
    mod._clear_task_status = lambda *a, **k: None
    return mod


def _fake_generation_claims_module(release_calls: list):
    mod = types.ModuleType("generation_claims")

    async def _release(tenant_id, video_id, stage):
        release_calls.append((tenant_id, video_id, stage))

    mod.release = _release
    return mod


async def _drive_action_step(executor_instance, release_calls):
    fake_pe = _fake_pipeline_executor_module(executor_instance)
    fake_rp = _fake_routes_pipeline_module()
    fake_gc = _fake_generation_claims_module(release_calls)

    async def _fast_sleep(*_a, **_k):
        return None

    with patch.dict(sys.modules, {
        "pipeline_executor": fake_pe, "routes.pipeline": fake_rp, "generation_claims": fake_gc,
    }):
        with patch("asyncio.sleep", _fast_sleep):
            step = actions.make_action_step(
                "tenant-1", "video-1", [("run_voice", True)], stage="voice",
            )
            await step()


async def test_make_action_step_releases_claim_on_success():
    release_calls: list = []
    await _drive_action_step(_FakeExecutorOK(), release_calls)
    assert release_calls == [("tenant-1", "video-1", "voice")]
    print("✅ test_make_action_step_releases_claim_on_success")


async def test_make_action_step_releases_claim_on_exception():
    release_calls: list = []
    await _drive_action_step(_FakeExecutorRaises(), release_calls)
    assert release_calls == [("tenant-1", "video-1", "voice")], (
        "release() must fire in the finally block even when the executor raises"
    )
    print("✅ test_make_action_step_releases_claim_on_exception")


class _FakeAutobuildExecutor:
    """Enough of PipelineExecutor for make_autobuild_step's first loop pass
    to hit a terminal branch immediately: target='finish' returns as soon as
    status is in actions.DONE_STATUSES — 'done' hits that on iteration 1, so
    this exercises the SAME finally block without needing to fake the whole
    stage chain (that's not what this test is about — see Part 2/3 for the
    verb-dispatch and release-on-success/exception coverage)."""

    async def _get_video(self, video_id):
        return {"status": "done", "pipeline_stages": None, "render_mode": None}


async def test_make_autobuild_step_releases_main_claim_on_completion():
    release_calls: list = []
    fake_pe = _fake_pipeline_executor_module(_FakeAutobuildExecutor())
    fake_rp = _fake_routes_pipeline_module()
    fake_gc = _fake_generation_claims_module(release_calls)

    async def _fast_sleep(*_a, **_k):
        return None

    with patch.dict(sys.modules, {
        "pipeline_executor": fake_pe, "routes.pipeline": fake_rp, "generation_claims": fake_gc,
    }):
        with patch("asyncio.sleep", _fast_sleep):
            step = actions.make_autobuild_step("tenant-1", "video-1", target="finish")
            await step()

    assert release_calls == [("tenant-1", "video-1", "main")], (
        "make_autobuild_step must release the 'main' claim it was scheduled under"
    )
    print("✅ test_make_autobuild_step_releases_main_claim_on_completion")


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
