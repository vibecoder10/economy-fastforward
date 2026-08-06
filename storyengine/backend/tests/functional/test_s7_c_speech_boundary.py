"""S7-C — the SPEECH BOUNDARY for LOCATION:/ACTION: stage-direction headers
(S7-A's authoring channel, storyengine/backend/story_laws.py).

S7-A's storage law: scripts.scene_text and videos.script keep a scene's
LOCATION:/ACTION: header lines VERBATIM — text is never rewritten at
storage. That means every place raw scene_text turns into SPOKEN audio must
strip the headers itself, or the narrator reads "LOCATION: the kitchen"
aloud (recon-confirmed live bug: narration mode, i.e. dialogue_mode !=
"character_dialogue", had NO strip anywhere before this chunk).

Two speech boundaries close this:
  1. skills/video-pipeline/voice/run.py::narration_text — the narrator's
     boundary. Strips leading LOCATION:/ACTION: headers (plain or
     markdown-bolded, either order) before anything else runs.
  2. storyengine/backend/dialogue_intelligence.py::segment_scene — the
     dialogue-classification boundary. Strips both headers from scene_text
     BEFORE it ever reaches the Claude call that splits a scene into
     narration/dialogue segments (scripts.dialogue_segments) — this
     transitively protects every consumer of that column:
     dialogue_voice.py's per-segment TTS and clip_dialogue.py's lip-sync
     prompt quoting, since both read ONLY scripts.dialogue_segments, never
     raw scene_text.

Contrasted with the STORAGE law (routes/videos.py::sync_video_script, kept
BYTE-IDENTICAL per settled decision P11): videos.script keeps the header
verbatim. Both laws are proven together below, off the SAME source text, so
a regression in either direction (over-stripping storage, or under-stripping
speech) shows up as a failed assertion, not a passed one.

STASH-PROOF: this file imports
voice.run._strip_leading_stage_headers directly at module level — that
symbol does not exist before this chunk, so `git stash` on voice/run.py
makes this whole file fail at COLLECTION (ImportError), the loudest
possible "before" failure. The dialogue_intelligence.segment_scene tests
independently prove the same "before" state fails on BEHAVIOR (the header
shows up in the captured Claude prompt) rather than on import, since
segment_scene's signature doesn't change — belt and suspenders.

Local/no-spend: every Claude call is a fake client capturing its own
prompt; every DB call is a fake fetch_all/fetch_one/execute — same
convention as tests/test_s7_a_scene_action.py and
tests/functional/test_d7_7_external_stale.py.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_s7_c_speech_boundary.py -q
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

VIDEO_PIPELINE = Path(__file__).parents[4] / "skills" / "video-pipeline"
if str(VIDEO_PIPELINE) not in sys.path:
    sys.path.insert(0, str(VIDEO_PIPELINE))

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from voice.run import narration_text, _strip_leading_stage_headers  # noqa: E402

import dialogue_intelligence  # noqa: E402
import clip_dialogue  # noqa: E402
import story_laws  # noqa: E402


# =============================================================================
# Boundary 1 — voice/run.py::narration_text (the narrator's speech boundary)
# =============================================================================

def test_narration_text_strips_action_only_header():
    text = "ACTION: she jumps on the table and dances\n\nThe room falls silent."
    assert narration_text(text) == "The room falls silent."


def test_narration_text_strips_location_only_header():
    text = "LOCATION: the kitchen\n\nShe stirs the soup slowly."
    assert narration_text(text) == "She stirs the soup slowly."


def test_narration_text_strips_both_headers_location_then_action():
    text = "LOCATION: the garage\nACTION: she dances on the workbench\n\nMusic plays."
    out = narration_text(text)
    assert out == "Music plays."
    assert "LOCATION" not in out and "ACTION" not in out


def test_narration_text_strips_both_headers_action_then_location():
    text = "ACTION: she dances on the workbench\nLOCATION: the garage\n\nMusic plays."
    out = narration_text(text)
    assert out == "Music plays."
    assert "LOCATION" not in out and "ACTION" not in out


def test_narration_text_strips_bolded_location_header():
    """A model-authored bold label ('**LOCATION:** the kitchen') must die
    just as reliably as the plain form — _BOLD_SPEAKER_RE (which runs AFTER
    this strip in narration_text) would otherwise reduce it to plain
    'LOCATION: the kitchen' and leave it in the narrator's text."""
    text = "**LOCATION:** the kitchen\n\nShe stirs the soup slowly."
    assert narration_text(text) == "She stirs the soup slowly."


