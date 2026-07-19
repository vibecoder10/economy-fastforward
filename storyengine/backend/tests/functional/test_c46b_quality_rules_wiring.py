"""Wiring tests for checklist C46b (per-channel quality-rules store).

Covers what tests/test_quality_rules.py (the pure-module unit file) can't:
  1. pipeline_executor.py's `_grade_and_maybe_revise_script`: rules_text now
     sources from the real `quality_rules` table (scope-matched against the
     video), with script_templates.structure kept as an ADDITIONAL block —
     and a hard-gate rule failure genuinely reaches the bounded edit loop
     (severity forces 'revise' even when the judge's own verdict said
     'pass').
  2. routes/chat.py's "draft_quality_rules" ingestion door: stash-only (no
     write) -> confirm card -> "yes" tap is the ONLY thing that calls
     quality_rules.bulk_create_rules.
  3. routes/quality_rules.py's CRUD route functions: tenant-scoped calls
     into quality_rules.py, never a parallel implementation.
  4. producer_prompt.py teaches the draft_quality_rules vocabulary.

Local/no-spend: every Claude call is a fake client; every DB call is a fake
fetch_one/fetch_all/execute, matching tests/test_c46a_quality_critic_wiring.py
and tests/functional/test_c22_style_draft.py's established conventions.
"""

import asyncio
import json
import os
import sys
import types

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


async def _boom(*a, **k):
    raise AssertionError("pure tests must not touch runtime services")


_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom, safe_column=lambda name: name)
_stub("vault", get_secret=_boom)

import producer_prompt  # noqa: E402
import routes.chat as chat  # noqa: E402
import routes.quality_rules as quality_rules_routes  # noqa: E402
import quality_rules as qr  # noqa: E402
import pipeline_executor as pe  # noqa: E402

TENANT = "tenant-1"


# =============================================================================
# 1. pipeline_executor._grade_and_maybe_revise_script — real quality_rules
#    sourcing, house-format kept additional, severity reaches blocking.
# =============================================================================

class FakeAnthropic:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("FakeAnthropic ran out of canned responses")
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


def _base_video(**overrides):
    video = {
        "id": "video-1",
        "video_title": "Title",
        "script": "Scene one text. Scene two text.",
        "script_validation": None,
        "executive_hook": None,
        "hook_script": None,
        "status": "ready_for_scripting",
        "research_skipped": False,
        "pipeline_stages": None,
        "render_mode": None,
        "render_style": None,
    }
    video.update(overrides)
    return video


def _make_executor(video, anthropic, *, quality_rule_rows=None, template_row=None, fetch_all_scenes=None):
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": anthropic})()

    writes = []

    async def fake_execute(query, *args):
        writes.append((query, args))
        return None

    async def fake_fetch_one(query, *args):
        if "FROM videos" in query:
            return dict(video)
        if "FROM script_templates" in query:
            return template_row
        return None

    async def fake_fetch_all(query, *args):
        if "FROM scripts" in query:
            return fetch_all_scenes or []
        if "FROM quality_rules" in query:
            return quality_rule_rows or []
        return []

    return executor, fake_execute, fake_fetch_one, fake_fetch_all, writes


def test_rules_text_sourced_from_quality_rules_scope_matched(monkeypatch):
    video = _base_video(render_mode="static_docu", research_skipped=False, pipeline_stages=None)
    anthropic = FakeAnthropic(['{"verdict": "pass", "score": 90, "failing_gates": [], "rewrite_guidance": ""}'])
    rules = [
        {"rule_id": "QL-3", "law": "Every entry needs a designed-vs-used twist.",
         "evidence": None, "severity": "hard_gate", "applies_to": '{"story": true}'},
        {"rule_id": "QL-18", "law": "Two independent sources for every number.",
         "evidence": None, "severity": "hard_gate", "applies_to": '{"research": true}'},
    ]
    executor, fake_execute, fake_fetch_one, fake_fetch_all, writes = _make_executor(
        video, anthropic,
        quality_rule_rows=rules,
        fetch_all_scenes=[{"scene": 1, "scene_text": "Scene one text."}],
    )
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)

    asyncio.run(executor._grade_and_maybe_revise_script("video-1"))

    system_prompt = anthropic.calls[0]["system_prompt"]
    # story-scoped rule matched (render_mode=static_docu); research-scoped
    # rule ALSO matched (research_skipped=False, no plan restriction) — a
    # hybrid video gets both.
    assert "QL-3" in system_prompt
    assert "QL-18" in system_prompt
    assert "[HARD-GATE]" in system_prompt


