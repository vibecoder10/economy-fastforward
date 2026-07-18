"""Tests for C15c (checklist §Phase 1, tasks/storyengine-wiring-fix-checklist.md
"Director memory: durable preference store"): a correction said once ("the
kitten is gray", "never use premium models on Poco") becomes a STANDING
preference the chat remembers across conversations and videos, instead of
forcing the creator to re-say it every turn.

New tenant-scoped table `director_preferences` (migrations/091_director_
preferences.sql), applied live via Supabase MCP against wrromlupsmyzrrcqlucn
and confirmed via information_schema.columns. Mirrors the existing
`_save_creator_brief` / `_hydrate_creator_brief` pattern in routes/chat.py:
fail-soft everywhere (a memory-store DB error must never break a chat turn).

Layers pinned here:
  1. `routes.chat._save_preference` — verbatim text, tenant-bound, scoped
     ('channel' or a video_id), fail-soft on DB error.
  2. `routes.chat._list_preferences` — channel-wide + (optionally) one
     video's own, tenant-bound, newest-first, capped, fail-soft -> [].
  3. `routes.chat._preferences_brief` — the additive system-prompt block:
     empty when there's nothing to say, numbered + video-tagged, length
     capped, fail-soft -> "".
  4. `routes.chat._deactivate_preference` — "forget #N" / "forget that" /
     text match; soft-delete only (UPDATE ... active=false, never DELETE);
     fail-soft -> (False, "").
  5. `routes.chat._handle_remember_op` / `_handle_forget_op` — the in-video
     co-pilot's kind=="remember"/"forget" branches.
  6. Source-lock: BOTH chat system-prompt builders (`chat_turn` for the home
     producer, `_handle_copilot` for the in-video co-pilot) actually call
     `_preferences_brief` — the memory can't silently stop being hydrated
     into one side without this test catching it (same source-inspection
     pattern test_c15a/test_c15b use for their own wiring locks).
  7. Both decision schemas (agent_brain's tool-loop brain, and chat.py's
     one-shot fallback classifier) carry the remember/forget vocabulary.
  8. Home producer's `_apply_profile_ops` "remember"/"forget" ops (the write
     path for the home chat, which has no single "current video" in scope).

Same stub pattern as test_c15a/test_c15b: no live DB, no network.
Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c15c_director_memory.py -q
"""
import asyncio
import inspect
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


_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom)
_stub("vault", get_secret=_boom)

import routes.chat as chat  # noqa: E402

TENANT = "tenant-1"
OTHER_TENANT = "tenant-2"
VIDEO = "video-1"


# ---------------------------------------------------------------------------
# 1. _save_preference — verbatim, tenant-bound, scoped, fail-soft
# ---------------------------------------------------------------------------

def test_save_preference_writes_verbatim_text_tenant_and_scope_bound(monkeypatch):
    seen = {}

    async def fake_execute(query, *args):
        seen["query"] = query
        seen["args"] = args

    monkeypatch.setattr(chat, "execute", fake_execute)
    asyncio.run(chat._save_preference(TENANT, "  never use premium models on Poco  ", scope="channel"))

    assert "INSERT INTO director_preferences" in seen["query"]
    # Exactly the trimmed verbatim text — never paraphrased, never re-cased.
    assert seen["args"] == (TENANT, "channel", "never use premium models on Poco")


def test_save_preference_video_scoped_stores_the_video_id_as_scope(monkeypatch):
    seen = {}

    async def fake_execute(query, *args):
        seen["args"] = args

    monkeypatch.setattr(chat, "execute", fake_execute)
    asyncio.run(chat._save_preference(TENANT, "the kitten is gray", scope=VIDEO))
    assert seen["args"] == (TENANT, VIDEO, "the kitten is gray")


def test_save_preference_empty_text_is_a_noop(monkeypatch):
    async def fake_execute(*a, **k):
        raise AssertionError("must not write an empty preference")
    monkeypatch.setattr(chat, "execute", fake_execute)
    asyncio.run(chat._save_preference(TENANT, "   "))  # no exception


def test_save_preference_fail_soft_on_db_error(monkeypatch):
    async def fake_execute(*a, **k):
        raise RuntimeError("db is down")
    monkeypatch.setattr(chat, "execute", fake_execute)
    # Must not raise -- memory is best-effort, never blocks the turn that triggered it.
    asyncio.run(chat._save_preference(TENANT, "always use gray for the kitten"))


