"""Unit tests for dvsu_script_v2 - the only DvsU machine-paragraph writer.

Mocking pattern mirrors tests/test_dvsu_research_v2.py: a hand-rolled client
with an async ``generate(**kwargs)`` that records calls and returns queued
JSON strings; a PipelineExecutor built with ``__new__`` and the handful of
DB-touching methods replaced by AsyncMocks. Never a mock of the SDK.
"""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import dvsu_research_v2 as research
import dvsu_script_v2 as script

MACHINE = "USS Nautilus SSN-571"
SIBLING = "USS Holland SS-1"
TITLE = "Every US Submarine Class Ever Built"

GOOD_PARAGRAPH = (
    "For fifty years every submarine had been a surface ship that could hide, surfacing to breathe "
    "and to charge batteries that emptied within hours. Nautilus ended that bargain in January 1955 "
    "with a reactor that never needed air, and her first signal, underway on nuclear power, was written "
    "as a fact rather than a boast. The price was a hull built around a machine nobody had put to sea "
    "before, with shielding and a crew trained for an accident no one could describe. She crossed under "
    "the North Pole in 1958, a voyage no earlier vessel could have attempted. The submarine had not "
    "become faster. It had simply stopped needing the surface at all."
)


class _Client:
    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


def _packet(machine=MACHINE):
    return {
        "machine": machine,
        "act_number": 4,
        "problem": {"answer": "Diesel submarines had to surface to breathe.",
                    "source_url": "https://example.navy.mil/problem", "quote": "Problem quote."},
        "design": {"answer": "A pressurized-water reactor drove the propulsion plant.",
                   "source_url": "https://example.navy.mil/design", "quote": "Design quote."},
        "trade_off": {"answer": "Shielding and reactor space cost weapons volume.",
                      "source_url": "https://example.navy.mil/tradeoff", "quote": "Trade-off quote."},
        "outcome_candidates": [
            {"fact": "Crossed under the North Pole in 1958.", "source_url": "https://example.navy.mil/outcome1", "quote": "Outcome quote one."},
            {"fact": "Signalled underway on nuclear power in 1955.", "source_url": "https://example.navy.mil/outcome2", "quote": "Outcome quote two."},
        ],
        "surprising_fact": {"answer": "Her first message was a plain three-word signal.",
                            "source_url": "https://example.navy.mil/surprise", "quote": "Surprising quote."},
        "contrast": {"answer": "Built as an experiment, she rewrote the fleet.",
                     "source_url": "https://example.navy.mil/contrast", "quote": "Contrast quote."},
    }


def _package(machine=MACHINE):
    return research.adapt_packet_to_factual_card(machine, 4, _packet(machine), 1, TITLE)["package"]


def _draft(paragraph=GOOD_PARAGRAPH, **extra):
    body = {
        "paragraph": paragraph,
        "claim_map": [{"sentence": "She crossed under the North Pole in 1958, a voyage no earlier vessel could have attempted.",
                       "source_url": "https://example.navy.mil/outcome1", "quote": "Outcome quote one."}],
        "opened_with_name": False,
        "bridged_to": None,
    }
    body.update(extra)
    return json.dumps(body)


# ---------------------------------------------------------------------------
# Brief: round trip through the saved package (the packet is never persisted)
# ---------------------------------------------------------------------------

def test_packet_round_trips_through_the_adapted_package():
    rebuilt = research.packet_from_verified_source_package(MACHINE, _package())
    expected = _packet()
    expected.pop("act_number")
    assert rebuilt == expected


def test_legacy_package_without_call3_sources_yields_no_brief():
    legacy = {"machine": MACHINE, "sources": [{"source_id": "S1", "source_url": "https://x"}],
              "candidate_excerpts": [{"excerpt_id": "S1-E1", "source_id": "S1", "source_url": "https://x", "text": "t"}],
              "claim_assessment": {"claims": []}}
    assert research.packet_from_verified_source_package(MACHINE, legacy) is None
    assert script.brief_for_machine({"machine_raw_source_packages": {"USSNAUTILUSSSN571": legacy}}, MACHINE) is None


