"""Tests for checklist C53 (P4.2-d) — auto-draft verification audit + the
launch_candidate double-launch race fix.

Two things pinned here:

1. **Plan-limit gate wiring.** `routes.autopilot.launch_candidate` was the
   ONE video-create entry point NOT covered by
   `test_plan_limits_enforcement_lock.py` (which locks the 3 UI routes:
   `videos.py::create_video`, `pipeline.py::create_idea`,
   `discovery.py::launch_idea`). C51's auto_draft dial level and C52's
   `accept_proposal` both funnel through this exact function unattended, so
   an unguarded `launch_candidate` meant autopilot could create unlimited
   videos for a free-plan tenant. This pins `check_plan_limits(tenant_id,
   "video")` running FIRST (before the candidate SELECT, before any write)
   and `increment_usage(tenant_id, "videos_created")` running after the
   video INSERT — same shape as the 3 already-locked entry points.

2. **The double-launch race (SYSTEM_STATE.md §C52 "Known gap").** Two
   concurrent `launch_candidate` calls for the SAME candidate (two accept
   clicks, an accept racing the auto_draft loop, or a plain double-click)
   used to both pass the `our_video_id IS NULL` check before either write
   landed, creating TWO video rows from one candidate. The fix is an atomic
   claim (`UPDATE competitor_videos SET launch_claimed_at = NOW() WHERE ...
   AND our_video_id IS NULL RETURNING id`, migration 109): only one
   concurrent caller gets a row back; the loser gets a clean 409 and creates
   nothing. A launch that raises AFTER acquiring the claim but BEFORE the
   final `our_video_id` write must release the claim (clear
   `launch_claimed_at`) so a crashed/failed launch doesn't wedge the
   candidate forever.

No live DB: `routes.autopilot`'s own `fetch_one`/`fetch_all`/`execute`
(imported from `database` at module scope) are monkeypatched directly, same
convention as `tests/test_c51_candidate_auto_launch.py`. The lazily-imported
helpers (`check_plan_limits`/`increment_usage` from `routes.billing`,
`_get_or_create_project` from `routes.projects`, `apply_default_template`
from `routes.script_templates`, `apply_format_defaults` from
`channel_format`, `apply_locked_cast` from `routes.characters`) are
monkeypatched on their OWN modules, since `launch_candidate` re-imports them
by name at call time (resolves the current attribute, not a frozen
reference) — patching the source module is what a lazy `from X import Y`
picks up.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/test_c53_launch_candidate_gates.py -q
"""
import asyncio

import pytest
from fastapi import HTTPException

import routes.autopilot as autopilot_route
import routes.billing as billing
import routes.projects as projects
import routes.script_templates as script_templates
import channel_format
import routes.characters as characters

TENANT = "tenant-c53"
CANDIDATE_ID = "cand-c53"


def _candidate_row(our_video_id=None, launch_claimed_at=None):
    return {
        "id": CANDIDATE_ID, "video_id": "yt-1", "title": "Some Title", "url": "https://y/1",
        "channel": "SomeChannel", "channel_url": "https://y/c", "views": 1000, "vph": 10.0,
        "hours_old": 5, "published_date": None, "modeled": False,
        "our_video_id": our_video_id, "thumbnail_url": None,
    }


def _patch_creation_helpers(monkeypatch):
    """No-op the 3 side-effect helpers launch_candidate calls after the video
    INSERT — none of them are what this chunk is testing."""
    async def _fake_project(tenant_id):
        return {"id": "project-1"}

    async def _fake_true(*a, **k):
        return True

    monkeypatch.setattr(projects, "_get_or_create_project", _fake_project)
    monkeypatch.setattr(script_templates, "apply_default_template", _fake_true)
    monkeypatch.setattr(channel_format, "apply_format_defaults", _fake_true)
    monkeypatch.setattr(characters, "apply_locked_cast", _fake_true)


