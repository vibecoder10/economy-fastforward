"""D9-6/D9-7 (migration 148): store_scene must stamp assets.transition_kind /
assets.continuity_bridge / assets.caused_by from the parsed coverage plan's
frame dicts, exactly like it already does for assets.purpose_kind /
assets.shot_purpose (migration 147, D9-1) and assets.shot_location /
assets.group_arrangement (migration 143).

Same reasoning as test_d9_1_shot_purpose_stamp.py (read there for the full
"why store_scene is the ONE real stamping site" argument, confirmed again by
reading coverage_to_app.py before writing this file — nothing changed about
that): the sheet-preview planning path never inserts an asset row at all, so
store_scene is the one place a coverage picture ever becomes an `assets` row.

No network, no real DB: database/storage/vault/kie_unified/actions are
stubbed at import time (mirrors test_d3_62_image_prompt_truncation.py's
module-stub pattern, same as D9-1's stamp test). store_scene is exercised
directly with a captured `execute` mock so the test proves what actually
lands in the SQL parameters, not just that the function runs without
raising.

Run: cd storyengine/backend && ./venv/bin/python -m pytest \
    tests/functional/test_d9_6_7_transition_causality_stamp.py -q
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

VIDEO_ID = "33333333-3333-3333-3333-333333333333"
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
    }
    base.update(overrides)
    return base


def test_store_scene_stamps_transition_kind_continuity_bridge_and_caused_by(tmp_path):
    """The decisive test: a frame carrying transition_kind/continuity_bridge/
    caused_by (as generate_coverage_frames now threads them from the parsed
    shot dict) must land in the INSERT's corresponding SQL parameters."""
    frames_by_moment = [(
        "moment 1 summary",
        [_frame(tmp_path, "frame1.png",
                transition_kind="time_cut",
                continuity_bridge="the same harness buckle, now sun-bleached",
                caused_by="M1-MASTER")],
        None, None,
    )]
    n, captured = _run_store_scene(frames_by_moment, tmp_path)
    assert n == 1
    assert len(captured) == 1
    params = captured[0]
    cols = _insert_columns()
    assert "transition_kind" in cols and "continuity_bridge" in cols and "caused_by" in cols, \
        "sanity: all three columns must be in the INSERT column list"
    # params order: ...,purpose_kind,shot_purpose,transition_kind,
    # continuity_bridge,caused_by (28 positional params after the SQL
    # string — indices 0-27 in *params, the new three are the LAST three).
    assert params[-3] == "time_cut"
    assert params[-2] == "the same harness buckle, now sun-bleached"
    assert params[-1] == "M1-MASTER"


def test_store_scene_transition_and_causality_fields_default_null_for_untagged_shot(tmp_path):
    """A shot the planner didn't tag (every shot before this migration, and
    any code-synthesized floor shot going forward) must store NULL, not
    crash and not silently invent a value."""
    frames_by_moment = [(
        "moment 1 summary",
        [_frame(tmp_path, "frame1.png")],  # all three default None
        None, None,
    )]
    n, captured = _run_store_scene(frames_by_moment, tmp_path)
    assert n == 1
    params = captured[0]
    assert params[-3] is None
    assert params[-2] is None
    assert params[-1] is None


def test_store_scene_stamps_transition_and_causality_independently_per_shot(tmp_path):
    """Master and angle in the SAME moment carry DIFFERENT transition/
    causality values — proves the stamping is per-frame, not a moment-level
    constant leaking across shots."""
    frames_by_moment = [(
        "moment 1 summary",
        [
            _frame(tmp_path, "frame1.png", role="master",
                   transition_kind="opening", continuity_bridge=None, caused_by=None),
            _frame(tmp_path, "frame2.png", role="angle", shot_type="MCU",
                   transition_kind="continuous", continuity_bridge=None, caused_by="M1-MASTER"),
        ],
        None, None,
    )]
    n, captured = _run_store_scene(frames_by_moment, tmp_path)
    assert n == 2
    assert captured[0][-3:] == ("opening", None, None)
    assert captured[1][-3:] == ("continuous", None, "M1-MASTER")


def test_store_scene_stamps_continuity_bridge_only_when_stated(tmp_path):
    """A non-continuous kind WITH a bridge must stamp both — proves the
    bridge column isn't tied to a fixed kind, just whatever text
    parse_coverage actually extracted."""
    frames_by_moment = [(
        "moment 1 summary",
        [_frame(tmp_path, "frame1.png",
                transition_kind="montage",
                continuity_bridge="the same drumbeat under every cut",
                caused_by="M0-ANGLE2")],
        None, None,
    )]
    n, captured = _run_store_scene(frames_by_moment, tmp_path)
    assert n == 1
    params = captured[0]
    assert params[-3] == "montage"
    assert params[-2] == "the same drumbeat under every cut"
    assert params[-1] == "M0-ANGLE2"


def _insert_columns():
    """Re-reads the actual INSERT column list out of the source so this
    test file fails loudly (not silently) if the column names ever drift
    from what this test asserts positionally — same technique as D9-1's
    stamp test."""
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
        test_store_scene_stamps_transition_kind_continuity_bridge_and_caused_by(p)
        test_store_scene_transition_and_causality_fields_default_null_for_untagged_shot(p)
        test_store_scene_stamps_transition_and_causality_independently_per_shot(p)
        test_store_scene_stamps_continuity_bridge_only_when_stated(p)
    print("ok — D9-6/D9-7 store_scene transition/causality stamp tests passed")
