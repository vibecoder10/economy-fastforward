"""Tests for ENV-1 — a structured per-scene script location can never be
silently dropped, and a missed environment is recoverable without a full
paid redraw.

Real incident (2026-08-05, tenant PocoAPoco, video d39892b2-0c85-4752-85d7-
b61ca209342a): the video's submitted script tagged 7 scenes with per-scene
`location` values (STORY LAW S3, migration 144's `scripts.location`
column), but `_extract_locations_from_script` (routes/environments.py) only
ever read `video["script"]` prose through a Claude call — "the kitchen at
home" was never spoken in any dialogue line, so Claude found only 6 and the
7th was silently dropped. The only recovery was a full paid re-design of
every environment on the video.

This file covers:
  1. `_extract_locations_from_script` ALL-tagged branch — the real-incident
     shape: 7 scenes all carrying a `scripts.location`, one of them absent
     from every dialogue line. The Claude/Anthropic client must NOT be
     called at all, and all 7 locations must come back.
  2. The SOME-tagged branch: Claude runs (seeded with the known names) and
     its result is UNIONed with the structured set, so a structured
     location the model didn't surface is still returned.
  3. The NONE-tagged branch: byte-for-byte the pre-fix behavior — same
     prompt text, same return shape, LLM called exactly as before.
  4. `_dedupe_locations` — case-insensitive + whitespace-normalized dedupe,
     first-seen casing wins.
  5. `POST /{video_id}/environments` (create-one) — happy path + 404.
  6. MCP `add_environment` tool — happy path, matching the existing
     edit_environment/delete_environment MCP test conventions.

STASH-PROOF: with the ALL/SOME branching reverted to the old
prose-only-every-time behavior, test_all_scenes_tagged_bypasses_llm_and_
returns_all_seven (which asserts the Claude client is never called and all
7 locations return, including the undialogued one) fails a real assertion
— not an import/collection error.

Run: cd storyengine/backend && ./venv/bin/python -m pytest \
    tests/functional/test_env1_location_extraction.py -q
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import routes.environments as env_route  # noqa: E402
from auth import get_tenant_id  # noqa: E402

TENANT = "tenant-poco"
VIDEO_ID = "d39892b2-0c85-4752-85d7-b61ca209342a"


def _video_row(**over):
    base = {
        "id": VIDEO_ID, "tenant_id": TENANT, "video_title": "Test Video",
        "script": "", "image_style_override": None, "original_dna": None,
        "story_bible": None, "aspect_ratio": "16:9",
        "environments_approved_at": None, "project_id": None,
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# 1. ALL scenes tagged — the real incident shape
# ---------------------------------------------------------------------------

REAL_INCIDENT_SCENES = [
    {"scene": 1, "location": "the living room"},
    {"scene": 2, "location": "the front porch"},
    {"scene": 3, "location": "the kitchen at home"},  # never spoken aloud
    {"scene": 4, "location": "the driveway"},
    {"scene": 5, "location": "the garage"},
    {"scene": 6, "location": "the backyard"},
    {"scene": 7, "location": "the mailbox"},
]

# Dialogue-only prose a Claude prose extractor would see — deliberately
# omits any mention of "kitchen" (the real-incident failure condition).
REAL_INCIDENT_SCRIPT = (
    "Sam paced the living room, waiting. Out on the front porch, the mail truck rattled by. "
    "Sam jogged down the driveway to check. In the garage, the old bike still leaned against "
    "the wall. Later, out back in the yard, the dog barked at the fence. Finally, Sam opened "
    "the mailbox and found the letter."
)


class TestAllScenesTaggedBypassesLLM:
    def test_all_seven_locations_returned_including_the_undialogued_one(self, monkeypatch):
        video = _video_row(script=REAL_INCIDENT_SCRIPT)

        async def fake_fetch_all(query, *args):
            assert "FROM scripts" in query
            return REAL_INCIDENT_SCENES

        claude_calls = {"n": 0}

        async def spy_call_claude(*a, **kw):
            claude_calls["n"] += 1
            raise AssertionError("Claude must never be called on the all-tagged path")

        import routes.model_video as model_video_mod
        monkeypatch.setattr(env_route, "fetch_all", fake_fetch_all)
        monkeypatch.setattr(model_video_mod, "_call_claude", spy_call_claude)

        result = asyncio.run(env_route._extract_locations_from_script(video, "fake-kie-key"))

        assert claude_calls["n"] == 0, "the Anthropic/Claude client must NOT be called on the all-locations path"
        names = [r["name"] for r in result]
        assert len(result) == 7
        assert "the kitchen at home" in names, "the undialogued structured location must not be dropped"
        # Scene order preserved.
        assert names == [s["location"] for s in REAL_INCIDENT_SCENES]

    def test_all_tagged_with_no_script_prose_still_returns_all(self, monkeypatch):
        """Even a completely empty script (never reaches the prose branch at
        all) must not lose structured locations."""
        video = _video_row(script="")

        async def fake_fetch_all(query, *args):
            return REAL_INCIDENT_SCENES

        monkeypatch.setattr(env_route, "fetch_all", fake_fetch_all)
        result = asyncio.run(env_route._extract_locations_from_script(video, "fake-kie-key"))
        assert len(result) == 7


# ---------------------------------------------------------------------------
# 2. SOME scenes tagged — seed + union, never a silent drop
# ---------------------------------------------------------------------------

PARTIAL_SCENES = [
    {"scene": 1, "location": "the kitchen at home"},
    {"scene": 2, "location": ""},  # untagged
    {"scene": 3, "location": None},  # untagged
]

PARTIAL_SCRIPT = "Sam cooked dinner. Later, at the lake, Sam watched the sunset. Then home again."


class TestSomeScenesTaggedUnion:
    def test_llm_omits_structured_location_union_still_returns_it(self, monkeypatch):
        """Claude's own extraction (mocked) finds only 'Lake Shore' — the
        structured 'the kitchen at home' from scene 1 must still appear in
        the final result via UNION, never silently dropped."""
        video = _video_row(script=PARTIAL_SCRIPT)

        async def fake_fetch_all(query, *args):
            return PARTIAL_SCENES

        seen_prompts = []

        async def fake_call_claude(prompt, creds, tier="smart", max_tokens=2000):
            seen_prompts.append(prompt)
            import json
            return json.dumps({"locations": [
                {"name": "Lake Shore", "description": "a calm lake at sunset"},
            ]})

        async def fake_resolve_creds(tenant_id):
            return {"provider": "anthropic", "key": "fake-key"}

        import routes.model_video as model_video_mod
        monkeypatch.setattr(env_route, "fetch_all", fake_fetch_all)
        monkeypatch.setattr(model_video_mod, "_call_claude", fake_call_claude)
        monkeypatch.setattr(model_video_mod, "_resolve_claude_creds", fake_resolve_creds)

        result = asyncio.run(env_route._extract_locations_from_script(video, "fake-kie-key"))

        names = [r["name"] for r in result]
        assert "Lake Shore" in names
        assert "the kitchen at home" in names, "structured location must survive UNION even when the LLM misses it"

        # Seeding: the prompt sent to Claude must mention the known location.
        assert len(seen_prompts) == 1
        assert "the kitchen at home" in seen_prompts[0]
        assert "already tagged" in seen_prompts[0]

    def test_llm_finds_the_same_location_no_duplicate(self, monkeypatch):
        """When Claude's own extraction ALSO finds the structured location
        (possibly with a richer description), the union must not duplicate
        it — the LLM's (fuller) entry wins."""
        video = _video_row(script=PARTIAL_SCRIPT)

        async def fake_fetch_all(query, *args):
            return PARTIAL_SCENES

        async def fake_call_claude(prompt, creds, tier="smart", max_tokens=2000):
            import json
            return json.dumps({"locations": [
                {"name": "the kitchen at home", "description": "a bright kitchen with a big window"},
                {"name": "Lake Shore", "description": "a calm lake at sunset"},
            ]})

        async def fake_resolve_creds(tenant_id):
            return {"provider": "anthropic", "key": "fake-key"}

        import routes.model_video as model_video_mod
        monkeypatch.setattr(env_route, "fetch_all", fake_fetch_all)
        monkeypatch.setattr(model_video_mod, "_call_claude", fake_call_claude)
        monkeypatch.setattr(model_video_mod, "_resolve_claude_creds", fake_resolve_creds)

        result = asyncio.run(env_route._extract_locations_from_script(video, "fake-kie-key"))

        kitchens = [r for r in result if r["name"].casefold() == "the kitchen at home"]
        assert len(kitchens) == 1, "no duplicate entry for a location both structured data and the LLM found"
        assert kitchens[0]["description"] == "a bright kitchen with a big window", "the LLM's richer description wins on a collision"

    def test_claude_failure_falls_back_to_structured_never_to_empty(self, monkeypatch):
        video = _video_row(script=PARTIAL_SCRIPT)

        async def fake_fetch_all(query, *args):
            return PARTIAL_SCENES

        async def boom_call_claude(*a, **kw):
            raise RuntimeError("network down")

        async def fake_resolve_creds(tenant_id):
            return {"provider": "anthropic", "key": "fake-key"}

        import routes.model_video as model_video_mod
        monkeypatch.setattr(env_route, "fetch_all", fake_fetch_all)
        monkeypatch.setattr(model_video_mod, "_call_claude", boom_call_claude)
        monkeypatch.setattr(model_video_mod, "_resolve_claude_creds", fake_resolve_creds)

        result = asyncio.run(env_route._extract_locations_from_script(video, "fake-kie-key"))
        assert [r["name"] for r in result] == ["the kitchen at home"]


