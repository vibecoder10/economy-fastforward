"""Tests for P2 (chat channel-identity rebuild, checklist P2 — "Chat wiring").

P1 (commit 10f4af85) built the pool: channel_identity_context.build_identity_pool
+ render_identity_brief, a compact canonical prompt block that OPENS with the
hard precedence law (our locked identity leads; a reference contributes topic
only, never format/runtime/titling). This chunk makes every chat surface that
assembles a producer/co-pilot system prompt (routes/chat.py's chat_turn intake
turn, its onboarding hand-off _seed_producer, and the in-video co-pilot
_handle_copilot) drink from that pool FIRST, and rewrites the three
reference-anchoring instructions that used to compete with it (producer_
prompt.py's LENGTH card + MODELING A REFERENCE bullet, and routes/chat.py's
_reference_brief) to point back at it instead.

Ordering/wiring is pinned with `inspect.getsource` string-index checks — the
SAME convention this file's neighbors already use for exactly this kind of
"which briefs does this assembly call, in what order" lock (see
test_c15c_director_memory.py §6, test_c15d_voice_and_data_reach.py, test_
c21b_style_axis_split.py, test_c22_style_draft.py). The identity pool brief
is injected INLINE at each assembly site (not behind an extra indirection
function) specifically so those existing source-lock tests keep seeing the
same literal call text they already pin — an earlier draft of this chunk
extracted the assemblies into helper functions and broke five of them
(inspect.getsource(chat_turn) no longer contained the brief calls once they
moved into a helper); reverted in favor of this project's established
in-place convention.

Covers:
  1. producer_prompt.py: the old "anchor to the reference's runtime" /
     "adapts THIS video's proven formula" wording is gone from the LENGTH and
     MODELING A REFERENCE bullets; the new subordinate wording is present.
  2. routes/chat.py's _reference_brief: same pin, at the actual runtime output
     (not just the source string) — the old "Anchor the recommended length"
     phrase is gone, the new "OUR CHANNEL IDENTITY LEADS" / "context only"
     wording is present, and the factual reference metadata survives.
  3. Source-lock: chat_turn, _seed_producer (the onboarding hand-off into the
     SAME producer), and _handle_copilot all call _identity_pool_brief, and
     it comes BEFORE every other brief in each assembly (string-index order,
     matching the neighboring tests' own pattern).
  4. _identity_pool_brief itself, at runtime: real pool -> the exact law line
     leads its output; empty pool -> render_identity_brief's own minimal
     fallback, not a crash; pool-build exception -> "" (fail-soft), never
     breaks prompt assembly.

No live DB, no network. DB boundaries are stubbed at the module level
(database.fetch_one/fetch_all/execute raise if a test's own monkeypatches
don't cover a path) — same convention as test_producer_kie_fallback.py and
tests/test_channel_identity_context.py.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_p2_chat_identity_wiring.py -q
"""
from __future__ import annotations

import inspect
import os
import sys
import types
from unittest.mock import AsyncMock

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


async def _boom(*a, **k):
    raise AssertionError("pure tests must not touch runtime services")


_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom)
_stub("vault", get_secret=_boom)

import routes.chat as chat  # noqa: E402
import channel_identity_context as cic  # noqa: E402
import producer_prompt  # noqa: E402


# =============================================================================
# 1. producer_prompt.py — the subordinated instructions, pinned at the source.
# =============================================================================

def test_length_card_no_longer_anchors_blindly_to_reference_runtime():
    prompt = producer_prompt.PRODUCER_SYSTEM_PROMPT
    idx = prompt.index('- LENGTH (act like a director')
    next_idx = prompt.index('- LOOK ENGINE')
    section = prompt[idx:next_idx]
    assert 'anchor to it: "the video you\'re modeling runs' not in section
    assert "OUR CHANNEL IDENTITY LEADS" in section
    assert "never the anchor" in section


def test_modeling_reference_bullet_is_subordinate_to_identity():
    prompt = producer_prompt.PRODUCER_SYSTEM_PROMPT
    idx = prompt.index("- MODELING A REFERENCE")
    next_idx = prompt.index("- Only show a card for something you still need")
    section = prompt[idx:next_idx]
    assert "your spin on the reference's proven title formula, adapted to this creator" not in section
    assert "OUR CHANNEL IDENTITY LEADS" in section
    assert "OUR locked format" in section
    assert "never the reference's runtime, pacing, or title structure" in section


def test_producer_prompt_offline_selftest_still_passes():
    """producer_prompt.py's own __main__ self-test asserts generic strings
    that must survive this rewrite untouched."""
    assert "creative producer" in producer_prompt.build_system_prompt().lower()
    assert "Niche: cooking" in producer_prompt.build_system_prompt("Niche: cooking")


# =============================================================================
# 2. routes/chat.py — _reference_brief, pinned at the REAL runtime output.
# =============================================================================

