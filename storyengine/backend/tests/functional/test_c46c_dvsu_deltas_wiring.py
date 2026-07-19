"""Wiring tests for checklist C46c (DvsU deltas as the reference-tenant
table-driven gates).

Covers what tests/test_quality_rules.py (pure resolver unit tests) and
tests/test_machine_documentary_hold.py (direct rule_overrides= unit tests on
the validators themselves) can't:

  1. ``PipelineExecutor._load_dvsu_rule_overrides`` — the async DB-fetch +
     scope-match + resolve seam that ``_run_static_script_hold`` calls once
     per script-hold run. Proves it reads the real ``quality_rules`` table
     (tenant-scoped, active-only), scope-matches against THIS video's shape
     data (never an LLM judgment call — Ryan's 2026-07-19 ruling, same
     discipline as C46b's ``_grade_and_maybe_revise_script`` wiring), and
     fails open (returns ``{}``) on any error.

Local/no-spend: every DB call is a fake fetch_all, matching
tests/test_c46a_quality_critic_wiring.py and
tests/functional/test_c46b_quality_rules_wiring.py's established
conventions.
"""

import asyncio
import os
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import pipeline_executor as pe  # noqa: E402


def _make_executor(tenant_id="tenant-test"):
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = tenant_id
    return executor


def _video(**overrides):
    video = {
        "id": "video-1",
        "render_mode": "static_docu",
        "render_style": None,
        "research_skipped": False,
        "pipeline_stages": None,
    }
    video.update(overrides)
    return video


def test_load_overrides_fetches_active_rules_scoped_to_tenant(monkeypatch):
    captured = {}

    async def fake_fetch_all(query, *args):
        captured["query"] = query
        captured["args"] = args
        return [
            {"rule_id": "QL-1", "law": "Reject under 80 spoken words; warn 80-95; reject over 170.",
             "evidence": None, "severity": "hard_gate", "applies_to": '{"story": true}'},
        ]

    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    executor = _make_executor()

    overrides = asyncio.run(executor._load_dvsu_rule_overrides(_video()))

    assert "FROM quality_rules WHERE tenant_id = $1 AND active" in captured["query"]
    assert captured["args"] == ("tenant-test",)
    assert overrides["word_floor"] == {
        "hard_min": 80, "warn_top": 95, "hard_max": 170, "severity": "hard_gate",
    }


def test_load_overrides_excludes_out_of_scope_rule(monkeypatch):
    """A story-scoped QL-1 row must NOT match a video whose render_mode isn't
    static_docu — deterministic scope matching, not "DvsU always gets it"."""
    async def fake_fetch_all(query, *args):
        return [
            {"rule_id": "QL-1", "law": "Reject under 80 spoken words; warn 80-95; reject over 170.",
             "evidence": None, "severity": "hard_gate", "applies_to": '{"story": true}'},
        ]

    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    executor = _make_executor()

    overrides = asyncio.run(executor._load_dvsu_rule_overrides(_video(render_mode=None)))

    assert overrides == {}


def test_load_overrides_fails_open_to_empty_dict_on_db_error(monkeypatch):
    async def boom(*_a, **_k):
        raise RuntimeError("no quality_rules table yet")

    monkeypatch.setattr(pe, "fetch_all", boom)
    executor = _make_executor()

    overrides = asyncio.run(executor._load_dvsu_rule_overrides(_video()))

    assert overrides == {}


def test_load_overrides_empty_rows_is_byte_identical_fallback(monkeypatch):
    async def fake_fetch_all(*_a, **_k):
        return []

    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    executor = _make_executor()

    overrides = asyncio.run(executor._load_dvsu_rule_overrides(_video()))

    assert overrides == {}


def _run_static_script_hold_source() -> str:
    """Slice ``_run_static_script_hold``'s own source body (not the whole
    9000+ line module) so the wiring-lock assertions below can't
    accidentally match an unrelated method elsewhere in the file."""
    import inspect

    lines = inspect.getsource(pe).splitlines()
    start = next(i for i, line in enumerate(lines) if "async def _run_static_script_hold(" in line)
    end = next(
        i for i, line in enumerate(lines[start + 1:], start=start + 1)
        if line.startswith("    async def ") or line.startswith("    def ")
    )
    return "\n".join(lines[start:end])


def test_run_static_script_hold_computes_overrides_once_before_the_loop():
    """Wiring lock (same pattern as test_first_run_checklist_wired_lock.py):
    proves the fetch happens ONCE per script-hold run (not per machine —
    would be a needless DB round-trip per roster item) by requiring it to
    appear textually before the per-machine `for i, machine in
    selected_units:` loop starts."""
    source = _run_static_script_hold_source()
    fetch_pos = source.index("await self._load_dvsu_rule_overrides(video)")
    loop_pos = source.index("for i, machine in selected_units:")
    assert fetch_pos < loop_pos


def test_run_static_script_hold_threads_overrides_into_every_validator_call():
    """Wiring lock: every call to the three C46c-aware validators inside
    _run_static_script_hold must actually pass dvsu_rule_overrides through —
    a helper that resolves the right value but is never threaded to the
    gate is dead code."""
    source = _run_static_script_hold_source()

    story_sentence_calls = [
        line for line in source.splitlines()
        if "_validate_machine_story_sentences(machine, story_plan, bundle" in line
    ]
    assert story_sentence_calls, "expected at least one _validate_machine_story_sentences call"
    assert all("dvsu_rule_overrides" in line for line in story_sentence_calls)

    static_paragraph_calls = [
        line for line in source.splitlines()
        if "self._validate_static_unit_paragraph(machine, paragraph" in line
    ]
    assert static_paragraph_calls, "expected at least one _validate_static_unit_paragraph call"
    assert all("dvsu_rule_overrides" in line for line in static_paragraph_calls)

    audit_block_start = source.index("quality_audit = _anton_preview_quality_audit(")
    audit_block = source[audit_block_start:audit_block_start + 300]
    assert "dvsu_rule_overrides" in audit_block
