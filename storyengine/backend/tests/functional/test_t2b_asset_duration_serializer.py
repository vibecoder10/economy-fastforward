"""T2b (TIMELINE-WORKBENCH-PLAN.md): expose assets.video_duration and
assigned_video_duration on GET /api/videos/{id}/assets.

Recon (TIMELINE-WORKBENCH-PLAN.md's T2b line, re-verified against the route
itself before this change): the DB holds real per-clip seconds in these two
columns (migrations/000_baseline_schema.sql), but `routes/videos.py`'s
`get_video_assets` SELECT list never named them, so the API response simply
didn't have those keys — proven live by curl 2026-07-28. The frontend
(`TimelineAltitudeView.tsx`'s `getRealDurationSeconds`) already reads
`assigned_video_duration` / `video_duration` defensively and auto-activates a
real proportional ruler the moment they appear — no frontend change needed,
only this one-line SELECT addition.

This test proves the FIX, not just "the query ran": it calls the real route
coroutine (`routes.videos.get_video_assets`) with `database.fetch_all`
monkeypatched to a fake that returns rows shaped exactly like a real
Postgres row (both duration columns populated for one asset, both NULL for
another — the honest "no duration yet" case some rows will always be in) and
asserts the exact keys/values survive to the JSON-serializable response the
route returns. No live DB, no network.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_t2b_asset_duration_serializer.py -q
"""
import asyncio
import os
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import routes.videos as videos_mod  # noqa: E402

TENANT = "tenant-t2b"
VIDEO = "video-t2b"


def _real_asset_row(asset_id, *, video_duration=None, assigned_video_duration=None,
                     has_clip=True):
    """Shaped like a real row from the SELECT this test drives — every
    column the real query names, not a hand-picked subset, so a future
    column rename here would fail loudly instead of the test silently
    passing on a stale shape."""
    return {
        "id": asset_id, "video_id": VIDEO, "scene": 1, "image_index": 100,
        "image_url": "https://fake/img.png", "drive_image_url": None,
        "image_prompt": "a factory floor",
        "status": "done", "shot_type": "MASTER", "hero_shot": False,
        "sentence_text": None,
        "video_clip_url": "https://fake/clip.mp4" if has_clip else None,
        "video_prompt": "slow push in", "sound_prompt": None,
        "sound_effect_url": None, "sound_volume": None,
        "duration_seconds": None, "extraction_flags": None, "image_model": None,
        "routed_model": None, "routing_reason": None, "model_used": None,
        "model_override": None, "camera_movement": None, "camera_preset_id": None,
        "carries_own_line": False, "clip_speech_start": None, "clip_speech_end": None,
        "assigned_dialogue": None, "generation_method": None, "caption": None,
        "video_duration": video_duration,
        "assigned_video_duration": assigned_video_duration,
        "created_at": "2026-07-28T00:00:00",
    }


def test_serializer_exposes_both_real_duration_columns(monkeypatch):
    captured_query = {}

    async def fake_fetch_all(query, *args):
        captured_query["sql"] = query
        return [
            _real_asset_row("asset-with-duration", video_duration=7.0,
                             assigned_video_duration=6.5),
            _real_asset_row("asset-no-clip-yet", has_clip=False,
                             video_duration=None, assigned_video_duration=None),
        ]

    monkeypatch.setattr(videos_mod, "fetch_all", fake_fetch_all)

    rows = asyncio.run(videos_mod.get_video_assets(VIDEO, tenant_id=TENANT))

    # The query itself must actually SELECT the two columns — not just that
    # this fake happens to hand them back regardless of what was asked for.
    assert "video_duration" in captured_query["sql"]
    assert "assigned_video_duration" in captured_query["sql"]

    by_id = {r["id"]: r for r in rows}
    with_dur = by_id["asset-with-duration"]
    assert with_dur["video_duration"] == 7.0
    assert with_dur["assigned_video_duration"] == 6.5

    # Honest fallback case: a row with no real duration yet must still come
    # through as None, not a fabricated 0 or missing key — the frontend's
    # getRealDurationSeconds treats None/0/negative identically as "no real
    # duration," so this must round-trip exactly.
    no_dur = by_id["asset-no-clip-yet"]
    assert no_dur["video_duration"] is None
    assert no_dur["assigned_video_duration"] is None


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-q"]))
