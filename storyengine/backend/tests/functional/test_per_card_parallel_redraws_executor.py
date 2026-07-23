"""C1b (feat/per-card-parallel-clips, backend enabler for parallel image
redraw): scripts.coverage_to_app.redraw_asset_images' multi-asset manual
run. The image-redraw sibling of
tests/functional/test_per_card_parallel_clips_executor.py (C1's identical
proof for pipeline_executor.run_clip_generation).

Companion to tests/functional/queue_recovery/test_per_card_parallel_redraws_lane.py
(the ROUTE-level "redraw_manual" lane doesn't 409 itself); this file proves
the ASSET-level guard inside redraw_asset_images itself — the actual
money-safety mechanism, since the route's lane relaxation alone would let
two overlapping manual runs both redraw the same picture (double spend, and
a clobbered image_url write) without it.

Same mocking technique as tests/functional/test_redraw_style_parity.py
(module-level fetch_one/fetch_all/execute/record_ledger_entry/get_secret/
ImageClient/generate_scene_image_for_model/_stable_url patched directly on
scripts.coverage_to_app) — no live DB, no real spend.

Covers the required proofs:
  (a) a request with 2+ asset_ids redraws ALL of them.
  (b) a single asset_id is a claim-guarded PASSTHROUGH to redraw_asset_image
      — same result shape as calling it directly (byte-for-byte on the
      happy path), proving the claim step is the only new thing in that path.
  (c) two overlapping manual runs (simulated via asyncio.gather, same
      video) never redraw the same asset twice, even when their requested
      sets overlap — redraw_asset_claims is what makes this deterministic
      regardless of asyncio scheduling order.
  (d) an id already claimed by another in-flight run is skipped, not
      re-redrawn, and reported as `in_progress_elsewhere`.
  (e) a request for ids that don't exist under this (video, tenant) fails
      cleanly (single vs. multi error wording), no claim ever taken.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_per_card_parallel_redraws_executor.py -q
"""
import asyncio
import os
import sys

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))

import scripts.coverage_to_app as cta_mod  # noqa: E402
import redraw_asset_claims  # noqa: E402

TENANT = "tenant-c1b"
VIDEO = "video-c1b"


def _asset_row(asset_id, scene, image_index):
    return {
        "id": asset_id, "scene": scene, "image_index": image_index,
        "image_prompt": f"a factory floor, shot {asset_id}",
        "aspect": "16:9", "image_model_override": None,
        "image_style_override": None, "visual_style": None,
    }


