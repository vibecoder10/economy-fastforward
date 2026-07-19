"""Tests for C24 (checklist §2.3 — "script-voice profiles not user-
selectable today"). shared.profiles.script/*.py (neutral_v1 default,
power_doctrine_v2/v1 opt-in) already existed but nothing let a creator pick
one; this chunk adds videos.script_profile (migration 098) + two write
doors, mirroring C20's VISUAL_PROFILE seam exactly.

Five layers pinned here, no live DB / no network (same TestClient +
monkeypatch pattern as test_c20_style_presets.py / test_c23_camera_presets.py):

  1. GET /api/script-profiles (routes/script_profiles.py) — catalog shape,
     copy pulled from each profile's own template_metadata, auth required.
  2. routes/videos.py's `_resolve_script_profile` — the create_video /
     update_video validation gate: a real registered profile id passes
     through unchanged, an unknown id 400s, blank/None is a silent no-op.
  3. pipeline_executor.py's `_resolve_script_profile_id` — the SCRIPT_PROFILE
     executor seam: an explicit script_profile wins; NULL/blank falls back
     to "neutral_v1" — the SAME default shared.profiles.script's
     load_script_profile() already uses, so this is byte-identical to the
     pre-C24 script voice. Power Doctrine is never the fallback.
  4. routes/videos.py's update_video — "script_profile" is in the generic
     PATCH allowed_fields set and re-validated there (the ScriptVoiceTab
     door).
  5. actions.py::_runner_script_profile — the conversational door ("write it
     in the investigative style"), same write (videos.script_profile), free
     (no confirm card), reversible ("neutral"/"auto" clears it).

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c24_script_profiles.py -q
"""
import asyncio
import os
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from auth import get_tenant_id
import routes.script_profiles as script_profiles_route  # noqa: E402
import routes.videos as videos_route  # noqa: E402
import actions  # noqa: E402
from pipeline_executor import _resolve_script_profile_id  # noqa: E402
from orchestrator.pipeline_constants import IdeaFields  # noqa: E402

TENANT = "00000000-0000-0000-0000-000000000000"
VIDEO_ID = "video-1"


def _profiles_client() -> TestClient:
    app = FastAPI()
    app.include_router(script_profiles_route.router)
    app.dependency_overrides[get_tenant_id] = lambda: TENANT
    return TestClient(app)


# =============================================================================
# Part 1 — GET /api/script-profiles
# =============================================================================

def test_returns_real_registered_profiles_with_default_first():
    client = _profiles_client()
    resp = client.get("/api/script-profiles")
    assert resp.status_code == 200
    profiles = resp.json()["profiles"]
    ids = [p["id"] for p in profiles]
    assert ids[0] == "neutral_v1", "the default must sort first"
    assert set(ids) == {"neutral_v1", "power_doctrine_v2", "power_doctrine_v1"}
    by_id = {p["id"]: p for p in profiles}
    assert by_id["neutral_v1"]["is_default"] is True
    assert by_id["power_doctrine_v2"]["is_default"] is False
    assert by_id["power_doctrine_v1"]["is_default"] is False
    for p in profiles:
        assert p["display_name"]
        assert p["description"]


def test_copy_pulled_verbatim_from_template_metadata_not_invented():
    """Pin the exact display_name/description each profile module declares
    in its own TemplateMetadata — this route must never hand-write copy."""
    from shared.profiles.script import load_script_profile
    client = _profiles_client()
    profiles = {p["id"]: p for p in client.get("/api/script-profiles").json()["profiles"]}
    for profile_id in ("neutral_v1", "power_doctrine_v2", "power_doctrine_v1"):
        source = load_script_profile(profile_id)
        assert profiles[profile_id]["display_name"] == source.template_metadata.display_name
        assert profiles[profile_id]["description"] == source.template_metadata.description


def test_requires_tenant_auth():
    app = FastAPI()
    app.include_router(script_profiles_route.router)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/script-profiles")
    assert resp.status_code in (401, 403, 422)


# =============================================================================
# Part 2 — routes/videos.py::_resolve_script_profile (write-time validation)
# =============================================================================

def test_resolve_blank_or_none_is_noop():
    assert videos_route._resolve_script_profile(None) is None
    assert videos_route._resolve_script_profile("   ") is None


def test_resolve_valid_registered_profile_passes_through():
    assert videos_route._resolve_script_profile("power_doctrine_v2") == "power_doctrine_v2"
    assert videos_route._resolve_script_profile("neutral_v1") == "neutral_v1"


def test_resolve_unknown_profile_raises_400():
    with __import__("pytest").raises(HTTPException) as exc_info:
        videos_route._resolve_script_profile("not_a_real_profile")
    assert exc_info.value.status_code == 400


# =============================================================================
# Part 3 — pipeline_executor.py::_resolve_script_profile_id (SCRIPT_PROFILE seam)
# =============================================================================

def test_explicit_script_profile_wins():
    idea = {IdeaFields.SCRIPT_PROFILE: "power_doctrine_v2"}
    assert _resolve_script_profile_id(idea) == "power_doctrine_v2"


