"""Lock: an EXPLICIT research request in a video's plan is honored by
autobuild instead of being silently skipped (C06a, follow-up to C06).

Prior bug (recorded in SYSTEM_STATE.md §C06 "Found but explicitly NOT
fixed"): actions.make_autobuild_step's skip branch (idea_logged/approved,
non-static_docu) never consulted the video's pipeline_stages plan before
skipping research — so a video created with workflow:"research" (plan =
["research"]) or any custom plan naming "research" got silently skipped
anyway by the SAME chat-triggered autobuild, and could route straight to
"done" with no script and no research payload.

This pins the fix:

  1. A video with NO plan (pipeline_stages is NULL — the ordinary default
     full pipeline) still SKIPS research and never calls run_research —
     byte-identical to the pre-C06a behavior. This is the case that must
     NOT change (running research here would silently bill every default
     autobuild).
  2. A video whose plan EXPLICITLY names "research" (e.g. workflow:
     "research" -> pipeline_stages=["research"], or a custom plan like
     ["research", "script"]) calls run_research instead of skipping, and
     never writes research_skipped=TRUE (research actually ran).
  3. static_docu is unaffected either way: it always researches via its own
     branch before this new check is ever reached, so it can't double-run
     research even when its plan also happens to name "research".

No network, no real DB: `database`, `pipeline_executor`, and
`routes.pipeline` are stubbed with the same module-stub pattern used by
test_research_skipped_chip.py. `status_map` imports for real (pure
functions, no external deps), so parse_stage_plan runs its genuine logic.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_autobuild_explicit_research_plan.py -q
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
        self.research_call_count = 0

    @property
    def research_called(self):
        return self.research_call_count > 0

    async def _get_video(self, video_id):
        self.calls += 1
        if self.calls == 1:
            return dict(self._first_video)
        # Second pass: report a status OUTSIDE BUILD_TO_PICTURES so the loop
        # stops immediately instead of chasing run_next_step/etc - only the
        # skip/explicit-research decision itself is under test here.
        return {"status": "ready_for_images", "render_mode": self._first_video.get("render_mode")}

    async def run_research(self, video_id):
        self.research_call_count += 1
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


def _skip_writes():
    return [(q, a) for (q, a) in EXECUTED if "research_skipped" in q and "TRUE" in q]


# --- tests ---------------------------------------------------------------

def test_default_plan_still_skips_research_unchanged():
    """pipeline_stages is NULL (the ordinary default) -> unchanged: skip,
    record research_skipped=TRUE, never call run_research."""
    EXECUTED.clear()
    ex = _run_autobuild({"status": "idea_logged", "render_mode": None, "pipeline_stages": None})

    assert ex.research_called is False, "a default (no-plan) video must not run research"
    writes = _skip_writes()
    assert len(writes) == 1, f"expected exactly one research_skipped=TRUE write, got {EXECUTED}"
    _q, args = writes[0]
    assert args == ("video-1", "tenant-1")
    print("✅ test_default_plan_still_skips_research_unchanged")


def test_explicit_research_only_plan_runs_research_not_skip():
    """workflow:'research' -> pipeline_stages=['research'] -> run research,
    do NOT record research_skipped."""
    EXECUTED.clear()
    ex = _run_autobuild({
        "status": "idea_logged", "render_mode": None, "pipeline_stages": ["research"],
    })

    assert ex.research_call_count == 1, "an explicit research request must run research"
    assert _skip_writes() == [], f"an explicitly-requested research run must not be recorded as skipped, got {EXECUTED}"
    print("✅ test_explicit_research_only_plan_runs_research_not_skip")


def test_explicit_custom_plan_including_research_runs_research():
    """A custom plan naming research alongside other stages also counts as
    explicit — e.g. ["research", "script"]."""
    EXECUTED.clear()
    ex = _run_autobuild({
        "status": "approved", "render_mode": None, "pipeline_stages": ["research", "script"],
    })

    assert ex.research_call_count == 1
    assert _skip_writes() == []
    print("✅ test_explicit_custom_plan_including_research_runs_research")


def test_plan_without_research_still_skips():
    """A restricted plan that does NOT name research (e.g. script_assets ->
    ["script", "images"]) still skips, same as the default case."""
    EXECUTED.clear()
    ex = _run_autobuild({
        "status": "idea_logged", "render_mode": None, "pipeline_stages": ["script", "images"],
    })

    assert ex.research_called is False
    assert len(_skip_writes()) == 1
    print("✅ test_plan_without_research_still_skips")


def test_static_docu_with_research_in_plan_researches_exactly_once():
    """static_docu always researches via its own branch — even if its plan
    also happens to name 'research', the new explicit-plan check must never
    be reached, so research runs exactly once (no double-run)."""
    EXECUTED.clear()
    ex = _run_autobuild({
        "status": "idea_logged", "render_mode": "static_docu", "pipeline_stages": ["research", "images"],
    })

    assert ex.research_call_count == 1, f"static_docu must research exactly once, got {ex.research_call_count}"
    assert _skip_writes() == []
    print("✅ test_static_docu_with_research_in_plan_researches_exactly_once")


if __name__ == "__main__":
    test_default_plan_still_skips_research_unchanged()
    test_explicit_research_only_plan_runs_research_not_skip()
    test_explicit_custom_plan_including_research_runs_research()
    test_plan_without_research_still_skips()
    test_static_docu_with_research_in_plan_researches_exactly_once()
    print("All tests passed!")
