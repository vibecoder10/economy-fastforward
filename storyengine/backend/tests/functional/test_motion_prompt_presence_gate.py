"""Tests for the motion-prompt presence GATE + REPAIR (contract-triangle 2nd/3rd
legs on the SILENT/ESTABLISH absence bug, 2026-07-22).

Found live: scripts/coverage_to_app.py::_write_motion_prompts asks Claude to
write the per-shot camera-motion line for grok-imagine, and stored the result
UNVALIDATED. For a SILENT/ESTABLISH beat the writer produced a line narrating
the characters as absent — "ending on the empty sofa where Ryan and Vanessa
will sit" — over a still (image_prompt) that already showed them seated. Grok
follows the TEXT over the picture and renders an empty room, wasting a paid
clip.

A second, unrelated systematic failure found by a parallel audit the same day:
REACTION shots ("CU on Ryan, listening to Vanessa's line" — Ryan framed,
Vanessa off-frame) came back describing VANESSA's hands/gesture instead of
Ryan's — 4/4 occurrences on the audited scene. Root cause: _shot()'s builder
falls back to the raw truncated image_prompt snippet whenever sentence_text
is null (true for REACTION rows), and the writer LLM misread "listening to
Vanessa's line" as "describe Vanessa."

A THIRD class from prod real-frames feedback (same day): reveal-traverse /
delayed entrance — a camera path starting on scenery ("sweeping past the
balloons... before settling on Ryan and Vanessa") made Grok stage the start
without the characters and pop them in ghost-style on arrival. Gate class (d)
rejects traverse-start + arrival-on-present-character; the fallback for
character shots is a first-frame-visibility hold, never a traverse template.

The fix ships as a contract triangle in the SAME commit:
  1. PROMPT — _MOTION_SYSTEM rule 2 now says a character in the shot is
     ALREADY there; "before anyone speaks" describes dialogue timing, not
     who's in frame. _shot() now passes an explicit "SUBJECT ON CAMERA: X"
     structured hint on REACTION rows instead of the raw snippet.
  2. GATE — gate_motion_prompt(video_prompt, image_prompt): pure, cheap,
     deterministic, now covering BOTH failure classes. THIS FILE pins it.
  3. REPAIR — _write_motion_prompts retries once on a gate failure, then
     falls back to the camera-lock template text (_camera_lock_fallback_text)
     and logs a warning. A gate-failing prompt must never reach the DB.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_motion_prompt_presence_gate.py -q
"""
import asyncio
import os
import sys
import types
from unittest.mock import AsyncMock, patch

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


async def _boom(*a, **k):
    raise AssertionError("pure tests must not touch runtime services")


# Placeholders at import time — every real test overrides fetch_one/fetch_all/
# execute via patch("scripts.coverage_to_app.X", ...) (mirrors test_c16b's pattern).
_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom)
_stub("storage", upload_bytes=_boom)
_stub("vault", get_secret=_boom)
_stub("kie_unified", get_text_client_for_tenant=_boom)

from scripts.coverage_to_app import (  # noqa: E402
    gate_motion_prompt, _write_motion_prompts, _camera_lock_fallback_text,
)

VIDEO_ID = "11111111-1111-1111-1111-111111111111"
TENANT_ID = "tenant-1"


# ---------------------------------------------------------------------------
# gate_motion_prompt — pure function, no DB/LLM
# ---------------------------------------------------------------------------

# The real bug: image already shows both characters seated; the motion line
# narrates the destination as empty and them as not-yet-arrived.
REAL_BUG_IMAGE_PROMPT = (
    "Wide shot of a living room at dusk. Ryan sits on the left cushion of the "
    "sofa, Vanessa sits on the right, both facing each other mid-conversation."
)
REAL_BUG_VIDEO_PROMPT = (
    "Camera holds on the room, slowly panning across the space before "
    "ending on the empty sofa where Ryan and Vanessa will sit."
)


