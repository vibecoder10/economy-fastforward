"""Tests for thumbnail/title_generator.py — the C34c/S10-5 de-branding fix.

TITLE_GENERATION_SYSTEM_PROMPT is the DEFAULT used whenever no tenant/video
system_prompt_override is set. Before this fix it hardcoded "Economy
FastForward, a finance/economics YouTube channel" plus a geopolitics-flavored
caps_word vocabulary — and because `_load_prompt_overrides` (pipeline_executor.py)
always resolves a non-blank "thumbnail" override for every StoryEngine
tenant, this default was DEAD in practice everywhere except the legacy
Airtable-only pipeline (which has no override mechanism at all) and any
future call site that forgets to wire an override — an "unguarded regression
trap" per the audit finding. This mirrors the existing de-branding regression
tests in storyengine/backend/tests/test_engine_templates.py.
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from thumbnail.title_generator import (
    TITLE_GENERATION_SYSTEM_PROMPT,
    TITLE_OUTPUT_CONTRACT,
    TitleGenerator,
)


class _StubAnthropicClient:
    """Captures the exact (prompt, system_prompt) sent to Claude, and returns
    a canned, schema-valid JSON title response."""

    def __init__(self, response: dict = None):
        self.calls = []
        self._response = response or {
            "title": "The Recipe TRAP Nobody Sees Coming (A 3-Step Fix)",
            "caps_word": "TRAP",
            "formula_used": "formula_1",
            "line_1": "THE TRAP",
            "line_2": "3 STEPS",
        }

    async def generate(self, prompt, system_prompt, model=None, max_tokens=None):
        self.calls.append({"prompt": prompt, "system_prompt": system_prompt})
        return json.dumps(self._response)


# ---------------------------------------------------------------------------
# The literal-text de-branding pin (grep-style, mirrors test_engine_templates.py)
# ---------------------------------------------------------------------------

def test_system_prompt_has_no_channel_branding():
    low = TITLE_GENERATION_SYSTEM_PROMPT.lower()
    assert "economy fastforward" not in low
    assert "power doctrine" not in low
    assert "finance/economics" not in low
    # The old MANDATORY branded caps-word vocabulary is gone as a fixed list —
    # the prompt now says to MATCH the register to the video, not prescribe
    # one channel's power words.
    assert "best caps_words (prefer these)" not in low


def test_system_prompt_examples_span_multiple_niches():
    """Mirrors engine_templates.py's already-neutral style: illustrate with
    more than one niche so no single vertical reads as the assumed default."""
    low = TITLE_GENERATION_SYSTEM_PROMPT.lower()
    assert "cooking" in low
    assert "language-learning" in low or "language learning" in low
    # Old prompt forced "[Country]" into formula shapes 2 and 4 — now neutral.
    assert "[country]" not in low
    assert "[subject]" in low


def test_output_contract_unchanged_mechanically():
    """The JSON schema mechanic (caps_word / line_1 / line_2 / formula_used)
    must survive the de-branding pass untouched — downstream parsing depends
    on it byte-for-byte."""
    for key in ("caps_word", "formula_used", "line_1", "line_2"):
        assert key in TITLE_GENERATION_SYSTEM_PROMPT
        assert key in TITLE_OUTPUT_CONTRACT
    assert "exactly ONE" in TITLE_GENERATION_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Runtime behavior: default vs. override precedence, and the user-prompt leak
# ---------------------------------------------------------------------------

def test_default_prompt_used_when_no_override():
    stub = _StubAnthropicClient()
    gen = TitleGenerator(stub, system_prompt_override=None)
    asyncio.run(gen.generate(video_title="How to Fold a Croissant", video_summary="Baking basics."))
    assert stub.calls[0]["system_prompt"] == TITLE_GENERATION_SYSTEM_PROMPT


def test_override_mechanism_still_wins():
    stub = _StubAnthropicClient()
    override = "You write titles for Poco a Poco, a Spanish-learning comedy channel."
    gen = TitleGenerator(stub, system_prompt_override=override)
    asyncio.run(gen.generate(video_title="Ordering Coffee in Spanish", video_summary="A comedy sketch."))
    sent = stub.calls[0]["system_prompt"]
    assert sent == override + "\n\n" + TITLE_OUTPUT_CONTRACT
    assert "economy fastforward" not in sent.lower()


def test_user_prompt_never_leaks_economy_fastforward_regardless_of_override():
    """Regression: the user-turn prompt literally said 'Generate a title for
    this Economy FastForward video' unconditionally, even when a tenant
    override replaced the system prompt (e.g. Poco a Poco, Designed vs Used,
    Slow English all got this leaked into their user turn)."""
    stub = _StubAnthropicClient()
    gen = TitleGenerator(stub, system_prompt_override="You write titles for Slow English.")
    asyncio.run(gen.generate(video_title="Talking About the Weather", video_summary="Simple ESL story."))
    assert "economy fastforward" not in stub.calls[0]["prompt"].lower()


def test_generate_result_shape_unchanged():
    stub = _StubAnthropicClient()
    gen = TitleGenerator(stub, system_prompt_override=None)
    result = asyncio.run(gen.generate(video_title="Something", video_summary="Something else."))
    for key in ("title", "caps_word", "formula_used", "line_1", "line_2"):
        assert key in result
    assert result["caps_word"] == "TRAP"