def test_brief_for_machine_reads_the_saved_package_by_cache_key():
    import pipeline_executor as pe
    payload = {"machine_raw_source_packages": {pe._verified_source_cache_key(MACHINE): _package()}}
    brief = script.brief_for_machine(payload, MACHINE)
    assert brief["problem"]["answer"].startswith("Diesel submarines")
    assert script.brief_source_urls(brief) == {
        "https://example.navy.mil/problem", "https://example.navy.mil/design", "https://example.navy.mil/tradeoff",
        "https://example.navy.mil/outcome1", "https://example.navy.mil/outcome2", "https://example.navy.mil/surprise",
        "https://example.navy.mil/contrast",
    }
    assert "## Surprising fact" in script.brief_markdown(brief)


# ---------------------------------------------------------------------------
# Prompt: the v3 template plus the stateful context the design requires
# ---------------------------------------------------------------------------

def test_write_prompt_carries_brief_prior_paragraphs_and_next_machine():
    prompt = script.build_write_prompt(
        title=TITLE, thesis="The submarine stopped needing the surface.",
        acts=[{"act_number": 1, "argument": "The submarine learns to hide."}, {"act_number": 4, "argument": "The submarine stops surfacing."}],
        machine=MACHINE, act_number=4, act_thesis="The submarine stops surfacing.", scene=12, roster_size=24,
        brief_markdown=script.brief_markdown(_packet()),
        prior_paragraphs=[{"machine": SIBLING, "act_number": 1, "paragraph": "Holland proved a submarine could threaten without fighting."}],
        next_machine={"machine": "USS Thresher SSN-593", "act_number": 5, "problem": "Deeper diving demanded a new hull."},
    )
    assert "ENGINEERING DECISION" in prompt
    assert "95-120 words" in prompt
    assert "[Act 1] USS Holland SS-1: Holland proved" in prompt
    assert "NEXT MACHINE: USS Thresher SSN-593 (Act 5) - its problem: Deeper diving" in prompt
    assert "## Surprising fact" in prompt
    assert "never boat/boats" in prompt  # submarine context
    assert "bridged_to" in prompt


def test_write_prompt_first_paragraph_and_final_paragraph_edges():
    prompt = script.build_write_prompt(
        title="Every US Strategic Bomber Ever Built", thesis="t", acts=[], machine="Boeing B-52", act_number=1,
        act_thesis="", scene=1, roster_size=24, brief_markdown="", prior_paragraphs=[], next_machine=None,
    )
    assert "this is the first paragraph" in prompt
    assert "final paragraph of the video" in prompt
    assert "do NOT open with the machine's name by default" in prompt
    assert "never boat/boats" not in prompt


# ---------------------------------------------------------------------------
# write_paragraph: exactly one call, block shape, nothing can reject it
# ---------------------------------------------------------------------------

def _write(client, **overrides):
    kwargs = dict(
        title=TITLE, thesis="t", acts=[{"act_number": 4, "argument": "The submarine stops surfacing."}],
        roster=[SIBLING, MACHINE], machine=MACHINE, scene=2, act_number=4, brief=_packet(),
        prior_paragraphs=[], next_machine=None,
    )
    kwargs.update(overrides)
    return asyncio.run(script.write_paragraph(client, **kwargs))


def test_clean_draft_costs_exactly_one_call_and_passes():
    client = _Client(_draft(bridged_to="USS Holland SS-1"))
    block = _write(client)
    assert len(client.calls) == 1
    assert client.calls[0]["system_prompt"] == script.SYSTEM_PROMPT
    assert client.calls[0]["checkpoint_path"] is None  # no scope supplied
    assert block["passed"] is True
    assert block["machine_script_contract"] == script.SCRIPT_CONTRACT
    assert block["source_fingerprint"] == script.brief_fingerprint(MACHINE, _packet())
    assert block["bridged_to"] == SIBLING
    assert block["claim_map"] == [{"sentence": "She crossed under the North Pole in 1958, a voyage no earlier vessel could have attempted.",
                                   "source_url": "https://example.navy.mil/outcome1", "quote": "Outcome quote one."}]
    assert block["attempts"] == 1 and block["violations"] == []


