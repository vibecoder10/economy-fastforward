"""D7-7 — the S6 gap D7-6 left open: an externally-submitted or
user-pasted script never flagged the existing cast/environments stale.

D7-2 wired ``_flag_stale_cast_and_environments`` (routes/videos.py) into
every writer that funnels through ``sync_video_script``, plus the two other
inline direct-writers that bypass it (pipeline_executor's
``_save_machine_script_block``, custom_film_production_runner's
``_script`` — see tests/functional/test_d7_2_staleness_hash.py). It missed a
THIRD family: user_script.py's two doors, ``set_user_script`` (the creator-
verbatim "use this script" path) and ``accept_external_script`` (C46d's
agent/MCP-submitted path, the exact door D6-6a's dry-run gate exercises via
``submit_script``). Both write ``videos.script`` directly — never through
``sync_video_script`` — so a script installed through either door left a
prior cast/environment set looking un-stale even though it was generated
from a script version this text just replaced.

D7-7 adds an explicit call to the same ``_flag_stale_cast_and_environments``
helper at the end of both writers, after their scene rows and
``videos.script`` are fully settled. Advisory-only: the helper's own
try/except already swallows any failure (including hitting the real, unset
DATABASE_URL when a test doesn't monkeypatch routes.videos's DB functions)
and never raises — proven below by NOT patching routes.videos for the
"failure must not block the save" case.

Also resolves the coverage-hash question D7-7's brief raised: both doors
already ``DELETE FROM scripts`` then re-``INSERT`` every row on every call,
and the fresh ``INSERT`` never sets ``coverage_directive_hash`` — so it
starts NULL on the new rows regardless. There is no stale hash surviving
onto a replacement scene row to separately clear (see
test_replace_wipes_coverage_directive_hash_via_delete_insert below, which
proves the DELETE+INSERT shape rather than asserting a no-op).

STASH-PROOF: with the ``_flag_stale_cast_and_environments`` call removed
from either writer (or the function itself neutered to a no-op),
test_set_user_script_flips_both_statuses_to_stale and
test_accept_external_script_flips_both_statuses_to_stale fail real
assertions (status stays 'approved' instead of flipping to 'stale') — not
import/collection-time errors.

Local/no-spend: every DB call is a fake execute/fetch_one dispatched by
query text, same convention as test_d7_2_staleness_hash.py and
tests/test_c46d_trust_boundaries.py. accept_external_script's Claude critic
call is a fake client returning a canned 'pass' verdict.

Run: cd storyengine/backend && ./venv/bin/python -m pytest \
    tests/functional/test_d7_7_external_stale.py -q
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

VIDEO_PIPELINE = Path(__file__).parents[4] / "skills" / "video-pipeline"
if str(VIDEO_PIPELINE) not in sys.path:
    sys.path.insert(0, str(VIDEO_PIPELINE))

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import user_script  # noqa: E402
import routes.videos as rv  # noqa: E402
import kie_unified  # noqa: E402
import identity  # noqa: E402
import quality_rules  # noqa: E402
import dialogue_intelligence  # noqa: E402

VIDEO_ID = "video-ext-1"
TENANT_ID = "tenant-ext"
OLD_TEXT = "The old paragraph about a lighthouse keeper, long enough to be its own scene."


def _hash(text: str) -> str:
    return hashlib.sha1(" ".join((text or "").split()).encode()).hexdigest()


def _video_row(**overrides):
    row = {
        "id": VIDEO_ID, "tenant_id": TENANT_ID, "video_title": "External Stale Test",
        "status": "ready_for_scripting", "executive_hook": None, "hook_script": None,
    }
    row.update(overrides)
    return row


def _make_shared_fake_db(*, characters_hash=None, environments_hash=None):
    """One fake DB shared across user_script's OWN fetch_one/execute bindings
    and routes.videos's (the flag helper reads/writes through rv.fetch_one/
    rv.execute — a SEPARATE module-level name binding from user_script's own,
    even though both originally came from `database.py`), so a call to
    _flag_stale_cast_and_environments triggered from inside user_script.py
    actually observes the same state the writer just committed."""
    state = {
        "videos_script": OLD_TEXT,
        "script_source": None,
        "characters_hash": characters_hash,
        "environments_hash": environments_hash,
        "video_characters_status": "approved",
        "video_environments_status": "approved",
    }
    writes = []

    async def fake_fetch_one(query, *args):
        q = query.strip()
        if "characters_hash, environments_hash FROM videos" in q:
            # The flag helper's own read — must see whatever this writer
            # already committed to videos.script.
            return {
                "script": state["videos_script"],
                "characters_hash": state["characters_hash"],
                "environments_hash": state["environments_hash"],
            }
        if "FROM videos WHERE id = $1 AND tenant_id = $2" in q:
            # set_user_script / accept_external_script's own video lookup.
            vid, tenant = args[0], args[1]
            if vid == VIDEO_ID and tenant == TENANT_ID:
                return _video_row()
            return None
        return None

    async def fake_execute(query, *args):
        writes.append((query, args))
        q = query.strip()
        if q.startswith("UPDATE videos SET script = $1, script_source = 'user_supplied'"):
            full_script, _validation_json, _status, _vid, _tenant = args
            state["videos_script"] = full_script
            state["script_source"] = "user_supplied"
            return "UPDATE 1"
        if q.startswith("UPDATE videos SET script = $1, script_source = $2"):
            full_text, source, _validation_json, _status, _vid, _tenant = args
            state["videos_script"] = full_text
            state["script_source"] = source
            return "UPDATE 1"
        if q.startswith("UPDATE video_characters SET status = 'stale'"):
            state["video_characters_status"] = "stale"
            return "UPDATE 1"
        if q.startswith("UPDATE video_environments SET status = 'stale'"):
            state["video_environments_status"] = "stale"
            return "UPDATE 1"
        return "UPDATE 1"

    return state, writes, fake_fetch_one, fake_execute


# ---------------------------------------------------------------------------
# 1. set_user_script — the creator-verbatim door
# ---------------------------------------------------------------------------

def test_set_user_script_flips_both_statuses_to_stale(monkeypatch):
    state, writes, fake_fetch_one, fake_execute = _make_shared_fake_db(
        characters_hash=_hash(OLD_TEXT), environments_hash=_hash(OLD_TEXT),
    )

    async def fake_tag(*_a, **_kw):
        return {}

    monkeypatch.setattr(user_script, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(user_script, "execute", fake_execute)
    monkeypatch.setattr(rv, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(rv, "execute", fake_execute)
    monkeypatch.setattr(dialogue_intelligence, "tag_video_dialogue", fake_tag, raising=False)

    new_text = (
        "A submarine captain named Vasquez discovers the reactor is failing, "
        "a whole paragraph long enough to form its own scene."
    )
    result = asyncio.run(user_script.set_user_script(TENANT_ID, VIDEO_ID, new_text))

    assert result["scenes"] >= 1
    assert new_text in state["videos_script"]
    assert state["video_characters_status"] == "stale"
    assert state["video_environments_status"] == "stale"
    assert not any(q.strip().startswith("DELETE FROM video_characters") for q, _ in writes)
    assert not any(q.strip().startswith("DELETE FROM video_environments") for q, _ in writes)


def test_set_user_script_no_op_when_hash_already_matches(monkeypatch):
    """The stamped hash already matches the new text (e.g. a no-op resave) —
    nothing should flip."""
    new_text = "Exactly the text the cast/environments were already stamped against."
    state, writes, fake_fetch_one, fake_execute = _make_shared_fake_db(
        characters_hash=_hash(new_text), environments_hash=_hash(new_text),
    )

    async def fake_tag(*_a, **_kw):
        return {}

    monkeypatch.setattr(user_script, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(user_script, "execute", fake_execute)
    monkeypatch.setattr(rv, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(rv, "execute", fake_execute)
    monkeypatch.setattr(dialogue_intelligence, "tag_video_dialogue", fake_tag, raising=False)

    asyncio.run(user_script.set_user_script(TENANT_ID, VIDEO_ID, new_text))

    assert state["video_characters_status"] == "approved"
    assert state["video_environments_status"] == "approved"


def test_set_user_script_flag_failure_never_blocks_the_save(monkeypatch):
    """routes.videos is NOT monkeypatched here at all — the flag helper's own
    fetch_one hits the real (unset in this test env) DATABASE_URL, raises
    inside its own try/except, and must never propagate. The save (via
    user_script's OWN fetch_one/execute, which ARE patched) must still
    succeed exactly as it would have before D7-7."""
    writes = []

    async def fake_fetch_one(query, *args):
        return _video_row()

    async def fake_execute(query, *args):
        writes.append((query, args))
        return "UPDATE 1"

    async def fake_tag(*_a, **_kw):
        return {}

    monkeypatch.setattr(user_script, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(user_script, "execute", fake_execute)
    monkeypatch.setattr(dialogue_intelligence, "tag_video_dialogue", fake_tag, raising=False)

    result = asyncio.run(user_script.set_user_script(
        TENANT_ID, VIDEO_ID,
        "A perfectly fine creator paragraph, long enough to form its own scene on its own.",
    ))

    assert result["scenes"] >= 1
    assert any(w[0].strip().startswith("UPDATE videos SET script") for w in writes)


# ---------------------------------------------------------------------------
# 2. accept_external_script — the agent/MCP-submitted door (C46d, D6-6a's
#    submit_script exercises this exact function)
# ---------------------------------------------------------------------------

class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    async def generate(self, **kwargs):
        self.calls += 1
        return self.response


def _pass_json():
    return json.dumps({
        "verdict": "pass", "score": 92, "failing_gates": [],
        "rewrite_guidance": "", "rule_verdicts": [],
    })


def _scenes(*texts):
    return [{"scene": i + 1, "text": t, "location": "the bridge"} for i, t in enumerate(texts)]


def _wire_external(monkeypatch, fake_fetch_one, fake_execute):
    client = _FakeClient(_pass_json())

    async def fake_get_client(_tenant_id):
        return client

    async def fake_build_identity(_tenant_id, _video):
        return type("FakeIdentity", (), {"niche": "test-niche"})()

    async def fake_list_all_rules(_tenant_id, *, active_only=False):
        return []

    async def fake_tag(_video_id, _tenant_id):
        return None

    monkeypatch.setattr(user_script, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(user_script, "execute", fake_execute)
    monkeypatch.setattr(kie_unified, "get_text_client_for_tenant", fake_get_client)
    monkeypatch.setattr(identity, "build_identity_context", fake_build_identity)
    monkeypatch.setattr(quality_rules, "list_all_rules", fake_list_all_rules)
    monkeypatch.setattr(dialogue_intelligence, "tag_video_dialogue", fake_tag, raising=False)
    return client


def test_accept_external_script_flips_both_statuses_to_stale(monkeypatch):
    state, writes, fake_fetch_one, fake_execute = _make_shared_fake_db(
        characters_hash=_hash(OLD_TEXT), environments_hash=_hash(OLD_TEXT),
    )
    _wire_external(monkeypatch, fake_fetch_one, fake_execute)
    monkeypatch.setattr(rv, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(rv, "execute", fake_execute)

    new_text = "A whole new bridge scene the submitting agent wrote from scratch."
    result = asyncio.run(user_script.accept_external_script(
        TENANT_ID, VIDEO_ID, _scenes(new_text), source="agent_submitted",
    ))

    assert result["accepted"] is True
    assert new_text in state["videos_script"]
    assert state["script_source"] == "agent_submitted"
    assert state["video_characters_status"] == "stale"
    assert state["video_environments_status"] == "stale"


def test_accept_external_script_rejected_submission_never_flags(monkeypatch):
    """A rejected submission touches nothing — including the staleness
    flag, since nothing was actually saved."""
    state, writes, fake_fetch_one, fake_execute = _make_shared_fake_db(
        characters_hash=_hash(OLD_TEXT), environments_hash=_hash(OLD_TEXT),
    )
    client = _FakeClient(json.dumps({
        "verdict": "revise", "score": 30, "failing_gates": ["hook speed"],
        "rewrite_guidance": "", "rule_verdicts": [],
    }))

    async def fake_get_client(_tenant_id):
        return client

    async def fake_list_all_rules(_tenant_id, *, active_only=False):
        return []

    async def fake_tag(_video_id, _tenant_id):
        return None

    monkeypatch.setattr(user_script, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(user_script, "execute", fake_execute)
    monkeypatch.setattr(kie_unified, "get_text_client_for_tenant", fake_get_client)
    monkeypatch.setattr(quality_rules, "list_all_rules", fake_list_all_rules)
    monkeypatch.setattr(dialogue_intelligence, "tag_video_dialogue", fake_tag, raising=False)
    monkeypatch.setattr(rv, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(rv, "execute", fake_execute)

    result = asyncio.run(user_script.accept_external_script(
        TENANT_ID, VIDEO_ID, _scenes("Weak scene."), source="agent_submitted",
    ))

    assert result["accepted"] is False
    assert writes == [], "a rejected submission must touch NOTHING in the DB, including the flag"
    assert state["video_characters_status"] == "approved"
    assert state["video_environments_status"] == "approved"


def test_accept_external_script_flag_failure_never_blocks_the_save(monkeypatch):
    """routes.videos is NOT monkeypatched — the flag helper hits the real
    (unset) DATABASE_URL, fails inside its own try/except, and must never
    stop the accept from completing."""
    async def fake_fetch_one(query, *args):
        q = query.strip()
        if "FROM videos WHERE id = $1 AND tenant_id = $2" in q:
            return _video_row()
        return None

    writes = []

    async def fake_execute(query, *args):
        writes.append((query, args))
        return "UPDATE 1"

    _wire_external(monkeypatch, fake_fetch_one, fake_execute)

    result = asyncio.run(user_script.accept_external_script(
        TENANT_ID, VIDEO_ID, _scenes("A clean scene with a location."), source="agent_submitted",
    ))

    assert result["accepted"] is True
    assert any(w[0].strip().startswith("UPDATE videos SET script") for w in writes)


# ---------------------------------------------------------------------------
# 3. Coverage-hash question: both doors DELETE+re-INSERT every scripts row,
#    so a stale coverage_directive_hash never survives onto a replacement
#    row — nothing to separately clear (D7-3's _clear_scene_downstream is a
#    no-op here by construction, not by an added call).
# ---------------------------------------------------------------------------

def test_set_user_script_replace_deletes_and_reinserts_without_coverage_hash(monkeypatch):
    state, writes, fake_fetch_one, fake_execute = _make_shared_fake_db()

    async def fake_tag(*_a, **_kw):
        return {}

    monkeypatch.setattr(user_script, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(user_script, "execute", fake_execute)
    monkeypatch.setattr(rv, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(rv, "execute", fake_execute)
    monkeypatch.setattr(dialogue_intelligence, "tag_video_dialogue", fake_tag, raising=False)

    asyncio.run(user_script.set_user_script(
        TENANT_ID, VIDEO_ID,
        "Scene one paragraph.\n\nScene two paragraph, a distinct second beat entirely.",
    ))

    deletes = [q for q, _ in writes if q.strip().startswith("DELETE FROM scripts")]
    inserts = [(q, a) for q, a in writes if q.strip().startswith("INSERT INTO scripts")]
    assert len(deletes) == 1, "every scripts row for this video must be wholesale replaced"
    assert len(inserts) >= 1
    for insert_query, _args in inserts:
        assert "coverage_directive_hash" not in insert_query, (
            "the INSERT never carries coverage_directive_hash forward — a "
            "fresh row always starts with no stored board plan to reuse"
        )
