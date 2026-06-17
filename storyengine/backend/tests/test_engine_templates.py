"""Tests for engine_templates.py — neutral craft skeletons + SAFE identity fill.

The critical safety property: safe_fill must fill ONLY the known identity
placeholders and leave every other brace (e.g. {HEADLINE}, {TOPIC}, JSON
{{...}}) byte-for-byte intact. Real prompts in this repo contain such braces
(see prompt_defaults.py), so a naive str.format() would crash or corrupt them.
"""
import pytest

from identity import IdentityContext
from engine_templates import ENGINE_TEMPLATES, safe_fill, render


def _identity():
    return IdentityContext(
        channel_name="Calm Coding",
        niche="beginner programming tutorials",
        target_audience="self-taught developers",
        voice_style="patient and jargon-free",
        visual_style="minimalist line art",
        frameworks=["the 3-act explainer", "show-then-tell"],
    )


def test_render_script_fills_niche_and_has_no_leftover_placeholder():
    out = render("script", _identity())
    assert "beginner programming tutorials" in out
    assert "{niche}" not in out
    assert "{channel_name}" not in out
    # Niche-neutral: no geopolitics / Power Doctrine / Economy FastForward
    low = out.lower()
    assert "power doctrine" not in low
    assert "geopolit" not in low
    assert "economy fastforward" not in low


def test_all_templates_render_clean_for_every_known_key():
    idc = _identity()
    for key in ENGINE_TEMPLATES:
        out = render(key, idc)
        assert out, f"{key} template rendered empty"
        for slot in ("{channel_name}", "{niche}", "{target_audience}",
                     "{voice_style}", "{visual_style}"):
            assert slot not in out, f"{key} left {slot} unfilled"
        assert "power doctrine" not in out.lower()


def test_safe_fill_preserves_foreign_braces():
    """THE key safety test: identity slots get filled, foreign braces survive
    verbatim (single {HEADLINE} and doubled {{x}})."""
    idc = _identity()
    text = "Topic {niche}. Headline: {HEADLINE}. JSON {{x}}"
    out = safe_fill(text, idc)

    assert "beginner programming tutorials" in out  # {niche} filled
    assert "{HEADLINE}" in out                       # unknown single-brace preserved
    assert "{{x}}" in out                            # doubled braces preserved verbatim
    assert out == "Topic beginner programming tutorials. Headline: {HEADLINE}. JSON {{x}}"


def test_safe_fill_joins_frameworks_when_referenced():
    idc = _identity()
    out = safe_fill("Use these frameworks: {frameworks}.", idc)
    assert "the 3-act explainer, show-then-tell" in out
    assert "{frameworks}" not in out


def test_safe_fill_empty_frameworks_is_blank_not_crash():
    idc = IdentityContext(
        channel_name="c", niche="n", target_audience="a",
        voice_style="v", visual_style="vs", frameworks=[],
    )
    out = safe_fill("Frameworks: [{frameworks}]", idc)
    assert out == "Frameworks: []"


def test_render_unknown_key_does_not_raise_and_returns_empty():
    out = render("does_not_exist", _identity())
    assert out == ""


def test_safe_fill_repeated_placeholder_all_replaced():
    idc = _identity()
    out = safe_fill("{niche} for {target_audience}, again {niche}", idc)
    assert out == ("beginner programming tutorials for self-taught developers, "
                   "again beginner programming tutorials")


def test_safe_fill_handles_no_placeholders():
    idc = _identity()
    assert safe_fill("plain text with no braces", idc) == "plain text with no braces"
