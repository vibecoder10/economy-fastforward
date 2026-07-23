"""C1 (feat/per-card-parallel-clips, backend enabler):
pipeline_executor.run_clip_generation's multi-asset manual run.

Companion to tests/functional/queue_recovery/test_per_card_parallel_clips_lane.py
(the ROUTE-level "clip_manual" lane doesn't 409 itself); this file proves
the ASSET-level guard inside the executor itself — the actual money-safety
mechanism, since the route's lane relaxation alone would let two
overlapping manual runs both animate the same asset (double spend, and a
clobbered video_clip_url write) without it.

Same harness/mocking technique as tests/functional/test_c13_clip_model_routing.py
(`PipelineExecutor.__new__` skips `__init__`; `pipeline_executor`'s bound
`fetch_one`/`fetch_all`/`execute`/`record_ledger_entry` names monkeypatched;
`storage.upload_bytes` and `clip_dialogue.duck_audio` monkeypatched on their
own modules; a fake image client captures each generate_video call) — no
live DB, no real spend.

Covers the required proofs:
  (a) a request with 2+ asset_ids animates ALL of them.
  (c) an asset that already has video_clip_url only re-runs with force=True.
  (b) two overlapping manual runs (simulated via asyncio.gather, same
      video) never animate the same asset twice, even when their requested
      sets overlap — clip_asset_claims is what makes this deterministic
      regardless of asyncio scheduling order.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_per_card_parallel_clips_executor.py -q
"""
import asyncio
import os
import sys

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))

import pipeline_executor as pe_mod  # noqa: E402
from pipeline_executor import PipelineExecutor  # noqa: E402
import storage as storage_mod  # noqa: E402
import clip_dialogue as clip_dialogue_mod  # noqa: E402
import clip_asset_claims  # noqa: E402

TENANT = "tenant-c1"
VIDEO = "video-c1"


class _FakeLightPipeline:
    def __init__(self, image_client):
        self.image_client = image_client
        self.should_cancel = None


class _FakeImageClient:
    VEO_MODEL_QUALITY = "veo-quality-id"
    VEO_MODEL_FAST = "veo-fast-id"

    def __init__(self, delay: float = 0.0):
        self.calls = []
        self._delay = delay

    async def generate_video(self, img, prompt, duration=6, extra_image_urls=None,
                              aspect_ratio="16:9", resolution="720p", task_id_out=None):
        if self._delay:
            await asyncio.sleep(self._delay)
        self.calls.append(("grok", img))
        if task_id_out is not None:
            task_id_out.append("grok-task")
        return f"https://fake/clip-for-{img}.mp4"

    async def generate_video_seedance(self, *a, **k):
        raise AssertionError("seedance should not be called in these tests")

    async def generate_video_veo(self, *a, **k):
        raise AssertionError("veo should not be called in these tests")

    async def download_image(self, url):
        return b"fake-clip-bytes"


def _asset_row(asset_id, scene, image_index, *, video_clip_url=None):
    return {
        "id": asset_id, "scene": scene, "image_index": image_index,
        "image_url": f"https://fake/img-{asset_id}.png", "drive_image_url": None,
        "video_prompt": f"Wide shot on {asset_id}.",
        "video_clip_url": video_clip_url, "duration_seconds": 4.0,
        "sentence_text": None, "image_prompt": "a factory floor",
        "assigned_dialogue": None, "routed_model": None, "model_override": None,
    }


def _video_row():
    return {
        "id": VIDEO, "video_model": "grok-imagine", "aspect_ratio": "16:9",
        "video_resolution": "720p", "dialogue_mode": None,
        "dialogue_audio": "voice_over", "character_reference_url": None,
        "image_style_override": None, "status": "ready_for_video_generation",
    }


