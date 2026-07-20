"""Tests for C25a-fix7 (2026-07-20): Seedance clip dispatch was broken —
Kie's createTask rejected 3/3 attempts on video cd5d2883-427e-4bfb-854d-8849d025d444
(tenant ee93e6d1, PROD 2026-07-20 16:46) with "The reference image and the
first and last frames are mutually exclusive, and only one scene can be
selected" because `ImageClient.generate_video_seedance` sent BOTH
`first_frame_url` AND `reference_image_urls` in the same createTask call.

Kie's docs (docs.kie.ai/market/bytedance/seedance-2-fast) confirm the three
input modes are mutually exclusive on a single call: "Image-to-Video (First
Frame), Image-to-Video (First & Last Frames), and Multimodal Reference-to-
Video are three mutually exclusive scenarios and cannot be used
simultaneously." Animating one storyboard panel needs the clip's start frame
to be EXACTLY that panel (pipeline_executor's `_decorate` prompt contract:
"Animate @image1 exactly as shown"), so First-Frame mode is the only one of
the three that guarantees literal frame fidelity — the fix drops
`reference_image_urls` from the payload entirely rather than swapping which
image goes where.

1. Direct `ImageClient.generate_video_seedance` payload-shape tests (no live
   network — httpx.AsyncClient monkeypatched, same pattern as
   test_c25a_fix4_kie_null_data_parsing.py): the JSON body sent to Kie must
   carry `first_frame_url` and must NOT carry `reference_image_urls` /
   `last_frame_url`, and `aspect_ratio` must equal whatever the caller passed
   in (not a hardcoded default) — regardless of how many cast-sheet refs the
   caller offered.
2. A `pipeline_executor.run_clip_generation` -> Seedance dispatch test (same
   monkeypatch pattern as test_c13_clip_model_routing.py): a video whose
   `aspect_ratio` is "9:16" must reach Kie as "9:16", and a video whose
   `aspect_ratio` is "16:9" must reach Kie as "16:9" — the two-value diff
   proves the aspect is genuinely THREADED from `videos.aspect_ratio`, not
   hardcoded to either value (the prod incident's OTHER symptom: a 16:9 video
   dispatched as "9:16").

These are git-stash-sensitive: `git stash` the image_client.py fix and test 1
below fails (`reference_image_urls` present) while test 2's Kie-payload
assertion still passes (aspect threading was already correct before this
chunk — see decisions.md; this suite pins BOTH facts down so a future
regression on either one is caught).

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c25a_fix7_seedance_payload.py -q
"""
import asyncio
import os
import sys
import types
from pathlib import Path

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PIPELINE_ROOT = _REPO_ROOT / "skills" / "video-pipeline"
if str(_PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_ROOT))


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


async def _boom(*a, **k):
    raise AssertionError("pure tests must not touch runtime services")


_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom)
os.environ.setdefault("KIE_AI_API_KEY", "fake-key-for-tests")

from shared.clients.image_client import ImageClient  # noqa: E402


# ---------------------------------------------------------------------------
# Part 1: ImageClient.generate_video_seedance payload shape (no live network).
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code
        self.text = str(body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _CapturingAsyncClient:
    """Drop-in for `async with httpx.AsyncClient() as client:` that records
    every POST body (the createTask payload) and answers with a canned,
    always-successful taskId so the call under test never has to poll."""

    def __init__(self, captured):
        self._captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, **kwargs):
        self._captured.append(json)
        return _FakeResponse({"code": 200, "data": {"taskId": "fake-task-1"}})

    async def get(self, url, **kwargs):  # pragma: no cover - poll not reached
        raise AssertionError("payload-shape tests must not reach the poll step")


def _seedance_payload(monkeypatch, *, aspect_ratio, extra_image_urls):
    """Fires one generate_video_seedance call and returns the exact JSON
    body that would have been POSTed to Kie's createTask, without waiting
    for the (never-reached) poll step."""
    import shared.clients.image_client as image_client_mod

    captured = []
    monkeypatch.setattr(image_client_mod.httpx, "AsyncClient",
                         lambda *a, **k: _CapturingAsyncClient(captured))

    ic = ImageClient(api_key="fake-key")

    async def _run():
        task_id_box = []
        # Race the real call against a task_id_out probe: as soon as the
        # taskId is captured (right after createTask), the payload we need
        # already sits in `captured[0]` — cancel before the (asserting) poll.
        gen = asyncio.ensure_future(
            ic.generate_video_seedance(
                "https://fake/panel.png", "a wide establishing shot",
                duration=6, extra_image_urls=extra_image_urls,
                aspect_ratio=aspect_ratio, task_id_out=task_id_box))
        while not captured:
            await asyncio.sleep(0)
        gen.cancel()
        try:
            await gen
        except asyncio.CancelledError:
            pass

    asyncio.run(_run())
    assert captured, "createTask was never POSTed"
    return captured[0]


def test_seedance_payload_omits_mutually_exclusive_fields_when_refs_given(monkeypatch):
    """The exact prod failure shape: a cast-sheet ref alongside the panel.
    reference_image_urls (and last_frame_url) must be ABSENT — Kie rejects
    first_frame_url + reference_image_urls together."""
    payload = _seedance_payload(
        monkeypatch, aspect_ratio="16:9",
        extra_image_urls=["https://fake/cast-sheet.png"])

    body = payload["input"]
    assert body["first_frame_url"] == "https://fake/panel.png"
    assert "reference_image_urls" not in body, (
        "reference_image_urls must never be sent alongside first_frame_url "
        "— this exact combo is what Kie rejected in prod")
    assert "last_frame_url" not in body


