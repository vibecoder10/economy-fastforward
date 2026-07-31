"""Tests for G8 (DVsU bulletproof API pipeline loop, chunk "engine-side
per-machine research loop"): a static_docu build with a multi-unit roster
must complete its research stage HANDS-FREE on the pipeline's own API path.

Live bug this pins the fix for (video d05efae3-46f8-4ee3-b690-849c3ca31fbc):
Research Agent ran, roster discovery found the 5 locked ships, then
pipeline_executor.py's untargeted bulk per-machine hold (INSIDE run_research)
tripped its own hallucination-safety gate ("Bulk DVsU machine-card generation
is disabled...", commit e945c762) because no verified per-machine card
existed yet for any roster machine — and actions.make_autobuild_step's
static_docu branch treated that as a hard failure, parking the video with
no research and no visible progress.

The fix (actions.py, make_autobuild_step's nested
`_run_static_docu_roster_research`): when run_research fails specifically
because the roster passed validation but the untargeted bulk hold was
refused, walk the SAME locked roster — using the gate's own persisted
per-machine breakdown (research_payload.unit_research_hold_validation.units)
as the enumeration — through the identical safe verified one-machine path a
human satisfies by hand at POST /machine-research-one/{video_id}
(PipelineExecutor.run_one_machine_research), one machine at a time. The bulk
gate itself is never bypassed or weakened; this only supplies, from inside
the engine, the exact same per-machine calls a human would otherwise have to
click through one by one.

Covers:
  (a) a 3-machine fake roster -> the loop calls run_one_machine_research
      once per machine, IN ORDER, all pass -> status advances to
      ready_for_scripting via the same _advance() the research-skip path uses.
  (b) machine 2 fails referee review -> the loop still attempts machine 3
      (continue-through, not abort-on-first-failure — see
      test_machine_2_failure_does_not_abort_remaining_roster's docstring for
      the product-logic justification), and the final park message names
      machine 2 and its warning.
  (c) the video's spend cap is reached after machine 1 completes -> the loop
      stops BEFORE calling run_one_machine_research for machine 2, with a
      clean "1/3 done" pause message — proven by the fake client/executor
      never being asked for machine 2 or 3 at all (no wasted paid calls).
  (d) the per-machine progress messages ("Researching machine 2/3: ...") are
      emitted in order via the same _set_task_status channel every other
      autobuild stage uses.
  (e) safe-to-merge guardrails: when this ISN'T the "roster passed, bulk hold
      refused" shape (no locked roster at all, or the roster validation
      itself failed), the new loop is a no-op — the ORIGINAL failure message
      fires, byte-identical to before G8, and run_one_machine_research is
      never called. This is the proof that non-roster and roster-invalid
      static_docu builds — and every non-static_docu build, which never
      reaches this branch at all — take the identical path as before.

No network, no real DB, no real Anthropic client: `pipeline_executor` and
`routes.pipeline` are faked via sys.modules stubs (same pattern as
test_autobuild_explicit_research_plan.py); `database.execute`/`fetch_one` are
monkeypatched on the already-imported `actions` module (same pattern as
test_c36_budget_cap.py). The fake PipelineExecutor's run_one_machine_research
records every call it receives so a test can assert the exact call count and
order — proving "no further model calls" for the budget-cap case and
"continues past a failure" for the referee-failure case without spending a
cent or touching a real Anthropic client.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_g8_roster_research_loop.py -q
"""
import asyncio
import os
import sys
import types
from unittest.mock import patch

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import actions  # noqa: E402

TENANT = "tenant-1"
VIDEO = "video-1"

_ROSTER = ["Machine A", "Machine B", "Machine C"]


def _units(passed_map=None):
    passed_map = passed_map or {}
    return [{"machine": m, "passed": bool(passed_map.get(m, False))} for m in _ROSTER]


