"""Functional tests for the per-video character design step (routes/characters.py).

Stub-based — no DB or network. Covers cast extraction (Story Bible path +
script path via patched Claude), and pins the wiring that makes the feature
real: the executor's character gate + multi-ref pass-through to the
storyboard bot (the "wired but not plugged in" failure mode).

Run:  python3 tests/functional/test_characters.py   (from storyengine/backend)
"""

import asyncio
import json
import os
import sys
import types

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REPO = os.path.abspath(os.path.join(BACKEND, "..", ".."))
sys.path.insert(0, BACKEND)

# Stub heavy imports before loading the module under test
for name in ("auth", "database", "vault"):
    if name not in sys.modules:
        mod = types.ModuleType(name)
        if name == "auth":
            mod.get_tenant_id = lambda: "t"
        if name == "database":
            async def _f(*a, **k):
                return None
            mod.execute = _f
            mod.fetch_one = _f
            mod.fetch_all = _f
        if name == "vault":
            async def _gs(n, t=None):
                return "kie-key"
            mod.get_secret = _gs
        sys.modules[name] = mod

import routes.characters as ch  # noqa: E402


def test_extract_cast_from_story_bible():
    video = {
        "story_bible": json.dumps({
            "characters": [
                {"name": "Tom", "description": "8-year-old boy", "costume": "blue t-shirt, khaki shorts"},
                {"name": "Mom", "costume": "yellow sundress, brown braid"},
                {"name": "", "costume": "ignored — no name"},
            ]
        }),
        "script": "irrelevant — bible wins",
    }
    cast = asyncio.run(ch._extract_cast(video, "key"))
    assert [c["name"] for c in cast] == ["Tom", "Mom"], cast
    assert "blue t-shirt" in cast[0]["description"]
    print("PASS test_extract_cast_from_story_bible")


def test_extract_cast_from_script_via_claude():
    async def fake_call(prompt, creds, tier="smart", max_tokens=2000, image_url=None):
        assert "baby bird" in prompt
        return json.dumps({"characters": [
            {"name": "Tom", "description": "young boy, blue shirt"},
            {"name": "Lisa", "description": "younger sister, red dress"},
        ]})
    import routes.model_video as mv
    orig = mv._call_claude
    mv._call_claude = fake_call
    try:
        video = {"story_bible": None, "script": "Tom finds a baby bird. Lisa helps.", "tenant_id": None}
        cast = asyncio.run(ch._extract_cast(video, "key"))
        assert [c["name"] for c in cast] == ["Tom", "Lisa"], cast
    finally:
        mv._call_claude = orig
    print("PASS test_extract_cast_from_script_via_claude")


def test_extract_cast_requires_script():
    try:
        asyncio.run(ch._extract_cast({"story_bible": None, "script": ""}, "key"))
        assert False, "should have raised"
    except ValueError as e:
        assert "Write the script first" in str(e)
    print("PASS test_extract_cast_requires_script")


def test_executor_gate_and_multiref_wiring():
    """Pin the cross-layer wiring (file-level — modules are import-heavy)."""
    executor_src = open(os.path.join(BACKEND, "pipeline_executor.py")).read()
    assert "_load_character_refs" in executor_src
    assert executor_src.count("await self._load_character_refs(video_id, video)") >= 2, \
        "character gate must guard both storyboard grids and image generation"
    assert "characters_approved_at" in executor_src
    assert "character_reference_urls" in executor_src

    bot_src = open(os.path.join(REPO, "skills/video-pipeline/storyboard/bot.py")).read()
    assert "character_reference_urls=None" in bot_src, "bot must accept the cast list"
    assert "character_reference_urls or _load_character_reference" in bot_src, \
        "cast list must win over the legacy single reference"

    run_src = open(os.path.join(REPO, "skills/video-pipeline/storyboard/run_images.py")).read()
    assert 'getattr(pipeline, "character_reference_urls", None)' in run_src

    client_src = open(os.path.join(REPO, "skills/video-pipeline/shared/clients/image_client.py")).read()
    assert "isinstance(reference_image_url, list)" in client_src, \
        "generate_with_reference must accept a multi-character list"

    main_src = open(os.path.join(BACKEND, "main.py")).read()
    assert "characters.router" in main_src, "characters router not registered in main.py"
    print("PASS test_executor_gate_and_multiref_wiring")


def test_story_lock_gates():
    """Phase-3 pins: image spend + extraction are locked behind story_locked_at."""
    executor_src = open(os.path.join(BACKEND, "pipeline_executor.py")).read()
    assert executor_src.count('video.get("story_locked_at")') >= 2,         "both run_images and run_storyboard_extract must check the story lock"
    videos_src = open(os.path.join(BACKEND, "routes", "videos.py")).read()
    assert "/lock-story" in videos_src and "/unlock-story" in videos_src
    assert "Generate storyboard grids first" in videos_src,         "lock must require reviewed grids"
    mig = open(os.path.join(BACKEND, "migrations", "047_story_lock.sql")).read()
    assert "story_locked_at" in mig and "SET DEFAULT 'On'" in mig
    print("PASS test_story_lock_gates")


if __name__ == "__main__":
    test_extract_cast_from_story_bible()
    test_extract_cast_from_script_via_claude()
    test_extract_cast_requires_script()
    test_executor_gate_and_multiref_wiring()
    test_story_lock_gates()
    print("\nALL CHARACTER+LOCK TESTS PASSED (5/5)")
