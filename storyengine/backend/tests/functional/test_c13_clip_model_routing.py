"""Tests for C13 (checklist §1.2, tasks/storyengine-wiring-fix-checklist.md):
clip generation READS the per-scene routed model C12 wrote, and records
model_used. C12 only wrote routed_model/routing_reason at shot-plan time —
this is the first behavior change on the PAID clip path, so money
correctness is the whole point.

Two layers:

1. `actions.estimate_cost()` ("animate"/"build" verbs) — the pre-spend quote
   must sum EACH not-yet-clipped row's own resolved model price, not one
   flat video-level price times a count (money invariant #2). Real
   `actions` module, `fetch_all`/`fetch_one` monkeypatched (same pattern as
   tests/functional/test_video_ledger_endpoint.py) — no live DB.

2. `pipeline_executor.PipelineExecutor.run_clip_generation()` — the actual
   generation call. `PipelineExecutor.__new__` skips `__init__`'s vault/env
   loading (same technique as tests/functional/test_prompt_override_wiring.py);
   `_ensure_initialized` is skipped via `_initialized = True`; `database`
   module-level names (`fetch_one`/`fetch_all`/`execute`) and
   `generation_ledger.record_ledger_entry` are monkeypatched on the
   `pipeline_executor` module object itself (they're plain bound names
   imported there via `from database import ...` / `from generation_ledger
   import ...`); `storage.upload_bytes` and `clip_dialogue.duck_audio` are
   monkeypatched on their OWN modules since `run_clip_generation` re-imports
   them locally at call time. A fake `image_client` on a fake `_pipeline`
   captures which generation call (`generate_video` = Grok/default vs.
   `generate_video_veo` = Veo) actually ran.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c13_clip_model_routing.py -q
"""
import asyncio
import os
import sys

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))

import actions  # noqa: E402
from shared.channel_profile import MODEL_REGISTRY  # noqa: E402


# ---------------------------------------------------------------------------
# 1. actions.estimate_cost() — quote must match routed per-scene spend
# ---------------------------------------------------------------------------

TENANT = "tenant-1"
VIDEO = "video-1"

GROK_PRICE = MODEL_REGISTRY["grok-imagine"].cost_per_clip[min(MODEL_REGISTRY["grok-imagine"].cost_per_clip)]
VEO_QUALITY_PRICE = MODEL_REGISTRY["veo-3.1-quality"].cost_per_clip[8]


def _summary(**over):
    base = {
        "title": "T", "status": "ready_for_video_generation", "length_min": 5,
        "model": "grok-imagine", "scenes": 3, "boards": 3, "voiced": 3,
        "max_scene": 3, "pics": 3, "clips": 0, "cast": 0, "spent": 0.0,
    }
    base.update(over)
    return base


def test_animate_quote_sums_per_scene_resolved_prices_not_flat_video_model(monkeypatch):
    """Three not-yet-clipped rows: one routed to Veo Quality (wired), one
    routed to an unwired model (falls back to the video-level grok price),
    one with no routing at all (also falls back). The quote must equal the
    SUM of each row's own resolved price, matching what generation will
    actually spend — not 3 * grok_price."""
    rows = [
        {"routed_model": "veo-3.1-quality"},
        {"routed_model": "kling-3.0-pro"},  # registered but wired=False
        {"routed_model": None},
    ]

    async def fake_fetch_all(query, *args):
        assert "FROM assets" in query and "routed_model" in query
        return rows

    monkeypatch.setattr(actions, "fetch_all", fake_fetch_all)

    cost, text = asyncio.run(actions.estimate_cost(TENANT, VIDEO, "animate", None, _summary()))

    expected = round(VEO_QUALITY_PRICE + GROK_PRICE + GROK_PRICE, 2)
    assert cost == expected, f"expected sum of per-row resolved prices ({expected}), got {cost}"
    # The old flat-price math would have been 3 * GROK_PRICE — prove the two
    # diverge so this test is provably non-vacuous against the routed sum.
    assert cost != round(3 * GROK_PRICE, 2)
    assert text == f"~${expected:.2f}"


