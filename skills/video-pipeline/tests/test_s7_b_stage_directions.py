"""S7-B (STORY-LAWS.md S7 — scripts.action, migration 154) — the coverage.py
side: threading the script's canonical scripts.action into the PLANNING
PROMPT (generate_coverage_directive / _coverage_user_prompt's DECLARED STAGE
DIRECTIONS block), rule 31's cross-reference, and the WARN-only drift alarm
(check_stage_direction_presence).

Companion file storyengine/backend/tests/functional/test_s7_b_stage_
directions.py covers the coverage_to_app.py sheet-composer side (the hash
gate, the SHEET path's threading, the completion-message suffix — needs the
backend's own venv) and duplicates a couple of the presence-check tests
below so the backend suite is self-contained too.

Run (TARGETED — the full skills suite has a pre-existing collection error in
test_ctr_12h_tracking.py, unrelated to this chunk, do not try to fix it here):
    cd skills/video-pipeline && \
        <backend-venv>/bin/python -m pytest \
        tests/test_s7_b_stage_directions.py -q
"""
import asyncio
import os
import sys

_PIPELINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PIPELINE_ROOT)
sys.path.insert(0, os.path.join(_PIPELINE_ROOT, "storyboard"))
sys.path.append(os.path.join(_PIPELINE_ROOT, "image_prompts"))

from storyboard.coverage import (  # noqa: E402
    _coverage_system_prompt, _coverage_user_prompt, generate_coverage_directive,
    check_stage_direction_presence,
)
from shared.channel_profile import load_profile  # noqa: E402

_PROFILE = load_profile({})

ACTION_TEXT = "A stray cat leaps onto the windowsill."


# =============================================================================
# _coverage_system_prompt — rule 31's cross-reference is present
# =============================================================================

def test_system_prompt_carries_rule_31_stage_direction_marker():
    prompt = _coverage_system_prompt(_PROFILE, max_moments=6, angles_min=2, angles_max=4)
    assert "31)" in prompt
    assert "DECLARED STAGE DIRECTIONS" in prompt
    assert "S7-B" in prompt
    # Rule 30 itself is untouched — still present, still the props rule.
    assert "30) NAME EVERY PHYSICAL PROP AND PHYSICAL ACTION" in prompt


# =============================================================================
# _coverage_user_prompt — the DECLARED STAGE DIRECTIONS block
# =============================================================================

def test_user_prompt_includes_declared_stage_directions_block_when_given():
    prompt = _coverage_user_prompt("Ryan cooks.", "Test Video", None, [1], [], action=ACTION_TEXT)
    assert "DECLARED STAGE DIRECTIONS" in prompt
    assert ACTION_TEXT in prompt
    assert "[PROPS |" in prompt or "PROPS" in prompt


def test_user_prompt_omits_declared_stage_directions_block_when_absent():
    prompt = _coverage_user_prompt("Ryan cooks.", "Test Video", None, [1], [])
    assert "DECLARED STAGE DIRECTIONS" not in prompt


def test_user_prompt_omits_declared_stage_directions_block_for_blank_string():
    prompt = _coverage_user_prompt("Ryan cooks.", "Test Video", None, [1], [], action="   ")
    assert "DECLARED STAGE DIRECTIONS" not in prompt


def test_user_prompt_carries_both_location_and_action_blocks_together():
    """The two DECLARED blocks are independent — a scene can have either,
    both, or neither."""
    prompt = _coverage_user_prompt("Ryan cooks.", "Test Video", None, [1], [],
                                   location="the kitchen at home", action=ACTION_TEXT)
    assert "DECLARED LOCATION" in prompt
    assert "DECLARED STAGE DIRECTIONS" in prompt
    assert "the kitchen at home" in prompt
    assert ACTION_TEXT in prompt


# =============================================================================
# generate_coverage_directive — action threads through to the user prompt
# the (mocked) Anthropic client actually receives
# =============================================================================

class _CapturingClient:
    """Stands in for AnthropicClient — records every generate() call's
    kwargs so a test can inspect the EXACT prompt text sent, without a real
    API call."""

    def __init__(self):
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return "[MOMENT 1 | x]\n- MASTER [WS]: a plain shot.\n"


