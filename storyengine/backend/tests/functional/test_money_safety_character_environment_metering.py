"""Money-safety fix: character-sheet and environment-plate generation both
spent real GPT Image 2 calls with NO generation_ledger write and NO
videos.max_spend cap check at all — confirmed live (video
686b4651-e495-44be-baf6-97fc6dd527e9: 2 characters + 3 environments
generated, videos.total_cost stayed $0.00 the whole time). Since
actions.budget_check() only ever reads videos.total_cost, a cap on either
stage could never stop a runaway spend.

This file proves, per the verification bar: a test that FAILS on
unpatched main and PASSES after the fix, for each of:
  1. character portrait generation writes a correct generation_ledger row
     and rolls videos.total_cost (routes/characters.py regenerate_character).
  2. environment plate generation writes a correct generation_ledger row
     and rolls videos.total_cost (routes/environments.py regenerate_environment).
  3. character generation is REFUSED (no image call, no DB write) when it
     would exceed max_spend.
  4. environment generation is REFUSED the same way.
  5. a per-video BATCH (design_characters) stops mid-batch the moment the
     running spend would cross the cap — proving this isn't just a single
     up-front check that a multi-item call can slip past.
  6. GET /api/videos/{id} actually returns max_spend (it was selected in
     SQL but never passed to the VideoDetail(...) response).

Style: real modules imported directly, DB/network boundaries monkeypatched
— same pattern as tests/functional/test_c4_prop_manifest.py and
tests/functional/test_c36_budget_cap.py (which this file complements: C36
proved budget_check()/make_autobuild_step's OWN gate works; this file
proves the two stages that never called into any of that machinery now do).

Run: cd storyengine/backend && ./venv/bin/python -m pytest \
    tests/functional/test_money_safety_character_environment_metering.py -q
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import actions  # noqa: E402
import routes.characters as characters_route  # noqa: E402
import routes.environments as environments_route  # noqa: E402
import routes.pipeline as pipeline_mod  # noqa: E402
import routes.videos as videos_route  # noqa: E402
import vault as vault_mod  # noqa: E402
from fastapi import HTTPException  # noqa: E402

TENANT = "tenant-1"
VIDEO = "video-1"


class _FakeBackgroundTasks:
    """Mirrors tests/functional/test_c4_prop_manifest.py's helper — records
    the scheduled background closure without a real ASGI request cycle."""

    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *a, **kw):
        self.tasks.append((fn, a, kw))


def _char_video_row(**over):
    base = {
        "id": VIDEO, "video_title": "T", "script": "irrelevant",
        "image_style_override": "", "original_dna": None, "story_bible": None,
        "characters_approved_at": None, "project_id": None,
        "total_cost": 0.0, "max_spend": None,
    }
    base.update(over)
    return base


def _env_video_row(**over):
    base = {
        "id": VIDEO, "video_title": "T", "script": "irrelevant",
        "image_style_override": "", "original_dna": None, "story_bible": None,
        "aspect_ratio": "16:9", "environments_approved_at": None, "project_id": None,
        "total_cost": 0.0, "max_spend": None,
    }
    base.update(over)
    return base


def _patch_common(monkeypatch):
    """Scaffolding every test below needs: no real Kie key lookup, no real
    task-lane bookkeeping, no real 30s UX delay in the _run() finally block."""
    async def fake_get_secret(name, tenant_id=None):
        return "fake-kie-key"

    async def fake_is_task_active(*a, **kw):
        return False

    def fake_set_task_status(*a, **kw):
        pass

    def fake_clear_task_status(*a, **kw):
        pass

    def fake_lane_begin(*a, **kw):
        pass

    def fake_lane_finish(*a, **kw):
        pass

    async def fast_sleep(*a, **kw):
        return None

    monkeypatch.setattr(vault_mod, "get_secret", fake_get_secret)
    monkeypatch.setattr(pipeline_mod, "_is_task_active", fake_is_task_active)
    monkeypatch.setattr(pipeline_mod, "_set_task_status", fake_set_task_status)
    monkeypatch.setattr(pipeline_mod, "_clear_task_status", fake_clear_task_status)
    monkeypatch.setattr(pipeline_mod, "_lane_begin", fake_lane_begin)
    monkeypatch.setattr(pipeline_mod, "_lane_finish", fake_lane_finish)
    monkeypatch.setattr(characters_route.asyncio, "sleep", fast_sleep)
    monkeypatch.setattr(environments_route.asyncio, "sleep", fast_sleep)


# ---------------------------------------------------------------------------
# 1 + 2. real ledger write + total_cost roll-up
# ---------------------------------------------------------------------------

def test_character_regenerate_writes_ledger_row_and_rolls_total_cost(monkeypatch):
    _patch_common(monkeypatch)

    async def fake_get_video(video_id, tenant_id):
        return _char_video_row(max_spend=None)  # no cap -> never refused

    async def fake_video_summary(tenant_id, video_id):
        return {"total_cost": 0.0, "max_spend": None}

    async def fake_fetch_one(query, *a):
        if "FROM video_characters" in query:
            return {"id": "char-1", "name": "Rex", "description": "a red robot"}
        return None

    execute_calls = []

    async def fake_execute(query, *a):
        execute_calls.append((query, a))
        return "OK"

    async def fake_generate_portrait(api_key, description, style_dna, name=""):
        return {"url": "https://kie.example/tmp.png", "model": "gpt-image-2", "task_id": "task-abc"}

    async def fake_persist(tenant_id, video_id, char_id, temp_url):
        return "https://storage.example/permanent.png"

    ledger_calls = []

    async def fake_record_ledger_entry(**kwargs):
        ledger_calls.append(kwargs)

    monkeypatch.setattr(characters_route, "_get_video", fake_get_video)
    monkeypatch.setattr(characters_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(characters_route, "execute", fake_execute)
    monkeypatch.setattr(characters_route, "_generate_portrait", fake_generate_portrait)
    monkeypatch.setattr(characters_route, "_persist_portrait_url", fake_persist)
    monkeypatch.setattr(characters_route, "record_ledger_entry", fake_record_ledger_entry)
    monkeypatch.setattr(actions, "video_summary", fake_video_summary)

    bg = _FakeBackgroundTasks()
    resp = asyncio.run(characters_route.regenerate_character(VIDEO, "char-1", bg, tenant_id=TENANT))
    assert resp["status"] == "running"
    assert len(bg.tasks) == 1, "must schedule the redesign, not refuse it (no cap set)"
    fn, args, kwargs = bg.tasks[0]
    asyncio.run(fn())

    assert len(ledger_calls) == 1, "portrait generation must write exactly one ledger row"
    row = ledger_calls[0]
    assert row["tenant_id"] == TENANT
    assert row["video_id"] == VIDEO
    assert row["stage"] == "character_sheet"
    assert row["model"] == "gpt-image-2"
    assert row["unit_cost"] == actions.picture_price_for("gpt-image-2") == 0.05
    assert row["actual_cost"] == 0.05
    assert row["kie_task_id"] == "task-abc"


def test_environment_regenerate_writes_ledger_row_and_rolls_total_cost(monkeypatch):
    _patch_common(monkeypatch)

    async def fake_get_video(video_id, tenant_id):
        return _env_video_row(max_spend=None)

    async def fake_video_summary(tenant_id, video_id):
        return {"total_cost": 0.0, "max_spend": None}

    async def fake_fetch_one(query, *a):
        if "FROM video_environments" in query:
            return {"id": "env-1", "name": "Kitchen", "description": "a sunlit kitchen"}
        return None

    async def fake_execute(query, *a):
        return "OK"

    async def fake_generate_environment(api_key, description, style_dna, aspect_ratio):
        return {"url": "https://kie.example/tmp-env.png", "model": "nano-banana-2", "task_id": "task-env-1"}

    async def fake_persist(tenant_id, video_id, env_id, temp_url):
        return "https://storage.example/env-permanent.png"

    ledger_calls = []

    async def fake_record_ledger_entry(**kwargs):
        ledger_calls.append(kwargs)

    monkeypatch.setattr(environments_route, "_get_video", fake_get_video)
    monkeypatch.setattr(environments_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(environments_route, "execute", fake_execute)
    monkeypatch.setattr(actions, "video_summary", fake_video_summary)
    monkeypatch.setattr(environments_route, "_generate_environment", fake_generate_environment)
    monkeypatch.setattr(environments_route, "_persist_portrait_url", fake_persist)
    monkeypatch.setattr(environments_route, "record_ledger_entry", fake_record_ledger_entry)

    bg = _FakeBackgroundTasks()
    resp = asyncio.run(environments_route.regenerate_environment(VIDEO, "env-1", bg, tenant_id=TENANT))
    assert resp["status"] == "running"
    assert len(bg.tasks) == 1
    fn, args, kwargs = bg.tasks[0]
    asyncio.run(fn())

    assert len(ledger_calls) == 1, "environment generation must write exactly one ledger row"
    row = ledger_calls[0]
    assert row["stage"] == "environment"
    assert row["model"] == "nano-banana-2"
    assert row["unit_cost"] == actions.picture_price_for("nano-banana-2") == 0.04
    assert row["actual_cost"] == 0.04
    assert row["kie_task_id"] == "task-env-1"


# ---------------------------------------------------------------------------
# 3 + 4. refusal actually blocks the spend (no image call, no DB write)
# ---------------------------------------------------------------------------

def test_character_regenerate_refused_when_over_cap(monkeypatch):
    """videos.max_spend=$1.00, total_cost already $1.00 -> the very next
    portrait (quote ~$0.05) would push past the cap. Proves the refusal
    is a real block: HTTPException raised BEFORE any background task is
    scheduled, so _generate_portrait/record_ledger_entry are never called —
    not merely a warning that gets logged and ignored."""
    _patch_common(monkeypatch)

    async def fake_get_video(video_id, tenant_id):
        return _char_video_row(max_spend=1.00, total_cost=1.00)

    async def fake_video_summary(tenant_id, video_id):
        return {"total_cost": 1.00, "max_spend": 1.00}

    async def fake_fetch_one(query, *a):
        return {"id": "char-1", "name": "Rex", "description": "a red robot"}

    generate_calls = []
    ledger_calls = []

    async def fake_generate_portrait(*a, **kw):
        generate_calls.append(1)
        return {"url": "x", "model": "gpt-image-2", "task_id": None}

    async def fake_record_ledger_entry(**kwargs):
        ledger_calls.append(kwargs)

    monkeypatch.setattr(characters_route, "_get_video", fake_get_video)
    monkeypatch.setattr(characters_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(characters_route, "_generate_portrait", fake_generate_portrait)
    monkeypatch.setattr(characters_route, "record_ledger_entry", fake_record_ledger_entry)
    monkeypatch.setattr(actions, "video_summary", fake_video_summary)

    bg = _FakeBackgroundTasks()
    with __import__("pytest").raises(HTTPException) as exc:
        asyncio.run(characters_route.regenerate_character(VIDEO, "char-1", bg, tenant_id=TENANT))
    assert exc.value.status_code == 400
    assert "cap" in exc.value.detail.lower()
    assert len(bg.tasks) == 0, "no background task may be scheduled once the cap is refused"
    assert not generate_calls, "the paid provider call must never fire"
    assert not ledger_calls, "no spend happened, so no ledger row may be written"


def test_environment_regenerate_refused_when_over_cap(monkeypatch):
    _patch_common(monkeypatch)

    async def fake_get_video(video_id, tenant_id):
        return _env_video_row(max_spend=1.00, total_cost=1.00)

    async def fake_video_summary(tenant_id, video_id):
        return {"total_cost": 1.00, "max_spend": 1.00}

    async def fake_fetch_one(query, *a):
        return {"id": "env-1", "name": "Kitchen", "description": "a sunlit kitchen"}

    generate_calls = []

    async def fake_generate_environment(*a, **kw):
        generate_calls.append(1)
        return {"url": "x", "model": "gpt-image-2", "task_id": None}

    monkeypatch.setattr(environments_route, "_get_video", fake_get_video)
    monkeypatch.setattr(environments_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(environments_route, "_generate_environment", fake_generate_environment)
    monkeypatch.setattr(actions, "video_summary", fake_video_summary)

    bg = _FakeBackgroundTasks()
    with __import__("pytest").raises(HTTPException) as exc:
        asyncio.run(environments_route.regenerate_environment(VIDEO, "env-1", bg, tenant_id=TENANT))
    assert exc.value.status_code == 400
    assert "cap" in exc.value.detail.lower()
    assert len(bg.tasks) == 0
    assert not generate_calls, "the paid provider call must never fire"


def test_character_batch_stops_mid_batch_once_cap_would_be_crossed(monkeypatch):
    """design_characters designs a WHOLE cast in one call. A cap wide enough
    for character #1 (~$0.05) but not #2 (~$0.10 total) must stop the batch
    cold after #1 — proving the cap is re-checked every iteration as real
    spend accrues, not just once before the batch starts."""
    _patch_common(monkeypatch)

    video = _char_video_row(max_spend=0.06, total_cost=0.0)

    async def fake_extract_cast(video_arg, api_key):
        return [
            {"name": "Rex", "description": "a red robot"},
            {"name": "Nia", "description": "a blue robot"},
        ]

    async def fake_fetch_one(query, *a):
        if "INSERT INTO video_characters" in query:
            return {"id": f"char-{len(insert_calls)}"}
        return None

    insert_calls = []

    async def fake_execute(query, *a):
        if "INSERT INTO video_characters" in query or "DELETE FROM" in query or "UPDATE videos" in query:
            insert_calls.append((query, a))
        return "OK"

    # total_cost mutates as the (fake) ledger "spends" — this is the live
    # video row _budget_refusal reads fresh every iteration via
    # actions.video_summary, so it must reflect accruing spend for the
    # per-iteration check to mean anything.
    state = {"total_cost": 0.0}

    async def fake_video_summary(tenant_id, video_id):
        return {"total_cost": state["total_cost"], "max_spend": video["max_spend"]}

    generate_calls = []

    async def fake_generate_portrait(api_key, description, style_dna, name=""):
        generate_calls.append(name)
        state["total_cost"] = round(state["total_cost"] + 0.05, 2)
        return {"url": "https://kie.example/tmp.png", "model": "gpt-image-2", "task_id": None}

    async def fake_persist(tenant_id, video_id, char_id, temp_url):
        return "https://storage.example/permanent.png"

    ledger_calls = []

    async def fake_record_ledger_entry(**kwargs):
        ledger_calls.append(kwargs)

    monkeypatch.setattr(characters_route, "_extract_cast", fake_extract_cast)
    monkeypatch.setattr(characters_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(characters_route, "execute", fake_execute)
    monkeypatch.setattr(characters_route, "_generate_portrait", fake_generate_portrait)
    monkeypatch.setattr(characters_route, "_persist_portrait_url", fake_persist)
    monkeypatch.setattr(characters_route, "record_ledger_entry", fake_record_ledger_entry)
    monkeypatch.setattr(actions, "video_summary", fake_video_summary)

    async def fake_get_video(video_id, tenant_id):
        return video

    monkeypatch.setattr(characters_route, "_get_video", fake_get_video)

    bg = _FakeBackgroundTasks()
    resp = asyncio.run(characters_route.design_characters(VIDEO, bg, tenant_id=TENANT))
    assert resp["status"] == "running"
    assert len(bg.tasks) == 1
    fn, args, kwargs = bg.tasks[0]
    asyncio.run(fn())

    assert generate_calls == ["Rex"], (
        "the cap ($0.06) covers character #1 (~$0.05) but not #1+#2 (~$0.10) — "
        "the batch must stop after #1, never even attempting #2"
    )
    assert len(ledger_calls) == 1


# ---------------------------------------------------------------------------
# 5. GET /api/videos/{id} actually returns max_spend
# ---------------------------------------------------------------------------

def test_get_video_returns_max_spend(monkeypatch):
    """max_spend was SELECTed in the SQL but never passed to VideoDetail(...),
    so PATCH .../max_spend wrote it fine while GET always served null — no
    UI or API consumer could ever see the cap that was actually set."""
    async def fake_fetch_one(query, *a):
        assert "max_spend" in query, "the SELECT must still name the column explicitly"
        return {"id": VIDEO, "max_spend": 12.5, "total_cost": 3.0}

    monkeypatch.setattr(videos_route, "fetch_one", fake_fetch_one)

    result = asyncio.run(videos_route.get_video(VIDEO, tenant_id=TENANT))
    assert result.max_spend == 12.5


def test_get_video_max_spend_is_none_when_uncapped(monkeypatch):
    async def fake_fetch_one(query, *a):
        return {"id": VIDEO, "max_spend": None, "total_cost": 0.0}

    monkeypatch.setattr(videos_route, "fetch_one", fake_fetch_one)

    result = asyncio.run(videos_route.get_video(VIDEO, tenant_id=TENANT))
    assert result.max_spend is None


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-v"]))
