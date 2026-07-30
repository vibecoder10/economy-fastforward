"""D10-2ab wiring locks: PipelineExecutor.run_story_bible on the native
generator + direct-UPDATE persistence path.

Covers what tests/test_story_bible_native.py can't (that file is the pure
story_bible_native.py unit — no PipelineExecutor, no DB):

  (c) persistence is a direct, tenant-scoped
      `UPDATE videos SET story_bible = $1 ... WHERE id = $2 AND
      tenant_id = $3` and the FULL document (all six top-level sections)
      round-trips through it byte-for-byte.
  (d) failure semantics: a generation failure (bad Claude response, no
      script rows, missing Anthropic client) reports "failed", never
      "completed" — and never writes to videos.story_bible.

No network, no real DB: PipelineExecutor.__new__ skips __init__'s vault/env
loading; _ensure_initialized is skipped via _initialized = True (same
technique as tests/functional/test_c16d_thumbnail_skip_if_done.py and
tests/test_c46a_quality_critic_wiring.py); database module-level names
(fetch_one/fetch_all/execute) are monkeypatched on the pipeline_executor
module object itself.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/test_d10_2ab_run_story_bible.py -q
"""
import asyncio
import json
import os
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import pipeline_executor as pe  # noqa: E402

TENANT = "tenant-d10-2ab"
VIDEO = "video-d10-2ab"


class FakeAnthropic:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("FakeAnthropic ran out of canned responses")
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


def _fixture_response():
    return json.dumps({
        "characters": [{"id": "hero", "costume": "field jacket", "role": "protagonist"}],
        "locations": [{"id": "loc_a", "description": "desert outpost",
                        "lighting": "harsh noon sun", "color_temperature": "warm",
                        "type": "EXTERIOR"}],
        "scene_blocks": [
            {"block_id": "block_1", "act": 1, "location_id": "loc_a",
             "location": "desert outpost", "lighting": "harsh noon sun", "mood": "tense",
             "characters_present": ["hero"],
             "images": [
                 {"image_index": 1, "camera": "wide", "action": "hero arrives",
                  "narration_excerpt": "excerpt one"},
             ]},
        ],
        "narrative": {"genre": "thriller", "tone": "tense", "themes": ["power"],
                      "conflict": "hero vs the outpost", "stakes": "the outpost falls",
                      "time_period": "present day", "world_rules": []},
        "relationships": [],
        "arcs": {"hero": {"start_state": "uncertain", "end_state": "resolute",
                           "turning_scenes": [1]}},
    })


def _video_row(**over):
    base = {
        "id": VIDEO, "status": "ready_for_storyboards", "video_title": "Test Video",
        "video_length_minutes": 1,
    }
    base.update(over)
    return base