def test_nothing_the_old_checker_rejected_is_rejected_any_more():
    """The code-side audit was removed 2026-09-22: no quality rule can block.

    This paragraph trips every hard rule the old checker had - hype, generic
    praise, a Wikipedia opening, conclusion language, a ranked-list connector
    and boat/boats in a submarine video. It must now be written in ONE call,
    with no repair call, and come back passed and intact.
    """
    bad = (
        "The Nautilus was a submarine built by Electric Boat in 1954. For fifty years every boat had been "
        "a surface ship that could hide. Nautilus, an incredible vessel and arguably the most important "
        "one, ended that bargain. Next came the polar run. In conclusion, she mattered."
    )
    client = _Client(_draft(bad))
    block = _write(client)
    assert len(client.calls) == 1, "a repair call was made; the repair loop should be gone"
    assert block["passed"] is True
    assert block["violations"] == []
    assert block["paragraph"] == bad, "the paragraph must be surfaced in full, unedited"
    assert block["attempts"] == 1


def test_claim_map_rows_citing_unknown_sources_are_dropped_with_a_warning():
    client = _Client(_draft(claim_map=[
        {"sentence": "x", "source_url": "https://example.navy.mil/outcome1", "quote": "q"},
        {"sentence": "y", "source_url": "https://invented.example/nope", "quote": "q"},
    ]))
    block = _write(client)
    assert [row["source_url"] for row in block["claim_map"]] == ["https://example.navy.mil/outcome1"]
    assert any("not in the brief" in w for w in block["warnings"])


def test_bridged_to_must_name_another_roster_machine():
    client = _Client(_draft(bridged_to="HMS Dreadnought"))
    block = _write(client)
    assert block["bridged_to"] is None
    assert any("bridged_to" in w for w in block["warnings"])


def test_unparseable_writer_response_fails_closed():
    client = _Client("not json at all")
    block = _write(client)
    assert block["passed"] is False and block["paragraph"] == ""
    assert len(client.calls) == 1


def test_checkpoint_scope_produces_a_stable_fingerprinted_path(tmp_path, monkeypatch):
    monkeypatch.setenv("STORYENGINE_RESEARCH_RESPONSE_DIR", str(tmp_path))
    client = _Client(_draft())
    _write(client, checkpoint_scope={"tenant_id": "t", "video_id": "v"})
    path = client.calls[0]["checkpoint_path"]
    assert path is not None and str(path).startswith(str(tmp_path))


# ---------------------------------------------------------------------------
# Readiness + the hand-written door
# ---------------------------------------------------------------------------

def _video(roster, blocks=None, packages=None, thesis="The submarine stopped needing the surface."):
    import pipeline_executor as pe
    payload = {
        "machine_discovery_buckets": {},
        "unit_roster": [{"machine": m, "act_number": i + 1} for i, m in enumerate(roster)],
        "thesis": thesis,
        "acts": [{"act_number": i + 1, "argument": f"Act {i + 1} argument."} for i in range(len(roster))],
        "machine_raw_source_packages": packages if packages is not None else {
            pe._verified_source_cache_key(m): _package(m) for m in roster
        },
    }
    return {
        "id": "v", "status": "ready_for_scripting", "video_title": TITLE, "render_mode": "static_docu",
        "research_payload": payload, "max_spend": None, "total_cost": 0,
        "script_validation": {"machine_script_blocks": blocks or {}},
    }


def _current_block(machine, scene, paragraph=GOOD_PARAGRAPH):
    return {
        "machine": machine, "scene": scene, "paragraph": paragraph, "passed": True,
        "machine_script_contract": script.SCRIPT_CONTRACT, "subject_context": TITLE,
        "source_fingerprint": script.brief_fingerprint(machine, _packet(machine)), "opened_with_name": False,
    }


def test_script_readiness_requires_a_current_passed_block_for_every_machine():
    roster = [SIBLING, MACHINE]
    assert script.script_readiness(_video(roster), roster) is False
    both = {SIBLING: _current_block(SIBLING, 1), MACHINE: _current_block(MACHINE, 2)}
    assert script.script_readiness(_video(roster, blocks=both), roster) is True
    stale = {**both, MACHINE: {**both[MACHINE], "source_fingerprint": "old"}}
    assert script.script_readiness(_video(roster, blocks=stale), roster) is False
    wrong_scene = {**both, MACHINE: {**both[MACHINE], "scene": 1}}
    assert script.script_readiness(_video(roster, blocks=wrong_scene), roster) is False
    legacy = {**both, MACHINE: {**both[MACHINE], "machine_script_contract": "factual_100_v1"}}
    assert script.script_readiness(_video(roster, blocks=legacy), roster) is False


