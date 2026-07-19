"""C35 regression: a keyless (Kie-only) tenant hitting audio sync must get a
clear, actionable error — never a silent "success" dict with 0 durations
written. See docs/reports/2026-07-17-storyengine-agent-audit-findings.md
Sweep 2 finding 5 / tasks/storyengine-wiring-fix-checklist.md §3.4.
"""

import asyncio
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import render.audio_sync.transcriber as transcriber
import render.run_audio_sync as run_audio_sync

_TIMING_DIR = Path(__file__).resolve().parent.parent.parent.parent / "timing" / "video-c35-test"


@pytest.fixture(autouse=True)
def _clean_timing_dir():
    """run_audio_sync.run() writes to skills/video-pipeline/timing/<video_id>/
    on disk (legacy Airtable-cron pipeline behavior, not mocked here) —
    keep the test video_id's directory out of the repo working tree."""
    yield
    shutil.rmtree(_TIMING_DIR, ignore_errors=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeAirtable:
    def __init__(self, image_records):
        self._image_records = image_records
        self.images_table = SimpleNamespace(update=lambda *a, **k: None)

    def get_all_images_for_video(self, title):
        return self._image_records


class _FakeGoogle:
    """No Drive folder configured — forces the local public/ fallback,
    which also finds nothing, so `run()` exits before ever reaching
    transcription. Only used by the "0 duration_updates" test where we need
    to get past the audio-file-lookup gate with a fake local file."""

    def list_files_in_folder(self, folder_id):
        return []


class _FakeSlack:
    def __init__(self):
        self.notifications = []

    def notify(self, msg):
        self.notifications.append(msg)


def _make_pipeline(image_records=None):
    return SimpleNamespace(
        current_idea={"id": "rec123"},
        current_idea_id="video-c35-test",
        video_title="C35 Test Video",
        project_folder_id=None,
        airtable=_FakeAirtable(image_records or [{"Scene": 1, "Image Index": 1}]),
        google=_FakeGoogle(),
        slack=_FakeSlack(),
    )


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clear_openai_key(monkeypatch):
    """Every test controls OPENAI_API_KEY explicitly — never inherit the
    real environment's key (would make these tests non-deterministic on a
    machine that has one configured for the legacy single-tenant pipeline)."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


# ---------------------------------------------------------------------------
# transcriber.is_configured() — the single source of truth for "can Whisper
# run at all"
# ---------------------------------------------------------------------------

class TestIsConfigured:
    def test_missing_key_is_not_configured(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert transcriber.is_configured() is False

    def test_placeholder_key_is_not_configured(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-xxxxx-placeholder")
        assert transcriber.is_configured() is False

    def test_empty_string_key_is_not_configured(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "")
        assert transcriber.is_configured() is False

    def test_real_looking_key_is_configured(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-real-key-abc123")
        assert transcriber.is_configured() is True


# ---------------------------------------------------------------------------
# run_audio_sync.run() — the keyless tenant path
# ---------------------------------------------------------------------------

class TestKeylessTenantGetsClearError:
    def test_no_key_returns_error_not_silent_success(self, monkeypatch):
        """Before this fix: no key -> every scene's transcribe() raised,
        was caught per-scene, and the function still returned a dict with
        no "error" key (bot="Audio Sync", duration_updates=0) — reported
        as success by every caller. Now: fails fast with an "error" key
        before even touching Drive/Airtable for scene audio."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        pipeline = _make_pipeline()

        result = _run(run_audio_sync.run(pipeline))

        assert "error" in result, (
            "keyless tenant must get a clear error, not a silent success dict"
        )
        assert "OPENAI_API_KEY" in result["error"] or "OpenAI" in result["error"]
        assert result["bot"] == "Audio Sync"

    def test_no_key_notifies_slack(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        pipeline = _make_pipeline()

        _run(run_audio_sync.run(pipeline))

        assert pipeline.slack.notifications, "the missing-key stop must be surfaced, not silent"
        assert "Audio sync" in pipeline.slack.notifications[0]

    def test_placeholder_key_treated_same_as_missing(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-xxxxx")
        pipeline = _make_pipeline()

        result = _run(run_audio_sync.run(pipeline))

        assert "error" in result

    def test_real_key_configured_does_not_hit_the_fast_fail_gate(self, monkeypatch):
        """A tenant WITH a real key must not be stopped by the new upfront
        check — it should proceed into the normal flow (which, in this
        stub environment with no real audio files, fails later for an
        UNRELATED reason: no scene audio found). This proves the gate is
        keyed specifically on Whisper-key presence, not a blanket block."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-real-key-abc123")
        pipeline = _make_pipeline()

        result = _run(run_audio_sync.run(pipeline))

        assert "error" in result
        assert "No scene audio files found" in result["error"], (
            "expected to progress past the key gate and fail on the next "
            f"real gate instead — got: {result['error']!r}"
        )


class TestAllScenesFailingNeverReportsSilentSuccess:
    def test_zero_duration_updates_returns_error(self, monkeypatch):
        """Even with a real key configured, if every scene's transcription
        comes back empty/failed for some other reason (corrupt audio,
        transient API error), the stage must not write render_config.json
        and claim success with 0 timed images."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-real-key-abc123")

        pipeline = _make_pipeline(image_records=[
            {"Scene": 1, "Image Index": 1, "Sentence Text": "hello world"},
        ])

        def _fake_transcribe(audio_path, cache_dir=None, **_kwargs):
            raise RuntimeError("simulated transient transcription failure")

        monkeypatch.setattr(run_audio_sync, "transcribe", _fake_transcribe)

        # Give run_audio_sync one scene audio "file" via the Drive path so it
        # gets past the "no scene audio files found" gate and into the
        # per-scene transcription loop, where _fake_transcribe wipes out
        # every scene.
        pipeline.project_folder_id = "fake-folder-id"

        class _GoogleWithOneFile:
            def list_files_in_folder(self, folder_id):
                return [{"name": "Scene 1.mp3", "id": "file-1"}]

            def download_file(self, file_id):
                return b"x" * 1000  # must be >=500 bytes to pass run_audio_sync's size check

        pipeline.google = _GoogleWithOneFile()

        result = _run(run_audio_sync.run(pipeline))

        assert "error" in result, (
            "0 duration_updates (every scene failed transcription) must "
            "return an error dict, not a fake-success 'bot: Audio Sync' dict"
        )
        assert "0 timed images" in result["error"]