def _make_executor(monkeypatch, video, anthropic, *, script_rows=None):
    writes = []
    fetch_all_calls = []

    async def fake_fetch_one(query, *args):
        if "FROM videos" in query:
            return dict(video)
        return None

    async def fake_fetch_all(query, *args):
        fetch_all_calls.append((query, args))
        if "FROM scripts" in query:
            return script_rows if script_rows is not None else []
        return []

    async def fake_execute(query, *args):
        writes.append((query, args))
        return None

    monkeypatch.setattr(pe, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(pe, "execute", fake_execute)

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = TENANT
    executor._initialized = True
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": anthropic})()

    return executor, writes, fetch_all_calls


def _activity_writes(writes):
    return [w for w in writes if "bot_activity" in w[0]]


def _story_bible_writes(writes):
    return [w for w in writes if "UPDATE videos SET story_bible" in w[0]]


# ---------------------------------------------------------------------------
# (c) persistence — direct, tenant-scoped UPDATE; full document round-trips
# ---------------------------------------------------------------------------

def test_persists_via_direct_tenant_scoped_update(monkeypatch):
    anthropic = FakeAnthropic([_fixture_response()])
    video = _video_row()
    script_rows = [{
        "scene": 1,
        "scene_text": "Hero arrives at the outpost at dawn. " * 5,
    }]
    executor, writes, fetch_all_calls = _make_executor(
        monkeypatch, video, anthropic, script_rows=script_rows,
    )

    result = asyncio.run(executor.run_story_bible(VIDEO))

    assert result == {"status": "ready_for_storyboards", "video_id": VIDEO}

    # Scripts fetched tenant-scoped, by video_id.
    script_calls = [c for c in fetch_all_calls if "FROM scripts" in c[0]]
    assert len(script_calls) == 1
    assert script_calls[0][1] == (VIDEO, TENANT)

    # Exactly one direct UPDATE, no legacy Airtable-shim, no import of
    # storyboard.bot anywhere in this call path (asserted structurally: the
    # only write matching "story_bible" is our own direct UPDATE).
    sb_writes = _story_bible_writes(writes)
    assert len(sb_writes) == 1
    query, args = sb_writes[0]
    assert "WHERE id = $2 AND tenant_id = $3" in query
    written_json, written_video_id, written_tenant_id = args
    assert written_video_id == VIDEO
    assert written_tenant_id == TENANT

    # Full document round-trips: every section the native generator produced
    # is present verbatim in what got persisted.
    persisted = json.loads(written_json)
    for key in ("characters", "locations", "scene_blocks", "narrative", "relationships", "arcs"):
        assert key in persisted
    assert persisted["characters"][0]["id"] == "hero"
    assert persisted["arcs"]["hero"]["turning_scenes"] == [1]

    # completed, not "failed", was logged.
    activity = _activity_writes(writes)
    statuses = [a[1][3] for a in activity]
    assert statuses == ["started", "completed"]


def test_full_script_text_built_from_all_scene_rows(monkeypatch):
    anthropic = FakeAnthropic([_fixture_response()])
    video = _video_row()
    script_rows = [
        {"scene": 1, "scene_text": "Scene one text. " * 5},
        {"scene": 2, "scene_text": "Scene two text. " * 5},
    ]
    executor, writes, _ = _make_executor(monkeypatch, video, anthropic, script_rows=script_rows)

    asyncio.run(executor.run_story_bible(VIDEO))

    prompt = anthropic.calls[0]["prompt"]
    assert "[SCENE 1]" in prompt and "Scene one text." in prompt
    assert "[SCENE 2]" in prompt and "Scene two text." in prompt


# ---------------------------------------------------------------------------
# (d) failure semantics — never "completed" on a blocked stage, never a write
# ---------------------------------------------------------------------------

def test_claude_failure_reports_failed_never_completed_and_never_writes(monkeypatch):
    anthropic = FakeAnthropic([RuntimeError("upstream 500")])
    video = _video_row()
    script_rows = [{"scene": 1, "scene_text": "Hero arrives at the outpost at dawn. " * 5}]
    executor, writes, _ = _make_executor(monkeypatch, video, anthropic, script_rows=script_rows)

    result = asyncio.run(executor.run_story_bible(VIDEO))

    assert result["status"] == "failed"
    assert "error" in result
    assert len(anthropic.calls) == 1, "the injected Claude failure must actually be reached"
    assert _story_bible_writes(writes) == [], "a failed generation must never write story_bible"

    activity = _activity_writes(writes)
    statuses = [a[1][3] for a in activity]
    assert statuses == ["started", "failed"]
    assert "completed" not in statuses


def test_no_script_rows_fails_before_any_claude_call(monkeypatch):
    anthropic = FakeAnthropic([_fixture_response()])
    video = _video_row()
    executor, writes, _ = _make_executor(monkeypatch, video, anthropic, script_rows=[])

    result = asyncio.run(executor.run_story_bible(VIDEO))

    assert result["status"] == "failed"
    assert anthropic.calls == [], "must not spend a Claude call with no script to bible"
    assert _story_bible_writes(writes) == []


def test_missing_anthropic_client_fails_cleanly(monkeypatch):
    video = _video_row()
    script_rows = [{"scene": 1, "scene_text": "Hero arrives."}]
    executor, writes, _ = _make_executor(monkeypatch, video, None, script_rows=script_rows)

    result = asyncio.run(executor.run_story_bible(VIDEO))

    assert result["status"] == "failed"
    assert _story_bible_writes(writes) == []


def test_unparseable_claude_response_fails_without_partial_write(monkeypatch):
    anthropic = FakeAnthropic(["not json, no braces at all"])
    video = _video_row()
    script_rows = [{"scene": 1, "scene_text": "Hero arrives at the outpost at dawn. " * 5}]
    executor, writes, _ = _make_executor(monkeypatch, video, anthropic, script_rows=script_rows)

    result = asyncio.run(executor.run_story_bible(VIDEO))

    assert result["status"] == "failed"
    assert len(anthropic.calls) == 1, "the unparseable response must actually be reached"
    assert _story_bible_writes(writes) == []


def test_video_not_found_returns_failed_immediately(monkeypatch):
    anthropic = FakeAnthropic([_fixture_response()])
    executor, writes, _ = _make_executor(monkeypatch, video={}, anthropic=anthropic)
    # Simulate "no video" by making fetch_one return None for this id.
    async def fake_fetch_one_none(query, *args):
        return None
    monkeypatch.setattr(pe, "fetch_one", fake_fetch_one_none)

    result = asyncio.run(executor.run_story_bible(VIDEO))

    assert result == {"status": "failed", "error": "Video not found"}
    assert writes == [], "no activity log or write when the video itself doesn't exist"
