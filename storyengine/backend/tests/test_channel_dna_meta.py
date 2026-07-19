"""Tests for channel_dna_meta.py — the provenance envelope (checklist C40)
shared by every writer of `channel_profiles.channel_identity`.

Covers the pure helper (stamp_identity_write / field_provenance /
restore_field / coerce_identity) plus, per real writer
(identity_builder.build_channel_identity, channel_format.set_channel_format,
pipeline_executor._run_channel_formula_thumbnail's thumbnail_blueprint
cache), a monkeypatched-DB test proving THAT writer's merge survives another
writer's fields and the envelope itself. Also pins the reader side: an
envelope-carrying identity must produce a byte-identical IdentityContext to
the same identity without the envelope (identity.py never even selects the
column, but `build_identity_context_from_rows` ignoring unknown dict keys is
the general "readers stay clean" guarantee — proven directly here).

No live DB, no network. Run:
  cd storyengine/backend && ./venv/bin/python -m pytest tests/test_channel_dna_meta.py -q
"""
import asyncio
import copy
import json

import pytest

from channel_dna_meta import (
    HISTORY_LIMIT,
    coerce_identity,
    field_provenance,
    restore_field,
    stamp_identity_write,
)


# ---------------------------------------------------------------------------
# coerce_identity
# ---------------------------------------------------------------------------

def test_coerce_identity_handles_dict_string_and_junk():
    assert coerce_identity({"a": 1}) == {"a": 1}
    assert coerce_identity('{"a": 1}') == {"a": 1}
    assert coerce_identity(None) == {}
    assert coerce_identity("") == {}
    assert coerce_identity("not json") == {}
    assert coerce_identity([1, 2, 3]) == {}


# ---------------------------------------------------------------------------
# stamp_identity_write — core merge semantics
# ---------------------------------------------------------------------------

def test_stamp_on_write_records_source_and_history():
    identity = {"voice_tone": "old tone"}
    out = stamp_identity_write(identity, {"voice_tone": "new tone"}, learner="identity_builder", confidence=0.8)

    assert out["voice_tone"] == "new tone"
    prov = field_provenance(out, "voice_tone")
    assert prov["learner"] == "identity_builder"
    assert prov["confidence"] == 0.8
    assert prov["at"]  # non-empty ISO timestamp

    assert len(out["_history"]) == 1
    entry = out["_history"][0]
    assert entry["learner"] == "identity_builder"
    assert entry["fields_changed"] == ["voice_tone"]
    assert entry["previous"] == {"voice_tone": "old tone"}


def test_unrelated_fields_and_envelope_survive_a_different_writers_update():
    """The scenario the whole chunk exists for: identity_builder rebuilds
    voice/hook fields; channel_format's visual_format + format_locked (a
    DIFFERENT writer's fields) and the existing envelope must not be
    clobbered."""
    identity = stamp_identity_write(
        {}, {"visual_format": {"style": "3D"}, "format_locked": True}, learner="channel_format"
    )
    rebuilt = stamp_identity_write(
        identity, {"voice_tone": "confident", "hook_style": "cold open"}, learner="identity_builder"
    )

    # channel_format's fields untouched
    assert rebuilt["visual_format"] == {"style": "3D"}
    assert rebuilt["format_locked"] is True
    assert field_provenance(rebuilt, "visual_format")["learner"] == "channel_format"

    # identity_builder's new fields present with correct provenance
    assert rebuilt["voice_tone"] == "confident"
    assert field_provenance(rebuilt, "hook_style")["learner"] == "identity_builder"

    # both writers' history entries survive, in order
    assert [h["learner"] for h in rebuilt["_history"]] == ["channel_format", "identity_builder"]


def test_stamp_never_mutates_input_dict():
    identity = {"voice_tone": "old"}
    snapshot = copy.deepcopy(identity)
    stamp_identity_write(identity, {"voice_tone": "new"}, learner="x")
    assert identity == snapshot


def test_fields_dict_cannot_smuggle_envelope_keys():
    identity = stamp_identity_write({}, {"voice_tone": "a"}, learner="identity_builder")
    poisoned = stamp_identity_write(
        identity, {"_sources": {"fake": "injected"}, "_history": ["fake"], "cadence": "b"}, learner="attacker"
    )
    # The attempted envelope keys inside `fields` are ignored — only real
    # fields (cadence) get merged and stamped.
    assert poisoned["cadence"] == "b"
    assert poisoned["_sources"]["fake"] != "injected" if "fake" in poisoned["_sources"] else True
    assert "fake" not in poisoned["_sources"]
    assert poisoned["_history"][-1]["learner"] == "attacker"
    assert poisoned["_history"][-1]["fields_changed"] == ["cadence"]