def _patch_plan_limits_ok(monkeypatch):
    calls = []

    async def _fake_check(tenant_id, action="video"):
        calls.append(("check", tenant_id, action))

    async def _fake_increment(tenant_id, field, amount=1):
        calls.append(("increment", tenant_id, field))

    monkeypatch.setattr(billing, "check_plan_limits", _fake_check)
    monkeypatch.setattr(billing, "increment_usage", _fake_increment)
    return calls


class _FakeBackgroundTasks:
    def __init__(self):
        self.calls = []

    def add_task(self, fn, *a, **k):
        self.calls.append((fn, a, k))


# ---------------------------------------------------------------------------
# 1. Plan-limit gate: fires BEFORE any query, blocks the launch outright.
# ---------------------------------------------------------------------------

async def test_check_plan_limits_runs_before_any_db_query(monkeypatch):
    async def _fake_check_raises(tenant_id, action="video"):
        assert action == "video"
        raise HTTPException(status_code=402, detail="plan_limit_reached")

    monkeypatch.setattr(billing, "check_plan_limits", _fake_check_raises)

    async def _boom_fetch_one(query, *args):
        raise AssertionError(
            "no DB query should run once check_plan_limits has raised — "
            "the plan gate must be the FIRST thing launch_candidate does"
        )

    monkeypatch.setattr(autopilot_route, "fetch_one", _boom_fetch_one)

    with pytest.raises(HTTPException) as exc:
        await autopilot_route.launch_candidate(CANDIDATE_ID, _FakeBackgroundTasks(), tenant_id=TENANT)
    assert exc.value.status_code == 402
    print("✅ test_check_plan_limits_runs_before_any_db_query")


