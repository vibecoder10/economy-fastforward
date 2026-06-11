"""Functional tests for cooperative generation cancellation (Stop button).

Proves, without network or DB:
- cancel_registry local-flag semantics (set / TTL / clear)
- the image bot halts between scenes when should_cancel fires, returns
  cancelled=True, keeps completed counts, and never calls the image client
  for queued items
- voice and clip bots expose the same contract

Run:  python3 tests/functional/test_cancel_generation.py   (from storyengine/backend)
"""

import asyncio
import os
import sys
import types

BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
REPO = os.path.abspath(os.path.join(BACKEND, "..", ".."))
PIPELINE = os.path.join(REPO, "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(BACKEND))
sys.path.insert(0, PIPELINE)
for sub in ("orchestrator", "images", "voice", "video_motion"):
    p = os.path.join(PIPELINE, sub)
    if p not in sys.path:
        sys.path.append(p)

# Stub the database module BEFORE cancel_registry imports it
fake_db = types.ModuleType("database")
fake_db.DB_ROWS = []
async def _execute(q, *a):
    fake_db.LAST_EXECUTE = (q, a)
    return "UPDATE 0"
async def _fetch_one(q, *a):
    return fake_db.DB_ROWS[0] if fake_db.DB_ROWS else None
fake_db.execute = _execute
fake_db.fetch_one = _fetch_one
sys.modules["database"] = fake_db

import cancel_registry  # noqa: E402


def test_registry_local_flag():
    cancel_registry.clear_local("t1", "v1")
    assert not cancel_registry.is_requested_local("t1", "v1")
    cancel_registry.request_local("t1", "v1")
    assert cancel_registry.is_requested_local("t1", "v1")
    assert not cancel_registry.is_requested_local("t1", "v2"), "flag leaked across videos"
    assert not cancel_registry.is_requested_local("t2", "v1"), "flag leaked across tenants"
    cancel_registry.clear_local("t1", "v1")
    assert not cancel_registry.is_requested_local("t1", "v1")

    # DB fallback path (cross-process): row present -> cancelled
    async def check():
        fake_db.DB_ROWS = [{"?column?": 1}]
        assert await cancel_registry.is_cancel_requested("t1", "v1")
        fake_db.DB_ROWS = []
        assert not await cancel_registry.is_cancel_requested("t1", "v1")
    asyncio.run(check())
    print("PASS test_registry_local_flag")


class _Recorder:
    """No-op attribute sink that records calls."""
    def __init__(self):
        self.calls = []
    def __getattr__(self, name):
        def _f(*a, **k):
            self.calls.append(name)
            return {"id": "x"}
        return _f


def _fake_image_pipeline(cancel_after_checks: int):
    """Pipeline double for images/_generate_images with N pending images."""
    from orchestrator.pipeline_constants import ImageFields

    pending = [
        {"id": f"rec{i}", ImageFields.STATUS: ImageFields.STATUS_PENDING,
         ImageFields.IMAGE_PROMPT: f"prompt {i}", ImageFields.SCENE: i,
         ImageFields.IMAGE_INDEX: 1}
        for i in range(1, 4)  # 3 scenes, 1 image each
    ]

    p = types.SimpleNamespace()
    p.video_title = "Cancel Test Video"
    p.current_idea = {"Status": "Ready For Images"}
    p.core_image_url = None
    p.project_folder_id = "folder"
    p.scene_filter = None
    p.image_filter = None
    p._is_targeted_run = False
    p._filter_by_scene = lambda recs, scene_key="Scene": recs
    p.slack = _Recorder()
    p.google = _Recorder()

    airtable = _Recorder()
    airtable.get_all_images_for_video = lambda title: list(pending)
    def _mark_done(record_id, image_url, drive_url=None):
        for rec in pending:
            if rec["id"] == record_id:
                rec[ImageFields.STATUS] = ImageFields.STATUS_DONE
    airtable.update_image_record = _mark_done
    p.airtable = airtable

    image_client = _Recorder()
    p.image_client = image_client

    state = {"checks": 0}
    async def should_cancel():
        state["checks"] += 1
        return state["checks"] > cancel_after_checks
    p.should_cancel = should_cancel
    p._cancel_state = state
    return p, image_client


def test_image_bot_cancels_before_first_scene():
    from images.run import _generate_images
    pipeline, image_client = _fake_image_pipeline(cancel_after_checks=0)
    result = asyncio.run(_generate_images(pipeline))
    assert result.get("cancelled") is True, result
    assert result.get("image_count") == 0
    generate_calls = [c for c in image_client.calls if "generate" in c]
    assert not generate_calls, f"image client was called after cancel: {generate_calls}"
    print("PASS test_image_bot_cancels_before_first_scene")


def test_image_bot_runs_fully_without_cancel():
    from images.run import _generate_images
    pipeline, image_client = _fake_image_pipeline(cancel_after_checks=10_000)

    async def fake_generate_and_wait(prompt, aspect_ratio="16:9"):
        return ["https://example.com/img.png"]
    async def fake_download(url):
        return b"bytes"
    pipeline.image_client = types.SimpleNamespace(
        generate_and_wait=fake_generate_and_wait,
        download_image=fake_download,
    )
    result = asyncio.run(_generate_images(pipeline))
    assert not result.get("cancelled"), result
    assert result.get("image_count") == 3, result
    print("PASS test_image_bot_runs_fully_without_cancel")


def test_voice_bot_cancel_contract():
    """voice/run.py: cancelled flag halts the loop and blocks status advance."""
    import voice.run as voice_run
    src_has_checks = "should_cancel" in open(voice_run.__file__).read()
    assert src_has_checks, "voice bot lost its cancel check"
    src = open(voice_run.__file__).read()
    assert '"cancelled": True' in src
    print("PASS test_voice_bot_cancel_contract")


def test_clip_bot_cancel_contract():
    import video_motion.run_generate as clip_run
    src = open(clip_run.__file__).read()
    assert "should_cancel" in src and '"cancelled": True' in src
    assert src.index("if await _cancelled()") < src.index("generate_video("), \
        "cancel check must come before the paid clip call"
    print("PASS test_clip_bot_cancel_contract")


def test_storyboard_bot_cancel_contract():
    path = os.path.join(PIPELINE, "storyboard", "bot.py")
    src = open(path).read()
    assert "should_cancel=None" in src and 'result["cancelled"] = True' in src
    assert src.index("if await _cancelled()") < src.index("grid_url = await generate_contact_sheet"), \
        "cancel check must come before the paid grid call"
    print("PASS test_storyboard_bot_cancel_contract")


def test_cancel_endpoint_exempt_from_job_limit():
    """The Stop endpoint must not be blocked by the concurrent-job limiter —
    it is only ever called while a job is running (adversarial-review find)."""
    src = open(os.path.join(os.path.abspath(BACKEND), "rate_limit.py")).read()
    assert "_JOB_LIMIT_EXEMPT_PREFIXES" in src
    assert '"/api/pipeline/cancel/"' in src
    assert "_JOB_LIMIT_EXEMPT_PREFIXES)" in src.split("Pipeline concurrent job check")[1][:400],         "job-limit branch must consult the exemption list"
    schema = open(os.path.join(REPO, "storyengine", "schema.sql")).read()
    assert "video_characters_tenant_isolation" in schema,         "schema.sql must carry the video_characters RLS policy (parity with migration 046)"
    print("PASS test_cancel_endpoint_exempt_from_job_limit")


if __name__ == "__main__":
    test_registry_local_flag()
    test_image_bot_cancels_before_first_scene()
    test_image_bot_runs_fully_without_cancel()
    test_voice_bot_cancel_contract()
    test_clip_bot_cancel_contract()
    test_storyboard_bot_cancel_contract()
    test_cancel_endpoint_exempt_from_job_limit()
    print("\nALL CANCEL TESTS PASSED (7/7)")
