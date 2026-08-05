"""Tests for S6-C: (1) a save-time style-keyword lint on environment
description/material_map, and (2) a channel-DNA visual_format fallthrough
that feeds environment reference generation.

Incident this closes (verified recon, S6-C brief): a user-edited environment
description containing a style keyword ("anime") later tripped the
storyboard hard gate L29 (DECLARE-ONE-STYLE, scripts/coverage_to_app.py's
_assert_single_style_declaration) — the scene got NO board, and the reason
only surfaced in background_tasks.message, after real spend. Part 1 rejects
the doomed description/material_map at SAVE time using the EXACT SAME
keyword list and substring semantics as the L29 gate
(scripts.coverage_to_app._STYLE_KEYWORDS, `kw in low` substring match), so
save-time and board-time can never diverge.

Part 2: run_environments_design_step (and regenerate_environment) used to
build style_dna from ONLY video.image_style_override — a format-locked
channel's video with no per-video override got a reference with ZERO format
signal. This adds a fallthrough: image_style_override -> visual_style
(resolved the SAME way scripts.coverage_to_app._resolve_style resolves it
for every other image-prompt path) -> the locked channel format's look
(channel_format.get_channel_format / style_preset_for_format /
STYLE_DESCRIPTIONS) -> "" (old default).

This file covers:
  1. _reject_style_keywords — direct unit checks (hit, clean text, message
     length/field naming).
  2. PATCH /{video_id}/environments/{env_id} (update_environment) — a style
     keyword in description or material_map is refused with 400 and the row
     is NEVER updated (fetch_one/the UPDATE...RETURNING never fires); a
     clean description still updates normally (200, unchanged behavior).
  3. POST /{video_id}/environments (create_environment) — a style keyword
     in the description is refused with 400.
  4. MCP edit_environment (routes/mcp.py._call_edit_environment) — flows
     through the SAME linted update_environment route, so the same 400
     surfaces as an MCP error result.
  5. _resolve_environment_style_dna — the fallthrough chain: tier 1
     (image_style_override) wins unchanged; nothing anywhere falls back to
     "" (old default, channel format not locked); a format-locked channel
     with no per-video overrides resolves to that format's STYLE_
     DESCRIPTIONS look.
  6. run_environments_design_step and regenerate_environment both call the
     chain (capture the style_dna argument _generate_environment actually
     receives), proving both entry points that build an environment
     reference were fixed, not just one.

Style: real modules imported directly, DB/network boundaries monkeypatched
— same pattern as tests/functional/test_money_safety_character_environment_
metering.py and tests/functional/test_env1_location_extraction.py.

Run: cd storyengine/backend && ./venv/bin/python -m pytest \
    tests/functional/test_s6c_environment_style_lint_and_dna.py -q
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import actions  # noqa: E402
import routes.environments as env_route  # noqa: E402
import routes.pipeline as pipeline_mod  # noqa: E402
from auth import get_tenant_id  # noqa: E402

TENANT = "tenant-1"
VIDEO = "video-1"


class _FakeBackgroundTasks:
    """Mirrors test_money_safety_character_environment_metering.py's helper
    — records the scheduled background closure without a real ASGI cycle."""

    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *a, **kw):
        self.tasks.append((fn, a, kw))


def _env_video_row(**over):
    base = {
        "id": VIDEO, "tenant_id": TENANT, "video_title": "T", "script": "irrelevant",
        "image_style_override": None, "visual_style": None, "original_dna": None,
        "story_bible": None, "aspect_ratio": "16:9", "environments_approved_at": None,
        "project_id": None, "total_cost": 0.0, "max_spend": None,
    }
    base.update(over)
    return base


def _patch_common(monkeypatch):
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

    monkeypatch.setattr(pipeline_mod, "_is_task_active", fake_is_task_active)
    monkeypatch.setattr(pipeline_mod, "_set_task_status", fake_set_task_status)
    monkeypatch.setattr(pipeline_mod, "_clear_task_status", fake_clear_task_status)
    monkeypatch.setattr(pipeline_mod, "_lane_begin", fake_lane_begin)
    monkeypatch.setattr(pipeline_mod, "_lane_finish", fake_lane_finish)
    monkeypatch.setattr(env_route.asyncio, "sleep", fast_sleep)


# ---------------------------------------------------------------------------
# 1. _reject_style_keywords — direct unit checks
# ---------------------------------------------------------------------------

class TestRejectStyleKeywords:
    def test_no_op_on_clean_text(self):
        env_route._reject_style_keywords("a sunlit kitchen with warm morning light", "description")  # must not raise

    def test_no_op_on_none_and_empty(self):
        env_route._reject_style_keywords(None, "description")
        env_route._reject_style_keywords("", "description")

    def test_raises_400_naming_the_word_and_field(self):
        with pytest.raises(HTTPException) as exc:
            env_route._reject_style_keywords("a bright anime kitchen", "description")
        assert exc.value.status_code == 400
        assert "anime" in exc.value.detail
        assert "description" in exc.value.detail
        assert len(exc.value.detail) < 160

    def test_material_map_field_named_in_message(self):
        with pytest.raises(HTTPException) as exc:
            env_route._reject_style_keywords("claymation glass boundary at waist height", "material map")
        assert "material map" in exc.value.detail
        assert "claymation" in exc.value.detail
        assert len(exc.value.detail) < 160

    def test_uses_the_same_keyword_list_l29_uses(self):
        """Save-time and board-time must never diverge — this asserts the
        lint imports coverage_to_app's own _STYLE_KEYWORDS rather than a
        second, hand-copied tuple."""
        import inspect
        src = inspect.getsource(env_route._reject_style_keywords)
        assert "from scripts.coverage_to_app import _STYLE_KEYWORDS" in src

    def test_every_l29_keyword_is_caught(self):
        from scripts.coverage_to_app import _STYLE_KEYWORDS
        for kw in _STYLE_KEYWORDS:
            with pytest.raises(HTTPException):
                env_route._reject_style_keywords(f"a scene rendered in {kw} style", "description")

    def test_worst_case_message_length_stays_under_160(self):
        from scripts.coverage_to_app import _STYLE_KEYWORDS
        for kw in _STYLE_KEYWORDS:
            for field in ("description", "material map"):
                with pytest.raises(HTTPException) as exc:
                    env_route._reject_style_keywords(f"a scene with {kw} vibes", field)
                assert len(exc.value.detail) < 160, (kw, field, exc.value.detail)


# ---------------------------------------------------------------------------
# 2. PATCH /{video_id}/environments/{env_id} — update_environment
# ---------------------------------------------------------------------------

def _build_update_client(monkeypatch, *, video_exists=True):
    async def fake_get_video(video_id, tenant_id):
        if not video_exists:
            raise HTTPException(status_code=404, detail="Video not found")
        return _env_video_row()

    calls = {"fetch_one": []}

    async def fake_fetch_one(query, *args):
        calls["fetch_one"].append((query, args))
        if "UPDATE video_environments" in query:
            return {
                "id": "env-1", "name": "Kitchen", "description": args[0] if "description" in query else "old",
                "reference_url": None, "status": "draft", "source": "generated",
                "sort": 0, "props": None, "material_map": None,
            }
        return None

    monkeypatch.setattr(env_route, "_get_video", fake_get_video)
    monkeypatch.setattr(env_route, "fetch_one", fake_fetch_one)

    app = FastAPI()
    app.include_router(env_route.router)
    app.dependency_overrides[get_tenant_id] = lambda: TENANT
    return TestClient(app), calls


class TestUpdateEnvironmentStyleLint:
    def test_style_keyword_in_description_is_rejected_and_row_not_touched(self, monkeypatch):
        client, calls = _build_update_client(monkeypatch)
        resp = client.patch(
            f"/api/videos/{VIDEO}/environments/env-1",
            json={"description": "a bright anime kitchen"},
        )
        assert resp.status_code == 400, resp.text
        assert "anime" in resp.json()["detail"]
        assert not calls["fetch_one"], "the UPDATE...RETURNING must never fire once the lint rejects"

    def test_style_keyword_in_material_map_is_rejected_and_row_not_touched(self, monkeypatch):
        client, calls = _build_update_client(monkeypatch)
        resp = client.patch(
            f"/api/videos/{VIDEO}/environments/env-1",
            json={"material_map": "claymation glass wall from waist up"},
        )
        assert resp.status_code == 400, resp.text
        assert "claymation" in resp.json()["detail"]
        assert not calls["fetch_one"]

    def test_clean_description_still_updates_normally(self, monkeypatch):
        client, calls = _build_update_client(monkeypatch)
        resp = client.patch(
            f"/api/videos/{VIDEO}/environments/env-1",
            json={"description": "a sunlit kitchen with a large window"},
        )
        assert resp.status_code == 200, resp.text
        assert len(calls["fetch_one"]) == 1
        assert "UPDATE video_environments" in calls["fetch_one"][0][0]

    def test_clean_material_map_still_updates_normally(self, monkeypatch):
        client, calls = _build_update_client(monkeypatch)
        resp = client.patch(
            f"/api/videos/{VIDEO}/environments/env-1",
            json={"material_map": "glass wall from waist up, solid below"},
        )
        assert resp.status_code == 200, resp.text
        assert len(calls["fetch_one"]) == 1

    def test_name_only_edit_is_not_linted(self, monkeypatch):
        """name is deliberately NOT linted this pass — a style word in the
        name alone must not be rejected here (report-only follow-up)."""
        client, calls = _build_update_client(monkeypatch)
        resp = client.patch(
            f"/api/videos/{VIDEO}/environments/env-1",
            json={"name": "Anime Bedroom"},
        )
        assert resp.status_code == 200, resp.text
        assert len(calls["fetch_one"]) == 1


# ---------------------------------------------------------------------------
# 3. POST /{video_id}/environments — create_environment
# ---------------------------------------------------------------------------

def _build_create_client(monkeypatch, *, video_exists=True):
    async def fake_get_video(video_id, tenant_id):
        if not video_exists:
            raise HTTPException(status_code=404, detail="Video not found")
        return _env_video_row()

    inserted = {}

    async def fake_fetch_one(query, *args):
        if "COALESCE(MAX(sort)" in query:
            return {"next_sort": 0}
        if "INSERT INTO video_environments" in query:
            inserted["args"] = args
            return {
                "id": "env-new", "name": args[2], "description": args[3],
                "reference_url": None, "status": "draft", "source": "generated",
                "sort": args[4], "props": None, "material_map": None,
            }
        return None

    monkeypatch.setattr(env_route, "_get_video", fake_get_video)
    monkeypatch.setattr(env_route, "fetch_one", fake_fetch_one)

    app = FastAPI()
    app.include_router(env_route.router)
    app.dependency_overrides[get_tenant_id] = lambda: TENANT
    return TestClient(app), inserted


class TestCreateEnvironmentStyleLint:
    def test_style_keyword_in_description_is_rejected(self, monkeypatch):
        client, inserted = _build_create_client(monkeypatch)
        resp = client.post(
            f"/api/videos/{VIDEO}/environments",
            json={"name": "Bedroom", "description": "an anime-styled bedroom"},
        )
        assert resp.status_code == 400, resp.text
        assert "anime" in resp.json()["detail"]
        assert not inserted, "no draft row may be created once the lint rejects"

    def test_clean_description_still_creates_normally(self, monkeypatch):
        client, inserted = _build_create_client(monkeypatch)
        resp = client.post(
            f"/api/videos/{VIDEO}/environments",
            json={"name": "Bedroom", "description": "a cozy bedroom with warm light"},
        )
        assert resp.status_code == 200, resp.text
        assert inserted


# ---------------------------------------------------------------------------
# 4. MCP edit_environment flows through the SAME linted route
# ---------------------------------------------------------------------------

class TestMcpEditEnvironmentStyleLint:
    def test_mcp_edit_environment_rejects_style_keyword_in_description(self, monkeypatch):
        import routes.mcp as mcp_route

        async def fake_get_video(video_id, tenant_id):
            return _env_video_row()

        monkeypatch.setattr(env_route, "_get_video", fake_get_video)

        result = asyncio.run(mcp_route._call_edit_environment(
            TENANT,
            {"video_id": VIDEO, "env_id": "env-1", "description": "a watercolor courtyard"},
            "test-caller",
        ))
        assert result.get("isError") is True
        text = result["content"][0]["text"] if result.get("content") else str(result)
        assert "watercolor" in text

    def test_mcp_edit_environment_rejects_style_keyword_in_material_map(self, monkeypatch):
        import routes.mcp as mcp_route

        async def fake_get_video(video_id, tenant_id):
            return _env_video_row()

        monkeypatch.setattr(env_route, "_get_video", fake_get_video)

        result = asyncio.run(mcp_route._call_edit_environment(
            TENANT,
            {"video_id": VIDEO, "env_id": "env-1", "material_map": "cgi glass panel, waist height"},
            "test-caller",
        ))
        assert result.get("isError") is True


# ---------------------------------------------------------------------------
# 5. _resolve_environment_style_dna — the fallthrough chain
# ---------------------------------------------------------------------------

class TestResolveEnvironmentStyleDna:
    def test_image_style_override_wins_unchanged(self):
        video = _env_video_row(image_style_override="  hand-painted watercolor storybook  ",
                                visual_style="pixar_3d")
        result = asyncio.run(env_route._resolve_environment_style_dna(video, TENANT))
        assert result == "hand-painted watercolor storybook"

    def test_nothing_anywhere_falls_back_to_old_default(self, monkeypatch):
        import channel_format

        async def fake_get_channel_format(tenant_id):
            return {}, False  # not locked

        monkeypatch.setattr(channel_format, "get_channel_format", fake_get_channel_format)

        video = _env_video_row(image_style_override=None, visual_style=None)
        result = asyncio.run(env_route._resolve_environment_style_dna(video, TENANT))
        assert result == ""

    def test_channel_format_lookup_failure_fails_soft_to_old_default(self, monkeypatch):
        """No DATABASE_URL / a lookup error must never raise out of this
        helper — same fail-soft posture as channel_format's own reads."""
        video = _env_video_row(image_style_override=None, visual_style=None)
        result = asyncio.run(env_route._resolve_environment_style_dna(video, TENANT))
        assert result == ""

    def test_format_locked_channel_with_no_overrides_uses_the_locked_look(self, monkeypatch):
        import channel_format

        async def fake_get_channel_format(tenant_id):
            assert tenant_id == TENANT
            return {"style": "3D animated cartoon"}, True  # locked

        monkeypatch.setattr(channel_format, "get_channel_format", fake_get_channel_format)

        video = _env_video_row(image_style_override=None, visual_style=None)
        result = asyncio.run(env_route._resolve_environment_style_dna(video, TENANT))
        assert result == channel_format.STYLE_DESCRIPTIONS["pixar_3d"]["look"]
        assert "NOT photorealistic" in result


