"""Tests for the two CLIP/RENDER halves of the fail-closed motion-gate law
(code law, 2026-07-22 — "the prompt is the prompt; we can't be downgrading
prompts under automation"). scripts/coverage_to_app.py's gate/repair fix is
pinned in tests/functional/test_motion_prompt_presence_gate.py; THIS file
pins the two paid-boundary consumers of that block marker:

1. `pipeline_executor.PipelineExecutor.run_clip_generation` — a row with
   NULL/empty video_prompt OR assets.motion_gate_status='blocked' (migration
   118) must be SKIPPED before any Grok call or generation_ledger write, with
   a visible bot_activity row naming the skipped shots. The batch still
   completes every other valid shot (partial progress, never a silent
   full-stop). Same PipelineExecutor.__new__ / monkeypatch-the-module-level-
   names harness as tests/functional/test_c13_clip_model_routing.py.

2. The per-scene auto-stitch preview inside the same method (~L13180-13245):
   on performance-track assembly failure, the default is now to STOP — mark
   the failure visible via bot_activity and never auto-run the plain-stitch
   downgrade — unless SE_ALLOW_FALLBACK_STITCH=1 is explicitly set.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_motion_gate_fail_closed_clip_and_render.py -q
"""
import asyncio
import os
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))

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


class _FakeImageClient:
    VEO_MODEL_QUALITY = "veo-quality-id"
    VEO_MODEL_FAST = "veo-fast-id"

    def __init__(self):
        self.calls = []

    async def generate_video(self, img, prompt, duration=6, extra_image_urls=None,
                              aspect_ratio="16:9", resolution="720p", task_id_out=None):
        self.calls.append(("grok", prompt))
        if task_id_out is not None:
            task_id_out.append("grok-task-1")
        return "https://fake/grok-clip.mp4"

    async def generate_video_seedance(self, *a, **k):
        raise AssertionError("seedance should not be called in these tests")

    async def generate_video_veo(self, *a, **k):
        raise AssertionError("veo should not be called in these tests")

    async def download_image(self, url):
        return b"fake-clip-bytes"


def _video_row(dialogue_mode=None, dialogue_audio="voice_over"):
    return {
        "id": VIDEO, "video_model": "grok-imagine", "aspect_ratio": "16:9",
        "video_resolution": "720p", "dialogue_mode": dialogue_mode,
        "dialogue_audio": dialogue_audio, "character_reference_url": None,
        "image_style_override": None, "status": "ready_for_video_generation",
    }


def _row(id_, scene, image_index, video_prompt, motion_gate_status=None):
    return {
        "id": id_, "scene": scene, "image_index": image_index,
        "image_url": f"https://fake/img-{id_}.png", "drive_image_url": None,
        "video_prompt": video_prompt,
        "video_clip_url": None, "duration_seconds": 4.0,
        "sentence_text": None, "image_prompt": "a factory floor",
        "assigned_dialogue": None, "routed_model": None, "model_override": None,
        "camera_preset_id": None, "generation_method": "coverage",
        "motion_gate_status": motion_gate_status,
    }


def _base_patches(monkeypatch, rows, comp_result=None, dialogue_mode=None,
                   dialogue_audio="voice_over"):
    ledger_calls = []
    activity_inserts = []
    clip_url_updates = []

    async def fake_fetch_one(query, *args):
        if "FROM videos WHERE id" in query:
            return _video_row(dialogue_mode, dialogue_audio)
        if "SELECT scene FROM assets WHERE id" in query:
            return {"scene": rows[0]["scene"]} if rows else None
        if "COUNT(*) AS pics, COUNT(video_clip_url) AS clips" in query:
            return comp_result if comp_result is not None else {"pics": 0, "clips": 0}
        if "COUNT(*) AS n FROM assets" in query:
            return {"n": 0}
        return None

    async def fake_fetch_all(query, *args):
        if "FROM assets WHERE" in query and "motion_gate_status" in query:
            assert "routed_model" in query and "model_override" in query
            return rows
        if "DISTINCT scene FROM assets" in query:
            return [{"scene": r["scene"]} for r in rows]
        if "dialogue_segments FROM scripts" in query:
            return []
        return []

    async def fake_execute(query, *args):
        if "INSERT INTO bot_activity" in query:
            activity_inserts.append(args)
        elif "UPDATE assets SET video_clip_url" in query:
            clip_url_updates.append(args)
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

    return ledger_calls, activity_inserts, clip_url_updates


