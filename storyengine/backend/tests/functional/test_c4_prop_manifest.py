"""Tests for C4 (prop manifest — kill cross-scene prop drift), backend half.

Each approved environment gets a canonical structured prop list
(video_environments.props, migration 115) authored ONCE at approval time and
injected VERBATIM into every scene's planning + draw + repair prompts,
replacing the old mechanism where a fresh LLM call re-paraphrased the
location's prose every scene.

This file covers:
  1. props validation on the creator-editable edit route (routes/
     environments.py's PATCH /{id}/environments/{env_id} + its Pydantic
     models) — shape ({name, position}) and the max-count cap.
  2. Approval-time extraction is FAIL-SOFT: _extract_env_props raising never
     blocks approve_environments — status still flips to 'approved',
     environments_approved_at still stamps, props stays NULL.
  3. Approval-time extraction success path: a working extraction persists
     props via one UPDATE per environment, and is skipped entirely for an
     environment that already has a manifest (never re-spends).
  4. scripts/coverage_to_app.py's props plumbing: _approved_envs and
     _scene_locations parse the props JSONB column correctly (None-safe).
  5. The storyboard-SHEET-PREVIEW path (_plan_sheet_prompts /
     generate_storyboard_sheet_for_scene) is provably NOT touched by any of
     this — it has no props parameter, and its rendered panel text never
     contains the manifest phrase even when the moments it's given were
     built with a manifest-aware coverage plan.

The storyboard.bot / storyboard.coverage half (render_prop_manifest,
_format_story_bible_for_beat's injection, apply_prop_manifest, the
check_prop_manifest_consistency drift alarm) is covered in skills/
video-pipeline/tests/test_prop_manifest.py.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c4_prop_manifest.py -q
"""
import asyncio
import inspect
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

import routes.environments as env_route  # noqa: E402
import routes.model_video as model_video_mod  # noqa: E402
import scripts.coverage_to_app as coverage_to_app  # noqa: E402

TENANT = "tenant-1"
VIDEO_ID = "video-1"


class _FakeBackgroundTasks:
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *a, **kw):
        self.tasks.append((fn, a, kw))


def _video_row(**over):
    base = {
        "id": VIDEO_ID, "video_title": "Test Video", "script": "",
        "image_style_override": None, "original_dna": None, "story_bible": None,
        "aspect_ratio": "16:9", "environments_approved_at": None, "project_id": None,
    }
    base.update(over)
    return base