def test_resaving_identical_value_stamps_source_but_not_history():
    """A learner re-confirming the same value is provenance-worthy (fresh
    timestamp) but must not spam history with a no-op change."""
    identity = stamp_identity_write({}, {"voice_tone": "confident"}, learner="identity_builder")
    again = stamp_identity_write(identity, {"voice_tone": "confident"}, learner="identity_builder")

    assert len(again["_history"]) == 1  # no new entry — nothing changed
    assert field_provenance(again, "voice_tone")["at"] >= field_provenance(identity, "voice_tone")["at"]


def test_history_is_bounded_to_history_limit():
    identity = {}
    for i in range(HISTORY_LIMIT + 10):
        identity = stamp_identity_write(identity, {"voice_tone": f"v{i}"}, learner="identity_builder")
    assert len(identity["_history"]) == HISTORY_LIMIT
    # newest entry reflects the LAST write, oldest ones were dropped
    assert identity["_history"][-1]["previous"]["voice_tone"] == f"v{HISTORY_LIMIT + 8}"


def test_full_identity_builder_shaped_write_stamps_all_its_fields():
    """A realistic full rebuild (the actual keys identity_builder.py
    produces) stamps every one of them with the same learner/timestamp."""
    identity_payload = {
        "voice_tone": "wry, understated",
        "cadence": "short declaratives, then a long unwind",
        "hook_style": "cold statistic, no preamble",
        "structure": "hook -> context -> reveal -> verdict",
        "research_approach": {"sources": "primary docs", "depth": "deep"},
        "real_quotes": ["the numbers don't lie"],
        "signature_phrases": ["and here's the kicker"],
        "visual_format": {"style": "static", "motion": "ken burns"},
        "thumbnail_style": {"layout": "left subject, right text"},
        "style_description": "a 200 word paragraph...",
    }
    out = stamp_identity_write({}, identity_payload, learner="identity_builder", confidence=None)
    for key in identity_payload:
        prov = field_provenance(out, key)
        assert prov is not None, f"{key} was not stamped"
        assert prov["learner"] == "identity_builder"
    assert len(out["_history"]) == 1
    assert set(out["_history"][0]["fields_changed"]) == set(identity_payload.keys())


# ---------------------------------------------------------------------------
# field_provenance
# ---------------------------------------------------------------------------

def test_field_provenance_none_when_never_stamped():
    assert field_provenance({}, "voice_tone") is None
    assert field_provenance(None, "voice_tone") is None
    assert field_provenance({"voice_tone": "x"}, "voice_tone") is None  # no envelope at all


# ---------------------------------------------------------------------------
# restore_field
# ---------------------------------------------------------------------------

def test_restore_field_reverts_to_previous_value_and_is_itself_stamped():
    v1 = stamp_identity_write({}, {"voice_tone": "confident"}, learner="identity_builder")
    v2 = stamp_identity_write(v1, {"voice_tone": "overconfident"}, learner="identity_builder")

    restored = restore_field(v2, "voice_tone", history_index=1)  # the v1->v2 change
    assert restored["voice_tone"] == "confident"
    assert field_provenance(restored, "voice_tone")["learner"] == "restore"
    assert restored["_history"][-1]["fields_changed"] == ["voice_tone"]
    assert restored["_history"][-1]["previous"]["voice_tone"] == "overconfident"


def test_restore_field_out_of_range_raises():
    identity = stamp_identity_write({}, {"voice_tone": "a"}, learner="x")
    with pytest.raises(ValueError):
        restore_field(identity, "voice_tone", history_index=5)
    with pytest.raises(ValueError):
        restore_field(identity, "voice_tone", history_index=-1)


def test_restore_field_wrong_field_raises():
    identity = stamp_identity_write({}, {"voice_tone": "a"}, learner="x")
    with pytest.raises(ValueError):
        restore_field(identity, "cadence", history_index=0)  # that entry never touched cadence


def test_restore_field_to_previously_absent_sets_none():
    v1 = stamp_identity_write({}, {"cadence": "brand new"}, learner="identity_builder")
    restored = restore_field(v1, "cadence", history_index=0)
    assert restored["cadence"] is None


# ---------------------------------------------------------------------------
# Reader byte-identity — identity.py must ignore underscore-prefixed keys
# ---------------------------------------------------------------------------