def _make_executor(image_client):
    executor = PipelineExecutor.__new__(PipelineExecutor)
    executor.tenant_id = TENANT
    executor._initialized = True
    executor._pipeline = _FakeLightPipeline(image_client)
    return executor


# =============================================================================
# 1. run_clip_generation skips blocked/promptless rows, spends on the rest
# =============================================================================

def test_blocked_and_promptless_rows_are_skipped_no_spend_others_proceed(monkeypatch):
    """Three rows in one scene: a clean row, a row with NULL video_prompt
    (never wrote a motion line), and a row explicitly marked
    motion_gate_status='blocked' (even though it still carries stale prompt
    text — the status flag alone must be enough to skip it). Only the clean
    row may animate; zero ledger writes for the other two; the batch still
    completes (partial progress, not a silent full-stop)."""
    rows = [
        _row("asset-ok", 1, 1, "Camera holds steady on the machine, subject motion only."),
        _row("asset-null", 1, 2, None),
        _row("asset-blocked", 1, 3, "stale leftover text", motion_gate_status="blocked"),
    ]
    image_client = _FakeImageClient()
    ledger_calls, activity_inserts, clip_url_updates = _base_patches(monkeypatch, rows)

    executor = _make_executor(image_client)
    result = asyncio.run(executor.run_clip_generation(VIDEO))

    assert result["status"] == "completed", result
    assert result["clips_generated"] == 1
    assert result["clips_blocked"] == 2
    assert len(ledger_calls) == 1, "only the clean row may spend"
    assert len(clip_url_updates) == 1
    assert clip_url_updates[0][-1] == "asset-ok"  # id is the last positional arg
    assert len(image_client.calls) == 1, "Grok must only be called for the clean row"

    warnings = [a for a in activity_inserts if a[3] == "failed"]
    assert warnings, "a visible bot_activity warning must name the blocked shots"
    warning_msg = warnings[0][4]
    assert "S1.2" in warning_msg and "S1.3" in warning_msg
    assert "S1.1" not in warning_msg


def test_all_rows_blocked_completes_with_zero_spend_and_warning(monkeypatch):
    """Every candidate row is blocked/promptless — the call must still return
    'completed' (not hang or error), spend nothing, and log why."""
    rows = [
        _row("asset-null", 2, 1, None),
        _row("asset-blocked", 2, 2, "", motion_gate_status="blocked"),
    ]
    image_client = _FakeImageClient()
    ledger_calls, activity_inserts, clip_url_updates = _base_patches(monkeypatch, rows)

    executor = _make_executor(image_client)
    result = asyncio.run(executor.run_clip_generation(VIDEO))

    assert result["status"] == "completed", result
    assert result["clips_generated"] == 0
    assert result["clips_blocked"] == 2
    assert not ledger_calls
    assert not clip_url_updates
    assert not image_client.calls
    assert any(a[3] == "failed" for a in activity_inserts)


