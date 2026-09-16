"""Offline guards for factual-summary Run All completion and task status."""
import asyncio
import sys
import types
from unittest.mock import patch

import actions


TENANT = "tenant-test"
VIDEO = "video-test"


def _summary(current=True):
    return {"current": current}


def _factual_payload(*, attempts=None, runtime_selected=False):
    roster = [f"Machine {index}" for index in range(1, 21)]
    return {
        "machine_script_contract": "factual_100_v1",
        "unit_roster": roster,
        "unit_roster_validation": {"passed": True},
        # Deliberately incomplete: legacy behavior used this as the whole roster.
        "unit_research_hold_validation": {
            "passed": False,
            "units": [{"machine": "Machine 1", "passed": True}, {"machine": "Machine 2", "passed": False}],
        },
        "unit_research_cards": [{"unit": "Machine 1", "research_summary": _summary()}],
        "roster_loop_attempts": attempts or {},
    }
    if runtime_selected:
        payload.update({
            "roster_selection": {"version": 1, "status": "completed"},
            "research_phase": "roster_complete",
        })
    return payload


class _Executor:
    def __init__(self, _tenant, payload, machine_results=None, runtime_selected=False):
        self.payload = payload
        self.machine_results = machine_results or {}
        self.runtime_selected = runtime_selected
        self.calls = 0
        self.machine_calls = []

    async def _get_video(self, _video_id):
        self.calls += 1
        if self.calls == 1 and self.runtime_selected:
            return {"status": "idea_logged", "render_mode": "static_docu", "max_spend": None,
                    "total_cost": 0, "video_title": "Every Machine", "research_payload": self.payload}
        if self.calls <= 2:
            return {"status": "idea_logged", "render_mode": "static_docu", "max_spend": None,
                    "total_cost": 0, "video_title": "Every Machine", "research_payload": self.payload}
        return {"status": "ready_for_images", "render_mode": "static_docu"}

    async def run_research(self, _video_id):
        return {"status": "failed", "error": "Research gate failed; not advancing to scripting: Unit research-hold failed"}

    async def run_one_machine_research(self, _video_id, machine):
        self.machine_calls.append(machine)
        result = self.machine_results.get(machine, {"status": "completed"})
        if isinstance(result, BaseException):
            raise result
        if result.get("status") == "completed" and not result.get("no_save"):
            units = self.payload["unit_research_hold_validation"]["units"]
            existing = next((unit for unit in units if unit.get("machine") == machine), None)
            if existing is None:
                units.append({"machine": machine, "passed": True})
            else:
                existing["passed"] = True
            cards = self.payload.setdefault("unit_research_cards", [])
            if not any(card.get("unit") == machine for card in cards):
                cards.append({"unit": machine, "research_summary": _summary()})
        return dict(result)


def _run(payload, *, summary_version=1, machine_results=None, runtime_selected=False):
    holder, statuses, writes = [], [], []

    def factory(tenant):
        executor = _Executor(tenant, payload, machine_results, runtime_selected)
        holder.append(executor)
        return executor

    fake_pipeline = types.ModuleType("pipeline_executor")
    fake_pipeline.PipelineExecutor = factory
    fake_pipeline._verified_source_package_for_machine = lambda _payload, machine: {"machine": machine}
    fake_pipeline._machine_documentary_hold_roster = lambda video: list(
        (video.get("research_payload") or {}).get("unit_roster") or []
    )
    fake_research = types.ModuleType("factual_machine_research")
    fake_research.is_factual_machine_contract = lambda payload: payload.get("machine_script_contract") == "factual_100_v1"
    fake_summary = types.ModuleType("machine_research_summary")
    fake_summary.RESEARCH_SUMMARY_VERSION = summary_version
    fake_summary.research_summary_ready = lambda _machine, _package, summary, _context: bool((summary or {}).get("current"))
    fake_summary.is_recoverable_research_error = lambda exc: isinstance(exc, (TimeoutError, ConnectionError))
    fake_factual_pipeline = types.ModuleType("factual_machine_pipeline")
    def factual_readiness(current_payload, roster, subject_context=""):
        units = {unit.get("machine"): unit for unit in current_payload.get("unit_research_hold_validation", {}).get("units", [])}
        cards = {card.get("unit"): card for card in current_payload.get("unit_research_cards", [])}
        return bool(roster) and all(
            units.get(machine, {}).get("passed") and cards.get(machine, {}).get("research_summary", {}).get("current")
            for machine in roster
        )
    fake_factual_pipeline.factual_research_readiness = factual_readiness
    fake_routes = types.ModuleType("routes.pipeline")
    fake_routes._set_task_status = lambda _video, status, message, tenant_id=None: statuses.append((status, message))
    fake_routes._clear_task_status = lambda *_args, **_kwargs: None
    fake_images = types.ModuleType("roster_images")
    async def roster_image_state(*_args, **_kwargs):
        return {"status": "completed"}
    fake_images.roster_image_state = roster_image_state

    async def execute(query, *args):
        writes.append((query, args))
        return "UPDATE 1"

    async def fetch_one(query, *_args):
        if "pipeline_stages" in query:
            return {"pipeline_stages": None}
        if "SELECT status FROM videos" in query:
            return {"status": "idea_logged"}
        if "max_spend, total_cost" in query:
            return {"max_spend": None, "total_cost": 0}
        return None

    async def no_coverage(*_args, **_kwargs):
        return False

    async def fast_sleep(*_args, **_kwargs):
        return None

    with patch.object(actions, "execute", execute), patch.object(actions, "fetch_one", fetch_one), \
         patch.object(actions, "_static_image_coverage_missing", no_coverage), \
         patch.object(actions, "_factual_image_recheck_needed", no_coverage), \
         patch.dict(sys.modules, {"pipeline_executor": fake_pipeline, "factual_machine_research": fake_research,
                                  "machine_research_summary": fake_summary, "routes.pipeline": fake_routes,
                                  "roster_images": fake_images, "factual_machine_pipeline": fake_factual_pipeline}), \
         patch("asyncio.sleep", fast_sleep):
        asyncio.run(actions.make_autobuild_step(TENANT, VIDEO, target="pictures")())
    return holder[0], statuses, writes


