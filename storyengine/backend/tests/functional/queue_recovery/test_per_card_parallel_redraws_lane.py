"""C1b (feat/per-card-parallel-clips, backend enabler for parallel image
redraw): the route-level concurrency-safety mechanism for
POST /api/pipeline/redraw-image/{video_id} — the image-redraw sibling of
tests/functional/queue_recovery/test_per_card_parallel_clips_lane.py (C1's
same proof for clips).

Whole-feature context: before this chunk, EVERY redraw call ran in
routes/pipeline.py's exclusive "main" lane (via the un-lane-qualified
`_is_task_active(video_id, tenant_id)` call), so tapping Redraw on a second
card while the first was still redrawing 409'd. This chunk lets a manual
run target a SET of asset ids (`asset_ids`, additive alongside the existing
required `asset_id`) and routes every TARGETED run (one id or several)
through a new "redraw_manual" lane that — unlike every other lane in
_is_task_active — does not block a second call to itself, so several manual
redraws animate concurrently instead of queueing.

This pins the actual safety contract requirement, at the ROUTE level (see
tests/functional/test_per_card_parallel_redraws_executor.py for the
companion ASSET-level guard inside redraw_asset_images itself):

  1. `_normalize_manual_redraw_ids` correctly unifies asset_id/asset_ids
     (comma-separated, repeated params, both, dedup) — and returns None
     when NEITHER is given (redraw has no "redraw everything" fallback, so
     the route itself turns that into a 400 — not tested here, see the
     route-level test file, if any is added for the HTTP layer).
  2. lane="redraw_manual" is NOT blocked by another already-active
     "redraw_manual" run (the actual feature) ...
  3. ... but IS still blocked while "main" is running (a full pipeline
     stage never races a manual redraw) ...
  4. ... and, symmetrically, "main" (a full-scene/full-video build) is
     blocked while ANY manual redraw run is in flight — including when TWO
     manual runs overlap and only the SECOND one to start finishes first
     (the ref-counted _manual_redraw_begin/_manual_redraw_finish behavior:
     "main" must stay blocked until the LAST manual run finishes, not the
     first).
  5. "clip_manual" and "redraw_manual" are independent lanes — an active
     manual CLIP run does not block a manual REDRAW run on the same video,
     and vice versa (they're different resources; see redraw_asset_claims.py
     and clip_asset_claims.py's module docstrings for why they're kept
     separate).

Reuses this directory's conftest.py heavy-mock fixture (same one
test_per_card_parallel_clips_lane.py uses) — stubs asyncpg/database/
error_utils/status_map/... and evicts routes.pipeline after each test so
module-level _running_tasks/_side_lanes/_manual_redraw_refcount state never
leaks between tests.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/queue_recovery/test_per_card_parallel_redraws_lane.py -q
"""
from unittest.mock import AsyncMock, patch

import pytest

import routes.pipeline as pipeline


# --- 1. _normalize_manual_redraw_ids -----------------------------------------

def test_normalize_returns_none_when_neither_param_given():
    assert pipeline._normalize_manual_redraw_ids(None, None) is None


def test_normalize_singular_asset_id_only():
    assert pipeline._normalize_manual_redraw_ids("a", None) == ["a"]


def test_normalize_repeated_query_params():
    assert pipeline._normalize_manual_redraw_ids(None, ["a", "b"]) == ["a", "b"]


def test_normalize_comma_separated_single_value():
    assert pipeline._normalize_manual_redraw_ids(None, ["a,b,c"]) == ["a", "b", "c"]


def test_normalize_mixed_repeated_and_comma_separated():
    assert pipeline._normalize_manual_redraw_ids(None, ["a,b", "c"]) == ["a", "b", "c"]


def test_normalize_merges_asset_id_and_asset_ids_deduped_order_preserving():
    assert pipeline._normalize_manual_redraw_ids("a", ["a", "b"]) == ["a", "b"]


def test_normalize_strips_whitespace_and_drops_empties():
    assert pipeline._normalize_manual_redraw_ids(None, [" a , , b ,c "]) == ["a", "b", "c"]