def test_preview_readiness_names_the_missing_research_packet():
    video = _video([MACHINE], packages={})
    readiness = script.preview_readiness(video["research_payload"], MACHINE)
    assert readiness["ready"] is False
    assert "run per-machine research" in readiness["summary"]
    assert readiness["next_action"] == "run_one_machine_research_refresh"
    assert script.preview_readiness(_video([MACHINE])["research_payload"], MACHINE)["ready"] is True


def test_submitted_block_is_never_graded_and_makes_no_model_call():
    roster = [SIBLING, MACHINE]
    video = _video(roster)
    block = script.submitted_block(video, roster, MACHINE, "  " + GOOD_PARAGRAPH + "  ")
    assert block["passed"] is True and block["paragraph"] == GOOD_PARAGRAPH
    assert block["research_source"] == "hand_submitted" and block["scene"] == 2
    assert block["source_fingerprint"] == script.brief_fingerprint(MACHINE, _packet())
    # A hand-written paragraph that would have failed every old rule is kept.
    once_rejected = script.submitted_block(
        video, roster, MACHINE, GOOD_PARAGRAPH + " In conclusion, she was an incredible boat."
    )
    assert once_rejected["passed"] is True and once_rejected["violations"] == []


# ---------------------------------------------------------------------------
# run_script_hold: the orchestration, driven through a fake executor
# ---------------------------------------------------------------------------

@pytest.fixture
def hold(monkeypatch):
    import pipeline_executor as pe

    def _make(roster, blocks=None, packages=None, client=None):
        video = _video(roster, blocks=blocks, packages=packages)
        state = {"video": video, "status_writes": [], "saved": [], "previews": []}

        ex = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
        ex.tenant_id = "t"
        ex._pipeline = SimpleNamespace(anthropic=client, should_cancel=AsyncMock(return_value=False))
        ex._get_video = AsyncMock(side_effect=lambda _vid: json.loads(json.dumps(state["video"])))
        ex._load_machine_research_cards = AsyncMock(side_effect=lambda _v, p, _r, **kw: p)
        ex._log_activity = AsyncMock()
        ex._log_transition = AsyncMock()
        ex._skip_disabled_next = lambda _video, natural: natural

        async def _checkpoint(video_id, key, preview, snapshot):
            state["previews"].append((key, preview))
            return "UPDATE 1"
        ex._checkpoint_machine_script_preview = _checkpoint

        async def _save(*, video_id, video, roster, script_block, title, voice_id, advance_status=True):
            state["saved"].append((script_block["machine"], advance_status))
            blocks_now = dict(state["video"]["script_validation"].get("machine_script_blocks") or {})
            saved = {**script_block, "saved": True}
            blocks_now[script_block["machine"]] = saved
            state["video"]["script_validation"]["machine_script_blocks"] = blocks_now
            return saved
        ex._save_machine_script_block = _save

        async def _execute(sql, *args):
            if sql.startswith("UPDATE videos SET status="):
                state["status_writes"].append(args[0])
                state["video"]["status"] = args[0]
            return "UPDATE 1"
        monkeypatch.setattr(pe, "execute", _execute)
        monkeypatch.setattr(pe, "fetch_all", AsyncMock(return_value=[{"voice_id": "voice-x"}]))
        monkeypatch.setattr(script, "export_script_to_drive_fail_soft", AsyncMock(return_value=None))
        return ex, state
    return _make


def test_target_preview_writes_one_paragraph_checkpoints_it_and_saves_nothing(hold):
    roster = [SIBLING, MACHINE]
    client = _Client(_draft())
    ex, state = hold(roster, client=client)
    result = asyncio.run(script.run_script_hold(ex, "v", state["video"], roster, target_machine=MACHINE))
    assert result["status"] == "completed" and result["preview"]["passed"] is True
    assert len(client.calls) == 1
    assert state["saved"] == []
    import pipeline_executor as pe
    assert [key for key, _ in state["previews"]] == [pe._verified_source_cache_key(MACHINE)]
    assert state["status_writes"] == []
    assert "machine_script_previews" in result["research_payload"]