# ---------------------------------------------------------------------------
# 2. _list_preferences — channel + video scoping, tenant-bound, capped, fail-soft
# ---------------------------------------------------------------------------

def test_list_preferences_channel_only_when_no_video_id(monkeypatch):
    seen = {}

    async def fake_fetch_all(query, *args):
        seen["query"] = query
        seen["args"] = args
        return []

    monkeypatch.setattr(chat, "fetch_all", fake_fetch_all)
    asyncio.run(chat._list_preferences(TENANT, video_id=None))
    assert seen["args"][0] == TENANT
    assert seen["args"][1] == ["channel"]
    assert seen["args"][2] == chat._PREF_CAP


def test_list_preferences_adds_video_scope_when_video_id_given(monkeypatch):
    seen = {}

    async def fake_fetch_all(query, *args):
        seen["args"] = args
        return []

    monkeypatch.setattr(chat, "fetch_all", fake_fetch_all)
    asyncio.run(chat._list_preferences(TENANT, video_id=VIDEO))
    assert seen["args"][1] == ["channel", VIDEO]


def test_list_preferences_query_is_tenant_active_scoped_and_capped(monkeypatch):
    seen = {}

    async def fake_fetch_all(query, *args):
        seen["query"] = query
        return []

    monkeypatch.setattr(chat, "fetch_all", fake_fetch_all)
    asyncio.run(chat._list_preferences(TENANT))
    assert "tenant_id = $1" in seen["query"]
    assert "active = true" in seen["query"]
    assert "scope = ANY($2::text[])" in seen["query"]
    assert "ORDER BY created_at DESC" in seen["query"]
    assert "LIMIT $3" in seen["query"]


def test_list_preferences_different_tenant_gets_its_own_scoped_call(monkeypatch):
    seen = {}

    async def fake_fetch_all(query, *args):
        seen["args"] = args
        return []

    monkeypatch.setattr(chat, "fetch_all", fake_fetch_all)
    asyncio.run(chat._list_preferences(OTHER_TENANT))
    assert seen["args"][0] == OTHER_TENANT


def test_list_preferences_fail_soft_returns_empty_list(monkeypatch):
    async def fake_fetch_all(*a, **k):
        raise RuntimeError("db is down")
    monkeypatch.setattr(chat, "fetch_all", fake_fetch_all)
    result = asyncio.run(chat._list_preferences(TENANT))
    assert result == []


# ---------------------------------------------------------------------------
# 3. _preferences_brief — the hydration block
# ---------------------------------------------------------------------------

def _rows(n, scope="channel"):
    return [{"id": f"pref-{i}", "scope": scope, "text": f"preference number {i}"} for i in range(1, n + 1)]


def test_preferences_brief_empty_when_no_active_preferences(monkeypatch):
    async def fake_fetch_all(*a, **k):
        return []
    monkeypatch.setattr(chat, "fetch_all", fake_fetch_all)
    assert asyncio.run(chat._preferences_brief(TENANT)) == ""


def test_preferences_brief_numbers_newest_first_and_tags_video_scoped(monkeypatch):
    async def fake_fetch_all(*a, **k):
        return [
            {"id": "1", "scope": VIDEO, "text": "the kitten is gray"},
            {"id": "2", "scope": "channel", "text": "never use premium models on Poco"},
        ]
    monkeypatch.setattr(chat, "fetch_all", fake_fetch_all)
    block = asyncio.run(chat._preferences_brief(TENANT, video_id=VIDEO))
    assert "STANDING PREFERENCES" in block
    assert "1. the kitten is gray (this video only)" in block
    assert "2. never use premium models on Poco" in block
    assert "never use premium models on Poco (this video only)" not in block


def test_preferences_brief_no_video_tag_when_no_video_id(monkeypatch):
    async def fake_fetch_all(*a, **k):
        return [{"id": "1", "scope": "channel", "text": "always keep captions on"}]
    monkeypatch.setattr(chat, "fetch_all", fake_fetch_all)
    block = asyncio.run(chat._preferences_brief(TENANT))
    assert "(this video only)" not in block
    assert "1. always keep captions on" in block


