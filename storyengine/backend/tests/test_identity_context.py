"""Tests for identity.py — the single IdentityContext that Phase 1 injects.

These run under plain pytest (no pytest-asyncio in this repo). The pure
builder is synchronous; the async fetcher is driven via asyncio.run inside
sync test bodies so the coroutine actually executes.

The conftest.py at tests/conftest.py already adds storyengine/backend to
sys.path, so `import identity` resolves.
"""
import asyncio

from identity import (
    IdentityContext,
    build_identity_context_from_rows,
    build_identity_context,
)


def test_builds_from_profile_row():
    """A populated channel_profiles row fills every identity slot."""
    profile = {
        "channel_name": "Calm Coding",
        "niche": "beginner programming tutorials",
        "target_audience": "self-taught developers",
        "style_description": "patient, encouraging, jargon-free",
        "frameworks": ["the 3-act explainer", "show-then-tell"],
    }
    idc = build_identity_context_from_rows(project=None, profile=profile, video=None)

    assert isinstance(idc, IdentityContext)
    assert idc.channel_name == "Calm Coding"
    assert idc.niche == "beginner programming tutorials"
    assert idc.target_audience == "self-taught developers"
    assert idc.voice_style == "patient, encouraging, jargon-free"
    # No video override and no image_style_override -> falls back to style_description
    assert idc.visual_style == "patient, encouraging, jargon-free"
    assert idc.frameworks == ["the 3-act explainer", "show-then-tell"]


def test_empty_falls_back_to_neutral_and_never_geopolitics():
    """All-empty inputs produce a safe, generic identity — never blank,
    never Power Doctrine / geopolitics."""
    idc = build_identity_context_from_rows(project=None, profile=None, video=None)

    assert idc.channel_name == "this channel"
    assert idc.niche == "general educational content"
    assert "geopolit" not in idc.niche.lower()
    assert idc.target_audience == "a general audience"
    assert idc.voice_style == "clear, engaging, and natural"
    assert idc.visual_style == "a clean, consistent illustrated style"
    assert idc.frameworks == []


def test_empty_strings_treated_as_missing():
    """Blank strings must not survive — they fall through to neutral defaults."""
    project = {"name": "", "niche": ""}
    profile = {
        "channel_name": "",
        "niche": "",
        "target_audience": "  ",
        "style_description": "",
        "frameworks": None,
    }
    video = {"image_style_override": ""}
    idc = build_identity_context_from_rows(project=project, profile=profile, video=video)

    assert idc.channel_name == "this channel"
    assert idc.niche == "general educational content"
    assert idc.target_audience == "a general audience"
    assert idc.voice_style == "clear, engaging, and natural"
    assert idc.visual_style == "a clean, consistent illustrated style"
    assert idc.frameworks == []


def test_project_niche_overrides_profile_niche():
    """projects is the source of truth the Profile UI edits — it wins over
    the legacy channel_profiles row for name and niche."""
    project = {"name": "Project Channel", "niche": "home gardening"}
    profile = {
        "channel_name": "Legacy Channel",
        "niche": "stale onboarding niche",
        "target_audience": "weekend gardeners",
        "style_description": "warm and practical",
    }
    idc = build_identity_context_from_rows(project=project, profile=profile, video=None)

    assert idc.channel_name == "Project Channel"
    assert idc.niche == "home gardening"
    # target_audience / voice still come from the profile
    assert idc.target_audience == "weekend gardeners"
    assert idc.voice_style == "warm and practical"


def test_video_image_style_override_wins_for_visual():
    """A per-video image_style_override beats the profile style for visuals
    but does not change the voice_style."""
    profile = {"style_description": "minimalist line art"}
    video = {"image_style_override": "neon synthwave"}
    idc = build_identity_context_from_rows(project=None, profile=profile, video=video)

    assert idc.visual_style == "neon synthwave"
    assert idc.voice_style == "minimalist line art"


def test_async_build_uses_fetch_one_then_pure_builder(monkeypatch):
    """The async fetcher pulls projects then channel_profiles and hands them
    to the pure builder. We stub identity.fetch_one."""
    import identity as id_mod

    calls = []

    async def fake_fetch_one(query, *args):
        calls.append(query)
        if "projects" in query:
            return {"name": "Async Channel", "niche": "personal finance"}
        if "channel_profiles" in query:
            return {
                "channel_name": "ignored-legacy",
                "niche": "ignored-legacy",
                "target_audience": "new investors",
                "style_description": "approachable and concrete",
                "frameworks": ["the napkin math"],
            }
        return None

    monkeypatch.setattr(id_mod, "fetch_one", fake_fetch_one)

    video = {"image_style_override": None}
    idc = asyncio.run(build_identity_context("tenant-xyz", video))

    assert idc.channel_name == "Async Channel"
    assert idc.niche == "personal finance"
    assert idc.target_audience == "new investors"
    assert idc.voice_style == "approachable and concrete"
    assert idc.frameworks == ["the napkin math"]
    # Both tables were consulted
    assert any("projects" in q for q in calls)
    assert any("channel_profiles" in q for q in calls)


def test_async_build_is_defensive_on_db_error(monkeypatch):
    """If the DB raises, the async fetcher returns the neutral fallback
    rather than propagating — generation must never crash on identity."""
    import identity as id_mod

    async def boom(query, *args):
        raise RuntimeError("db down")

    monkeypatch.setattr(id_mod, "fetch_one", boom)

    idc = asyncio.run(build_identity_context("tenant-xyz", None))

    assert idc.channel_name == "this channel"
    assert idc.niche == "general educational content"
    assert idc.frameworks == []
