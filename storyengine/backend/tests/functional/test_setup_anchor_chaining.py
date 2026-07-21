"""Setup-anchor chaining (Ryan, 2026-07-21: background props wandered between
repeats of the same camera setup). The first-planned shot of each setup draws
normally and becomes the setup's ANCHOR; every later same-setup shot attaches
that frame LAST with _SETUP_ANCHOR and copies its room. Owners resolve their
future even on failure, so a dead owner can never hang the scene.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_setup_anchor_chaining.py -q
"""
import asyncio
import os
import sys
from unittest.mock import patch

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))

from storyboard.coverage import (  # noqa: E402
    generate_coverage_frames, _setup_id, _SETUP_ANCHOR, _BOARD_ANCHOR_MID,
    _STYLE_LOCK_HYGIENE,
)
from shared.channel_profile import load_profile  # noqa: E402

PROFILE = load_profile({})
CAST = ["https://fake/cast-a.png"]


def test_setup_id_parses_the_leading_tag():
    assert _setup_id({"description": "(SETUP C) MCU OTS onto Vanessa"}) == "C"
    assert _setup_id({"description": " (setup d-b) CU matched single"}) == "D-B"
    assert _setup_id({"description": "WS with no tag"}) is None
    assert _setup_id({"description": None}) is None


def _shot(desc, setup_id=None, owner=False, board=None):
    s = {"shot_type": "MCU", "description": desc}
    if setup_id:
        s["setup_id"] = setup_id
        if owner:
            s["setup_anchor_owner"] = True
    if board:
        s["board_url"], s["board_panel"] = board, 3
    return s


class _RecordingGen:
    """Fake _gen_ref: records every (prompt, refs) call, returns unique urls."""

    def __init__(self, fail_descriptions=()):
        self.calls = []
        self.n = 0
        self.fail_descriptions = fail_descriptions

    async def __call__(self, image_client, prompt, refs, aspect, resolution,
                       attempts=2, model_override=None):
        self.calls.append({"prompt": prompt, "refs": list(refs)})
        for marker in self.fail_descriptions:
            if marker in prompt:
                return None, None
        self.n += 1
        return f"https://fake/frame-{self.n}.png", "gpt-image-2"

    def call_for(self, marker):
        return next(c for c in self.calls if marker in c["prompt"])


def _run_moments(moments, gen, setups):
    """Run generate_coverage_frames over the moments concurrently with a
    shared setup_anchors dict, bounded so a plumbing bug fails fast instead
    of hanging the suite."""
    async def _go():
        anchors = {sid: asyncio.get_running_loop().create_future() for sid in setups}
        with patch("storyboard.coverage._gen_ref", gen):
            return await asyncio.wait_for(asyncio.gather(*[
                generate_coverage_frames(m, CAST, object(), PROFILE,
                                         setup_anchors=anchors)
                for m in moments
            ], return_exceptions=True), timeout=10)
    return asyncio.run(_go())


def test_repeat_setup_shot_attaches_the_owners_frame_last():
    gen = _RecordingGen()
    moments = [
        {"moment_number": 1,
         "master": _shot("(SETUP A) WS two-shot OWNER-A", "A", owner=True),
         "angles": [_shot("(SETUP C) MCU OTS OWNER-C", "C", owner=True)]},
        {"moment_number": 2,
         "master": _shot("(SETUP C) MCU OTS REPEAT-C", "C"),
         "angles": []},
    ]
    results = _run_moments(moments, gen, setups={"A", "C"})
    assert all(not isinstance(r, BaseException) and r for r in results), results

    owner_call = gen.call_for("OWNER-C")
    owner_result = next(f for r in results for f in r if "OWNER-C" in f["description"])
    repeat_call = gen.call_for("REPEAT-C")
    # The repeat carries the owner's landed frame as its LAST ref + the anchor text.
    assert repeat_call["refs"][-1] == owner_result["url"]
    assert "ANCHOR FRAME" in repeat_call["prompt"]
    # Owners never reference their own (unresolved) setup — no anchor text, and
    # the owner's refs are exactly cast (+ its moment master for angles).
    assert "ANCHOR FRAME" not in owner_call["prompt"]


