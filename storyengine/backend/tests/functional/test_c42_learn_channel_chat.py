"""Tests for C42 (checklist P4.1c — "learn this channel" chat front door +
confirmable digest card).

C41 (merged, tests/functional/test_c41_channel_dna.py) shipped the unified
orchestrator `channel_dna.learn_channel` but left it unreachable from any
door. This chunk wires it to chat, adds a digest card the creator can act
on (keep/revert/correct), and exposes the same function via a thin HTTP
route for C45 (onboarding) and a future MCP tool to reuse.

Four layers, matching the module split:

  1. channel_dna_meta.py extensions — `stamp_last_run` (the `_last_run`
     envelope key, set WITHOUT going through the per-field provenance loop)
     and `latest_history_index_for_field` (the revert-button gate + the
     server-side index re-resolution the revert op uses).
  2. channel_dna.py extensions — `_persist_last_run` (fail-soft: an execute()
     failure must fall back to the identity as already fetched, not blow up
     an otherwise-successful run), `revert_field` (the C40 history undo,
     tenant-scoped by construction), `is_learning` (fail-OPEN status read).
  3. routes/chat.py — `_learn_channel_intent` / `_extract_channel_url` /
     `_handle_learn_channel` (ack-now + background task, money-honest ack
     text); `_dna_digest_intent` / `_handle_show_channel_digest` /
     `_build_dna_digest_card` (per-learner sections, provenance, an honest
     header when a learner failed); `_handle_dna_digest_action` (the
     deterministic keep/revert/correct dispatch, source-locked to run BEFORE
     producer intake, exactly like C22's style_draft confirm).
  4. routes/channel_dna.py — the thin `/api/channel-dna/learn` + `/status`
     door, proven to call the EXACT SAME `learn_channel` callable chat uses
     (one implementation, two doors).

No live DB, no network. Run:
  cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c42_learn_channel_chat.py -q
"""
import asyncio
import inspect
import json
import os
import sys
import types
from unittest.mock import AsyncMock

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

import channel_dna  # noqa: E402
import routes.channel_dna as channel_dna_route  # noqa: E402
import routes.chat as chat  # noqa: E402
from channel_dna_meta import (  # noqa: E402
    coerce_identity,
    field_provenance,
    latest_history_index_for_field,
    stamp_identity_write,
    stamp_last_run,
)

TENANT = "tenant-1"


# =============================================================================
# 1. channel_dna_meta.py — stamp_last_run / latest_history_index_for_field
# =============================================================================

def test_stamp_last_run_sets_key_without_touching_sources_or_history():
    identity = stamp_identity_write({}, {"voice_tone": "confident"}, learner="identity_builder")
    run_digest = {"at": "2026-07-19T00:00:00+00:00", "ok": True, "learners": {"identity_builder": {"status": "learned"}}}
    out = stamp_last_run(identity, run_digest)

    assert out["_last_run"] == run_digest
    # untouched: same provenance, same single history entry as before
    assert field_provenance(out, "voice_tone")["learner"] == "identity_builder"
    assert len(out["_history"]) == 1
    assert out["voice_tone"] == "confident"


def test_stamp_last_run_never_mutates_input_and_preserves_other_writers_fields():
    prior = stamp_identity_write({}, {"visual_format": {"style": "3D"}}, learner="channel_format")
    import copy
    snapshot = copy.deepcopy(prior)
    out = stamp_last_run(prior, {"ok": True, "learners": {}})
    assert prior == snapshot  # input untouched
    assert out["visual_format"] == {"style": "3D"}  # survives


def test_latest_history_index_for_field_finds_most_recent_change():
    v1 = stamp_identity_write({}, {"voice_tone": "a"}, learner="identity_builder")  # history[0]: voice_tone
    v2 = stamp_identity_write(v1, {"cadence": "b"}, learner="identity_builder")  # history[1]: cadence (new field)
    v3 = stamp_identity_write(v2, {"voice_tone": "c"}, learner="identity_builder")  # history[2]: voice_tone again

    idx = latest_history_index_for_field(v3, "voice_tone")
    assert idx == 2  # the v2->v3 change, not the v1 creation (index 0)
    assert v3["_history"][idx]["fields_changed"] == ["voice_tone"]
    assert latest_history_index_for_field(v3, "cadence") == 1