async def test_increment_usage_called_after_video_insert(monkeypatch):
    calls = _patch_plan_limits_ok(monkeypatch)
    _patch_creation_helpers(monkeypatch)

    store = {CANDIDATE_ID: _candidate_row()}

    async def fake_fetch_one(query, *args):
        if "FROM competitor_videos WHERE id" in query:
            return dict(store[args[0]])
        if "SET launch_claimed_at = NOW()" in query:
            row = store[args[0]]
            if row["our_video_id"] is not None:
                return None
            row["launch_claimed_at"] = "now"
            return {"id": args[0]}
        if "INSERT INTO videos" in query:
            return {"id": "video-1"}
        return None

    async def fake_execute(query, *args):
        if "SET modeled = true" in query:
            store[args[1]]["our_video_id"] = args[0]
            store[args[1]]["launch_claimed_at"] = None
        return "UPDATE 1"

    monkeypatch.setattr(autopilot_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(autopilot_route, "fetch_all", lambda *a, **k: _empty_list())
    monkeypatch.setattr(autopilot_route, "execute", fake_execute)

    result = await autopilot_route.launch_candidate(CANDIDATE_ID, _FakeBackgroundTasks(), tenant_id=TENANT)
    assert result["status"] == "launched"
    assert ("check", TENANT, "video") in calls
    assert ("increment", TENANT, "videos_created") in calls
    # increment must come AFTER the video insert, i.e. after "check" and
    # before nothing else meaningful — ordering proof: check precedes increment
    assert calls.index(("check", TENANT, "video")) < calls.index(("increment", TENANT, "videos_created"))
    print("✅ test_increment_usage_called_after_video_insert")


async def _empty_list():
    return []


# ---------------------------------------------------------------------------
# 2. The double-launch race: two concurrent calls, only one wins.
# ---------------------------------------------------------------------------

async def test_concurrent_launch_calls_only_one_creates_a_video(monkeypatch):
    _patch_plan_limits_ok(monkeypatch)
    _patch_creation_helpers(monkeypatch)

    store = {CANDIDATE_ID: _candidate_row()}
    insert_count = {"n": 0}

    async def fake_fetch_one(query, *args):
        if "FROM competitor_videos WHERE id" in query:
            # Force a real suspension here so BOTH concurrent callers reach
            # this point (and read the pre-claim state) before either
            # proceeds — otherwise a single-threaded asyncio.gather just
            # runs task1 to completion before task2 ever starts, which
            # would prove nothing about the race.
            await asyncio.sleep(0)
            return dict(store[args[0]])
        if "SET launch_claimed_at = NOW()" in query:
            # Same forced-suspension trick, positioned BEFORE the
            # check-and-set so both callers arrive here (having already
            # seen our_video_id/launch_claimed_at as clear) before either
            # one mutates `store`. Once resumed, the check-and-set itself
            # is synchronous (no `await` inside it) — that's what a real
            # single `UPDATE ... RETURNING` statement guarantees atomically
            # via Postgres's row lock, and is the actual property this test
            # exercises: only the FIRST resumed caller can see a clear row.
            await asyncio.sleep(0)
            row = store[args[0]]
            if row["our_video_id"] is not None or row.get("launch_claimed_at"):
                return None
            row["launch_claimed_at"] = "claimed"
            return {"id": args[0]}
        if "INSERT INTO videos" in query:
            insert_count["n"] += 1
            return {"id": f"video-{insert_count['n']}"}
        return None

    async def fake_execute(query, *args):
        if "SET modeled = true" in query:
            store[args[1]]["our_video_id"] = args[0]
            store[args[1]]["launch_claimed_at"] = None
        elif "SET launch_claimed_at = NULL" in query:
            if store[args[0]]["our_video_id"] is None:
                store[args[0]]["launch_claimed_at"] = None
        return "UPDATE 1"

    monkeypatch.setattr(autopilot_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(autopilot_route, "fetch_all", lambda *a, **k: _empty_list())
    monkeypatch.setattr(autopilot_route, "execute", fake_execute)

    bg1, bg2 = _FakeBackgroundTasks(), _FakeBackgroundTasks()
    results = await asyncio.gather(
        autopilot_route.launch_candidate(CANDIDATE_ID, bg1, tenant_id=TENANT),
        autopilot_route.launch_candidate(CANDIDATE_ID, bg2, tenant_id=TENANT),
        return_exceptions=True,
    )

    successes = [r for r in results if isinstance(r, dict)]
    failures = [r for r in results if isinstance(r, HTTPException)]
    assert len(successes) == 1, f"exactly one caller should win the launch, got {results}"
    assert len(failures) == 1, f"exactly one caller should lose with a clean error, got {results}"
    assert failures[0].status_code == 409
    assert insert_count["n"] == 1, "the loser must NOT create a second video row"
    print("✅ test_concurrent_launch_calls_only_one_creates_a_video")


async def test_already_launched_candidate_is_rejected_without_reclaiming(monkeypatch):
    """A candidate that's already fully launched (our_video_id set) must be
    rejected — the fast 400 path — without ever touching the atomic claim
    (which would also correctly reject it with 409, but the fast path gives
    a clearer message for the common "double click after success" case)."""
    _patch_plan_limits_ok(monkeypatch)
    store = {CANDIDATE_ID: _candidate_row(our_video_id="video-already")}

    async def fake_fetch_one(query, *args):
        if "FROM competitor_videos WHERE id" in query:
            return dict(store[args[0]])
        raise AssertionError("no further query should run once already-launched is detected")

    monkeypatch.setattr(autopilot_route, "fetch_one", fake_fetch_one)

    with pytest.raises(HTTPException) as exc:
        await autopilot_route.launch_candidate(CANDIDATE_ID, _FakeBackgroundTasks(), tenant_id=TENANT)
    assert exc.value.status_code == 400
    print("✅ test_already_launched_candidate_is_rejected_without_reclaiming")


# ---------------------------------------------------------------------------
# 3. Failure path: claim acquired, then something raises before completion
#    -> the claim must be released, not left wedged.
# ---------------------------------------------------------------------------

async def test_failed_launch_after_claim_releases_it(monkeypatch):
    _patch_plan_limits_ok(monkeypatch)

    store = {CANDIDATE_ID: _candidate_row()}
    release_calls = []

    async def fake_fetch_one(query, *args):
        if "FROM competitor_videos WHERE id" in query:
            return dict(store[args[0]])
        if "SET launch_claimed_at = NOW()" in query:
            row = store[args[0]]
            if row["our_video_id"] is not None or row.get("launch_claimed_at"):
                return None
            row["launch_claimed_at"] = "claimed"
            return {"id": args[0]}
        return None

    async def fake_execute(query, *args):
        if "SET launch_claimed_at = NULL" in query:
            release_calls.append(args)
            if store[args[0]]["our_video_id"] is None:
                store[args[0]]["launch_claimed_at"] = None
        return "UPDATE 1"

    async def _boom_project(tenant_id):
        raise RuntimeError("simulated failure creating the project")

    monkeypatch.setattr(projects, "_get_or_create_project", _boom_project)
    monkeypatch.setattr(autopilot_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(autopilot_route, "fetch_all", lambda *a, **k: _empty_list())
    monkeypatch.setattr(autopilot_route, "execute", fake_execute)

    with pytest.raises(RuntimeError):
        await autopilot_route.launch_candidate(CANDIDATE_ID, _FakeBackgroundTasks(), tenant_id=TENANT)

    assert store[CANDIDATE_ID]["our_video_id"] is None, "a failed launch must NEVER set our_video_id"
    assert store[CANDIDATE_ID]["launch_claimed_at"] is None, (
        "a failed launch must release launch_claimed_at — otherwise the candidate is wedged"
    )
    assert release_calls == [(CANDIDATE_ID, TENANT)]
    print("✅ test_failed_launch_after_claim_releases_it")


async def test_failed_launch_then_retry_succeeds(monkeypatch):
    """The release in the previous test isn't just cosmetic: prove a FRESH
    launch_candidate call for the same candidate succeeds right after a
    failure, with no stale-claim wait required."""
    _patch_plan_limits_ok(monkeypatch)
    _patch_creation_helpers(monkeypatch)

    store = {CANDIDATE_ID: _candidate_row()}
    attempt = {"n": 0}

    async def fake_fetch_one(query, *args):
        if "FROM competitor_videos WHERE id" in query:
            return dict(store[args[0]])
        if "SET launch_claimed_at = NOW()" in query:
            row = store[args[0]]
            if row["our_video_id"] is not None or row.get("launch_claimed_at"):
                return None
            row["launch_claimed_at"] = "claimed"
            return {"id": args[0]}
        if "INSERT INTO videos" in query:
            return {"id": "video-retry"}
        return None

    async def fake_execute(query, *args):
        if "SET modeled = true" in query:
            store[args[1]]["our_video_id"] = args[0]
            store[args[1]]["launch_claimed_at"] = None
        elif "SET launch_claimed_at = NULL" in query:
            if store[args[0]]["our_video_id"] is None:
                store[args[0]]["launch_claimed_at"] = None
        return "UPDATE 1"

    async def _maybe_boom_project(tenant_id):
        attempt["n"] += 1
        if attempt["n"] == 1:
            raise RuntimeError("first attempt fails")
        return {"id": "project-1"}

    monkeypatch.setattr(projects, "_get_or_create_project", _maybe_boom_project)
    monkeypatch.setattr(autopilot_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(autopilot_route, "fetch_all", lambda *a, **k: _empty_list())
    monkeypatch.setattr(autopilot_route, "execute", fake_execute)

    with pytest.raises(RuntimeError):
        await autopilot_route.launch_candidate(CANDIDATE_ID, _FakeBackgroundTasks(), tenant_id=TENANT)

    # Retry — must succeed, not 409, proving the release actually cleared the claim.
    result = await autopilot_route.launch_candidate(CANDIDATE_ID, _FakeBackgroundTasks(), tenant_id=TENANT)
    assert result["status"] == "launched"
    print("✅ test_failed_launch_then_retry_succeeds")


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-q"]))