def test_shot1_real_prompt_fails_gate():
    violation = gate_motion_prompt(REAL_BUG_VIDEO_PROMPT, REAL_BUG_IMAGE_PROMPT)
    assert violation is not None
    assert "empty" in violation.lower() or "sofa" in violation.lower()


def test_clean_motion_prompt_passes_gate():
    image_prompt = "Marco sits at the kitchen table, coffee mug in hand, morning light through the window."
    video_prompt = ("Camera slowly pushes in on Marco as he lifts his mug and takes a slow "
                     "breath, eyes drifting toward the window.")
    assert gate_motion_prompt(video_prompt, image_prompt) is None


def test_prop_mention_empty_cup_passes_gate():
    """'empty' attached to a PROP, not a character or their furniture destination,
    must never trip the gate — this is the over-blocking guard rail."""
    image_prompt = "Marco sits at the kitchen table, an empty coffee cup in front of him."
    video_prompt = ("Camera holds steady as Marco lifts the empty coffee cup and sets it "
                     "back down, eyes lifting toward the door.")
    assert gate_motion_prompt(video_prompt, image_prompt) is None


def test_will_sit_anticipation_fails_gate():
    """A present character described as not-yet-seated ('will sit') must fail,
    even with no 'empty'/'vacant' furniture language at all."""
    image_prompt = "Priya stands by the sunlit window in the living room, arms crossed, waiting."
    video_prompt = ("The camera pans slowly across the room before settling on the "
                     "doorway, where Priya will sit once she comes inside.")
    violation = gate_motion_prompt(video_prompt, image_prompt)
    assert violation is not None
    assert "priya" in violation.lower()


def test_character_not_in_image_fails_gate():
    """The writer inventing a person the still never drew must fail — even with
    no absence/anticipation language, naming + acting a character the image
    doesn't show is itself the contradiction."""
    image_prompt = "A quiet kitchen at dawn, steam rising from a kettle on the stove."
    video_prompt = "Camera pushes in as Diego turns to speak, eyes lifting toward the door."
    violation = gate_motion_prompt(video_prompt, image_prompt)
    assert violation is not None
    assert "diego" in violation.lower()


def test_no_one_language_only_flagged_when_image_has_people():
    """'no one'/'nobody' language over a genuinely EMPTY establishing shot
    (no characters in image_prompt at all) is legitimate and must pass."""
    image_prompt = "An empty hallway at night, a single light flickering overhead."
    video_prompt = "Camera tracks slowly down the hallway; no one is in frame, just the flickering light."
    assert gate_motion_prompt(video_prompt, image_prompt) is None


# --- REACTION-shot subject swap (audit finding, 2026-07-22, 4/4 occurrences) ---

REACTION_IMAGE_PROMPT = "CU on Ryan, listening to Vanessa's line, same instant."


def test_reaction_shot_speaker_hands_instead_of_reactor_fails_gate():
    """The real broken example: the shot is framed on Ryan (the reactor), but
    the motion text describes Vanessa's (the off-frame speaker's) hands."""
    video_prompt = ("Vanessa's hands press flat on the table, fingers spreading as she "
                     "leans forward to make her point.")
    violation = gate_motion_prompt(video_prompt, REACTION_IMAGE_PROMPT)
    assert violation is not None
    assert "ryan" in violation.lower() and "vanessa" in violation.lower()


def test_reaction_shot_reactor_watching_speaker_passes_gate():
    """Corrected line: Ryan (the framed reactor) is the one acting; Vanessa is
    only named as his gaze target. Watching the speaker is legal — only the
    speaker acting instead of the reactor is the violation."""
    video_prompt = ("Ryan's easy smile fades a degree, eyes staying locked on Vanessa "
                     "as he listens.")
    assert gate_motion_prompt(video_prompt, REACTION_IMAGE_PROMPT) is None


def test_reaction_shot_reactor_also_described_passes_gate():
    """If the reactor is ALSO given a physical action of their own, the shot
    isn't a clean subject swap — the reactor isn't 'absent or passive', so
    this must not be flagged as a clear contradiction."""
    video_prompt = ("Ryan's hand tightens on his glass as Vanessa's fingers drum the "
                     "table, tension building between them.")
    assert gate_motion_prompt(video_prompt, REACTION_IMAGE_PROMPT) is None