# ---------------------------------------------------------------------------
# 3. NONE tagged — byte-for-byte the old behavior
# ---------------------------------------------------------------------------

NONE_TAGGED_SCENES = [
    {"scene": 1, "location": None},
    {"scene": 2, "location": ""},
]

NONE_TAGGED_SCRIPT = "Sam cooked dinner in the kitchen. Later, at the lake, Sam watched the sunset."


def _expected_old_prompt(script: str) -> str:
    """Reconstructs the EXACT pre-fix prompt string (MAX_ENVIRONMENTS
    unchanged, no seed_line) to assert byte-identical output."""
    return f"""Read this script and list every VISUALLY DISTINCT location shown on screen — one
environment per place that LOOKS different and would need its OWN reference image. Two rooms in
the same building are SEPARATE environments if they look different: a kitchen and a garage are
TWO environments, not one "home"; an indoor room and an outdoor shore are separate. ONLY merge
shots of the literally same room/place (e.g. two angles of the same kitchen). Skip one-off
throwaway mentions. Maximum {env_route.MAX_ENVIRONMENTS}.

SCRIPT:
{script[:12000]}

Return ONLY valid JSON:
{{"locations": [{{"name": "short SPECIFIC place name (e.g. 'Kitchen', 'Garage', 'Lake shore' — never a combined 'Home/Garage')", "description": "what the place looks like + its lighting/time of day, written so an image generator draws the SAME place every time (40-80 words). NEVER mention knives, blades, scissors, sharp tools or weapons — describe food as already prepared, utensils as spoons/wooden tools"}}]}}"""


