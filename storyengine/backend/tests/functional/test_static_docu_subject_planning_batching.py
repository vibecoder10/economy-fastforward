"""Tests for the subject-planning batching fix (2026-08-03 live incident).

Root cause: the static-documentary pictures stage failed for ALL 23 scenes
of a real video in 31 seconds with "no segment reached 2 verified views
(scenes failed: 1..23)". `_scene_subjects` planned title-card metadata for
the WHOLE roster in ONE Claude call at a flat `max_tokens=1800`. A 23-scene
roster needs roughly 3,500-4,500 output tokens, so the JSON array reply
truncated mid-array. `_parse_json_array` is deliberately strict (one
`re.search(r"\\[.*\\]")` then `json.loads`, no salvage), so the truncated
reply parsed to None, `_scene_subjects` returned {} for every scene, and
every scene then bounced on the metadata gate in `_one_scene` — reported via
the misleading aggregate "no segment reached N verified views" even though
zero images were ever attempted. A 5-scene video fit under 1800 tokens,
which is why past live tests of this stage passed.

Fix (static_docu.py):
- `_scene_subjects` now plans in chunks of `_SUBJECTS_CHUNK_SIZE` scenes per
  call, each sized its own generous `max_tokens` budget, and merges the
  per-chunk dicts. A chunk whose reply fails to parse gets ONE retry; scenes
  still unparseable after the retry are returned by scene number
  (`unparseable_scenes`) instead of silently vanishing into an empty dict.
- `_one_scene` tags a scene that hit that failure mode with the distinct
  reason `subject_planning_unparseable` (was lumped into the generic
  `missing_title_metadata`).
- `generate_static_images_for_video`'s aggregate failure path now reports
  "subject planning produced no title-card metadata for scenes X, Y — model
  reply unparseable/truncated" when that's what actually happened, instead
  of blaming "verified views" for a scene that never reached image
  generation at all.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_static_docu_subject_planning_batching.py -q
"""
import json
import os
import re
import sys

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import static_docu  # noqa: E402

# Pre-import for the same reason every other static_docu test file does:
# anthropic's _base_client.py subclasses httpx.AsyncClient at MODULE IMPORT
# time, so it must finish loading before any test monkeypatches
# httpx.AsyncClient to a fake callable (via test_static_docu_qa_park's
# _pipeline_env, used below for the end-to-end test).
import shared.clients.image_client as image_client_mod  # noqa: E402

from test_static_docu_qa_park import _pipeline_env  # noqa: E402


def _scene_numbers_in_prompt(prompt: str) -> list[int]:
    """Scene numbers a chunk's prompt covers, read off the `[n] ...` segment
    markers _scene_subjects_chunk builds — lets a fake client reply
    correctly no matter how the caller chunked the roster."""
    return [int(n) for n in re.findall(r"^\[(\d+)\]", prompt, re.MULTILINE)]


def _valid_reply_for(prompt: str) -> str:
    nums = _scene_numbers_in_prompt(prompt)
    items = [
        {
            "scene": n,
            "machine": f"Test Machine {n}",
            "aliases": [],
            "caption_title": f"Machine {n}",
            "caption_sub": f"Operator {n} • 1950-1960",
            "caption_specs": [f"Spec {n}"],
            "detail_focus": "engine nacelle",
            "search_query": f"Test Machine {n} prototype",
        }
        for n in nums
    ]
    return json.dumps(items)


class _ScriptedTextClient:
    """Fake Claude text client. `behavior(call_index, prompt) -> str` decides
    each call's raw reply, so a test can script exactly which call in the
    chunk sequence fails."""

    def __init__(self, behavior):
        self._behavior = behavior
        self.calls: list[dict] = []

    async def generate(self, **kwargs):
        idx = len(self.calls)
        self.calls.append(kwargs)
        return self._behavior(idx, kwargs["prompt"])


def _install_client(monkeypatch, client):
    import kie_unified

    async def fake_get_text_client_for_tenant(tenant_id):
        return client

    monkeypatch.setattr(
        kie_unified, "get_text_client_for_tenant", fake_get_text_client_for_tenant
    )


def _scenes(n: int) -> list[dict]:
    return [
        {"scene": i, "scene_text": f"Segment {i} narration about a test machine."}
        for i in range(1, n + 1)
    ]


# ---------------------------------------------------------------------------
# (a) 23 scenes -> multiple planning calls, whose merged output covers all
#     23 scenes. This is the direct regression test for the live incident:
#     before the fix, this was ONE call with max_tokens=1800 and (with a
#     real model) would have truncated; the fix's own contract is "never one
#     call for a roster this size".
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_23_scene_roster_is_planned_in_multiple_calls_covering_every_scene(
    monkeypatch,
):
    client = _ScriptedTextClient(lambda idx, prompt: _valid_reply_for(prompt))
    _install_client(monkeypatch, client)

    scenes = _scenes(23)
    subjects, unparseable = await static_docu._scene_subjects("tenant", scenes, None)

    assert unparseable == []
    assert set(subjects.keys()) == set(range(1, 24))
    for scene_num, sub in subjects.items():
        assert sub["machine"] == f"Test Machine {scene_num}"

    # The whole point of the fix: never plan a 23-scene roster in one call.
    assert len(client.calls) > 1
    for call in client.calls:
        nums = _scene_numbers_in_prompt(call["prompt"])
        assert 0 < len(nums) <= static_docu._SUBJECTS_CHUNK_SIZE
        # each call's own budget scales with its chunk, not a flat 1800
        assert call["max_tokens"] == static_docu._subjects_chunk_max_tokens(len(nums))