def test_target_block_saves_the_scene_and_lets_the_save_helper_advance(hold):
    roster = [MACHINE]
    client = _Client(_draft())
    ex, state = hold(roster, client=client)
    result = asyncio.run(script.run_script_hold(ex, "v", state["video"], roster, target_machine=MACHINE, save_target_script=True))
    assert result["status"] == "completed" and result["script_block"]["saved"] is True
    assert state["saved"] == [(MACHINE, True)]


def test_bulk_run_reuses_current_blocks_without_spend_and_advances_when_complete(hold):
    roster = [SIBLING, MACHINE]
    client = _Client(_draft(bridged_to=SIBLING))
    ex, state = hold(roster, blocks={SIBLING: _current_block(SIBLING, 1)}, client=client)
    result = asyncio.run(script.run_script_hold(ex, "v", state["video"], roster))
    assert result["status"] == "completed" and result["new_status"] == "ready_for_voice"
    assert len(client.calls) == 1  # Holland was current: no spend
    # The prior paragraph reached the writer as context, with its act.
    assert f"[Act 1] {SIBLING}: {GOOD_PARAGRAPH}" in client.calls[0]["prompt"]
    assert "NEXT MACHINE: none" in client.calls[0]["prompt"]
    assert state["saved"] == [(MACHINE, False)]
    assert state["status_writes"] == ["ready_for_voice"]
    ex._log_transition.assert_awaited_once()


def test_bulk_run_passes_every_prior_paragraph_and_the_next_machines_problem(hold):
    roster = [SIBLING, MACHINE, "USS Thresher SSN-593"]
    client = _Client(_draft(GOOD_PARAGRAPH.replace("Nautilus", "Holland")), _draft(), _draft(GOOD_PARAGRAPH.replace("Nautilus", "Thresher")))
    ex, state = hold(roster, client=client)
    result = asyncio.run(script.run_script_hold(ex, "v", state["video"], roster))
    assert result["status"] == "completed"
    assert "NEXT MACHINE: USS Nautilus SSN-571 (Act 2) - its problem: Diesel submarines" in client.calls[0]["prompt"]
    third = client.calls[2]["prompt"]
    assert f"[Act 1] {SIBLING}:" in third and f"[Act 2] {MACHINE}:" in third


def test_bulk_run_saves_and_advances_even_when_a_paragraph_breaks_the_old_rules(hold):
    """No paragraph is withheld any more; the run completes and advances."""
    roster = [SIBLING, MACHINE]
    bad = GOOD_PARAGRAPH.replace("Nautilus ended that bargain", "Nautilus, an incredible vessel, ended that bargain")
    holland = GOOD_PARAGRAPH.replace("Nautilus", "Holland")
    client = _Client(_draft(holland), _draft(bad))
    ex, state = hold(roster, client=client)
    result = asyncio.run(script.run_script_hold(ex, "v", state["video"], roster))
    assert result["status"] == "completed"
    assert len(client.calls) == 2, "no repair call should be made"
    assert [machine for machine, _ in state["saved"]] == [SIBLING, MACHINE]
    saved_preview = [p for key, p in state["previews"] if p["machine"] == MACHINE][-1]
    assert saved_preview["passed"] is True and saved_preview["paragraph"] == bad


def test_bulk_run_still_stops_when_the_writer_returns_nothing_usable(hold):
    """A transport failure is not a quality judgement - there is no text to save."""
    roster = [SIBLING, MACHINE]
    holland = GOOD_PARAGRAPH.replace("Nautilus", "Holland")
    client = _Client(_draft(holland), "not json at all")
    ex, state = hold(roster, client=client)
    result = asyncio.run(script.run_script_hold(ex, "v", state["video"], roster))
    assert result["status"] == "needs_review"
    assert [machine for machine, _ in state["saved"]] == [SIBLING]
    assert state["status_writes"] == []


