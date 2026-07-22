"""Tests for P3 (chat channel-identity rebuild, checklist P3 — "Length
backstop + steering").

P1 (10f4af85) built channel_identity_context.build_identity_pool, including
own_median_minutes (the tenant's OWN catalog runtime, never a competitor's).
P2 (cb53803d) wired that pool into every chat system prompt FIRST. This
chunk fixes the two remaining mechanical causes of the "chat models the
reference verbatim and ignores steering" incident:

  1. routes/chat.py's `_stamp_length_default` used to force-bump ANY proposed
     length >= 2 min UP to `_competitor_median_seconds` (someone else's
     catalog) — a deterministic override the creator's own steering could
     never reach. Now: it anchors on the tenant's OWN median first
     (channel_identity_context.own_median_minutes, the shared P1 helper,
     imported rather than duplicated), falls back to the competitor median
     only when there's no own-catalog history, and — the actual bug fix —
     never touches a length the producer marks spec.length_user_set=true,
     in either direction (shorter or longer than the channel median).
  2. `state["pending_reference_url"]` / `state["video_dna"]` were never
     clearable — `_reference_brief` re-injected the reference block forever.
     A new `clear_reference` profile_op (producer_prompt.py's ops list +
     routes/chat.py's `_apply_profile_ops` dispatcher) empties both state
     keys AND persists the steering as a durable director_preferences row
     (reusing `_save_preference`/`_PREF_SCOPE_CHANNEL` — the SAME channel-wide
     write path the "remember" op already uses; no new table/infra).

Same stub pattern as test_p2_chat_identity_wiring.py / test_c15c_director_
memory.py: no live DB, no network; database.fetch_one/fetch_all/execute raise
if a test's own monkeypatch doesn't cover a path.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_p3_length_backstop_and_reference_steering.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys
import types

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
if os.path.abspath(_BACKEND) not in sys.path:
    sys.path.insert(0, os.path.abspath(_BACKEND))


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

TENANT = "tenant-p3"


def _plan_data(cards=None, video_length_minutes=None, length_user_set=None, recommended_minutes=None):
    """Build a producer-turn `data` dict shaped like what `_stamp_length_default`
    receives: a cards list (the length slider card) + a plan.spec."""
    card = {"id": "length", "type": "slider"}
    if recommended_minutes is not None:
        card["recommended_minutes"] = recommended_minutes
    spec = {}
    if video_length_minutes is not None:
        spec["video_length_minutes"] = video_length_minutes
    if length_user_set is not None:
        spec["length_user_set"] = length_user_set
    return {
        "assistant_text": "ok",
        "phase": "plan",
        "cards": [card] if cards is None else cards,
        "plan": {"spec": spec},
    }


# =============================================================================
# 1a. Own median wins over competitor median.
# =============================================================================

def test_own_median_wins_over_competitor_median(monkeypatch):
    """Tenant has BOTH an own-catalog median (7 min) and a competitor median
    (20 min). The backstop must anchor on the tenant's OWN channel, not the
    competitor's — that's the entire point of this chunk."""
    async def fake_own(tenant_id):
        assert tenant_id == TENANT
        return 7.0

    async def fake_competitor(tenant_id):
        raise AssertionError("must not fall back to competitor median when own data exists")

    monkeypatch.setattr(cic, "own_median_minutes", fake_own)
    monkeypatch.setattr(chat, "_competitor_median_seconds", fake_competitor)

    data = _plan_data(video_length_minutes=3)  # NORMAL-form, below the channel median
    asyncio.run(chat._stamp_length_default(data, TENANT))
    assert data["cards"][0]["recommended_seconds"] == 7 * 60


# =============================================================================
# 1b. Competitor fallback ONLY when there's no own-catalog history.
# =============================================================================

def test_competitor_median_used_only_when_no_own_history(monkeypatch):
    async def fake_own(tenant_id):
        return None  # no own-catalog data yet

    async def fake_competitor(tenant_id):
        return 600  # 10 min, in seconds

    monkeypatch.setattr(cic, "own_median_minutes", fake_own)
    monkeypatch.setattr(chat, "_competitor_median_seconds", fake_competitor)

    data = _plan_data(video_length_minutes=3)
    asyncio.run(chat._stamp_length_default(data, TENANT))
    assert data["cards"][0]["recommended_seconds"] == 10 * 60


# =============================================================================
# 1c. User-specified length is NEVER overridden — both directions.
# =============================================================================

def test_user_set_length_shorter_than_median_survives(monkeypatch):
    """Creator explicitly asked for 1 min; the channel median is 8 min. The
    backstop must leave the 1-minute pick alone. P5: length_user_set is only
    trusted when the creator's own transcript actually says a length, so this
    test supplies one."""
    async def fake_own(tenant_id):
        return 8.0

    monkeypatch.setattr(cic, "own_median_minutes", fake_own)
    monkeypatch.setattr(chat, "_competitor_median_seconds", _boom)

    data = _plan_data(video_length_minutes=1, length_user_set=True)
    transcript = [{"role": "user", "content": "keep this one to 1 minute please"}]
    asyncio.run(chat._stamp_length_default(data, TENANT, transcript))
    assert data["cards"][0]["recommended_seconds"] == 60


def test_user_set_length_longer_than_median_survives(monkeypatch):
    """Creator explicitly asked for 15 min; the channel median is 5 min. The
    old code only bumped UP, but the gate must block ANY touch when the
    creator set it themselves — confirms this isn't just a one-directional
    fix. P5: transcript carries the actual length phrase the guard checks for."""
    async def fake_own(tenant_id):
        return 5.0

    monkeypatch.setattr(cic, "own_median_minutes", fake_own)
    monkeypatch.setattr(chat, "_competitor_median_seconds", _boom)

    data = _plan_data(video_length_minutes=15, length_user_set=True)
    transcript = [{"role": "user", "content": "I want this to be a full 15 minute deep dive"}]
    asyncio.run(chat._stamp_length_default(data, TENANT, transcript))
    assert data["cards"][0]["recommended_seconds"] == 15 * 60


def test_user_set_length_without_plausible_expression_is_distrusted(monkeypatch):
    """P5 fix: spec.length_user_set is the producer LLM's own self-report,
    not ground truth. When nothing in the creator's own recent turns actually
    reads like a length expression, the deterministic guard distrusts the
    self-report and the channel-runtime backstop applies exactly as if
    length_user_set had never been set."""
    async def fake_own(tenant_id):
        return 8.0

    monkeypatch.setattr(cic, "own_median_minutes", fake_own)
    monkeypatch.setattr(chat, "_competitor_median_seconds", _boom)

    data = _plan_data(video_length_minutes=3, length_user_set=True)
    transcript = [{"role": "user", "content": "make it about the history of the Roman empire"}]
    asyncio.run(chat._stamp_length_default(data, TENANT, transcript))
    assert data["cards"][0]["recommended_seconds"] == 8 * 60


def test_user_set_length_with_no_transcript_is_distrusted(monkeypatch):
    """Same guard, no transcript supplied at all (None) — must not crash and
    must fall back to the backstop rather than trusting the self-report."""
    async def fake_own(tenant_id):
        return 8.0

    monkeypatch.setattr(cic, "own_median_minutes", fake_own)
    monkeypatch.setattr(chat, "_competitor_median_seconds", _boom)

    data = _plan_data(video_length_minutes=3, length_user_set=True)
    asyncio.run(chat._stamp_length_default(data, TENANT))
    assert data["cards"][0]["recommended_seconds"] == 8 * 60


def test_user_length_expression_present_matches_common_phrasings():
    """Unit coverage for the regex guard itself, both directions."""
    positive = [
        "keep it under 90 seconds",
        "make it a 3-minute video",
        "I want a 15 minute deep dive",
        "let's do 45s for the short",
        "give me a 1 hour documentary",
        "2hrs would be great",
    ]
    for text in positive:
        transcript = [{"role": "user", "content": text}]
        assert chat._user_length_expression_present(transcript), text

    negative = [
        "make it about the Roman empire",
        "focus on the moon landing",
        "I like this style, keep going",
    ]
    for text in negative:
        transcript = [{"role": "user", "content": text}]
        assert not chat._user_length_expression_present(transcript), text

    # Only user turns count — an assistant turn mentioning a length must not count.
    assistant_only = [{"role": "assistant", "content": "how about a 5 minute video?"}]
    assert not chat._user_length_expression_present(assistant_only)

    # Non-list / empty transcript never crashes.
    assert not chat._user_length_expression_present(None)
    assert not chat._user_length_expression_present([])


def test_non_user_set_normal_form_length_still_bumped_to_median(monkeypatch):
    """Regression check: when length_user_set is NOT true, the existing bump
    behavior (a NORMAL-form pick below the channel median gets bumped up)
    still fires — P3 only adds the gate, it doesn't remove the backstop."""
    async def fake_own(tenant_id):
        return 8.0

    monkeypatch.setattr(cic, "own_median_minutes", fake_own)
    monkeypatch.setattr(chat, "_competitor_median_seconds", _boom)

    data = _plan_data(video_length_minutes=3, length_user_set=False)
    asyncio.run(chat._stamp_length_default(data, TENANT))
    assert data["cards"][0]["recommended_seconds"] == 8 * 60