def test_rules_text_excludes_out_of_scope_rules(monkeypatch):
    video = _base_video(render_mode=None, research_skipped=True, pipeline_stages=None)
    anthropic = FakeAnthropic(['{"verdict": "pass", "score": 90, "failing_gates": [], "rewrite_guidance": ""}'])
    rules = [
        {"rule_id": "QL-3", "law": "Story-arc twist law.", "evidence": None,
         "severity": "warn", "applies_to": '{"story": true}'},
        {"rule_id": "QL-18", "law": "Research two-source law.", "evidence": None,
         "severity": "warn", "applies_to": '{"research": true}'},
        {"rule_id": "QL-12", "law": "No hype words, ever.", "evidence": None,
         "severity": "hard_gate", "applies_to": '{"all": true}'},
    ]
    executor, fake_execute, fake_fetch_one, fake_fetch_all, writes = _make_executor(
        video, anthropic,
        quality_rule_rows=rules,
        fetch_all_scenes=[{"scene": 1, "scene_text": "Scene one text."}],
    )
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)

    asyncio.run(executor._grade_and_maybe_revise_script("video-1"))

    system_prompt = anthropic.calls[0]["system_prompt"]
    assert "QL-12" in system_prompt   # all-scope, always present
    assert "QL-3" not in system_prompt    # story scope, not a static_docu video
    assert "QL-18" not in system_prompt   # research scope, research_skipped=True


def test_house_format_kept_as_additional_block_alongside_quality_rules(monkeypatch):
    video = _base_video()
    anthropic = FakeAnthropic(['{"verdict": "pass", "score": 90, "failing_gates": [], "rewrite_guidance": ""}'])
    rules = [{"rule_id": "QL-12", "law": "No hype words.", "evidence": None,
              "severity": "hard_gate", "applies_to": '{"all": true}'}]
    executor, fake_execute, fake_fetch_one, fake_fetch_all, writes = _make_executor(
        video, anthropic,
        quality_rule_rows=rules,
        template_row={"structure": "Always cold-open on a ticking clock."},
        fetch_all_scenes=[{"scene": 1, "scene_text": "Scene one text."}],
    )
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)

    asyncio.run(executor._grade_and_maybe_revise_script("video-1"))

    system_prompt = anthropic.calls[0]["system_prompt"]
    assert "QL-12" in system_prompt
    assert "Always cold-open on a ticking clock." in system_prompt


def test_empty_quality_rules_and_no_template_is_byte_compatible_with_c46a(monkeypatch):
    """No quality_rules rows configured yet AND no script_templates row ->
    rules_text stays empty, exactly the pre-C46b/pre-C46a state (no CHANNEL
    RULES addendum is added at all)."""
    video = _base_video()
    anthropic = FakeAnthropic(['{"verdict": "pass", "score": 90, "failing_gates": [], "rewrite_guidance": ""}'])
    executor, fake_execute, fake_fetch_one, fake_fetch_all, writes = _make_executor(
        video, anthropic,
        fetch_all_scenes=[{"scene": 1, "scene_text": "Scene one text."}],
    )
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)

    asyncio.run(executor._grade_and_maybe_revise_script("video-1"))

    assert "CHANNEL RULES" not in anthropic.calls[0]["system_prompt"]