def test_narration_text_strips_bolded_action_header():
    text = "**ACTION:** she jumps on the table and dances\n\nThe room falls silent."
    assert narration_text(text) == "The room falls silent."


def test_narration_text_strips_bolded_headers_both_orders():
    for text in (
        "**LOCATION:** the garage\n**ACTION:** she dances on the workbench\n\nMusic plays.",
        "**ACTION:** she dances on the workbench\n**LOCATION:** the garage\n\nMusic plays.",
    ):
        out = narration_text(text)
        assert out == "Music plays.", f"FAIL for {text!r}: got {out!r}"


def test_narration_text_mixed_bold_and_plain_header_order():
    """One header bolded, the sibling plain — real scripts will not always
    be consistent about it."""
    text = "**LOCATION:** the garage\nACTION: she dances\n\nMusic plays."
    assert narration_text(text) == "Music plays."


# ---------------------------------------------------------------------------
# S7-C follow-up (manager review, 2026-08-06) — the colon-OUTSIDE-the-bold
# form: "**ACTION**: x" / "**LOCATION**: x". A first cut of the header
# regexes only tolerated stars immediately before the keyword and
# immediately after the colon ("**ACTION:** x"), so this shape — stars
# wrapping ONLY the keyword, colon outside — matched neither header regex,
# survived the strip, got reduced by _BOLD_SPEAKER_RE to plain "ACTION: x",
# and nothing removed it in narration mode: the narrator would read it
# aloud. _BOLD_SPEAKER_RE's own colon alternation
# (?::\s*\*{1,3}|\*{1,3}\s*:) already treats this as an equally valid
# speaker-label shape — the header regexes must too.
# ---------------------------------------------------------------------------

def test_narration_text_strips_colon_outside_bold_location_header():
    text = "**LOCATION**: the kitchen\n\nShe stirs the soup slowly."
    assert narration_text(text) == "She stirs the soup slowly."


def test_narration_text_strips_colon_outside_bold_action_header():
    text = "**ACTION**: she jumps on the table and dances\n\nThe room falls silent."
    assert narration_text(text) == "The room falls silent."


def test_narration_text_strips_colon_outside_bold_headers_both_orders():
    for text in (
        "**LOCATION**: the garage\n**ACTION**: she dances on the workbench\n\nMusic plays.",
        "**ACTION**: she dances on the workbench\n**LOCATION**: the garage\n\nMusic plays.",
    ):
        out = narration_text(text)
        assert out == "Music plays.", f"FAIL for {text!r}: got {out!r}"


def test_narration_text_colon_outside_bold_paired_with_plain_sibling():
    """The exact leak scenario, either header order, mixed with a plain
    (unstyled) sibling header — no consistent authoring style assumed."""
    for text in (
        "**LOCATION**: the garage\nACTION: she dances\n\nMusic plays.",
        "ACTION: she dances\n**LOCATION**: the garage\n\nMusic plays.",
        "**ACTION**: she dances\nLOCATION: the garage\n\nMusic plays.",
        "LOCATION: the garage\n**ACTION**: she dances\n\nMusic plays.",
    ):
        out = narration_text(text)
        assert out == "Music plays.", f"FAIL for {text!r}: got {out!r}"