def test_animate_quote_scene_scoped_sums_only_that_scenes_rows(monkeypatch):
    """A per-scene quote (tapped 'Animate this scene') must only sum THAT
    scene's rows, scoped by the same WHERE clause as before (scene=$3)."""
    async def fake_fetch_all(query, *args):
        assert "scene=$3" in query
        assert args[-1] == 2  # the scene param
        return [{"routed_model": "veo-3.1-quality"}]

    monkeypatch.setattr(actions, "fetch_all", fake_fetch_all)

    cost, _ = asyncio.run(actions.estimate_cost(TENANT, VIDEO, "animate", 2, _summary()))
    assert cost == VEO_QUALITY_PRICE


def test_animate_quote_empty_scene_falls_back_to_small_guess_unchanged(monkeypatch):
    """Pre-C13 behavior for a scene with zero matching rows yet (e.g. a
    fresh scene whose pictures haven't landed): guess 4 clips at the
    video-level price. Unchanged by this chunk."""
    async def fake_fetch_all(query, *args):
        return []

    monkeypatch.setattr(actions, "fetch_all", fake_fetch_all)

    cost, _ = asyncio.run(actions.estimate_cost(TENANT, VIDEO, "animate", 5, _summary()))
    assert cost == round(4 * GROK_PRICE, 2)


def test_build_quote_with_existing_pictures_uses_routed_sum_not_flat_price(monkeypatch):
    """'Finish it' after pictures already exist: the shot plan (and each
    row's routed_model) was already computed before those pictures were
    drawn, so the same routed per-row sum applies here too — not the flat
    `pics * grok_price` the pre-C13 code used."""
    rows = [{"routed_model": "veo-3.1-quality"}, {"routed_model": None}]

    async def fake_fetch_all(query, *args):
        return rows

    monkeypatch.setattr(actions, "fetch_all", fake_fetch_all)

    cost, _ = asyncio.run(actions.estimate_cost(
        TENANT, VIDEO, "build", None,
        _summary(status="ready_for_video_generation", pics=2)))
    expected = round(VEO_QUALITY_PRICE + GROK_PRICE, 2)
    assert cost == expected


def test_build_quote_before_pictures_exist_falls_back_to_flat_math(monkeypatch):
    """Money invariant #3: when the shot plan doesn't exist yet (no
    pictures), there is nothing to route per scene — fall back to today's
    rough flat estimate instead of inventing per-scene numbers. Also proves
    NO assets query fires in this branch (fetch_all would raise if called)."""
    async def fail_fetch_all(query, *args):
        raise AssertionError("must not query per-row routing before a shot plan exists")

    monkeypatch.setattr(actions, "fetch_all", fail_fetch_all)

    cost, _ = asyncio.run(actions.estimate_cost(
        TENANT, VIDEO, "build", None,
        _summary(status="ready_for_video_generation", pics=0, scenes=5)))
    assert cost == round(5 * 6 * GROK_PRICE, 2)


def test_animate_quote_scene_override_wins_over_routed_model(monkeypatch):
    """C14: a manual scene override (assets.model_override) must win the
    quote's per-row price too, not just routed_model — otherwise the quote
    a creator confirms after overriding a scene would lie about what
    generation is about to spend. One row is routed to Grok but manually
    overridden to Veo Quality; the quote must reflect Veo Quality's price."""
    rows = [{"routed_model": "grok-imagine", "model_override": "veo-3.1-quality"}]

    async def fake_fetch_all(query, *args):
        assert "model_override" in query
        return rows

    monkeypatch.setattr(actions, "fetch_all", fake_fetch_all)

    cost, _ = asyncio.run(actions.estimate_cost(TENANT, VIDEO, "animate", None, _summary()))
    assert cost == VEO_QUALITY_PRICE, (
        "the scene override must win the quote over routed_model, matching "
        "what run_clip_generation will actually spend")
    assert cost != GROK_PRICE


# ---------------------------------------------------------------------------
# 2. run_clip_generation() — the real generation call resolves per row
# ---------------------------------------------------------------------------

import pipeline_executor as pe_mod  # noqa: E402
from pipeline_executor import PipelineExecutor  # noqa: E402
import storage as storage_mod  # noqa: E402
import clip_dialogue as clip_dialogue_mod  # noqa: E402
from clip_dialogue import clip_cost_for  # noqa: E402