# --- Class (d): reveal-traverse / delayed character entrance (prod real
# frames, 2026-07-22) — camera path starting on scenery and arriving on a
# present character makes Grok ghost the characters in mid-shot. ---

PARTY_IMAGE_PROMPT = (
    "Wide shot of a decorated living room: balloons and party decor along the "
    "wall, Ryan and Vanessa standing together at the coffee table."
)
# The exact prompt that failed on prod (shot 1's earlier gate-corrected line).
REVEAL_TRAVERSE_PROMPT = (
    "Camera trucks right on a straight horizontal track, sweeping past the "
    "balloons and party decor before settling on Ryan and Vanessa already "
    "standing at the coffee table."
)
# The replacement that fixed it on prod.
REVEAL_SAFE_REPLACEMENT = (
    "Camera drifts right in a slow, gentle glide. Ryan and Vanessa are fully "
    "visible from the very first frame, standing at the coffee table as Vanessa "
    "adjusts a plate and Ryan looks toward her. No one enters or exits the frame."
)


def test_reveal_traverse_exact_prod_prompt_fails_gate():
    violation = gate_motion_prompt(REVEAL_TRAVERSE_PROMPT, PARTY_IMAGE_PROMPT)
    assert violation is not None
    assert "reveal" in violation.lower()
    assert "ryan" in violation.lower() or "vanessa" in violation.lower()


def test_reveal_safe_replacement_passes_gate():
    """The prod replacement — first-frame visibility clause, 'no one enters or
    exits' presence-PRESERVING language — must pass, including its 'no one'
    wording (the no-one check exempts change-of-state verbs)."""
    assert gate_motion_prompt(REVEAL_SAFE_REPLACEMENT, PARTY_IMAGE_PROMPT) is None


def test_scenery_only_traverse_passes_gate():
    """A traverse over a shot with NO characters in image_prompt (the balloon
    insert) is legitimate coverage and must never be blocked."""
    image_prompt = "INSERT: balloons and streamers taped along the living room wall, party decor."
    video_prompt = ("Camera trucks right, sweeping past the balloons and streamers "
                     "before settling on the stacked gift boxes at the wall's end.")
    assert gate_motion_prompt(video_prompt, image_prompt) is None


def test_traverse_arriving_on_object_passes_gate():
    """Arrival on an OBJECT in a character shot is legal — only arrival on a
    present character is the ghost-entrance trigger."""
    video_prompt = ("Camera pans across the table, settling on the cake as Ryan and "
                     "Vanessa stay in frame laughing through the whole move.")
    assert gate_motion_prompt(video_prompt, PARTY_IMAGE_PROMPT) is None


def test_character_shot_fallback_has_first_frame_clause_not_traverse():
    """Class-(d) REPAIR: a shot WITH characters must fall back to the static
    hold with the explicit first-frame-visibility clause — never a camera-lock
    traverse template (truck_right's own 'pan across the scene' wording is
    what seeded the prod failure)."""
    for camera_movement in [None, "static", "truck_right|reveal", "push_in|x"]:
        text = _camera_lock_fallback_text(camera_movement, PARTY_IMAGE_PROMPT)
        assert "fully visible from the very first frame" in text
        assert "no one enters or exits" in text
        assert "pan across" not in text.lower()
        assert "trucks" not in text.lower()
        assert gate_motion_prompt(text, PARTY_IMAGE_PROMPT) is None


def test_camera_lock_fallback_never_trips_its_own_gate():
    """The REPAIR fallback text itself must always pass the gate it's the
    escape hatch for — otherwise a fallback could recursively fail. Both
    forms: scenery-only (template/static path) and character shots (the
    class-(d) first-frame-visibility hold)."""
    for camera_movement in [None, "", "static", "push_in|reveal", "not_a_real_move|x"]:
        for image_prompt in ["A quiet empty kitchen at dawn.", REAL_BUG_IMAGE_PROMPT, PARTY_IMAGE_PROMPT]:
            text = _camera_lock_fallback_text(camera_movement, image_prompt)
            assert gate_motion_prompt(text, image_prompt) is None