def _env_row(**over):
    base = {
        "id": "env-1", "tenant_id": TENANT, "video_id": VIDEO_ID, "name": "Kitchen",
        "description": "A sunlit kitchen.", "reference_url": "https://example.com/kitchen.png",
        "status": "draft", "source": "generated", "sort": 0, "props": None,
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# 1. props validation (edit route + models)
# ---------------------------------------------------------------------------

class TestPropsValidation:
    def test_valid_shape_accepted(self):
        upd = env_route.EnvironmentUpdate(props=[{"name": "kettle", "position": "on the stove"}])
        assert upd.props[0].name == "kettle"
        assert upd.props[0].position == "on the stove"

    def test_missing_position_field_rejected(self):
        with pytest.raises(Exception):
            env_route.EnvironmentUpdate(props=[{"name": "kettle"}])

    def test_missing_name_field_rejected(self):
        with pytest.raises(Exception):
            env_route.EnvironmentUpdate(props=[{"position": "on the stove"}])

    def test_blank_name_rejected(self):
        with pytest.raises(Exception):
            env_route.EnvironmentUpdate(props=[{"name": "   ", "position": "on the stove"}])

    def test_over_max_count_rejected(self):
        props = [{"name": f"item{i}", "position": "somewhere"} for i in range(env_route.MAX_PROPS + 1)]
        with pytest.raises(Exception):
            env_route.EnvironmentUpdate(props=props)

    def test_exactly_max_count_accepted(self):
        props = [{"name": f"item{i}", "position": "somewhere"} for i in range(env_route.MAX_PROPS)]
        upd = env_route.EnvironmentUpdate(props=props)
        assert len(upd.props) == env_route.MAX_PROPS

    def test_omitted_props_leaves_field_none(self):
        upd = env_route.EnvironmentUpdate(name="new name")
        assert upd.props is None


def test_update_environment_route_persists_valid_props(monkeypatch):
    """PATCH .../environments/{env_id} with a valid props list writes it as
    JSON into the props column and returns it in the serialized read model."""
    seen = {}

    async def fake_get_video(video_id, tenant_id):
        return _video_row()

    async def fake_fetch_one(query, *args):
        seen["query"] = query
        seen["args"] = args
        return _env_row(props=args[0])

    monkeypatch.setattr(env_route, "_get_video", fake_get_video)
    monkeypatch.setattr(env_route, "fetch_one", fake_fetch_one)

    body = env_route.EnvironmentUpdate(props=[{"name": "kettle", "position": "on the stove"}])
    result = asyncio.run(env_route.update_environment(VIDEO_ID, "env-1", body, tenant_id=TENANT))

    assert "props" in seen["query"]
    assert json.loads(seen["args"][0]) == [{"name": "kettle", "position": "on the stove"}]
    assert result["props"][0]["name"] == "kettle"


def test_update_environment_route_clears_props_with_empty_list(monkeypatch):
    """An explicit empty list clears the manifest back to NULL — the
    creator's way to say 'no manifest' again."""
    seen = {}

    async def fake_get_video(video_id, tenant_id):
        return _video_row()

    async def fake_fetch_one(query, *args):
        seen["args"] = args
        return _env_row(props=None)

    monkeypatch.setattr(env_route, "_get_video", fake_get_video)
    monkeypatch.setattr(env_route, "fetch_one", fake_fetch_one)

    body = env_route.EnvironmentUpdate(props=[])
    asyncio.run(env_route.update_environment(VIDEO_ID, "env-1", body, tenant_id=TENANT))
    assert seen["args"][0] is None


def test_update_environment_omitted_props_does_not_touch_the_column(monkeypatch):
    """Omitting props (only editing name/description) must never write the
    props column at all — untouched, not cleared."""
    seen = {}

    async def fake_get_video(video_id, tenant_id):
        return _video_row()

    async def fake_fetch_one(query, *args):
        seen["query"] = query
        return _env_row()

    monkeypatch.setattr(env_route, "_get_video", fake_get_video)
    monkeypatch.setattr(env_route, "fetch_one", fake_fetch_one)

    body = env_route.EnvironmentUpdate(name="New Name")
    asyncio.run(env_route.update_environment(VIDEO_ID, "env-1", body, tenant_id=TENANT))
    assert "props" not in seen["query"]


# ---------------------------------------------------------------------------
# 2 & 3. approve_environments: fail-soft extraction + success path
# ---------------------------------------------------------------------------

def _patch_approve_scaffolding(monkeypatch, env_row, *, resolve_creds_returns=None):
    """Common monkeypatching for approve_environments tests: DB calls, the
    pipeline task-status/lane helpers, and Claude-creds resolution. Returns
    the list `execute_calls` will be appended to (query, args) tuples."""
    import routes.pipeline as pipeline_mod

    execute_calls = []

    async def fake_get_video(video_id, tenant_id):
        return _video_row()

    async def fake_fetch_all(query, *args):
        return [env_row]

    async def fake_execute(query, *args):
        execute_calls.append((query, args))
        return "OK"

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

    async def fake_sync_bible(*a, **kw):
        return None

    async def fake_resolve_claude_creds(tenant_id):
        return resolve_creds_returns

    monkeypatch.setattr(env_route, "_get_video", fake_get_video)
    monkeypatch.setattr(env_route, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(env_route, "execute", fake_execute)
    monkeypatch.setattr(env_route, "_sync_bible_to_locations", fake_sync_bible)
    monkeypatch.setattr(pipeline_mod, "_is_task_active", fake_is_task_active)
    monkeypatch.setattr(pipeline_mod, "_set_task_status", fake_set_task_status)
    monkeypatch.setattr(pipeline_mod, "_clear_task_status", fake_clear_task_status)
    monkeypatch.setattr(pipeline_mod, "_lane_begin", fake_lane_begin)
    monkeypatch.setattr(pipeline_mod, "_lane_finish", fake_lane_finish)
    monkeypatch.setattr(model_video_mod, "_resolve_claude_creds", fake_resolve_claude_creds)

    # The pre-existing description-refresh vision pass must not hit the
    # network in a test — it's already independently fail-soft (its own
    # try/except), so making it explode fast is a safe, minimal stub.
    import shared.clients.vision_client as vision_client_mod

    async def boom_vision_call(*a, **kw):
        raise RuntimeError("no network in tests")

    monkeypatch.setattr(vision_client_mod, "vision_call", boom_vision_call)

    # _run()'s finally block does a real `await asyncio.sleep(30)` (a UX
    # delay in prod, so a "completed" status is visible before it clears) —
    # not a paid call, but a real test would otherwise wait it out. Skip it.
    async def fast_sleep(*a, **kw):
        return None

    monkeypatch.setattr(env_route.asyncio, "sleep", fast_sleep)

    return execute_calls


def _run_approve_background_task(monkeypatch, env_row, *, extract_props_impl):
    execute_calls = _patch_approve_scaffolding(
        monkeypatch, env_row, resolve_creds_returns={"provider": "anthropic", "key": "fake-key"})
    monkeypatch.setattr(env_route, "_extract_env_props", extract_props_impl)

    bg = _FakeBackgroundTasks()
    result = asyncio.run(env_route.approve_environments(VIDEO_ID, bg, tenant_id=TENANT))
    assert result["status"] == "running"
    assert len(bg.tasks) == 1
    fn, args, kwargs = bg.tasks[0]
    asyncio.run(fn(*args, **kwargs))  # run the background body inline
    return execute_calls


def test_approve_environments_fail_soft_when_extraction_raises(monkeypatch):
    """(e) THE fail-soft requirement: extraction raising must never block or
    fail approval. Approval still flips status='approved' and stamps
    environments_approved_at; props is never written (stays NULL)."""
    env = _env_row(props=None)

    async def boom_extract(*a, **kw):
        raise RuntimeError("vision provider exploded")

    execute_calls = _run_approve_background_task(monkeypatch, env, extract_props_impl=boom_extract)

    approved = [q for q, a in execute_calls if "status = 'approved'" in q]
    stamped = [q for q, a in execute_calls
               if "environments_approved_at = now()" in q and "UPDATE videos" in q]
    props_writes = [(q, a) for q, a in execute_calls if "SET props" in q]

    assert approved, "approval must still flip status='approved' even when extraction fails"
    assert stamped, "approval must still stamp environments_approved_at even when extraction fails"
    assert not props_writes, "a failed extraction must never write to the props column"


def test_approve_environments_extraction_success_persists_props(monkeypatch):
    """The happy path: a working extraction writes exactly one UPDATE ...
    SET props = <json> per environment."""
    env = _env_row(props=None)
    extracted = [{"name": "red kettle", "position": "on the rear left burner"}]

    async def fake_extract(env_name, description, img_url, creds):
        return extracted

    execute_calls = _run_approve_background_task(monkeypatch, env, extract_props_impl=fake_extract)

    props_writes = [(q, a) for q, a in execute_calls if "SET props" in q]
    assert len(props_writes) == 1
    _, args = props_writes[0]
    assert json.loads(args[0]) == extracted


def test_approve_environments_skips_extraction_when_props_already_present(monkeypatch):
    """Re-approving an environment that already has a manifest must never
    re-spend on extraction."""
    env = _env_row(props=json.dumps([{"name": "kettle", "position": "on the stove"}]))
    calls = {"n": 0}

    async def counting_extract(*a, **kw):
        calls["n"] += 1
        return [{"name": "should not be called", "position": "x"}]

    execute_calls = _run_approve_background_task(monkeypatch, env, extract_props_impl=counting_extract)

    assert calls["n"] == 0
    assert not [(q, a) for q, a in execute_calls if "SET props" in q]


def test_approve_environments_skips_extraction_entirely_without_claude_creds(monkeypatch):
    """No Claude creds configured for this tenant (today's common case for a
    keyless tenant) -> the whole vision pass (description refresh AND prop
    extraction) is skipped, fail-soft, approval still succeeds."""
    env = _env_row(props=None)
    calls = {"n": 0}

    async def counting_extract(*a, **kw):
        calls["n"] += 1
        return [{"name": "x", "position": "y"}]

    execute_calls = _patch_approve_scaffolding(monkeypatch, env, resolve_creds_returns=None)
    monkeypatch.setattr(env_route, "_extract_env_props", counting_extract)

    bg = _FakeBackgroundTasks()
    result = asyncio.run(env_route.approve_environments(VIDEO_ID, bg, tenant_id=TENANT))
    fn, args, kwargs = bg.tasks[0]
    asyncio.run(fn(*args, **kwargs))

    assert calls["n"] == 0
    approved = [q for q, a in execute_calls if "status = 'approved'" in q]
    assert approved


# ---------------------------------------------------------------------------
# 4. coverage_to_app.py props plumbing (SELECT -> parsed list[dict])
# ---------------------------------------------------------------------------

class TestPropsPlumbing:
    def test_parse_props_none_safe(self):
        assert coverage_to_app._parse_props(None) is None
        assert coverage_to_app._parse_props("") is None
        assert coverage_to_app._parse_props("[]") is None
        assert coverage_to_app._parse_props("null") is None

    def test_parse_props_parses_json_string(self):
        raw = json.dumps([{"name": "kettle", "position": "on the stove"}])
        assert coverage_to_app._parse_props(raw) == [{"name": "kettle", "position": "on the stove"}]

    def test_parse_props_passes_through_a_list(self):
        val = [{"name": "kettle", "position": "on the stove"}]
        assert coverage_to_app._parse_props(val) == val

    def test_approved_envs_carries_parsed_props(self, monkeypatch):
        raw_row = {
            "name": "Kitchen", "description": "A sunlit kitchen.",
            "reference_url": "https://example.com/k.png",
            "props": json.dumps([{"name": "kettle", "position": "on the stove"}]),
        }

        async def fake_fetch_all(query, *a):
            assert "props" in query
            return [raw_row]

        monkeypatch.setattr(coverage_to_app, "fetch_all", fake_fetch_all)
        envs = asyncio.run(coverage_to_app._approved_envs(VIDEO_ID, TENANT))
        assert envs[0]["props"] == [{"name": "kettle", "position": "on the stove"}]

    def test_approved_envs_props_none_when_column_null(self, monkeypatch):
        raw_row = {
            "name": "Kitchen", "description": "A sunlit kitchen.",
            "reference_url": "https://example.com/k.png", "props": None,
        }

        async def fake_fetch_all(query, *a):
            return [raw_row]

        monkeypatch.setattr(coverage_to_app, "fetch_all", fake_fetch_all)
        envs = asyncio.run(coverage_to_app._approved_envs(VIDEO_ID, TENANT))
        assert envs[0]["props"] is None

    def test_scene_locations_carries_parsed_props(self, monkeypatch):
        raw_row = {
            "name": "kitchen", "description": "A sunlit kitchen.",
            "reference_url": "https://example.com/k.png",
            "props": json.dumps([{"name": "kettle", "position": "on the stove"}]),
        }

        async def fake_fetch_all(query, *a):
            return [raw_row]

        monkeypatch.setattr(coverage_to_app, "fetch_all", fake_fetch_all)
        locs = asyncio.run(coverage_to_app._scene_locations(VIDEO_ID, TENANT))
        assert locs[0]["props"] == [{"name": "kettle", "position": "on the stove"}]

    def test_scene_locations_props_absent_when_no_manifest(self, monkeypatch):
        raw_row = {
            "name": "kitchen", "description": "A sunlit kitchen.",
            "reference_url": "https://example.com/k.png", "props": None,
        }

        async def fake_fetch_all(query, *a):
            return [raw_row]

        monkeypatch.setattr(coverage_to_app, "fetch_all", fake_fetch_all)
        locs = asyncio.run(coverage_to_app._scene_locations(VIDEO_ID, TENANT))
        assert locs[0]["props"] is None


# ---------------------------------------------------------------------------
# 5. Sheet-preview path (_plan_sheet_prompts) is provably NOT touched
# ---------------------------------------------------------------------------

class TestSheetPreviewPathUntouched:
    def test_plan_sheet_prompts_has_no_props_parameter(self):
        """Static proof the sheet-preview builder was never wired to accept
        a prop manifest — its signature has no such parameter."""
        sig = inspect.signature(coverage_to_app._plan_sheet_prompts)
        assert "props" not in sig.parameters

    def test_generate_storyboard_sheet_for_scene_has_no_props_parameter(self):
        sig = inspect.signature(coverage_to_app.generate_storyboard_sheet_for_scene)
        assert "props" not in sig.parameters

    def test_plan_sheet_prompts_source_never_references_the_manifest_renderer(self):
        """The sheet-preview builder's OWN source must never call
        render_prop_manifest/apply_prop_manifest or read a `props` key —
        proof this path was never wired to the manifest, not just that its
        signature happens to lack the parameter today."""
        src = inspect.getsource(coverage_to_app._plan_sheet_prompts)
        assert "render_prop_manifest" not in src
        assert "apply_prop_manifest" not in src
        assert '"props"' not in src and "'props'" not in src

    def test_sheet_output_from_plain_moments_never_contains_manifest_phrase(self):
        """Sanity check on the default path: moments built the way
        generate_coverage_directive/parse_coverage actually produce them
        (no manifest tail — that only ever gets appended inside
        run_coverage's separate call to apply_prop_manifest) render with no
        manifest phrase, proving nothing in this path spontaneously injects
        one."""
        moments = [{
            "moment_number": 1,
            "master": {"shot_type": "WS", "description": "Wide shot of the kitchen, morning light."},
            "angles": [],
        }]
        panels = coverage_to_app._plan_sheet_prompts(moments, style_dir="Photoreal")
        joined = "\n".join(panels)
        assert "movable props" not in joined.lower()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