class _FakeLightPipeline:
    def __init__(self, image_client):
        self.image_client = image_client
        self.should_cancel = None  # _install_cancel_support overwrites this fail-soft


class _FakeImageClient:
    VEO_MODEL_QUALITY = "veo-quality-id"
    VEO_MODEL_FAST = "veo-fast-id"

    def __init__(self):
        self.calls = []

    async def generate_video(self, img, prompt, duration=6, extra_image_urls=None,
                              aspect_ratio="16:9", resolution="720p", task_id_out=None):
        self.calls.append(("grok", duration))
        if task_id_out is not None:
            task_id_out.append("grok-task-1")
        return "https://fake/grok-clip.mp4"

    async def generate_video_seedance(self, img, prompt, duration=6, extra_image_urls=None,
                                       aspect_ratio="16:9", task_id_out=None):
        raise AssertionError("seedance should not be called in this test")

    async def generate_video_veo(self, prompt, image_url=None, model=None, task_id_out=None):
        self.calls.append(("veo", model))
        if task_id_out is not None:
            task_id_out.append("veo-task-1")
        return "https://fake/veo-clip.mp4"

    async def generate_talking_video(self, image_url, audio_url, prompt=None,
                                      resolution="720p", task_id_out=None):
        self.calls.append(("infinitalk", audio_url))
        if task_id_out is not None:
            task_id_out.append("infinitalk-task-1")
        return "https://fake/talk-clip.mp4"

    async def download_image(self, url):
        return b"fake-clip-bytes"


def _asset_row(routed_model, assigned_dialogue=None, model_override=None):
    return {
        "id": "asset-1", "scene": 1, "image_index": 1,
        "image_url": "https://fake/img1.png", "drive_image_url": None,
        "video_prompt": "Wide shot pushes in on the machine.",
        "video_clip_url": None, "duration_seconds": 4.0,
        "sentence_text": None, "image_prompt": "a factory floor",
        "assigned_dialogue": assigned_dialogue, "routed_model": routed_model,
        "model_override": model_override,
    }


def _video_row(dialogue_mode=None, dialogue_audio="voice_over"):
    return {
        "id": VIDEO, "video_model": "grok-imagine", "aspect_ratio": "16:9",
        "video_resolution": "720p", "dialogue_mode": dialogue_mode,
        "dialogue_audio": dialogue_audio, "character_reference_url": None,
        "image_style_override": None, "status": "ready_for_video_generation",
    }


# One dialogue line, matched via assigned_dialogue's `Speaker: "text"` shape
# (scripts.dialogue_segments -> clip_dialogue.match_assigned). audio_url is
# a plain (non-Drive) URL on purpose: clip_dialogue.download_voice() only
# ever attempts a real fetch for a Drive-shaped URL — anything else returns
# None with zero network calls, which is exactly what naturally skips
# InfiniteTalk in the "falls back to Grok" test below without needing to
# fake httpx/Drive at all.
_DIALOGUE_LINE = {
    "type": "dialogue", "text": "Hello there.", "speaker": "Tom",
    "audio_url": "https://fake/voice1.mp3", "duration": 2.0,
}
_ASSIGNED_DIALOGUE = 'Tom: "Hello there."'