async def test_reference_brief_subordinate_wording(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "fake-key")
    monkeypatch.setattr("routes.model_video._parse_youtube_id", lambda url: "abc123")

    async def fake_fetch_single_video(yid, api_key):
        assert yid == "abc123"
        return {
            "title": "How I Survived a Year Alone",
            "channel": "SomeChannel",
            "views": 500_000,
            "duration_seconds": 480,
            "published_at": "2024-01-01",
            "description": "A survival story.",
        }

    monkeypatch.setattr("youtube_data_api.fetch_single_video", fake_fetch_single_video)

    state: dict = {}
    brief = await chat._reference_brief(state, "https://youtube.com/watch?v=abc123")

    assert "Anchor the recommended length to this video's runtime" not in brief
    assert "adapts THIS video's proven formula" not in brief
    assert "OUR CHANNEL IDENTITY LEADS" in brief
    assert "context only, never the anchor" in brief
    assert "OUR channel's own title convention" in brief
    # Factual reference metadata must survive — the anchoring INSTRUCTION is
    # what got rewritten, not the data.
    assert "How I Survived a Year Alone" in brief
    assert "SomeChannel" in brief
    assert "500,000" in brief


async def test_reference_brief_empty_when_no_url():
    assert await chat._reference_brief({}, None) == ""


# =============================================================================
# 3. Source-lock: every chat system-prompt assembly calls _identity_pool_brief
#    FIRST — same inspect.getsource convention test_c15c/c15d/c21b/c22 use.
# =============================================================================

def _assert_identity_brief_first(src: str, *other_markers: str) -> None:
    assert "await _identity_pool_brief(tenant_id)" in src
    idx_identity = src.index("await _identity_pool_brief(tenant_id)")
    for marker in other_markers:
        assert marker in src, f"missing {marker!r} in source"
        assert idx_identity < src.index(marker), f"{marker!r} appears before the identity brief"


def test_chat_turn_calls_identity_brief_before_creator_brief():
    src = inspect.getsource(chat.chat_turn)
    _assert_identity_brief_first(src, "_creator_brief(state)", "_reference_brief(state,")


def test_seed_producer_calls_identity_brief_before_creator_brief():
    """The onboarding hand-off into the SAME producer chat_turn drives must
    open with the same precedence law from turn one, not just on later
    chat_turn turns."""
    src = inspect.getsource(chat._seed_producer)
    _assert_identity_brief_first(src, "_creator_brief(state)", "_reference_brief(state,")


def test_handle_copilot_calls_identity_brief_before_summary_line():
    src = inspect.getsource(chat._handle_copilot)
    _assert_identity_brief_first(src, "_summary_line(summary)", "_preferences_brief(tenant_id, video_id)")


def test_c15c_preference_hydration_untouched_by_this_wiring():
    """Regression pin (mirrors test_c15d's own pin of the same invariant):
    C15c's STANDING PREFERENCES hydration must survive this rewrite in both
    chat surfaces — proves the identity-brief insertion didn't dislodge it."""
    assert "_preferences_brief(tenant_id)" in inspect.getsource(chat.chat_turn)
    assert "_preferences_brief(tenant_id, video_id)" in inspect.getsource(chat._handle_copilot)


# =============================================================================
# 4. _identity_pool_brief itself, at runtime.
# =============================================================================

_FIXTURE_POOL = {
    "dna": {"voice_tone": "deadpan analyst", "cadence": "punchy, fast cuts"},
    "cast": [],
    "format": {"visual_format": {}, "locked": False},
    "own_median_minutes": 6.2,
    "title_patterns": [],
    "script_profiles": [],
    "script_prompt_summary": None,
}


async def test_identity_pool_brief_leads_with_the_law_line(monkeypatch):
    monkeypatch.setattr(cic, "build_identity_pool", AsyncMock(return_value=_FIXTURE_POOL))
    brief = await chat._identity_pool_brief("tenant-p2")
    assert brief.strip().startswith("OUR CHANNEL IDENTITY LEADS (hard law):")
    assert "deadpan analyst" in brief
    assert "6 min" in brief  # own_median_minutes rendered in the LENGTH line


async def test_identity_pool_brief_empty_pool_still_valid(monkeypatch):
    """A fresh tenant with nothing learned yet still gets a valid, honest
    block — render_identity_brief's own minimal fallback, no special case
    needed at the chat wiring layer."""
    monkeypatch.setattr(cic, "build_identity_pool", AsyncMock(return_value={}))
    brief = await chat._identity_pool_brief("empty-tenant")
    assert "OUR CHANNEL IDENTITY LEADS (hard law):" in brief
    assert "No channel identity learned yet" in brief


async def test_identity_pool_brief_fail_soft(monkeypatch):
    async def boom(tenant_id):
        raise RuntimeError("db down")
    monkeypatch.setattr(cic, "build_identity_pool", boom)
    assert await chat._identity_pool_brief("t1") == ""
