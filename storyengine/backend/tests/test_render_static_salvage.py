"""Render-salvage guard (2026-07-22 incident) + GoogleClient strict-folder init.

Incident: a 63-min static render finished, but the post-render Drive upload
404'd (bad parent folder — GoogleClient fell back to a hardcoded personal
folder the VPS Drive identity can't see), and render_static_video's
`finally: shutil.rmtree(workdir)` then deleted the only copy of the finished
MP4. Two independent fixes, two tests:

  1. render_static.render_static_video: if out.mp4 exists when a post-render
     step raises, the file is moved to ~/render_salvage/<video_id>.mp4 BEFORE
     the workdir cleanup, and the original exception still propagates.
  2. shared.clients.google_client.GoogleClient: strict_folder=True raises at
     __init__ instead of silently resolving to the hardcoded default folder
     when GOOGLE_DRIVE_FOLDER_ID is unset and no parent_folder_id is given.

Both are local/no-spend: no real Drive, no real Remotion/ffmpeg, no real DB —
every dependency render_static_video touches is monkeypatched to a stub that
just moves bytes around on disk, matching the pattern in
tests/test_drive_workspace.py (FakeGoogleClient) and
tests/test_machine_documentary_hold.py (fake fetch_one/fetch_all).
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import render_static  # noqa: E402


# ---------------------------------------------------------------------------
# 1. Salvage path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_failure_salvages_finished_mp4_before_workdir_cleanup(
    monkeypatch, tmp_path
):
    video_id = "salvage-test-vid"
    tenant_id = "tenant-1"
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    created_workdirs = []
    real_mkdtemp = render_static.tempfile.mkdtemp

    def fake_mkdtemp(prefix=None, dir=None):
        path = real_mkdtemp(prefix=prefix, dir=str(tmp_path))
        created_workdirs.append(path)
        return path

    monkeypatch.setattr(render_static.tempfile, "mkdtemp", fake_mkdtemp)

    async def fake_gather_segments(video_id, tenant_id):
        return [{
            "scene": 1, "scene_text": "hello", "voice_url": "http://x/v.mp3",
            "voice_duration": 5.0, "image_url": "http://x/i.png", "caption": None,
        }]

    def fake_google_client():
        return object()

    async def fake_download_to(url, dest, gc):
        dest.write_bytes(b"fake-bytes")

    async def fake_normalize_audio(path):
        return None

    async def fake_probe_duration(path):
        return 5.0

    def fake_build_render_config(video_id, segments):
        return {"video_id": video_id, "total_duration_seconds": 5.0, "scenes": []}

    async def fake_select_music_beds(tenant_id, segments, rc, public_dir):
        return []

    async def fake_run_remotion(public_dir, props_file, out_file, on_progress):
        out_file.write_bytes(b"fake-finished-mp4-bytes")

    async def fake_upload_bytes(data, path, content_type, tenant_id):
        raise RuntimeError("simulated Drive 404 (bad parent folder)")

    monkeypatch.setattr(render_static, "_gather_segments", fake_gather_segments)
    monkeypatch.setattr(render_static, "_google_client", fake_google_client)
    monkeypatch.setattr(render_static, "_download_to", fake_download_to)
    monkeypatch.setattr(render_static, "_normalize_audio", fake_normalize_audio)
    monkeypatch.setattr(render_static, "_probe_duration", fake_probe_duration)
    monkeypatch.setattr(render_static, "_build_render_config", fake_build_render_config)
    monkeypatch.setattr(render_static, "_select_music_beds", fake_select_music_beds)
    monkeypatch.setattr(render_static, "_run_remotion", fake_run_remotion)
    monkeypatch.setattr(render_static, "upload_bytes", fake_upload_bytes)

    with pytest.raises(RuntimeError, match="simulated Drive 404"):
        await render_static.render_static_video(video_id, tenant_id, title="Test Video")

    assert len(created_workdirs) == 1
    workdir = created_workdirs[0]

    # The exception propagated — the caller (background task runner) still
    # sees the real failure, it's just no longer a total loss.
    assert not os.path.exists(workdir), "workdir must still be cleaned up on failure"

    salvage_path = fake_home / "render_salvage" / f"{video_id}.mp4"
    assert salvage_path.exists(), "finished MP4 must be salvaged before workdir cleanup"
    assert salvage_path.read_bytes() == b"fake-finished-mp4-bytes"


@pytest.mark.asyncio
async def test_happy_path_still_cleans_up_fully_no_salvage_file(monkeypatch, tmp_path):
    """Control case: when nothing raises, no salvage file is left behind and
    the workdir is still removed — the salvage guard must not change the
    happy path."""
    video_id = "happy-path-vid"
    tenant_id = "tenant-1"
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    created_workdirs = []
    real_mkdtemp = render_static.tempfile.mkdtemp

    def fake_mkdtemp(prefix=None, dir=None):
        path = real_mkdtemp(prefix=prefix, dir=str(tmp_path))
        created_workdirs.append(path)
        return path

    monkeypatch.setattr(render_static.tempfile, "mkdtemp", fake_mkdtemp)

    async def fake_gather_segments(video_id, tenant_id):
        return [{
            "scene": 1, "scene_text": "hello", "voice_url": "http://x/v.mp3",
            "voice_duration": 5.0, "image_url": "http://x/i.png", "caption": None,
        }]

    async def fake_download_to(url, dest, gc):
        dest.write_bytes(b"fake-bytes")

    async def fake_normalize_audio(path):
        return None

    async def fake_probe_duration(path):
        return 5.0

    def fake_build_render_config(video_id, segments):
        return {"video_id": video_id, "total_duration_seconds": 5.0, "scenes": []}

    async def fake_select_music_beds(tenant_id, segments, rc, public_dir):
        return []

    async def fake_run_remotion(public_dir, props_file, out_file, on_progress):
        out_file.write_bytes(b"fake-finished-mp4-bytes")

    async def fake_upload_bytes(data, path, content_type, tenant_id):
        return "https://drive.example.com/final.mp4"

    monkeypatch.setattr(render_static, "_gather_segments", fake_gather_segments)
    monkeypatch.setattr(render_static, "_google_client", lambda: object())
    monkeypatch.setattr(render_static, "_download_to", fake_download_to)
    monkeypatch.setattr(render_static, "_normalize_audio", fake_normalize_audio)
    monkeypatch.setattr(render_static, "_probe_duration", fake_probe_duration)
    monkeypatch.setattr(render_static, "_build_render_config", fake_build_render_config)
    monkeypatch.setattr(render_static, "_select_music_beds", fake_select_music_beds)
    monkeypatch.setattr(render_static, "_run_remotion", fake_run_remotion)
    monkeypatch.setattr(render_static, "upload_bytes", fake_upload_bytes)

    result = await render_static.render_static_video(video_id, tenant_id, title="Test Video")

    assert result["final_video_url"] == "https://drive.example.com/final.mp4"
    assert len(created_workdirs) == 1
    assert not os.path.exists(created_workdirs[0])
    assert not (fake_home / "render_salvage").exists()


# ---------------------------------------------------------------------------
# 2. Clean frames: no caption text on static-docu renders by default
# ---------------------------------------------------------------------------

def _caption_segments():
    return [{
        "scene": 1, "scene_text": "hello", "voice_url": "http://x/v.mp3",
        "voice_duration": 5.0, "duration": 5.0, "image_url": "http://x/i.png",
        "caption": {"title": "B-52 STRATOFORTRESS", "sub": "1955 — present"},
    }]


def test_render_config_has_no_caption_text_by_default(monkeypatch):
    """DvsU clean-frames rule: even when the asset rows carry caption JSON,
    the renderConfig hands Scene.tsx empty caption fields — Scene.tsx only
    draws its text block when caption_title is non-empty."""
    assert render_static.DRAW_CAPTIONS is False  # default off
    rc = render_static._build_render_config("vid-1", _caption_segments())
    scene = rc["scenes"][0]
    assert scene["caption_title"] == ""
    assert scene["caption_sub"] == ""


def test_render_config_carries_captions_when_flag_enabled(monkeypatch):
    """The drawing plumbing stays: flipping the flag restores captions."""
    monkeypatch.setattr(render_static, "DRAW_CAPTIONS", True)
    rc = render_static._build_render_config("vid-1", _caption_segments())
    scene = rc["scenes"][0]
    assert scene["caption_title"] == "B-52 STRATOFORTRESS"
    assert scene["caption_sub"] == "1955 — present"


# ---------------------------------------------------------------------------
# 3. GoogleClient strict-folder init
# ---------------------------------------------------------------------------

def test_strict_folder_raises_when_env_and_explicit_parent_both_missing(monkeypatch):
    monkeypatch.delenv("GOOGLE_DRIVE_FOLDER_ID", raising=False)
    from shared.clients.google_client import GoogleClient

    with pytest.raises(RuntimeError, match="GOOGLE_DRIVE_FOLDER_ID not set"):
        GoogleClient(
            client_id="cid", client_secret="csecret", refresh_token="rtok",
            strict_folder=True,
        )


def test_strict_folder_ok_when_explicit_parent_given(monkeypatch):
    monkeypatch.delenv("GOOGLE_DRIVE_FOLDER_ID", raising=False)
    from shared.clients.google_client import GoogleClient

    client = GoogleClient(
        client_id="cid", client_secret="csecret", refresh_token="rtok",
        parent_folder_id="explicit-folder-id", strict_folder=True,
    )
    assert client.parent_folder_id == "explicit-folder-id"


def test_strict_folder_ok_when_env_var_set(monkeypatch):
    monkeypatch.setenv("GOOGLE_DRIVE_FOLDER_ID", "env-folder-id")
    from shared.clients.google_client import GoogleClient

    client = GoogleClient(
        client_id="cid", client_secret="csecret", refresh_token="rtok",
        strict_folder=True,
    )
    assert client.parent_folder_id == "env-folder-id"


def test_non_strict_still_falls_back_to_default_for_local_skill_runs(monkeypatch):
    """Unchanged legacy behavior for content-engine / clone-video local runs
    that never set GOOGLE_DRIVE_FOLDER_ID: default parent_folder_id, no
    exception."""
    monkeypatch.delenv("GOOGLE_DRIVE_FOLDER_ID", raising=False)
    from shared.clients.google_client import GoogleClient

    client = GoogleClient(client_id="cid", client_secret="csecret", refresh_token="rtok")
    assert client.parent_folder_id == GoogleClient.DEFAULT_PARENT_FOLDER_ID