def _run_clip_generation_for(monkeypatch, routed_model, *, dialogue_mode=None,
                              dialogue_audio="voice_over", assigned_dialogue=None,
                              model_override=None, extra_patches=None):
    """Drives run_clip_generation for ONE asset row carrying `routed_model`
    (and optionally a C14 `model_override`), with all paid/DB/storage
    boundaries faked. `extra_patches(monkeypatch, image_client)` lets a
    caller layer on more monkeypatches (e.g. faking InfiniteTalk's audio
    pipeline) before the run. Returns (image_client, ledger_calls,
    model_used_updates, clip_url_updates)."""
    ledger_calls = []
    model_used_updates = []
    clip_url_updates = []

    async def fake_fetch_one(query, *args):
        if "FROM videos WHERE id" in query:
            return _video_row(dialogue_mode, dialogue_audio)
        if "SELECT scene FROM assets WHERE id" in query:
            return {"scene": 1}
        if "COUNT(*) AS pics, COUNT(video_clip_url) AS clips" in query:
            # pics=1, clips=0 -> deliberately NOT fully clipped, so the
            # auto-stitch branch skips calling the real stitcher.
            return {"pics": 1, "clips": 0}
        return None

    async def fake_fetch_all(query, *args):
        if "FROM assets WHERE" in query and "routed_model" in query:
            assert "model_override" in query, (
                "run_clip_generation's asset query must select model_override "
                "(C14) alongside routed_model, or the override can never resolve")
            return [_asset_row(routed_model, assigned_dialogue, model_override)]
        if "dialogue_segments FROM scripts" in query:
            return [{"scene": 1, "dialogue_segments": [_DIALOGUE_LINE]}]
        return []

    async def fake_execute(query, *args):
        if "UPDATE assets SET video_clip_url" in query:
            clip_url_updates.append(args)
        elif "UPDATE assets SET model_used" in query:
            model_used_updates.append(args)
        return "OK"

    async def fake_record_ledger_entry(**kwargs):
        ledger_calls.append(kwargs)

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
    # clip_dialogue.load_dialogue_lines() imports its OWN `fetch_all` from
    # `database` at clip_dialogue.py's module level (separate bound name
    # from pipeline_executor's) — must be patched here too or a
    # character_dialogue-mode run hits the real (unset) DATABASE_URL.
    monkeypatch.setattr(clip_dialogue_mod, "fetch_all", fake_fetch_all)

    image_client = _FakeImageClient()
    if extra_patches:
        extra_patches(monkeypatch, image_client)

    executor = PipelineExecutor.__new__(PipelineExecutor)
    executor.tenant_id = TENANT
    executor._initialized = True  # skip vault/env loading in _ensure_initialized
    executor._pipeline = _FakeLightPipeline(image_client)

    result = asyncio.run(executor.run_clip_generation(VIDEO, asset_id="asset-1"))
    assert result["status"] == "completed", result
    return image_client, ledger_calls, model_used_updates, clip_url_updates


def test_routed_model_wired_wins_over_video_level_model(monkeypatch):
    """A row carrying a WIRED routed_model (veo-3.1-quality) must animate
    through Veo, not the video's own default model (grok-imagine) — and the
    ledger + model_used must both name veo-3.1-quality, not grok-imagine."""
    client, ledger_calls, model_used_updates, clip_url_updates = _run_clip_generation_for(
        monkeypatch, "veo-3.1-quality")

    assert client.calls == [("veo", client.VEO_MODEL_QUALITY)], (
        "expected exactly one generate_video_veo call — got " + repr(client.calls))

    assert len(ledger_calls) == 1
    ledger = ledger_calls[0]
    assert ledger["model"] == "veo-3.1-quality"
    assert ledger["stage"] == "clip"
    clip_dur = clip_url_updates[0][1]  # (drive_url, clip_dur, id)
    expected_cost = clip_cost_for(MODEL_REGISTRY["veo-3.1-quality"].cost_per_clip, clip_dur)
    assert ledger["unit_cost"] == ledger["actual_cost"] == expected_cost
    assert expected_cost == VEO_QUALITY_PRICE  # veo-3.1-quality has only one duration tier (8s)

    assert len(model_used_updates) == 1
    assert model_used_updates[0] == ("veo-3.1-quality", "asset-1")


def test_scene_override_wins_over_routed_model(monkeypatch):
    """C14: a manual per-scene override (assets.model_override) must win
    over C12's automatic routed_model recommendation — the whole point of
    giving a creator a one-tap override is that it actually takes effect.
    Row is routed to Grok (the video default) but manually overridden to
    Veo Quality; the clip, ledger, and model_used must all say Veo."""
    client, ledger_calls, model_used_updates, clip_url_updates = _run_clip_generation_for(
        monkeypatch, "grok-imagine", model_override="veo-3.1-quality")

    assert client.calls == [("veo", client.VEO_MODEL_QUALITY)], (
        "expected the override to route through Veo, not the routed_model's "
        "Grok recommendation — got " + repr(client.calls))
    assert ledger_calls[0]["model"] == "veo-3.1-quality"
    assert model_used_updates[0] == ("veo-3.1-quality", "asset-1")