def test_preferences_brief_length_is_capped(monkeypatch):
    long_rows = [{"id": str(i), "scope": "channel", "text": "x" * 500} for i in range(20)]

    async def fake_fetch_all(*a, **k):
        return long_rows

    monkeypatch.setattr(chat, "fetch_all", fake_fetch_all)
    block = asyncio.run(chat._preferences_brief(TENANT))
    assert len(block) <= chat._PREF_BLOCK_MAX_CHARS + 200  # + header/prefix overhead


def test_preferences_brief_fail_soft_on_db_error(monkeypatch):
    async def fake_fetch_all(*a, **k):
        raise RuntimeError("db is down")
    monkeypatch.setattr(chat, "fetch_all", fake_fetch_all)
    assert asyncio.run(chat._preferences_brief(TENANT)) == ""


# ---------------------------------------------------------------------------
# 4. _deactivate_preference — soft-delete only, matching rules, fail-soft
# ---------------------------------------------------------------------------

def test_deactivate_preference_exact_text_match(monkeypatch):
    monkeypatch.setattr(chat, "fetch_all", lambda *a, **k: _async(_rows(3)))
    seen = {}

    async def fake_execute(query, *args):
        seen["query"] = query
        seen["args"] = args

    monkeypatch.setattr(chat, "execute", fake_execute)
    ok, matched = asyncio.run(chat._deactivate_preference(TENANT, "preference number 2"))
    assert ok is True
    assert matched == "preference number 2"
    assert "UPDATE director_preferences" in seen["query"]
    assert "active = false" in seen["query"]
    assert "DELETE" not in seen["query"].upper()
    assert seen["args"] == ("pref-2", TENANT)


def test_deactivate_preference_numeric_hash_reference_matches_by_position(monkeypatch):
    monkeypatch.setattr(chat, "fetch_all", lambda *a, **k: _async(_rows(3)))

    async def fake_execute(*a, **k):
        pass
    monkeypatch.setattr(chat, "execute", fake_execute)

    ok, matched = asyncio.run(chat._deactivate_preference(TENANT, "#2"))
    assert ok is True
    assert matched == "preference number 2"


def test_deactivate_preference_bare_number_matches_by_position(monkeypatch):
    monkeypatch.setattr(chat, "fetch_all", lambda *a, **k: _async(_rows(3)))

    async def fake_execute(*a, **k):
        pass
    monkeypatch.setattr(chat, "execute", fake_execute)

    ok, matched = asyncio.run(chat._deactivate_preference(TENANT, "3"))
    assert ok is True
    assert matched == "preference number 3"


def test_deactivate_preference_substring_match(monkeypatch):
    async def fake_fetch_all(*a, **k):
        return [{"id": "p1", "scope": "channel", "text": "never use premium models on Poco"}]
    monkeypatch.setattr(chat, "fetch_all", fake_fetch_all)

    async def fake_execute(*a, **k):
        pass
    monkeypatch.setattr(chat, "execute", fake_execute)

    ok, matched = asyncio.run(chat._deactivate_preference(TENANT, "premium models"))
    assert ok is True
    assert matched == "never use premium models on Poco"


def test_deactivate_preference_generic_reference_picks_most_recent(monkeypatch):
    """rows are already newest-first (matches _list_preferences' ORDER BY)."""
    monkeypatch.setattr(chat, "fetch_all", lambda *a, **k: _async(_rows(3)))

    async def fake_execute(*a, **k):
        pass
    monkeypatch.setattr(chat, "execute", fake_execute)

    for ref in ("that", "it", "last", "the last one", ""):
        ok, matched = asyncio.run(chat._deactivate_preference(TENANT, ref))
        assert ok is True
        assert matched == "preference number 1", f"ref={ref!r}"


def test_deactivate_preference_no_match_returns_false(monkeypatch):
    monkeypatch.setattr(chat, "fetch_all", lambda *a, **k: _async(_rows(2)))

    async def fake_execute(*a, **k):
        raise AssertionError("must not write when nothing matched")
    monkeypatch.setattr(chat, "execute", fake_execute)

    ok, matched = asyncio.run(chat._deactivate_preference(TENANT, "something totally unrelated xyz"))
    assert ok is False
    assert matched == ""