# =============================================================================
# 1d. A missing length still gets filled from the channel median.
# =============================================================================

def test_missing_length_still_gets_filled(monkeypatch):
    async def fake_own(tenant_id):
        return 6.0

    monkeypatch.setattr(cic, "own_median_minutes", fake_own)
    monkeypatch.setattr(chat, "_competitor_median_seconds", _boom)

    data = _plan_data(video_length_minutes=None)
    asyncio.run(chat._stamp_length_default(data, TENANT))
    assert data["cards"][0]["recommended_seconds"] == 6 * 60


def test_short_form_intentional_pick_left_alone(monkeypatch):
    """Regression check: a real short (< 2 min), not user-marked, is still
    left alone — 'make a 30s short' must keep working."""
    async def fake_own(tenant_id):
        return 8.0

    monkeypatch.setattr(cic, "own_median_minutes", fake_own)
    monkeypatch.setattr(chat, "_competitor_median_seconds", _boom)

    data = _plan_data(video_length_minutes=0.5, length_user_set=False)
    asyncio.run(chat._stamp_length_default(data, TENANT))
    assert data["cards"][0]["recommended_seconds"] == 30


# =============================================================================
# 1e. spec.length_user_set is taught in the producer prompt.
# =============================================================================

def test_producer_prompt_teaches_length_user_set():
    assert "length_user_set" in producer_prompt.PRODUCER_SYSTEM_PROMPT
    idx = producer_prompt.PRODUCER_SYSTEM_PROMPT.index("- LENGTH (act like a director")
    next_idx = producer_prompt.PRODUCER_SYSTEM_PROMPT.index("- LOOK ENGINE")
    section = producer_prompt.PRODUCER_SYSTEM_PROMPT[idx:next_idx]
    assert "length_user_set" in section
    assert '"length_user_set"' in producer_prompt.PRODUCER_SYSTEM_PROMPT  # in the JSON schema block too