# ---------------------------------------------------------------------------
# _write_motion_prompts — REPAIR wiring: retry once, then fall back; a
# gate-failing prompt must never be the one written to the DB.
# ---------------------------------------------------------------------------

SCENE = 1
ROW = {
    "id": "asset-1", "shot_type": "WS", "image_prompt": REAL_BUG_IMAGE_PROMPT,
    "sentence_text": "Ryan and Vanessa sit together before the conversation begins.",
    "assigned_dialogue": None, "camera_movement": None,
}


def _run_write_motion_prompts(claude_generate_side_effect):
    claude = AsyncMock()
    claude.generate = AsyncMock(side_effect=claude_generate_side_effect)
    fetch_all_mock = AsyncMock(side_effect=lambda q, *a: (
        [dict(ROW)] if "FROM assets" in q else _fail(f"unexpected fetch_all: {q}")
    ))
    fetch_one_mock = AsyncMock(return_value={"scene_text": "Ryan and Vanessa sit quietly."})
    execute_mock = AsyncMock(return_value="OK")
    with patch("scripts.coverage_to_app.fetch_all", fetch_all_mock), \
         patch("scripts.coverage_to_app.fetch_one", fetch_one_mock), \
         patch("scripts.coverage_to_app.execute", execute_mock):
        written = asyncio.run(_write_motion_prompts(VIDEO_ID, TENANT_ID, SCENE, claude))
    return written, execute_mock


def _fail(msg):
    raise AssertionError(msg)


def test_repair_retry_succeeds_stores_the_repaired_line():
    """First LLM call returns the bug line; the one-shot repair retry returns
    a clean line — the clean repaired line (not the original) must be stored,
    and it must pass the gate."""
    responses = iter([
        f"1. {REAL_BUG_VIDEO_PROMPT}",           # initial batch write
        "1. Camera holds steady on Ryan and Vanessa, framing their quiet conversation.",  # repair
    ])
    written, execute_mock = _run_write_motion_prompts(lambda **kw: next(responses))
    assert written == 1
    stored_prompt = execute_mock.await_args_list[-1].args[1]
    assert gate_motion_prompt(stored_prompt, REAL_BUG_IMAGE_PROMPT) is None
    assert "will sit" not in stored_prompt.lower()
    assert "empty" not in stored_prompt.lower()


def test_repair_retry_fails_falls_back_to_camera_lock_template():
    """Both the original AND the repair retry violate the gate — the stored
    value must be the neutral fallback template, never a gate-failing line."""
    responses = iter([
        f"1. {REAL_BUG_VIDEO_PROMPT}",  # initial batch write
        "1. Camera lands on the empty sofa where Ryan and Vanessa will sit.",  # repair still fails
    ])
    written, execute_mock = _run_write_motion_prompts(lambda **kw: next(responses))
    assert written == 1
    stored_prompt = execute_mock.await_args_list[-1].args[1]
    assert gate_motion_prompt(stored_prompt, REAL_BUG_IMAGE_PROMPT) is None
    # The shot's image has characters -> class-(d) rule: the fallback must be
    # the first-frame-visibility hold, never a camera-lock traverse template.
    assert stored_prompt == _camera_lock_fallback_text(None, REAL_BUG_IMAGE_PROMPT)
    assert "fully visible from the very first frame" in stored_prompt


def test_clean_first_write_never_triggers_repair_call():
    """A clean first write must be stored as-is — the repair path (a second
    claude.generate call) must never fire when the gate already passes."""
    clean = "Camera holds steady on Ryan and Vanessa, framing their quiet conversation."
    calls = []

    async def _gen(**kw):
        calls.append(kw)
        return f"1. {clean}"

    written, execute_mock = _run_write_motion_prompts(_gen)
    assert written == 1
    assert len(calls) == 1  # no repair call
    stored_prompt = execute_mock.await_args_list[-1].args[1]
    # _strip_embedded_line trims a trailing period — compare modulo that.
    assert stored_prompt == clean.rstrip(".")