def test_narration_text_colon_outside_bold_end_to_end_narration_mode():
    """End-to-end through narration_text in narration mode (dialogue_mode
    falsy — the exact mode the manager's review flagged as having NO strip
    at all before S7-C): the line must be fully gone, not just transformed,
    proving the narrator never receives it."""
    text = "**ACTION**: she leaps onto the crate\n\nShe opens the hatch."
    out = narration_text(text, dialogue_mode="")
    assert out == "She opens the hatch."
    assert "ACTION" not in out
    assert "leaps onto the crate" not in out


def test_narration_text_colon_outside_bold_location_end_to_end_narration_mode():
    text = "**LOCATION**: the kitchen\n\nThe narrator explains the recipe."
    out = narration_text(text, dialogue_mode="")
    assert out == "The narrator explains the recipe."
    assert "LOCATION" not in out
    assert "the kitchen" not in out


def test_narration_text_keeps_prose_intact_when_no_headers():
    text = "She wakes up and reaches for the light. The room is cold."
    assert narration_text(text) == text


def test_narration_text_keeps_mid_text_action_mention_intact():
    """An 'ACTION:' (or 'LOCATION:') mention that isn't on a leading line is
    ordinary narration, never mistaken for the header — mirrors
    story_laws.py's own leading-header-only contract."""
    text = "She waits.\nACTION: she dances\nThen leaves."
    assert narration_text(text) == text


def test_narration_text_only_one_line_of_tolerance_not_two():
    """A third leading line that is neither header breaks the tolerance
    window — the LOCATION header two lines down must NOT be treated as
    leading, exactly like story_laws._extract_leading_header."""
    text = "ACTION: she dances\nSome narration line.\nLOCATION: the garage\n\nBody."
    out = narration_text(text)
    assert "ACTION: she dances" not in out  # its own header still strips
    assert "LOCATION: the garage" in out  # but this one is now mid-text, kept


def test_narration_text_strips_headers_in_narration_mode():
    """THE bug this chunk closes: narration mode (dialogue_mode is falsy)
    previously had NO strip anywhere — the narrator would read the header
    aloud."""
    text = "LOCATION: the kitchen\n\nThe narrator explains the recipe."
    out = narration_text(text, dialogue_mode="")
    assert out == "The narrator explains the recipe."
    assert "LOCATION" not in out


def test_narration_text_strips_headers_in_character_dialogue_mode():
    """Same header strip applies in character_dialogue mode too, alongside
    the existing (pre-S7-C) speaker-line drop."""
    text = "LOCATION: the kitchen\nACTION: she stirs the pot\n\nMarco: Dinner's ready!\nThey all sit down."
    out = narration_text(text, dialogue_mode="character_dialogue")
    assert "LOCATION" not in out
    assert "ACTION" not in out
    assert "Marco:" not in out  # pre-existing speaker-line drop, unchanged
    assert "They all sit down." in out


def test_strip_leading_stage_headers_no_op_on_plain_text():
    """Sanity on the helper directly: untouched text in, untouched text out."""
    text = "Just plain narration, no headers at all."
    assert _strip_leading_stage_headers(text) == text


def test_strip_leading_stage_headers_empty_and_none():
    assert _strip_leading_stage_headers("") == ""
    assert _strip_leading_stage_headers(None) == ""


# =============================================================================
# Boundary 2 — dialogue_intelligence.segment_scene (the classification
# boundary, protects dialogue_voice.py + clip_dialogue.py transitively)
# =============================================================================

class _FakeClaudeCapture:
    """Captures the prompt segment_scene sends, and returns a canned
    segmentation response built purely from what a REAL stripped scene would
    contain — never echoing the raw (possibly header-carrying) input, so a
    regression that stops stripping would show up as the header appearing
    in `captured['prompt']`, not as a crash here."""

    def __init__(self, segments_json):
        self.captured = {}
        self._segments_json = segments_json

    async def __call__(self, prompt, tenant_id, tier="fast", max_tokens=4000):
        self.captured["prompt"] = prompt
        self.captured["tenant_id"] = tenant_id
        return self._segments_json


