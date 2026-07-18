"""Lock: default autobuild records research_skipped instead of lying silently
(C06, checklist P0.5).

Before this fix, actions.make_autobuild_step skipped the optional research
step for every non-static_docu video (idea_logged/approved -> straight to
ready_for_scripting) with no trace anywhere that it happened - the creator had
no way to know their video wasn't researched. This pins:

  1. The skip branch (non-static_docu) writes `UPDATE videos SET
     research_skipped = TRUE ...` for the video before advancing - the fact
     the checklist requires recording.
  2. The static_docu branch (which DOES run research first, always) never
     writes research_skipped = TRUE, and calls PipelineExecutor.run_research.
  3. The non-static branch never calls run_research (the "keep the default"
     half of the requirement - WHEN research runs is unchanged).

No network, no real DB: `database`, `pipeline_executor`, and `routes.pipeline`
are stubbed with the same module-stub pattern used by
test_producer_kie_fallback.py. `status_map` imports for real (pure functions,
no external deps), so resolve_planned_status/parse_stage_plan run their
genuine logic against the stub's fetch_one responses.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_research_skipped_chip.py -q
"""
import asyncio
import os
import sys
import types
from unittest.mock import patch

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, _BACKEND)


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


# --- database stub (actions.py imports execute/fetch_one eagerly at module
# load, so this must be in place BEFORE `import actions`) ---------------------

EXECUTED = []


async def _fake_execute(query, *args):
    EXECUTED.append((query, args))
    return "UPDATE 1"


async def _fake_fetch_one(query, *args):
    if "pipeline_stages" in query:
        return {"pipeline_stages": None}
    if "SELECT status FROM videos" in query:
        return {"status": "idea_logged"}
    return None


_stub("database", execute=_fake_execute, fetch_one=_fake_fetch_one)

import actions  # noqa: E402


# --- fakes for the two lazy imports inside make_autobuild_step ---------------

class _FakeExecutor:
    """Stands in for PipelineExecutor - only what the idea_logged/approved
    branch of make_autobuild_step touches."""

    def __init__(self, tenant_id, first_video):
        self.tenant_id = tenant_id
        self._first_video = first_video
        self.calls = 0
        self.research_called = False

    async def _get_video(self, video_id):
        self.calls += 1
        if self.calls == 1:
            return dict(self._first_video)
        # Second pass: report a status OUTSIDE BUILD_TO_PICTURES so the loop
        # stops immediately instead of chasing run_next_step/etc - only the
        # skip branch itself is under test here.
        return {"status": "ready_for_images", "render_mode": self._first_video.get("render_mode")}

    async def run_research(self, video_id):
        self.research_called = True
        return {"status": "ready_for_scripting"}


def _make_fake_pipeline_executor_module(first_video: dict, holder: list):
    def _factory(tenant_id):
        ex = _FakeExecutor(tenant_id, first_video)
        holder.append(ex)
        return ex
    mod = types.ModuleType("pipeline_executor")
    mod.PipelineExecutor = _factory
    return mod


def _make_fake_routes_pipeline_module():
    mod = types.ModuleType("routes.pipeline")
    mod._set_task_status = lambda *a, **k: None
    mod._clear_task_status = lambda *a, **k: None
    return mod


def _run_autobuild(first_video: dict):
    """Drive actions.make_autobuild_step(...)() to completion against fakes,
    with asyncio.sleep patched out (the real _run() sleeps 20s in its
    finally-block before clearing the task slot)."""
    holder = []
    fake_pe = _make_fake_pipeline_executor_module(first_video, holder)
    fake_rp = _make_fake_routes_pipeline_module()

    async def _fast_sleep(*_a, **_k):
        return None

    with patch.dict(sys.modules, {"pipeline_executor": fake_pe, "routes.pipeline": fake_rp}):
        with patch("asyncio.sleep", _fast_sleep):
            step = actions.make_autobuild_step("tenant-1", "video-1", target="pictures")
            asyncio.run(step())
    return holder[0]


# --- tests ---------------------------------------------------------------

def test_non_static_docu_records_research_skipped_and_never_researches():
    EXECUTED.clear()
    ex = _run_autobuild({"status": "idea_logged", "render_mode": None})

    assert ex.research_called is False, "the default skip must not call run_research"
    skip_writes = [
        (q, a) for (q, a) in EXECUTED
        if "research_skipped" in q and "TRUE" in q
    ]
    assert len(skip_writes) == 1, f"expected exactly one research_skipped=TRUE write, got {EXECUTED}"
    _query, args = skip_writes[0]
    assert args == ("video-1", "tenant-1")
    print("✅ test_non_static_docu_records_research_skipped_and_never_researches")


def test_static_docu_researches_and_never_records_skipped():
    EXECUTED.clear()
    ex = _run_autobuild({"status": "idea_logged", "render_mode": "static_docu"})

    assert ex.research_called is True, "static_docu must always research first"
    skip_writes = [q for (q, _a) in EXECUTED if "research_skipped" in q and "TRUE" in q]
    assert skip_writes == [], f"static_docu must never record research_skipped, got {EXECUTED}"
    print("✅ test_static_docu_researches_and_never_records_skipped")


def test_approved_status_also_records_the_skip():
    # The skip branch triggers on either idea_logged OR approved.
    EXECUTED.clear()
    ex = _run_autobuild({"status": "approved", "render_mode": None})

    assert ex.research_called is False
    skip_writes = [q for (q, _a) in EXECUTED if "research_skipped" in q and "TRUE" in q]
    assert len(skip_writes) == 1
    print("✅ test_approved_status_also_records_the_skip")


if __name__ == "__main__":
    test_non_static_docu_records_research_skipped_and_never_researches()
    test_static_docu_researches_and_never_records_skipped()
    test_approved_status_also_records_the_skip()
    print("All tests passed!")
