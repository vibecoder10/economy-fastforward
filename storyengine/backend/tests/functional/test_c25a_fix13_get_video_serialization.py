"""Regression test for C25a-fix13 (live-evidence bug, 2026-07-20): a real
connected-Claude MCP session called `get_video` and the server returned a
serialization error instead of the video summary.

Root cause: `videos.video_length_minutes` is a Postgres NUMERIC column
(schema.sql), so asyncpg hands it back as a `decimal.Decimal`.
`actions.video_summary()` put that value straight onto the `length_min` key
with no cast — unlike `total_cost`/`max_spend` on the SAME return dict,
which already go through an explicit `float(...)` (the NUMERIC columns
right next to it). `routes/mcp.py`'s `_text_result()` then calls
`json.dumps(payload)` with no `default=`, which raises
`TypeError: Object of type Decimal is not JSON serializable` the moment a
real (non-NULL) video_length_minutes reaches it — exactly what a fully
populated prod video row (e.g. cd5d2883) has, and exactly why the C26/C27/
C29 test suites' `video_summary` stubs (plain ints/strings, never a real
Decimal) never caught this.

Fix: `actions.video_summary()` now casts video_length_minutes the same way
it already casts total_cost/max_spend, and the same way
`routes/videos.py`'s own GET /api/videos/{id} handler already casts this
identical column (`float(r["video_length_minutes"]) if ... else None`).

Non-vacuous: `test_get_video_serializes_a_fully_populated_prod_shaped_row`
fails against the pre-fix code with the exact TypeError above (confirmed
via `git stash` before this file was added — see the chunk's report for the
raw traceback).

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c25a_fix13_get_video_serialization.py -q
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from decimal import Decimal
from unittest.mock import patch

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import actions  # noqa: E402
import routes.mcp as mcp_mod  # noqa: E402

TENANT = "tenant-1"
VIDEO_ID = "cd5d2883-0000-0000-0000-000000000000"

# Shaped like a REAL, fully-populated prod video row — every NUMERIC column
# comes back from asyncpg as Decimal, not int/float/None. This is the shape
# the C26/C27/C29 stubs never used (they hand-wrote plain-Python dicts).
_FAKE_VIDEO_ROW = {
    "video_title": "Real Prod Video",
    "status": "in_progress",
    "video_length_minutes": Decimal("10"),
    "video_model": "grok-imagine",
    "script_validation": "ok",
    "render_style": "cinematic",
    "total_cost": Decimal("4.50"),
    "max_spend": Decimal("50.00"),
    # feat/approval-gates: video_summary()'s SELECT now also reads these two
    # columns (the anchors-gate approval markers) — a fully-populated prod
    # row has them set once the cast/locations are locked.
    "characters_approved_at": "2026-06-18T22:01:52.293086+00:00",
    "environments_approved_at": "2026-06-18T20:15:53.569797+00:00",
}
_FAKE_SCRIPTS_ROW = {"scenes": 5, "boards": 5, "voiced": 5, "max_scene": 5}
_FAKE_ASSETS_ROW = {"pics": 10, "clips": 5}
_FAKE_CHARACTERS_ROW = {"n": 2}
# feat/approval-gates: video_summary() added a sibling environments count
# query right next to the characters one above.
_FAKE_ENVIRONMENTS_ROW = {"n": 3}


async def _fake_fetch_one(query, *args):
    q = query.lower()
    if "from videos" in q:
        return dict(_FAKE_VIDEO_ROW)
    if "from scripts" in q:
        return dict(_FAKE_SCRIPTS_ROW)
    if "from assets" in q:
        return dict(_FAKE_ASSETS_ROW)
    if "from video_characters" in q:
        return dict(_FAKE_CHARACTERS_ROW)
    if "from video_environments" in q:
        return dict(_FAKE_ENVIRONMENTS_ROW)
    raise AssertionError(f"unexpected fetch_one query: {query!r}")


async def test_get_video_serializes_a_fully_populated_prod_shaped_row():
    """The exact live-tonight repro: get_video against a row with a real
    (non-NULL) NUMERIC video_length_minutes must not raise, and the
    resulting MCP content must be valid, round-trippable JSON."""
    with patch.object(actions, "fetch_one", _fake_fetch_one):
        result = await mcp_mod._call_get_video(TENANT, {"video_id": VIDEO_ID})

    assert result["isError"] is False, f"get_video errored: {result}"
    text = result["content"][0]["text"]
    payload = json.loads(text)  # would already have raised TypeError pre-fix
    assert payload["length_min"] == 10.0
    assert isinstance(payload["length_min"], float)
    assert payload["total_cost"] == 4.5
    assert payload["max_spend"] == 50.0
    print("✅ test_get_video_serializes_a_fully_populated_prod_shaped_row")


async def test_video_summary_length_min_is_none_when_column_is_null():
    """The other half of the cast: an unset video_length_minutes (NULL,
    common pre-length-picked videos) must stay None, not become 0.0 or
    error — matching the existing total_cost/max_spend None-handling right
    next to it in the same function."""
    row = dict(_FAKE_VIDEO_ROW)
    row["video_length_minutes"] = None

    async def _fetch_one_null(query, *args):
        q = query.lower()
        if "from videos" in q:
            return dict(row)
        if "from scripts" in q:
            return dict(_FAKE_SCRIPTS_ROW)
        if "from assets" in q:
            return dict(_FAKE_ASSETS_ROW)
        if "from video_characters" in q:
            return dict(_FAKE_CHARACTERS_ROW)
        if "from video_environments" in q:
            return dict(_FAKE_ENVIRONMENTS_ROW)
        raise AssertionError(f"unexpected fetch_one query: {query!r}")

    with patch.object(actions, "fetch_one", _fetch_one_null):
        summary = await actions.video_summary(TENANT, VIDEO_ID)
    assert summary["length_min"] is None
    json.dumps(summary)  # must still be JSON-serializable
    print("✅ test_video_summary_length_min_is_none_when_column_is_null")


TESTS_ASYNC = [
    test_get_video_serializes_a_fully_populated_prod_shaped_row,
    test_video_summary_length_min_is_none_when_column_is_null,
]


def main() -> int:
    failed = 0
    for t in TESTS_ASYNC:
        try:
            asyncio.run(t())
        except AssertionError as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
    total = len(TESTS_ASYNC)
    print(f"\n{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