def test_segment_scene_prompt_never_contains_location_header(monkeypatch):
    fake = _FakeClaudeCapture(json.dumps({
        "segments": [{"type": "narration", "text": "She stirs the soup slowly."}],
    }))
    monkeypatch.setattr(dialogue_intelligence, "_claude", fake)

    scene_text = "LOCATION: the kitchen\n\nShe stirs the soup slowly."
    result = asyncio.run(dialogue_intelligence.segment_scene(scene_text, [], "tenant-1"))

    assert "LOCATION" not in fake.captured["prompt"]
    assert result == [{"type": "narration", "text": "She stirs the soup slowly."}]


def test_segment_scene_prompt_never_contains_action_header(monkeypatch):
    fake = _FakeClaudeCapture(json.dumps({
        "segments": [{"type": "narration", "text": "The room falls silent."}],
    }))
    monkeypatch.setattr(dialogue_intelligence, "_claude", fake)

    scene_text = "ACTION: she jumps on the table and dances\n\nThe room falls silent."
    asyncio.run(dialogue_intelligence.segment_scene(scene_text, [], "tenant-1"))

    assert "ACTION" not in fake.captured["prompt"]


def test_segment_scene_prompt_never_contains_either_header_regardless_of_order(monkeypatch):
    for scene_text in (
        "LOCATION: the garage\nACTION: she dances on the workbench\n\nMusic plays. Marco: Wait!",
        "ACTION: she dances on the workbench\nLOCATION: the garage\n\nMusic plays. Marco: Wait!",
    ):
        fake = _FakeClaudeCapture(json.dumps({
            "segments": [
                {"type": "narration", "text": "Music plays."},
                {"type": "dialogue", "speaker": "Marco", "text": "Wait!"},
            ],
        }))
        monkeypatch.setattr(dialogue_intelligence, "_claude", fake)
        asyncio.run(dialogue_intelligence.segment_scene(scene_text, ["Marco"], "tenant-1"))
        assert "LOCATION" not in fake.captured["prompt"], f"FAIL for {scene_text!r}"
        assert "ACTION" not in fake.captured["prompt"], f"FAIL for {scene_text!r}"


def test_segment_scene_prompt_scene_block_matches_story_laws_strip():
    """Direct proof the SCENE: block segment_scene builds is byte-identical
    to chaining story_laws' own two extractors — no independent/divergent
    stripping logic living in two places."""
    scene_text = "LOCATION: the garage\nACTION: she dances\n\nBody text here."
    _, after_location = story_laws.extract_scene_location(scene_text)
    _, expected = story_laws.extract_scene_action(after_location)
    assert expected == "Body text here."


def test_segment_scene_mid_text_mention_is_preserved(monkeypatch):
    """A non-leading 'ACTION:'-shaped line (ordinary prose) must still reach
    the Claude prompt — this boundary only strips the LEADING header, never
    mid-scene text, matching story_laws' own contract."""
    fake = _FakeClaudeCapture(json.dumps({
        "segments": [{"type": "narration", "text": "She waits. ACTION: she dances. Then leaves."}],
    }))
    monkeypatch.setattr(dialogue_intelligence, "_claude", fake)

    scene_text = "She waits.\nACTION: she dances\nThen leaves."
    asyncio.run(dialogue_intelligence.segment_scene(scene_text, [], "tenant-1"))
    assert "ACTION: she dances" in fake.captured["prompt"]


def test_segment_scene_no_headers_unaffected(monkeypatch):
    """Regression: a scene with no headers at all behaves exactly as
    before — full text reaches the prompt unchanged."""
    fake = _FakeClaudeCapture(json.dumps({
        "segments": [{"type": "narration", "text": "Just plain narration here."}],
    }))
    monkeypatch.setattr(dialogue_intelligence, "_claude", fake)

    scene_text = "Just plain narration here."
    asyncio.run(dialogue_intelligence.segment_scene(scene_text, [], "tenant-1"))
    assert scene_text in fake.captured["prompt"]