def test_hard_gate_rule_failure_reaches_the_bounded_edit_loop(monkeypatch):
    """The judge returns 'pass' overall (a plausible under-call) but flags a
    hard-gate rule as failed — script_quality._apply_rule_severity must
    upgrade the verdict to 'revise', which is what makes
    run_critique_and_edit's edit loop actually engage. Proves severity
    reaches the critic's blocking logic end-to-end through
    pipeline_executor's real wiring, not just script_quality in isolation."""
    video = _base_video()
    judge_pass_but_flags_hard_gate = json.dumps({
        "verdict": "pass", "score": 88, "failing_gates": [], "rewrite_guidance": "",
        "rule_verdicts": [{"rule": "QL-12", "passed": False, "note": "used 'incredible'"}],
    })
    edited = "@@@SCENE 1@@@\nA cleaner scene one.\n"
    judge_pass_after_edit = json.dumps({"verdict": "pass", "score": 95, "failing_gates": [], "rewrite_guidance": ""})
    anthropic = FakeAnthropic([judge_pass_but_flags_hard_gate, edited, judge_pass_after_edit])
    rules = [{"rule_id": "QL-12", "law": "Never use hype words.", "evidence": None,
              "severity": "hard_gate", "applies_to": '{"all": true}'}]
    executor, fake_execute, fake_fetch_one, fake_fetch_all, writes = _make_executor(
        video, anthropic,
        quality_rule_rows=rules,
        fetch_all_scenes=[{"scene": 1, "scene_text": "This is incredible tech."}],
    )
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)

    result = asyncio.run(executor._grade_and_maybe_revise_script("video-1"))

    assert len(anthropic.calls) == 3, "grade(revise-forced) -> edit -> re-grade(pass)"
    assert result == {"needs_review": False, "violations": []}
    assert any("DELETE FROM scripts" in w[0] for w in writes), "the edit loop must have actually run and persisted"


# =============================================================================
# 2. routes/chat.py — "draft_quality_rules" ingestion door
# =============================================================================

_TABLE_TEXT = """
| ID | Law (testable) | Evidence (counts) | Triangle - B / R / G | Sev |
|---|---|---|---|---|
| QL-12 | Ban thumbnail-hype adjectives. | 0 occurrences in 40,000 words. | B no hype. R flag hype. G hard-reject. | hard-gate |
| QL-7 | Cap bare name-openers at 57%. | 105 entries: name 57%. | B vary opener. R flag. G warn. | warn |
"""


def test_producer_prompt_teaches_draft_quality_rules():
    assert "draft_quality_rules" in producer_prompt.PRODUCER_SYSTEM_PROMPT
    assert '"op": "draft_quality_rules"' in producer_prompt.PRODUCER_SYSTEM_PROMPT


def test_draft_quality_rules_stashes_only_never_writes(monkeypatch):
    # fetch_one/fetch_all/execute remain bound to the module-level _boom
    # stubs — a write attempt fails loudly.
    state = {}
    ops = [{"op": "draft_quality_rules", "value": {"text": _TABLE_TEXT}}]
    results = asyncio.run(chat._apply_profile_ops(TENANT, ops, state, None))

    assert "pending_quality_rules_draft" in state
    rows = state["pending_quality_rules_draft"]["rows"]
    assert [r["rule_id"] for r in rows] == ["QL-12", "QL-7"]
    assert any("2 rule" in r for r in results)


def test_draft_quality_rules_with_no_text_asks_for_it():
    state = {}
    ops = [{"op": "draft_quality_rules", "value": {}}]
    results = asyncio.run(chat._apply_profile_ops(TENANT, ops, state, None))
    assert "pending_quality_rules_draft" not in state
    assert any("paste" in r.lower() or "drop" in r.lower() for r in results)


def test_draft_quality_rules_reads_asset_parsed_text(monkeypatch):
    async def fake_fetch_one(query, *args):
        assert "chat_assets" in query
        return {"parsed_text": _TABLE_TEXT}

    monkeypatch.setattr(chat, "fetch_one", fake_fetch_one)
    state = {}
    ops = [{"op": "draft_quality_rules", "value": {"asset_id": "asset-1"}}]
    asyncio.run(chat._apply_profile_ops(TENANT, ops, state, None))
    assert state["pending_quality_rules_draft"]["asset_id"] == "asset-1"
    assert len(state["pending_quality_rules_draft"]["rows"]) == 2


