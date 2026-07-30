"""Tests for pipeline_executor.resolve_prompt — the pure per-key resolver.

Precedence: per-video override > tenant override > neutral engine template
(identity-filled). Keys without a template (sound_curation/sound_generation)
return None. Identity placeholders are filled in every path; foreign braces
(e.g. {HEADLINE}) are preserved.
"""
from identity import IdentityContext
from pipeline_executor import resolve_prompt


def _identity():
    return IdentityContext(
        channel_name="Calm Coding",
        niche="beginner programming tutorials",
        target_audience="self-taught developers",
        voice_style="patient and jargon-free",
        visual_style="minimalist line art",
        frameworks=["the 3-act explainer"],
    )


def test_tenant_override_wins_over_neutral_template():
    """A tenant override beats the neutral template — Phase 1 must not change
    behavior for tenants that already customized their prompt."""
    idc = _identity()
    tenant = "TENANT custom script prompt for {channel_name}."
    out = resolve_prompt(per_video=None, tenant=tenant, prompt_key="script", identity=idc)
    # The override is used (not the neutral template) and identity is injected.
    assert out.startswith("TENANT custom script prompt for Calm Coding.")


def test_per_video_override_wins_over_tenant():
    idc = _identity()
    out = resolve_prompt(
        per_video="PER-VIDEO wins",
        tenant="TENANT default",
        prompt_key="script",
        identity=idc,
    )
    # D6-3/D6-4: the override still wins outright over the tenant default,
    # but STORY-LAWS S3 and S1 ride along after it, in that order (same seam
    # standing_preferences uses) — a customized script prompt must not
    # silently opt out of either law. See tests/test_d6_3_story_law_s3.py
    # and tests/test_d6_4_story_law_s1.py for direct coverage of each
    # append; this only asserts the override still wins the FIRST slot in
    # precedence.
    import story_laws
    assert out == (
        "PER-VIDEO wins" + "\n\n" + story_laws.SCENE_LOCATION_LAW
        + "\n\n" + story_laws.LOCATION_TRANSIT_LAW
    )


def test_no_override_templated_key_returns_neutral_with_niche():
    """No override + a key that HAS a template -> neutral identity text, not
    None. This is the behavior change Phase 1 introduces."""
    idc = _identity()
    out = resolve_prompt(per_video=None, tenant=None, prompt_key="script", identity=idc)
    assert out is not None
    assert "beginner programming tutorials" in out
    assert "{niche}" not in out
    assert "power doctrine" not in out.lower()


def test_override_with_foreign_brace_is_preserved_and_niche_filled():
    """An override containing {HEADLINE} keeps {HEADLINE} verbatim while
    {niche} gets filled."""
    idc = _identity()
    override = "Write about {niche}. Headline slot: {HEADLINE}."
    out = resolve_prompt(per_video=override, tenant=None, prompt_key="script", identity=idc)
    assert "{HEADLINE}" in out
    assert "beginner programming tutorials" in out
    assert "{niche}" not in out


def test_sound_curation_no_override_returns_none():
    """A key with no engine template and no override -> None (bot uses its own
    neutral default)."""
    idc = _identity()
    out = resolve_prompt(per_video=None, tenant=None, prompt_key="sound_curation", identity=idc)
    assert out is None


def test_sound_curation_with_override_still_returns_filled_override():
    """Even a no-template key returns its override (identity-filled) when one
    exists."""
    idc = _identity()
    out = resolve_prompt(
        per_video=None,
        tenant="Sound design for {channel_name}.",
        prompt_key="sound_curation",
        identity=idc,
    )
    assert out == "Sound design for Calm Coding."


def test_blank_override_falls_through_to_neutral_template():
    """A whitespace-only override is treated as no override and falls through
    to the neutral template."""
    idc = _identity()
    out = resolve_prompt(per_video="   ", tenant=None, prompt_key="research", identity=idc)
    assert out is not None
    assert "beginner programming tutorials" in out
