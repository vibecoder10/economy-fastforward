"""C46d — trust boundaries: the ingest gate for externally-submitted scripts.

Covers:
  1. ``user_script.accept_external_script`` — the seam C47's MCP
     ``submit_script`` tool will call. Accept/reject/warn matrix:
       - a universal-gate 'revise'/'regenerate' verdict -> REJECT, nothing
         saved, no status change, rule-by-rule violations returned.
       - a hard-gate channel RULE failure (severity enforced deterministically
         by script_quality._apply_rule_severity, same as C46b/C46a) -> REJECT
         with that rule named.
       - a WARN-severity rule failure alone -> the verdict never flips, so
         ACCEPT, with the failure surfaced as a non-blocking "warning" (not a
         "violation").
       - a clean pass -> ACCEPT, saved through the exact scene/videos.script
         save path set_user_script uses, script_source = the caller's
         `source` (never 'user_supplied' — keeps this submission distinct
         from a creator's verbatim text everywhere downstream), status
         advances.
     No server-side rewrite ever happens here (no edit loop) — proven by
     the FakeAnthropic response queues below never being asked for more than
     ONE grading call per accept/reject.
  2. The 'user_supplied' bypass stays reserved for set_user_script alone:
     accept_external_script refuses source='user_supplied' outright.
  3. Tenant scoping: a video that doesn't belong to the calling tenant is
     "not found", same as set_user_script's existing contract.
  4. Shape validation: bad/empty scene lists raise ValueError with no DB
     writes attempted.
  5. The banner data path (routes/videos.py::_parse_script_validation): a
     script_validation blob carrying ONLY the generic quality_critic record
     (no sibling "checks" array — exactly what accept_external_script and
     pipeline_executor._grade_and_maybe_revise_script both write) must not
     be silently dropped to None, or the C46d Script tab banner never has
     anything to render.

Local/no-spend: every Claude call is a fake client; every DB call is a fake
fetch_one/execute (matches tests/test_c46a_quality_critic_wiring.py's
convention). quality_rules.list_all_rules is faked at the module-attribute
level so the REAL (pure) active_rules_for_video/compose_rules_text resolvers
still run — proving the severity wiring end to end, not just the fakes.
"""

import asyncio
import json

import pytest

import identity
import kie_unified
import quality_rules
import user_script
import routes.videos as videos_route


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("FakeClient ran out of canned responses")
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


def _json(verdict="pass", score=90, failing_gates=None, rule_verdicts=None):
    return json.dumps({
        "verdict": verdict, "score": score,
        "failing_gates": failing_gates or [],
        "rewrite_guidance": "",
        "rule_verdicts": rule_verdicts or [],
    })


VIDEO_ID = "video-ext-1"
TENANT_ID = "tenant-ext"


def _video(**overrides):
    v = {
        "id": VIDEO_ID,
        "tenant_id": TENANT_ID,
        "video_title": "External Submission Test",
        "executive_hook": None,
        "hook_script": None,
        "status": "ready_for_scripting",
    }
    v.update(overrides)
    return v