def test_identity_context_byte_identical_with_and_without_envelope():
    """identity.py's build_identity_context_from_rows plucks specific known
    keys (channel_name, niche, target_audience, style_description,
    frameworks) off the `profile` row rather than iterating it — so an
    envelope living in a DIFFERENT dict (channel_identity, which this
    function's SQL doesn't even SELECT) or stray extra keys on the same row
    can never change its output. Pinned here so a future refactor that
    starts iterating the row can't silently start leaking _sources/_history."""
    from identity import build_identity_context_from_rows

    profile_plain = {
        "channel_name": "Calm Coding",
        "niche": "beginner programming tutorials",
        "target_audience": "self-taught developers",
        "style_description": "patient, encouraging, jargon-free",
        "frameworks": ["the 3-act explainer"],
    }
    envelope = stamp_identity_write(
        {}, {"voice_tone": "patient"}, learner="identity_builder", confidence=0.9
    )
    profile_with_envelope = dict(profile_plain)
    profile_with_envelope["channel_identity"] = envelope  # extra key a wider SELECT * might add

    idc_plain = build_identity_context_from_rows(project=None, profile=profile_plain, video=None)
    idc_with_envelope = build_identity_context_from_rows(project=None, profile=profile_with_envelope, video=None)

    assert idc_plain == idc_with_envelope


# ---------------------------------------------------------------------------
# Per-writer merge tests (monkeypatched DB, no live DB/network)
# ---------------------------------------------------------------------------

def _fake_row_db(initial_channel_identity):
    """A tiny single-tenant fake channel_profiles row keyed on tenant_id,
    supporting the exact fetch_one/execute call shapes each writer uses."""
    state = {"tenant-1": {"channel_identity": initial_channel_identity}}
    calls = []

    async def fake_fetch_one(query, *args):
        calls.append(("fetch_one", query, args))
        q = " ".join(query.split())
        if "channel_identity" in q and "FROM channel_profiles" in q and args:
            tenant_id = args[0]
            row = state.get(tenant_id)
            if row is None:
                return None
            if "->>'thumbnail_blueprint'" in q:
                ci = coerce_identity(row["channel_identity"])
                bp = ci.get("thumbnail_blueprint")
                return {"bp": bp} if bp else {"bp": None}
            return {"channel_identity": row["channel_identity"]}
        return None

    async def fake_execute(query, *args):
        calls.append(("execute", query, args))
        q = " ".join(query.split())
        if "channel_identity" in q:
            tenant_id = args[0]
            # every writer's final positional arg is the JSON payload
            payload = args[-1]
            state.setdefault(tenant_id, {})["channel_identity"] = payload
        return None

    return state, calls, fake_fetch_one, fake_execute