def _video_after_research(units):
    """What ex._get_video would return right after run_research persisted a
    roster that PASSED validation but whose untargeted bulk hold was refused
    (research_payload already written — see pipeline_executor.run_research's
    own "the roster is ALREADY PERSISTED above" comment)."""
    return {
        "status": "idea_logged",
        "render_mode": "static_docu",
        "research_payload": {
            "unit_roster_validation": {"passed": True},
            "unit_research_hold_validation": {"passed": False, "units": units},
        },
    }


class _FakeExecutor:
    """Stands in for PipelineExecutor - only what the static_docu research
    branch + the new roster loop touch."""

    def __init__(self, tenant_id, after_research_row, machine_results=None):
        self.tenant_id = tenant_id
        self._after_research_row = after_research_row
        self.machine_results = machine_results or {}
        self.calls = 0
        self.machine_calls: list[str] = []
        self.run_research_call_count = 0

    async def _get_video(self, video_id):
        self.calls += 1
        if self.calls == 1:
            # First fetch of the outer autobuild loop: a fresh static_docu
            # video, comfortably under any cap so the OUTER pre-stage cap
            # check (unrelated to G8) never trips.
            return {
                "status": "idea_logged", "render_mode": "static_docu",
                "max_spend": None, "total_cost": 0.0,
            }
        if self.calls == 2:
            # The new loop's own fetch, reading what run_research persisted.
            return dict(self._after_research_row)
        # Any later fetch (the outer loop's NEXT iteration after we advance
        # status) reports a status outside BUILD_TO_PICTURES so the loop
        # stops cleanly — only the research stage itself is under test here
        # (same technique test_autobuild_explicit_research_plan.py uses).
        return {"status": "ready_for_images", "render_mode": "static_docu"}

    async def run_research(self, video_id):
        self.run_research_call_count += 1
        # Simulates the real pipeline_executor.run_research: roster discovery
        # + validation passed, but the untargeted bulk per-machine hold
        # tripped its own hallucination-safety gate.
        return {
            "status": "failed",
            "error": "Research gate failed; not advancing to scripting: Unit research-hold failed",
        }

    async def run_one_machine_research(self, video_id, machine):
        self.machine_calls.append(machine)
        result = self.machine_results.get(machine, {"status": "completed"})
        if callable(result):
            result = result()
        return dict(result)


def _stub_pipeline_and_routes(fake_executor_factory):
    fake_pe = types.ModuleType("pipeline_executor")
    fake_pe.PipelineExecutor = fake_executor_factory
    statuses: list[tuple] = []

    def _fake_set_task_status(video_id, status, message, tenant_id=None):
        statuses.append((status, message))

    fake_rp = types.ModuleType("routes.pipeline")
    fake_rp._set_task_status = _fake_set_task_status
    fake_rp._clear_task_status = lambda *a, **k: None
    return fake_pe, fake_rp, statuses


def _run_autobuild(after_research_row, machine_results=None, cap_probe=None):
    """Drive actions.make_autobuild_step(...)() against the fakes.

    cap_probe: optional callable(query, args) -> Optional[dict] consulted
    for the "SELECT max_spend, total_cost FROM videos" cap-recheck query the
    new loop issues before EACH machine; None means "no cap" (never pauses).
    """
    executed = []
    holder = []

    def _factory(tenant_id):
        ex = _FakeExecutor(tenant_id, after_research_row, machine_results)
        holder.append(ex)
        return ex

    fake_pe, fake_rp, statuses = _stub_pipeline_and_routes(_factory)

    async def fake_execute(query, *args):
        executed.append((query, args))
        return "UPDATE 1"

    async def fake_fetch_one(query, *args):
        if "pipeline_stages" in query:
            return {"pipeline_stages": None}
        if "SELECT status FROM videos" in query:
            return {"status": "idea_logged"}
        if "max_spend, total_cost" in query:
            if cap_probe is not None:
                return cap_probe(query, args)
            return {"max_spend": None, "total_cost": 0.0}
        return None

    async def _fast_sleep(*_a, **_k):
        return None

    with patch.object(actions, "execute", fake_execute), \
         patch.object(actions, "fetch_one", fake_fetch_one), \
         patch.dict(sys.modules, {"pipeline_executor": fake_pe, "routes.pipeline": fake_rp}), \
         patch("asyncio.sleep", _fast_sleep):
        step = actions.make_autobuild_step(TENANT, VIDEO, target="pictures")
        asyncio.run(step())
    return holder[0], statuses, executed