# ---------------------------------------------------------------------------
# 6. Both entry points that build a reference use the chain
# ---------------------------------------------------------------------------

class TestChannelDnaReachesBothGenerationEntryPoints:
    def test_run_environments_design_step_passes_locked_look_to_generate_environment(self, monkeypatch):
        import channel_format

        async def fake_get_secret(name, tenant_id=None):
            return "fake-kie-key"

        async def fake_get_channel_format(tenant_id):
            return {"style": "3D animated cartoon"}, True

        async def fake_execute(query, *a):
            return "OK"

        async def fake_fetch_one(query, *a):
            if "INSERT INTO video_environments" in query:
                return {"id": "env-1"}
            return None

        async def fake_persist(tenant_id, video_id, env_id, url):
            return url

        async def fake_ledger(**kw):
            pass

        async def fake_video_summary(tenant_id, video_id):
            return {"total_cost": 0.0, "max_spend": None}

        captured = {}

        async def fake_generate_environment(api_key, description, style_dna, aspect_ratio="16:9"):
            captured["style_dna"] = style_dna
            return {"url": "https://x/y.png", "model": "gpt-image-2", "task_id": "t1"}

        import vault as vault_mod
        monkeypatch.setattr(vault_mod, "get_secret", fake_get_secret)
        monkeypatch.setattr(channel_format, "get_channel_format", fake_get_channel_format)
        monkeypatch.setattr(env_route, "execute", fake_execute)
        monkeypatch.setattr(env_route, "fetch_one", fake_fetch_one)
        monkeypatch.setattr(env_route, "_persist_portrait_url", fake_persist)
        monkeypatch.setattr(env_route, "record_ledger_entry", fake_ledger)
        monkeypatch.setattr(env_route, "_generate_environment", fake_generate_environment)
        monkeypatch.setattr(actions, "video_summary", fake_video_summary)

        video = _env_video_row(
            image_style_override=None, visual_style=None,
            story_bible={"locations": [{"id": "Kitchen", "description": "a kitchen", "lighting": "warm"}]},
        )
        result = asyncio.run(env_route.run_environments_design_step(video, TENANT))
        assert result["status"] == "completed"
        assert captured["style_dna"] == channel_format.STYLE_DESCRIPTIONS["pixar_3d"]["look"]

    def test_regenerate_environment_passes_locked_look_to_generate_environment(self, monkeypatch):
        _patch_common(monkeypatch)
        import channel_format

        async def fake_get_video(video_id, tenant_id):
            return _env_video_row(image_style_override=None, visual_style=None)

        async def fake_fetch_one(query, *a):
            return {"id": "env-1", "name": "Kitchen", "description": "a sunlit kitchen"}

        async def fake_get_secret(name, tenant_id=None):
            return "fake-kie-key"

        async def fake_video_summary(tenant_id, video_id):
            return {"total_cost": 0.0, "max_spend": None}

        async def fake_get_channel_format(tenant_id):
            return {"style": "3D animated cartoon"}, True

        async def fake_execute(query, *a):
            return "OK"

        async def fake_persist(tenant_id, video_id, env_id, url):
            return url

        async def fake_ledger(**kw):
            pass

        captured = {}

        async def fake_generate_environment(api_key, description, style_dna, aspect_ratio):
            captured["style_dna"] = style_dna
            return {"url": "https://x/y.png", "model": "gpt-image-2", "task_id": "t1"}

        import vault as vault_mod
        monkeypatch.setattr(env_route, "_get_video", fake_get_video)
        monkeypatch.setattr(env_route, "fetch_one", fake_fetch_one)
        monkeypatch.setattr(env_route, "execute", fake_execute)
        monkeypatch.setattr(vault_mod, "get_secret", fake_get_secret)
        monkeypatch.setattr(channel_format, "get_channel_format", fake_get_channel_format)
        monkeypatch.setattr(actions, "video_summary", fake_video_summary)
        monkeypatch.setattr(env_route, "_persist_portrait_url", fake_persist)
        monkeypatch.setattr(env_route, "record_ledger_entry", fake_ledger)
        monkeypatch.setattr(env_route, "_generate_environment", fake_generate_environment)

        bg = _FakeBackgroundTasks()
        resp = asyncio.run(env_route.regenerate_environment(VIDEO, "env-1", bg, tenant_id=TENANT))
        assert resp["status"] == "running"
        assert len(bg.tasks) == 1
        fn, args, kwargs = bg.tasks[0]
        asyncio.run(fn())

        assert captured["style_dna"] == channel_format.STYLE_DESCRIPTIONS["pixar_3d"]["look"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
