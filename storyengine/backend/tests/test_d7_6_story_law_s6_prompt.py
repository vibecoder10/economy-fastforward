"""D7-6 — STORY-LAWS S6 (THE SCRIPT IS THE ORIGIN OF TRUTH, AND CHANGING IT
INVALIDATES WHAT CAME BEFORE): the PROMPT leg.

S6's GATE (hash compare-and-flag: videos.characters_hash/environments_hash,
migration 145) and REPAIR (invalidation on every scene-text write) legs
already landed on main — see tests/functional/test_d7_2_staleness_hash.py
and tests/functional/test_d7_3_scene_edit_invalidation.py. Neither is touched
here. This file covers only the missing third leg: the law's TEXT reaching
every script-generation prompt, mirroring exactly how
tests/test_d6_4_story_law_s1.py proves S1's PROMPT leg rides alongside S3's
at the same two call sites.

Covers:
  - pipeline_executor.resolve_prompt: SCRIPT_IS_SOURCE_OF_TRUTH_LAW rides
    alongside SCENE_LOCATION_LAW/LOCATION_TRANSIT_LAW for prompt_key=="script"
    only, never leaking into other prompt keys.
  - pipeline_executor._run_modeled_script: the same constant appears in the
    inline prompt sent to the model for a modeled ("Model A Video") script.
  - routes/mcp.py's submit_script tool description: explains S6 to a
    submitting agent, same as it already does for S1/S3.
  - user_script.py: the module docstring and accept_external_script's
    docstring state the S6 contract for a human reader of the external-
    script acceptance surface.

Local/no-spend: every Claude/provider call is faked; no I/O beyond an
in-memory monkeypatched `execute`. Same pattern test_d6_4_story_law_s1.py
already uses for _run_modeled_script.

Run: cd storyengine/backend && ./venv/bin/python -m pytest \
    tests/test_d7_6_story_law_s6_prompt.py -q
"""

import asyncio

import story_laws


# ---------------------------------------------------------------------------
# resolve_prompt — S6 rides along with S3/S1, at the very end
# ---------------------------------------------------------------------------

def test_resolve_prompt_appends_source_of_truth_law_for_script_key():
    import pipeline_executor as pe
    from identity import IdentityContext

    identity = IdentityContext(
        channel_name="Test Channel", niche="cooking", target_audience="home cooks",
        voice_style="warm", visual_style="bright", frameworks=[],
    )
    resolved = pe.resolve_prompt(None, None, "script", identity)
    assert story_laws.SCENE_LOCATION_LAW in resolved
    assert story_laws.LOCATION_TRANSIT_LAW in resolved
    assert story_laws.SCRIPT_IS_SOURCE_OF_TRUTH_LAW in resolved


def test_resolve_prompt_does_not_leak_source_of_truth_law_into_other_prompt_keys():
    import pipeline_executor as pe
    from identity import IdentityContext

    identity = IdentityContext(
        channel_name="Test Channel", niche="cooking", target_audience="home cooks",
        voice_style="warm", visual_style="bright", frameworks=[],
    )
    resolved = pe.resolve_prompt(None, None, "thumbnail", identity)
    assert resolved is None or story_laws.SCRIPT_IS_SOURCE_OF_TRUTH_LAW not in resolved


def test_resolve_prompt_per_video_override_still_carries_source_of_truth_law():
    """A tenant/per-video custom script prompt does not get to silently opt
    out of S6 — same guarantee resolve_prompt already gives S1/S3 (see
    test_resolve_prompt.py's per-video-override test)."""
    import pipeline_executor as pe
    from identity import IdentityContext

    identity = IdentityContext(
        channel_name="Test Channel", niche="cooking", target_audience="home cooks",
        voice_style="warm", visual_style="bright", frameworks=[],
    )
    resolved = pe.resolve_prompt("A CUSTOM per-video script prompt", None, "script", identity)
    assert "A CUSTOM per-video script prompt" in resolved
    assert story_laws.SCRIPT_IS_SOURCE_OF_TRUTH_LAW in resolved


# ---------------------------------------------------------------------------
# _run_modeled_script — the modeled path's own inline prompt
# ---------------------------------------------------------------------------

class _FakeAnthropicModeled:
    def __init__(self, raw):
        self.raw = raw
        self.captured_prompts = []

    async def generate(self, **kwargs):
        self.captured_prompts.append(kwargs.get("prompt"))
        return self.raw


def _modeled_video(**overrides):
    video = {
        "id": "video-1", "video_title": "Modeled Video", "status": "ready_for_scripting",
        "source": "modeled", "script_system_prompt": "Write like the reference.",
        "video_length_minutes": 3, "original_dna": None, "writer_guidance": "",
        "research_payload": None,
    }
    video.update(overrides)
    return video


def test_modeled_prompt_includes_source_of_truth_law(monkeypatch):
    import pipeline_executor as pe

    fake = _FakeAnthropicModeled(
        "@@@SCENE 1@@@\nLOCATION: the garage\nShe opens the hatch.\n"
        "@@@SCENE 2@@@\nLOCATION: the corridor\nShe runs down the hall.\n"
        "@@@SCENE 3@@@\nLOCATION: the lakeside dock\nThe boat is gone.\n"
    )
    video = _modeled_video()
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-1"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": fake})()

    async def fake_execute(query, *args):
        return None

    async def fake_log_activity(*_a, **_k):
        return None

    async def fake_log_transition(*_a, **_k):
        return None

    monkeypatch.setattr(pe, "execute", fake_execute)
    executor._log_activity = fake_log_activity
    executor._log_transition = fake_log_transition

    asyncio.run(executor._run_modeled_script("video-1", video))
    assert any(
        story_laws.SCRIPT_IS_SOURCE_OF_TRUTH_LAW in (p or "")
        for p in fake.captured_prompts
    )


# ---------------------------------------------------------------------------
# routes/mcp.py submit_script tool description — explains S6 to a
# submitting agent, same as it already does for S1/S3.
# ---------------------------------------------------------------------------

def test_submit_script_tool_description_explains_s6():
    from routes.mcp import _SUBMIT_SCRIPT_TOOL

    description = _SUBMIT_SCRIPT_TOOL["description"]
    assert "STORY LAW S6" in description
    assert "ORIGIN OF TRUTH" in description
    assert "stale" in description.lower()


# ---------------------------------------------------------------------------
# user_script.py — the external-script acceptance surface's own docstrings
# state the S6 contract for a human reader.
# ---------------------------------------------------------------------------

def test_user_script_module_docstring_states_s6_contract():
    import user_script

    assert "S6" in user_script.__doc__
    assert "stale" in user_script.__doc__.lower()


def test_accept_external_script_docstring_states_s6_contract():
    import user_script

    doc = user_script.accept_external_script.__doc__ or ""
    assert "S6" in doc
    assert "stale" in doc.lower()
