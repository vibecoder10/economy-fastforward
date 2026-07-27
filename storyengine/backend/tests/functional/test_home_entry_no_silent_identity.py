"""Root-cause fix for a live bug (2026-07-27): a video created from
DirectorHome's single-prompt entry box — "make a video about a dystopian
world, where humans live... bugs, cap the spend at 1$" — silently came out
as PocoAPoco's locked Ryan/Vanessa two-hander dialogue, because
routes.videos.create_video's three fail-soft identity-defaulting steps
(house script template, locked visual format, locked cast) ran
UNCONDITIONALLY for every new video. In the same turn, "cap the spend at
1$" was silently dropped — CreateVideoRequest had no `max_spend` field at
all, so a typed cap had nowhere to land at creation time.

This file pins both fixes:
  1. `apply_channel_identity=False` (DirectorHome's free-text box sets this)
     skips all three identity-defaulting steps; None/True (every other
     caller — New Video form, MCP, chat producer, queue, autopilot, the
     clone/model path) keeps the original always-inherit behavior.
  2. `max_spend` on CreateVideoRequest lands in the INSERT, with the same
     validation the PATCH /api/videos/{id} path already enforces (>0 or
     None).

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_home_entry_no_silent_identity.py -q
"""
import asyncio

import pytest
from fastapi import BackgroundTasks, HTTPException

import routes.billing as billing_route
import routes.characters as characters_route
import routes.projects as projects_route
import routes.script_templates as script_templates_route
import routes.videos as videos_route
from models import CreateVideoRequest


def _wire_common_fakes(monkeypatch, inserts):
    async def noop(*_args, **_kwargs):
        return None

    async def fake_project(_tenant_id):
        return {"id": "project-home-entry"}

    async def fake_fetch_one(query, *args):
        if "INSERT INTO videos" not in query:
            raise AssertionError(f"unexpected fetch_one query: {query}")
        inserts.append((query, args))
        return {
            "id": f"video-{len(inserts)}",
            "video_title": args[2],
            "status": args[3],
            "thumbnail_url": None,
            "accent_color": "#00D4AA",
            "total_cost": 0,
            "views": 0,
            "ctr": None,
            "created_at": "now",
            "updated_at": "now",
        }

    monkeypatch.setattr(billing_route, "check_plan_limits", noop)
    monkeypatch.setattr(billing_route, "enforce_video_length_cap", noop)
    monkeypatch.setattr(billing_route, "increment_usage", noop)
    monkeypatch.setattr(projects_route, "_get_or_create_project", fake_project)
    monkeypatch.setattr(videos_route, "fetch_one", fake_fetch_one)
    # static_docu detection must never block a plain-text create (see the
    # existing try/except in create_video around static_mode_for_tenant).
    import static_docu
    async def fake_static_mode(_tenant_id):
        return False
    monkeypatch.setattr(static_docu, "static_mode_for_tenant", fake_static_mode)
    # Drive workspace sync is a background_tasks.add_task, never awaited here.


def test_apply_channel_identity_false_skips_all_three_identity_steps(monkeypatch):
    """DirectorHome's free-text box: apply_channel_identity=False must skip
    house-format template, locked visual format, AND locked cast — the
    exact three steps that turned a dystopian-bugs video into PocoAPoco's
    Ryan/Vanessa two-hander live."""
    inserts = []
    _wire_common_fakes(monkeypatch, inserts)

    calls = {"template": 0, "format": 0, "cast": 0}

    async def track_template(*_a, **_k):
        calls["template"] += 1
        return False

    async def track_format(*_a, **_k):
        calls["format"] += 1
        return False

    async def track_cast(*_a, **_k):
        calls["cast"] += 1
        return False

    monkeypatch.setattr(script_templates_route, "apply_default_template", track_template)
    monkeypatch.setattr("channel_format.apply_format_defaults", track_format)
    monkeypatch.setattr(characters_route, "apply_locked_cast", track_cast)

    asyncio.run(
        videos_route.create_video(
            CreateVideoRequest(
                title="a dystopian world where humans live in bubbles, watched like bugs",
                apply_channel_identity=False,
            ),
            BackgroundTasks(),
            "tenant-home-entry",
        )
    )

    assert calls == {"template": 0, "format": 0, "cast": 0}, (
        "apply_channel_identity=False must skip every identity-defaulting "
        f"step; got call counts {calls}"
    )
    print("✅ test_apply_channel_identity_false_skips_all_three_identity_steps")