def _wire(monkeypatch, video, client, *, rule_rows=None):
    """Common fixture wiring: fake DB + fake tenant client + fake rules rows
    (processed by the REAL quality_rules resolvers) + a no-op identity/
    dialogue tagging so tests stay focused on accept_external_script's own
    logic."""
    writes = []

    async def fake_fetch_one(query, *args):
        if "FROM videos" in query:
            vid, tenant = args[0], args[1]
            if vid == video["id"] and tenant == video["tenant_id"]:
                return dict(video)
            return None
        return None

    async def fake_execute(query, *args):
        writes.append((query, args))
        return None

    async def fake_get_client(_tenant_id):
        return client

    async def fake_build_identity(_tenant_id, _video):
        return type("FakeIdentity", (), {"niche": "test-niche"})()

    async def fake_list_all_rules(_tenant_id, *, active_only=False):
        return list(rule_rows or [])

    async def fake_tag_dialogue(_video_id, _tenant_id):
        return None

    monkeypatch.setattr(user_script, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(user_script, "execute", fake_execute)
    monkeypatch.setattr(kie_unified, "get_text_client_for_tenant", fake_get_client)
    monkeypatch.setattr(identity, "build_identity_context", fake_build_identity)
    monkeypatch.setattr(quality_rules, "list_all_rules", fake_list_all_rules)

    import dialogue_intelligence
    monkeypatch.setattr(dialogue_intelligence, "tag_video_dialogue", fake_tag_dialogue)

    return writes


def _scenes(*texts):
    # D6-3: every scene needs a "location" (STORY-LAWS S3) or
    # accept_external_script's deterministic gate rejects it before the
    # critic this file is actually testing ever runs. A fixed placeholder
    # keeps every existing case here focused on the critic matrix.
    return [{"scene": i + 1, "text": t, "location": "the set"} for i, t in enumerate(texts)]


# ---------------------------------------------------------------------------
# Accept/reject/warn matrix
# ---------------------------------------------------------------------------

def test_pass_verdict_accepts_saves_and_advances(monkeypatch):
    video = _video()
    client = FakeClient([_json(verdict="pass", score=95)])
    writes = _wire(monkeypatch, video, client)

    result = asyncio.run(user_script.accept_external_script(
        TENANT_ID, VIDEO_ID, _scenes("Scene one.", "Scene two."),
        source="agent_submitted",
    ))

    assert result["accepted"] is True
    assert result["verdict"] == "pass"
    assert result["violations"] == []
    assert result["warnings"] == []
    assert result["scenes"] == 2
    assert result["status"] == "ready_for_voice"
    assert len(client.calls) == 1, "verdict-only — never a second (edit) call for external content"

    script_write = next(w for w in writes if w[0].strip().startswith("UPDATE videos SET script"))
    full_text, source_arg, validation_json, status_arg = script_write[1][:4]
    assert full_text == "Scene one.\n\nScene two."
    assert source_arg == "agent_submitted", "must never silently become 'user_supplied'"
    assert status_arg == "ready_for_voice"
    validation = json.loads(validation_json)
    assert validation["quality_critic"]["passed"] is True
    assert validation["quality_critic"]["verdict"] == "pass"

    inserts = [w for w in writes if "INSERT INTO scripts" in w[0]]
    assert len(inserts) == 2
    assert inserts[0][1][3] == "Scene one."
    assert inserts[1][1][3] == "Scene two."
    assert any("DELETE FROM scripts" in w[0] for w in writes)


def test_universal_gate_revise_rejects_nothing_saved(monkeypatch):
    video = _video()
    client = FakeClient([_json(verdict="revise", score=40, failing_gates=["hook speed"])])
    writes = _wire(monkeypatch, video, client)

    result = asyncio.run(user_script.accept_external_script(
        TENANT_ID, VIDEO_ID, _scenes("Weak scene."), source="agent_submitted",
    ))

    assert result["accepted"] is False
    assert result["verdict"] == "revise"
    assert result["violations"] == ["hook speed"]
    assert writes == [], "a rejected submission must touch NOTHING in the DB"
    assert len(client.calls) == 1, "no edit-loop retry for external content — one grade, then reject"


def test_hard_gate_rule_violation_rejects_with_rule_named(monkeypatch):
    video = _video()
    # verdict comes back "pass" from the judge itself, but QL-2 is tagged
    # hard_gate — script_quality._apply_rule_severity must upgrade this to
    # 'revise' deterministically, same enforcement C46b/C46a already proved.
    client = FakeClient([_json(
        verdict="pass", score=85,
        rule_verdicts=[{"rule": "QL-2", "passed": False, "note": "banned hype word"}],
    )])
    rule_rows = [{
        "rule_id": "QL-2", "law": "No banned hype words.", "evidence": "",
        "severity": "hard_gate", "applies_to": {"all": True},
    }]
    writes = _wire(monkeypatch, video, client, rule_rows=rule_rows)

    result = asyncio.run(user_script.accept_external_script(
        TENANT_ID, VIDEO_ID, _scenes("Scene with hype."), source="agent_submitted",
    ))

    assert result["accepted"] is False
    assert result["verdict"] == "revise", "severity enforcement must upgrade pass -> revise"
    assert result["violations"] == ["QL-2"]
    assert writes == []


def test_warn_only_rule_failure_still_accepts_with_warning(monkeypatch):
    video = _video()
    client = FakeClient([_json(
        verdict="pass", score=88,
        rule_verdicts=[{"rule": "QL-9", "passed": False, "note": "a bit vague"}],
    )])
    rule_rows = [{
        "rule_id": "QL-9", "law": "Prefer concrete numbers.", "evidence": "",
        "severity": "warn", "applies_to": {"all": True},
    }]
    writes = _wire(monkeypatch, video, client, rule_rows=rule_rows)

    result = asyncio.run(user_script.accept_external_script(
        TENANT_ID, VIDEO_ID, _scenes("Scene text."), source="agent_submitted",
    ))

    assert result["accepted"] is True
    assert result["verdict"] == "pass"
    assert result["violations"] == []
    assert result["warnings"] == ["a bit vague"]

    script_write = next(w for w in writes if w[0].strip().startswith("UPDATE videos SET script"))
    validation = json.loads(script_write[1][2])
    qc = validation["quality_critic"]
    assert qc["warnings"] == ["a bit vague"]
    assert qc["severity_by_rule"] == {"QL-9": "warn"}
    assert qc["rule_verdicts"] == [{"rule": "QL-9", "passed": False, "note": "a bit vague"}]


def test_no_client_fails_open_and_accepts(monkeypatch):
    """script_quality.critique_script's own fail-open contract (a missing/
    broken client returns a default 'pass' CritiqueResult): when the tenant
    has no usable Claude client, accept_external_script must still accept
    rather than indefinitely block a submission no human is watching."""
    video = _video()
    writes = []

    async def fake_fetch_one(query, *args):
        return dict(video) if "FROM videos" in query else None

    async def fake_execute(query, *args):
        writes.append((query, args))

    async def fake_get_client_raises(_tenant_id):
        raise RuntimeError("no key configured")

    async def fake_list_all_rules(_tenant_id, *, active_only=False):
        return []

    async def fake_tag_dialogue(_video_id, _tenant_id):
        return None

    monkeypatch.setattr(user_script, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(user_script, "execute", fake_execute)
    monkeypatch.setattr(kie_unified, "get_text_client_for_tenant", fake_get_client_raises)
    monkeypatch.setattr(quality_rules, "list_all_rules", fake_list_all_rules)
    import dialogue_intelligence
    monkeypatch.setattr(dialogue_intelligence, "tag_video_dialogue", fake_tag_dialogue)

    result = asyncio.run(user_script.accept_external_script(
        TENANT_ID, VIDEO_ID, _scenes("Scene text."), source="agent_submitted",
    ))

    assert result["accepted"] is True
    assert result["verdict"] == "pass"
    assert any(w[0].strip().startswith("UPDATE videos SET script") for w in writes)


# ---------------------------------------------------------------------------
# user_supplied stays set_user_script's alone
# ---------------------------------------------------------------------------

def test_refuses_user_supplied_source(monkeypatch):
    calls = {"fetch_one": 0}

    async def fake_fetch_one(*_a, **_k):
        calls["fetch_one"] += 1
        return None

    monkeypatch.setattr(user_script, "fetch_one", fake_fetch_one)

    with pytest.raises(ValueError, match="user_supplied"):
        asyncio.run(user_script.accept_external_script(
            TENANT_ID, VIDEO_ID, _scenes("Text."), source="user_supplied",
        ))
    assert calls["fetch_one"] == 0, "refused before ever touching the DB"


# ---------------------------------------------------------------------------
# Tenant scoping
# ---------------------------------------------------------------------------

def test_wrong_tenant_is_not_found(monkeypatch):
    video = _video()

    async def fake_fetch_one(query, *args):
        # Simulate the real SQL's tenant_id = $2 clause: a mismatched
        # tenant gets nothing back, exactly like set_user_script's guard.
        if "FROM videos" in query and args[1] == video["tenant_id"]:
            return dict(video)
        return None

    monkeypatch.setattr(user_script, "fetch_one", fake_fetch_one)

    with pytest.raises(ValueError, match="not found"):
        asyncio.run(user_script.accept_external_script(
            "some-other-tenant", VIDEO_ID, _scenes("Text."), source="agent_submitted",
        ))


# ---------------------------------------------------------------------------
# Scene-shape validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_scenes", [
    [],
    "not a list",
    [{"no_text_field": True}],
    [{"text": "   "}],
    [{"text": "ok"}, "not a dict"],
])
def test_bad_scene_shape_raises_before_any_db_touch(monkeypatch, bad_scenes):
    video = _video()
    calls = {"fetch_one": 0}

    async def fake_fetch_one(query, *args):
        calls["fetch_one"] += 1
        return dict(video)

    async def forbidden_execute(*_a, **_k):
        raise AssertionError("bad scene shape must never reach a DB write")

    monkeypatch.setattr(user_script, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(user_script, "execute", forbidden_execute)

    with pytest.raises(ValueError):
        asyncio.run(user_script.accept_external_script(
            TENANT_ID, VIDEO_ID, bad_scenes, source="agent_submitted",
        ))


# ---------------------------------------------------------------------------
# Banner data path — routes/videos.py::_parse_script_validation must not
# drop a quality_critic-only blob (the C46d fix).
# ---------------------------------------------------------------------------

def test_parse_script_validation_keeps_quality_critic_only_blob():
    blob = json.dumps({
        "quality_critic": {
            "passed": False, "verdict": "revise", "score": 40,
            "failing_gates": ["hook speed"], "violations": ["hook speed"],
            "rule_verdicts": [], "severity_by_rule": {},
            "edit_rounds": 2, "regenerated": False,
        }
    })

    parsed = videos_route._parse_script_validation(blob)

    assert parsed is not None, "quality_critic-only JSON must not be dropped to None"
    decoded = json.loads(parsed)
    assert decoded["quality_critic"]["verdict"] == "revise"
    assert decoded["quality_critic"]["failing_gates"] == ["hook speed"]


def test_parse_script_validation_still_passes_through_checks_shape():
    blob = json.dumps({"passed": True, "checks": [{"name": "x", "passed": True, "detail": "ok"}]})
    assert videos_route._parse_script_validation(blob) == blob


def test_parse_script_validation_still_converts_legacy_plain_text():
    legacy = "Editorial validation: PASSED\n[PASS] number_density: 12/10 numbers found"
    parsed = videos_route._parse_script_validation(legacy)
    assert parsed is not None
    decoded = json.loads(parsed)
    assert decoded["passed"] is True
    assert decoded["checks"][0]["name"] == "number_density"
