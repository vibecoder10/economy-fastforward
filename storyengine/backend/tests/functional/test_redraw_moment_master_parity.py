"""D3-65: the redraw repair path draws the wrong picture, systematically.

Root cause (proven against live data, video 686b4651 scene 1): every failed
redraw (S-01.101/102/108/109) was a non-master ANGLE (hero_shot=false) — the
untouched masters (100/103/107) were never redrawn and stayed correct.
generate_coverage_frames (skills/video-pipeline/storyboard/coverage.py) NEVER
draws an angle on cast+env alone — its `angle_base` is always
`cast_refs + [master_url] + env_refs`, plus `_SAME_SUBJECT` stamped into the
prompt ("this is the SAME moment from a different camera... match the
staging and setting of the attached reference exactly"). redraw_asset_image
sent only `cast_refs + env_refs` — no photo anchoring a non-master shot to
ITS OWN moment's composition/location — so a redrawn angle had nothing
pulling it toward its specific staging and regressed toward the one generic
per-scene env photo it did have (sometimes the WRONG location for a
multi-location scene), overriding its own full-length, correct, per-shot
text.

This test proves the redraw assembly is now field-identical, for a non-master
asset, to what generate_coverage_frames' angle path would have sent:
references = cast_refs + [moment_master_url] + env_refs, and the prompt
carries _SAME_SUBJECT. Stash-proof: reverting scripts/coverage_to_app.py's
D3-65 change (or the storyboard.coverage import of _SAME_SUBJECT) makes this
fail — the old code never queries for a master row and never adds
_SAME_SUBJECT, so `refs` stays `[cast, env]` and the assertions below fail.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_redraw_moment_master_parity.py -q
"""
import asyncio
import os
import sys
import types
from unittest.mock import AsyncMock, patch

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


async def _boom(*a, **k):
    raise AssertionError("pure tests must not touch runtime services")


_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom)
_stub("storage", upload_bytes=_boom)
_stub("vault", get_secret=_boom)
_stub("kie_unified", get_text_client_for_tenant=_boom)

from scripts.coverage_to_app import redraw_asset_image, _SAME_SUBJECT  # noqa: E402

VID, TENANT, SCENE = "vid-686b4651", "tenant-1", 1
ANGLE_ASSET = "asset-101"
MASTER_URL = "https://fake/S01_i100.png"
ENV = {"name": "Nyla's glass bubble-pod interior", "reference_url": "https://fake/env.png"}
STORED_PROMPT = ("(SETUP B) MCU from outside the glass looking in — Nyla's face soft "
                  "and sleepy behind the curved surface...")


def _run(*, hero_shot: bool, image_index: int = 101, master_row=None,
         mfetch_calls: list | None = None):
    """Drive redraw_asset_image for one asset and capture the image-gen call.
    master_row: the row (or None) the moment-master lookup query should
    return — simulates whether an earlier hero_shot row exists in this scene."""
    calls = []
    mfetch_calls = mfetch_calls if mfetch_calls is not None else []

    async def fake_fetch_one(query, *args):
        if "FROM assets a JOIN videos v" in query:
            return {"id": ANGLE_ASSET, "scene": SCENE, "image_index": image_index,
                     "image_prompt": STORED_PROMPT, "hero_shot": hero_shot,
                     "generation_method": "coverage", "aspect": "16:9",
                     "image_model_override": None, "image_style_override": None,
                     "visual_style": None}
        if "coverage_directive, scene_text FROM scripts" in query:
            return {"coverage_directive": "pod interior plan", "scene_text": "pod scene"}
        if "hero_shot=true AND image_index<" in query:
            mfetch_calls.append(args)
            return master_row
        raise AssertionError(f"unexpected fetch_one: {query}")

    async def fake_fetch_all(query, *args):
        if "FROM video_characters" in query:
            return [{"reference_url": "https://fake/cast-a.png"}]
        raise AssertionError(f"unexpected fetch_all: {query}")

    async def fake_gen(ic, model_override, prompt, reference_urls=None, **kw):
        calls.append({"prompt": prompt, "refs": list(reference_urls or [])})
        return "https://fake/redrawn.png", "gpt-image-2"

    patches = [
        patch("scripts.coverage_to_app.fetch_one", fake_fetch_one),
        patch("scripts.coverage_to_app.fetch_all", fake_fetch_all),
        patch("scripts.coverage_to_app.execute", AsyncMock()),
        patch("scripts.coverage_to_app.get_secret", AsyncMock(return_value="fake-key")),
        patch("scripts.coverage_to_app.ImageClient", lambda **kw: object()),
        patch("scripts.coverage_to_app._approved_envs", AsyncMock(return_value=[ENV])),
        patch("scripts.coverage_to_app._match_scene_env", lambda text, e: (e[0] if e else None)),
        patch("scripts.coverage_to_app.generate_scene_image_for_model", fake_gen),
        patch("scripts.coverage_to_app._stable_url", AsyncMock(return_value="https://stable/x.png")),
        patch("scripts.coverage_to_app.record_ledger_entry", AsyncMock()),
    ]
    for p in patches:
        p.start()
    try:
        result = asyncio.run(redraw_asset_image(VID, TENANT, ANGLE_ASSET))
    finally:
        for p in patches:
            p.stop()
    assert result["status"] == "completed", result
    assert len(calls) == 1
    return calls[0]


