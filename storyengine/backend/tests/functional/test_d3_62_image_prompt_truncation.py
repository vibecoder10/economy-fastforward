"""Tests for D3-62 (image_prompt 1000-char truncation) + the (BRIDGE)-tag
plan->store investigation carried in the same chunk.

BEFORE this fix, scripts/coverage_to_app.py::store_scene sliced every frame's
draw prompt to `[:1000]` before writing it into assets.image_prompt — a
copy-paste of the SHORT-BIO `[:1000]` convention used elsewhere in this
codebase (character/environment `description` columns), applied to the wrong
kind of text. The coverage draw prompt carries the scene's full SET/AXIS/
STAGING/SEQUENCE/FACING lock tails (coverage.py's run_coverage) appended on
top of the planner's own shot text — routinely well over 1000 chars.
Confirmed live via `se db` (video 686b4651, scene 1, shots 107/108/109): all
three stored prompts were EXACTLY 1000 chars, cut mid-word inside a lock tail
("...vertica", "...low"). assets.image_prompt is unbounded TEXT
(migrations/000_baseline_schema.sql) — there was never a DB constraint
requiring the slice, so this fix needs no migration.

Also traced in this chunk: whether the same write path drops the "(BRIDGE)"
tag between the plan and the stored prompt (as D3-63's brief assumed for
shot 107). It does NOT — verified by pulling the actual directive.txt for
that exact generation off the VPS (/tmp/coverage_app/686b4651/scene1/
directive.txt, still present, timestamped after the D3-53c BRIDGE-law
deploy): the planner's own raw output never contains a "(BRIDGE)" tag for
this scene at all, despite a real location change between moment 2 (pod
interior) and moment 3 (corridor). run_coverage stores `fr["description"]`
byte-for-byte from `moment["master"/"angles"]["description"]` with no prefix
rewriting anywhere in between, so there is nothing to fix in the write path
for a tag the plan never emitted — the real gap is the pre-existing "NOT
BUILT" LOCATION-JUMP gate coverage.py documents around line 2197 (needs a
per-moment location field; correctly left out of scope there as a future
chunk, not reopened here).

No network, no real DB: database/storage/vault/kie_unified/actions are
stubbed at import time (mirrors test_c16b_coverage_skip_if_done.py's
module-stub pattern). store_scene is exercised directly with a captured
`execute` mock so the test proves what actually lands in the image_prompt
SQL parameter, not just that the function runs without raising.

Run: cd storyengine/backend && ./venv/bin/python -m pytest \
    tests/functional/test_d3_62_image_prompt_truncation.py -q
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


# Placeholders at import time; each test overrides the ones it actually
# exercises via patch("scripts.coverage_to_app.X", ...). `actions` is stubbed
# too because store_scene does a LOCAL `from actions import picture_price_for`
# inside its ledger branch — the real module drags in fastapi/shared.* just
# to price a picture, which this test has no reason to exercise for real.
_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom)
_stub("storage", upload_bytes=_boom)
_stub("vault", get_secret=_boom)
_stub("kie_unified", get_text_client_for_tenant=_boom)
_stub("actions", picture_price_for=lambda model_label=None: 0.05)

from scripts.coverage_to_app import store_scene  # noqa: E402

VIDEO_ID = "11111111-1111-1111-1111-111111111111"
TENANT_ID = "tenant-1"

# Mirrors a REAL lock-stamped description: the planner's own text plus the
# kind of long SET/AXIS/STAGING/SEQUENCE/FACING tails run_coverage appends —
# well past 1000 chars, with a distinctive marker near the very end so
# truncation is unambiguous either way.
_LOCK_TAIL = (
    " Set dressing and character blocking, identical in every shot of this scene: " + ("prop " * 100)
    + "Screen-direction lock, identical in every shot of this scene: Nyla frame-LEFT looking "
    "frame-RIGHT. Camera kit for this scene — the actors are PLANTED and never move: " + ("setup " * 100)
    + "Facing lock: this shot's expression is the point — the face must be readable to the lens."
)
LONG_DESCRIPTION = "(SETUP D) WS low-angle corridor shot" + _LOCK_TAIL + " TAIL_MARKER_PAST_1000_CHARS"


def test_long_description_fixture_actually_exceeds_the_old_cut():
    """Sanity: the fixture must be longer than 1000 chars, or this test
    proves nothing about the truncation bug."""
    assert len(LONG_DESCRIPTION) > 1000, len(LONG_DESCRIPTION)


def test_store_scene_does_not_truncate_image_prompt_at_1000_chars(tmp_path):
    """(D3-62) store_scene's INSERT must carry the FULL description — not
    the old `[:1000]` slice. Stash-proof: replacing the fix's
    `fr.get("description") or ""` with the old `(fr.get("description") or
    "")[:1000]` makes this test fail (the marker falls outside the cut)."""
    img_path = tmp_path / "frame.png"
    img_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    frames_by_moment = [(
        "moment 1 summary",
        [{
            "role": "master", "shot_type": "MCU", "description": LONG_DESCRIPTION,
            "_path": str(img_path), "camera_move": None, "routed_model": None,
            "routing_reason": None, "duration_seconds": None, "image_model": None,
        }],
        None, None,
    )]

    captured = {}

    async def fake_execute(sql, *params):
        if "INSERT INTO assets" in sql:
            captured["image_prompt"] = params[7]  # id,tenant,vid,scene,idx,idx,summary,image_prompt,...
        return None

    async def fake_upload_bytes(*a, **k):
        return "https://img/fake.png"

    with patch("scripts.coverage_to_app.execute", AsyncMock(side_effect=fake_execute)), \
         patch("scripts.coverage_to_app.upload_bytes", AsyncMock(side_effect=fake_upload_bytes)), \
         patch("scripts.coverage_to_app.record_ledger_entry", AsyncMock(return_value=None)):
        n = asyncio.run(store_scene(
            VIDEO_ID, TENANT_ID, "Test Video", "16:9", 1, frames_by_moment,
        ))

    assert n == 1
    stored = captured.get("image_prompt")
    assert stored is not None, "INSERT INTO assets was never observed"
    assert stored == LONG_DESCRIPTION, "FAIL: image_prompt was mutated/truncated on the way to storage"
    assert len(stored) > 1000, f"FAIL: stored image_prompt is only {len(stored)} chars — truncated"
    assert stored.endswith("TAIL_MARKER_PAST_1000_CHARS"), \
        "FAIL: the tail marker (planted past char 1000) did not survive storage"


def test_store_scene_old_cut_would_have_failed_this_fixture():
    """Stash-proof, the other direction: confirms the fixture actually
    exercises the bug — the OLD `[:1000]` slice on this exact fixture drops
    the tail marker, same failure mode observed live on shots 107/108/109
    (cut mid-word inside a lock tail)."""
    old_sliced = LONG_DESCRIPTION[:1000]
    assert len(old_sliced) == 1000
    assert "TAIL_MARKER_PAST_1000_CHARS" not in old_sliced
    assert old_sliced != LONG_DESCRIPTION
