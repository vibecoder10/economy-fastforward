"""Money-safety fix (chunk C56 — closing the remaining spend-cap holes after
the C55 character/environment fix, docs/failure-modes.md and
tasks/decisions.md 2026-07-27 "SFX entry" have the fuller history).

Six real, LIVE paid-generation call sites spent money with no
generation_ledger write and, where a live per-video cap check made sense, no
budget_refusal call either — so videos.max_spend (which budget_check() reads
straight off videos.total_cost, the generation_ledger rollup) could never
stop them:

  1. pipeline_executor.py::run_dialogue_voice ->
     dialogue_voice.py::synthesize_video_segments — real per-segment
     ElevenLabs synthesis (character-dialogue voice track), reachable from
     routes/pipeline.py, the MCP redo_dialogue_scene_voice tool, and
     automatically during Animate.
  2. custom_film_production_runner.py::SharedSectionProductionSeams._voice —
     real ElevenLabs synthesis for a Custom Film section's narration track.
     Metered ONLY (no new incremental cap check): Custom Film already gates
     its ENTIRE film's quoted cost against videos.max_spend up front, before
     scheduling any section (custom_film_runtime.compile_runtime_plan /
     custom_film_contract.py's approval-time budget_check) — a second,
     per-line refusal here would be a second cap mechanism for this
     subsystem, not a reuse of the existing one.
  3. static_docu.py::generate_static_images_for_video — real GPT Image 2
     calls (up to 2 per view: the base render plus an optional QA retry),
     the live image path for render_mode='static_docu'.
  4. pipeline_executor.py::run_upscale_panels — real Nano Banana 2 calls,
     one per un-upscaled panel (can be dozens per video).
  5. pipeline_executor.py::run_fix_text_card — one real GPT Image 2 call
     per "Fix text" tap.

Also closes two CURRENTLY UNREACHABLE duplicates of the same spend (meter
them anyway so a future caller can't spend silently):
  6. extraction.py::extract_grid's nested _upscale_one (both call sites in
     pipeline_executor.py pass no image_client, so this never fires today).
  7. scripts/coverage_to_app.py::redo_characters (CLI-only, not reachable
     from the app).

routes/visual_styles.py::generate_character (the 6th item in the original
audit list) is NOT fixed here: it is project/style-scoped with no video_id
anywhere in its call chain, and generation_ledger.video_id is NOT NULL — the
same structural gap the audit explicitly flagged as "do not fix, no schema
change" for routes/projects.py::generate_channel_cast_member. See the C56
report for the full reasoning; no test for it here (there is nothing to
assert against — no video-scoped state exists to check).

Style: real modules imported directly, DB/network boundaries monkeypatched —
same convention as test_money_safety_character_environment_metering.py
(the C55 predecessor this file complements) and
tests/functional/test_c36_budget_cap.py.

Run: cd storyengine/backend && ./venv/bin/python -m pytest \
    tests/functional/test_money_safety_gaps_c56.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import actions  # noqa: E402
import dialogue_voice  # noqa: E402
import extraction  # noqa: E402
import generation_ledger as ledger_mod  # noqa: E402
import pipeline_executor as pe_mod  # noqa: E402
import static_docu  # noqa: E402
from pipeline_executor import PipelineExecutor  # noqa: E402

TENANT = "tenant-c56"
VIDEO = "video-c56"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# =============================================================================
# 0. actions.budget_refusal — the shared helper every fix below relies on.
#    Same video_summary + budget_check pair as routes/characters.py's
#    _budget_refusal (the C55 pattern), just packaged for non-route callers.
# =============================================================================

def test_budget_refusal_none_when_no_cap_set(monkeypatch):
    async def fake_summary(tenant_id, video_id):
        return {"total_cost": 5.0, "max_spend": None}
    monkeypatch.setattr(actions, "video_summary", fake_summary)
    assert _run(actions.budget_refusal(TENANT, VIDEO, 1.0)) is None


def test_budget_refusal_none_when_quote_fits_under_cap(monkeypatch):
    async def fake_summary(tenant_id, video_id):
        return {"total_cost": 1.0, "max_spend": 5.0}
    monkeypatch.setattr(actions, "video_summary", fake_summary)
    assert _run(actions.budget_refusal(TENANT, VIDEO, 1.0)) is None


def test_budget_refusal_message_when_over_cap(monkeypatch):
    async def fake_summary(tenant_id, video_id):
        return {"total_cost": 4.5, "max_spend": 5.0}
    monkeypatch.setattr(actions, "video_summary", fake_summary)
    msg = _run(actions.budget_refusal(TENANT, VIDEO, 1.0, "this thing"))
    assert msg is not None
    assert "cap" in msg.lower()
    assert "this thing" in msg


# =============================================================================
# 1. dialogue_voice.synthesize_video_segments — ledger write per segment,
#    hard refusal before any spend once the cap would be crossed.
# =============================================================================

class _FakeTTS:
    def __init__(self, audio=b"fake-mp3"):
        self.audio = audio
        self.calls = []

    async def generate_voice(self, text, voice_id=None, **settings):
        self.calls.append((text, voice_id))
        return {"audio_content": self.audio}


def _dialogue_env(monkeypatch, segments, *, cast_voices=None):
    scripts_row = {
        "id": "script-1", "scene": 1, "voice_id": "narrator-voice",
        "dialogue_segments": segments,
    }

    async def fake_fetch_all(query, *a):
        if "FROM video_characters" in query:
            return [{"name": n, "voice_name": v} for n, v in (cast_voices or {}).items()]
        if "FROM scripts" in query:
            return [dict(scripts_row)]
        return []

    execute_calls = []

    async def fake_execute(query, *a):
        execute_calls.append((query, a))
        return "UPDATE 1"

    async def fake_upload_bytes(data, path, mime):
        return f"https://storage.example/{path}"

    monkeypatch.setattr(dialogue_voice, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(dialogue_voice, "execute", fake_execute)
    monkeypatch.setattr(dialogue_voice, "upload_bytes", fake_upload_bytes)
    return execute_calls


def test_dialogue_voice_writes_ledger_row_per_segment(monkeypatch):
    """Money-safety proof #1: real ElevenLabs spend for a dialogue segment
    must land in generation_ledger — this stage had NO ledger write at all
    before the fix (docs/failure-modes.md's confirmed live $1.50 silent-audio
    billing)."""
    segments = [
        {"type": "narration", "text": "Once upon a time.", "speaker": ""},
        {"type": "dialogue", "text": "Hello there!", "speaker": "Ana"},
    ]
    _dialogue_env(monkeypatch, segments, cast_voices={"ana": "voice-ana"})

    async def fake_budget_refusal(tenant_id, video_id, quote, label="this generation"):
        return None
    monkeypatch.setattr(actions, "budget_refusal", fake_budget_refusal)

    ledger_calls = []

    async def fake_record_ledger_entry(**kwargs):
        ledger_calls.append(kwargs)
    monkeypatch.setattr(ledger_mod, "record_ledger_entry", fake_record_ledger_entry)

    tts = _FakeTTS()
    result = _run(dialogue_voice.synthesize_video_segments(VIDEO, TENANT, tts=tts))

    assert result["segments_voiced"] == 2
    assert len(tts.calls) == 2, "both real segments must have been synthesized"
    assert len(ledger_calls) == 2, "one ledger row per real segment synthesized"
    for row, (text, _voice) in zip(ledger_calls, tts.calls):
        assert row["tenant_id"] == TENANT
        assert row["video_id"] == VIDEO
        assert row["stage"] == "dialogue_voice"
        assert row["model"] == "elevenlabs"
        assert row["units"] == len(text)
        expected_cost = round(len(text) / 1000 * actions.VOICE_PRICE_PER_1K_CHARS, 2)
        assert row["actual_cost"] == expected_cost


def test_dialogue_voice_refused_before_any_spend_when_over_cap(monkeypatch):
    """Money-safety proof #1b: once the cap would be crossed, the loop stops
    BEFORE the paid call — never a warning that gets logged and ignored."""
    segments = [
        {"type": "narration", "text": "First line.", "speaker": ""},
        {"type": "narration", "text": "Second line, never reached.", "speaker": ""},
    ]
    _dialogue_env(monkeypatch, segments)

    async def fake_budget_refusal(tenant_id, video_id, quote, label="this generation"):
        return f"Paused — over the ${5.0:.2f} cap."
    monkeypatch.setattr(actions, "budget_refusal", fake_budget_refusal)

    ledger_calls = []

    async def fake_record_ledger_entry(**kwargs):
        ledger_calls.append(kwargs)
    monkeypatch.setattr(ledger_mod, "record_ledger_entry", fake_record_ledger_entry)

    tts = _FakeTTS()
    result = _run(dialogue_voice.synthesize_video_segments(VIDEO, TENANT, tts=tts))

    assert not tts.calls, "the paid ElevenLabs call must never fire once refused"
    assert not ledger_calls, "no spend happened, so no ledger row may be written"
    assert result["segments_voiced"] == 0
    assert result["budget_stopped"] is True


# =============================================================================
# 2. custom_film_production_runner.SharedSectionProductionSeams._voice —
#    ledger write (metered ONLY — see module docstring for why no new cap
#    check was added here).
# =============================================================================

def test_custom_film_voice_writes_ledger_row(monkeypatch):
    import custom_film_production_runner as production
    import custom_film_provider_operations as operations  # noqa: F401
    from test_custom_film_production_runner import _adapter, _Pool, _AsyncContext  # noqa: E402

    request = production._request(
        _adapter("voice", seconds=12),
        ("scene-1",),
        "custom-film-op:" + "a" * 64,
    )
    seams = production.SharedSectionProductionSeams("tenant-cf")

    async def rows(_request):
        return [{
            "id": "scene-1", "scene": 1, "scene_text": "Narrator line for the ledger test.",
            "voice_id": "voice-1", "voice_status": None, "voice_over_url": None,
        }]

    class Voice:
        async def generate_and_wait(self, text, voice_id=None, task_id_callback=None):
            if task_id_callback:
                await task_id_callback("kie-task-x")
            return "/tmp/fake.mp3"

        async def download_audio(self, path):
            return b"fake-audio"

    class Google:
        def get_or_create_folder(self, name):
            return {"id": "folder-1"}

        def search_file(self, filename, folder_id):
            return None

        def upload_audio(self, content, filename, folder_id):
            return {"id": "drive-audio-1"}

    class Executor:
        def __init__(self):
            self._pipeline = SimpleNamespace(elevenlabs=Voice(), google=Google())

        async def _ensure_initialized(self):
            return None

    class Connection:
        async def execute(self, sql, *args):
            return "UPDATE 1"

    async def get_pool():
        return _Pool(Connection())

    monkeypatch.setattr(seams, "_scene_rows", rows)
    seams._executor = Executor()
    monkeypatch.setattr("database.get_pool", get_pool)

    ledger_calls = []

    async def fake_record_ledger_entry(**kwargs):
        ledger_calls.append(kwargs)
    monkeypatch.setattr(ledger_mod, "record_ledger_entry", fake_record_ledger_entry)

    result = _run(seams._voice(request))

    assert result["voiced_scene_ids"] == ["scene-1"]
    assert len(ledger_calls) == 1, "Custom Film section voice must write exactly one ledger row"
    row = ledger_calls[0]
    assert row["tenant_id"] == "tenant-cf"
    assert row["video_id"] == "video-1"
    assert row["stage"] == "voice"
    assert row["model"] == "elevenlabs"
    text_len = len("Narrator line for the ledger test.")
    assert row["units"] == text_len
    expected_cost = round(text_len / 1000 * actions.VOICE_PRICE_PER_1K_CHARS, 2)
    assert row["actual_cost"] == expected_cost


# =============================================================================
# 3. static_docu.generate_static_images_for_video — ledger write per real
#    GPT Image 2 call (including the QA-retry's SECOND call), refused before
#    any provider call once the cap would be crossed.
# =============================================================================

# Reuse the qa_park suite's rich scaffold (cached reference, one scene, one
# view — isolates the per-view money question from the reference-lookup and
# QA-orchestration logic those tests already cover).
import shared.clients.image_client as image_client_mod  # noqa: E402
from test_static_docu_qa_park import _pipeline_env, RENDER_1, RENDER_2, DURABLE  # noqa: E402


def test_static_docu_writes_ledger_row_on_qa_pass(monkeypatch):
    env = _pipeline_env(monkeypatch, verdicts=[True], gen_urls=[RENDER_1],
                        docu_module=static_docu, image_client_module=image_client_mod)

    async def fake_budget_refusal(tenant_id, video_id, quote, label="this generation"):
        return None
    monkeypatch.setattr(actions, "budget_refusal", fake_budget_refusal)

    ledger_calls = []

    async def fake_record_ledger_entry(**kwargs):
        ledger_calls.append(kwargs)
    monkeypatch.setattr(ledger_mod, "record_ledger_entry", fake_record_ledger_entry)

    result = _run(static_docu.generate_static_images_for_video(env["video_id"], env["tenant_id"]))

    assert result["status"] == "completed"
    assert len(ledger_calls) == 1, "one real GPT Image 2 call -> one ledger row"
    row = ledger_calls[0]
    assert row["tenant_id"] == env["tenant_id"]
    assert row["video_id"] == env["video_id"]
    assert row["stage"] == "image"
    assert row["model"] == "gpt-image-2"
    assert row["unit_cost"] == actions.picture_price_for("gpt-image-2") == 0.05
    assert row["actual_cost"] == 0.05


def test_static_docu_qa_retry_writes_two_ledger_rows(monkeypatch):
    """The QA-triggered retry is a SECOND real generation call — it must be
    metered too, not just the first."""
    env = _pipeline_env(monkeypatch, verdicts=[False, True], gen_urls=[RENDER_1, RENDER_2],
                        docu_module=static_docu, image_client_module=image_client_mod)

    async def fake_budget_refusal(tenant_id, video_id, quote, label="this generation"):
        return None
    monkeypatch.setattr(actions, "budget_refusal", fake_budget_refusal)

    ledger_calls = []

    async def fake_record_ledger_entry(**kwargs):
        ledger_calls.append(kwargs)
    monkeypatch.setattr(ledger_mod, "record_ledger_entry", fake_record_ledger_entry)

    result = _run(static_docu.generate_static_images_for_video(env["video_id"], env["tenant_id"]))

    assert result["status"] == "completed"
    assert len(ledger_calls) == 2, "base render + QA retry are both real spend"
    assert all(r["stage"] == "image" and r["model"] == "gpt-image-2" for r in ledger_calls)


def test_static_docu_refused_before_first_call_when_over_cap(monkeypatch):
    """Money-safety proof: the FIRST GPT Image 2 call for a view must never
    fire once the cap would be exceeded — no image call, no ledger row."""
    env = _pipeline_env(monkeypatch, verdicts=[True], gen_urls=[RENDER_1],
                        docu_module=static_docu, image_client_module=image_client_mod)

    async def fake_budget_refusal(tenant_id, video_id, quote, label="this generation"):
        return "Paused — over the cap."
    monkeypatch.setattr(actions, "budget_refusal", fake_budget_refusal)

    ledger_calls = []

    async def fake_record_ledger_entry(**kwargs):
        ledger_calls.append(kwargs)
    monkeypatch.setattr(ledger_mod, "record_ledger_entry", fake_record_ledger_entry)

    result = _run(static_docu.generate_static_images_for_video(env["video_id"], env["tenant_id"]))

    assert result["status"] == "failed"
    assert env["gen_prompts"] == [], "the paid GPT Image 2 call must never fire once refused"
    assert not ledger_calls, "no spend happened, so no ledger row may be written"


def test_static_docu_refuses_retry_call_only_after_first_generation_billed(monkeypatch):
    """Cap crosses exactly between the base render and its QA retry: the
    first call (real spend) is ledgered, the second (refused) never fires."""
    env = _pipeline_env(monkeypatch, verdicts=[False], gen_urls=[RENDER_1, RENDER_2],
                        docu_module=static_docu, image_client_module=image_client_mod)

    calls = {"n": 0}

    async def fake_budget_refusal(tenant_id, video_id, quote, label="this generation"):
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # base render still fits under the cap
        return "Paused — the base render pushed you over the cap."
    monkeypatch.setattr(actions, "budget_refusal", fake_budget_refusal)

    ledger_calls = []

    async def fake_record_ledger_entry(**kwargs):
        ledger_calls.append(kwargs)
    monkeypatch.setattr(ledger_mod, "record_ledger_entry", fake_record_ledger_entry)

    result = _run(static_docu.generate_static_images_for_video(env["video_id"], env["tenant_id"]))

    assert result["status"] == "failed"
    assert env["gen_prompts"] == [
        # Only the base render's prompt was ever sent — the retry's
        # "Reproduce the machine..." prompt must never appear.
        env["gen_prompts"][0],
    ]
    assert not any("Reproduce the machine" in p for p in env["gen_prompts"])
    assert len(ledger_calls) == 1, "only the base render actually spent money"


# =============================================================================
# 4 + 5. pipeline_executor.run_upscale_panels / run_fix_text_card — ledger
#    write, hard refusal before any spend once the cap would be exceeded.
# =============================================================================

def _make_executor(monkeypatch, *, fetch_one_by_query=None, fetch_all_result=None):
    ledger_calls = []

    async def fake_execute(query, *a):
        return "OK"

    async def fake_fetch_one(query, *a):
        for needle, row in (fetch_one_by_query or {}).items():
            if needle in query:
                return row
        return None

    async def fake_fetch_all(query, *a):
        return fetch_all_result or []

    async def fake_upload_from_url(url, path, tenant_id=None):
        return f"https://storage.example/{path}"

    async def fake_record_ledger_entry(**kwargs):
        ledger_calls.append(kwargs)

    monkeypatch.setattr(pe_mod, "execute", fake_execute)
    monkeypatch.setattr(pe_mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pe_mod, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(pe_mod, "upload_from_url", fake_upload_from_url)
    monkeypatch.setattr(pe_mod, "record_ledger_entry", fake_record_ledger_entry)

    executor = PipelineExecutor.__new__(PipelineExecutor)
    executor.tenant_id = TENANT
    executor._initialized = True

    async def fake_log_activity(*a, **kw):
        return None
    executor._log_activity = fake_log_activity
    return executor, ledger_calls


def test_run_upscale_panels_writes_ledger_row_per_panel(monkeypatch):
    panels = [
        {"id": "asset-1", "scene": 1, "image_index": 1, "image_url": "https://x/p1.png"},
        {"id": "asset-2", "scene": 1, "image_index": 2, "image_url": "https://x/p2.png"},
    ]
    executor, ledger_calls = _make_executor(monkeypatch, fetch_all_result=panels)

    async def fake_budget_refusal(tenant_id, video_id, quote, label="this generation"):
        return None
    monkeypatch.setattr(actions, "budget_refusal", fake_budget_refusal)

    calls = []

    class FakeImageClient:
        async def generate_scene_image(self, prompt, reference_image_url):
            calls.append(reference_image_url)
            return {"url": "https://kie.example/upscaled.png"}

    executor._pipeline = SimpleNamespace(image_client=FakeImageClient())

    result = _run(executor.run_upscale_panels(VIDEO))

    assert result["upscaled"] == 2
    assert len(calls) == 2
    assert len(ledger_calls) == 2
    for row in ledger_calls:
        assert row["tenant_id"] == TENANT
        assert row["video_id"] == VIDEO
        assert row["stage"] == "image"
        assert row["model"] == "nano-banana-2"
        assert row["unit_cost"] == actions.picture_price_for("nano-banana-2") == 0.04
        assert row["actual_cost"] == 0.04


def test_run_upscale_panels_refused_before_any_spend_when_over_cap(monkeypatch):
    panels = [
        {"id": "asset-1", "scene": 1, "image_index": 1, "image_url": "https://x/p1.png"},
    ]
    executor, ledger_calls = _make_executor(monkeypatch, fetch_all_result=panels)

    async def fake_budget_refusal(tenant_id, video_id, quote, label="this generation"):
        return "Paused — over the cap."
    monkeypatch.setattr(actions, "budget_refusal", fake_budget_refusal)

    calls = []

    class FakeImageClient:
        async def generate_scene_image(self, prompt, reference_image_url):
            calls.append(reference_image_url)
            return {"url": "https://kie.example/upscaled.png"}

    executor._pipeline = SimpleNamespace(image_client=FakeImageClient())

    result = _run(executor.run_upscale_panels(VIDEO))

    assert result["upscaled"] == 0
    assert result.get("budget_stopped") is True
    assert not calls, "the paid Nano Banana 2 call must never fire once refused"
    assert not ledger_calls, "no spend happened, so no ledger row may be written"


def test_run_fix_text_card_writes_ledger_row(monkeypatch):
    asset_row = {
        "scene": 3, "image_index": 2, "image_prompt": "a card", "sentence_text": "Hello",
        "image_url": "https://x/card.png", "drive_image_url": "https://x/card.png",
    }
    video_row = {"aspect_ratio": "16:9", "image_style_override": ""}
    executor, ledger_calls = _make_executor(
        monkeypatch,
        fetch_one_by_query={"FROM assets": asset_row, "FROM videos": video_row},
    )

    async def fake_budget_refusal(tenant_id, video_id, quote, label="this generation"):
        return None
    monkeypatch.setattr(actions, "budget_refusal", fake_budget_refusal)

    calls = []

    class FakeImageClient:
        async def generate_thumbnail_gpt2(self, prompt, refs, aspect_ratio="16:9"):
            calls.append((prompt, refs))
            return {"url": "https://kie.example/fixed.png"}

    executor._pipeline = SimpleNamespace(image_client=FakeImageClient())

    result = _run(executor.run_fix_text_card(VIDEO, "asset-1"))

    assert result["status"] == "completed"
    assert len(calls) == 1, "the paid GPT Image 2 redraw must fire exactly once"
    assert len(ledger_calls) == 1
    row = ledger_calls[0]
    assert row["tenant_id"] == TENANT
    assert row["video_id"] == VIDEO
    assert row["stage"] == "image"
    assert row["model"] == "gpt-image-2"
    assert row["unit_cost"] == actions.picture_price_for("gpt-image-2") == 0.05
    assert row["actual_cost"] == 0.05


def test_run_fix_text_card_refused_before_any_spend_when_over_cap(monkeypatch):
    asset_row = {
        "scene": 3, "image_index": 2, "image_prompt": "a card", "sentence_text": "Hello",
        "image_url": "https://x/card.png", "drive_image_url": "https://x/card.png",
    }
    video_row = {"aspect_ratio": "16:9", "image_style_override": ""}
    executor, ledger_calls = _make_executor(
        monkeypatch,
        fetch_one_by_query={"FROM assets": asset_row, "FROM videos": video_row},
    )

    async def fake_budget_refusal(tenant_id, video_id, quote, label="this generation"):
        return "Paused — over the cap."
    monkeypatch.setattr(actions, "budget_refusal", fake_budget_refusal)

    calls = []

    class FakeImageClient:
        async def generate_thumbnail_gpt2(self, prompt, refs, aspect_ratio="16:9"):
            calls.append((prompt, refs))
            return {"url": "https://kie.example/fixed.png"}

    executor._pipeline = SimpleNamespace(image_client=FakeImageClient())

    result = _run(executor.run_fix_text_card(VIDEO, "asset-1"))

    assert result["status"] == "completed"
    assert "cap" in (result.get("message") or "").lower()
    assert not calls, "the paid GPT Image 2 call must never fire once refused"
    assert not ledger_calls, "no spend happened, so no ledger row may be written"


# =============================================================================
# 6. extraction.py::extract_grid's _upscale_one — currently unreachable (no
#    live caller passes image_client), but must not spend silently once a
#    future caller does. Call extract_grid DIRECTLY with a fake image_client
#    to exercise the dead path.
# =============================================================================

def test_extract_grid_upscale_writes_ledger_row_when_client_and_tenant_given(monkeypatch):
    from PIL import Image
    import io as _io

    img = Image.new("RGB", (300, 300), color=(10, 20, 30))
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    async def fake_download_bytes(url):
        return png_bytes

    async def fake_upload_bytes(data, path):
        return f"https://storage.example/{path}"

    async def fake_upload_from_url(url, path):
        return f"https://storage.example/{path}"

    monkeypatch.setattr(extraction, "download_bytes", fake_download_bytes)
    monkeypatch.setattr(extraction, "upload_bytes", fake_upload_bytes)
    monkeypatch.setattr(extraction, "upload_from_url", fake_upload_from_url)

    async def fake_budget_refusal(tenant_id, video_id, quote, label="this generation"):
        return None
    monkeypatch.setattr(actions, "budget_refusal", fake_budget_refusal)

    ledger_calls = []

    async def fake_record_ledger_entry(**kwargs):
        ledger_calls.append(kwargs)
    monkeypatch.setattr(ledger_mod, "record_ledger_entry", fake_record_ledger_entry)

    calls = []

    class FakeImageClient:
        async def generate_scene_image(self, prompt, reference_image_url):
            calls.append(reference_image_url)
            return {"url": "https://kie.example/upscaled-panel.png"}

    result = _run(extraction.extract_grid(
        "https://x/grid.png", VIDEO, 1, 1, 0,
        image_client=FakeImageClient(), rows=1, cols=1, expected_panels=1,
        tenant_id=TENANT,
    ))

    assert len(calls) == 1, "the single panel must have been upscaled"
    assert len(ledger_calls) == 1
    row = ledger_calls[0]
    assert row["tenant_id"] == TENANT
    assert row["video_id"] == VIDEO
    assert row["stage"] == "image"
    assert row["model"] == "nano-banana-2"
    assert row["unit_cost"] == actions.picture_price_for("nano-banana-2") == 0.04


def test_extract_grid_upscale_refused_before_any_spend_when_over_cap(monkeypatch):
    from PIL import Image
    import io as _io

    img = Image.new("RGB", (300, 300), color=(10, 20, 30))
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    async def fake_download_bytes(url):
        return png_bytes

    async def fake_upload_bytes(data, path):
        return f"https://storage.example/{path}"

    monkeypatch.setattr(extraction, "download_bytes", fake_download_bytes)
    monkeypatch.setattr(extraction, "upload_bytes", fake_upload_bytes)

    async def fake_budget_refusal(tenant_id, video_id, quote, label="this generation"):
        return "Paused — over the cap."
    monkeypatch.setattr(actions, "budget_refusal", fake_budget_refusal)

    ledger_calls = []

    async def fake_record_ledger_entry(**kwargs):
        ledger_calls.append(kwargs)
    monkeypatch.setattr(ledger_mod, "record_ledger_entry", fake_record_ledger_entry)

    calls = []

    class FakeImageClient:
        async def generate_scene_image(self, prompt, reference_image_url):
            calls.append(reference_image_url)
            return {"url": "https://kie.example/upscaled-panel.png"}

    result = _run(extraction.extract_grid(
        "https://x/grid.png", VIDEO, 1, 1, 0,
        image_client=FakeImageClient(), rows=1, cols=1, expected_panels=1,
        tenant_id=TENANT,
    ))

    assert not calls, "the paid Nano Banana 2 call must never fire once refused"
    assert not ledger_calls, "no spend happened, so no ledger row may be written"
    # The original crop is kept (panel_result returned unchanged) rather than
    # silently dropped.
    assert len(result) == 1
    assert result[0]["panel_url"].startswith("https://storage.example/")


# =============================================================================
# 7. scripts/coverage_to_app.py::redo_characters — CLI-only, not reachable
#    from the app today, but a duplicate of a feature (character-sheet
#    generation) that IS metered elsewhere. Meter it the same way.
# =============================================================================

def test_redo_characters_writes_ledger_row_and_refuses_over_cap(monkeypatch):
    sys.path.insert(0, os.path.join(_BACKEND, "scripts"))
    import coverage_to_app as cta

    rows = [{"id": "char-1", "name": "Rex", "description": "a red robot with a very long, "
             "detailed, precise photoreal description well past two hundred characters so the "
             "tightening branch is skipped entirely for this deterministic test case, padding it "
             "with extra descriptive words about its chrome plating, glowing optics, articulated "
             "limbs, and worn paint to comfortably clear the two-hundred-character threshold."}]

    async def fake_fetch_all(query, *a):
        return rows

    async def fake_fetch_one(query, *a):
        return {"image_model_override": None}

    execute_calls = []

    async def fake_execute(query, *a):
        execute_calls.append((query, a))
        return "OK"

    monkeypatch.setattr(cta, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(cta, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(cta, "execute", fake_execute)

    async def fake_stable_url(url, path, tenant):
        return f"https://storage.example/{path}"
    monkeypatch.setattr(cta, "_stable_url", fake_stable_url)

    gen_calls = []

    async def fake_generate_for_model(ic, model_override, prompt, aspect_ratio="16:9"):
        gen_calls.append(prompt)
        return "https://kie.example/sheet.png", "gpt-image-2"
    monkeypatch.setattr(cta, "generate_scene_image_for_model", fake_generate_for_model)

    ledger_calls = []

    async def fake_record_ledger_entry(**kwargs):
        ledger_calls.append(kwargs)
    # coverage_to_app.py imports record_ledger_entry at module load time
    # (`from generation_ledger import record_ledger_entry`), so it must be
    # patched on cta's own namespace, not generation_ledger's.
    monkeypatch.setattr(cta, "record_ledger_entry", fake_record_ledger_entry)

    # Happy path: no cap set.
    async def fake_budget_refusal_none(tenant_id, video_id, quote, label="this generation"):
        return None
    monkeypatch.setattr(actions, "budget_refusal", fake_budget_refusal_none)

    n = _run(cta.redo_characters(VIDEO, TENANT, claude=None, claude_model=None,
                                 ic=object(), script_text="story"))
    assert n == 1
    assert len(gen_calls) == 1
    assert len(ledger_calls) == 1
    row = ledger_calls[0]
    assert row["tenant_id"] == TENANT
    assert row["video_id"] == VIDEO
    assert row["stage"] == "character_sheet"
    assert row["model"] == "gpt-image-2"
    assert row["unit_cost"] == actions.picture_price_for("gpt-image-2") == 0.05

    # Refusal path: over cap -> no generation call, no ledger row.
    gen_calls.clear()
    ledger_calls.clear()

    async def fake_budget_refusal_over(tenant_id, video_id, quote, label="this generation"):
        return "Paused — over the cap."
    monkeypatch.setattr(actions, "budget_refusal", fake_budget_refusal_over)

    n2 = _run(cta.redo_characters(VIDEO, TENANT, claude=None, claude_model=None,
                                  ic=object(), script_text="story"))
    assert n2 == 0
    assert not gen_calls, "the paid image call must never fire once refused"
    assert not ledger_calls, "no spend happened, so no ledger row may be written"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
