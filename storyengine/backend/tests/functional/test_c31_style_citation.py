"""Tests for C31 (checklist §3.1 [U] — "producer cites channel-data in LOOK
recommendations", the P3.1b closer of the preset-performance loop).

C30 already wired `_style_performance_brief` into the producer's `_loop_brief`
(routes/chat.py) and the copilot's `channel_data` tool — the numbers were
REACHABLE but nothing told the producer to actually quote them when
recommending a LOOK. This chunk is prompt-only: it adds a citation
instruction to producer_prompt.PRODUCER_SYSTEM_PROMPT's LOOK card guidance.

Follows the C15d prompt-pin pattern (test_c15d_voice_and_data_reach.py): pin
the instruction text exists, AND non-vacuously prove it actually composes
into the SAME system prompt string as a real `_style_performance_brief`
output — the two halves (C30's data, C31's instruction) must coexist in one
composed prompt, not just live in two files that happen to both exist.

Also pins the "never fabricate" contract: the instruction must tell the
model to stay silent about channel performance when the brief carries no
PERFORMANCE BY CREATIVE CHOICE block, rather than inventing a stat.

No live DB / no network. Run:
  cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c31_style_citation.py -q
"""
import asyncio
import os
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import channel_briefs  # noqa: E402
import producer_prompt  # noqa: E402

TENANT = "tenant-31"

# Same canned shape as test_c30_style_performance.py's STYLE_PRESET_ROWS: one
# group with real synced analytics (clears MIN_SAMPLE), one "no data yet".
STYLE_PRESET_AGG = [
    {"dimension": "by_style_preset", "choice": "holographic_hud", "video_count": 3,
     "synced_count": 2, "avg_ctr": 8.4, "avg_retention": 55.0, "total_views": 15000,
     "total_spend": 42.10},
    {"dimension": "by_style_preset", "choice": "dossier", "video_count": 1,
     "synced_count": 0, "avg_ctr": None, "avg_retention": None, "total_views": 0,
     "total_spend": 5.00},
]


# ---------------------------------------------------------------------------
# 1. The instruction itself: present, and shaped the way the checklist asks.
# ---------------------------------------------------------------------------

def test_look_card_guidance_includes_citation_instruction():
    prompt = producer_prompt.PRODUCER_SYSTEM_PROMPT
    assert "PERFORMANCE BY CREATIVE CHOICE" in prompt
    assert "CITING CHANNEL DATA WHEN RECOMMENDING A LOOK" in prompt
    # the checklist's own example phrasing anchors the tone
    assert "2.1x the channel CTR" in prompt


def test_citation_instruction_forbids_fabrication_when_data_absent():
    prompt = producer_prompt.PRODUCER_SYSTEM_PROMPT
    idx = prompt.index("CITING CHANNEL DATA WHEN RECOMMENDING A LOOK")
    section = prompt[idx: idx + 1200]
    assert "ABSENT" in section
    assert "never fabricate" in section.lower() or "never invent" in section.lower()
    assert "say nothing about channel performance" in section.lower() or "recommend on creative merit alone" in section.lower()


def test_citation_instruction_lives_in_look_card_guidance_not_a_new_section():
    """It's an addition to the existing LOOK bullet in CARD GUIDANCE, not a
    freestanding section — keeps the citation logic attached to the moment
    the producer is actually picking a look, per the chunk's [B] scope."""
    prompt = producer_prompt.PRODUCER_SYSTEM_PROMPT
    card_guidance_idx = prompt.index("CARD GUIDANCE:")
    look_bullet_idx = prompt.index('- LOOK: when the visual style')
    citation_idx = prompt.index("CITING CHANNEL DATA WHEN RECOMMENDING A LOOK")
    length_bullet_idx = prompt.index("- LENGTH (act like a director")
    assert card_guidance_idx < look_bullet_idx < citation_idx < length_bullet_idx


# ---------------------------------------------------------------------------
# 2. Non-vacuous pin: the instruction and a REAL brief coexist in one
#    composed system prompt (C15d pattern — prove runtime output, not source).
# ---------------------------------------------------------------------------

def test_composed_prompt_pairs_real_style_brief_with_citation_instruction(monkeypatch):
    async def fake_get_style_performance(tenant_id):
        assert tenant_id == TENANT
        return {
            "by_style_preset": STYLE_PRESET_AGG,
            "by_render_style": [],
            "by_script_profile": [],
            "by_clip_model": [],
        }

    import analytics_by_style
    monkeypatch.setattr(analytics_by_style, "get_style_performance", fake_get_style_performance)

    brief = asyncio.run(channel_briefs._style_performance_brief(TENANT))
    assert "PERFORMANCE BY CREATIVE CHOICE" in brief
    assert "holographic_hud" in brief
    assert "dossier" not in brief  # below MIN_SAMPLE, correctly excluded from the citable brief

    composed = producer_prompt.build_system_prompt(brief)
    # Both halves present in the ONE string actually sent to the model.
    assert "CITING CHANNEL DATA WHEN RECOMMENDING A LOOK" in composed
    assert "PERFORMANCE BY CREATIVE CHOICE" in composed
    assert "holographic_hud" in composed
    assert "8.4% CTR" in composed


def test_composed_prompt_without_style_data_carries_no_fabrication_license(monkeypatch):
    """When the brief has nothing to cite (e.g. a brand-new channel), the
    composed prompt must NOT contain a PERFORMANCE BY CREATIVE CHOICE block —
    proving the "stay silent" instruction has real data (or lack of it) to
    apply to, not just a section that always renders something."""
    async def empty(tenant_id):
        return ""

    monkeypatch.setattr(channel_briefs, "_next_to_make_brief", empty)
    monkeypatch.setattr(channel_briefs, "_own_performance_brief", empty)
    monkeypatch.setattr(channel_briefs, "_learnings_brief", empty)

    async def fake_get_style_performance(tenant_id):
        return {"by_style_preset": [], "by_render_style": [], "by_script_profile": [], "by_clip_model": []}

    import analytics_by_style
    monkeypatch.setattr(analytics_by_style, "get_style_performance", fake_get_style_performance)

    brief = asyncio.run(channel_briefs._style_performance_brief(TENANT))
    assert brief == ""

    composed = producer_prompt.build_system_prompt(brief)
    # The instruction text ITSELF names the block ("PERFORMANCE BY CREATIVE
    # CHOICE") so that phrase is always present as an instruction — the real
    # signal is that the actual BRIEF CONTENT (channel_briefs.py's literal
    # header sentence, with real cited numbers) never got appended, because
    # there was nothing to cite this turn.
    assert "real synced analytics grouped by what actually made the video" not in composed
    assert "--- THIS CREATOR'S CHANNEL ---" not in composed
    # the instruction teaching it to cite (and to stay silent when absent) is
    # still there — it just has nothing to cite this turn.
    assert "CITING CHANNEL DATA WHEN RECOMMENDING A LOOK" in composed
