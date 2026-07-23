"""Tests for the three dialogue-guard laws shipped 2026-07-22 (root causes
verified live on video f00ea79a scene 1):

LAW 1 — a coverage row's assigned_dialogue is the SINGLE SOURCE OF TRUTH for
whether it speaks. NULL means non-speaking, period — match_lines' substring
match against sentence_text must never promote a coverage row, because a
reaction card's beat label ("T16 — Vanessa softens: \"Flores. Flowers. Okay.
That is sweet.\"") embeds the SPEAKER's full quoted line and was silently
hijacking the reactor's own motion prompt AND its ElevenLabs voice lock.
pipeline_executor.py's `_one()` closure (~12775 for the `lines` computation,
~12939 for the `spk` voice-lock fallback).

LAW 2 — a non-speaking clip's prompt explicitly says mouths stay shut
(clip_dialogue.NO_SPEECH_CLAUSE, appended in pipeline_executor.py's
non-speaking branch). Never leaks into the speaking branch.

LAW 3 — a channel tone hint (channel_identity.voice_tone, the SAME field
identity_builder already writes) reaches both the motion-writer's user
message (scripts/coverage_to_app.py::_write_motion_prompts) and
clip_dialogue.speaking_prompt()'s delivery instruction — one line, byte-
identical output when no tone is on file.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_dialogue_guard_laws.py -q
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))

import pipeline_executor as pe_mod  # noqa: E402
from pipeline_executor import PipelineExecutor  # noqa: E402
import storage as storage_mod  # noqa: E402
import clip_dialogue as clip_dialogue_mod  # noqa: E402
from clip_dialogue import speaking_prompt, OFF_SCREEN_SPEAKER_RULE, NO_SPEECH_CLAUSE  # noqa: E402
import channel_format  # noqa: E402

TENANT = "tenant-1"
VIDEO = "video-1"


# ===========================================================================
# LAW 1 + LAW 2 — run_clip_generation(): a coverage reaction row whose
# sentence_text embeds a full quoted line stays non-speaking, keeps its own
# motion prompt, and gets the mouths-shut clause.
# ===========================================================================

class _FakeLightPipeline:
    def __init__(self, image_client):
        self.image_client = image_client
        self.should_cancel = None  # _install_cancel_support overwrites this fail-soft


class _CapturingImageClient:
    """Records the prompt actually sent to Grok — proves which branch
    (speaking vs non-speaking) ran and exactly what it said."""
    VEO_MODEL_QUALITY = "veo-quality-id"
    VEO_MODEL_FAST = "veo-fast-id"

    def __init__(self):
        self.calls = []  # (engine, prompt)

    async def generate_video(self, img, prompt, duration=6, extra_image_urls=None,
                              aspect_ratio="16:9", resolution="720p", task_id_out=None):
        self.calls.append(("grok", prompt))
        if task_id_out is not None:
            task_id_out.append("grok-task-1")
        return "https://fake/grok-clip.mp4"

    async def generate_video_veo(self, prompt, image_url=None, model=None, task_id_out=None):
        self.calls.append(("veo", prompt))
        if task_id_out is not None:
            task_id_out.append("veo-task-1")
        return "https://fake/veo-clip.mp4"

    async def download_image(self, url):
        return b"fake-clip-bytes"


# The actual root-cause shape from prod: a reaction card's sentence_text
# names the beat and quotes the SPEAKER's line verbatim.
REACTOR_SENTENCE_TEXT = 'T16 — Vanessa softens: "Flores. Flowers. Okay. That is sweet."'
REACTOR_MOTION_PROMPT = "Ryan glances toward Vanessa, quietly listening, a small smile forming."

_DIALOGUE_LINE = {
    "type": "dialogue", "text": "Flores. Flowers. Okay. That is sweet.", "speaker": "Vanessa",
    "audio_url": "https://fake/voice1.mp3", "duration": 2.0,
}


def _reactor_row(generation_method="coverage"):
    return {
        "id": "asset-1", "scene": 1, "image_index": 3,
        "image_url": "https://fake/img1.png", "drive_image_url": None,
        "video_prompt": REACTOR_MOTION_PROMPT,
        "video_clip_url": None, "duration_seconds": 4.0,
        "sentence_text": REACTOR_SENTENCE_TEXT,
        "image_prompt": "Ryan in the kitchen, Vanessa beside him",
        "assigned_dialogue": None,  # LAW 1: NULL — this card does NOT speak
        "routed_model": None, "model_override": None, "camera_preset_id": None,
        "generation_method": generation_method,
    }


def _video_row():
    return {
        "id": VIDEO, "video_model": "grok-imagine", "aspect_ratio": "16:9",
        "video_resolution": "720p", "dialogue_mode": "character_dialogue",
        "dialogue_audio": "voice_over", "character_reference_url": None,
        "image_style_override": None, "status": "ready_for_video_generation",
    }


def _run_clip_generation_for_row(monkeypatch, row):
    async def fake_fetch_one(query, *args):
        if "FROM videos WHERE id" in query:
            return _video_row()
        if "SELECT scene FROM assets WHERE id" in query:
            return {"scene": 1}
        if "COUNT(*) AS pics, COUNT(video_clip_url) AS clips" in query:
            return {"pics": 1, "clips": 0}
        return None

    async def fake_fetch_all(query, *args):
        if "FROM assets WHERE" in query and "generation_method" in query:
            assert "generation_method" in query, (
                "run_clip_generation's asset query must select generation_method "
                "(LAW 1) or a coverage row can never be told apart from a legacy card")
            return [row]
        if "dialogue_segments FROM scripts" in query:
            return [{"scene": 1, "dialogue_segments": [_DIALOGUE_LINE]}]
        if "video_characters" in query:
            return []
        return []

    model_used_updates = []
    clip_url_updates = []

    async def fake_execute(query, *args):
        if "UPDATE assets SET video_clip_url" in query:
            clip_url_updates.append(args)
        elif "UPDATE assets SET model_used" in query:
            model_used_updates.append(args)
        return "OK"

    async def fake_record_ledger_entry(**kwargs):
        pass

    async def fake_upload_bytes(data, path, content_type, tenant_id=None):
        return f"https://fake-storage.example/{path}"

    async def fake_duck_audio(clip_bytes, gain=0.3):
        return clip_bytes  # passthrough — no real ffmpeg dependency in tests

    monkeypatch.setattr(pe_mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pe_mod, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(pe_mod, "execute", fake_execute)
    monkeypatch.setattr(pe_mod, "record_ledger_entry", fake_record_ledger_entry)
    monkeypatch.setattr(storage_mod, "upload_bytes", fake_upload_bytes)
    monkeypatch.setattr(clip_dialogue_mod, "duck_audio", fake_duck_audio)
    monkeypatch.setattr(clip_dialogue_mod, "fetch_all", fake_fetch_all)
    # LAW 3's tone lookup fires unconditionally now — keep it a clean no-op
    # here so these tests stay about LAW 1/2, not tone plumbing (covered
    # separately below).
    monkeypatch.setattr(channel_format, "get_channel_tone", AsyncMock(return_value=None))

    image_client = _CapturingImageClient()
    executor = PipelineExecutor.__new__(PipelineExecutor)
    executor.tenant_id = TENANT
    executor._initialized = True  # skip vault/env loading in _ensure_initialized
    executor._pipeline = _FakeLightPipeline(image_client)

    result = asyncio.run(executor.run_clip_generation(VIDEO, asset_id="asset-1"))
    assert result["status"] == "completed", result
    return image_client, model_used_updates, clip_url_updates


def test_coverage_reaction_row_with_embedded_quoted_line_stays_non_speaking(monkeypatch):
    """LAW 1 root-cause regression: a coverage reaction card whose
    sentence_text embeds the SPEAKER's full quoted line (the real beat-label
    shape from prod) must NOT be promoted to speaking just because
    match_lines would substring-match it. It keeps its own motion prompt
    (LAW 1) and picks up the mouths-shut clause (LAW 2) instead of the
    generic speaking_prompt() template."""
    image_client, model_used_updates, _ = _run_clip_generation_for_row(
        monkeypatch, _reactor_row(generation_method="coverage"))

    assert len(image_client.calls) == 1
    engine, prompt = image_client.calls[0]
    assert engine == "grok"
    # LAW 1: own motion prompt preserved verbatim, never discarded.
    assert REACTOR_MOTION_PROMPT in prompt
    # LAW 1: never promoted to the generic speaking template.
    assert "speaks with clear natural mouth movement" not in prompt
    # LAW 2: explicit mouths-shut clause present on the non-speaking clip.
    assert NO_SPEECH_CLAUSE in prompt
    assert model_used_updates[0] == ("grok-imagine", "asset-1")


def test_legacy_noncoverage_card_keeps_match_lines_promotion(monkeypatch):
    """The existing substring-match path is preserved for LEGACY (non-
    coverage) cards — LAW 1 only changes behavior for generation_method=
    'coverage' rows, per the comment already in clip_dialogue.match_lines."""
    row = _reactor_row(generation_method=None)
    image_client, _, _ = _run_clip_generation_for_row(monkeypatch, row)

    assert len(image_client.calls) == 1
    engine, prompt = image_client.calls[0]
    assert engine == "grok"
    # A legacy card DOES get promoted to speaking via match_lines' substring
    # match against sentence_text — unchanged pre-existing behavior.
    assert "speaks with clear natural mouth movement" in prompt
    assert NO_SPEECH_CLAUSE not in prompt  # LAW 2 never leaks into speaking


# ===========================================================================
# LAW 2 (unit-level) — the clause lives on the non-speaking side only.
# ===========================================================================

def test_no_speech_clause_absent_from_speaking_prompt_template():
    out = speaking_prompt([{"speaker": "Tom", "text": "Hello there."}])
    assert NO_SPEECH_CLAUSE not in out


# ===========================================================================
# LAW 3a — clip_dialogue.speaking_prompt(): tone appears only when given;
# byte-identical to the pre-LAW-3 template when absent.
# ===========================================================================

_LINES = [{"speaker": "Tom", "text": "Hello there."}]


def test_speaking_prompt_no_tone_is_byte_identical_to_legacy_template():
    out = speaking_prompt(_LINES)
    expected = (
        'Tom speaks with clear natural mouth movement, saying: "Hello there.". '
        "The character starts speaking right away. Expressive face, "
        "natural small gestures; other characters react subtly but do not talk. "
        "Keep the characters, art style and scene exactly as shown in the image. "
        + OFF_SCREEN_SPEAKER_RULE
    )
    assert out == expected


def test_speaking_prompt_with_tone_adds_delivery_clause():
    out = speaking_prompt(_LINES, tone="playful and comedic")
    assert "in a playful and comedic tone" in out
    assert 'Tom speaks with clear natural mouth movement, saying: "Hello there."' in out


# ===========================================================================
# LAW 3b — channel_format.get_channel_tone(): reads voice_tone, no-ops when
# absent, fails soft (never invents a tone, never raises) on a DB error.
# ===========================================================================

def test_get_channel_tone_returns_voice_tone_when_present(monkeypatch):
    async def fake_fetch_one(query, *args):
        return {"channel_identity": {"voice_tone": "deadpan analyst"}}
    monkeypatch.setattr(channel_format, "fetch_one", fake_fetch_one)
    tone = asyncio.run(channel_format.get_channel_tone("tenant-x"))
    assert tone == "deadpan analyst"


def test_get_channel_tone_no_op_when_absent(monkeypatch):
    async def fake_fetch_one(query, *args):
        # Real shape for the PocoAPoco tenant today (checked live 2026-07-22):
        # format_locked/visual_format/thumbnail_blueprint, no voice_tone yet.
        return {"channel_identity": {"format_locked": True,
                                      "visual_format": {"style": "3D cartoon"}}}
    monkeypatch.setattr(channel_format, "fetch_one", fake_fetch_one)
    tone = asyncio.run(channel_format.get_channel_tone("tenant-x"))
    assert tone is None


def test_get_channel_tone_fails_soft_on_db_error(monkeypatch):
    async def fake_fetch_one(query, *args):
        raise RuntimeError("DATABASE_URL not set")
    monkeypatch.setattr(channel_format, "fetch_one", fake_fetch_one)
    tone = asyncio.run(channel_format.get_channel_tone("tenant-x"))
    assert tone is None

# LAW 3c (scripts/coverage_to_app.py::_write_motion_prompts' user-message
# wiring) lives in its own file, test_dialogue_guard_law3_motion_writer.py —
# it needs sys.modules stubs for database/storage/vault/kie_unified (same as
# tests/functional/test_motion_prompt_presence_gate.py), and this file's
# conftest-level per-file isolation means a module-level stub here would
# leak into the real-`vault`-dependent run_clip_generation tests above.