# ---------------------------------------------------------------------------
# REACTION rows: PROMPT root-cause fix (_shot()'s structured hint) + full
# gate/repair wiring on a REACTION row with sentence_text=None (the actual
# shape of the audited bug — sentence_text is null on REACTION rows).
# ---------------------------------------------------------------------------

REACTION_ROW = {
    "id": "asset-2", "shot_type": "CU", "image_prompt": REACTION_IMAGE_PROMPT,
    "sentence_text": None, "assigned_dialogue": None, "camera_movement": None,
}


def test_shot_builder_sends_structured_hint_not_raw_reaction_snippet():
    """PROMPT root-cause pin: _shot() must hand the writer an explicit
    'SUBJECT ON CAMERA: <reactor>' hint on a REACTION row (sentence_text
    null), not the raw 'CU on Ryan, listening to Vanessa's line' snippet the
    LLM was found misreading as 'describe Vanessa'."""
    captured = {}

    async def _gen(**kw):
        captured["prompt"] = kw.get("prompt", "")
        return "1. Ryan's easy smile fades a degree, eyes staying locked on Vanessa as he listens."

    claude = AsyncMock()
    claude.generate = AsyncMock(side_effect=_gen)
    fetch_all_mock = AsyncMock(side_effect=lambda q, *a: (
        [dict(REACTION_ROW)] if "FROM assets" in q else _fail(f"unexpected fetch_all: {q}")
    ))
    fetch_one_mock = AsyncMock(return_value={"scene_text": "Ryan and Vanessa talk quietly."})
    execute_mock = AsyncMock(return_value="OK")
    with patch("scripts.coverage_to_app.fetch_all", fetch_all_mock), \
         patch("scripts.coverage_to_app.fetch_one", fetch_one_mock), \
         patch("scripts.coverage_to_app.execute", execute_mock):
        asyncio.run(_write_motion_prompts(VIDEO_ID, TENANT_ID, SCENE, claude))

    sent = captured["prompt"]
    assert "SUBJECT ON CAMERA: Ryan" in sent
    assert "CU on Ryan, listening to Vanessa's line" not in sent


def test_reaction_row_speaker_swap_gets_repaired_and_never_stored():
    """End-to-end: the writer's first pass makes the classic subject-swap
    mistake on a REACTION row; the repair retry fixes it; the swapped line
    must never reach the DB."""
    responses = iter([
        "1. Vanessa's hands press flat on the table, fingers spreading as she leans forward.",
        "1. Ryan's easy smile fades a degree, eyes staying locked on Vanessa as he listens.",
    ])
    claude = AsyncMock()
    claude.generate = AsyncMock(side_effect=lambda **kw: next(responses))
    fetch_all_mock = AsyncMock(side_effect=lambda q, *a: (
        [dict(REACTION_ROW)] if "FROM assets" in q else _fail(f"unexpected fetch_all: {q}")
    ))
    fetch_one_mock = AsyncMock(return_value={"scene_text": "Ryan and Vanessa talk quietly."})
    execute_mock = AsyncMock(return_value="OK")
    with patch("scripts.coverage_to_app.fetch_all", fetch_all_mock), \
         patch("scripts.coverage_to_app.fetch_one", fetch_one_mock), \
         patch("scripts.coverage_to_app.execute", execute_mock):
        written = asyncio.run(_write_motion_prompts(VIDEO_ID, TENANT_ID, SCENE, claude))

    assert written == 1
    stored_prompt = execute_mock.await_args_list[-1].args[1]
    assert gate_motion_prompt(stored_prompt, REACTION_IMAGE_PROMPT) is None
    assert "vanessa's hands" not in stored_prompt.lower()