def test_factual_run_all_enumerates_full_locked_roster_not_partial_verdicts():
    executor, _statuses, _writes = _run(_factual_payload())
    assert executor.machine_calls == [f"Machine {index}" for index in range(2, 21)]


def test_factual_run_all_enumerates_full_locked_roster_with_zero_verdicts():
    payload = _factual_payload()
    payload["unit_research_hold_validation"]["units"] = []
    payload["unit_research_cards"] = []
    executor, _statuses, _writes = _run(payload)
    assert executor.machine_calls == [f"Machine {index}" for index in range(1, 21)]


def test_factual_current_summary_is_not_rerun_and_legacy_scalar_gets_one_bounded_retry():
    payload = _factual_payload(attempts={"Machine 2": 2})
    executor, statuses, writes = _run(
        payload,
        machine_results={"Machine 2": {"status": "needs_review", "warnings": ["missing source"]}},
    )
    assert "Machine 1" not in executor.machine_calls
    assert executor.machine_calls == ["Machine 2"] + [f"Machine {index}" for index in range(3, 21)]
    assert any("roster_loop_attempts" in query for query, _args in writes)
    parked = [message for status, message in statuses if status == "needs_review"]
    assert parked and "Machine 2" in parked[-1] and "Open Research" in parked[-1]


def test_factual_same_version_cap_parks_but_new_summary_version_can_retry_once():
    identity_v1 = "factual-summary:factual_100_v1:summary-v1:automation-v1"
    payload = _factual_payload(attempts={"Machine 2": {identity_v1: 2}})
    executor, _statuses, _writes = _run(payload, summary_version=1)
    assert "Machine 2" not in executor.machine_calls

    executor, _statuses, _writes = _run(payload, summary_version=2)
    assert "Machine 2" in executor.machine_calls


def test_runtime_factual_run_all_skips_bulk_and_respects_exhausted_machine_cap():
    identity = "factual-summary:factual_100_v1:summary-v1:automation-v1"
    payload = _factual_payload(
        runtime_selected=True,
        attempts={"Machine 2": {identity: 2}},
    )
    executor, statuses, _writes = _run(payload, runtime_selected=True)
    assert "Machine 2" not in executor.machine_calls
    assert not hasattr(executor, "run_unit_research")
    assert any(status == "needs_review" for status, _message in statuses)


def test_factual_transient_machine_failure_is_saved_and_other_machines_continue():
    payload = _factual_payload()
    executor, _statuses, writes = _run(
        payload,
        machine_results={"Machine 2": TimeoutError("network timeout")},
    )
    assert executor.machine_calls == [f"Machine {index}" for index in range(2, 21)]
    assert any("roster_loop_attempts" in query for query, _args in writes)


def test_factual_completed_result_without_saved_summary_never_advances_script():
    payload = _factual_payload()
    _executor, statuses, writes = _run(
        payload,
        machine_results={"Machine 2": {"status": "completed", "no_save": True}},
    )
    # The worker claim is insufficient: readback requires the saved summary.
    assert any(status == "needs_review" for status, _message in statuses)
    assert not any("ready_for_scripting" in query for query, _args in writes)
