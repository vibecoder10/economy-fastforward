"""D11-1 (professional shot-archetype library, migration 149): store_scene
must stamp assets.shot_archetype from the parsed coverage plan's frame
dicts, exactly like it already does for assets.purpose_kind / assets.
shot_purpose (migration 147, D9-1) and assets.transition_kind / assets.
continuity_bridge / assets.caused_by (migration 148, D9-6/D9-7).

Same reasoning as test_d9_1_shot_purpose_stamp.py (read there for the full
"why store_scene is the ONE real stamping site" argument): the sheet-preview
planning path never inserts an asset row at all, so store_scene is the one
place a coverage picture ever becomes an `assets` row.

No network, no real DB: database/storage/vault/kie_unified/actions are
stubbed at import time (same module-stub pattern as the D9-1/D9-6/D9-7 stamp
tests). store_scene is exercised directly with a captured `execute` mock so
the test proves what actually lands in the SQL parameters, not just that the
function runs without raising.

Run: cd storyengine/backend && ./venv/bin/python -m pytest \
    tests/functional/test_d11_1_shot_archetype_stamp.py -q
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


_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom)
_stub("storage", upload_bytes=_boom)
_stub("vault", get_secret=_boom)
_stub("kie_unified", get_text_client_for_tenant=_boom)
_stub("actions", picture_price_for=lambda model_label=None: 0.05)

from scripts.coverage_to_app import store_scene  # noqa: E402

VIDEO_ID = "44444444-4444-4444-4444-444444444444"
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
    }
    base.update(overrides)
    return base


def test_store_scene_stamps_shot_archetype(tmp_path):
    """The decisive test: a frame carrying shot_archetype (as
    generate_coverage_frames now threads it from the parsed shot dict) must
    land in the INSERT's shot_archetype SQL parameter — the LAST positional
    param, since D11-1 appended it after D9-6/D9-7's caused_by."""
    frames_by_moment = [(
        "moment 1 summary",
        [_frame(tmp_path, "frame1.png", shot_archetype="establishing_wide")],
        None, None,
    )]
    n, captured = _run_store_scene(frames_by_moment, tmp_path)
    assert n == 1
    assert len(captured) == 1
    params = captured[0]
    cols = _insert_columns()
    assert "shot_archetype" in cols, "sanity: column must be in the INSERT column list"
    # params order: ...,purpose_kind,shot_purpose,transition_kind,
    # continuity_bridge,caused_by,shot_archetype (29 positional params after
    # the SQL string — indices 0-28 in *params; shot_archetype is the LAST
    # one, index -1).
    assert params[-1] == "establishing_wide"


def test_store_scene_shot_archetype_defaults_null_for_untagged_shot(tmp_path):
    """A shot the planner didn't tag an archetype onto (the overwhelming
    majority — tagging is OPTIONAL per rule 27) must store NULL, not crash
    and not silently invent a value."""
    frames_by_moment = [(
        "moment 1 summary",
        [_frame(tmp_path, "frame1.png")],  # shot_archetype defaults None
        None, None,
    )]
    n, captured = _run_store_scene(frames_by_moment, tmp_path)
    assert n == 1
    params = captured[0]
    assert params[-1] is None


def test_store_scene_stamps_shot_archetype_independently_per_shot(tmp_path):
    """Master and angle in the SAME moment carry DIFFERENT archetypes —
    proves the stamping is per-frame, not a moment-level constant leaking
    across shots."""
    frames_by_moment = [(
        "moment 1 summary",
        [
            _frame(tmp_path, "frame1.png", role="master",
                   shot_archetype="establishing_wide"),
            _frame(tmp_path, "frame2.png", role="angle", shot_type="MCU",
                   shot_archetype="medium_close"),
        ],
        None, None,
    )]
    n, captured = _run_store_scene(frames_by_moment, tmp_path)
    assert n == 2
    assert captured[0][-1] == "establishing_wide"
    assert captured[1][-1] == "medium_close"


def _insert_columns():
    """Re-reads the actual INSERT column list out of the source so this
    test file fails loudly (not silently) if the column names ever drift
    from what this test asserts positionally — same technique as the D9-1/
    D9-6/D9-7 stamp tests."""
    src_path = os.path.join(_BACKEND, "scripts", "coverage_to_app.py")
    with open(src_path) as f:
        src = f.read()
    start = src.index("INSERT INTO assets (")
    end = src.index(")", start)
    return src[start:end]


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        test_store_scene_stamps_shot_archetype(p)
        test_store_scene_shot_archetype_defaults_null_for_untagged_shot(p)
        test_store_scene_stamps_shot_archetype_independently_per_shot(p)
    print("ok — D11-1 store_scene shot-archetype stamp tests passed")