def test_identity_builder_write_merges_through_helper(monkeypatch):
    """identity_builder.build_channel_identity used to do a BLIND overwrite
    (`channel_identity = $3`). Prove the migrated version merges: a prior
    channel_format visual_format/format_locked (and its provenance) survives
    a full identity rebuild."""
    import identity_builder as ib

    prior = stamp_identity_write(
        {}, {"visual_format": {"style": "3D"}, "format_locked": True}, learner="channel_format"
    )
    state, calls, fake_fetch_one, fake_execute = _fake_row_db(json.dumps(prior))
    monkeypatch.setattr(ib, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(ib, "execute", fake_execute)

    async def fake_ranked_videos(tenant_id, limit):
        return [{"video_id": "v1", "title": "Ep 1", "view_count": 100,
                  "thumbnail_url": None, "duration_seconds": 300}]

    async def fake_firecrawl(video_id):
        return "This is the real transcript. It has enough content to quote from directly here."

    async def fake_get_text_client_for_tenant(tenant_id):
        class _C:
            async def generate(self, **kw):
                return json.dumps({
                    "voice_tone": "confident",
                    "cadence": "short bursts",
                    "hook_style": "cold open",
                    "structure": "hook then reveal",
                    "style_description": "a paragraph of guidance",
                })
        return _C()

    monkeypatch.setattr(ib, "_ranked_videos", fake_ranked_videos)
    monkeypatch.setattr(ib, "_firecrawl_transcript", fake_firecrawl)
    monkeypatch.setattr(ib, "_thumbnail_style", lambda *a, **k: _async_none())

    # build_channel_identity does `from kie_unified import get_text_client_for_tenant`
    # LOCALLY (inside the function), so stubbing sys.modules before the call is
    # enough to intercept it without ever touching the real module/network.
    import sys, types
    fake_mod = types.ModuleType("kie_unified")
    fake_mod.get_text_client_for_tenant = fake_get_text_client_for_tenant
    monkeypatch.setitem(sys.modules, "kie_unified", fake_mod)
    monkeypatch.setattr(ib, "claude_model_for_direct_client", lambda c: None)

    result = asyncio.run(ib.build_channel_identity("tenant-1", top_n=1))
    assert result["ok"] is True

    final = coerce_identity(state["tenant-1"]["channel_identity"])
    # identity_builder's own new fields present
    assert final["voice_tone"] == "confident"
    assert field_provenance(final, "voice_tone")["learner"] == "identity_builder"
    # channel_format's fields from BEFORE the rebuild survive untouched
    assert final["visual_format"] == {"style": "3D"}
    assert final["format_locked"] is True
    assert field_provenance(final, "visual_format")["learner"] == "channel_format"
    # both writers' history entries present
    assert "channel_format" in [h["learner"] for h in final["_history"]]
    assert "identity_builder" in [h["learner"] for h in final["_history"]]


async def _async_none():
    return None


def test_channel_format_write_merges_through_helper(monkeypatch):
    """channel_format.set_channel_format used a SQL `||` merge (fine for its
    own fields but blind to the envelope). Prove the migrated version
    preserves a prior identity_builder field + provenance while adding its
    own visual_format/format_locked."""
    import channel_format as cf

    prior = stamp_identity_write({}, {"voice_tone": "confident"}, learner="identity_builder")
    state, calls, fake_fetch_one, fake_execute = _fake_row_db(json.dumps(prior))
    monkeypatch.setattr(cf, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(cf, "execute", fake_execute)

    fmt = asyncio.run(cf.set_channel_format("tenant-1", {"style": "anime", "motion": "animated"}))
    assert fmt["style"] == "anime"

    final = coerce_identity(state["tenant-1"]["channel_identity"])
    # identity_builder's field survives
    assert final["voice_tone"] == "confident"
    assert field_provenance(final, "voice_tone")["learner"] == "identity_builder"
    # channel_format's own fields present with correct provenance
    assert final["visual_format"]["style"] == "anime"
    assert final["format_locked"] is True
    assert field_provenance(final, "format_locked")["learner"] == "channel_format"


def test_channel_format_no_prior_row_still_locks_format(monkeypatch):
    """A tenant with no channel_profiles row yet (INSERT branch) still gets a
    clean, stamped visual_format."""
    import channel_format as cf

    calls = []

    async def fake_fetch_one(query, *args):
        calls.append(args)
        return None  # no row yet

    async def fake_execute(query, *args):
        calls.append(args)
        return None

    monkeypatch.setattr(cf, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(cf, "execute", fake_execute)

    fmt = asyncio.run(cf.set_channel_format("tenant-2", {"style": "watercolor"}))
    assert fmt["style"] == "watercolor"


def test_get_channel_format_ignores_envelope_keys(monkeypatch):
    """channel_format.get_channel_format must never surface _sources/_history
    as if they were visual_format content."""
    import channel_format as cf

    identity = stamp_identity_write(
        {}, {"visual_format": {"style": "anime"}, "format_locked": True}, learner="channel_format"
    )

    async def fake_fetch_one(query, *args):
        return {"channel_identity": json.dumps(identity)}

    monkeypatch.setattr(cf, "fetch_one", fake_fetch_one)
    fmt, locked = asyncio.run(cf.get_channel_format("tenant-1"))
    assert fmt == {"style": "anime"}
    assert locked is True
    assert "_sources" not in fmt
    assert "_history" not in fmt


def test_thumbnail_blueprint_cache_merges_through_helper(monkeypatch):
    """pipeline_executor's third writer (_cache_channel_thumbnail_blueprint,
    extracted to module level so it's unit-testable) used the same kind of
    SQL `||` merge as channel_format's old code — blind to the envelope.
    Prove the migrated version preserves identity_builder's + channel_format's
    prior fields and provenance while stamping its own thumbnail_blueprint."""
    import pipeline_executor as pe

    prior = stamp_identity_write({}, {"voice_tone": "confident"}, learner="identity_builder")
    prior = stamp_identity_write(
        prior, {"visual_format": {"style": "3D"}, "format_locked": True}, learner="channel_format"
    )
    state, calls, fake_fetch_one, fake_execute = _fake_row_db(json.dumps(prior))
    monkeypatch.setattr(pe, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pe, "execute", fake_execute)

    asyncio.run(pe._cache_channel_thumbnail_blueprint("tenant-1", '{"layout": "left subject"}'))

    final = coerce_identity(state["tenant-1"]["channel_identity"])
    assert final["thumbnail_blueprint"] == '{"layout": "left subject"}'
    assert field_provenance(final, "thumbnail_blueprint")["learner"] == "thumbnail_formula"
    # identity_builder's + channel_format's fields and provenance survive
    assert final["voice_tone"] == "confident"
    assert field_provenance(final, "voice_tone")["learner"] == "identity_builder"
    assert final["visual_format"] == {"style": "3D"}
    assert field_provenance(final, "format_locked")["learner"] == "channel_format"
    assert [h["learner"] for h in final["_history"]] == [
        "identity_builder", "channel_format", "thumbnail_formula",
    ]