def test_deactivate_preference_nothing_active_returns_false(monkeypatch):
    monkeypatch.setattr(chat, "fetch_all", lambda *a, **k: _async([]))
    ok, matched = asyncio.run(chat._deactivate_preference(TENANT, "that"))
    assert ok is False
    assert matched == ""


def test_deactivate_preference_fail_soft_on_db_error(monkeypatch):
    monkeypatch.setattr(chat, "fetch_all", lambda *a, **k: _async(_rows(1)))

    async def fake_execute(*a, **k):
        raise RuntimeError("db is down")
    monkeypatch.setattr(chat, "execute", fake_execute)

    ok, matched = asyncio.run(chat._deactivate_preference(TENANT, "that"))
    assert ok is False
    assert matched == ""


def test_deactivate_preference_scoped_to_tenant_and_video_group(monkeypatch):
    """Confirms the same channel+video scope group hydration uses is what
    forget searches -- passing video_id threads through to _list_preferences."""
    seen = {}

    async def fake_fetch_all(query, *args):
        seen["args"] = args
        return []

    monkeypatch.setattr(chat, "fetch_all", fake_fetch_all)
    asyncio.run(chat._deactivate_preference(TENANT, "that", video_id=VIDEO))
    assert seen["args"][0] == TENANT
    assert seen["args"][1] == ["channel", VIDEO]


async def _async(value):
    return value


# ---------------------------------------------------------------------------
# 5. _handle_remember_op / _handle_forget_op -- the in-video co-pilot branches
# ---------------------------------------------------------------------------

async def _collect_reply(coro):
    replies = []

    async def _reply(text, cards=None):
        replies.append((text, cards))
        return {"text": text, "cards": cards}

    await coro(_reply)
    return replies[-1]


def test_handle_remember_op_saves_verbatim_and_defaults_channel_wide(monkeypatch):
    saved = {}

    async def fake_save(tenant_id, text, scope="channel"):
        saved["tenant_id"] = tenant_id
        saved["text"] = text
        saved["scope"] = scope

    monkeypatch.setattr(chat, "_save_preference", fake_save)

    async def run(_reply):
        return await chat._handle_remember_op(
            TENANT, VIDEO, {"change": "never use premium models on Poco"}, _reply
        )

    text, _cards = asyncio.run(_collect_reply(run))
    assert saved == {"tenant_id": TENANT, "text": "never use premium models on Poco", "scope": "channel"}
    assert "Got it" in text
    assert "never use premium models on Poco" in text
    assert "forget that" in text.lower()


def test_handle_remember_op_video_scope_when_explicitly_requested(monkeypatch):
    saved = {}

    async def fake_save(tenant_id, text, scope="channel"):
        saved["scope"] = scope

    monkeypatch.setattr(chat, "_save_preference", fake_save)

    async def run(_reply):
        return await chat._handle_remember_op(
            TENANT, VIDEO, {"change": "the kitten is gray", "scope": "video"}, _reply
        )

    text, _cards = asyncio.run(_collect_reply(run))
    assert saved["scope"] == VIDEO
    assert "this video" in text.lower()


def test_handle_remember_op_empty_text_asks_instead_of_saving(monkeypatch):
    async def fake_save(*a, **k):
        raise AssertionError("must not save an empty preference")
    monkeypatch.setattr(chat, "_save_preference", fake_save)

    async def run(_reply):
        return await chat._handle_remember_op(TENANT, VIDEO, {"change": ""}, _reply)

    text, _cards = asyncio.run(_collect_reply(run))
    assert "what would you like me to remember" in text.lower()


def test_handle_forget_op_success_confirms_what_was_removed(monkeypatch):
    async def fake_deactivate(tenant_id, ref, video_id=None):
        assert tenant_id == TENANT
        assert ref == "that"
        assert video_id == VIDEO
        return True, "never use premium models on Poco"

    monkeypatch.setattr(chat, "_deactivate_preference", fake_deactivate)

    async def run(_reply):
        return await chat._handle_forget_op(TENANT, VIDEO, {"change": "that"}, _reply)

    text, _cards = asyncio.run(_collect_reply(run))
    assert "Forgot it" in text
    assert "never use premium models on Poco" in text


