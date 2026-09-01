"""Tests for voice/run.py's failure handling (voicefix, root cause #1).

Before this fix: a scene whose ElevenLabs/Kie call failed (generate_and_wait
returned None) was silently skipped — voice_count just didn't count it, no
error was recorded, and the bot still advanced status to
'Ready For Image Prompts' as if every scene had been voiced. That is exactly
what happened to tenant tgb29's video 146242df: all 3 scenes ended up with
voice_over_url IS NULL, yet the status advanced three stages past voice and
$1.50 of real image spend got logged afterward.

These tests exercise voice.run.run() directly against a minimal fake
pipeline — no real Airtable/Supabase/ElevenLabs/Google calls.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orchestrator.pipeline_constants import ScriptFields, Statuses  # noqa: E402
from voice.run import run, mp3_duration_seconds  # noqa: E402


def _fixture_mp3(num_frames: int = 40) -> bytes:
    """A tiny but fully valid MPEG-1 Layer III file: N identical 128kbps/
    44.1kHz/stereo frames back to back, no ID3/Xing header. mutagen parses
    real frame headers to get the length — this is not a hardcoded/mocked
    duration, it is computed from the bytes exactly like a real ElevenLabs
    MP3 would be. Frame size 417 bytes = floor(144*128000/44100) (verified
    against mutagen directly: 40 frames -> 1.04s, matching 40*1152/44100)."""
    header = bytes([0xFF, 0xFB, 0x90, 0x00])
    frame_size = 417
    frame = header + b"\x00" * (frame_size - len(header))
    return frame * num_frames


class FakeElevenLabs:
    """Scene number -> outcome. Outcome is either a truthy 'audio url' string
    (success) or None (failure, with an optional fail message captured via
    fail_info_out — mirrors the real ElevenLabsClient.generate_and_wait
    contract added by this fix)."""

    def __init__(
        self,
        outcomes: dict,
        fail_message: str = "Kie TTS task failed: Internal Error, Please try again later.",
        audio_bytes: bytes = b"fake-audio-bytes",
    ):
        self.outcomes = outcomes
        self.fail_message = fail_message
        self.calls = []
        # Deliberately NOT a valid MP3 by default — mirrors the pre-fix world
        # and proves duration parsing failure never blocks the URL write.
        # A test that wants a real computed duration passes real MP3 bytes.
        self.audio_bytes = audio_bytes

    async def generate_and_wait(self, text, voice_id=None, task_id_callback=None, fail_info_out=None):
        # scene number is threaded through via the calling test's scene_text->scene map
        self.calls.append(text)
        scene = self._scene_for_text(text)
        ok = self.outcomes.get(scene, True)
        if ok:
            return f"file:///tmp/scene-{scene}.mp3"
        if fail_info_out is not None:
            fail_info_out.append({"failCode": "500", "failMsg": self.fail_message, "creditsConsumed": 0.0})
        return None

    def _scene_for_text(self, text):
        # tests encode the scene number at the front of the scene text
        return int(text.split()[0])

    async def download_audio(self, audio_path):
        return self.audio_bytes


class FakeGoogle:
    def get_or_create_folder(self, title):
        return {"id": "folder-1"}

    def upload_audio(self, content, filename, folder_id):
        return {"id": f"drive-{filename}"}


class FakeSlack:
    def notify_voice_start(self):
        pass

    def notify_voice_done(self):
        pass


class FakeAirtable:
    def __init__(self, scripts):
        self._scripts = scripts
        self.finished = []

    def get_scripts_by_title(self, title):
        return self._scripts

    def mark_script_finished(self, script_id, url, voice_duration_seconds=None):
        self.finished.append((script_id, url, voice_duration_seconds))
        for s in self._scripts:
            if s["id"] == script_id:
                s[ScriptFields.SCRIPT_STATUS] = ScriptFields.STATUS_FINISHED


class FakePipeline:
    def __init__(self, scripts, outcomes, scene_filter=None):
        self.current_idea = {"Status": Statuses.READY_VOICE}
        self.video_title = "Test Video"
        self.project_folder_id = "folder-1"
        self.google = FakeGoogle()
        self.slack = FakeSlack()
        self.airtable = FakeAirtable(scripts)
        self.elevenlabs = FakeElevenLabs(outcomes)
        self.scene_filter = scene_filter
        self.image_filter = None
        self.should_cancel = None
        self.dialogue_mode = ""
        self.status_updates = []

    @property
    def _is_targeted_run(self):
        return self.scene_filter is not None or self.image_filter is not None

    def _log_filters(self):
        pass

    def _update_status(self, new_status):
        self.status_updates.append(new_status)
        self.current_idea["Status"] = new_status


def _scripts(n):
    """n scenes, each scene_text starting with its own scene number (so the
    fake ElevenLabs client can look up its per-scene outcome)."""
    return [
        {
            "id": f"script-{i}",
            "scene": i,
            ScriptFields.SCENE_TEXT: f"{i} This is the narration for scene {i}.",
            ScriptFields.SCRIPT_STATUS: "",
        }
        for i in range(1, n + 1)
    ]


def test_all_scenes_succeed_advances_status():
    """Baseline (unchanged behavior): every scene voiced -> status advances."""
    scripts = _scripts(3)
    pipeline = FakePipeline(scripts, outcomes={1: True, 2: True, 3: True})
    result = asyncio.run(run(pipeline))
    assert result.get("error") is None
    assert result["voice_count"] == 3
    assert pipeline.status_updates == [Statuses.READY_IMAGE_PROMPTS]
    print("test_all_scenes_succeed_advances_status OK")


def test_all_scenes_fail_does_not_advance_and_surfaces_error():
    """Root cause #1, the reproduction of the tgb29 incident: every provider
    call fails -> the bot must NOT advance status and MUST return an error."""
    scripts = _scripts(3)
    pipeline = FakePipeline(scripts, outcomes={1: False, 2: False, 3: False})
    result = asyncio.run(run(pipeline))
    assert result.get("error"), f"expected an error, got: {result}"
    assert result["voice_count"] == 0
    assert pipeline.status_updates == [], (
        "status must NOT advance when zero scenes were voiced — this is the "
        "exact tgb29 bug (status advanced with 0/3 scenes voiced)"
    )
    assert result["failed_scenes"] == [1, 2, 3]
    print("test_all_scenes_fail_does_not_advance_and_surfaces_error OK")


def test_provider_auth_failure_stops_after_first_scene():
    """An invalid account is global, not scene-specific. Do not hammer the
    same rejected credential once per scene before admitting the stage is
    blocked."""
    scripts = _scripts(24)
    pipeline = FakePipeline(scripts, outcomes={i: False for i in range(1, 25)})
    pipeline.elevenlabs.fail_message = (
        "Kie TTS createTask failed: Unauthorized - Authentication failed"
    )

    result = asyncio.run(run(pipeline))

    assert result.get("error")
    assert "Settings" in result["error"]
    assert result.get("provider_auth_failed") is True
    assert len(pipeline.elevenlabs.calls) == 1
    assert pipeline.status_updates == []


def test_partial_failure_does_not_advance_status():
    """Partial-success rule: even ONE missing scene stops the run and
    reports it, rather than silently rendering a film with gaps."""
    scripts = _scripts(3)
    pipeline = FakePipeline(scripts, outcomes={1: True, 2: False, 3: True})
    result = asyncio.run(run(pipeline))
    assert result.get("error"), f"expected an error for the partial failure, got: {result}"
    assert result["voice_count"] == 2, "the 2 scenes that DID succeed must still be counted/persisted"
    assert pipeline.status_updates == [], "status must not advance on a partial failure"
    assert result["failed_scenes"] == [2]
    # The two successful scenes were persisted (mark_script_finished called),
    # so a re-run only needs to retry scene 2 — already-finished scenes are
    # skipped by the SCRIPT_STATUS check at the top of the loop.
    assert len(pipeline.airtable.finished) == 2
    print("test_partial_failure_does_not_advance_status OK")


def test_resume_after_fix_only_retries_failed_scene():
    """After a partial failure, re-running voice only re-attempts the scene
    that failed — already-finished scenes are skipped (resumability)."""
    scripts = _scripts(3)
    pipeline = FakePipeline(scripts, outcomes={1: True, 2: False, 3: True})
    first = asyncio.run(run(pipeline))
    assert first.get("error")

    # Simulate the retry succeeding this time.
    pipeline.elevenlabs = FakeElevenLabs(outcomes={1: True, 2: True, 3: True})
    second = asyncio.run(run(pipeline))
    assert second.get("error") is None
    assert second["voice_count"] == 1, "only scene 2 should have been (re)synthesized"
    assert pipeline.status_updates == [Statuses.READY_IMAGE_PROMPTS]
    print("test_resume_after_fix_only_retries_failed_scene OK")


def test_targeted_run_failure_is_reported_not_silent():
    """A single-scene targeted regeneration that fails must surface an error
    too (previously it silently reported {'targeted': True} with no hint the
    retry didn't take)."""
    scripts = _scripts(1)
    pipeline = FakePipeline(scripts, outcomes={1: False}, scene_filter=1)
    result = asyncio.run(run(pipeline))
    assert result.get("targeted") is True
    assert result.get("error"), "a failed targeted regeneration must report an error"
    assert pipeline.status_updates == []
    print("test_targeted_run_failure_is_reported_not_silent OK")


# ── voice_duration_seconds (this fix) ──────────────────────────────────────
#
# storyengine/schema.sql's scripts.voice_duration_seconds existed but was
# always NULL: run.py downloaded the narration MP3 bytes, uploaded them to
# Drive, and called mark_script_finished(id, url) — never computing or
# passing a duration. render_static.py and channel_identity_context.py both
# read this column downstream (falling back to ffprobe / silently excluding
# the video from duration totals when it's NULL). These tests prove the real
# MP3 bytes already in memory get turned into a duration and written in the
# SAME mark_script_finished call that stores voice_over_url.

def test_mp3_duration_seconds_computes_real_length():
    """Direct unit test of the helper: a real (synthetic but valid) MPEG
    frame stream must parse to a real, rounded, positive duration."""
    duration = mp3_duration_seconds(_fixture_mp3(num_frames=40))
    assert duration is not None
    # 40 frames * 1152 samples/frame / 44100 Hz ≈ 1.045s; mutagen's own
    # frame-header reader (verified directly, not re-derived here) reports
    # 1.04s for this exact fixture.
    assert duration == 1.04, f"expected 1.04, got {duration}"
    print("test_mp3_duration_seconds_computes_real_length OK")


def test_mp3_duration_seconds_returns_none_for_unparseable_bytes():
    """Bytes that aren't a real MP3 must not raise — they return None so the
    scene can still be persisted with voice_over_url set."""
    assert mp3_duration_seconds(b"fake-audio-bytes") is None
    assert mp3_duration_seconds(b"") is None
    print("test_mp3_duration_seconds_returns_none_for_unparseable_bytes OK")


def test_voice_duration_written_alongside_url_from_real_mp3_bytes():
    """End-to-end through run(): when the downloaded audio is a real MP3,
    mark_script_finished is called with BOTH the Drive URL and the real
    computed duration, in the same call."""
    scripts = _scripts(1)
    pipeline = FakePipeline(scripts, outcomes={1: True})
    pipeline.elevenlabs = FakeElevenLabs(outcomes={1: True}, audio_bytes=_fixture_mp3(num_frames=40))
    result = asyncio.run(run(pipeline))
    assert result.get("error") is None, result
    assert len(pipeline.airtable.finished) == 1
    script_id, url, duration = pipeline.airtable.finished[0]
    assert script_id == "script-1"
    assert url == "https://drive.google.com/uc?id=drive-Scene 1.mp3&export=download"
    assert duration == 1.04, f"expected real duration 1.04, got {duration}"
    print("test_voice_duration_written_alongside_url_from_real_mp3_bytes OK")


def test_voice_duration_none_never_blocks_url_write():
    """When the audio bytes can't be parsed (default FakeElevenLabs behavior
    — mirrors a real provider hiccup or unusual encoding), the scene must
    still be marked finished with its voice_over_url; duration is None."""
    scripts = _scripts(1)
    pipeline = FakePipeline(scripts, outcomes={1: True})  # default audio_bytes = unparseable
    result = asyncio.run(run(pipeline))
    assert result.get("error") is None, result
    assert len(pipeline.airtable.finished) == 1
    script_id, url, duration = pipeline.airtable.finished[0]
    assert url, "voice_over_url must still be written even when duration parsing fails"
    assert duration is None
    print("test_voice_duration_none_never_blocks_url_write OK")


if __name__ == "__main__":
    test_all_scenes_succeed_advances_status()
    test_all_scenes_fail_does_not_advance_and_surfaces_error()
    test_partial_failure_does_not_advance_status()
    test_resume_after_fix_only_retries_failed_scene()
    test_targeted_run_failure_is_reported_not_silent()
    test_mp3_duration_seconds_computes_real_length()
    test_mp3_duration_seconds_returns_none_for_unparseable_bytes()
    test_voice_duration_written_alongside_url_from_real_mp3_bytes()
    test_voice_duration_none_never_blocks_url_write()
    print("\nAll voice/run.py failure-handling tests passed.")
