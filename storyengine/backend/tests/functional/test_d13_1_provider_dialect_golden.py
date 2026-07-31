"""D13-1 golden tests: provider-dialect adapter (backend/provider_dialect.py).

WHY this file exists: a July audit found that swapping which video-clip
engine a shot uses required touching CREATIVE code — pipeline_executor.py's
``_animate_for``/``_decorate`` hardcoded Grok's ``@image1``/``@image2``
reference-token syntax straight into shot prompt TEXT, and the Veo branch
bypassed ``_decorate`` entirely, sending a raw prompt through a different
kwarg shape (``image_url=`` instead of a positional image arg, no
``duration``/``extra_image_urls``). D13-1 moves that provider-specific
shaping into ``backend/provider_dialect.py`` — ONE adapter creative code
hands a neutral request to, keyed by model_id.

This is a PURE REFACTOR — zero behavior change. These tests are the proof:
they drive the REAL ``PipelineExecutor.run_clip_generation`` end-to-end
(same harness pattern as tests/functional/test_c13_clip_model_routing.py —
DB/storage/ledger/network all faked, only the shot-composition + dialect
code is real) and capture the EXACT prompt string + kwargs handed to the
fake image client's ``generate_video``/``generate_video_seedance``/
``generate_video_veo`` methods.

The literal expected strings below were captured by running this file
against pipeline_executor.py AS IT EXISTED BEFORE D13-1 (the inline
``_animate_for``/``_decorate``/veo-branch code, not the adapter) — i.e.
they are what "today's code" (pre-D13-1) actually produces, not a
hand-derived guess. After the refactor, this file is re-run UNMODIFIED
against the adapter-backed code and must still pass byte-identical.

Run: cd storyengine/backend && ./venv/bin/python -m pytest \
    tests/functional/test_d13_1_provider_dialect_golden.py -q
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
# These three are the provider-AGNOSTIC "people rule" + no-speech clause —
# not part of the dialect under test — imported for real (not
# hand-transcribed) so the golden fixtures below can't drift from them by a
# copy-paste typo. Only the @image1/@image2 GROK-DIALECT wrapper text is a
# hand-verified literal (captured from a real pre-D13-1 run — see the
# module docstring).
from clip_dialogue import NO_SPEECH_CLAUSE, NO_NEW_PEOPLE_PREFIX, CUTAWAY_PREFIX  # noqa: E402


TENANT = "tenant-golden"
VIDEO = "video-golden"


# ---------------------------------------------------------------------------
# Fakes — same shape/pattern as test_c13_clip_model_routing.py's harness,
# but the image client records the FULL args/kwargs of every provider call
# (not just a (dialect, duration) tuple) so the golden assertions can check
# the exact prompt string and exact kwarg shape.
# ---------------------------------------------------------------------------

class _FakeLightPipeline:
    def __init__(self, image_client):
        self.image_client = image_client
        self.should_cancel = None  # _install_cancel_support overwrites this fail-soft


class _CapturingImageClient:
    VEO_MODEL_QUALITY = "veo-quality-id"
    VEO_MODEL_FAST = "veo-fast-id"

    def __init__(self):
        self.calls = []

    async def generate_video(self, img, prompt, duration=6, extra_image_urls=None,
                              aspect_ratio="16:9", resolution="720p", task_id_out=None):
        self.calls.append({
            "method": "generate_video",
            "image_url": img,
            "prompt": prompt,
            "duration": duration,
            "extra_image_urls": extra_image_urls,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
        })
        if task_id_out is not None:
            task_id_out.append("grok-task-1")
        return "https://fake/grok-clip.mp4"

    async def generate_video_seedance(self, img, prompt, duration=6, extra_image_urls=None,
                                       aspect_ratio="16:9", task_id_out=None):
        self.calls.append({
            "method": "generate_video_seedance",
            "image_url": img,
            "prompt": prompt,
            "duration": duration,
            "extra_image_urls": extra_image_urls,
            "aspect_ratio": aspect_ratio,
        })
        if task_id_out is not None:
            task_id_out.append("seedance-task-1")
        return "https://fake/seedance-clip.mp4"

    async def generate_video_veo(self, prompt, image_url=None, model=None, task_id_out=None):
        self.calls.append({
            "method": "generate_video_veo",
            "prompt": prompt,
            "image_url": image_url,
            "model": model,
        })
        if task_id_out is not None:
            task_id_out.append("veo-task-1")
        return "https://fake/veo-clip.mp4"

    async def download_image(self, url):
        return b"fake-clip-bytes"


def _video_row(video_model, *, character_reference_url=None, image_style_override=None,
               dialogue_mode=None, aspect_ratio="16:9", video_resolution="720p"):
    return {
        "id": VIDEO, "video_model": video_model, "aspect_ratio": aspect_ratio,
        "video_resolution": video_resolution, "dialogue_mode": dialogue_mode,
        "dialogue_audio": "voice_over", "character_reference_url": character_reference_url,
        "image_style_override": image_style_override, "status": "ready_for_video_generation",
    }


def _asset_row(video_prompt, *, image_prompt="a factory floor", sentence_text=None,
               camera_preset_id=None, duration_seconds=4.0):
    return {
        "id": "asset-1", "scene": 1, "image_index": 1,
        "image_url": "https://fake/img1.png", "drive_image_url": None,
        "video_prompt": video_prompt,
        "video_clip_url": None, "duration_seconds": duration_seconds,
        "sentence_text": sentence_text, "image_prompt": image_prompt,
        "assigned_dialogue": None, "routed_model": None, "model_override": None,
        "camera_preset_id": camera_preset_id,
    }


def _drive(monkeypatch, *, video_model, character_reference_url=None,
           image_style_override=None, dialogue_mode=None, video_prompt,
           camera_preset_id=None, cast_rows=None):
    """Drive run_clip_generation for ONE non-speaking (narration) asset row,
    with DB/storage/ledger/network all faked. Returns the _CapturingImageClient
    with its captured call(s)."""
    monkeypatch.setenv("VOICE_SWAP", "off")  # no character-dialogue shot in this
    # file needs a real/faked ElevenLabs key — keep the xi_key lookup a no-op.

    async def fake_fetch_one(query, *args):
        if "FROM videos WHERE id" in query:
            return _video_row(
                video_model, character_reference_url=character_reference_url,
                image_style_override=image_style_override, dialogue_mode=dialogue_mode)
        if "SELECT scene FROM assets WHERE id" in query:
            return {"scene": 1}
        if "COUNT(*) AS pics, COUNT(video_clip_url) AS clips" in query:
            return {"pics": 1, "clips": 0}
        return None

    async def fake_fetch_all(query, *args):
        if "FROM assets WHERE" in query and "routed_model" in query:
            return [_asset_row(video_prompt, camera_preset_id=camera_preset_id)]
        if "FROM video_characters" in query:
            return cast_rows or []
        return []

    async def fake_execute(query, *args):
        return "OK"

    async def fake_record_ledger_entry(**kwargs):
        pass

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

    image_client = _CapturingImageClient()
    executor = PipelineExecutor.__new__(PipelineExecutor)
    executor.tenant_id = TENANT
    executor._initialized = True
    executor._pipeline = _FakeLightPipeline(image_client)

    result = asyncio.run(executor.run_clip_generation(VIDEO, asset_id="asset-1"))
    assert result["status"] == "completed", result
    return image_client


# ---------------------------------------------------------------------------
# GOLDEN CASE 1 — Grok, bare narration shot: no reference sheet, no style
# override, no camera preset. This is the most common shape.
# ---------------------------------------------------------------------------

# The @image1 lead-in is Grok's dialect signature — hand-verified literal,
# captured against pre-D13-1 pipeline_executor._decorate.
GROK_IMAGE1_BASE = (
    "Animate @image1 exactly as shown: same characters, same faces, ages,"
    " heights, proportions and clothing. NEVER introduce a character who"
    " is not visible in @image1 — if someone is off-screen, only hands or"
    " feet may enter the frame."
)

VIDEO_PROMPT = "Wide shot pushes in on the harbor at dawn."

# core = motion_guard prefix + video_prompt + " " + NO_SPEECH_CLAUSE — the
# provider-AGNOSTIC part of the shot (unaffected by which engine animates
# it). image_prompt is "a factory floor" (see _asset_row) and cast_names is
# "" for every case below except the cast-names case, so motion_guard picks
# NO_NEW_PEOPLE_PREFIX here (empty cast_names -> always that branch).
CORE_NO_CAST = f"{NO_NEW_PEOPLE_PREFIX}{VIDEO_PROMPT} {NO_SPEECH_CLAUSE}"

GROK_BARE_PROMPT = f"{GROK_IMAGE1_BASE} Motion: {CORE_NO_CAST}"


def test_grok_bare_narration_prompt_and_kwargs_golden(monkeypatch):
    client = _drive(
        monkeypatch, video_model="grok-imagine",
        video_prompt="Wide shot pushes in on the harbor at dawn.")
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["method"] == "generate_video"
    assert call["prompt"] == GROK_BARE_PROMPT
    assert call["image_url"] == "https://fake/img1.png"
    assert call["extra_image_urls"] is None
    assert call["aspect_ratio"] == "16:9"
    assert call["resolution"] == "720p"
    assert call["duration"] == 6


# ---------------------------------------------------------------------------
# GOLDEN CASE 2 — Grok with a character reference sheet + style override:
# the @image2 clause and the "Art style:" clause both fire.
# ---------------------------------------------------------------------------

# NOTE (pre-existing quirk, preserved byte-for-byte — not this chunk's to
# fix): _decorate appends " Art style: {style_note}" with no trailing
# period, so it runs straight into " Motion: ..." with only a single space.
GROK_SHEET_PROMPT = (
    f"{GROK_IMAGE1_BASE} @image2 is the official cast sheet"
    " — anyone visible in @image1 must match it precisely."
    " Art style: noir, high contrast"
    f" Motion: {CORE_NO_CAST}"
)


def test_grok_reference_sheet_and_style_note_prompt_golden(monkeypatch):
    client = _drive(
        monkeypatch, video_model="grok-imagine",
        character_reference_url="https://fake/sheet.png",
        image_style_override="noir, high contrast",
        video_prompt="Wide shot pushes in on the harbor at dawn.")
    call = client.calls[0]
    assert call["method"] == "generate_video"
    assert call["prompt"] == GROK_SHEET_PROMPT
    assert call["extra_image_urls"] == ["https://fake/sheet.png"]


# ---------------------------------------------------------------------------
# GOLDEN CASE 3 — Grok with a reference sheet AND cast names (the
# parenthetical in the @image2 clause).
# ---------------------------------------------------------------------------

# cast_names = "Tom, Jerry" is truthy AND neither name appears in shot_text
# ("a factory floor") -> motion_guard's has_cast check is False -> it picks
# CUTAWAY_PREFIX, not NO_NEW_PEOPLE_PREFIX (see clip_dialogue.motion_guard's
# docstring: "Cutaway (no cast name anywhere in the shot text) -> absolute
# NO PEOPLE"). Provider-agnostic behavior, imported for real above.
CORE_WITH_CAST = f"{CUTAWAY_PREFIX}{VIDEO_PROMPT} {NO_SPEECH_CLAUSE}"

GROK_SHEET_CAST_PROMPT = (
    f"{GROK_IMAGE1_BASE} @image2 is the official cast sheet (Tom, Jerry)"
    " — anyone visible in @image1 must match it precisely."
    f" Motion: {CORE_WITH_CAST}"
)


def test_grok_reference_sheet_with_cast_names_prompt_golden(monkeypatch):
    client = _drive(
        monkeypatch, video_model="grok-imagine",
        character_reference_url="https://fake/sheet.png",
        dialogue_mode="character_dialogue",
        cast_rows=[{"name": "Tom", "voice_name": "v1"}, {"name": "Jerry", "voice_name": "v2"}],
        video_prompt="Wide shot pushes in on the harbor at dawn.")
    call = client.calls[0]
    assert call["prompt"] == GROK_SHEET_CAST_PROMPT


# ---------------------------------------------------------------------------
# GOLDEN CASE 4 — Veo: RAW (undecorated) prompt, different kwarg shape
# (image_url= kwarg, no duration/extra_image_urls, has model=).
# ---------------------------------------------------------------------------

VEO_RAW_PROMPT = CORE_NO_CAST  # no @image1/@image2 wrapper — this IS the whole point


def test_veo_fast_raw_prompt_and_kwarg_shape_golden(monkeypatch):
    client = _drive(
        monkeypatch, video_model="veo-3.1-fast",
        video_prompt="Wide shot pushes in on the harbor at dawn.")
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["method"] == "generate_video_veo"
    assert call["prompt"] == VEO_RAW_PROMPT, "Veo must NOT get @image1/@image2 decoration"
    assert call["image_url"] == "https://fake/img1.png"
    assert call["model"] == "veo-fast-id"
    assert "duration" not in call and "extra_image_urls" not in call and "resolution" not in call


def test_veo_quality_selects_quality_model_id_golden(monkeypatch):
    client = _drive(
        monkeypatch, video_model="veo-3.1-quality",
        video_prompt="Wide shot pushes in on the harbor at dawn.")
    call = client.calls[0]
    assert call["method"] == "generate_video_veo"
    assert call["model"] == "veo-quality-id"
    assert call["prompt"] == VEO_RAW_PROMPT


# ---------------------------------------------------------------------------
# GOLDEN CASE 5 — Seedance: SAME @imageN decoration as Grok, but a
# different kwarg shape (no `resolution`).
# ---------------------------------------------------------------------------

SEEDANCE_PROMPT = GROK_BARE_PROMPT  # decoration logic is identical to Grok's


def test_seedance_decorated_prompt_and_kwarg_shape_golden(monkeypatch):
    client = _drive(
        monkeypatch, video_model="seedance-2-fast",
        video_prompt="Wide shot pushes in on the harbor at dawn.")
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["method"] == "generate_video_seedance"
    assert call["prompt"] == SEEDANCE_PROMPT
    assert call["extra_image_urls"] is None
    assert call["aspect_ratio"] == "16:9"
    assert "resolution" not in call