def test_handle_forget_op_no_match_asks_which_one(monkeypatch):
    async def fake_deactivate(*a, **k):
        return False, ""
    monkeypatch.setattr(chat, "_deactivate_preference", fake_deactivate)

    async def run(_reply):
        return await chat._handle_forget_op(TENANT, VIDEO, {"change": "something obscure"}, _reply)

    text, _cards = asyncio.run(_collect_reply(run))
    assert "couldn't find" in text.lower()


# ---------------------------------------------------------------------------
# 6. Source-lock: BOTH chat system prompts actually hydrate preferences
# ---------------------------------------------------------------------------

def test_home_producer_chat_turn_hydrates_preferences_into_system_prompt():
    src = inspect.getsource(chat.chat_turn)
    assert "_preferences_brief(tenant_id)" in src


def test_in_video_copilot_hydrates_preferences_into_summary():
    src = inspect.getsource(chat._handle_copilot)
    assert "_preferences_brief(tenant_id, video_id)" in src


def test_copilot_dispatches_remember_and_forget_kinds():
    src = inspect.getsource(chat._handle_copilot)
    assert '_handle_remember_op(tenant_id, video_id, data, _reply)' in src
    assert '_handle_forget_op(tenant_id, video_id, data, _reply)' in src


# ---------------------------------------------------------------------------
# 7. Both decision schemas carry the remember/forget vocabulary
# ---------------------------------------------------------------------------

def test_agent_brain_decision_schema_includes_remember_and_forget():
    import agent_brain
    schema = agent_brain._decision_schema()
    assert "remember" in schema
    assert "forget" in schema
    assert '"scope":"channel|video' in schema


def test_agent_brain_system_prompt_teaches_the_classification_trigger():
    import agent_brain
    src = inspect.getsource(agent_brain.run_copilot_brain)
    assert "always" in src.lower() and "never" in src.lower() and "from now on" in src.lower()
    assert "VERBATIM" in src


def test_fallback_classifier_prompt_includes_remember_and_forget():
    src = inspect.getsource(chat._handle_copilot)
    assert '"kind":"read|action|prompt|show|remember|forget"' in src


# ---------------------------------------------------------------------------
# 8. Home producer write path: profile_ops "remember" / "forget"
# ---------------------------------------------------------------------------

def test_apply_profile_ops_remember_saves_channel_wide(monkeypatch):
    saved = {}

    async def fake_save(tenant_id, text, scope="channel"):
        saved["tenant_id"] = tenant_id
        saved["text"] = text
        saved["scope"] = scope

    monkeypatch.setattr(chat, "_save_preference", fake_save)
    results = asyncio.run(chat._apply_profile_ops(
        TENANT, [{"op": "remember", "value": "always use the watercolor look"}], {}, None
    ))
    assert saved == {"tenant_id": TENANT, "text": "always use the watercolor look", "scope": chat._PREF_SCOPE_CHANNEL}
    assert any("Got it" in r for r in results)


def test_apply_profile_ops_forget_confirms_removal(monkeypatch):
    async def fake_deactivate(tenant_id, ref, video_id=None):
        assert video_id is None  # home chat has no single "current video"
        return True, "always use the watercolor look"

    monkeypatch.setattr(chat, "_deactivate_preference", fake_deactivate)
    results = asyncio.run(chat._apply_profile_ops(
        TENANT, [{"op": "forget", "value": "that"}], {}, None
    ))
    assert any("Forgot it" in r and "always use the watercolor look" in r for r in results)


def test_apply_profile_ops_remember_empty_value_asks_instead_of_saving(monkeypatch):
    async def fake_save(*a, **k):
        raise AssertionError("must not save an empty preference")
    monkeypatch.setattr(chat, "_save_preference", fake_save)
    results = asyncio.run(chat._apply_profile_ops(TENANT, [{"op": "remember", "value": ""}], {}, None))
    assert any("what would you like me to remember" in r.lower() for r in results)


def test_producer_prompt_teaches_remember_and_forget_ops():
    import producer_prompt
    assert '"op":"remember"' in producer_prompt.PRODUCER_SYSTEM_PROMPT
    assert '"op":"forget"' in producer_prompt.PRODUCER_SYSTEM_PROMPT
    assert "WORD FOR WORD" in producer_prompt.PRODUCER_SYSTEM_PROMPT
    assert "STANDING PREFERENCES" in producer_prompt.PRODUCER_SYSTEM_PROMPT