class TestNoneScenesTaggedUnchanged:
    def test_prompt_is_byte_identical_to_pre_fix_and_llm_still_called(self, monkeypatch):
        video = _video_row(script=NONE_TAGGED_SCRIPT)

        async def fake_fetch_all(query, *args):
            return NONE_TAGGED_SCENES

        seen_prompts = []

        async def fake_call_claude(prompt, creds, tier="smart", max_tokens=2000):
            seen_prompts.append(prompt)
            import json
            return json.dumps({"locations": [
                {"name": "Kitchen", "description": "a bright kitchen"},
                {"name": "Lake Shore", "description": "a calm lake at sunset"},
            ]})

        async def fake_resolve_creds(tenant_id):
            return {"provider": "anthropic", "key": "fake-key"}

        import routes.model_video as model_video_mod
        monkeypatch.setattr(env_route, "fetch_all", fake_fetch_all)
        monkeypatch.setattr(model_video_mod, "_call_claude", fake_call_claude)
        monkeypatch.setattr(model_video_mod, "_resolve_claude_creds", fake_resolve_creds)

        result = asyncio.run(env_route._extract_locations_from_script(video, "fake-kie-key"))

        assert len(seen_prompts) == 1
        assert seen_prompts[0] == _expected_old_prompt(NONE_TAGGED_SCRIPT)
        assert [r["name"] for r in result] == ["Kitchen", "Lake Shore"]

    def test_no_scripts_rows_at_all_also_unchanged(self, monkeypatch):
        """A video with no `scripts` rows yet (e.g. Story Bible path never
        populated them) must take the exact same prose-only path."""
        video = _video_row(script=NONE_TAGGED_SCRIPT)

        async def fake_fetch_all(query, *args):
            return []

        seen_prompts = []

        async def fake_call_claude(prompt, creds, tier="smart", max_tokens=2000):
            seen_prompts.append(prompt)
            import json
            return json.dumps({"locations": []})

        async def fake_resolve_creds(tenant_id):
            return {"provider": "anthropic", "key": "fake-key"}

        import routes.model_video as model_video_mod
        monkeypatch.setattr(env_route, "fetch_all", fake_fetch_all)
        monkeypatch.setattr(model_video_mod, "_call_claude", fake_call_claude)
        monkeypatch.setattr(model_video_mod, "_resolve_claude_creds", fake_resolve_creds)

        asyncio.run(env_route._extract_locations_from_script(video, "fake-kie-key"))
        assert seen_prompts[0] == _expected_old_prompt(NONE_TAGGED_SCRIPT)

    def test_empty_script_and_no_tags_returns_empty_list_llm_never_called(self, monkeypatch):
        video = _video_row(script="")

        async def fake_fetch_all(query, *args):
            return []

        monkeypatch.setattr(env_route, "fetch_all", fake_fetch_all)
        result = asyncio.run(env_route._extract_locations_from_script(video, "fake-kie-key"))
        assert result == []


# ---------------------------------------------------------------------------
# 4. _dedupe_locations
# ---------------------------------------------------------------------------