def test_angle_redraw_anchors_on_its_moment_master_like_coverage_does():
    """The core D3-65 fix: a non-master (angle) redraw's reference list must
    match generate_coverage_frames' angle_base exactly — cast, THEN the
    moment's master frame, THEN env — not cast+env alone."""
    call = _run(hero_shot=False, master_row={"image_url": MASTER_URL})
    assert call["refs"] == ["https://fake/cast-a.png", MASTER_URL, "https://fake/env.png"], (
        "redraw must attach the moment's master frame between cast and env refs, "
        "exactly like coverage's angle_base — this is what pulls a redrawn angle "
        "toward its OWN moment's staging/location instead of the generic scene env")


def test_angle_redraw_prompt_carries_same_subject_guard():
    """_SAME_SUBJECT is the text half of the anchor — coverage.py stamps it
    into every angle prompt alongside the master ref; a redraw needs the same
    pairing, not just the photo with no instruction attached to it."""
    call = _run(hero_shot=False, master_row={"image_url": MASTER_URL})
    assert _SAME_SUBJECT in call["prompt"]
    assert call["prompt"].index(STORED_PROMPT) < call["prompt"].index(_SAME_SUBJECT.strip())


def test_moment_master_lookup_scoped_to_this_scene_and_earlier_index():
    """The lookup must be scene- and index-scoped (nearest EARLIER hero_shot
    row in the SAME scene) — never a blind 'any master anywhere' query."""
    calls: list = []
    _run(hero_shot=False, image_index=101, master_row={"image_url": MASTER_URL},
         mfetch_calls=calls)
    assert len(calls) == 1
    assert calls[0] == (VID, TENANT, SCENE, 101)


def test_master_redraw_skips_the_lookup_entirely():
    """A MASTER shot (hero_shot=True) needs no moment-master anchor — its own
    coverage-path reference set is already just cast+env (see
    test_redraw_style_parity.py). The lookup must not even run for it."""
    calls: list = []
    call = _run(hero_shot=True, master_row={"image_url": MASTER_URL}, mfetch_calls=calls)
    assert calls == [], "a master redraw must never query for its own moment-master"
    assert call["refs"] == ["https://fake/cast-a.png", "https://fake/env.png"]
    assert _SAME_SUBJECT not in call["prompt"]


def test_angle_redraw_with_no_earlier_master_falls_back_cleanly():
    """No qualifying master row (e.g. this scene's master itself never drew,
    or was deleted) — fail-soft to the pre-fix cast+env assembly, same as a
    missing env match already does. Never raise, never block the redraw."""
    call = _run(hero_shot=False, master_row=None)
    assert call["refs"] == ["https://fake/cast-a.png", "https://fake/env.png"]
    assert _SAME_SUBJECT not in call["prompt"]