# --- (a) all three machines pass, in order, status advances -----------------

def test_all_machines_pass_in_order_and_status_advances():
    units = _units()  # all pending
    ex, statuses, executed = _run_autobuild(_video_after_research(units))

    assert ex.machine_calls == _ROSTER, (
        f"expected run_one_machine_research called once per machine IN ORDER, got {ex.machine_calls}"
    )
    assert ex.run_research_call_count == 1, "run_research must run exactly once, not per machine"

    advance_writes = [
        (q, a) for (q, a) in executed
        if "UPDATE videos SET status" in q and len(a) >= 1 and a[0] == "ready_for_scripting"
    ]
    assert advance_writes, f"expected _advance('ready_for_scripting') to write the status, got {executed}"

    # The loop must never itself report a terminal failure/pause — the
    # outer loop's own next iteration (a plain status check) is what ends it.
    terminal = [s for s, _m in statuses if s in ("failed",)]
    assert not terminal, f"a fully-passing roster must not surface a failed task status, got {statuses}"
    print("✅ test_all_machines_pass_in_order_and_status_advances")


# --- (d) progress messages sequence -----------------------------------------

def test_progress_messages_sequence_names_each_machine():
    units = _units()
    _ex, statuses, _executed = _run_autobuild(_video_after_research(units))

    progress = [m for (_s, m) in statuses if m and m.startswith("Researching machine")]
    assert progress == [
        "Researching machine 1/3: Machine A",
        "Researching machine 2/3: Machine B",
        "Researching machine 3/3: Machine C",
    ], progress
    print("✅ test_progress_messages_sequence_names_each_machine")


# --- (b) machine 2 fails referee review -------------------------------------

def test_machine_2_failure_does_not_abort_remaining_roster():
    """Product-logic choice: continue past a referee failure rather than
    abort the whole loop on the first bad machine. Rationale: a research
    referee failure is a content-quality gate, not a systemic/API failure —
    the remaining machines are independent research calls with their own
    independent chance of passing, and walking all of them in one pass lets
    the park message name EVERY machine that needs a look at once, instead of
    a human running the build, hitting machine 2, fixing it, re-running,
    hitting machine 4, fixing it, re-running... This mirrors the existing
    run_roster_orchestrator's own "keep walking, only break on a genuine
    systemic (3-in-a-row) failure" design one level down; G8 doesn't need
    that circuit breaker because the OTHER existing guard (the per-machine
    budget cap check, see test_c below) already bounds runaway spend on a
    systemically broken pass."""
    units = _units()
    machine_results = {
        "Machine B": {"status": "needs_review", "warnings": ["dates not corroborated by two sources"]},
    }
    ex, statuses, _executed = _run_autobuild(_video_after_research(units), machine_results)

    assert ex.machine_calls == _ROSTER, (
        f"machine 3 must still be attempted after machine 2 fails, got {ex.machine_calls}"
    )
    # The fake _set_task_status here records the raw status make_autobuild_step
    # passes it ("needs_review") — the REAL routes.pipeline._set_task_status
    # normalizes that to "completed" + an additive needs_review=True flag
    # (see its own C-frontdoor2 docstring: exactly the existing "a quality
    # gate rejected some content, park it for a look" bucket, not a hard
    # crash). Asserting the raw value proves make_autobuild_step chose that
    # bucket deliberately rather than "failed".
    parked = [(s, m) for (s, m) in statuses if s == "needs_review" and m and "Machine B" in m]
    assert parked, f"expected a parked needs_review message naming Machine B, got {statuses}"
    _status, message = parked[-1]
    assert "2/3" in message, message
    assert "dates not corroborated by two sources" in message, message
    print("✅ test_machine_2_failure_does_not_abort_remaining_roster")