def test_missing_research_packet_is_a_clear_needs_review_not_a_crash(hold):
    roster = [MACHINE]
    client = _Client()
    ex, state = hold(roster, packages={}, client=client)
    result = asyncio.run(script.run_script_hold(ex, "v", state["video"], roster, target_machine=MACHINE))
    assert result["status"] == "completed" and result["preview"]["passed"] is False
    assert "run per-machine research" in result["preview"]["warnings"][0]
    assert client.calls == []
    bulk = asyncio.run(script.run_script_hold(ex, "v", state["video"], roster))
    assert bulk["status"] == "needs_review" and "run per-machine research" in bulk["error"]


def test_hold_refuses_without_an_anthropic_client(hold):
    roster = [MACHINE]
    ex, state = hold(roster, client=None)
    result = asyncio.run(script.run_script_hold(ex, "v", state["video"], roster))
    assert result["status"] == "failed" and "Anthropic client" in result["error"]


def test_budget_cap_pauses_before_any_call(hold):
    roster = [MACHINE]
    client = _Client(_draft())
    ex, state = hold(roster, client=client)
    state["video"]["max_spend"] = 1.0
    state["video"]["total_cost"] = 1.0
    result = asyncio.run(script.run_script_hold(ex, "v", state["video"], roster))
    assert result["status"] == "paused" and client.calls == []


def test_script_markdown_lists_every_machine_in_roster_order():
    roster = [SIBLING, MACHINE]
    text = script.script_markdown(TITLE, roster, {SIBLING: _current_block(SIBLING, 1)}, {SIBLING: 1, MACHINE: 4})
    assert text.index(f"### 1. {SIBLING} (Act 1)") < text.index(f"### 2. {MACHINE} (Act 4)")
    assert "(not written)" in text


# ---------------------------------------------------------------------------
# Wiring: the executor has exactly one script path and the legacy ones are gone
# ---------------------------------------------------------------------------

def test_executor_static_script_hold_delegates_to_the_v2_writer(monkeypatch):
    import pipeline_executor as pe
    calls = []

    async def _fake(ex, video_id, video, roster, target_machine=None, save_target_script=False):
        calls.append((video_id, roster, target_machine, save_target_script))
        return {"status": "completed"}
    monkeypatch.setattr(script, "run_script_hold", _fake)
    ex = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    ex.tenant_id = "t"
    result = asyncio.run(ex._run_static_script_hold("v", {"research_payload": {}}, [MACHINE], target_machine=MACHINE, save_target_script=True))
    assert result == {"status": "completed"}
    assert calls == [("v", [MACHINE], MACHINE, True)]


def test_legacy_script_writers_do_not_exist_anymore():
    import pipeline_executor as pe
    # _machine_story_plan itself survives only because the Research tab's
    # repair-promote-excerpt route still calls it (follow-up, see HANDOFF.md).
    for name in ("_validate_machine_story_sentences", "_apply_dvsu_language_polish", "_anton_preview_quality_audit",
                 "_anton_inventory_title_mode", "_deterministic_beat_plan", "_parse_planned_story_sentences",
                 "_classify_opener_type", "_persist_machine_script_attempt_state", "_telemetry_quality_critique"):
        assert not hasattr(pe, name), name
    import factual_machine_pipeline as fmp
    for name in ("run_factual_script_hold", "factual_script_readiness", "_expected_script_packet"):
        assert not hasattr(fmp, name), name
    import factual_machine_summary as fms
    for name in ("_script_writer_prompt", "generate_factual_machine_summary", "review_existing_factual_summary", "_review_prompt"):
        assert not hasattr(fms, name), name
    source = Path(pe.__file__).read_text(encoding="utf-8")
    hold_source = source.split("async def _run_static_script_hold")[1].split("\n    async def ")[0]
    assert 'machine_script_contract") == "factual_100_v1"' not in hold_source  # no contract-flag dispatch
    assert "run_factual_script_hold" not in hold_source and "complete_inventory_mode" not in hold_source


def test_run_script_arms_cancel_support_and_relay_binding():
    """Live find (2026-09-22): run_script never called _install_cancel_support, so the
    v2 writer's per-machine cancel check was a no-op and every relay request it parked
    carried video_id=None. The preview/research entries already arm it; run_script must too."""
    import inspect

    import pipeline_executor as executor

    source = inspect.getsource(executor.PipelineExecutor.run_script)
    arm = source.index("await self._install_cancel_support(video_id)")
    first_video_read = source.index("await self._get_video(video_id)")
    assert arm < first_video_read