def test_null_script_profile_falls_back_to_neutral_default_byte_identical():
    """The core stash-proof contract: no explicit script_profile (every
    pre-C24 video) must resolve to EXACTLY the value
    shared.profiles.script.DEFAULT_PROFILE_ID already uses — never
    power_doctrine, per storyengine/CLAUDE.md's deletion rule."""
    from shared.profiles.script import DEFAULT_PROFILE_ID
    assert _resolve_script_profile_id({}) == DEFAULT_PROFILE_ID == "neutral_v1"


def test_blank_script_profile_falls_through_not_treated_as_set():
    idea = {IdeaFields.SCRIPT_PROFILE: "   "}
    assert _resolve_script_profile_id(idea) == "neutral_v1"


def test_missing_field_entirely_also_falls_back():
    """A video row predating migration 098 has no 'Script Profile' key at
    all in the idea dict (not even a None) — .get() must not raise."""
    idea = {"Video Title": "Some Video"}
    assert _resolve_script_profile_id(idea) == "neutral_v1"


# =============================================================================
# Part 4 — routes/videos.py update_video — the ScriptVoiceTab write door
# =============================================================================

def _videos_client() -> TestClient:
    app = FastAPI()
    app.include_router(videos_route.router)
    app.dependency_overrides[get_tenant_id] = lambda: TENANT
    return TestClient(app)


def test_update_video_accepts_script_profile(monkeypatch):
    writes = []

    async def fake_fetch_one(query, *args):
        return {"id": VIDEO_ID}

    async def fake_execute(query, *args):
        writes.append((query, args))
        return "UPDATE 1"

    monkeypatch.setattr(videos_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(videos_route, "execute", fake_execute)
    client = _videos_client()
    resp = client.patch(f"/api/videos/{VIDEO_ID}", json={"script_profile": "power_doctrine_v2"})
    assert resp.status_code == 200
    query, args = writes[0]
    assert "script_profile" in query
    assert "power_doctrine_v2" in args


def test_update_video_rejects_unknown_script_profile(monkeypatch):
    async def fake_fetch_one(query, *args):
        return {"id": VIDEO_ID}

    async def fail_execute(*a, **k):
        raise AssertionError("must not write an unknown profile")

    monkeypatch.setattr(videos_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(videos_route, "execute", fail_execute)
    client = _videos_client()
    resp = client.patch(f"/api/videos/{VIDEO_ID}", json={"script_profile": "not_a_real_profile"})
    assert resp.status_code == 400


# =============================================================================
# Part 5 — actions.py::_runner_script_profile (the conversational door)
# =============================================================================

def test_script_profile_wired_into_actions_table_and_runners():
    assert actions.ACTIONS["script_profile"]["paid"] is False, "must run without a confirm card"
    assert actions.ACTIONS["script_profile"]["needs"] is None, "settable before or after script exists"
    assert actions.RUNNERS["script_profile"] is actions._runner_script_profile


def test_runner_resolves_investigative_alias_and_writes_video_scoped(monkeypatch):
    writes = []

    async def fake_execute(query, *args):
        writes.append((query, args))
        return "UPDATE 1"

    monkeypatch.setattr(actions, "execute", fake_execute)
    result = asyncio.run(actions._runner_script_profile(
        TENANT, VIDEO_ID, None, {"change": "write it in the investigative style"}))
    query, args = writes[0]
    assert "script_profile" in query
    assert args == ("power_doctrine_v2", VIDEO_ID, TENANT)
    assert "Investigative Reveal" in result


def test_runner_resolves_framework_explainer_alias():
    profile_id, is_clear = actions._resolve_script_profile_text("use the framework explainer voice")
    assert profile_id == "power_doctrine_v1"
    assert is_clear is False


def test_runner_clears_back_to_neutral(monkeypatch):
    writes = []

    async def fake_execute(query, *args):
        writes.append(args)
        return "UPDATE 1"

    monkeypatch.setattr(actions, "execute", fake_execute)
    result = asyncio.run(actions._runner_script_profile(
        TENANT, VIDEO_ID, None, {"change": "neutral"}))
    assert writes[0] == (None, VIDEO_ID, TENANT)
    assert "neutral" in result.lower()


def test_runner_unrecognized_text_writes_nothing(monkeypatch):
    async def fail_execute(*a, **k):
        raise AssertionError("must not write an unrecognized voice")
    monkeypatch.setattr(actions, "execute", fail_execute)
    result = asyncio.run(actions._runner_script_profile(
        TENANT, VIDEO_ID, None, {"change": "make it sparkle"}))
    assert "didn't recognize" in result.lower()


def test_runner_direct_catalog_id_also_resolves():
    """If the classifier already learned a real id (e.g. from
    GET /api/script-profiles), it resolves directly — the alias map is a
    fallback, not the only path."""
    profile_id, is_clear = actions._resolve_script_profile_text("power_doctrine_v1")
    assert profile_id == "power_doctrine_v1"
    assert is_clear is False


def test_power_doctrine_never_reachable_via_clear_words():
    """Clearing (auto/default/neutral/clear) must always land on None (the
    engine's own neutral default) — never accidentally alias to Power
    Doctrine, which stays strictly opt-in."""
    for word in actions._SCRIPT_PROFILE_CLEAR_WORDS:
        profile_id, is_clear = actions._resolve_script_profile_text(word)
        assert is_clear is True
        assert profile_id is None