def test_unwired_scene_override_falls_back_to_routed_model(monkeypatch):
    """An override naming a real-but-unwired model (kling-3.0-pro) must not
    attempt a dead generation path — falls through to routed_model (Veo
    Quality here), exactly like resolve_clip_model's own documented
    precedence."""
    client, ledger_calls, model_used_updates, _ = _run_clip_generation_for(
        monkeypatch, "veo-3.1-quality", model_override="kling-3.0-pro")

    assert client.calls == [("veo", client.VEO_MODEL_QUALITY)], (
        "an unwired override must fall through to routed_model, not silently "
        "no-op the routing entirely — got " + repr(client.calls))
    assert ledger_calls[0]["model"] == "veo-3.1-quality"
    assert model_used_updates[0] == ("veo-3.1-quality", "asset-1")


def test_null_routed_model_falls_back_byte_identical_to_video_level_model(monkeypatch):
    """The core C13 money invariant: a row with NO routed_model must clip
    through the exact SAME engine (Grok) and price as every video ever did
    before this chunk — proving the fallback is byte-identical, not merely
    'close enough'."""
    client, ledger_calls, model_used_updates, clip_url_updates = _run_clip_generation_for(
        monkeypatch, None)

    assert client.calls and client.calls[0][0] == "grok", (
        "NULL routed_model must fall back to the video-level model's own "
        "animator (grok-imagine here) — got " + repr(client.calls))

    assert len(ledger_calls) == 1
    ledger = ledger_calls[0]
    assert ledger["model"] == "grok-imagine"
    clip_dur = clip_url_updates[0][1]
    expected_cost = clip_cost_for(MODEL_REGISTRY["grok-imagine"].cost_per_clip, clip_dur)
    assert ledger["unit_cost"] == ledger["actual_cost"] == expected_cost

    assert model_used_updates[0] == ("grok-imagine", "asset-1")


def test_unwired_routed_model_falls_back_same_as_null(monkeypatch):
    """A routed_model naming a REAL but unwired registry entry (kling-3.0-pro
    — no live generation path) must fall back exactly like NULL: never
    attempt to animate through a dead engine."""
    assert MODEL_REGISTRY["kling-3.0-pro"].wired is False  # pin the fixture's premise
    client, ledger_calls, model_used_updates, _ = _run_clip_generation_for(
        monkeypatch, "kling-3.0-pro")

    assert client.calls and client.calls[0][0] == "grok"
    assert ledger_calls[0]["model"] == "grok-imagine"
    assert model_used_updates[0] == ("grok-imagine", "asset-1")


# ---------------------------------------------------------------------------
# 2b. Orchestrator review: the SPEAKING branch has no Veo case, and
# InfiniteTalk (not the routed model) can be the real engine — model_used
# and the ledger must describe whichever engine ACTUALLY produced the clip,
# never the routed target when the two diverge.
# ---------------------------------------------------------------------------

def test_speaking_branch_veo_routed_row_falls_back_to_grok_not_veo(monkeypatch):
    """Reachability: dialogue_mode='character_dialogue' + dialogue_audio=
    'voice_over' (native_voices False) + a matched dialogue line (via
    assigned_dialogue/match_assigned) puts the row on the SPEAKING branch
    (`if lines:`). _animate_for() has no Veo case there — only Grok/
    Seedance — so a row purpose-routed to Veo (a REVEAL/PAYOFF/ESTABLISH/
    SCALE/ISOLATION shot that ALSO happens to carry dialogue) must not be
    animated, priced, or recorded as Veo: it silently runs through Grok's
    closure, so cost/ledger/model_used must say Grok, not Veo."""
    client, ledger_calls, model_used_updates, clip_url_updates = _run_clip_generation_for(
        monkeypatch, "veo-3.1-quality",
        dialogue_mode="character_dialogue", dialogue_audio="voice_over",
        assigned_dialogue=_ASSIGNED_DIALOGUE)

    assert client.calls and client.calls[0][0] == "grok", (
        "the speaking branch's Grok-fallback leg must actually run Grok, "
        "never silently attempt Veo — got " + repr(client.calls))
    assert not any(c[0] == "veo" for c in client.calls), (
        "Veo must never be called from the speaking branch — got " + repr(client.calls))

    assert len(ledger_calls) == 1
    assert ledger_calls[0]["model"] == "grok-imagine", (
        "ledger must name the engine that ACTUALLY ran (grok-imagine), not "
        "the routed target (veo-3.1-quality) the speaking branch can't honor")
    clip_dur = clip_url_updates[0][1]
    expected_cost = clip_cost_for(MODEL_REGISTRY["grok-imagine"].cost_per_clip, clip_dur)
    assert ledger_calls[0]["unit_cost"] == ledger_calls[0]["actual_cost"] == expected_cost
    assert ledger_calls[0]["unit_cost"] != VEO_QUALITY_PRICE, (
        "must not be charged Veo Quality's $1.25 for a clip Grok actually generated")

    assert model_used_updates[0] == ("grok-imagine", "asset-1")


