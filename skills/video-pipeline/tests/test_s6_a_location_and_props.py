"""S6-A (STORY-LAWS.md S6 — "the script is the origin of truth", BOARD-LAWS.md
L30) — the coverage.py-side half: threading the script's canonical
scripts.location into the PLANNING PROMPT (generate_coverage_directive /
_coverage_user_prompt), rule 30's per-moment [PROPS | ...] extraction
(_coverage_system_prompt), its parser (parse_coverage), and the WARN-only
drift alarm (check_prop_action_presence).

Companion file storyengine/backend/tests/functional/test_s6_a_location_and_
props.py covers the coverage_to_app.py sheet-composer side (_plan_sheet_
prompts, _match_scene_env, _assert_scene_location_declared — needs the
backend's own venv) and duplicates a couple of the parse_coverage/check_
prop_action_presence tests below so the backend suite is self-contained too.

Run (TARGETED — the full skills suite has a pre-existing collection error in
test_ctr_12h_tracking.py, unrelated to this chunk, do not try to fix it here):
    cd skills/video-pipeline && \
        <backend-venv>/bin/python -m pytest \
        tests/test_board_laws.py tests/test_s6_a_location_and_props.py -q
"""
import asyncio
import os
import sys

_PIPELINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PIPELINE_ROOT)
sys.path.insert(0, os.path.join(_PIPELINE_ROOT, "storyboard"))
sys.path.append(os.path.join(_PIPELINE_ROOT, "image_prompts"))

from storyboard.coverage import (  # noqa: E402
    parse_coverage, _coverage_system_prompt, _coverage_user_prompt,
    generate_coverage_directive, check_prop_action_presence,
)
from shared.channel_profile import load_profile  # noqa: E402

_PROFILE = load_profile({})


# =============================================================================
# _coverage_system_prompt — rule 30's PROPS instruction is present
# =============================================================================

def test_system_prompt_carries_rule_30_props_marker():
    prompt = _coverage_system_prompt(_PROFILE, max_moments=6, angles_min=2, angles_max=4)
    assert "30) NAME EVERY PHYSICAL PROP AND PHYSICAL ACTION" in prompt
    assert "[PROPS |" in prompt
    assert "S6-A" in prompt


# =============================================================================
# _coverage_user_prompt — the DECLARED LOCATION block
# =============================================================================

def test_user_prompt_includes_declared_location_block_when_given():
    prompt = _coverage_user_prompt("Ryan cooks.", "Test Video", None, [1], [],
                                   location="the kitchen at home")
    assert "DECLARED LOCATION" in prompt
    assert "the kitchen at home" in prompt
    assert "[SET | ...]" in prompt or "[LOCSET | ...]" in prompt


def test_user_prompt_omits_declared_location_block_when_absent():
    prompt = _coverage_user_prompt("Ryan cooks.", "Test Video", None, [1], [])
    assert "DECLARED LOCATION" not in prompt


def test_user_prompt_omits_declared_location_block_for_blank_string():
    prompt = _coverage_user_prompt("Ryan cooks.", "Test Video", None, [1], [], location="   ")
    assert "DECLARED LOCATION" not in prompt


# =============================================================================
# generate_coverage_directive — location threads through to the user prompt
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


def test_generate_coverage_directive_threads_location_into_the_real_call():
    client = _CapturingClient()
    asyncio.run(generate_coverage_directive(
        "Ryan cooks.", "Test Video", _PROFILE, None, [1], [],
        max_moments=3, angles_min=2, angles_max=4,
        anthropic_client=client, location="the kitchen at home"))
    assert len(client.calls) == 1
    assert "the kitchen at home" in client.calls[0]["prompt"]
    assert "DECLARED LOCATION" in client.calls[0]["prompt"]


def test_generate_coverage_directive_location_default_none_is_byte_identical():
    """The default (no location passed, e.g. the legacy cron caller in
    storyboard/bot.py) must produce the SAME prompt text as before this
    chunk existed — no DECLARED LOCATION block at all."""
    client = _CapturingClient()
    asyncio.run(generate_coverage_directive(
        "Ryan cooks.", "Test Video", _PROFILE, None, [1], [],
        max_moments=3, angles_min=2, angles_max=4,
        anthropic_client=client))
    assert "DECLARED LOCATION" not in client.calls[0]["prompt"]


# =============================================================================
# parse_coverage — [PROPS | ...] per-moment parsing
# =============================================================================

PROPS_DIRECTIVE = """\
[SET | the kitchen at home: a wooden island]
[MOMENT 1 | Ryan hands over the tickets]
LINE: Ryan | "Here, two tickets — Dos boletos."
[PROPS | two tickets, Dos boletos]
- MASTER [MS]: Ryan holds up two tickets marked Dos boletos toward Vanessa.

[MOMENT 2 | a silent beat]
- MASTER [WS]: An empty kitchen, morning light through the window.
"""


def test_parse_coverage_populates_props_when_present():
    moments = parse_coverage(PROPS_DIRECTIVE)
    assert moments[0]["props"] == ["two tickets", "Dos boletos"]


def test_parse_coverage_props_empty_list_when_row_absent():
    moments = parse_coverage(PROPS_DIRECTIVE)
    assert moments[1]["props"] == []


def test_parse_coverage_legacy_plan_props_is_empty_list_not_none():
    legacy = "[MOMENT 1 | x]\n- MASTER [WS]: a plain establishing shot.\n"
    moments = parse_coverage(legacy)
    assert moments[0]["props"] == []


# =============================================================================
# check_prop_action_presence — WARN-only, never raises
# =============================================================================

def test_check_prop_action_presence_zero_when_drawn():
    directive = """\
[MOMENT 1 | Ryan hands over the tickets]
[PROPS | two tickets]
- MASTER [MS]: Ryan holds up two tickets toward Vanessa.
"""
    moments = parse_coverage(directive)
    assert check_prop_action_presence(moments) == 0


def test_check_prop_action_presence_warns_when_never_drawn():
    directive = """\
[MOMENT 1 | Ryan hands over the tickets]
[PROPS | two tickets, a water bottle]
- MASTER [MS]: Ryan smiles warmly at Vanessa.
"""
    moments = parse_coverage(directive)
    assert check_prop_action_presence(moments) == 2


def test_check_prop_action_presence_zero_for_no_moments():
    assert check_prop_action_presence([]) == 0
