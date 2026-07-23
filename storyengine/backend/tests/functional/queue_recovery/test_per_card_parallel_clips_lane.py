"""C1 (feat/per-card-parallel-clips, backend enabler): the route-level
concurrency-safety mechanism for POST /api/pipeline/clip/{video_id}.

Whole-feature context: today ALL clip runs (one card, one scene, or the
whole video) share routes/pipeline.py's exclusive "main" lane, so tapping
a second card while the first is still animating 409s. This chunk lets a
manual run target a SET of asset ids (`asset_ids`, additive alongside the
existing `asset_id`) and routes every TARGETED run (one id or several)
through a new "clip_manual" lane that — unlike every other lane in
_is_task_active — does not block a second call to itself, so several
manual clip runs animate concurrently instead of queueing.

This pins the actual safety contract requirement 3 asks for, at the ROUTE
level (see tests/functional/test_per_card_parallel_clips_executor.py for
the companion ASSET-level guard inside run_clip_generation itself):

  1. `_normalize_manual_clip_ids` correctly unifies asset_id/asset_ids
     (comma-separated, repeated params, both, dedup) — and returns None
     for a genuine scene/full-video request (so those keep using "main").
  2. lane="clip_manual" is NOT blocked by another already-active
     "clip_manual" run (the actual feature) ...
  3. ... but IS still blocked while "main" is running (a full pipeline
     stage never races a manual clip run) ...
  4. ... and, symmetrically, "main" (a full-scene/full-video build) is
     blocked while ANY manual clip run is in flight — including when TWO
     manual runs overlap and only the SECOND one to start finishes first
     (the ref-counted _manual_clip_begin/_manual_clip_finish behavior:
     "main" must stay blocked until the LAST manual run finishes, not the
     first).

Reuses this directory's conftest.py heavy-mock fixture (same one
test_c16a_manual_routes_claim_check.py uses) — stubs asyncpg/database/
error_utils/status_map/... and evicts routes.pipeline after each test so
module-level _running_tasks/_side_lanes/_manual_clip_refcount state never
leaks between tests.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/queue_recovery/test_per_card_parallel_clips_lane.py -q
"""
from unittest.mock import AsyncMock, patch

import pytest

import routes.pipeline as pipeline


@pytest.fixture(autouse=True)
def _normal_drain_state():
    """These lane tests predate drain-mode's merge into _is_task_active and
    never exercise the drain gate itself — keep drain "normal" so the
    pre-existing lane assertions run unchanged. Mirrors
    test_c16a_manual_routes_claim_check.py's identical fixture."""
    with patch.object(
        pipeline.drain_mode,
        "assert_accepting_new_work",
        new=AsyncMock(return_value=None),
    ):
        yield


# --- 1. _normalize_manual_clip_ids ------------------------------------------

def test_normalize_returns_none_when_neither_param_given():
    assert pipeline._normalize_manual_clip_ids(None, None) is None


def test_normalize_singular_asset_id_only():
    assert pipeline._normalize_manual_clip_ids("a", None) == ["a"]


def test_normalize_repeated_query_params():
    # FastAPI's Query(None) with List[str] already collects ?asset_ids=a&asset_ids=b
    # into ["a", "b"] before this function ever sees it.
    assert pipeline._normalize_manual_clip_ids(None, ["a", "b"]) == ["a", "b"]


def test_normalize_comma_separated_single_value():
    # ?asset_ids=a,b,c arrives as a 1-element list ["a,b,c"].
    assert pipeline._normalize_manual_clip_ids(None, ["a,b,c"]) == ["a", "b", "c"]


def test_normalize_mixed_repeated_and_comma_separated():
    assert pipeline._normalize_manual_clip_ids(None, ["a,b", "c"]) == ["a", "b", "c"]


def test_normalize_merges_asset_id_and_asset_ids_deduped_order_preserving():
    assert pipeline._normalize_manual_clip_ids("a", ["a", "b"]) == ["a", "b"]


def test_normalize_strips_whitespace_and_drops_empties():
    assert pipeline._normalize_manual_clip_ids(None, [" a , , b ,c "]) == ["a", "b", "c"]


# --- 2 & 3. clip_manual lane: no self-block, still blocked by main ----------

@pytest.mark.asyncio
async def test_clip_manual_not_blocked_by_another_clip_manual_run():
    """The core ask: a manual clip run must NOT 409 against another
    manual clip run on the same video."""
    video_id, tenant_id = "video-cm1", "tenant-cm1"
    pipeline._manual_clip_begin(video_id, tenant_id)
    try:
        with patch("generation_claims.is_blocked", new=AsyncMock(return_value=False)):
            result = await pipeline._is_task_active(video_id, tenant_id, lane="clip_manual")
        assert result is False, "a second manual clip run must NOT be blocked by the first"
    finally:
        pipeline._manual_clip_finish(video_id, tenant_id)
    print("✅ test_clip_manual_not_blocked_by_another_clip_manual_run")


