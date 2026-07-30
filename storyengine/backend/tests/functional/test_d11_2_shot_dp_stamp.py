"""D11-2 (per-shot DP fields as data, migration 150): store_scene must stamp
assets.lens_mm / assets.camera_height / assets.dof from the parsed coverage
plan's frame dicts, exactly like it already does for assets.shot_archetype
(migration 149, D11-1) and the three metadata-row harvests before it.

Same reasoning as test_d9_1_shot_purpose_stamp.py (read there for the full
"why store_scene is the ONE real stamping site" argument): the sheet-preview
planning path never inserts an asset row at all, so store_scene is the one
place a coverage picture ever becomes an `assets` row.

No network, no real DB: database/storage/vault/kie_unified/actions are
stubbed at import time (same module-stub pattern as the D9-1/D9-6/D9-7/D11-1
stamp tests). store_scene is exercised directly with a captured `execute`
mock so the test proves what actually lands in the SQL parameters, not just
that the function runs without raising.

Unlike the three prior stamp-test files (which shipped with a hardcoded
`params[-N]` that broke every time a later chunk appended one more trailing
column — three chunks in a row, per this chunk's own notes), this file is
name-keyed from the start via _param_index, so a future chunk appending
MORE trailing columns after dof cannot break it.

Run: cd storyengine/backend && ./venv/bin/python -m pytest \
    tests/functional/test_d11_2_shot_dp_stamp.py -q
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

VIDEO_ID = "55555555-5555-5555-5555-555555555555"
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
        "transition_kind": None, "continuity_bridge": None, "caused_by": None,
        "shot_archetype": None,
        "lens_mm": None, "camera_height": None, "dof": None,
    }
    base.update(overrides)
    return base


def test_store_scene_stamps_dp_fields(tmp_path):
    """The decisive test: a frame carrying lens_mm/camera_height/dof (as
    generate_coverage_frames now threads them from the parsed shot dict)
    must land in the INSERT's corresponding SQL parameters."""
    frames_by_moment = [(
        "moment 1 summary",
        [_frame(tmp_path, "frame1.png", lens_mm=35, camera_height="eye", dof="shallow")],
        None, None,
    )]
    n, captured = _run_store_scene(frames_by_moment, tmp_path)
    assert n == 1
    assert len(captured) == 1
    params = captured[0]
    cols = _insert_columns()
    assert "lens_mm" in cols and "camera_height" in cols and "dof" in cols, \
        "sanity: all three columns must be in the INSERT column list"
    assert params[_param_index("lens_mm")] == 35
    assert params[_param_index("camera_height")] == "eye"
    assert params[_param_index("dof")] == "shallow"


def test_store_scene_dp_fields_default_null_for_untagged_shot(tmp_path):
    """A shot the planner didn't tag DP fields onto (the overwhelming
    majority — the row is OPTIONAL per rule 28) must store NULL, not crash
    and not silently invent a value."""
    frames_by_moment = [(
        "moment 1 summary",
        [_frame(tmp_path, "frame1.png")],  # lens_mm/camera_height/dof default None
        None, None,
    )]
    n, captured = _run_store_scene(frames_by_moment, tmp_path)
    assert n == 1
    params = captured[0]
    assert params[_param_index("lens_mm")] is None
    assert params[_param_index("camera_height")] is None
    assert params[_param_index("dof")] is None


def test_store_scene_stamps_dp_fields_independently_per_shot(tmp_path):
    """Master and angle in the SAME moment carry DIFFERENT DP values —
    proves the stamping is per-frame, not a moment-level constant leaking
    across shots."""
    frames_by_moment = [(
        "moment 1 summary",
        [
            _frame(tmp_path, "frame1.png", role="master",
                   lens_mm=24, camera_height="eye", dof="deep"),
            _frame(tmp_path, "frame2.png", role="angle", shot_type="MCU",
                   lens_mm=85, camera_height="chest", dof="shallow"),
        ],
        None, None,
    )]
    n, captured = _run_store_scene(frames_by_moment, tmp_path)
    assert n == 2
    idxs = [_param_index("lens_mm"), _param_index("camera_height"), _param_index("dof")]
    assert tuple(captured[0][i] for i in idxs) == (24, "eye", "deep")
    assert tuple(captured[1][i] for i in idxs) == (85, "chest", "shallow")


def test_store_scene_stamps_partial_dp_row(tmp_path):
    """Only ONE of the three DP slots stated (rule 28: each part is
    independently optional) — the other two must stay NULL, not get
    invented."""
    frames_by_moment = [(
        "moment 1 summary",
        [_frame(tmp_path, "frame1.png", lens_mm=50)],  # camera_height/dof omitted
        None, None,
    )]
    n, captured = _run_store_scene(frames_by_moment, tmp_path)
    assert n == 1
    params = captured[0]
    assert params[_param_index("lens_mm")] == 50
    assert params[_param_index("camera_height")] is None
    assert params[_param_index("dof")] is None


def _insert_columns():
    """Re-reads the actual INSERT column list out of the source so this
    test file fails loudly (not silently) if the column names ever drift
    from what this test asserts positionally — same technique as the D9-1/
    D9-6/D9-7/D11-1 stamp tests."""
    src_path = os.path.join(_BACKEND, "scripts", "coverage_to_app.py")
    with open(src_path) as f:
        src = f.read()
    start = src.index("INSERT INTO assets (")
    end = src.index(")", start)
    return src[start:end]


# See test_d11_1_shot_archetype_stamp.py's equivalent block for the full
# rationale — this file is written name-keyed from the start rather than
# with a positional index, so a future chunk appending more trailing
# columns after dof cannot break it the way params[-1]/params[-N] broke the
# three prior stamp-test files.
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
        test_store_scene_stamps_dp_fields(p)
        test_store_scene_dp_fields_default_null_for_untagged_shot(p)
        test_store_scene_stamps_dp_fields_independently_per_shot(p)
        test_store_scene_stamps_partial_dp_row(p)
    print("ok — D11-2 store_scene DP-field stamp tests passed")