@pytest.mark.parametrize("flag", [None, True])
def test_apply_channel_identity_default_still_inherits(monkeypatch, flag):
    """Every OTHER caller (New Video form, MCP, chat producer, queue,
    autopilot, the clone/model path) must keep the original always-inherit
    behavior — None (field omitted) and explicit True are both "inherit"."""
    inserts = []
    _wire_common_fakes(monkeypatch, inserts)

    calls = {"template": 0, "format": 0, "cast": 0}

    async def track_template(*_a, **_k):
        calls["template"] += 1
        return False

    async def track_format(*_a, **_k):
        calls["format"] += 1
        return False

    async def track_cast(*_a, **_k):
        calls["cast"] += 1
        return False

    monkeypatch.setattr(script_templates_route, "apply_default_template", track_template)
    monkeypatch.setattr("channel_format.apply_format_defaults", track_format)
    monkeypatch.setattr(characters_route, "apply_locked_cast", track_cast)

    kwargs = {"title": "a channel-card video"}
    if flag is not None:
        kwargs["apply_channel_identity"] = flag
    asyncio.run(
        videos_route.create_video(
            CreateVideoRequest(**kwargs),
            BackgroundTasks(),
            "tenant-home-entry",
        )
    )

    assert calls == {"template": 1, "format": 1, "cast": 1}, (
        f"apply_channel_identity={flag!r} must still run every identity-"
        f"defaulting step exactly once (legacy behavior); got {calls}"
    )
    print(f"✅ test_apply_channel_identity_default_still_inherits[{flag}]")


def test_max_spend_at_creation_lands_in_the_insert(monkeypatch):
    """A cap typed at creation ("cap the spend at $1") must actually reach
    videos.max_spend — CreateVideoRequest had no field for this at all
    before this fix, so DirectorHome had nowhere to put a parsed cap."""
    inserts = []
    _wire_common_fakes(monkeypatch, inserts)
    monkeypatch.setattr(script_templates_route, "apply_default_template", _noop)
    monkeypatch.setattr("channel_format.apply_format_defaults", _noop)
    monkeypatch.setattr(characters_route, "apply_locked_cast", _noop)

    asyncio.run(
        videos_route.create_video(
            CreateVideoRequest(title="cap test", max_spend=1.0, apply_channel_identity=False),
            BackgroundTasks(),
            "tenant-home-entry",
        )
    )

    assert len(inserts) == 1
    query, args = inserts[0]
    assert "max_spend" in query
    # max_spend is the LAST bound param (appended at the end of the column
    # list) — see routes/videos.py's INSERT INTO videos statement.
    assert args[-1] == 1.0, f"expected max_spend=1.0 as the last INSERT param, got {args[-1]!r}"
    print("✅ test_max_spend_at_creation_lands_in_the_insert")


def test_max_spend_omitted_stays_null(monkeypatch):
    """No cap mentioned -> unchanged behavior: max_spend stays NULL, never a
    guessed number."""
    inserts = []
    _wire_common_fakes(monkeypatch, inserts)
    monkeypatch.setattr(script_templates_route, "apply_default_template", _noop)
    monkeypatch.setattr("channel_format.apply_format_defaults", _noop)
    monkeypatch.setattr(characters_route, "apply_locked_cast", _noop)

    asyncio.run(
        videos_route.create_video(
            CreateVideoRequest(title="no cap here", apply_channel_identity=False),
            BackgroundTasks(),
            "tenant-home-entry",
        )
    )

    assert len(inserts) == 1
    _query, args = inserts[0]
    assert args[-1] is None
    print("✅ test_max_spend_omitted_stays_null")


def test_max_spend_zero_or_negative_rejected(monkeypatch):
    """Same guard as the PATCH path (routes/videos.py update_video): a
    zero/negative cap would either silently disable itself or brick every
    paid action, so it must 400, not be coerced."""
    inserts = []
    _wire_common_fakes(monkeypatch, inserts)
    monkeypatch.setattr(script_templates_route, "apply_default_template", _noop)
    monkeypatch.setattr("channel_format.apply_format_defaults", _noop)
    monkeypatch.setattr(characters_route, "apply_locked_cast", _noop)

    for bad in (0, -5.0):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                videos_route.create_video(
                    CreateVideoRequest(title="bad cap", max_spend=bad),
                    BackgroundTasks(),
                    "tenant-home-entry",
                )
            )
        assert exc.value.status_code == 400
    assert not inserts, "a rejected max_spend must never reach the INSERT"
    print("✅ test_max_spend_zero_or_negative_rejected")


async def _noop(*_a, **_k):
    return False