def _install_common_mocks(monkeypatch, rows_by_id, *, gen_delay: float = 0.0,
                           execute_delay: float = 0.0):
    """Wires the standard DB/image/ledger fakes on scripts.coverage_to_app.
    `rows_by_id` is the full fixture set; fake_fetch_all's candidate query
    filters it by whatever id list the query actually asks for (via
    `id = ANY($3::uuid[])`), so each concurrent call only ever sees the
    rows IT requested — exactly like the real query would once Postgres
    applies the WHERE clause."""
    ledger_calls = []
    image_updates = []  # asset ids that got an image_url write
    gen_calls = []

    async def fake_fetch_one(query, *args):
        if "FROM assets a JOIN videos v" in query:
            aid = args[0]
            row = rows_by_id.get(aid)
            return dict(row) if row else None
        if "coverage_directive, scene_text FROM scripts" in query:
            return {"coverage_directive": "", "scene_text": ""}
        raise AssertionError(f"unexpected fetch_one: {query}")

    async def fake_fetch_all(query, *args):
        if "FROM assets WHERE" in query and "id = ANY" in query:
            ids = args[-1]
            return [
                {"id": r["id"], "scene": r["scene"], "image_index": r["image_index"]}
                for aid, r in rows_by_id.items() if aid in ids
            ]
        if "FROM video_characters" in query:
            return []
        raise AssertionError(f"unexpected fetch_all: {query}")

    async def fake_execute(query, *args):
        if "UPDATE assets SET image_url" in query:
            if execute_delay:
                await asyncio.sleep(execute_delay)
            image_updates.append(args[-2])  # asset id (second-to-last param)
        return "OK"

    async def fake_get_secret(*a, **k):
        return "fake-key"

    async def fake_gen(ic, model_override, prompt, reference_urls=None, **kw):
        if gen_delay:
            await asyncio.sleep(gen_delay)
        gen_calls.append(prompt)
        return "https://fake/redrawn.png", "gpt-image-2"

    async def fake_stable_url(url, path, tenant_id):
        return f"https://stable/{path}"

    async def fake_approved_envs(*a, **k):
        return []

    async def fake_record_ledger_entry(**kwargs):
        ledger_calls.append(kwargs)

    monkeypatch.setattr(cta_mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(cta_mod, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(cta_mod, "execute", fake_execute)
    monkeypatch.setattr(cta_mod, "get_secret", fake_get_secret)
    monkeypatch.setattr(cta_mod, "ImageClient", lambda **kw: object())
    monkeypatch.setattr(cta_mod, "generate_scene_image_for_model", fake_gen)
    monkeypatch.setattr(cta_mod, "_stable_url", fake_stable_url)
    monkeypatch.setattr(cta_mod, "_approved_envs", fake_approved_envs)
    monkeypatch.setattr(cta_mod, "record_ledger_entry", fake_record_ledger_entry)
    return ledger_calls, image_updates, gen_calls


@pytest.fixture(autouse=True)
def _reset_claims():
    """redraw_asset_claims is a module-level dict — clear it before AND
    after each test so a failed/aborted test can never leak a stale claim
    into the next one."""
    redraw_asset_claims._claimed.clear()
    yield
    redraw_asset_claims._claimed.clear()


# --- (a) a request with 2+ asset_ids redraws ALL of them --------------------

def test_multi_asset_ids_redraws_every_requested_asset(monkeypatch):
    rows = {
        "asset-A": _asset_row("asset-A", scene=1, image_index=1),
        "asset-B": _asset_row("asset-B", scene=1, image_index=2),
        "asset-C": _asset_row("asset-C", scene=2, image_index=1),
    }
    ledger_calls, image_updates, gen_calls = _install_common_mocks(monkeypatch, rows)

    result = asyncio.run(cta_mod.redraw_asset_images(
        VIDEO, TENANT, ["asset-A", "asset-B", "asset-C"]))

    assert result["status"] == "completed", result
    assert result["redrawn"] == 3
    assert result["failed"] == 0
    assert sorted(image_updates) == ["asset-A", "asset-B", "asset-C"]
    assert len(ledger_calls) == 3, "one ledger row per redrawn picture"
    assert len(gen_calls) == 3
    # Claims must be fully released once the run completes.
    assert redraw_asset_claims.claimed_ids(TENANT, VIDEO) == set()


# --- (b) a single asset_id is a claim-guarded passthrough -------------------

def test_single_asset_id_is_a_claim_guarded_passthrough(monkeypatch):
    """The wrapper's result for a lone id must be BYTE-IDENTICAL to calling
    redraw_asset_image directly — the claim step is the only new thing."""
    rows = {"asset-1": _asset_row("asset-1", scene=1, image_index=1)}
    _install_common_mocks(monkeypatch, rows)

    result_wrapped = asyncio.run(cta_mod.redraw_asset_images(VIDEO, TENANT, ["asset-1"]))
    assert redraw_asset_claims.claimed_ids(TENANT, VIDEO) == set(), (
        "the passthrough path must still release its claim when done")

    result_direct = asyncio.run(cta_mod.redraw_asset_image(VIDEO, TENANT, "asset-1"))

    assert result_wrapped == result_direct, (
        f"wrapped={result_wrapped!r} vs direct={result_direct!r} — "
        "a single-id manual redraw must return the exact pre-C1b result shape"
    )
    assert result_wrapped["status"] == "completed"
    assert "cost" in result_wrapped


# --- (c) two overlapping manual runs never double-redraw the shared asset --

def test_overlapping_manual_runs_never_double_redraw_the_shared_asset(monkeypatch):
    """The crux test. Two manual runs on the SAME video, with OVERLAPPING
    asset sets ({A, B} and {B, C}), fired concurrently (asyncio.gather —
    the same event loop a real overlapping pair of HTTP requests would
    share). Asset B must be redrawn by EXACTLY ONE of the two runs, never
    both, regardless of which run's coroutine happens to reach the claim
    point first."""
    rows = {
        "asset-A": _asset_row("asset-A", scene=1, image_index=1),
        "asset-B": _asset_row("asset-B", scene=1, image_index=2),
        "asset-C": _asset_row("asset-C", scene=2, image_index=1),
    }
    # A small delay on the generation + DB write widens the window where a
    # broken (unguarded) implementation could interleave and double-process
    # B — makes this test a real proof, not one that only passes by
    # accident of both calls finishing before either yields.
    ledger_calls, image_updates, gen_calls = _install_common_mocks(
        monkeypatch, rows, gen_delay=0.01, execute_delay=0.01)

    async def _run_both():
        return await asyncio.gather(
            cta_mod.redraw_asset_images(VIDEO, TENANT, ["asset-A", "asset-B"]),
            cta_mod.redraw_asset_images(VIDEO, TENANT, ["asset-B", "asset-C"]),
        )

    result1, result2 = asyncio.run(_run_both())

    for r in (result1, result2):
        assert r["status"] == "completed", r

    total_redrawn = result1["redrawn"] + result2["redrawn"]
    assert total_redrawn == 3, (
        f"expected exactly 3 pictures redrawn total across both runs (A, B, C once each), "
        f"got {total_redrawn} — asset-B was redrawn more than once")

    assert len(image_updates) == 3, image_updates
    assert sorted(image_updates) == ["asset-A", "asset-B", "asset-C"], (
        "each asset must get exactly one image_url write — a duplicate entry "
        "here would mean B was clobbered by a second concurrent write"
    )
    assert len(ledger_calls) == 3, "exactly 3 paid ledger entries — a double-redraw would over-charge"

    b_prompt_calls = [c for c in gen_calls if "asset-B" in c]
    assert len(b_prompt_calls) == 1, (
        f"asset-B's generator was called {len(b_prompt_calls)} times — must be exactly 1")

    assert (
        result1.get("in_progress_elsewhere", 0) + result2.get("in_progress_elsewhere", 0)
    ) >= 1, "one run should report skipping the asset the other already claimed"

    assert redraw_asset_claims.claimed_ids(TENANT, VIDEO) == set(), (
        "every claim must be released once both runs finish")


def test_overlapping_manual_runs_disjoint_sets_both_complete_fully(monkeypatch):
    """Two manual runs with NO overlap must both fully succeed — the claim
    guard must never block a genuinely disjoint concurrent run."""
    rows = {
        "asset-A": _asset_row("asset-A", scene=1, image_index=1),
        "asset-B": _asset_row("asset-B", scene=2, image_index=1),
    }
    _install_common_mocks(monkeypatch, rows)

    async def _run_both():
        return await asyncio.gather(
            cta_mod.redraw_asset_images(VIDEO, TENANT, ["asset-A"]),
            cta_mod.redraw_asset_images(VIDEO, TENANT, ["asset-B"]),
        )

    result1, result2 = asyncio.run(_run_both())
    assert result1["status"] == "completed" and result2["status"] == "completed"
    assert result1.get("in_progress_elsewhere", 0) == 0
    assert result2.get("in_progress_elsewhere", 0) == 0


# --- (d) an id already claimed elsewhere is skipped, not re-redrawn ---------

def test_asset_already_claimed_elsewhere_is_skipped(monkeypatch):
    rows = {"asset-1": _asset_row("asset-1", scene=1, image_index=1)}
    ledger_calls, image_updates, gen_calls = _install_common_mocks(monkeypatch, rows)

    # Simulate another in-flight run already holding this claim.
    won = redraw_asset_claims.claim(TENANT, VIDEO, ["asset-1"])
    assert won == ["asset-1"]
    try:
        result = asyncio.run(cta_mod.redraw_asset_images(VIDEO, TENANT, ["asset-1"]))
        assert result["status"] == "completed"
        assert result["redrawn"] == 0
        assert result["in_progress_elsewhere"] == 1
        assert image_updates == [], "the already-claimed asset must not be redrawn a second time"
        assert ledger_calls == [], "no spend for a skipped already-in-flight redraw"
    finally:
        redraw_asset_claims.release(TENANT, VIDEO, won)


# --- (e) ids that don't exist under this (video, tenant) fail cleanly ------

def test_single_unknown_asset_id_fails_with_specific_message(monkeypatch):
    _install_common_mocks(monkeypatch, {})
    result = asyncio.run(cta_mod.redraw_asset_images(VIDEO, TENANT, ["ghost"]))
    assert result["status"] == "failed"
    assert result["error"] == "picture not found"
    assert redraw_asset_claims.claimed_ids(TENANT, VIDEO) == set(), "no claim should ever be taken"


def test_multi_unknown_asset_ids_fail_with_generic_message(monkeypatch):
    _install_common_mocks(monkeypatch, {})
    result = asyncio.run(cta_mod.redraw_asset_images(VIDEO, TENANT, ["ghost-1", "ghost-2"]))
    assert result["status"] == "failed"
    assert result["error"] == "no matching pictures found for the requested ids"


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-q"]))