# =============================================================================
# 2a. clear_reference op empties BOTH state keys.
# =============================================================================

def test_clear_reference_op_empties_both_state_keys(monkeypatch):
    saved = {}

    async def fake_save(tenant_id, text, scope="channel"):
        saved["tenant_id"] = tenant_id
        saved["text"] = text
        saved["scope"] = scope

    monkeypatch.setattr(chat, "_save_preference", fake_save)
    state = {
        "pending_reference_url": "https://youtube.com/watch?v=abc123",
        "video_dna": {"summary": "a survival story", "dna": {"hook": "cold open"}},
        "_ref_brief_for": "https://youtube.com/watch?v=abc123",
        "_ref_brief": "cached reference brief text",
    }
    results = asyncio.run(chat._apply_profile_ops(
        TENANT, [{"op": "clear_reference"}], state, None
    ))
    assert "pending_reference_url" not in state
    assert "video_dna" not in state
    assert "_ref_brief_for" not in state
    assert "_ref_brief" not in state
    assert any("Dropped that reference" in r for r in results)
    # Durable steering lesson persisted via the SAME channel-wide store "remember" uses.
    assert saved["tenant_id"] == TENANT
    assert saved["scope"] == chat._PREF_SCOPE_CHANNEL
    assert "abc123" in saved["text"] or "reference" in saved["text"].lower()


def test_clear_reference_with_nothing_pending_is_a_safe_noop(monkeypatch):
    async def fake_save(*a, **k):
        raise AssertionError("must not write a preference when there was no reference to clear")

    monkeypatch.setattr(chat, "_save_preference", fake_save)
    state: dict = {}
    results = asyncio.run(chat._apply_profile_ops(
        TENANT, [{"op": "clear_reference"}], state, None
    ))
    assert "pending_reference_url" not in state
    assert "video_dna" not in state
    assert results  # still says something, just no lesson to persist


# =============================================================================
# 2b. After clear_reference, the NEXT _reference_brief call renders nothing.
# =============================================================================

async def test_reference_brief_renders_nothing_after_clear(monkeypatch):
    async def fake_save(*a, **k):
        return None

    monkeypatch.setattr(chat, "_save_preference", fake_save)
    state = {
        "pending_reference_url": "https://youtube.com/watch?v=abc123",
        "video_dna": {"summary": "x"},
        "_ref_brief_for": "https://youtube.com/watch?v=abc123",
        "_ref_brief": "STALE CACHED REFERENCE BLOCK",
    }
    await chat._apply_profile_ops(TENANT, [{"op": "clear_reference"}], state, None)
    brief = await chat._reference_brief(state, state.get("pending_reference_url"))
    assert brief == ""
    assert chat._dna_brief(state) == ""


# =============================================================================
# 2c. clear_reference is listed in the producer prompt text.
# =============================================================================

def test_producer_prompt_teaches_clear_reference_op():
    assert '"op":"clear_reference"' in producer_prompt.PRODUCER_SYSTEM_PROMPT
    assert "CLEARING A REFERENCE" in producer_prompt.PRODUCER_SYSTEM_PROMPT


def test_clear_reference_never_auto_fires_outside_the_op():
    """Regression guard for the 'do NOT auto-clear on every disagreement'
    requirement: _apply_profile_ops only clears state when the op is
    actually present in the ops list — an unrelated op must leave the
    reference untouched."""
    state = {"pending_reference_url": "https://youtube.com/watch?v=abc123"}
    asyncio.run(chat._apply_profile_ops(
        TENANT, [{"op": "set_niche", "value": "cooking"}], state, None
    ))
    assert state.get("pending_reference_url") == "https://youtube.com/watch?v=abc123"