def _install_common_mocks(monkeypatch, rows_by_id, *, execute_delay: float = 0.0,
                           image_client=None):
    """Wires the standard DB/storage/ledger fakes. `rows_by_id` is the full
    fixture set; fake_fetch_all filters it by whatever id list the query
    actually asks for (via `id = ANY($3::uuid[])`), so each concurrent call
    only ever sees the rows IT requested — exactly like the real query
    would once Postgres applies the WHERE clause."""
    ledger_calls = []
    clip_url_updates = []  # list of asset ids that got a video_clip_url write

    async def fake_fetch_one(query, *args):
        if "FROM videos WHERE id" in query:
            return _video_row()
        if "SELECT scene FROM assets WHERE id" in query:
            aid = args[-1]
            row = rows_by_id.get(aid)
            return {"scene": row["scene"]} if row else None
        if "COUNT(*) AS pics, COUNT(video_clip_url) AS clips" in query:
            return {"pics": len(rows_by_id), "clips": 0}
        return None

    async def fake_fetch_all(query, *args):
        if "FROM assets WHERE" in query and "routed_model" in query:
            if "id = ANY" in query:
                ids = args[-1]
                return [rows_by_id[i] for i in ids if i in rows_by_id]
            return list(rows_by_id.values())
        if "dialogue_segments FROM scripts" in query:
            return []
        if "SELECT DISTINCT scene FROM assets WHERE id = ANY" in query:
            ids = args[-1]
            scenes = sorted({rows_by_id[i]["scene"] for i in ids if i in rows_by_id})
            return [{"scene": s} for s in scenes]
        return []

    async def fake_execute(query, *args):
        if "UPDATE assets SET video_clip_url" in query:
            if execute_delay:
                await asyncio.sleep(execute_delay)
            clip_url_updates.append(args[-1])  # the asset id (last param)
        return "OK"

    async def fake_record_ledger_entry(**kwargs):
        ledger_calls.append(kwargs)

    async def fake_upload_bytes(data, path, content_type, tenant_id=None):
        return f"https://fake-storage.example/{path}"

    async def fake_duck_audio(clip_bytes, gain=0.3):
        return clip_bytes

    monkeypatch.setattr(pe_mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pe_mod, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(pe_mod, "execute", fake_execute)
    monkeypatch.setattr(pe_mod, "record_ledger_entry", fake_record_ledger_entry)
    monkeypatch.setattr(storage_mod, "upload_bytes", fake_upload_bytes)
    monkeypatch.setattr(clip_dialogue_mod, "duck_audio", fake_duck_audio)
    monkeypatch.setattr(clip_dialogue_mod, "fetch_all", fake_fetch_all)

    client = image_client or _FakeImageClient()
    executor = PipelineExecutor.__new__(PipelineExecutor)
    executor.tenant_id = TENANT
    executor._initialized = True
    executor._pipeline = _FakeLightPipeline(client)
    return executor, client, ledger_calls, clip_url_updates


@pytest.fixture(autouse=True)
def _reset_claims():
    """clip_asset_claims is a module-level dict — clear this test's key
    before AND after so a failed/aborted test can never leak a stale claim
    into the next one (belt-and-suspenders on top of each test's own
    unique video_id where used)."""
    yield
    clip_asset_claims._claimed.pop((TENANT, VIDEO), None)


# --- (a) a request with 2+ asset_ids animates ALL of them -------------------

def test_multi_asset_ids_animates_every_requested_asset(monkeypatch):
    rows = {
        "asset-A": _asset_row("asset-A", scene=1, image_index=1),
        "asset-B": _asset_row("asset-B", scene=1, image_index=2),
        "asset-C": _asset_row("asset-C", scene=2, image_index=1),
    }
    executor, client, ledger_calls, clip_url_updates = _install_common_mocks(monkeypatch, rows)

    result = asyncio.run(executor.run_clip_generation(
        VIDEO, asset_ids=["asset-A", "asset-B", "asset-C"]))

    assert result["status"] == "completed", result
    assert result["clips_generated"] == 3
    assert {c[1] for c in client.calls} == {
        "https://fake/img-asset-A.png", "https://fake/img-asset-B.png", "https://fake/img-asset-C.png",
    }, "every requested asset must have been animated exactly once"
    assert sorted(clip_url_updates) == ["asset-A", "asset-B", "asset-C"]
    assert len(ledger_calls) == 3, "one ledger row per animated clip"
    # Claims must be fully released once the run completes.
    assert clip_asset_claims.claimed_ids(TENANT, VIDEO) == set()


def test_single_asset_id_backward_compatible_path_unchanged(monkeypatch):
    """The pre-existing single-card tap keeps using the singular asset_id
    kwarg end to end — proves C1 didn't disturb that path."""
    rows = {"asset-1": _asset_row("asset-1", scene=1, image_index=1)}
    executor, client, ledger_calls, clip_url_updates = _install_common_mocks(monkeypatch, rows)

    result = asyncio.run(executor.run_clip_generation(VIDEO, asset_id="asset-1"))

    assert result["status"] == "completed", result
    assert result["clips_generated"] == 1
    assert clip_url_updates == ["asset-1"]


# --- (c) force=True required to re-run an asset that already has a clip ----

def test_asset_with_existing_clip_is_skipped_without_force(monkeypatch):
    rows = {
        "asset-A": _asset_row("asset-A", scene=1, image_index=1),
        "asset-B": _asset_row("asset-B", scene=1, image_index=2,
                               video_clip_url="https://fake/already-clipped.mp4"),
    }
    executor, client, ledger_calls, clip_url_updates = _install_common_mocks(monkeypatch, rows)

    result = asyncio.run(executor.run_clip_generation(VIDEO, asset_ids=["asset-A", "asset-B"]))

    assert result["status"] == "completed", result
    assert result["clips_generated"] == 1, "only the not-yet-clipped asset should animate"
    assert clip_url_updates == ["asset-A"]
    assert len(client.calls) == 1
    assert len(ledger_calls) == 1, "no ledger entry (no spend) for the skipped already-clipped asset"


def test_asset_with_existing_clip_reruns_with_force_true(monkeypatch):
    rows = {
        "asset-A": _asset_row("asset-A", scene=1, image_index=1),
        "asset-B": _asset_row("asset-B", scene=1, image_index=2,
                               video_clip_url="https://fake/already-clipped.mp4"),
    }
    executor, client, ledger_calls, clip_url_updates = _install_common_mocks(monkeypatch, rows)

    result = asyncio.run(executor.run_clip_generation(
        VIDEO, asset_ids=["asset-A", "asset-B"], force=True))

    assert result["status"] == "completed", result
    assert result["clips_generated"] == 2, "force=True must re-animate the already-clipped asset too"
    assert sorted(clip_url_updates) == ["asset-A", "asset-B"]
    assert len(ledger_calls) == 2


# --- (b) two overlapping manual runs never animate the same asset twice ----

def test_overlapping_manual_runs_never_double_animate_the_shared_asset(monkeypatch):
    """The crux test. Two manual runs on the SAME video, with OVERLAPPING
    asset sets ({A, B} and {B, C}), fired concurrently (asyncio.gather —
    the same event loop a real overlapping pair of HTTP requests would
    share). Asset B must be animated by EXACTLY ONE of the two runs, never
    both, regardless of which run's coroutine happens to reach the claim
    point first."""
    rows = {
        "asset-A": _asset_row("asset-A", scene=1, image_index=1),
        "asset-B": _asset_row("asset-B", scene=1, image_index=2),
        "asset-C": _asset_row("asset-C", scene=2, image_index=1),
    }
    # A small delay on the DB write widens the window where a broken
    # (unguarded) implementation could interleave and double-process B —
    # makes this test a real proof, not one that only passes by accident
    # of both calls finishing before either yields.
    client = _FakeImageClient(delay=0.01)
    executor, _client, ledger_calls, clip_url_updates = _install_common_mocks(
        monkeypatch, rows, execute_delay=0.01, image_client=client)

    async def _run_both():
        return await asyncio.gather(
            executor.run_clip_generation(VIDEO, asset_ids=["asset-A", "asset-B"]),
            executor.run_clip_generation(VIDEO, asset_ids=["asset-B", "asset-C"]),
        )

    result1, result2 = asyncio.run(_run_both())

    for r in (result1, result2):
        assert r["status"] == "completed", r

    # Total clips generated across BOTH runs must be exactly 3 (A, B, C) —
    # not 4, which is what a double-animated B would produce.
    total_generated = result1["clips_generated"] + result2["clips_generated"]
    assert total_generated == 3, (
        f"expected exactly 3 clips total across both runs (A, B, C once each), "
        f"got {total_generated} — asset-B was animated more than once")

    assert len(clip_url_updates) == 3, clip_url_updates
    assert sorted(clip_url_updates) == ["asset-A", "asset-B", "asset-C"], (
        "each asset must get exactly one video_clip_url write — a duplicate "
        "entry here would mean B was clobbered by a second concurrent write"
    )
    assert len(ledger_calls) == 3, "exactly 3 paid ledger entries — a double-animate would over-charge"

    # B must appear in exactly one of the two runs' own results, not both.
    b_url = "https://fake/img-asset-B.png"
    calls_with_b = [c for c in client.calls if c[1] == b_url]
    assert len(calls_with_b) == 1, (
        f"asset-B's animator was called {len(calls_with_b)} times — must be exactly 1")

    # One run's "already_in_flight" skip message should show up for B —
    # confirms the SKIP path (not a lucky race) is what produced this.
    assert (
        result1.get("clips_in_progress_elsewhere", 0) + result2.get("clips_in_progress_elsewhere", 0)
    ) >= 1, "one run should report skipping the asset the other already claimed"

    assert clip_asset_claims.claimed_ids(TENANT, VIDEO) == set(), (
        "every claim must be released once both runs finish")


def test_overlapping_manual_runs_disjoint_sets_both_complete_fully(monkeypatch):
    """Two manual runs with NO overlap must both fully succeed — the claim
    guard must never block a genuinely disjoint concurrent run."""
    rows = {
        "asset-A": _asset_row("asset-A", scene=1, image_index=1),
        "asset-B": _asset_row("asset-B", scene=2, image_index=1),
    }
    executor, client, ledger_calls, clip_url_updates = _install_common_mocks(monkeypatch, rows)

    async def _run_both():
        return await asyncio.gather(
            executor.run_clip_generation(VIDEO, asset_id="asset-A"),
            executor.run_clip_generation(VIDEO, asset_id="asset-B"),
        )

    result1, result2 = asyncio.run(_run_both())
    assert result1["clips_generated"] == 1
    assert result2["clips_generated"] == 1
    assert sorted(clip_url_updates) == ["asset-A", "asset-B"]
    assert result1.get("clips_in_progress_elsewhere", 0) == 0
    assert result2.get("clips_in_progress_elsewhere", 0) == 0


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-q"]))