class TestDedupeLocations:
    def test_case_and_whitespace_insensitive_first_seen_casing_wins(self):
        result = env_route._dedupe_locations([
            {"name": "the Kitchen", "description": "first"},
            {"name": "  the   kitchen  ", "description": "second, dropped"},
            {"name": "THE KITCHEN", "description": "third, dropped"},
            {"name": "Garage", "description": "kept, distinct"},
        ])
        assert [r["name"] for r in result] == ["the Kitchen", "Garage"]
        assert result[0]["description"] == "first"

    def test_empty_names_skipped(self):
        result = env_route._dedupe_locations([{"name": "", "description": "x"}, {"name": "   ", "description": "y"}])
        assert result == []

    def test_preserves_input_order(self):
        result = env_route._dedupe_locations([
            {"name": "B"}, {"name": "A"}, {"name": "C"},
        ])
        assert [r["name"] for r in result] == ["B", "A", "C"]


# ---------------------------------------------------------------------------
# 5. POST /{video_id}/environments — create-one endpoint
# ---------------------------------------------------------------------------

def _build_client(monkeypatch, *, video_exists=True):
    async def fake_get_video(video_id, tenant_id):
        if not video_exists:
            raise HTTPException(status_code=404, detail="Video not found")
        return _video_row()

    inserted = {}

    async def fake_fetch_one(query, *args):
        if "COALESCE(MAX(sort)" in query:
            return {"next_sort": 3}
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


class TestCreateEnvironmentEndpoint:
    def test_happy_path_creates_draft_row(self, monkeypatch):
        client, inserted = _build_client(monkeypatch)
        resp = client.post(
            f"/api/videos/{VIDEO_ID}/environments",
            json={"name": "the kitchen at home", "description": "a bright kitchen"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == "the kitchen at home"
        assert body["description"] == "a bright kitchen"
        assert body["status"] == "draft"
        assert body["reference_url"] is None
        assert inserted["args"][4] == 3  # appended after existing max sort

    def test_missing_name_is_rejected(self, monkeypatch):
        client, _ = _build_client(monkeypatch)
        resp = client.post(f"/api/videos/{VIDEO_ID}/environments", json={"name": "   "})
        assert resp.status_code == 422

    def test_unknown_video_is_404(self, monkeypatch):
        client, _ = _build_client(monkeypatch, video_exists=False)
        resp = client.post(f"/api/videos/{VIDEO_ID}/environments", json={"name": "Kitchen"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 6. MCP add_environment tool
# ---------------------------------------------------------------------------

class TestMcpAddEnvironment:
    def test_add_environment_calls_shared_create_route(self, monkeypatch):
        import routes.mcp as mcp_route

        calls = []

        async def fake_create_environment(video_id, body, tenant_id):
            calls.append((video_id, body.name, body.description, tenant_id))
            return {"id": "env-new", "name": body.name, "description": body.description,
                    "reference_url": None, "status": "draft", "source": "generated", "sort": 0}

        monkeypatch.setattr(env_route, "create_environment", fake_create_environment)

        result = asyncio.run(mcp_route._call_add_environment(
            TENANT, {"video_id": VIDEO_ID, "name": "the kitchen at home", "description": "a bright kitchen"},
            "test-caller",
        ))

        assert len(calls) == 1
        assert calls[0][0] == VIDEO_ID
        assert calls[0][1] == "the kitchen at home"
        assert calls[0][2] == "a bright kitchen"
        assert calls[0][3] == TENANT
        assert result["isError"] is False

    def test_add_environment_registered_as_free_handler(self):
        import routes.mcp as mcp_route
        assert "add_environment" in mcp_route._ENVIRONMENT_FREE_HANDLERS
        assert mcp_route._ENVIRONMENT_FREE_HANDLERS["add_environment"] is mcp_route._call_add_environment

    def test_add_environment_tool_listed_in_tools(self):
        import routes.mcp as mcp_route
        names = [t["name"] for t in mcp_route._ENVIRONMENT_TOOLS]
        assert "add_environment" in names

    def test_missing_video_id_or_name_is_error_result(self):
        import routes.mcp as mcp_route
        result = asyncio.run(mcp_route._call_add_environment(TENANT, {"video_id": VIDEO_ID}, "test-caller"))
        assert result.get("isError") is True

    def test_video_not_found_returns_error_result(self, monkeypatch):
        import routes.mcp as mcp_route

        async def fake_create_environment(video_id, body, tenant_id):
            raise HTTPException(status_code=404, detail="Video not found")

        monkeypatch.setattr(env_route, "create_environment", fake_create_environment)
        result = asyncio.run(mcp_route._call_add_environment(
            TENANT, {"video_id": "missing-video", "name": "Kitchen"}, "test-caller",
        ))
        assert result.get("isError") is True


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