def test_normalize_redraw_and_clip_share_the_same_parsing_rules():
    """Both are thin wrappers over the same `_normalize_multi_asset_ids` —
    pin that they never drift apart for the same inputs."""
    for args in (("a", None), (None, ["a", "b"]), (None, ["a,b,c"]), (None, None)):
        assert pipeline._normalize_manual_redraw_ids(*args) == pipeline._normalize_manual_clip_ids(*args)


# --- 2 & 3. redraw_manual lane: no self-block, still blocked by main --------

@pytest.mark.asyncio
async def test_redraw_manual_not_blocked_by_another_redraw_manual_run():
    """The core ask: a manual redraw run must NOT 409 against another
    manual redraw run on the same video."""
    video_id, tenant_id = "video-rm1", "tenant-rm1"
    pipeline._manual_redraw_begin(video_id, tenant_id)
    try:
        with patch("generation_claims.is_blocked", new=AsyncMock(return_value=False)):
            result = await pipeline._is_task_active(video_id, tenant_id, lane="redraw_manual")
        assert result is False, "a second manual redraw run must NOT be blocked by the first"
    finally:
        pipeline._manual_redraw_finish(video_id, tenant_id)
    print("✅ test_redraw_manual_not_blocked_by_another_redraw_manual_run")


@pytest.mark.asyncio
async def test_redraw_manual_blocked_while_main_is_running():
    """A full pipeline stage (script/storyboards/a full-video build/...)
    must still block a manual redraw run — the relaxation is ONLY
    self-vs-self among manual redraw runs, never main-vs-manual."""
    import time
    video_id, tenant_id = "video-rm2", "tenant-rm2"
    key = (tenant_id, video_id)
    pipeline._running_tasks[key] = {
        "status": "running", "message": None, "error": None,
        "lane": "main", "started_at": time.time(),
    }
    try:
        result = await pipeline._is_task_active(video_id, tenant_id, lane="redraw_manual")
        assert result is True, "a manual redraw run must be blocked while main is running"
    finally:
        pipeline._running_tasks.pop(key, None)
    print("✅ test_redraw_manual_blocked_while_main_is_running")


@pytest.mark.asyncio
async def test_main_still_blocked_by_a_different_active_redraw_manual_run_id():
    """Sanity: two DIFFERENT videos never cross-block each other."""
    pipeline._manual_redraw_begin("video-other-rm", "tenant-rm3")
    try:
        with patch("generation_claims.is_blocked", new=AsyncMock(return_value=False)):
            result = await pipeline._is_task_active("video-unrelated-rm", "tenant-rm3", lane="main")
        assert result is False, "an unrelated video must not see another video's manual redraw run"
    finally:
        pipeline._manual_redraw_finish("video-other-rm", "tenant-rm3")
    print("✅ test_main_still_blocked_by_a_different_active_redraw_manual_run_id")


# --- 4. main is blocked while ANY manual redraw run is active (ref-counted) -

@pytest.mark.asyncio
async def test_main_blocked_while_a_single_manual_redraw_run_is_active():
    video_id, tenant_id = "video-rm4", "tenant-rm4"
    pipeline._manual_redraw_begin(video_id, tenant_id)
    try:
        result = await pipeline._is_task_active(video_id, tenant_id, lane="main")
        assert result is True, "a full build must not start while a manual redraw run is in flight"
    finally:
        pipeline._manual_redraw_finish(video_id, tenant_id)
    with patch("generation_claims.is_blocked", new=AsyncMock(return_value=False)):
        result = await pipeline._is_task_active(video_id, tenant_id, lane="main")
    assert result is False, "main must be free again once the manual redraw run finished"
    print("✅ test_main_blocked_while_a_single_manual_redraw_run_is_active")