def test_generate_coverage_directive_threads_action_into_the_real_call():
    client = _CapturingClient()
    asyncio.run(generate_coverage_directive(
        "Ryan cooks.", "Test Video", _PROFILE, None, [1], [],
        max_moments=3, angles_min=2, angles_max=4,
        anthropic_client=client, action=ACTION_TEXT))
    assert len(client.calls) == 1
    assert ACTION_TEXT in client.calls[0]["prompt"]
    assert "DECLARED STAGE DIRECTIONS" in client.calls[0]["prompt"]


def test_generate_coverage_directive_action_default_none_is_byte_identical():
    """The default (no action passed, e.g. the legacy cron caller in
    storyboard/bot.py, or any call site before this chunk existed) must
    produce the SAME prompt text as before this chunk existed — no DECLARED
    STAGE DIRECTIONS block at all. Regression guard for bot.py callers."""
    client = _CapturingClient()
    asyncio.run(generate_coverage_directive(
        "Ryan cooks.", "Test Video", _PROFILE, None, [1], [],
        max_moments=3, angles_min=2, angles_max=4,
        anthropic_client=client))
    assert "DECLARED STAGE DIRECTIONS" not in client.calls[0]["prompt"]


def test_generate_coverage_directive_location_default_still_byte_identical_alongside_action_default():
    """Sanity: adding the `action` parameter must not disturb S6-A's own
    location-default byte-identity guarantee."""
    client = _CapturingClient()
    asyncio.run(generate_coverage_directive(
        "Ryan cooks.", "Test Video", _PROFILE, None, [1], [],
        max_moments=3, angles_min=2, angles_max=4,
        anthropic_client=client))
    assert "DECLARED LOCATION" not in client.calls[0]["prompt"]


# =============================================================================
# check_stage_direction_presence — WARN-only, never raises
# =============================================================================

def test_check_stage_direction_presence_none_is_zero():
    assert check_stage_direction_presence(None, []) == 0


def test_check_stage_direction_presence_blank_is_zero():
    assert check_stage_direction_presence("   ", [{"master": {"description": "x"}}]) == 0


def test_check_stage_direction_presence_zero_when_staged_verbatim():
    moments = [{"master": {"description": "A stray cat leaps onto the windowsill in the light."},
                "angles": [], "props": []}]
    assert check_stage_direction_presence(ACTION_TEXT, moments) == 0


def test_check_stage_direction_presence_zero_when_staged_via_props_row():
    """A directed action may land in the [PROPS | ...] extraction instead of
    the prose description — scene-wide, not description-only."""
    moments = [{"master": {"description": "Wide shot of the empty kitchen."},
                "angles": [], "props": ["a stray cat leaping onto the windowsill"]}]
    assert check_stage_direction_presence(ACTION_TEXT, moments) == 0


def test_check_stage_direction_presence_zero_when_staged_in_a_neighboring_moment():
    """Scene-wide, not moment-by-moment — same discipline as
    check_prop_action_presence."""
    moments = [
        {"master": {"description": "Ryan looks toward the window, startled."},
         "angles": [], "props": []},
        {"master": {"description": "Insert on a stray cat leaping onto the windowsill."},
         "angles": [], "props": []},
    ]
    assert check_stage_direction_presence(ACTION_TEXT, moments) == 0


def test_check_stage_direction_presence_warns_when_never_staged():
    moments = [{"master": {"description": "Wide shot of Ryan smiling warmly at Vanessa."},
                "angles": [], "props": []}]
    assert check_stage_direction_presence(ACTION_TEXT, moments) == 1


def test_check_stage_direction_presence_never_raises_on_empty_moments():
    result = check_stage_direction_presence(ACTION_TEXT, [])
    assert isinstance(result, int)
    assert result == 1


def test_check_stage_direction_presence_multiple_directions_split_on_sentences():
    """`action` may name several directions in one field (a creator writes
    more than one stage direction) — each is checked independently."""
    action = "Ryan waves at the camera. A stray cat leaps onto the windowsill."
    moments = [{"master": {"description": "Ryan waves warmly toward the lens."},
                "angles": [], "props": []}]
    # First direction ("Ryan waves...") is staged; second (the cat) is not.
    assert check_stage_direction_presence(action, moments) == 1


def test_check_stage_direction_presence_multiple_directions_both_staged_is_zero():
    action = "Ryan waves at the camera. A stray cat leaps onto the windowsill."
    moments = [{"master": {"description": "Ryan waves warmly toward the lens as a stray cat "
                                          "leaps onto the windowsill behind him."},
                "angles": [], "props": []}]
    assert check_stage_direction_presence(action, moments) == 0


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
