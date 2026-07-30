"""D9-1 (Custom Film director ShotDraft harvest, migration 147): store_scene
must stamp assets.purpose_kind / assets.shot_purpose from the parsed
coverage plan's frame dicts, exactly like it already does for assets.
shot_location / assets.group_arrangement (migration 143).

This is the ONE place a coverage picture ever becomes an `assets` row —
confirmed by reading coverage_to_app.py: the sheet-preview planning path
(generate_storyboard_sheet_for_scene) never inserts an asset row at all
("Storyboard SHEETS are a preview, not an asset row" — its own comment); it
only persists the parsed plan (scripts.coverage_directive) and draws grid
PREVIEW images into scripts.storyboard_N_url. Both that path and the real
per-shot picture path call the SAME shared storyboard.coverage.
plan_moments_deterministic (C7 fix (a)), so both read identical parsed
purpose_kind/shot_purpose fields off a shot dict — this test proves the
one path that turns those fields into a persisted DB column does so
correctly.

No network, no real DB: database/storage/vault/kie_unified/actions are
stubbed at import time (mirrors test_d3_62_image_prompt_truncation.py's
module-stub pattern). store_scene is exercised directly with a captured
`execute` mock so the test proves what actually lands in the SQL
parameters, not just that the function runs without raising.

Run: cd storyengine/backend && ./venv/bin/python -m pytest \
    tests/functional/test_d9_1_shot_purpose_stamp.py -q
"""
import asyncio
import os
import re
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


_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom)
_stub("storage", upload_bytes=_boom)
_stub("vault", get_secret=_boom)
_stub("kie_unified", get_text_client_for_tenant=_boom)
_stub("actions", picture_price_for=lambda model_label=None: 0.05)

from scripts.coverage_to_app import store_scene  # noqa: E402

VIDEO_ID = "22222222-2222-2222-2222-222222222222"
TENANT_ID = "tenant-1"


def _run_store_scene(frames_by_moment, tmp_path):
    """Writes each frame's bytes to a real temp file (store_scene reads
    fr["_path"] off disk) and captures the INSERT INTO assets SQL params."""
    captured = []

    async def fake_execute(sql, *params):
        if "INSERT INTO assets" in sql:
            captured.append(params)
        return None

    async def fake_upload_bytes(*a, **k):
        return "https://img/fake.png"

    with patch("scripts.coverage_to_app.execute", AsyncMock(side_effect=fake_execute)), \
         patch("scripts.coverage_to_app.upload_bytes", AsyncMock(side_effect=fake_upload_bytes)), \
         patch("scripts.coverage_to_app.record_ledger_entry", AsyncMock(return_value=None)):
        n = asyncio.run(store_scene(
            VIDEO_ID, TENANT_ID, "Test Video", "16:9", 1, frames_by_moment,
        ))
    return n, captured


def _frame(tmp_path, name, **overrides):
    img_path = tmp_path / name
    img_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    base = {
        "role": "master", "shot_type": "WS", "description": "wide shot",
        "_path": str(img_path), "camera_move": None, "routed_model": None,
        "routing_reason": None, "duration_seconds": None, "image_model": None,
        "shot_location": None, "group_arrangement": None,
        "purpose_kind": None, "shot_purpose": None,
    }
    base.update(overrides)
    return base


def test_store_scene_stamps_purpose_kind_and_shot_purpose(tmp_path):
    """The decisive test: a frame carrying purpose_kind/shot_purpose (as
    generate_coverage_frames now threads them from the parsed shot dict)
    must land in the INSERT's purpose_kind/shot_purpose SQL parameters."""
    frames_by_moment = [(
        "moment 1 summary",
        [_frame(tmp_path, "frame1.png",
                purpose_kind="spatial",
                shot_purpose="shows how Ryan gets from the pod to the corridor")],
        None, None,
    )]
    n, captured = _run_store_scene(frames_by_moment, tmp_path)
    assert n == 1
    assert len(captured) == 1
    params = captured[0]
    assert "purpose_kind" in _insert_columns(), "sanity: column must be in the INSERT column list"
    # D11-2 broke this test's old hardcoded params[-6]/[-5] a THIRD time —
    # migration 150 appended three more trailing columns (lens_mm,
    # camera_height, dof) after shot_archetype. Name-keyed via _param_index
    # instead, so this can never drift again regardless of how many more
    # trailing columns a future chunk adds (see test_d9_6_7_transition_
    # causality_stamp.py / test_d11_1_shot_archetype_stamp.py for the same
    # fix applied there).
    assert params[_param_index("purpose_kind")] == "spatial"
    assert params[_param_index("shot_purpose")] == (
        "shows how Ryan gets from the pod to the corridor")