@pytest.mark.asyncio
async def test_main_stays_blocked_until_the_last_of_two_overlapping_manual_redraw_runs_finishes():
    """The ref-count is the point of _manual_redraw_begin/_manual_redraw_finish:
    two manual redraw runs overlap, the FIRST one to start finishes FIRST (an
    arbitrary interleaving, not FIFO) — main must stay blocked because a
    SECOND manual run is still going. Only after BOTH finish does main free
    up."""
    video_id, tenant_id = "video-rm5", "tenant-rm5"
    pipeline._manual_redraw_begin(video_id, tenant_id)  # run A starts
    pipeline._manual_redraw_begin(video_id, tenant_id)  # run B starts (overlap)

    result = await pipeline._is_task_active(video_id, tenant_id, lane="main")
    assert result is True, "main must be blocked while 2 manual redraw runs are active"

    pipeline._manual_redraw_finish(video_id, tenant_id)  # run A finishes (B still going)
    result = await pipeline._is_task_active(video_id, tenant_id, lane="main")
    assert result is True, (
        "main must STAY blocked — a second manual redraw run (B) is still in flight; "
        "this is the exact bug a non-ref-counted single-slot lane would have"
    )

    pipeline._manual_redraw_finish(video_id, tenant_id)  # run B finishes (last one)
    with patch("generation_claims.is_blocked", new=AsyncMock(return_value=False)):
        result = await pipeline._is_task_active(video_id, tenant_id, lane="main")
    assert result is False, "main must be free once the LAST manual redraw run has finished"
    print("✅ test_main_stays_blocked_until_the_last_of_two_overlapping_manual_redraw_runs_finishes")


@pytest.mark.asyncio
async def test_two_overlapping_redraw_manual_calls_never_409_each_other():
    """End-to-end shape: simulate two manual redraw dispatches back to back
    the way the route does it (check -> begin -> check -> begin) and
    confirm neither ever sees 'busy' from the other."""
    video_id, tenant_id = "video-rm6", "tenant-rm6"
    with patch("generation_claims.is_blocked", new=AsyncMock(return_value=False)):
        blocked1 = await pipeline._is_task_active(video_id, tenant_id, lane="redraw_manual")
        assert blocked1 is False
        pipeline._manual_redraw_begin(video_id, tenant_id)

        blocked2 = await pipeline._is_task_active(video_id, tenant_id, lane="redraw_manual")
        assert blocked2 is False, "run 2 must not be 409'd by run 1"
        pipeline._manual_redraw_begin(video_id, tenant_id)

    pipeline._manual_redraw_finish(video_id, tenant_id)
    pipeline._manual_redraw_finish(video_id, tenant_id)
    print("✅ test_two_overlapping_redraw_manual_calls_never_409_each_other")


# --- 5. clip_manual and redraw_manual are independent lanes -----------------

@pytest.mark.asyncio
async def test_active_clip_manual_run_does_not_block_a_redraw_manual_run():
    video_id, tenant_id = "video-rm7", "tenant-rm7"
    pipeline._manual_clip_begin(video_id, tenant_id)
    try:
        with patch("generation_claims.is_blocked", new=AsyncMock(return_value=False)):
            result = await pipeline._is_task_active(video_id, tenant_id, lane="redraw_manual")
        assert result is False, "an active manual CLIP run must not block a manual REDRAW run"
    finally:
        pipeline._manual_clip_finish(video_id, tenant_id)
    print("✅ test_active_clip_manual_run_does_not_block_a_redraw_manual_run")


@pytest.mark.asyncio
async def test_active_redraw_manual_run_does_not_block_a_clip_manual_run():
    video_id, tenant_id = "video-rm8", "tenant-rm8"
    pipeline._manual_redraw_begin(video_id, tenant_id)
    try:
        with patch("generation_claims.is_blocked", new=AsyncMock(return_value=False)):
            result = await pipeline._is_task_active(video_id, tenant_id, lane="clip_manual")
        assert result is False, "an active manual REDRAW run must not block a manual CLIP run"
    finally:
        pipeline._manual_redraw_finish(video_id, tenant_id)
    print("✅ test_active_redraw_manual_run_does_not_block_a_clip_manual_run")


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-q"]))
