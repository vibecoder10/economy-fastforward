"""S7 follow-up — the CAPTION boundary for LOCATION:/ACTION: stage headers
(sibling of tests/functional/test_s7_c_speech_boundary.py, same law pair).

S7-A's storage law: scripts.scene_text keeps a scene's LOCATION:/ACTION:
header lines VERBATIM — text is never rewritten at storage. S7-C closed the
SPEECH boundaries (voice/run.py narration_text, dialogue_intelligence.
segment_scene), so the audio a scene actually gets is header-free. That
left the CAPTION side segmenting the RAW stored text: a header line became
its own caption/asset row with no matching audio underneath (an on-screen
artifact), and — the subtler desync — the deterministic splitter computes
words-per-second as total_word_count / voice_duration, so header words the
narrator never reads inflated the word count and skewed EVERY segment's
duration share, not just the header row's.

Two caption boundaries close this, both through ONE shared strip —
story_laws.strip_scene_stage_headers (which chains the module's own two
extractors, order-independent, so no third stripping dialect can drift):

  1. pipeline_executor.PipelineExecutor.run_split — segments scene_text
     into assets.sentence_text caption rows with per-row durations.
  2. render_static._gather_segments — the per-scene segment dicts every
     render-side consumer of scene_text reads (today the music-mood pass;
     any future caption use inherits the clean text automatically).

Storage law vs caption law are proven off the SAME source text below, so a
regression in either direction (over-stripping storage, or under-stripping
captions) fails an assertion rather than passing silently. sync_video_script
stays byte-identical (settled decision P11) and is deliberately NOT touched
or re-tested here — test_s7_c_speech_boundary.py already pins it.

STASH-PROOF: this file imports story_laws.strip_scene_stage_headers at
module level — that symbol does not exist before this fix, so reverting the
fix makes the whole file fail at COLLECTION (ImportError). The run_split
tests independently fail on BEHAVIOR pre-fix (the header shows up in an
inserted sentence_text and every duration shifts), since run_split's
signature doesn't change — belt and suspenders, same convention as the
S7-C file.

Local/no-spend: every DB call is a fake fetch_all/fetch_one/execute — same
convention as tests/test_sfx_guard_auto_advance.py and
tests/functional/test_s7_c_speech_boundary.py. run_split makes no API
calls by design ("pure Python, fast and free").

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_s7_caption_boundary.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

VIDEO_PIPELINE = Path(__file__).parents[4] / "skills" / "video-pipeline"
if str(VIDEO_PIPELINE) not in sys.path:
    sys.path.insert(0, str(VIDEO_PIPELINE))

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

# Stash-proof anchor: this symbol is the fix. Pre-fix, collection dies here.
from story_laws import strip_scene_stage_headers  # noqa: E402

import pipeline_executor as pe_mod  # noqa: E402
from pipeline_executor import PipelineExecutor  # noqa: E402
import render_static  # noqa: E402
from shared.clients.deterministic_splitter import segment_scene_deterministic  # noqa: E402

TENANT = "tenant-caption-boundary"
VIDEO = "video-caption-boundary"

# The same raw shape the S7-C file uses for its storage-vs-speech pair:
# both headers, then prose. Multiple sentences so the splitter has real
# per-sentence work to do (a single sentence would trivially survive any
# duration skew).
RAW_BOTH = (
    "LOCATION: the garage\n"
    "ACTION: she dances on the workbench\n"
    "\n"
    "Music plays through the open door. She spins once across the concrete "
    "floor. The neighbors stop to watch her from the driveway. Nobody says "
    "a word until the song ends."
)
PROSE_ONLY = (
    "Music plays through the open door. She spins once across the concrete "
    "floor. The neighbors stop to watch her from the driveway. Nobody says "
    "a word until the song ends."
)


# =============================================================================
# The shared strip itself — story_laws.strip_scene_stage_headers
# =============================================================================

def test_strip_removes_both_headers_location_first():
    assert strip_scene_stage_headers(RAW_BOTH) == PROSE_ONLY


def test_strip_removes_both_headers_action_first():
    text = (
        "ACTION: she dances on the workbench\n"
        "LOCATION: the garage\n\n" + PROSE_ONLY
    )
    assert strip_scene_stage_headers(text) == PROSE_ONLY


def test_strip_removes_single_header_of_either_kind():
    assert strip_scene_stage_headers(
        "LOCATION: the kitchen\n\nShe stirs the soup slowly."
    ) == "She stirs the soup slowly."
    assert strip_scene_stage_headers(
        "ACTION: she jumps on the table\n\nThe room falls silent."
    ) == "The room falls silent."


def test_strip_handles_markdown_bold_headers():
    """The extractors already tolerate bold labels (S7-A follow-ups) — the
    chained strip must inherit that, both bold shapes."""
    assert strip_scene_stage_headers(
        "**LOCATION:** the garage\n**ACTION:** she dances\n\nMusic plays."
    ) == "Music plays."
    assert strip_scene_stage_headers(
        "**ACTION**: she dances\n**LOCATION**: the garage\n\nMusic plays."
    ) == "Music plays."


def test_strip_is_byte_identical_when_no_headers():
    assert strip_scene_stage_headers(PROSE_ONLY) == PROSE_ONLY


def test_strip_keeps_mid_text_header_shaped_lines():
    """Only LEADING headers are storage metadata — a header-shaped line deep
    in the narration is ordinary prose, exactly like the extractors' own
    contract (and voice/run.py's strip)."""
    text = "She waits.\nACTION: she dances\nThen leaves."
    assert strip_scene_stage_headers(text) == text


def test_strip_empty_and_none():
    assert strip_scene_stage_headers("") == ""
    assert strip_scene_stage_headers(None) == ""


def test_strip_headers_only_scene_becomes_empty():
    """A scene that is NOTHING but stage directions has no speech and must
    yield no caption text at all."""
    assert strip_scene_stage_headers(
        "LOCATION: the garage\nACTION: she dances"
    ) == ""


def test_strip_matches_chained_extractors_exactly():
    """The helper must be byte-identical to chaining the module's own two
    extractors — no third stripping dialect (mirrors the S7-C file's
    scene-block-matches-story-laws pin)."""
    import story_laws
    for text in (RAW_BOTH, PROSE_ONLY, "LOCATION: x\n\nBody.", ""):
        _, after_location = story_laws.extract_scene_location(text)
        _, expected = story_laws.extract_scene_action(after_location)
        assert strip_scene_stage_headers(text) == expected


# =============================================================================
# Caption boundary 1 — PipelineExecutor.run_split (assets.sentence_text)
# =============================================================================

class _FakeDB:
    """Captures every write; serves the two reads run_split makes."""

    def __init__(self, script_rows, existing_cnt: int = 0):
        self.script_rows = script_rows
        self.existing_cnt = existing_cnt
        self.calls: list[tuple[str, tuple]] = []

    async def fetch_all(self, query, *args):
        assert "FROM scripts" in query, f"unexpected fetch_all: {query}"
        return self.script_rows

    async def fetch_one(self, query, *args):
        if "video_title" in query:
            return {"video_title": "Caption Boundary Test"}
        if "COUNT(*)" in query:
            return {"cnt": self.existing_cnt}
        raise AssertionError(f"unexpected fetch_one: {query}")

    async def execute(self, query, *args):
        self.calls.append((query, args))
        return "OK"

    def asset_inserts(self):
        return [c for c in self.calls if "INSERT INTO assets" in c[0]]


def _run_split_with(monkeypatch, script_rows, existing_cnt: int = 0):
    db = _FakeDB(script_rows, existing_cnt=existing_cnt)
    monkeypatch.setattr(pe_mod, "fetch_all", db.fetch_all)
    monkeypatch.setattr(pe_mod, "fetch_one", db.fetch_one)
    monkeypatch.setattr(pe_mod, "execute", db.execute)
    result = asyncio.run(PipelineExecutor(TENANT).run_split(VIDEO))
    return db, result


def test_run_split_sentence_text_matches_stripped_segmentation(monkeypatch):
    """THE fix: the caption rows run_split writes must be exactly what the
    splitter produces from the STRIPPED text — same texts, same durations —
    because that stripped text is what the voice step actually synthesized
    (S7-C). Text AND duration are both asserted: the duration half is the
    timing-desync leg (header words inflate the word count the splitter
    divides voice_duration across, shifting every row, not just one)."""
    voice_duration = 16.0
    db, result = _run_split_with(monkeypatch, [{
        "id": "s1", "scene": 1, "scene_text": RAW_BOTH,
        "voice_over_url": "http://x/1.mp3",
        "voice_duration_seconds": voice_duration,
    }])
    assert result["status"] == "completed", result
    assert result["scenes_split"] == 1

    inserted = [(a[6], a[7]) for _, a in db.asset_inserts()]
    expected = [
        (s["text"], s["duration"])
        for s in segment_scene_deterministic(
            strip_scene_stage_headers(RAW_BOTH), voice_duration
        )
    ]
    assert inserted == expected

    for text, _ in inserted:
        assert "LOCATION" not in text and "ACTION" not in text
        assert "the garage" not in text  # header VALUES die with their lines
        assert "workbench" not in text

    # Non-vacuous: segmenting the RAW text (the pre-fix behavior) genuinely
    # differs — the header surfaces in a caption row and the timing shifts —
    # so this test fails before the fix rather than passing by accident.
    raw = [
        (s["text"], s["duration"])
        for s in segment_scene_deterministic(RAW_BOTH, voice_duration)
    ]
    assert raw != expected
    assert any("LOCATION" in text for text, _ in raw)


def test_run_split_headers_only_scene_writes_no_caption_rows(monkeypatch):
    """A scene that is ONLY stage directions has no speech — pre-fix it
    minted a phantom caption row with the whole voice duration under it;
    now it is skipped entirely, same as an empty scene."""
    db, result = _run_split_with(monkeypatch, [{
        "id": "s1", "scene": 1,
        "scene_text": "LOCATION: the garage\nACTION: she dances",
        "voice_over_url": "http://x/1.mp3",
        "voice_duration_seconds": 3.0,
    }])
    assert result["status"] == "completed", result
    assert result["scenes_split"] == 0
    assert result["total_segments"] == 0
    assert db.asset_inserts() == []


def test_run_split_headerless_scene_behavior_unchanged(monkeypatch):
    """Regression: a scene with no headers segments exactly as before the
    fix — the strip is byte-identical on plain prose."""
    voice_duration = 12.0
    db, result = _run_split_with(monkeypatch, [{
        "id": "s1", "scene": 1, "scene_text": PROSE_ONLY,
        "voice_over_url": "http://x/1.mp3",
        "voice_duration_seconds": voice_duration,
    }])
    assert result["status"] == "completed", result
    inserted = [(a[6], a[7]) for _, a in db.asset_inserts()]
    expected = [
        (s["text"], s["duration"])
        for s in segment_scene_deterministic(PROSE_ONLY, voice_duration)
    ]
    assert inserted == expected and inserted


def test_run_split_never_writes_scripts_storage_law(monkeypatch):
    """Storage law leg for THIS boundary: run_split strips for its CAPTION
    rows only — it must never rewrite scripts.scene_text (the verbatim
    guarantee lives at storage, per S7-A / settled decision P11)."""
    db, result = _run_split_with(monkeypatch, [{
        "id": "s1", "scene": 1, "scene_text": RAW_BOTH,
        "voice_over_url": "http://x/1.mp3",
        "voice_duration_seconds": 16.0,
    }])
    assert result["status"] == "completed", result
    for query, _ in db.calls:
        assert "UPDATE scripts" not in query
        assert "INSERT INTO scripts" not in query


# =============================================================================
# Caption boundary 2 — render_static._gather_segments (render-side dicts)
# =============================================================================

def _patch_render_static_db(monkeypatch, script_rows, asset_rows):
    async def fake_fetch_all(query, *args):
        if "FROM scripts" in query:
            return script_rows
        if "FROM assets" in query:
            return asset_rows
        raise AssertionError(f"unexpected fetch_all: {query}")

    monkeypatch.setattr(render_static, "fetch_all", fake_fetch_all)


def _asset_row(scene: int) -> dict:
    return {
        "scene": scene, "image_index": 1, "image_url": "http://x/img.png",
        "generation_method": "static_docu", "hero_shot": True,
        "caption": None, "transition_kind": None,
    }


def test_gather_segments_scene_text_is_header_free(monkeypatch):
    script_rows = [{
        "scene": 1, "scene_text": RAW_BOTH,
        "voice_over_url": "http://x/1.mp3", "voice_duration_seconds": 16.0,
    }]
    _patch_render_static_db(monkeypatch, script_rows, [_asset_row(1)])

    segments = asyncio.run(render_static._gather_segments(VIDEO, TENANT))
    assert len(segments) == 1
    assert segments[0]["scene_text"] == PROSE_ONLY
    assert "LOCATION" not in segments[0]["scene_text"]
    assert "ACTION" not in segments[0]["scene_text"]
    # The row itself (what storage holds) still carries the headers — the
    # strip happens at the render boundary, never against the source.
    assert script_rows[0]["scene_text"] == RAW_BOTH


def test_gather_segments_headerless_scene_text_unchanged(monkeypatch):
    _patch_render_static_db(monkeypatch, [{
        "scene": 1, "scene_text": PROSE_ONLY,
        "voice_over_url": "http://x/1.mp3", "voice_duration_seconds": 16.0,
    }], [_asset_row(1)])

    segments = asyncio.run(render_static._gather_segments(VIDEO, TENANT))
    assert segments[0]["scene_text"] == PROSE_ONLY


# =============================================================================
# Storage law vs caption law, off the SAME source text (mirrors the S7-C
# file's closing pair) — storage keeps the headers verbatim; neither caption
# boundary ever surfaces them.
# =============================================================================

def test_storage_keeps_headers_captions_never_do_same_source(monkeypatch):
    stored = RAW_BOTH  # what scripts.scene_text holds, verbatim (S7-A)

    db, result = _run_split_with(monkeypatch, [{
        "id": "s1", "scene": 1, "scene_text": stored,
        "voice_over_url": "http://x/1.mp3",
        "voice_duration_seconds": 16.0,
    }])
    assert result["status"] == "completed", result

    # Storage law: the source row is untouched, headers verbatim.
    assert "LOCATION: the garage" in stored
    assert "ACTION: she dances on the workbench" in stored

    # Caption law: no caption row anywhere carries either header.
    caption_texts = [a[6] for _, a in db.asset_inserts()]
    assert caption_texts, "expected caption rows for the prose"
    for text in caption_texts:
        assert "LOCATION" not in text
        assert "ACTION" not in text