def test_voice_over_speaking_shot_sts_swap_sets_carries_own_line(monkeypatch):
    """STS voice-lock (2026-07-22, replaced InfiniteTalk): a voice_over
    speaking shot animates through Grok, then swap_voice re-renders the
    take's audio in the pinned cast voice. On success the persist row must
    carry carries_own_line=True plus the measured speech bounds (the
    performance assembler sizes the shot's window from them), and the
    ledger/model_used must still name the engine that drew the pixels
    (grok-imagine) — STS is a polish pass, not an animator."""
    def _wire_sts(monkeypatch, image_client):
        import vault as vault_mod

        async def fake_get_secret(name, tenant_id=None, user_id=None):
            return "fake-xi-key" if name == "elevenlabs_api_key" else None

        async def fake_swap_voice(clip_bytes, voice_id, xi_key):
            assert voice_id == "fake-voice-tom"
            return b"swapped-clip-bytes"

        async def fake_measure(clip_bytes):
            assert clip_bytes == b"swapped-clip-bytes"
            return (0.42, 3.1)

        async def fake_fetch_all_cast(query, *args):
            if "FROM video_characters" in query:
                return [{"name": "Tom", "voice_name": "fake-voice-tom"}]
            return None

        monkeypatch.setattr(vault_mod, "get_secret", fake_get_secret)
        monkeypatch.setattr(clip_dialogue_mod, "swap_voice", fake_swap_voice)
        monkeypatch.setattr(clip_dialogue_mod, "measure_speech_bounds", fake_measure)
        # layer the cast query on top of the harness's fetch_all
        prev = pe_mod.fetch_all

        async def fetch_all_with_cast(query, *args):
            hit = await fake_fetch_all_cast(query, *args)
            return hit if hit is not None else await prev(query, *args)

        monkeypatch.setattr(pe_mod, "fetch_all", fetch_all_with_cast)

    client, ledger_calls, model_used_updates, clip_url_updates = _run_clip_generation_for(
        monkeypatch, "veo-3.1-quality",
        dialogue_mode="character_dialogue", dialogue_audio="voice_over",
        assigned_dialogue=_ASSIGNED_DIALOGUE, extra_patches=_wire_sts)

    assert client.calls and client.calls[0][0] == "grok", (
        "voice_over speaking shots animate through Grok since InfiniteTalk's "
        "removal — got " + repr(client.calls))
    # persist: (drive_url, clip_dur, carries_own_line, speech_start, speech_end, id)
    row = clip_url_updates[0]
    assert row[2] is True, "successful STS swap must persist carries_own_line=True"
    assert row[3] == 0.42 and row[4] == 3.1
    assert ledger_calls[0]["model"] == "grok-imagine"
    assert model_used_updates[0] == ("grok-imagine", "asset-1")