def test_quality_rules_draft_card_shape():
    draft = {"rows": [
        {"rule_id": "QL-12", "law": "No hype.", "severity": "hard_gate"},
        {"rule_id": "QL-7", "law": "Cap openers.", "severity": "warn"},
    ]}
    card = chat._quality_rules_draft_card(draft)
    assert card["id"] == "quality_rules_draft"
    assert "2 quality rules" in card["label"]
    values = {o["value"] for o in card["options"]}
    assert values == {"yes", "no"}


def test_no_card_when_no_pending_draft_even_if_op_present():
    data = {"assistant_text": "ok", "profile_ops": [{"op": "draft_quality_rules", "value": {}}]}
    state = {}
    chat._maybe_attach_quality_rules_draft_card(data, state)
    assert "cards" not in data


def test_attach_card_when_op_and_pending_draft_both_present():
    data = {"assistant_text": "ok", "profile_ops": [{"op": "draft_quality_rules", "value": {}}]}
    state = {"pending_quality_rules_draft": {"rows": [{"rule_id": "QL-1", "law": "x", "severity": "warn"}]}}
    chat._maybe_attach_quality_rules_draft_card(data, state)
    assert data["cards"][0]["id"] == "quality_rules_draft"


def test_confirm_with_no_pending_draft_writes_nothing(monkeypatch):
    async def fake_persist(*a, **k):
        pass
    monkeypatch.setattr(chat, "_persist", fake_persist)

    resp = asyncio.run(chat._handle_quality_rules_draft_confirm(
        {"quality_rules_draft": "yes"}, "conv-1", TENANT, [], {}
    ))
    assert "waiting" in resp.assistant_text.lower()


def test_confirm_no_discards_without_writing(monkeypatch):
    async def fake_persist(*a, **k):
        pass

    async def boom_bulk_create(*a, **k):
        raise AssertionError("must not write on 'no'")

    monkeypatch.setattr(chat, "_persist", fake_persist)
    monkeypatch.setattr(qr, "bulk_create_rules", boom_bulk_create)

    state = {"pending_quality_rules_draft": {"rows": [{"rule_id": "QL-1", "law": "x", "severity": "warn"}]}}
    resp = asyncio.run(chat._handle_quality_rules_draft_confirm(
        {"quality_rules_draft": "no"}, "conv-1", TENANT, [], state
    ))
    assert "didn't save" in resp.assistant_text.lower()
    assert "pending_quality_rules_draft" not in state


def test_confirm_yes_calls_bulk_create_rules_exactly_once(monkeypatch):
    calls = []

    async def fake_persist(*a, **k):
        pass

    async def fake_bulk_create(tenant_id, rows, *, source):
        calls.append((tenant_id, rows, source))
        return [{"id": str(i), **r} for i, r in enumerate(rows)]

    async def fake_execute(query, *args):
        assert "chat_assets" in query

    monkeypatch.setattr(chat, "_persist", fake_persist)
    monkeypatch.setattr(chat, "execute", fake_execute)
    monkeypatch.setattr(qr, "bulk_create_rules", fake_bulk_create)

    rows = [{"rule_id": "QL-12", "law": "No hype.", "severity": "hard_gate"}]
    state = {"pending_quality_rules_draft": {"rows": rows, "asset_id": "asset-1"}}
    resp = asyncio.run(chat._handle_quality_rules_draft_confirm(
        {"quality_rules_draft": "yes"}, "conv-1", TENANT, [], state
    ))

    assert len(calls) == 1
    tenant_id, saved_rows, source = calls[0]
    assert tenant_id == TENANT
    assert saved_rows == rows
    assert source == "doc_upload"
    assert "1 quality rule" in resp.assistant_text
    assert "pending_quality_rules_draft" not in state


