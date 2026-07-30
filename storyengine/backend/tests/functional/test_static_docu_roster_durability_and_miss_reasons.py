"""Tests for chunks C12 + C8 (2026-07-29).

C12 — the roster reference-photo sweep must survive a restart. Before this
fix, dispatch_roster_prefetch (static_docu.py) called a bare
asyncio.create_task(prefetch_roster_references(...)) with NO row in the
background_tasks table, so the repo's own reapers (routes/pipeline.py's
recover_stale_tasks / reap_stale_running_tasks) could never see, retry, or
even know the sweep existed. A restart or redeploy mid-sweep silently
dropped the fetch with zero record. Fix: _run_tracked_roster_prefetch wraps
the sweep in a background_tasks row (task_type='roster_prefetch'), and
resume_interrupted_roster_prefetches (called from main.py's lifespan,
mirroring the existing custom_film outbox pattern) finds rows the generic
startup reaper just flipped to 'failed' with the restart marker and
re-dispatches them — cheap and safe because prefetch_roster_references
already skips any machine already cached.

C8 — a miss used to be a bare absence. Three different problems (no
candidate found, a candidate found but never hosted, a candidate hosted but
vision-rejected) looked identical. Fix: _prefetch_one_machine now persists
WHY into static_reference_misses (scoped per tenant+video+machine, since
the same machine can miss for one video and succeed for another), cleared
the instant that machine verifies (prefetch, re-check, or manual seed).
pipeline_executor.roster_repair_dashboard surfaces reason_code/
reason_detail/retryable for the frontend.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_static_docu_roster_durability_and_miss_reasons.py -q
"""
import asyncio
import os
import sys
import uuid
from pathlib import Path

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PIPELINE_ROOT = _REPO_ROOT / "skills" / "video-pipeline"
if str(_PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_ROOT))

import static_docu  # noqa: E402
import pipeline_executor  # noqa: E402


# ---------------------------------------------------------------------------
# C8: miss-reason classification + clearing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_candidates_records_that_exact_reason(monkeypatch):
    """SEARCH FOUND NOTHING: _gather_reference_candidates returns an empty
    list -> reason_code must be no_candidates, and no hosting/vision call
    should even be attempted."""
    video_id, tenant_id = str(uuid.uuid4()), str(uuid.uuid4())
    machine = "Lend-Lease escort carriers Attacker class (US-built)"
    miss_writes = []

    async def fake_gather(machine_arg, aliases, query):
        return []

    async def fake_execute(query, *args):
        if "INSERT INTO static_reference_misses" in query:
            miss_writes.append(args)
        return None

    host_calls = []

    async def fake_host(*a, **k):
        host_calls.append(a)
        return "https://storage.example/x.jpg"

    monkeypatch.setattr(static_docu, "_gather_reference_candidates", fake_gather)
    monkeypatch.setattr(static_docu, "execute", fake_execute)
    monkeypatch.setattr(static_docu, "_host_reference", fake_host)

    result = await static_docu._prefetch_one_machine(tenant_id, video_id, machine, 0)

    assert result is False
    assert not host_calls, "no candidates means hosting must never be attempted"
    assert len(miss_writes) == 1
    tenant_arg, video_arg, mkey_arg, machine_arg, reason_arg, detail_arg = miss_writes[0]
    assert tenant_arg == tenant_id
    assert video_arg == video_id
    assert reason_arg == static_docu.REASON_NO_CANDIDATES
    assert "search returned nothing" in detail_arg.lower()


