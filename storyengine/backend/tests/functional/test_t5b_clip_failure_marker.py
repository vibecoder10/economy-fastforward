"""T5b (TIMELINE-WORKBENCH-PLAN.md): persist a real clip-failure marker.

T1's recon (see canvas-shared/timeline-slots.ts's file header) proved the
live clip-generation failure path never wrote anything back to the `assets`
row — `_safe_one`'s except branch in pipeline_executor.py only incremented an
in-memory counter and logged an activity-feed line, so a failed clip attempt
was indistinguishable from "never attempted" the instant the request
returned. This is the fix: the except branch now writes
`assets.video_status = 'failed'`, and the success path clears it (`video_status
= NULL`) in the same statement that writes `video_clip_url`, mirroring the
existing redraw-clears-stale-clip pattern in coverage_to_app.py.

Column choice, verified before writing this test (not guessed):
  - `assets.status` means "picture done" (set by coverage_to_app.py's
    store_scene INSERT) — overwriting it here would destroy that meaning.
  - `assets.video_status` is a real Postgres column (migrations/
    000_baseline_schema.sql), already the dedicated clip-status field: the
    ONLY other live write to it is coverage_to_app.py's redraw path, which
    clears it to NULL when a stale clip is invalidated — this is the exact
    same column, used consistently.
  - Every retry-candidate query in run_clip_generation (`candidates = [...]`)
    filters only on `image_url`/`drive_image_url` present and
    `video_clip_url` absent — never `video_status` — so a failed row is
    still picked up and retried next run, unchanged from before this fix.

Same harness/mocking technique as test_per_card_parallel_clips_executor.py
(`PipelineExecutor.__new__` skips `__init__`; `pipeline_executor`'s bound
`fetch_one`/`fetch_all`/`execute`/`record_ledger_entry` names monkeypatched;
`storage.upload_bytes` and `clip_dialogue.duck_audio` monkeypatched on their
own modules; a fake image client captures each generate_video call) — no
live DB, no real spend, no live provider call.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_t5b_clip_failure_marker.py -q
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

TENANT = "tenant-t5b"
VIDEO = "video-t5b"


class _FakeLightPipeline:
    def __init__(self, image_client):
        self.image_client = image_client
        self.should_cancel = None


class _FakeImageClientPartialFailure:
    """generate_video raises for any image URL in `fail_for`, succeeds for
    everything else — lets one test drive both branches of _safe_one at once."""
    VEO_MODEL_QUALITY = "veo-quality-id"
    VEO_MODEL_FAST = "veo-fast-id"

    def __init__(self, fail_for):
        self.fail_for = set(fail_for)
        self.calls = []

    async def generate_video(self, img, prompt, duration=6, extra_image_urls=None,
                              aspect_ratio="16:9", resolution="720p", task_id_out=None):
        self.calls.append(("grok", img))
        if img in self.fail_for:
            raise RuntimeError("simulated provider timeout")
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


def _install_common_mocks(monkeypatch, rows_by_id, image_client):
    """Wires the standard DB/storage/ledger fakes and records EVERY `UPDATE
    assets SET ...` call verbatim (query text + args) so tests can assert
    exactly which column got written for which asset id — not just that
    *some* write happened."""
    ledger_calls = []
    asset_updates = []  # list of (query, args) tuples, every UPDATE assets call

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
        if "UPDATE assets SET" in query:
            asset_updates.append((query, args))
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

    executor = PipelineExecutor.__new__(PipelineExecutor)
    executor.tenant_id = TENANT
    executor._initialized = True
    executor._pipeline = _FakeLightPipeline(image_client)
    return executor, ledger_calls, asset_updates


@pytest.fixture(autouse=True)
def _reset_claims():
    yield
    clip_asset_claims._claimed.pop((TENANT, VIDEO), None)


def test_failed_clip_persists_video_status_failed_marker(monkeypatch):
    """The crux proof: a clip generation call that raises must leave
    assets.video_status = 'failed' on that row — not silently vanish into an
    in-memory counter, which is exactly what T1 found broken."""
    rows = {
        "asset-fail": _asset_row("asset-fail", scene=1, image_index=1),
    }
    client = _FakeImageClientPartialFailure(fail_for={"https://fake/img-asset-fail.png"})
    executor, ledger_calls, asset_updates = _install_common_mocks(monkeypatch, rows, client)

    result = asyncio.run(executor.run_clip_generation(VIDEO, asset_id="asset-fail"))

    # A batch where every requested asset failed reports status="failed"
    # (distinct from a partial-success mixed batch — see the mixed-batch
    # test below, which stays "completed"). This test's proof is the
    # PERSISTED MARKER, not this top-level status string.
    assert result["status"] == "failed", result
    assert result["clips_generated"] == 0

    marker_writes = [
        (q, a) for (q, a) in asset_updates
        if "video_status" in q and "video_clip_url" not in q
    ]
    assert len(marker_writes) == 1, (
        f"expected exactly one dedicated video_status marker write, got "
        f"{len(marker_writes)}: {asset_updates}"
    )
    query, args = marker_writes[0]
    assert "UPDATE assets SET video_status" in query
    assert "failed" in args
    assert "asset-fail" in args, "the marker write must target the failed row's id"

    # No clip was ever produced, so no ledger spend for the failed row.
    assert len(ledger_calls) == 0

    # The claim must still be released even though the row failed.
    assert clip_asset_claims.claimed_ids(TENANT, VIDEO) == set()


def test_success_clears_any_stale_failure_marker_in_the_same_statement(monkeypatch):
    """A row that failed on a previous run (video_status='failed' already
    set) and now succeeds on retry must have that stale marker cleared —
    proven by asserting the SUCCESS write's own SQL sets video_status = NULL
    alongside video_clip_url, not a separate never-fired cleanup step."""
    rows = {
        "asset-ok": _asset_row("asset-ok", scene=1, image_index=1),
    }
    client = _FakeImageClientPartialFailure(fail_for=set())
    executor, ledger_calls, asset_updates = _install_common_mocks(monkeypatch, rows, client)

    result = asyncio.run(executor.run_clip_generation(VIDEO, asset_id="asset-ok"))

    assert result["status"] == "completed", result
    assert result["clips_generated"] == 1

    clip_writes = [
        (q, a) for (q, a) in asset_updates
        if "video_clip_url" in q
    ]
    assert len(clip_writes) == 1
    query, _args = clip_writes[0]
    assert "video_status = NULL" in query, (
        "the success write must clear any stale failure marker in the same "
        f"statement it writes video_clip_url — got: {query}"
    )
    assert len(ledger_calls) == 1


def test_mixed_batch_one_fails_one_succeeds_each_gets_its_own_correct_marker(monkeypatch):
    """Two assets in one batch, one fails and one succeeds — proves the
    failure marker is scoped to the actual failed row, never applied to (or
    withheld from) its sibling."""
    rows = {
        "asset-A": _asset_row("asset-A", scene=1, image_index=1),
        "asset-B": _asset_row("asset-B", scene=1, image_index=2),
    }
    client = _FakeImageClientPartialFailure(fail_for={"https://fake/img-asset-B.png"})
    executor, ledger_calls, asset_updates = _install_common_mocks(monkeypatch, rows, client)

    result = asyncio.run(executor.run_clip_generation(VIDEO, asset_ids=["asset-A", "asset-B"]))

    assert result["status"] == "completed", result
    assert result["clips_generated"] == 1
    assert result["generated_asset_ids"] == ["asset-A"]

    marker_writes = [
        (q, a) for (q, a) in asset_updates
        if "video_status" in q and "video_clip_url" not in q
    ]
    assert len(marker_writes) == 1
    _q, args = marker_writes[0]
    assert "asset-B" in args
    assert "asset-A" not in args

    clip_writes = [(q, a) for (q, a) in asset_updates if "video_clip_url" in q]
    assert len(clip_writes) == 1
    _q2, args2 = clip_writes[0]
    assert "asset-A" in args2


# --- the marker only matters if the API actually serves it -----------------

def test_video_status_round_trips_through_the_real_assets_route(monkeypatch):
    """The write alone is not the whole fix — T5b's own stated purpose is
    "so the timeline can show failed honestly", and the timeline only ever
    sees what GET /api/videos/{id}/assets returns. Proves the SAME SELECT
    T2b touched (routes/videos.py's get_video_assets) also names
    `video_status`, and that a real 'failed' value on the row survives to
    the JSON-serializable response — the exact shape
    canvas-shared/timeline-slots.ts's `deriveState` already reads
    defensively. No live DB — routes.videos.fetch_all monkeypatched."""
    import routes.videos as videos_mod

    async def fake_fetch_all(query, *args):
        assert "video_status" in query, (
            "get_video_assets must SELECT video_status for T5b's marker to "
            f"ever reach the frontend — got: {query}"
        )
        return [{
            "id": "asset-failed", "video_id": "video-x", "scene": 1, "image_index": 100,
            "image_url": "https://fake/img.png", "drive_image_url": None,
            "image_prompt": "x", "status": "done", "shot_type": "WIDE",
            "hero_shot": False, "sentence_text": None, "video_clip_url": None,
            "video_prompt": "x", "sound_prompt": None, "sound_effect_url": None,
            "sound_volume": None, "duration_seconds": None, "extraction_flags": None,
            "image_model": None, "routed_model": None, "routing_reason": None,
            "model_used": None, "model_override": None, "camera_movement": None,
            "camera_preset_id": None, "carries_own_line": False,
            "clip_speech_start": None, "clip_speech_end": None,
            "assigned_dialogue": None, "generation_method": None, "caption": None,
            "video_duration": None, "assigned_video_duration": None,
            "video_status": "failed",
            "created_at": "2026-07-28T00:00:00",
        }]

    monkeypatch.setattr(videos_mod, "fetch_all", fake_fetch_all)
    rows = asyncio.run(videos_mod.get_video_assets("video-x", tenant_id="tenant-x"))
    assert rows[0]["video_status"] == "failed"


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-q"]))