def test_confirm_yes_fails_soft_when_crud_raises(monkeypatch):
    async def fake_persist(*a, **k):
        pass

    async def boom_bulk_create(*a, **k):
        raise RuntimeError("db is down")

    monkeypatch.setattr(chat, "_persist", fake_persist)
    monkeypatch.setattr(qr, "bulk_create_rules", boom_bulk_create)

    state = {"pending_quality_rules_draft": {"rows": [{"rule_id": "QL-1", "law": "x", "severity": "warn"}]}}
    resp = asyncio.run(chat._handle_quality_rules_draft_confirm(
        {"quality_rules_draft": "yes"}, "conv-1", TENANT, [], state
    ))
    assert "snag" in resp.assistant_text.lower()


def test_chat_turn_source_intercepts_quality_rules_draft_before_intake():
    import inspect
    src = inspect.getsource(chat.chat_turn)
    assert '"quality_rules_draft" in body.selections' in src
    assert 'state.get("pending_quality_rules_draft")' in src
    assert "_handle_quality_rules_draft_confirm(" in src
    assert src.index('_handle_quality_rules_draft_confirm(') < src.index("user_parts: list[str] = []")


# =============================================================================
# 3. routes/quality_rules.py — CRUD route functions, tenant-scoped
# =============================================================================

def test_list_rules_route_passes_tenant_and_active_only(monkeypatch):
    captured = {}

    async def fake_list_all_rules(tenant_id, *, active_only=False):
        captured["tenant_id"] = tenant_id
        captured["active_only"] = active_only
        return [{"id": "1"}]

    monkeypatch.setattr(quality_rules_routes.quality_rules, "list_all_rules", fake_list_all_rules)
    result = asyncio.run(quality_rules_routes.list_rules(active_only=True, tenant_id="tenant-abc"))
    assert captured == {"tenant_id": "tenant-abc", "active_only": True}
    assert result == {"rules": [{"id": "1"}]}


def test_create_rule_route_rejects_bad_severity():
    from fastapi import HTTPException
    body = quality_rules_routes.CreateRuleRequest(rule_id="QL-1", law="x", severity="bogus")
    with pytest.raises(HTTPException):
        asyncio.run(quality_rules_routes.create_rule(body, tenant_id="tenant-abc"))


def test_create_rule_route_calls_create_rule_with_tenant(monkeypatch):
    captured = {}

    async def fake_create_rule(tenant_id, *, rule_id, law, severity, evidence, applies_to, source):
        captured.update(tenant_id=tenant_id, rule_id=rule_id, law=law, severity=severity, source=source)
        return {"id": "1", "rule_id": rule_id}

    monkeypatch.setattr(quality_rules_routes.quality_rules, "create_rule", fake_create_rule)
    body = quality_rules_routes.CreateRuleRequest(rule_id="QL-1", law="No hype.", severity="hard_gate")
    result = asyncio.run(quality_rules_routes.create_rule(body, tenant_id="tenant-abc"))
    assert captured["tenant_id"] == "tenant-abc"
    assert captured["source"] == "chat"
    assert result["rule"]["rule_id"] == "QL-1"


def test_update_rule_route_404_when_not_found(monkeypatch):
    from fastapi import HTTPException

    async def fake_update_rule(tenant_id, id_, updates):
        return None

    monkeypatch.setattr(quality_rules_routes.quality_rules, "update_rule", fake_update_rule)
    body = quality_rules_routes.UpdateRuleRequest(active=False)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(quality_rules_routes.update_rule("missing-id", body, tenant_id="tenant-abc"))
    assert exc.value.status_code == 404


def test_deactivate_rule_route_calls_deactivate_with_tenant(monkeypatch):
    captured = {}

    async def fake_deactivate_rule(tenant_id, id_):
        captured.update(tenant_id=tenant_id, id_=id_)
        return True

    monkeypatch.setattr(quality_rules_routes.quality_rules, "deactivate_rule", fake_deactivate_rule)
    result = asyncio.run(quality_rules_routes.deactivate_rule("rule-1", tenant_id="tenant-abc"))
    assert captured == {"tenant_id": "tenant-abc", "id_": "rule-1"}
    assert result == {"status": "deactivated"}