@pytest.mark.asyncio
async def test_clip_manual_blocked_while_main_is_running():
    """A full pipeline stage (script/storyboards/a full-video build/...)
    must still block a manual clip run — the relaxation is ONLY
    self-vs-self among manual runs, never main-vs-manual."""
    import time
    video_id, tenant_id = "video-cm2", "tenant-cm2"
    key = (tenant_id, video_id)
    pipeline._running_tasks[key] = {
        "status": "running", "message": None, "error": None,
        "lane": "main", "started_at": time.time(),
    }
    try:
        result = await pipeline._is_task_active(video_id, tenant_id, lane="clip_manual")
        assert result is True, "a manual clip run must be blocked while main is running"
    finally:
        pipeline._running_tasks.pop(key, None)
    print("✅ test_clip_manual_blocked_while_main_is_running")


@pytest.mark.asyncio
async def test_main_still_blocked_by_a_different_active_clip_manual_run_id():
    """Sanity: two DIFFERENT videos never cross-block each other."""
    pipeline._manual_clip_begin("video-other", "tenant-cm3")
    try:
        with patch("generation_claims.is_blocked", new=AsyncMock(return_value=False)):
            result = await pipeline._is_task_active("video-unrelated", "tenant-cm3", lane="main")
        assert result is False, "an unrelated video must not see another video's manual run"
    finally:
        pipeline._manual_clip_finish("video-other", "tenant-cm3")
    print("✅ test_main_still_blocked_by_a_different_active_clip_manual_run_id")


# --- 4. main is blocked while ANY manual run is active (ref-counted) -------

@pytest.mark.asyncio
async def test_main_blocked_while_a_single_manual_run_is_active():
    video_id, tenant_id = "video-cm4", "tenant-cm4"
    pipeline._manual_clip_begin(video_id, tenant_id)
    try:
        result = await pipeline._is_task_active(video_id, tenant_id, lane="main")
        assert result is True, "a full build must not start while a manual clip run is in flight"
    finally:
        pipeline._manual_clip_finish(video_id, tenant_id)
    # And once the (only) manual run finishes, main must be free again.
    with patch("generation_claims.is_blocked", new=AsyncMock(return_value=False)):
        result = await pipeline._is_task_active(video_id, tenant_id, lane="main")
    assert result is False, "main must be free again once the manual run finished"
    print("✅ test_main_blocked_while_a_single_manual_run_is_active")


@pytest.mark.asyncio
async def test_main_stays_blocked_until_the_last_of_two_overlapping_manual_runs_finishes():
    """The ref-count is the point of _manual_clip_begin/_manual_clip_finish:
    two manual runs overlap, the FIRST one to start finishes FIRST (an
    arbitrary interleaving, not FIFO) — main must stay blocked because a
    SECOND manual run is still going. Only after BOTH finish does main free
    up. A naive single-slot _lane_begin/_lane_finish would have popped the
    lane entirely after the first finish and wrongly let main proceed."""
    video_id, tenant_id = "video-cm5", "tenant-cm5"
    pipeline._manual_clip_begin(video_id, tenant_id)  # run A starts
    pipeline._manual_clip_begin(video_id, tenant_id)  # run B starts (overlap)

    result = await pipeline._is_task_active(video_id, tenant_id, lane="main")
    assert result is True, "main must be blocked while 2 manual runs are active"

    pipeline._manual_clip_finish(video_id, tenant_id)  # run A finishes (B still going)
    result = await pipeline._is_task_active(video_id, tenant_id, lane="main")
    assert result is True, (
        "main must STAY blocked — a second manual run (B) is still in flight; "
        "this is the exact bug a non-ref-counted single-slot lane would have"
    )

    pipeline._manual_clip_finish(video_id, tenant_id)  # run B finishes (last one)
    with patch("generation_claims.is_blocked", new=AsyncMock(return_value=False)):
        result = await pipeline._is_task_active(video_id, tenant_id, lane="main")
    assert result is False, "main must be free once the LAST manual run has finished"
    print("✅ test_main_stays_blocked_until_the_last_of_two_overlapping_manual_runs_finishes")


@pytest.mark.asyncio
async def test_two_overlapping_clip_manual_calls_never_409_each_other():
    """End-to-end shape of requirement (d): simulate two manual clip
    dispatches back to back the way the route does it (begin -> check ->
    begin) and confirm neither ever sees 'busy' from the other."""
    video_id, tenant_id = "video-cm6", "tenant-cm6"
    with patch("generation_claims.is_blocked", new=AsyncMock(return_value=False)):
        # Run 1 checks the gate, then registers itself (mirrors the route:
        # check first, begin only if the check passes).
        blocked1 = await pipeline._is_task_active(video_id, tenant_id, lane="clip_manual")
        assert blocked1 is False
        pipeline._manual_clip_begin(video_id, tenant_id)

        # Run 2 arrives while run 1 is still in flight.
        blocked2 = await pipeline._is_task_active(video_id, tenant_id, lane="clip_manual")
        assert blocked2 is False, "run 2 must not be 409'd by run 1"
        pipeline._manual_clip_begin(video_id, tenant_id)

    pipeline._manual_clip_finish(video_id, tenant_id)
    pipeline._manual_clip_finish(video_id, tenant_id)
    print("✅ test_two_overlapping_clip_manual_calls_never_409_each_other")


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-q"]))