@pytest.mark.asyncio
async def test_small_roster_still_only_needs_one_call(monkeypatch):
    """A 5-scene video (the size that happened to pass live before this fix)
    should still cost exactly one planning call — the fix must not make the
    common case chattier than it needs to be."""
    client = _ScriptedTextClient(lambda idx, prompt: _valid_reply_for(prompt))
    _install_client(monkeypatch, client)

    scenes = _scenes(5)
    subjects, unparseable = await static_docu._scene_subjects("tenant", scenes, None)

    assert unparseable == []
    assert set(subjects.keys()) == {1, 2, 3, 4, 5}
    assert len(client.calls) == 1


# ---------------------------------------------------------------------------
# (b) One chunk's reply is unparseable (simulating truncation) -> only THAT
#     chunk's scenes are retried; the other chunks' scenes are unaffected
#     (single failed call, not re-planned).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_one_truncated_chunk_is_retried_without_touching_other_chunks(
    monkeypatch,
):
    # 23 scenes / chunk size 6 -> chunks are [1-6], [7-12], [13-18], [19-23].
    # Call index 1 is the FIRST attempt at the [7-12] chunk — make it come
    # back truncated (no closing bracket at all, the real-world failure
    # mode), succeed on the immediate retry.
    def behavior(idx, prompt):
        if idx == 1:
            return '[{"scene": 7, "machine": "Test Machine 7", "aliases": [' \
                   '"partial and cut off mid-strin'
        return _valid_reply_for(prompt)

    client = _ScriptedTextClient(behavior)
    _install_client(monkeypatch, client)

    scenes = _scenes(23)
    subjects, unparseable = await static_docu._scene_subjects("tenant", scenes, None)

    assert unparseable == []
    assert set(subjects.keys()) == set(range(1, 24))
    # 4 chunks + 1 retry for the one that came back truncated.
    assert len(client.calls) == 5

    failed_call_scenes = _scene_numbers_in_prompt(client.calls[1]["prompt"])
    retry_call_scenes = _scene_numbers_in_prompt(client.calls[2]["prompt"])
    assert failed_call_scenes == [7, 8, 9, 10, 11, 12]
    # The retry re-sends the SAME chunk, not a different one.
    assert retry_call_scenes == failed_call_scenes

    # Chunks before and after the failed one used exactly one call each —
    # the failure/retry is isolated to its own chunk, not the whole roster.
    assert _scene_numbers_in_prompt(client.calls[0]["prompt"]) == [1, 2, 3, 4, 5, 6]
    assert _scene_numbers_in_prompt(client.calls[3]["prompt"]) == [13, 14, 15, 16, 17, 18]
    assert _scene_numbers_in_prompt(client.calls[4]["prompt"]) == [19, 20, 21, 22, 23]


@pytest.mark.asyncio
async def test_chunk_unparseable_on_both_attempts_only_loses_its_own_scenes(
    monkeypatch,
):
    """When a chunk fails BOTH the first attempt and its retry, only that
    chunk's scenes end up in `unparseable` — every other chunk's scenes are
    still fully planned."""

    def behavior(idx, prompt):
        # Calls 1 and 2 are the two attempts for the [7-12] chunk.
        if idx in (1, 2):
            return "not JSON at all, and no brackets either"
        return _valid_reply_for(prompt)

    client = _ScriptedTextClient(behavior)
    _install_client(monkeypatch, client)

    scenes = _scenes(23)
    subjects, unparseable = await static_docu._scene_subjects("tenant", scenes, None)

    assert sorted(unparseable) == [7, 8, 9, 10, 11, 12]
    assert set(subjects.keys()) == set(range(1, 24)) - set(unparseable)
    # chunk0 (1 call) + chunk1 (2 attempts) + chunk2 (1) + chunk3 (1) = 5
    assert len(client.calls) == 5


# ---------------------------------------------------------------------------
# (c) Planning that produces nothing at all (every chunk unparseable, both
#     attempts) must surface a TRUTHFUL error naming the planning failure
#     and the affected scenes — not the generic "no segment reached N
#     verified views" message that made the live incident (correctly) look
#     like an image-QA problem when zero images were ever attempted.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_reports_planning_failure_by_name_not_verified_views(monkeypatch):
    import kie_unified

    env = _pipeline_env(
        monkeypatch,
        verdicts=[],
        gen_urls=[],
        docu_module=static_docu,
        image_client_module=image_client_mod,
    )

    async def fake_fetch_all_two_scenes(query, *args):
        if "FROM scripts" in query:
            return [
                {"scene": 1, "scene_text": "Segment one text about a tank."},
                {"scene": 2, "scene_text": "Segment two text about a plane."},
            ]
        return []

    monkeypatch.setattr(static_docu, "fetch_all", fake_fetch_all_two_scenes)

    class _BrokenTextClient:
        async def generate(self, **kwargs):
            return "Sorry, I can't help with that — no JSON here."

    async def fake_get_text_client_for_tenant(tenant_id):
        return _BrokenTextClient()

    monkeypatch.setattr(
        kie_unified, "get_text_client_for_tenant", fake_get_text_client_for_tenant
    )

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"]
    )

    assert result["status"] == "failed"
    assert "subject planning produced no title-card metadata" in result["error"]
    assert "scenes 1, 2" in result["error"]
    assert "verified views" not in result["error"]
    # No image door was ever opened for either scene.
    assert env["gen_prompts"] == []