def test_store_scene_purpose_fields_default_null_for_untagged_shot(tmp_path):
    """A shot the planner didn't tag (every shot before this migration, and
    any code-synthesized floor shot going forward) must store NULL, not
    crash and not silently invent a value."""
    frames_by_moment = [(
        "moment 1 summary",
        [_frame(tmp_path, "frame1.png")],  # purpose_kind/shot_purpose default None
        None, None,
    )]
    n, captured = _run_store_scene(frames_by_moment, tmp_path)
    assert n == 1
    params = captured[0]
    assert params[_param_index("purpose_kind")] is None
    assert params[_param_index("shot_purpose")] is None


def test_store_scene_stamps_purpose_independently_per_shot(tmp_path):
    """Master and angle in the SAME moment carry DIFFERENT purposes — proves
    the stamping is per-frame, not a moment-level constant leaking across
    shots."""
    frames_by_moment = [(
        "moment 1 summary",
        [
            _frame(tmp_path, "frame1.png", role="master",
                   purpose_kind="story", shot_purpose="opens the beat"),
            _frame(tmp_path, "frame2.png", role="angle", shot_type="MCU",
                   purpose_kind="emotion", shot_purpose="shows her reaction"),
        ],
        None, None,
    )]
    n, captured = _run_store_scene(frames_by_moment, tmp_path)
    assert n == 2
    idxs = [_param_index("purpose_kind"), _param_index("shot_purpose")]
    assert tuple(captured[0][i] for i in idxs) == ("story", "opens the beat")
    assert tuple(captured[1][i] for i in idxs) == ("emotion", "shows her reaction")


def _insert_columns():
    """Re-reads the actual INSERT column list out of the source so this
    test file fails loudly (not silently) if the column names ever drift
    from what this test asserts positionally."""
    src_path = os.path.join(_BACKEND, "scripts", "coverage_to_app.py")
    with open(src_path) as f:
        src = f.read()
    start = src.index("INSERT INTO assets (")
    end = src.index(")", start)
    return src[start:end]


# The INSERT's column list grows a trailing column almost every chunk (D9-1,
# D9-6/D9-7, D11-1, D11-2, ...), which used to break this file's hardcoded
# negative indices every time one more column landed — three chunks in a row
# hit this (D11-2's own chunk notes). Compute a column's position from the
# SAME column-name text _insert_columns() already re-reads from source, so
# these assertions can never drift again regardless of how many more
# trailing columns land after this one.
_LITERAL_COLUMNS = {"status", "generation_method"}  # SQL literals ('done'/'coverage'), not $N placeholders
_COLUMN_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _column_names():
    """The INSERT's column names, in order — parsed out of _insert_columns()'s
    raw source text. The SQL string is built from several adjacent Python
    string literals split across lines, so splitting that raw text on ","
    leaves some tokens with a closing-quote/newline/indentation/opening-quote
    artifact glued onto the front. Take the LAST identifier-like run in each
    token (_COLUMN_TOKEN_RE) rather than a plain .strip(), since a plain
    strip only trims whitespace at the ends and leaves that artifact in
    place."""
    tokens = _insert_columns().split(",")
    names = []
    for t in tokens:
        matches = _COLUMN_TOKEN_RE.findall(t)
        names.append(matches[-1] if matches else t.strip())
    return names


def _param_index(column_name):
    """0-based index into the *params tuple fake_execute captures, for a
    named INSERT column — derived from _column_names() instead of a
    hand-maintained offset. status/generation_method are hardcoded SQL
    literals, not $N placeholders, so they're subtracted out."""
    cols = _column_names()
    idx = cols.index(column_name)
    literal_count_before = sum(1 for c in cols[:idx] if c in _LITERAL_COLUMNS)
    return idx - literal_count_before


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        test_store_scene_stamps_purpose_kind_and_shot_purpose(p)
        test_store_scene_purpose_fields_default_null_for_untagged_shot(p)
        test_store_scene_stamps_purpose_independently_per_shot(p)
    print("ok — D9-1 store_scene purpose-stamp tests passed")