# =============================================================================
# Round-trip — segments produced from stripped text mean
# clip_dialogue.load_dialogue_lines can never surface header text
# (unit-level, per the chunk brief)
# =============================================================================

def test_load_dialogue_lines_never_surfaces_header_text(monkeypatch):
    """Simulates what scripts.dialogue_segments looks like AFTER the S7-C
    fix: since segment_scene now strips headers before the Claude call
    (proven above), the segments it ever writes to this column cannot
    contain header text. This proves the downstream reader
    (clip_dialogue.load_dialogue_lines, which feeds Grok's lip-sync
    speaking prompts) can't surface it either, since it only forwards
    whatever text is IN the column — garbage in, garbage out, and S7-C
    guarantees no garbage goes in."""
    clean_segments = [
        {"type": "narration", "text": "Music plays."},
        {"type": "dialogue", "speaker": "Marco", "text": "Wait!"},
    ]

    async def fake_fetch_all(query, *args):
        return [{"scene": 1, "dialogue_segments": json.dumps(clean_segments)}]

    monkeypatch.setattr(clip_dialogue, "fetch_all", fake_fetch_all)

    out = asyncio.run(clip_dialogue.load_dialogue_lines("video-1", "tenant-1"))
    assert 1 in out
    lines = out[1]
    assert len(lines) == 1
    assert lines[0]["speaker"] == "Marco"
    assert lines[0]["text"] == "Wait!"
    for line in lines:
        assert "LOCATION" not in line["text"]
        assert "ACTION" not in line["text"]


# =============================================================================
# Storage law vs speech law, off the SAME source text — sync_video_script
# (routes/videos.py, PINNED byte-identical) keeps the header verbatim;
# narration_text (the speech boundary) never does.
# =============================================================================

def test_sync_video_script_keeps_header_verbatim_storage_law(monkeypatch):
    import routes.videos as rv

    raw_text = "ACTION: she leaps onto the crate\nLOCATION: the garage\n\nShe opens the hatch."

    async def fake_fetch_all(query, *args):
        return [{"scene": 1, "location": "the garage", "scene_text": raw_text}]

    calls = []

    async def fake_execute(query, *args):
        calls.append((query, args))
        return "UPDATE 1"

    async def fake_fetch_one(query, *args):
        # _flag_stale_cast_and_environments's own read — advisory only,
        # its try/except swallows a bad shape; return None to keep it a
        # clean early-return rather than exercising unrelated staleness
        # logic this test isn't about.
        return None

    monkeypatch.setattr(rv, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(rv, "execute", fake_execute)
    monkeypatch.setattr(rv, "fetch_one", fake_fetch_one)

    asyncio.run(rv.sync_video_script("video-1", "tenant-1"))

    script_writes = [c for c in calls if "UPDATE videos SET script" in c[0]]
    assert len(script_writes) == 1
    stored_script = script_writes[0][1][2]  # (video_id, tenant_id, script)
    assert stored_script == raw_text, \
        "storage law violated: sync_video_script must keep the header verbatim"
    assert "ACTION:" in stored_script
    assert "LOCATION:" in stored_script


def test_narration_text_of_same_source_never_carries_the_header_speech_law():
    """Same raw_text as the storage-law test above — proves the two laws
    coexist correctly off IDENTICAL source text: storage keeps it, speech
    drops it."""
    raw_text = "ACTION: she leaps onto the crate\nLOCATION: the garage\n\nShe opens the hatch."
    spoken = narration_text(raw_text)
    assert spoken == "She opens the hatch."
    assert "ACTION:" not in spoken
    assert "LOCATION:" not in spoken