def test_voice_over_sts_failure_falls_back_to_overlay_mux_not_carrying(monkeypatch):
    """A swap failure must never lose the paid clip: the shot ships via the
    overlay-mux fallback and carries_own_line stays False so the assembler
    treats it exactly as before the STS work."""
    def _wire_failing_sts(monkeypatch, image_client):
        import vault as vault_mod

        async def fake_get_secret(name, tenant_id=None, user_id=None):
            return "fake-xi-key" if name == "elevenlabs_api_key" else None

        async def failing_swap_voice(clip_bytes, voice_id, xi_key):
            raise RuntimeError("elevenlabs down")

        async def fake_fetch_all_cast(query, *args):
            if "FROM video_characters" in query:
                return [{"name": "Tom", "voice_name": "fake-voice-tom"}]
            return None

        monkeypatch.setattr(vault_mod, "get_secret", fake_get_secret)
        monkeypatch.setattr(clip_dialogue_mod, "swap_voice", failing_swap_voice)
        prev = pe_mod.fetch_all

        async def fetch_all_with_cast(query, *args):
            hit = await fake_fetch_all_cast(query, *args)
            return hit if hit is not None else await prev(query, *args)

        monkeypatch.setattr(pe_mod, "fetch_all", fetch_all_with_cast)

    client, ledger_calls, model_used_updates, clip_url_updates = _run_clip_generation_for(
        monkeypatch, "veo-3.1-quality",
        dialogue_mode="character_dialogue", dialogue_audio="voice_over",
        assigned_dialogue=_ASSIGNED_DIALOGUE, extra_patches=_wire_failing_sts)

    assert client.calls and client.calls[0][0] == "grok"
    row = clip_url_updates[0]
    assert row[2] is False, "failed swap must persist carries_own_line=False"
    assert row[3] is None and row[4] is None
    assert ledger_calls[0]["model"] == "grok-imagine"


def test_model_used_write_is_fail_soft_never_breaks_a_paid_clip(monkeypatch):
    """model_used is a nice-to-have record, never a risk to the clip that
    already cost money: a forced failure on JUST that UPDATE must still let
    the run report 'completed' with the clip persisted (video_clip_url
    written, ledger row recorded)."""
    ledger_calls = []
    clip_url_updates = []

    async def fake_fetch_one(query, *args):
        if "FROM videos WHERE id" in query:
            return _video_row()
        if "SELECT scene FROM assets WHERE id" in query:
            return {"scene": 1}
        if "COUNT(*) AS pics, COUNT(video_clip_url) AS clips" in query:
            return {"pics": 1, "clips": 0}
        return None

    async def fake_fetch_all(query, *args):
        if "FROM assets WHERE" in query and "routed_model" in query:
            return [_asset_row("veo-3.1-quality")]
        return []

    async def fake_execute(query, *args):
        if "UPDATE assets SET video_clip_url" in query:
            clip_url_updates.append(args)
            return "OK"
        if "UPDATE assets SET model_used" in query:
            raise RuntimeError("simulated DB outage on the model_used write")
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
    # clip_dialogue.load_dialogue_lines() imports its OWN `fetch_all` from
    # `database` at clip_dialogue.py's module level (separate bound name
    # from pipeline_executor's) — must be patched here too or a
    # character_dialogue-mode run hits the real (unset) DATABASE_URL.
    monkeypatch.setattr(clip_dialogue_mod, "fetch_all", fake_fetch_all)

    executor = PipelineExecutor.__new__(PipelineExecutor)
    executor.tenant_id = TENANT
    executor._initialized = True
    executor._pipeline = _FakeLightPipeline(_FakeImageClient())

    result = asyncio.run(executor.run_clip_generation(VIDEO, asset_id="asset-1"))

    assert result["status"] == "completed", (
        f"a model_used write failure must never fail the clip itself — got {result}")
    assert result["clips_generated"] == 1
    assert len(clip_url_updates) == 1, "the paid clip's video_clip_url write must still land"
    assert len(ledger_calls) == 1, "the ledger row must still be written"
    print("✅ test_model_used_write_is_fail_soft_never_breaks_a_paid_clip")


if __name__ == "__main__":
    import inspect
    mod = sys.modules[__name__]
    test_fns = [obj for name, obj in vars(mod).items()
                if name.startswith("test_") and inspect.isfunction(obj)]
    for fn in test_fns:
        params = inspect.signature(fn).parameters
        if "monkeypatch" in params:
            print(f"skipping {fn.__name__} (needs pytest's monkeypatch fixture — run via pytest)")
            continue
        fn()
    print(f"✅ {len(test_fns)} test functions found — run via pytest for full coverage")