def test_owner_failure_resolves_future_and_never_hangs():
    # M1's master fails → its angle (owner of C) never draws. M2's SETUP C
    # repeat must still complete, unanchored, well inside the 10s guard.
    gen = _RecordingGen(fail_descriptions=("OWNER-A",))
    moments = [
        {"moment_number": 1,
         "master": _shot("(SETUP A) WS OWNER-A", "A", owner=True),
         "angles": [_shot("(SETUP C) MCU OWNER-C", "C", owner=True)]},
        {"moment_number": 2,
         "master": _shot("(SETUP C) MCU REPEAT-C", "C"),
         "angles": []},
    ]
    results = _run_moments(moments, gen, setups={"A", "C"})
    assert results[0] is None                      # failed master → moment dropped
    assert results[1] and results[1][0]["url"]     # repeat still landed
    repeat_call = gen.call_for("REPEAT-C")
    assert "ANCHOR FRAME" not in repeat_call["prompt"]   # anchor resolved to None


def test_board_wording_moves_off_last_when_anchor_attached():
    gen = _RecordingGen()
    moments = [
        {"moment_number": 1,
         "master": _shot("(SETUP B) MCU OWNER-B", "B", owner=True,
                         board="https://fake/board.png"),
         "angles": []},
        {"moment_number": 2,
         "master": _shot("(SETUP B) MCU REPEAT-B", "B",
                         board="https://fake/board.png"),
         "angles": []},
    ]
    results = _run_moments(moments, gen, setups={"B"})
    assert all(r for r in results), results
    owner_call = gen.call_for("OWNER-B")
    repeat_call = gen.call_for("REPEAT-B")
    # Owner, no anchor: board is LAST and claims the LAST slot.
    assert owner_call["refs"][-1] == "https://fake/board.png"
    assert "The LAST attached reference image is the APPROVED STORYBOARD SHEET" in owner_call["prompt"]
    # Repeat: anchor takes LAST; board switches to the position-free wording.
    assert repeat_call["refs"][-1] != "https://fake/board.png"
    assert "https://fake/board.png" in repeat_call["refs"]
    assert _BOARD_ANCHOR_MID.split("{panel}")[0].strip()[:40] in repeat_call["prompt"]
    assert "ANCHOR FRAME" in repeat_call["prompt"]


def test_shots_without_setup_tags_draw_exactly_as_before():
    gen = _RecordingGen()
    moments = [
        {"moment_number": 1,
         "master": _shot("WS legacy plan, no tag"),
         "angles": [_shot("MCU legacy angle")]},
    ]
    results = _run_moments(moments, gen, setups=set())
    assert results[0] and len(results[0]) == 2
    for c in gen.calls:
        assert "ANCHOR FRAME" not in c["prompt"]


def test_stated_style_leads_every_batch_frame_and_replaces_ref_lock():
    """Ryan 2026-07-21 late: boards stay as-is, so the stated channel style
    must lead every batch frame and outrank a wrong-style reference."""
    styled = load_profile({"Image Style Override":
                           "Fully animated 3D cartoon, NOT photorealistic."})
    gen = _RecordingGen()
    moments = [
        {"moment_number": 1,
         "master": _shot("(SETUP A) WS two-shot", "A", owner=True,
                         board="https://fake/board.png"),
         "angles": [_shot("(SETUP C) MCU OTS", "C", owner=True)]},
    ]
    async def _go():
        anchors = {"A": asyncio.get_running_loop().create_future(),
                   "C": asyncio.get_running_loop().create_future()}
        with patch("storyboard.coverage._gen_ref", gen):
            return await asyncio.wait_for(asyncio.gather(
                generate_coverage_frames(moments[0], CAST, object(), styled,
                                         setup_anchors=anchors)), timeout=10)
    results = asyncio.run(_go())
    assert results[0], results
    for c in gen.calls:
        assert c["prompt"].startswith("ART STYLE")
        assert "IGNORE its art style" in c["prompt"]
        assert _STYLE_LOCK_HYGIENE in c["prompt"]
        assert "EXACT same art style and rendering quality as the attached" not in c["prompt"]


def test_default_profile_keeps_classic_ref_matching_lock():
    gen = _RecordingGen()
    moments = [{"moment_number": 1, "master": _shot("(SETUP A) WS", "A", owner=True),
                "angles": []}]
    results = _run_moments(moments, gen, setups={"A"})
    assert results[0], results
    call = gen.calls[0]
    assert not call["prompt"].startswith("ART STYLE")
    assert "EXACT same art style and rendering quality as the attached" in call["prompt"]