@pytest.mark.asyncio
async def test_fetch_failed_when_candidates_exist_but_none_host(monkeypatch):
    """A candidate URL was found but _host_reference fails for every one of
    them (dead link, blocked host) -> reason_code must be fetch_failed, NOT
    vision_rejected, since vision was never even reached."""
    video_id, tenant_id = str(uuid.uuid4()), str(uuid.uuid4())
    machine = "HMS Pretoria Castle (F61) Pretoria Castle class"
    miss_writes = []
    vision_calls = []

    async def fake_gather(machine_arg, aliases, query):
        return [("https://example.com/a.jpg", True), ("https://example.com/b.jpg", False)]

    async def fake_host(*a, **k):
        return None  # every candidate fails to host

    async def fake_vision(*a, **k):
        vision_calls.append(a)
        return True

    async def fake_execute(query, *args):
        if "INSERT INTO static_reference_misses" in query:
            miss_writes.append(args)
        return None

    monkeypatch.setattr(static_docu, "_gather_reference_candidates", fake_gather)
    monkeypatch.setattr(static_docu, "_host_reference", fake_host)
    monkeypatch.setattr(static_docu, "_vision_confirms", fake_vision)
    monkeypatch.setattr(static_docu, "execute", fake_execute)

    result = await static_docu._prefetch_one_machine(tenant_id, video_id, machine, 0)

    assert result is False
    assert not vision_calls, "vision must never run for a candidate that never hosted"
    assert len(miss_writes) == 1
    assert miss_writes[0][4] == static_docu.REASON_FETCH_FAILED


@pytest.mark.asyncio
async def test_vision_rejected_when_hosted_but_never_confirmed(monkeypatch):
    """VISION REJECTED IT: candidates are found and hosted, but
    _vision_confirms refuses every one -> reason_code must be
    vision_rejected, distinct from the other two misses."""
    video_id, tenant_id = str(uuid.uuid4()), str(uuid.uuid4())
    machine = "HMS Pretoria Castle (F61) Pretoria Castle class"
    miss_writes = []

    async def fake_gather(machine_arg, aliases, query):
        return [("https://example.com/a.jpg", True)]

    async def fake_host(*a, **k):
        return "https://storage.example/hosted.jpg"

    async def fake_vision(*a, **k):
        return False  # rejected

    async def fake_execute(query, *args):
        if "INSERT INTO static_reference_misses" in query:
            miss_writes.append(args)
        return None

    monkeypatch.setattr(static_docu, "_gather_reference_candidates", fake_gather)
    monkeypatch.setattr(static_docu, "_host_reference", fake_host)
    monkeypatch.setattr(static_docu, "_vision_confirms", fake_vision)
    monkeypatch.setattr(static_docu, "execute", fake_execute)

    result = await static_docu._prefetch_one_machine(tenant_id, video_id, machine, 0)

    assert result is False
    assert len(miss_writes) == 1
    assert miss_writes[0][4] == static_docu.REASON_VISION_REJECTED


@pytest.mark.asyncio
async def test_success_clears_any_prior_miss_row(monkeypatch):
    """A machine that verifies must have its (per-video) miss row deleted —
    a human should never see a stale "why it missed" reason for a machine
    that is now fine."""
    video_id, tenant_id = str(uuid.uuid4()), str(uuid.uuid4())
    machine = "Boeing XB-15"
    delete_calls = []
    cache_writes = []

    async def fake_gather(machine_arg, aliases, query):
        return [("https://example.com/a.jpg", True)]

    async def fake_host(*a, **k):
        return "https://storage.example/hosted.jpg"

    async def fake_vision(*a, **k):
        return True

    async def fake_execute(query, *args):
        if "DELETE FROM static_reference_misses" in query:
            delete_calls.append(args)
        if "INSERT INTO static_reference_cache" in query:
            cache_writes.append(args)
        return None

    monkeypatch.setattr(static_docu, "_gather_reference_candidates", fake_gather)
    monkeypatch.setattr(static_docu, "_host_reference", fake_host)
    monkeypatch.setattr(static_docu, "_vision_confirms", fake_vision)
    monkeypatch.setattr(static_docu, "execute", fake_execute)

    result = await static_docu._prefetch_one_machine(tenant_id, video_id, machine, 0)

    assert result is True
    assert len(cache_writes) == 1
    assert len(delete_calls) == 1
    assert delete_calls[0] == (tenant_id, video_id, static_docu._machine_key(machine))