def test_latest_history_index_for_field_none_when_field_never_changed():
    identity = stamp_identity_write({}, {"voice_tone": "a"}, learner="identity_builder")
    assert latest_history_index_for_field(identity, "cadence") is None
    assert latest_history_index_for_field({}, "voice_tone") is None


# =============================================================================
# 2. channel_dna.py — _persist_last_run / revert_field / is_learning
# =============================================================================

def test_persist_last_run_writes_last_run_and_returns_merged_identity(monkeypatch):
    written = {}

    async def fake_current_identity(tenant_id):
        return {"voice_tone": "x"}

    async def fake_execute(query, *args):
        assert "channel_identity" in query
        written["payload"] = json.loads(args[-1])
        return None

    monkeypatch.setattr(channel_dna, "_current_identity", fake_current_identity)
    monkeypatch.setattr(channel_dna, "execute", fake_execute)

    learners = {"identity_builder": {"status": "learned", "summary": "ok", "fields_written": [], "error": None}}
    result = asyncio.run(channel_dna._persist_last_run(TENANT, learners, True))

    assert result["voice_tone"] == "x"
    assert result["_last_run"]["ok"] is True
    assert result["_last_run"]["learners"] == learners
    assert written["payload"]["_last_run"]["ok"] is True
    print("✅ test_persist_last_run_writes_last_run_and_returns_merged_identity")


def test_persist_last_run_fails_soft_and_falls_back_to_fetched_identity(monkeypatch):
    """An execute() hiccup while persisting the digest must never surface as
    a broken learn_channel call — the caller still gets a usable identity
    dict back, just without _last_run this time."""
    async def fake_current_identity(tenant_id):
        return {"voice_tone": "x"}

    async def failing_execute(*a, **k):
        raise RuntimeError("db is down")

    monkeypatch.setattr(channel_dna, "_current_identity", fake_current_identity)
    monkeypatch.setattr(channel_dna, "execute", failing_execute)

    result = asyncio.run(channel_dna._persist_last_run(TENANT, {}, True))
    assert result == {"voice_tone": "x"}
    assert "_last_run" not in result
    print("✅ test_persist_last_run_fails_soft_and_falls_back_to_fetched_identity")


