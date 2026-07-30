"""Tests for checklist C44 (P4.1e corrections loop wiring).

C15c gave the chat producer/co-pilot a "STANDING PREFERENCES" block hydrated
into their system prompts every turn. C42's digest card wired the "correct"
action to save those same channel-scope `director_preferences` rows. But
until now, nothing but CHAT ever read them back: a correction said once
never touched script/research/thumbnail/title/video_motion GENERATION.

This chunk wires the read into the ONE seam every generation stage shares
(per C43's audit table): `identity.build_identity_context` — consumed by
BOTH `pipeline_executor._load_prompt_overrides` (-> `resolve_prompt` ->
every text-stage system prompt) and `_export_visual_style` (the image
pipeline's env-var seam). Three layers, matching the module split:

  1. identity.py — `IdentityContext.standing_preferences` (new field, default
     "") + `_standing_preferences_block(tenant_id)`, a channel-scope-ONLY,
     capped, length-limited, fail-soft read of `director_preferences`. A
     DELIBERATELY separate/minimal query from chat.py's `_list_preferences`
     (not an import of it) — chat.py sits on a heavy import chain (FastAPI
     router, actions.py, the whole skills/video-pipeline package) this
     low-level, widely-imported module must not pull in.
  2. pipeline_executor.resolve_prompt — appends `identity.standing_preferences`
     after whichever prompt source won (per-video override / tenant override
     / neutral template), never templated in, so it applies unconditionally
     and can never silently vanish for a tenant with a custom override.
  3. routes/chat.py — `_build_dna_digest_card` gains `overridden_by` per
     field (cheap keyword match — no NLP, per the checklist's own hedge) and
     an unconditional `standing_directions` footer list so nothing is ever
     hidden just because the keyword match missed it.

No live DB, no network. Run:
  cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c44_corrections_loop.py -q
"""
import asyncio
import os
import sys
import types

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


async def _boom(*a, **k):
    raise AssertionError("pure tests must not touch runtime services")


_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom, get_pool=_boom, safe_column=lambda name: name)
_stub("vault", get_secret=_boom)

import identity  # noqa: E402
from identity import IdentityContext, build_identity_context_from_rows  # noqa: E402
from pipeline_executor import resolve_prompt  # noqa: E402
import routes.chat as chat  # noqa: E402

TENANT = "tenant-c44"


# =============================================================================
# 1. identity._standing_preferences_block — channel-scope, capped, fail-soft
# =============================================================================

def test_standing_preferences_block_empty_when_no_rows(monkeypatch):
    async def fake_fetch_all(query, *args):
        return []
    monkeypatch.setattr(identity, "fetch_all", fake_fetch_all)
    out = asyncio.run(identity._standing_preferences_block(TENANT))
    assert out == ""


def test_standing_preferences_block_formats_with_obey_over_framing(monkeypatch):
    async def fake_fetch_all(query, *args):
        return [{"text": "the voice is more playful now"}, {"text": "never use stock b-roll"}]
    monkeypatch.setattr(identity, "fetch_all", fake_fetch_all)
    out = asyncio.run(identity._standing_preferences_block(TENANT))
    assert out.startswith("\n\nSTANDING CREATOR DIRECTIONS (obey these over any conflicting learned style):")
    assert "1. the voice is more playful now" in out
    assert "2. never use stock b-roll" in out


def test_standing_preferences_block_queries_channel_scope_only(monkeypatch):
    """Per-video-scoped preferences (scope=<video_id>) must never reach
    generation — only the literal 'channel' scope. This is the boundary
    check: prove the query sent to the DB pins scope='channel'."""
    captured = {}

    async def fake_fetch_all(query, *args):
        captured["query"] = query
        captured["args"] = args
        return []
    monkeypatch.setattr(identity, "fetch_all", fake_fetch_all)
    asyncio.run(identity._standing_preferences_block(TENANT))
    assert "scope = $2" in captured["query"]
    assert captured["args"][1] == "channel"
    assert "active = true" in captured["query"]


def test_standing_preferences_block_fail_soft_on_db_error(monkeypatch):
    async def boom(query, *args):
        raise RuntimeError("db down")
    monkeypatch.setattr(identity, "fetch_all", boom)
    out = asyncio.run(identity._standing_preferences_block(TENANT))
    assert out == ""


def test_standing_preferences_block_length_capped(monkeypatch):
    rows = [{"text": f"instruction number {i} " + ("x" * 200)} for i in range(30)]

    async def fake_fetch_all(query, *args):
        return rows
    monkeypatch.setattr(identity, "fetch_all", fake_fetch_all)
    out = asyncio.run(identity._standing_preferences_block(TENANT))
    assert len(out) <= identity._STANDING_PREFS_BLOCK_MAX_CHARS + len(
        "\n\nSTANDING CREATOR DIRECTIONS (obey these over any conflicting learned style):\n"
    )