def test_asset_query_selects_motion_gate_status(monkeypatch):
    """The per-row SELECT must actually fetch motion_gate_status, or the
    skip logic can never see it. Returns zero rows so the call short-circuits
    cleanly on the "nothing to animate" path — no execute/storage mocking
    needed at all."""
    seen = {}

    async def fake_fetch_one(query, *args):
        if "FROM videos WHERE id" in query:
            return _video_row()
        return None

    async def fake_fetch_all(query, *args):
        if "FROM assets WHERE" in query and "image_prompt" in query:
            seen["query"] = query
        return []

    async def fake_log_activity(self, *a, **k):
        return None

    monkeypatch.setattr(pe_mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pe_mod, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(PipelineExecutor, "_log_activity", fake_log_activity)

    executor = _make_executor(_FakeImageClient())
    result = asyncio.run(executor.run_clip_generation(VIDEO))

    assert result["status"] == "completed"
    assert "query" in seen, "the per-row assets SELECT never ran"
    assert "motion_gate_status" in seen["query"]


# =============================================================================
# 2. Render-assembler failure fails closed (no auto-fallback stitch)
# =============================================================================

import render_perform as render_perform_mod  # noqa: E402
import render_stitch as render_stitch_mod  # noqa: E402


def _perform_render_test_setup(monkeypatch, allow_env):
    """One fully-clipped row in a character_dialogue/voice_over video —
    triggers run_clip_generation's per-scene auto-stitch-preview branch,
    which tries the performance-track assembler first."""
    rows = [_row("asset-1", 1, 1, "Camera holds steady, subject motion only.")]
    ledger_calls, activity_inserts, clip_url_updates = _base_patches(
        monkeypatch, rows, comp_result={"pics": 1, "clips": 1},
        dialogue_mode="character_dialogue", dialogue_audio="voice_over")

    stitch_calls = []

    async def fake_assemble_scene(video_id, tenant_id, scene):
        raise RuntimeError("boom: performance assembly exploded")

    async def fake_stitch_video(video_id, tenant_id, scene=None, **kw):
        stitch_calls.append((video_id, tenant_id, scene))
        return {"final_video_url": "https://fake/stitched.mp4", "clip_count": 1}

    monkeypatch.setattr(render_perform_mod, "assemble_scene", fake_assemble_scene)
    monkeypatch.setattr(render_stitch_mod, "stitch_video", fake_stitch_video)

    if allow_env is None:
        monkeypatch.delenv("SE_ALLOW_FALLBACK_STITCH", raising=False)
    else:
        monkeypatch.setenv("SE_ALLOW_FALLBACK_STITCH", allow_env)

    image_client = _FakeImageClient()
    executor = _make_executor(image_client)
    result = asyncio.run(executor.run_clip_generation(VIDEO))
    assert result["status"] == "completed", result
    return activity_inserts, stitch_calls


def test_assembly_failure_default_blocks_no_fallback_stitch(monkeypatch):
    """Default (SE_ALLOW_FALLBACK_STITCH unset): assembly failure must be
    logged to bot_activity and must NOT fall through to plain stitch_video —
    the quality downgrade never auto-ships."""
    activity_inserts, stitch_calls = _perform_render_test_setup(monkeypatch, allow_env=None)
    assert not stitch_calls, "plain stitch must never run automatically by default"
    render_failures = [a for a in activity_inserts if a[1] == "Render Bot" and a[3] == "failed"]
    assert render_failures, "the assembly failure must be visible on bot_activity"
    msg = render_failures[0][4]
    assert "blocked" in msg.lower()
    assert "SE_ALLOW_FALLBACK_STITCH" in msg


def test_assembly_failure_with_flag_on_falls_back_to_stitch(monkeypatch):
    """SE_ALLOW_FALLBACK_STITCH=1: the pre-existing behavior (0fb33de6) is
    restored — plain stitch runs and the bot_activity row says so."""
    activity_inserts, stitch_calls = _perform_render_test_setup(monkeypatch, allow_env="1")
    assert stitch_calls, "the explicit opt-in must still allow the fallback stitch"
    render_failures = [a for a in activity_inserts if a[1] == "Render Bot" and a[3] == "failed"]
    assert render_failures
    msg = render_failures[0][4]
    assert "fell back to plain stitch" in msg.lower()