def test_seedance_payload_omits_reference_image_urls_when_no_refs_given(monkeypatch):
    """No cast sheet offered at all — still must never carry the key."""
    payload = _seedance_payload(monkeypatch, aspect_ratio="16:9", extra_image_urls=None)
    assert "reference_image_urls" not in payload["input"]


def test_seedance_payload_aspect_ratio_is_16_9_when_16_9_passed_in(monkeypatch):
    payload = _seedance_payload(
        monkeypatch, aspect_ratio="16:9", extra_image_urls=["https://fake/cast.png"])
    assert payload["input"]["aspect_ratio"] == "16:9"


def test_seedance_payload_aspect_ratio_is_9_16_when_9_16_passed_in(monkeypatch):
    """The two-value diff against the test above proves aspect_ratio is
    threaded straight through from the caller, not hardcoded to either
    value — a hardcoded "9:16" (the prod symptom on a 16:9 video) or a
    hardcoded "16:9" would both fail one of these two tests."""
    payload = _seedance_payload(
        monkeypatch, aspect_ratio="9:16", extra_image_urls=["https://fake/cast.png"])
    assert payload["input"]["aspect_ratio"] == "9:16"


# ---------------------------------------------------------------------------
# Part 2: pipeline_executor.run_clip_generation -> Seedance dispatch threads
# the VIDEO's own aspect_ratio (same monkeypatch pattern as
# test_c13_clip_model_routing.py's _run_clip_generation_for).
# ---------------------------------------------------------------------------

import pipeline_executor as pe_mod  # noqa: E402
from pipeline_executor import PipelineExecutor  # noqa: E402
import storage as storage_mod  # noqa: E402
import clip_dialogue as clip_dialogue_mod  # noqa: E402

TENANT = "tenant-1"
VIDEO = "video-1"


class _FakeLightPipeline:
    def __init__(self, image_client):
        self.image_client = image_client
        self.should_cancel = None


class _SeedanceCapturingImageClient:
    VEO_MODEL_QUALITY = "veo-quality-id"
    VEO_MODEL_FAST = "veo-fast-id"

    def __init__(self):
        self.seedance_calls = []

    async def generate_video_seedance(self, img, prompt, duration=6, extra_image_urls=None,
                                       aspect_ratio="16:9", task_id_out=None):
        self.seedance_calls.append(aspect_ratio)
        if task_id_out is not None:
            task_id_out.append("seedance-task-1")
        return "https://fake/seedance-clip.mp4"

    async def generate_video(self, *a, **k):
        raise AssertionError("this test routes to seedance, not grok")

    async def download_image(self, url):
        return b"fake-clip-bytes"


def _video_row(aspect_ratio):
    return {
        "id": VIDEO, "video_model": "seedance-2-fast", "aspect_ratio": aspect_ratio,
        "video_resolution": "720p", "dialogue_mode": None,
        "dialogue_audio": "voice_over", "character_reference_url": None,
        "image_style_override": None, "status": "ready_for_video_generation",
    }


def _asset_row():
    return {
        "id": "asset-1", "scene": 1, "image_index": 1,
        "image_url": "https://fake/img1.png", "drive_image_url": None,
        "video_prompt": "Wide shot pushes in on the machine.",
        "video_clip_url": None, "duration_seconds": 4.0,
        "sentence_text": None, "image_prompt": "a factory floor",
        "assigned_dialogue": None, "routed_model": None, "model_override": None,
    }


def _run_seedance_dispatch_for(monkeypatch, video_aspect_ratio):
    async def fake_fetch_one(query, *args):
        if "FROM videos WHERE id" in query:
            return _video_row(video_aspect_ratio)
        if "SELECT scene FROM assets WHERE id" in query:
            return {"scene": 1}
        if "COUNT(*) AS pics, COUNT(video_clip_url) AS clips" in query:
            return {"pics": 1, "clips": 0}
        return None

    async def fake_fetch_all(query, *args):
        if "FROM assets WHERE" in query and "routed_model" in query:
            return [_asset_row()]
        if "dialogue_segments FROM scripts" in query:
            return []
        return []

    async def fake_execute(query, *args):
        return "OK"

    async def fake_record_ledger_entry(**kwargs):
        pass

    async def fake_upload_bytes(data, path, content_type, tenant_id=None):
        return f"https://fake-storage.example/{path}"

    monkeypatch.setattr(pe_mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pe_mod, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(pe_mod, "execute", fake_execute)
    monkeypatch.setattr(pe_mod, "record_ledger_entry", fake_record_ledger_entry)
    monkeypatch.setattr(storage_mod, "upload_bytes", fake_upload_bytes)
    monkeypatch.setattr(clip_dialogue_mod, "fetch_all", fake_fetch_all)

    image_client = _SeedanceCapturingImageClient()
    executor = PipelineExecutor.__new__(PipelineExecutor)
    executor.tenant_id = TENANT
    executor._initialized = True
    executor._pipeline = _FakeLightPipeline(image_client)

    result = asyncio.run(executor.run_clip_generation(VIDEO, asset_id="asset-1"))
    assert result["status"] == "completed", result
    return image_client


def test_seedance_dispatch_threads_video_aspect_ratio_16_9(monkeypatch):
    client = _run_seedance_dispatch_for(monkeypatch, "16:9")
    assert client.seedance_calls == ["16:9"]


def test_seedance_dispatch_threads_video_aspect_ratio_9_16(monkeypatch):
    """Same dispatch path, a video whose real aspect_ratio is 9:16 — proves
    the earlier 16:9 result wasn't a coincidence of a hardcoded default."""
    client = _run_seedance_dispatch_for(monkeypatch, "9:16")
    assert client.seedance_calls == ["9:16"]