@pytest.mark.asyncio
async def test_exception_mid_sweep_still_records_a_reason(monkeypatch):
    """An exception escaping _prefetch_one_machine (caught by
    prefetch_roster_references' own try/except) must still leave a miss
    reason behind — no miss should EVER be silently unexplained."""
    video_id, tenant_id = str(uuid.uuid4()), str(uuid.uuid4())
    roster = ["Boeing XB-15", "Northrop XB-35", "Convair YB-60"]
    video_row = {
        "id": video_id,
        "render_mode": "static_docu",
        "research_payload": {"documentary_style": "designed_vs_used", "unit_roster": roster},
    }
    miss_writes = []

    async def fake_fetch_one(query, *args):
        if "FROM videos" in query:
            return dict(video_row)
        if "FROM static_reference_cache" in query:
            return None
        return None

    async def fake_execute(query, *args):
        if "INSERT INTO static_reference_misses" in query:
            miss_writes.append(args)
        return None

    async def fake_lead_images(names, limit=3):
        if names[0] == "Boeing XB-15":
            raise RuntimeError("simulated blowup")
        return [{"url": f"https://en.wikipedia.org/thumb/{names[0]}.jpg",
                 "page": names[0], "trusted": True}]

    async def _empty(*a, **k):
        return []

    async def fake_host(url, vid, tid, tag):
        return f"https://storage.example/{tag}.jpg"

    async def fake_vision(*a, **k):
        return True

    monkeypatch.setattr(static_docu, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(static_docu, "execute", fake_execute)
    monkeypatch.setattr(static_docu, "find_wikipedia_lead_images", fake_lead_images)
    monkeypatch.setattr(static_docu, "find_article_images", _empty)
    monkeypatch.setattr(static_docu, "find_commons_photos", _empty)
    monkeypatch.setattr(static_docu, "_host_reference", fake_host)
    monkeypatch.setattr(static_docu, "_vision_confirms", fake_vision)

    result = await static_docu.prefetch_roster_references(video_id, tenant_id)

    assert result["missed"] == 1  # only Boeing XB-15 blew up
    assert result["verified"] == 2  # the other two still cached normally
    assert len(miss_writes) == 1
    assert miss_writes[0][4] == static_docu.REASON_ERROR


@pytest.mark.asyncio
async def test_warm_cache_hit_clears_stale_miss_from_a_prior_sweep(monkeypatch):
    """A machine already in the tenant-global static_reference_cache (e.g.
    verified via a DIFFERENT video, or seeded since the last sweep) must
    have any stale per-video miss row cleared too, not just skip re-fetch."""
    video_id, tenant_id = str(uuid.uuid4()), str(uuid.uuid4())
    roster = ["Boeing XB-15", "Northrop XB-35", "Convair YB-60"]
    video_row = {
        "id": video_id,
        "render_mode": "static_docu",
        "research_payload": {"documentary_style": "designed_vs_used", "unit_roster": roster},
    }
    delete_calls = []
    xb15_key = static_docu._machine_key("Boeing XB-15")

    async def fake_fetch_one(query, *args):
        if "FROM videos" in query:
            return dict(video_row)
        if "FROM static_reference_cache" in query:
            # Only "Boeing XB-15" is already warm in the tenant-global cache
            # (e.g. verified via a different video); the other two are not.
            if args[1] == xb15_key:
                return {"hosted_url": "https://storage.example/already-cached.jpg"}
            return None
        return None

    async def fake_execute(query, *args):
        if "DELETE FROM static_reference_misses" in query:
            delete_calls.append(args)
        return None

    async def _empty(*a, **k):
        return []

    monkeypatch.setattr(static_docu, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(static_docu, "execute", fake_execute)
    monkeypatch.setattr(static_docu, "find_wikipedia_lead_images", _empty)
    monkeypatch.setattr(static_docu, "find_article_images", _empty)
    monkeypatch.setattr(static_docu, "find_commons_photos", _empty)

    result = await static_docu.prefetch_roster_references(video_id, tenant_id)

    assert result["verified"] == 1  # only the already-cached XB-15
    assert result["missed"] == 2    # the other two found nothing (mocked empty)
    assert len(delete_calls) == 1
    assert delete_calls[0] == (tenant_id, video_id, xb15_key)


@pytest.mark.asyncio
async def test_roster_dashboard_surfaces_reason_for_missing_machine(monkeypatch):
    """pipeline_executor.roster_repair_dashboard's `reference` dict for a
    missing machine must carry reason_code/reason_detail/retryable read
    from static_reference_misses — this is what lets RosterStagePanel.tsx
    tell "wait", "retry", and "never built" apart instead of a bare
    "missing" for all three."""
    tenant_id, video_id = str(uuid.uuid4()), str(uuid.uuid4())
    roster = ["Boeing XB-15", "Northrop XB-35", "CVA-01"]
    video_row = {
        "id": video_id,
        "tenant_id": tenant_id,
        "render_mode": "static_docu",
        "research_payload": {"documentary_style": "designed_vs_used", "unit_roster": roster},
    }

    executor = pipeline_executor.PipelineExecutor(tenant_id)

    async def fake_ensure_initialized():
        return None

    async def fake_get_video(vid):
        return dict(video_row)

    async def fake_load_cards(vid, payload, roster=None, target_machine=None):
        return payload

    monkeypatch.setattr(executor, "_ensure_initialized", fake_ensure_initialized)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_load_machine_research_cards", fake_load_cards)

    xb15_key = static_docu._machine_key("Boeing XB-15")
    cva01_key = static_docu._machine_key("CVA-01")

    async def fake_fetch_all(query, *args):
        if "FROM machine_research_cards" in query:
            return []
        if "FROM static_reference_cache" in query:
            return [{"machine_key": xb15_key, "hosted_url": "https://storage.example/xb15.jpg",
                     "source_url": "https://en.wikipedia.org/xb15"}]
        if "FROM static_reference_misses" in query:
            return [{"machine_key": cva01_key, "reason_code": "never_built",
                     "reason_detail": "This machine was never actually built."}]
        return []

    monkeypatch.setattr(pipeline_executor, "fetch_all", fake_fetch_all)

    result = await executor.roster_repair_dashboard(video_id)

    assert result["status"] == "completed"
    units_by_machine = {u["machine"]: u for u in result["units"]}

    verified_unit = units_by_machine["Boeing XB-15"]
    assert verified_unit["reference"]["status"] == "verified"
    assert "reason_code" not in verified_unit["reference"]

    missing_unit = units_by_machine["CVA-01"]
    assert missing_unit["reference"]["status"] == "missing"
    assert missing_unit["reference"]["reason_code"] == "never_built"
    assert missing_unit["reference"]["retryable"] is False


@pytest.mark.asyncio
async def test_roster_dashboard_missing_with_no_miss_row_has_no_reason_fields(monkeypatch):
    """A machine that simply hasn't been swept yet (no static_reference_misses
    row at all) must degrade to the pre-C8 bare {"status": "missing"} shape —
    reason fields are additive, never fabricated."""
    tenant_id, video_id = str(uuid.uuid4()), str(uuid.uuid4())
    roster = ["Boeing XB-15", "Northrop XB-35", "Convair YB-60"]
    video_row = {
        "id": video_id,
        "tenant_id": tenant_id,
        "render_mode": "static_docu",
        "research_payload": {"documentary_style": "designed_vs_used", "unit_roster": roster},
    }

    executor = pipeline_executor.PipelineExecutor(tenant_id)

    async def fake_ensure_initialized():
        return None

    async def fake_get_video(vid):
        return dict(video_row)

    async def fake_load_cards(vid, payload, roster=None, target_machine=None):
        return payload

    monkeypatch.setattr(executor, "_ensure_initialized", fake_ensure_initialized)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_load_machine_research_cards", fake_load_cards)

    async def fake_fetch_all(query, *args):
        return []

    monkeypatch.setattr(pipeline_executor, "fetch_all", fake_fetch_all)

    result = await executor.roster_repair_dashboard(video_id)
    for unit in result["units"]:
        assert unit["reference"] == {"status": "missing"}


# ---------------------------------------------------------------------------
# C12: durable dispatch + restart recovery
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tracked_prefetch_registers_and_completes_a_background_tasks_row(monkeypatch):
    """_run_tracked_roster_prefetch (the coroutine dispatch_roster_prefetch
    now schedules instead of bare prefetch_roster_references) must INSERT a
    'running' background_tasks row under task_type='roster_prefetch' before
    the sweep, and close it out to 'completed' with a verified/missed
    summary once it's done — this is what makes the sweep visible to the
    repo's task-type-agnostic reapers."""
    video_id, tenant_id = str(uuid.uuid4()), str(uuid.uuid4())
    fake_task_id = str(uuid.uuid4())
    inserted = []
    updated = []

    async def fake_fetch_one(query, *args):
        if "INSERT INTO background_tasks" in query:
            inserted.append(args)
            return {"id": fake_task_id}
        return None

    async def fake_execute(query, *args):
        if "UPDATE background_tasks" in query:
            updated.append(args)
        return None

    async def fake_prefetch(vid, tid):
        assert vid == video_id and tid == tenant_id
        return {"status": "completed", "roster_count": 3, "verified": 2, "missed": 1}

    monkeypatch.setattr(static_docu, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(static_docu, "execute", fake_execute)
    monkeypatch.setattr(static_docu, "prefetch_roster_references", fake_prefetch)

    await static_docu._run_tracked_roster_prefetch(video_id, tenant_id)

    assert len(inserted) == 1
    ins_tenant, ins_video, ins_type, ins_message, ins_attempt = inserted[0]
    assert ins_tenant == tenant_id
    assert ins_video == video_id
    assert ins_type == static_docu._ROSTER_PREFETCH_TASK_TYPE == "roster_prefetch"
    assert ins_attempt == 1

    assert len(updated) == 1
    upd_status, upd_message, upd_task_id = updated[0]
    assert upd_status == "completed"
    assert "2" in upd_message and "1" in upd_message
    assert upd_task_id == fake_task_id


@pytest.mark.asyncio
async def test_tracked_prefetch_marks_row_failed_on_exception(monkeypatch):
    """If the sweep itself raises, the background_tasks row must close out
    as 'failed' (a status the DB CHECK constraint actually allows), not
    left dangling in 'running' or written with an invalid status string."""
    video_id, tenant_id = str(uuid.uuid4()), str(uuid.uuid4())
    fake_task_id = str(uuid.uuid4())
    updated = []

    async def fake_fetch_one(query, *args):
        if "INSERT INTO background_tasks" in query:
            return {"id": fake_task_id}
        return None

    async def fake_execute(query, *args):
        if "UPDATE background_tasks" in query:
            updated.append(args)
        return None

    async def fake_prefetch(vid, tid):
        raise RuntimeError("db blew up mid-sweep")

    monkeypatch.setattr(static_docu, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(static_docu, "execute", fake_execute)
    monkeypatch.setattr(static_docu, "prefetch_roster_references", fake_prefetch)

    # Must not raise — dispatch_roster_prefetch's whole point is that a
    # sweep failure never propagates to the research flow that triggered it.
    await static_docu._run_tracked_roster_prefetch(video_id, tenant_id)

    assert len(updated) == 1
    upd_status, upd_message, upd_task_id = updated[0]
    assert upd_status == "failed"
    assert "db blew up mid-sweep" in upd_message
    assert upd_task_id == fake_task_id


def test_dispatch_roster_prefetch_schedules_the_tracked_wrapper_not_bare_sweep(monkeypatch):
    """dispatch_roster_prefetch must schedule _run_tracked_roster_prefetch
    (the durability wrapper), not prefetch_roster_references directly —
    otherwise C12's registration never happens. Same fire-and-forget
    contract as before: exactly one asyncio.create_task call, never awaited
    here (the existing dispatch test already covers the create_task-count
    contract; this one asserts WHICH coroutine function got scheduled)."""
    scheduled = []

    def fake_create_task(coro):
        scheduled.append(coro)
        coro.close()
        return object()

    monkeypatch.setattr(asyncio, "create_task", fake_create_task)

    result = static_docu.dispatch_roster_prefetch(
        {"render_mode": "static_docu"}, "vid-1", "ten-1")

    assert result is True
    assert len(scheduled) == 1
    assert scheduled[0].cr_code.co_name == "_run_tracked_roster_prefetch"


@pytest.mark.asyncio
async def test_resume_finds_restart_interrupted_sweep_and_redispatches(monkeypatch):
    """The core C12 recovery path: a background_tasks row that the generic
    startup reaper (routes/pipeline.py's recover_stale_tasks) just flipped
    to status='failed' with the exact 'Server restarted...' marker, under
    task_type='roster_prefetch', must be picked up and re-dispatched as a
    fresh tracked sweep — WITHOUT any bespoke per-machine resume
    bookkeeping (prefetch_roster_references' own cache-skip does that)."""
    tenant_id, video_id = str(uuid.uuid4()), str(uuid.uuid4())

    async def fake_fetch_all(query, *args):
        assert query.strip().startswith("SELECT tenant_id, video_id")
        assert args[0] == "roster_prefetch"
        assert args[1] == "Server restarted — task interrupted"
        return [{"tenant_id": tenant_id, "video_id": video_id, "attempt": 1}]

    monkeypatch.setattr(static_docu, "fetch_all", fake_fetch_all)

    scheduled = []

    def fake_create_task(coro):
        scheduled.append(coro)
        coro.close()
        return object()

    monkeypatch.setattr(asyncio, "create_task", fake_create_task)

    resumed = await static_docu.resume_interrupted_roster_prefetches()

    assert resumed == 1
    assert len(scheduled) == 1
    assert scheduled[0].cr_code.co_name == "_run_tracked_roster_prefetch"


@pytest.mark.asyncio
async def test_resume_stops_after_max_attempts_instead_of_looping_forever(monkeypatch):
    """A roster that keeps genuinely failing (not just being interrupted)
    must eventually stop auto-resuming across restarts, rather than
    retrying identically forever."""
    tenant_id, video_id = str(uuid.uuid4()), str(uuid.uuid4())

    async def fake_fetch_all(query, *args):
        return [{
            "tenant_id": tenant_id, "video_id": video_id,
            "attempt": static_docu._ROSTER_PREFETCH_MAX_RESUME_ATTEMPTS,
        }]

    monkeypatch.setattr(static_docu, "fetch_all", fake_fetch_all)

    scheduled = []
    monkeypatch.setattr(asyncio, "create_task", lambda coro: (scheduled.append(coro), coro.close(), object())[-1])

    resumed = await static_docu.resume_interrupted_roster_prefetches()

    assert resumed == 0
    assert scheduled == []


@pytest.mark.asyncio
async def test_resume_scan_error_is_non_blocking(monkeypatch):
    """A DB error during the resume scan itself must never raise — startup
    must never be blocked by this best-effort recovery pass."""
    async def fake_fetch_all(query, *args):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(static_docu, "fetch_all", fake_fetch_all)

    resumed = await static_docu.resume_interrupted_roster_prefetches()

    assert resumed == 0