# --- (c) budget cap reached after machine 1 ---------------------------------

def test_budget_cap_reached_after_machine_one_stops_before_machine_two():
    units = _units()
    state = {"machine_one_done": False}

    def cap_probe(_query, _args):
        # Before machine 1: comfortably under. After machine 1 completes:
        # already at/over the cap (simulates spend recorded elsewhere in
        # this same build pushing total_cost over the video's cap).
        if state["machine_one_done"]:
            return {"max_spend": 5.0, "total_cost": 10.0}
        return {"max_spend": 5.0, "total_cost": 0.0}

    original_run_one = _FakeExecutor.run_one_machine_research

    async def run_one_and_flag(self, video_id, machine):
        result = await original_run_one(self, video_id, machine)
        if machine == "Machine A":
            state["machine_one_done"] = True
        return result

    with patch.object(_FakeExecutor, "run_one_machine_research", run_one_and_flag):
        ex, statuses, _executed = _run_autobuild(
            _video_after_research(units), cap_probe=cap_probe)

    assert ex.machine_calls == ["Machine A"], (
        f"the cap must stop the loop BEFORE machine 2 (no further model calls), got {ex.machine_calls}"
    )
    paused = [(s, m) for (s, m) in statuses if s == "completed" and m and "Paused" in m]
    assert paused, f"expected a clean pause message, got {statuses}"
    _status, message = paused[-1]
    assert "1/3" in message, message
    assert "$10.00" in message and "$5.00" in message, message
    print("✅ test_budget_cap_reached_after_machine_one_stops_before_machine_two")


# --- (e) safe-to-merge: not this loop's job -> byte-identical old failure ---

def test_no_locked_roster_falls_back_to_original_failure_message():
    """research_payload has no unit_research_hold_validation at all (e.g. a
    single/no-roster static_docu video, or a roster below the 3-40 lock
    bound) -> the new loop is a no-op; the ORIGINAL failure message fires
    and run_one_machine_research is never called."""
    row = {
        "status": "idea_logged", "render_mode": "static_docu",
        "research_payload": {},
    }
    ex, statuses, _executed = _run_autobuild(row)

    assert ex.machine_calls == [], "must never call run_one_machine_research when there's no locked roster"
    failed = [(s, m) for (s, m) in statuses if s == "failed"]
    assert failed, f"expected the original research-failed status, got {statuses}"
    _status, message = failed[-1]
    assert "Unit research-hold failed" in message, message
    print("✅ test_no_locked_roster_falls_back_to_original_failure_message")


def test_roster_validation_itself_failed_falls_back_to_original_failure_message():
    """The roster gate itself failed (not the per-machine hold) -> also not
    this loop's job; same byte-identical fallback."""
    row = {
        "status": "idea_logged", "render_mode": "static_docu",
        "research_payload": {
            "unit_roster_validation": {"passed": False, "warnings": ["roster too small"]},
        },
    }
    ex, statuses, _executed = _run_autobuild(row)

    assert ex.machine_calls == []
    failed = [(s, m) for (s, m) in statuses if s == "failed"]
    assert failed, statuses
    print("✅ test_roster_validation_itself_failed_falls_back_to_original_failure_message")


if __name__ == "__main__":
    test_all_machines_pass_in_order_and_status_advances()
    test_progress_messages_sequence_names_each_machine()
    test_machine_2_failure_does_not_abort_remaining_roster()
    test_budget_cap_reached_after_machine_one_stops_before_machine_two()
    test_no_locked_roster_falls_back_to_original_failure_message()
    test_roster_validation_itself_failed_falls_back_to_original_failure_message()
    print("All G8 roster-research-loop tests passed!")