def test_standing_preferences_block_ignores_blank_text_rows(monkeypatch):
    async def fake_fetch_all(query, *args):
        return [{"text": ""}, {"text": None}]
    monkeypatch.setattr(identity, "fetch_all", fake_fetch_all)
    out = asyncio.run(identity._standing_preferences_block(TENANT))
    assert out == ""


# =============================================================================
# 2. IdentityContext / build_identity_context wiring
# =============================================================================

def test_build_identity_context_from_rows_carries_standing_preferences():
    idc = build_identity_context_from_rows(
        project=None, profile=None, video=None, standing_preferences="STANDING BLOCK",
    )
    assert idc.standing_preferences == "STANDING BLOCK"


def test_build_identity_context_from_rows_defaults_to_empty_string():
    idc = build_identity_context_from_rows(project=None, profile=None, video=None)
    assert idc.standing_preferences == ""


def test_build_identity_context_wires_standing_preferences_through(monkeypatch):
    async def fake_fetch_one(query, *args):
        return None

    async def fake_fetch_all(query, *args):
        return [{"text": "always end on a cliffhanger"}]

    monkeypatch.setattr(identity, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(identity, "fetch_all", fake_fetch_all)
    idc = asyncio.run(identity.build_identity_context(TENANT, None))
    assert "always end on a cliffhanger" in idc.standing_preferences
    assert "STANDING CREATOR DIRECTIONS" in idc.standing_preferences


def test_build_identity_context_fail_soft_when_preferences_db_errors(monkeypatch):
    """A preferences-table hiccup must not break the rest of identity
    resolution — the two reads are independent fail-soft boundaries."""
    async def fake_fetch_one(query, *args):
        if "channel_profiles" in query:
            return {"channel_name": "Calm Coding", "niche": "coding", "target_audience": "devs",
                     "style_description": "calm", "frameworks": None}
        return None

    async def boom(query, *args):
        raise RuntimeError("director_preferences unreachable")

    monkeypatch.setattr(identity, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(identity, "fetch_all", boom)
    idc = asyncio.run(identity.build_identity_context(TENANT, None))
    assert idc.channel_name == "Calm Coding"  # rest of identity unaffected
    assert idc.standing_preferences == ""     # preferences hiccup -> empty, not a crash


# =============================================================================
# 3. pipeline_executor.resolve_prompt — the core wire + precedence framing
# =============================================================================

def _identity(standing_preferences=""):
    return IdentityContext(
        channel_name="Calm Coding",
        niche="beginner programming tutorials",
        target_audience="self-taught developers",
        voice_style="patient and jargon-free",
        visual_style="minimalist line art",
        frameworks=["the 3-act explainer"],
        standing_preferences=standing_preferences,
    )


_PREFS_BLOCK = (
    "\n\nSTANDING CREATOR DIRECTIONS (obey these over any conflicting learned style):\n"
    "1. Always be more playful."
)


def test_resolve_prompt_appends_standing_preferences_to_neutral_template():
    """Both blocks coexist: the identity-filled neutral template AND the
    standing-preferences block, with the obey-over framing intact."""
    idc = _identity(standing_preferences=_PREFS_BLOCK)
    out = resolve_prompt(per_video=None, tenant=None, prompt_key="script", identity=idc)
    assert "beginner programming tutorials" in out  # identity-learned content present
    assert out.endswith(_PREFS_BLOCK)  # preferences appended, not templated in
    assert "obey these over any conflicting learned style" in out


def test_resolve_prompt_appends_standing_preferences_even_with_tenant_override():
    idc = _identity(standing_preferences=_PREFS_BLOCK)
    tenant = "TENANT custom script prompt for {channel_name}."
    out = resolve_prompt(per_video=None, tenant=tenant, prompt_key="script", identity=idc)
    assert out.startswith("TENANT custom script prompt for Calm Coding.")
    assert out.endswith(_PREFS_BLOCK)


def test_resolve_prompt_appends_standing_preferences_even_with_per_video_override():
    idc = _identity(standing_preferences=_PREFS_BLOCK)
    out = resolve_prompt(per_video="PER-VIDEO wins", tenant="TENANT default", prompt_key="script", identity=idc)
    # D6-3/D6-4: STORY-LAWS S3 and S1 ride along the SAME way
    # standing_preferences does — appended right after the chosen source,
    # in that order, before standing_preferences.
    import story_laws
    assert out == (
        "PER-VIDEO wins" + "\n\n" + story_laws.SCENE_LOCATION_LAW
        + "\n\n" + story_laws.LOCATION_TRANSIT_LAW + _PREFS_BLOCK
    )


def test_resolve_prompt_no_preferences_is_byte_identical_to_pre_c44():
    """Regression: empty standing_preferences (the default for every existing
    caller/test) must reproduce the exact pre-C44 output."""
    idc = _identity()  # standing_preferences="" (default)
    out = resolve_prompt(per_video=None, tenant="TENANT default", prompt_key="sound_curation", identity=idc)
    assert out == "TENANT default"


def test_resolve_prompt_no_template_no_override_stays_none_even_with_preferences():
    """A key with no engine template and no override still returns None (the
    bot's own default) — standing preferences never manufacture a prompt out
    of nothing; they only ride along on top of a REAL resolved prompt."""
    idc = _identity(standing_preferences=_PREFS_BLOCK)
    out = resolve_prompt(per_video=None, tenant=None, prompt_key="sound_curation", identity=idc)
    assert out is None


# =============================================================================
# 4. routes/chat.py — digest overridden_by + standing_directions footer
# =============================================================================

def test_match_preference_override_finds_keyword_hit_most_recent_first():
    prefs = ["never use stock b-roll", "the voice is more playful now"]
    assert chat._match_preference_override("voice_tone", prefs) == "the voice is more playful now"
    assert chat._match_preference_override("visual_format", prefs) == "never use stock b-roll"


def test_match_preference_override_none_when_no_keyword_hits():
    prefs = ["always ship on Fridays"]
    assert chat._match_preference_override("voice_tone", prefs) is None
    assert chat._match_preference_override("unknown_field", prefs) is None


def test_build_dna_digest_card_flags_overridden_field_and_lists_footer():
    from channel_dna_meta import stamp_identity_write
    identity_dict = stamp_identity_write(
        {}, {"voice_tone": "confident, direct"}, learner="identity_builder",
    )
    run = {"learners": {}}
    prefs = [{"text": "actually the voice is more playful"}, {"text": "always ship on time"}]
    card = chat._build_dna_digest_card(identity_dict, run, prefs)

    voice_row = next(f for f in card["fields"] if f["field"] == "voice_tone")
    assert voice_row["overridden_by"] == "actually the voice is more playful"
    # Footer lists EVERY active preference, including the one that didn't
    # keyword-match any field — nothing is silently hidden.
    assert card["standing_directions"] == ["actually the voice is more playful", "always ship on time"]


def test_build_dna_digest_card_no_preferences_yields_none_overridden_and_empty_footer():
    from channel_dna_meta import stamp_identity_write
    identity_dict = stamp_identity_write({}, {"voice_tone": "x"}, learner="identity_builder")
    card = chat._build_dna_digest_card(identity_dict, {"learners": {}})
    voice_row = next(f for f in card["fields"] if f["field"] == "voice_tone")
    assert voice_row["overridden_by"] is None
    assert card["standing_directions"] == []


def test_handle_show_channel_digest_passes_preferences_into_the_card(monkeypatch):
    import json
    from channel_dna_meta import stamp_identity_write

    identity_dict = stamp_identity_write({}, {"voice_tone": "x"}, learner="identity_builder")

    async def fake_fetch_one(query, *args):
        return {"channel_identity": json.dumps(identity_dict)}

    async def fake_list_preferences(tenant_id, video_id=None):
        assert video_id is None  # channel-scope only, never leaks a video id in
        return [{"text": "always end on a cliffhanger", "scope": "channel"}]

    async def fake_persist(*a, **k):
        pass

    monkeypatch.setattr(chat, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(chat, "_list_preferences", fake_list_preferences)
    monkeypatch.setattr(chat, "_persist", fake_persist)

    state = {}
    resp = asyncio.run(chat._handle_show_channel_digest("conv-1", TENANT, [], state, "show digest"))
    assert resp.cards[0]["standing_directions"] == ["always end on a cliffhanger"]


# =============================================================================
# 5. C15c regression pin — chat's own preferences hydration is unchanged
# =============================================================================

def test_c15c_preferences_brief_framing_unchanged(monkeypatch):
    """Chat's OWN standing-preferences hydration (`_preferences_brief`, C15c)
    must be byte-for-byte unchanged by this chunk — it is a DIFFERENT block
    (per-turn chat framing) from the new generation-seam block C44 adds."""
    async def fake_list_preferences(tenant_id, video_id=None):
        return [{"scope": "channel", "text": "always be concise"}]

    monkeypatch.setattr(chat, "_list_preferences", fake_list_preferences)
    out = asyncio.run(chat._preferences_brief(TENANT))
    assert "STANDING PREFERENCES (obey unless the creator overrides this turn" in out
    assert "1. always be concise" in out
    # Not the generation-seam's distinct framing text.
    assert "STANDING CREATOR DIRECTIONS" not in out