def test_learn_channel_return_contract_includes_last_run(monkeypatch):
    """End-to-end (within learn_channel itself, learners monkeypatched): the
    returned identity carries _last_run once the real _persist_last_run path
    runs against a working fake DB."""
    async def fake_fetch_one(query, *args):
        return {"channel_identity": json.dumps({"voice_tone": "x"})}

    written = {}

    async def fake_execute(query, *args):
        written["payload"] = json.loads(args[-1])
        return None

    monkeypatch.setattr(channel_dna, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(channel_dna, "execute", fake_execute)
    monkeypatch.setattr(channel_dna.generation_claims, "acquire_channel", AsyncMock(return_value=True))
    monkeypatch.setattr(channel_dna.generation_claims, "release_channel", AsyncMock(return_value=None))

    async def learned(*a, **k):
        return channel_dna._learner_result("learned", "ok")
    monkeypatch.setattr(channel_dna, "_run_import", learned)
    monkeypatch.setattr(channel_dna, "_run_identity_builder", lambda *a, **k: _identity_triple())
    monkeypatch.setattr(channel_dna, "_run_script_template", learned)
    monkeypatch.setattr(channel_dna, "_run_channel_format", learned)
    monkeypatch.setattr(channel_dna, "_run_reference_video", learned)

    result = asyncio.run(channel_dna.learn_channel(TENANT))

    assert result["identity"]["voice_tone"] == "x"
    assert result["identity"]["_last_run"]["ok"] is True
    assert set(result["identity"]["_last_run"]["learners"].keys()) == set(result["learners"].keys())
    print("✅ test_learn_channel_return_contract_includes_last_run")


async def _identity_triple():
    return channel_dna._learner_result("learned", "ok"), None, []


def test_revert_field_success_writes_restored_identity(monkeypatch):
    prior = stamp_identity_write({}, {"voice_tone": "confident"}, learner="identity_builder")
    prior = stamp_identity_write(prior, {"voice_tone": "overconfident"}, learner="identity_builder")
    written = {}

    async def fake_current_identity(tenant_id):
        return prior

    async def fake_execute(query, *args):
        written["payload"] = json.loads(args[-1])
        return None

    monkeypatch.setattr(channel_dna, "_current_identity", fake_current_identity)
    monkeypatch.setattr(channel_dna, "execute", fake_execute)

    ok, msg = asyncio.run(channel_dna.revert_field(TENANT, "voice_tone"))
    assert ok is True
    assert "voice tone" in msg.lower()
    assert written["payload"]["voice_tone"] == "confident"
    assert field_provenance(written["payload"], "voice_tone")["learner"] == "restore"
    print("✅ test_revert_field_success_writes_restored_identity")


def test_revert_field_nothing_to_revert_is_friendly_not_an_error(monkeypatch):
    """A field that has NEVER been touched by any stamp_identity_write call
    (no envelope/history at all) has nothing to revert. Note: a field's very
    FIRST write IS revertable (back to absent) by C40's own design — see
    channel_dna_meta's test_restore_field_to_previously_absent_sets_none —
    so this test uses a field that was never learned in the first place,
    not one that's only been set once."""
    async def fake_current_identity(tenant_id):
        return stamp_identity_write({}, {"voice_tone": "learned"}, learner="identity_builder")

    async def boom_execute(*a, **k):
        raise AssertionError("must not write when there's nothing to revert")

    monkeypatch.setattr(channel_dna, "_current_identity", fake_current_identity)
    monkeypatch.setattr(channel_dna, "execute", boom_execute)

    ok, msg = asyncio.run(channel_dna.revert_field(TENANT, "cadence"))  # never learned
    assert ok is False
    assert "nothing to revert" in msg.lower()
    print("✅ test_revert_field_nothing_to_revert_is_friendly_not_an_error")


def test_revert_field_scoped_to_the_fetched_tenants_own_identity(monkeypatch):
    """revert_field never takes an identity as an argument — it always reads
    THIS tenant's own channel_profiles row via _current_identity, so it can't
    be pointed at another tenant's data no matter what the caller passes."""
    seen = {}

    async def fake_current_identity(tenant_id):
        seen["tenant_id"] = tenant_id
        return stamp_identity_write({}, {"voice_tone": "a"}, learner="x")

    monkeypatch.setattr(channel_dna, "_current_identity", fake_current_identity)
    monkeypatch.setattr(channel_dna, "execute", _boom)  # nothing to revert -> never reached anyway

    asyncio.run(channel_dna.revert_field("tenant-only-this-one", "voice_tone"))
    assert seen["tenant_id"] == "tenant-only-this-one"
    print("✅ test_revert_field_scoped_to_the_fetched_tenants_own_identity")


def test_is_learning_true_when_claim_row_present(monkeypatch):
    async def fake_fetch_one(query, *args):
        assert "generation_claims" in query
        assert args == (TENANT, channel_dna.CLAIM_STAGE)
        return {"x": 1}

    monkeypatch.setattr(channel_dna, "fetch_one", fake_fetch_one)
    assert asyncio.run(channel_dna.is_learning(TENANT)) is True


def test_is_learning_false_when_no_claim_row(monkeypatch):
    async def fake_fetch_one(query, *args):
        return None

    monkeypatch.setattr(channel_dna, "fetch_one", fake_fetch_one)
    assert asyncio.run(channel_dna.is_learning(TENANT)) is False


def test_is_learning_fails_open_on_db_error(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(channel_dna, "fetch_one", boom)
    assert asyncio.run(channel_dna.is_learning(TENANT)) is False


# =============================================================================
# 3. routes/chat.py — intent detection
# =============================================================================

def test_learn_channel_intent_matches_the_three_spec_examples():
    assert chat._learn_channel_intent("learn this channel: https://youtube.com/@SomeChannel") is True
    assert chat._learn_channel_intent("learn my channel") is True
    assert chat._learn_channel_intent("here's a channel I'm managing https://youtube.com/@X") is True


def test_learn_channel_intent_requires_channel_word():
    assert chat._learn_channel_intent("learn my voice") is False
    assert chat._learn_channel_intent("study the market") is False


def test_learn_channel_intent_false_on_ordinary_video_asks():
    assert chat._learn_channel_intent("make a video about dragons") is False
    assert chat._learn_channel_intent("") is False
    assert chat._learn_channel_intent(None) is False


def test_extract_channel_url_pulls_the_handle_or_url():
    assert chat._extract_channel_url("learn this channel: https://youtube.com/@SomeChannel") == "https://youtube.com/@SomeChannel"
    assert chat._extract_channel_url("here's a channel I'm managing @PowerDoctrine, learn it") == "@PowerDoctrine"
    assert chat._extract_channel_url("learn my channel") is None


def test_dna_digest_intent_matches_variants():
    assert chat._dna_digest_intent("show me the channel digest") is True
    assert chat._dna_digest_intent("what did you learn?") is True
    assert chat._dna_digest_intent("what did you learn about my channel") is True
    assert chat._dna_digest_intent("make a video about dragons") is False


# =============================================================================
# 4. routes/chat.py — _handle_learn_channel: ack-now + background task
# =============================================================================

def test_handle_learn_channel_acks_immediately_states_cost_and_backgrounds_the_work(monkeypatch):
    calls = []

    class FakeBackgroundTasks:
        def add_task(self, fn):
            calls.append(fn)

    async def fake_persist(*a, **k):
        pass

    monkeypatch.setattr(chat, "_persist", fake_persist)

    resp = asyncio.run(chat._handle_learn_channel(
        "conv-1", TENANT, [], {}, "learn this channel: https://youtube.com/@X", FakeBackgroundTasks(),
    ))

    assert "$0.10-0.30" in resp.assistant_text
    assert "analyzing the channel" in resp.assistant_text.lower()
    assert len(calls) == 1, "the actual learn_channel call must be scheduled as a background task, not awaited inline"


def test_handle_learn_channel_job_calls_the_real_orchestrator_with_the_parsed_url(monkeypatch):
    """The background job (captured, then run manually here) must call
    channel_dna.learn_channel with the URL extracted from the message."""
    seen = {}

    async def fake_learn_channel(tenant_id, channel_url=None, **kw):
        seen["tenant_id"] = tenant_id
        seen["channel_url"] = channel_url
        return {"ok": True, "busy": False, "error": None, "learners": {}, "identity": {}}

    fake_channel_dna_mod = types.ModuleType("channel_dna")
    fake_channel_dna_mod.learn_channel = fake_learn_channel
    monkeypatch.setitem(sys.modules, "channel_dna", fake_channel_dna_mod)

    calls = []

    class FakeBackgroundTasks:
        def add_task(self, fn):
            calls.append(fn)

    async def fake_persist(*a, **k):
        pass

    monkeypatch.setattr(chat, "_persist", fake_persist)

    asyncio.run(chat._handle_learn_channel(
        "conv-1", TENANT, [], {}, "learn this channel: https://youtube.com/@SomeChannel", FakeBackgroundTasks(),
    ))
    asyncio.run(calls[0]())

    assert seen["tenant_id"] == TENANT
    assert seen["channel_url"] == "https://youtube.com/@SomeChannel"


def test_handle_learn_channel_job_never_raises_out_of_the_background_task(monkeypatch):
    fake_channel_dna_mod = types.ModuleType("channel_dna")

    async def boom(*a, **k):
        raise RuntimeError("firecrawl down")
    fake_channel_dna_mod.learn_channel = boom
    monkeypatch.setitem(sys.modules, "channel_dna", fake_channel_dna_mod)

    calls = []

    class FakeBackgroundTasks:
        def add_task(self, fn):
            calls.append(fn)

    async def fake_persist(*a, **k):
        pass
    monkeypatch.setattr(chat, "_persist", fake_persist)

    asyncio.run(chat._handle_learn_channel("conv-1", TENANT, [], {}, "learn my channel", FakeBackgroundTasks()))
    asyncio.run(calls[0]())  # must not raise


# =============================================================================
# 5. routes/chat.py — digest card building + honest failed-learner header
# =============================================================================

def test_build_dna_digest_card_shape_with_provenance_and_no_failures():
    identity = stamp_identity_write({}, {"voice_tone": "wry, understated", "cadence": "short bursts"},
                                     learner="identity_builder", confidence=0.8)
    run = {"ok": True, "learners": {
        "identity_builder": {"status": "learned", "summary": "Learned voice, cadence, hooks.", "fields_written": [], "error": None},
        "script_template": {"status": "skipped", "summary": "No example script provided.", "fields_written": [], "error": None},
    }}
    card = chat._build_dna_digest_card(identity, run)

    assert card["id"] == "channel_dna_digest"
    assert card["any_failed"] is False
    assert card["header"] == "Here's what I learned about your channel:"
    names = {l["name"] for l in card["learners"]}
    assert names == {"identity_builder", "script_template"}
    voice_row = next(f for f in card["fields"] if f["field"] == "voice_tone")
    assert voice_row["value"] == "wry, understated"
    assert voice_row["learner"] == "identity_builder"
    # Even a field's first-ever write is revertable (back to absent) by C40's
    # own design — see channel_dna_meta's test_restore_field_to_previously_
    # absent_sets_none — so a freshly-learned field DOES show a Revert here.
    assert voice_row["revertable"] is True
    # cadence present too, structure/hook_style absent (never set) -> omitted, not manufactured
    field_names = {f["field"] for f in card["fields"]}
    assert "cadence" in field_names
    assert "structure" not in field_names
    print("✅ test_build_dna_digest_card_shape_with_provenance_and_no_failures")


def test_build_dna_digest_card_honest_header_when_a_learner_failed():
    identity = stamp_identity_write({}, {"voice_tone": "x"}, learner="identity_builder")
    run = {"ok": True, "learners": {
        "identity_builder": {"status": "learned", "summary": "ok", "fields_written": [], "error": None},
        "script_template": {"status": "failed", "summary": "Couldn't fetch transcripts.", "fields_written": [], "error": "blocked"},
    }}
    card = chat._build_dna_digest_card(identity, run)
    assert card["any_failed"] is True
    assert "snag" in card["header"].lower() or "partial" in card["header"].lower()


def test_build_dna_digest_card_includes_proposed_patterns_section():
    """checklist C46e: proposed (not-yet-confirmed) channel_patterns rows
    surface in the digest, additive and optional."""
    identity = stamp_identity_write({}, {"voice_tone": "wry"}, learner="identity_builder")
    patterns = [
        {"id": "row-1", "pattern": "Weak openers underperform by 30%", "polarity": "anti",
         "source": "import_analysis", "evidence": {"metric": "vph", "delta_pct": -30.0, "cohort_size": 6}},
    ]
    card = chat._build_dna_digest_card(identity, {"learners": {}}, patterns=patterns)
    assert card["patterns"] == [{
        "id": "row-1", "pattern": "Weak openers underperform by 30%", "polarity": "anti",
        "source": "import_analysis", "evidence_summary": "vph: -30.0% vs. channel median (n=6)",
    }]


def test_build_dna_digest_card_omits_patterns_key_content_when_none_given():
    identity = stamp_identity_write({}, {"voice_tone": "wry"}, learner="identity_builder")
    card = chat._build_dna_digest_card(identity, {"learners": {}})
    assert card["patterns"] == []


def test_build_dna_digest_card_marks_revertable_only_when_history_has_a_prior_value():
    identity = stamp_identity_write({}, {"voice_tone": "confident"}, learner="identity_builder")
    identity = stamp_identity_write(identity, {"voice_tone": "overconfident"}, learner="identity_builder")
    card = chat._build_dna_digest_card(identity, {"learners": {}})
    voice_row = next(f for f in card["fields"] if f["field"] == "voice_tone")
    assert voice_row["revertable"] is True


def test_handle_show_channel_digest_no_identity_yet_is_a_friendly_reply(monkeypatch):
    async def fake_fetch_one(query, *args):
        return None

    async def fake_persist(*a, **k):
        pass

    monkeypatch.setattr(chat, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(chat, "_persist", fake_persist)

    state = {}
    resp = asyncio.run(chat._handle_show_channel_digest("conv-1", TENANT, [], state, "what did you learn?"))
    assert "haven't learned" in resp.assistant_text.lower()
    assert "pending_dna_digest" not in state


def test_handle_show_channel_digest_renders_card_and_arms_pending_state(monkeypatch):
    identity = stamp_identity_write({}, {"voice_tone": "x"}, learner="identity_builder")

    async def fake_fetch_one(query, *args):
        return {"channel_identity": json.dumps(identity)}

    async def fake_persist(*a, **k):
        pass

    monkeypatch.setattr(chat, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(chat, "_persist", fake_persist)

    state = {}
    resp = asyncio.run(chat._handle_show_channel_digest("conv-1", TENANT, [], state, "show digest"))
    assert resp.cards and resp.cards[0]["id"] == "channel_dna_digest"
    assert state["pending_dna_digest"] is True


# =============================================================================
# 6. routes/chat.py — _handle_dna_digest_action: keep / revert / correct
# =============================================================================

def test_dna_digest_action_keep_acknowledges_and_clears_pending(monkeypatch):
    async def fake_persist(*a, **k):
        pass
    monkeypatch.setattr(chat, "_persist", fake_persist)

    state = {"pending_dna_digest": True}
    resp = asyncio.run(chat._handle_dna_digest_action({"channel_dna_digest": "keep"}, "conv-1", TENANT, [], state))
    assert "keeping" in resp.assistant_text.lower()
    assert "pending_dna_digest" not in state


def test_dna_digest_action_revert_calls_channel_dna_revert_field(monkeypatch):
    calls = []

    async def fake_revert_field(tenant_id, field):
        calls.append((tenant_id, field))
        return True, f'Reverted "{field}" back to its previous value.'

    fake_channel_dna_mod = types.ModuleType("channel_dna")
    fake_channel_dna_mod.revert_field = fake_revert_field
    monkeypatch.setitem(sys.modules, "channel_dna", fake_channel_dna_mod)

    async def fake_persist(*a, **k):
        pass
    monkeypatch.setattr(chat, "_persist", fake_persist)

    state = {"pending_dna_digest": True}
    resp = asyncio.run(chat._handle_dna_digest_action(
        {"channel_dna_digest": "revert", "field": "voice_tone"}, "conv-1", TENANT, [], state,
    ))
    assert calls == [(TENANT, "voice_tone")]
    assert "reverted" in resp.assistant_text.lower()
    assert "pending_dna_digest" not in state


def test_dna_digest_action_revert_without_a_field_asks_which_one(monkeypatch):
    async def fake_persist(*a, **k):
        pass
    monkeypatch.setattr(chat, "_persist", fake_persist)

    resp = asyncio.run(chat._handle_dna_digest_action(
        {"channel_dna_digest": "revert"}, "conv-1", TENANT, [], {"pending_dna_digest": True},
    ))
    assert "which field" in resp.assistant_text.lower()


def test_dna_digest_action_correct_saves_a_channel_scope_preference(monkeypatch):
    calls = []

    async def fake_save_preference(tenant_id, text, scope="channel"):
        calls.append((tenant_id, text, scope))

    async def fake_persist(*a, **k):
        pass

    monkeypatch.setattr(chat, "_save_preference", fake_save_preference)
    monkeypatch.setattr(chat, "_persist", fake_persist)

    resp = asyncio.run(chat._handle_dna_digest_action(
        {"channel_dna_digest": "correct", "correction_text": "actually the voice is more playful"},
        "conv-1", TENANT, [], {"pending_dna_digest": True},
    ))
    assert calls == [(TENANT, "actually the voice is more playful", chat._PREF_SCOPE_CHANNEL)]
    assert "remember" in resp.assistant_text.lower()


def test_dna_digest_action_correct_without_text_asks_what_to_fix(monkeypatch):
    async def fake_persist(*a, **k):
        pass
    monkeypatch.setattr(chat, "_persist", fake_persist)

    resp = asyncio.run(chat._handle_dna_digest_action(
        {"channel_dna_digest": "correct", "correction_text": ""}, "conv-1", TENANT, [], {"pending_dna_digest": True},
    ))
    assert "what would you like" in resp.assistant_text.lower()


# =============================================================================
# 6b. routes/chat.py — _handle_dna_digest_action: confirm_pattern / retire_pattern
# (checklist C46e, OR-6 EXPANDED)
# =============================================================================

def test_dna_digest_action_confirm_pattern_calls_channel_patterns_confirm(monkeypatch):
    calls = []

    async def fake_confirm_pattern(tenant_id, pattern_id, *, confirmed_by=None):
        calls.append((tenant_id, pattern_id, confirmed_by))
        return {"id": pattern_id, "pattern": "Weak openers underperform", "polarity": "anti"}

    fake_mod = types.ModuleType("channel_patterns")
    fake_mod.confirm_pattern = fake_confirm_pattern
    monkeypatch.setitem(sys.modules, "channel_patterns", fake_mod)

    async def fake_persist(*a, **k):
        pass
    monkeypatch.setattr(chat, "_persist", fake_persist)

    resp = asyncio.run(chat._handle_dna_digest_action(
        {"channel_dna_digest": "confirm_pattern", "pattern_id": "row-1"}, "conv-1", TENANT, [], {"pending_dna_digest": True},
    ))
    assert calls == [(TENANT, "row-1", "chat")]
    assert "confirmed" in resp.assistant_text.lower()
    assert "style-seed" in resp.assistant_text.lower()  # anti polarity note


def test_dna_digest_action_confirm_pattern_good_polarity_has_no_exclusion_note(monkeypatch):
    async def fake_confirm_pattern(tenant_id, pattern_id, *, confirmed_by=None):
        return {"id": pattern_id, "pattern": "Testimony openers overperform", "polarity": "good"}

    fake_mod = types.ModuleType("channel_patterns")
    fake_mod.confirm_pattern = fake_confirm_pattern
    monkeypatch.setitem(sys.modules, "channel_patterns", fake_mod)

    async def fake_persist(*a, **k):
        pass
    monkeypatch.setattr(chat, "_persist", fake_persist)

    resp = asyncio.run(chat._handle_dna_digest_action(
        {"channel_dna_digest": "confirm_pattern", "pattern_id": "row-2"}, "conv-1", TENANT, [], {"pending_dna_digest": True},
    ))
    assert "confirmed" in resp.assistant_text.lower()
    assert "style-seed" not in resp.assistant_text.lower()


def test_dna_digest_action_retire_pattern_calls_channel_patterns_retire(monkeypatch):
    calls = []

    async def fake_retire_pattern(tenant_id, pattern_id, *, confirmed_by=None):
        calls.append((tenant_id, pattern_id, confirmed_by))
        return {"id": pattern_id, "pattern": "Weak openers underperform", "polarity": "anti"}

    fake_mod = types.ModuleType("channel_patterns")
    fake_mod.retire_pattern = fake_retire_pattern
    monkeypatch.setitem(sys.modules, "channel_patterns", fake_mod)

    async def fake_persist(*a, **k):
        pass
    monkeypatch.setattr(chat, "_persist", fake_persist)

    resp = asyncio.run(chat._handle_dna_digest_action(
        {"channel_dna_digest": "retire_pattern", "pattern_id": "row-1"}, "conv-1", TENANT, [], {"pending_dna_digest": True},
    ))
    assert calls == [(TENANT, "row-1", "chat")]
    assert "retired" in resp.assistant_text.lower()


def test_dna_digest_action_confirm_pattern_without_id_asks_which_one(monkeypatch):
    async def fake_persist(*a, **k):
        pass
    monkeypatch.setattr(chat, "_persist", fake_persist)

    resp = asyncio.run(chat._handle_dna_digest_action(
        {"channel_dna_digest": "confirm_pattern"}, "conv-1", TENANT, [], {"pending_dna_digest": True},
    ))
    assert "which pattern" in resp.assistant_text.lower()


def test_dna_digest_action_confirm_pattern_not_found_is_friendly(monkeypatch):
    async def fake_confirm_pattern(tenant_id, pattern_id, *, confirmed_by=None):
        return None

    fake_mod = types.ModuleType("channel_patterns")
    fake_mod.confirm_pattern = fake_confirm_pattern
    monkeypatch.setitem(sys.modules, "channel_patterns", fake_mod)

    async def fake_persist(*a, **k):
        pass
    monkeypatch.setattr(chat, "_persist", fake_persist)

    resp = asyncio.run(chat._handle_dna_digest_action(
        {"channel_dna_digest": "confirm_pattern", "pattern_id": "missing"}, "conv-1", TENANT, [], {"pending_dna_digest": True},
    ))
    assert "couldn't find" in resp.assistant_text.lower()


def test_dna_digest_action_confirm_pattern_error_is_friendly_not_a_crash(monkeypatch):
    async def boom(tenant_id, pattern_id, *, confirmed_by=None):
        raise RuntimeError("db blip")

    fake_mod = types.ModuleType("channel_patterns")
    fake_mod.confirm_pattern = boom
    monkeypatch.setitem(sys.modules, "channel_patterns", fake_mod)

    async def fake_persist(*a, **k):
        pass
    monkeypatch.setattr(chat, "_persist", fake_persist)

    resp = asyncio.run(chat._handle_dna_digest_action(
        {"channel_dna_digest": "confirm_pattern", "pattern_id": "row-1"}, "conv-1", TENANT, [], {"pending_dna_digest": True},
    ))
    assert "snag" in resp.assistant_text.lower()


# =============================================================================
# 7. Source-lock: chat_turn dispatches C42 BEFORE producer intake / 3.5
# =============================================================================

def test_chat_turn_dispatches_learn_channel_and_digest_before_identity_only_path():
    src = inspect.getsource(chat.chat_turn)
    assert "_learn_channel_intent(msg_stripped)" in src
    assert "_handle_learn_channel(" in src
    assert "_dna_digest_intent(msg_stripped)" in src
    assert "_handle_show_channel_digest(" in src
    assert '"channel_dna_digest" in body.selections' in src
    assert 'state.get("pending_dna_digest")' in src
    # 3.4/3.6b must appear before 3.5's _identity_intent dispatch, so the
    # broader "learn my channel's voice" ask never gets routed to the
    # single-learner identity_builder-only path.
    assert src.index("_learn_channel_intent(msg_stripped)") < src.index("_identity_intent(body.message)")
    assert src.index("_handle_dna_digest_action(") < src.index("user_parts: list[str] = []")


# =============================================================================
# 8. routes/channel_dna.py — the thin HTTP door reuses the SAME callable
# =============================================================================

def test_thin_route_learn_reuses_the_exact_same_learn_channel_callable():
    assert channel_dna_route.learn_channel is channel_dna.learn_channel


def test_thin_route_start_learn_acks_and_backgrounds_the_work(monkeypatch):
    async def fake_is_learning(tenant_id):
        return False

    seen = {}

    async def fake_learn_channel(tenant_id, channel_url=None, example_script_text=None, reference_video_url=None):
        seen["called"] = (tenant_id, channel_url, example_script_text, reference_video_url)
        return {}

    monkeypatch.setattr(channel_dna_route, "is_learning", fake_is_learning)
    monkeypatch.setattr(channel_dna_route, "learn_channel", fake_learn_channel)

    calls = []

    class FakeBackgroundTasks:
        def add_task(self, fn):
            calls.append(fn)

    resp = asyncio.run(channel_dna_route.start_learn_channel(
        channel_dna_route.LearnChannelRequest(channel_url="https://youtube.com/@X"),
        FakeBackgroundTasks(),
        tenant_id=TENANT,
    ))
    assert resp.started is True
    assert resp.busy is False
    assert "$0.10-0.30" in resp.message
    assert len(calls) == 1
    asyncio.run(calls[0]())
    assert seen["called"] == (TENANT, "https://youtube.com/@X", None, None)


def test_thin_route_start_learn_reports_busy_without_scheduling_a_second_run(monkeypatch):
    async def fake_is_learning(tenant_id):
        return True

    async def boom_learn_channel(*a, **k):
        raise AssertionError("must not start a second run while one is already learning")

    monkeypatch.setattr(channel_dna_route, "is_learning", fake_is_learning)
    monkeypatch.setattr(channel_dna_route, "learn_channel", boom_learn_channel)

    calls = []

    class FakeBackgroundTasks:
        def add_task(self, fn):
            calls.append(fn)

    resp = asyncio.run(channel_dna_route.start_learn_channel(
        channel_dna_route.LearnChannelRequest(), FakeBackgroundTasks(), tenant_id=TENANT,
    ))
    assert resp.started is False
    assert resp.busy is True
    assert calls == []


def test_thin_route_status_reads_the_persisted_last_run(monkeypatch):
    identity = stamp_identity_write({}, {"voice_tone": "x"}, learner="identity_builder")
    identity = stamp_last_run(identity, {"at": "2026-07-19T00:00:00+00:00", "ok": True,
                                          "learners": {"identity_builder": {"status": "learned"}}})

    async def fake_is_learning(tenant_id):
        return False

    async def fake_current_identity(tenant_id):
        return identity

    monkeypatch.setattr(channel_dna_route, "is_learning", fake_is_learning)
    monkeypatch.setattr(channel_dna_route, "_current_identity", fake_current_identity)

    resp = asyncio.run(channel_dna_route.get_learn_channel_status(tenant_id=TENANT))
    assert resp.learning is False
    assert resp.ok is True
    assert resp.at == "2026-07-19T00:00:00+00:00"
    assert resp.learners == {"identity_builder": {"status": "learned"}}
    assert resp.identity["voice_tone"] == "x"


def test_thin_route_status_no_prior_run_is_empty_not_broken(monkeypatch):
    async def fake_is_learning(tenant_id):
        return False

    async def fake_current_identity(tenant_id):
        return {}

    monkeypatch.setattr(channel_dna_route, "is_learning", fake_is_learning)
    monkeypatch.setattr(channel_dna_route, "_current_identity", fake_current_identity)

    resp = asyncio.run(channel_dna_route.get_learn_channel_status(tenant_id=TENANT))
    assert resp.ok is None
    assert resp.learners == {}
    assert resp.identity == {}
