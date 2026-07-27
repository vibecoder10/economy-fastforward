"""Lock: a script the quality critic rejects (`needs_review`) must reach the
creator, and must never be silently recorded as a clean success (checklist
C-frontdoor2, 2026-07-27).

Root cause (verified live, video d218b352-8894-45d1-af0a-fb8847d39e55): the
script quality critic (`script_quality.run_critique_and_edit`, via
`pipeline_executor.run_script`) correctly returned
`{"status": "needs_review", ...}` after its bounded edit loop failed to fix
the draft. But:

  1. `routes/pipeline.py`'s `_set_task_status()` normalized ANY status that
     isn't literally "running"/"failed" to "completed" — so a real content
     rejection was recorded as an ordinary success, with no distinction any
     poller could act on.
  2. `actions.make_autobuild_step`'s per-stage loop only checked
     `script_result.get("status") == "failed"`; a `needs_review` result fell
     through to `continue`, looped back to the top, found the SAME status
     (the video's stage never advances on needs_review — by design, so a
     rejected script can't silently ship), and only stopped via the generic
     "no progress" branch with a bare "Paused at ready_for_scripting." —
     never mentioning a script existed, that it was rejected, or why.
  3. The critic's own `failing_gates` are internal jargon ("hook_speed",
     "escalation") never meant for a creator to read.

Fix (chosen over widening the "running/completed/failed" status enum, which
ripples through background_tasks' DB CHECK constraint AND every existing
poller's running->done detection — useTaskPoller, useTaskWatcher,
TaskStatus/SSETaskProgressEvent's frontend types — for zero benefit to this
narrow bug):

  a. `_set_task_status` still normalizes needs_review -> "completed" (100%
     unchanged DB/enum behavior for every existing consumer), but ADDITIVELY
     flags `needs_review: True` on the in-memory entry, threaded through to
     GET /task/{id} and the SSE task_progress stream as one more optional
     field (same absence-safe contract as C28's `via_agent`) — the ONE new
     consumer (ChatPipelineMap's banner in the chat) can react to it; every
     old consumer that doesn't know about the field is unaffected.
  b. `make_autobuild_step`'s script-stage branch now explicitly checks
     `needs_review` BEFORE falling through to `continue`, and stops with an
     honest, specific message instead of the generic "Paused at X.".
  c. `script_quality.plain_english_violations()` translates the critic's raw
     gate keys to plain English before they ever reach a human-facing
     message; `pipeline_executor.run_script`'s two needs_review branches
     (the modeled-script path and the ordinary brief-translator path) both
     use it for the "message" field (the raw keys still go into the
     internal-only log line and the "violations" list, for anyone reading
     logs/telemetry).

No network, no DB: `database`/`auth`/`vault` stubbed and `pipeline_executor`
faked with a minimal executor, same pattern as
test_autobuild_explicit_research_plan.py / test_cross_tenant_task_isolation.py.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_frontdoor_needs_review_surfacing.py -q
"""
import asyncio
import os
import sys
import types
from unittest.mock import patch

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


async def _noop(*a, **k):
    return None


_stub("database", fetch_one=_noop, fetch_all=_noop, execute=_noop)


async def _fake_get_tenant_id(*a, **k):
    return "stub-tenant"


_stub("auth", get_tenant_id=_fake_get_tenant_id)


class _StubPipelineExecutor:
    def __init__(self, *a, **k):
        pass


_stub("pipeline_executor", PipelineExecutor=_StubPipelineExecutor)

from routes import pipeline as pipeline_mod  # noqa: E402
import script_quality  # noqa: E402

TENANT = "tenant-1"
VIDEO = "video-1"


def _reset():
    pipeline_mod._running_tasks.clear()


# ---------------------------------------------------------------------------
# (a) _set_task_status: needs_review is additive, DB/enum status unchanged
# ---------------------------------------------------------------------------

def test_needs_review_normalizes_to_completed_but_flags_the_extra_field():
    _reset()
    pipeline_mod._set_task_status(
        VIDEO, "needs_review",
        "The script needs another look — the opening is slow to hook the viewer.",
        tenant_id=TENANT,
    )
    task = pipeline_mod._get_task_status(VIDEO, TENANT)
    assert task is not None
    # Every existing poller's running->done detection keys off "completed" —
    # this MUST still be exactly that, unchanged.
    assert task["status"] == "completed", (
        f"needs_review must still normalize to 'completed' (existing pollers "
        f"only recognize running/completed/failed), got {task['status']!r}"
    )
    # ...but the additive flag distinguishes it for the one consumer that cares.
    assert task["needs_review"] is True
    assert "needs another look" in task["message"]
    print("✅ test_needs_review_normalizes_to_completed_but_flags_the_extra_field")


def test_ordinary_completion_has_needs_review_false():
    """Regression guard: an ordinary passing stage must NOT pick up the new
    flag — only an explicit status="needs_review" call sets it."""
    _reset()
    pipeline_mod._set_task_status(VIDEO, "ready_for_voice", "Script written.", tenant_id=TENANT)
    task = pipeline_mod._get_task_status(VIDEO, TENANT)
    assert task["status"] == "completed"
    assert task["needs_review"] is False
    print("✅ test_ordinary_completion_has_needs_review_false")


def test_get_task_status_route_exposes_needs_review():
    """GET /task/{video_id} (routes.pipeline.get_task_status) must surface the
    same additive flag — this is what a fresh poll after reload would see."""
    _reset()
    pipeline_mod._set_task_status(
        VIDEO, "needs_review", "needs another look", tenant_id=TENANT,
    )
    result = asyncio.run(pipeline_mod.get_task_status(VIDEO, TENANT))
    assert result["status"] == "completed"
    assert result["needs_review"] is True
    print("✅ test_get_task_status_route_exposes_needs_review")


def test_failed_task_has_needs_review_false():
    """A genuine failure must not be confused with needs_review."""
    _reset()
    pipeline_mod._set_task_status(VIDEO, "failed", "boom", tenant_id=TENANT)
    task = pipeline_mod._get_task_status(VIDEO, TENANT)
    assert task["status"] == "failed"
    assert task["needs_review"] is False
    print("✅ test_failed_task_has_needs_review_false")


# ---------------------------------------------------------------------------
# (c) script_quality.plain_english_violations
# ---------------------------------------------------------------------------

def test_plain_english_translates_known_universal_gates():
    out = script_quality.plain_english_violations(["hook_speed", "escalation"])
    assert out == [
        "the opening is slow to hook the viewer",
        "the story doesn't escalate — it plateaus or sags partway through",
    ]
    print("✅ test_plain_english_translates_known_universal_gates")


def test_plain_english_is_forgiving_about_casing_and_spacing():
    """The judge is a free-text model, not a strict enum — different casing/
    spacing/separators for the same gate must still translate."""
    variants = ["HOOK_SPEED", "Hook Speed", "hook-speed"]
    for v in variants:
        assert script_quality.plain_english_violation(v) == "the opening is slow to hook the viewer", v
    print("✅ test_plain_english_is_forgiving_about_casing_and_spacing")


def test_plain_english_falls_back_gracefully_for_unknown_names():
    """A channel-specific rule name or the free-text rewrite_guidance fallback
    (anything not one of the five universal gates) must never crash and must
    never disappear — de-slugged, not translated, is the honest fallback."""
    assert script_quality.plain_english_violation("no_emoji_in_titles") == "no emoji in titles"
    assert script_quality.plain_english_violation("") == ""
    print("✅ test_plain_english_falls_back_gracefully_for_unknown_names")


# ---------------------------------------------------------------------------
# (b) actions.make_autobuild_step: needs_review stops the chain honestly
# ---------------------------------------------------------------------------

import actions  # noqa: E402


class _FakeExecutorNeedsReview:
    """A video sitting at ready_for_scripting whose script comes back
    needs_review. Only what make_autobuild_step's script branch touches."""

    def __init__(self, tenant_id):
        self.tenant_id = tenant_id
        self.get_video_calls = 0

    async def _get_video(self, video_id):
        self.get_video_calls += 1
        # Status NEVER advances past ready_for_scripting on needs_review —
        # matches pipeline_executor.run_script's real contract.
        return {"status": "ready_for_scripting", "render_mode": None, "max_spend": None}

    async def run_script(self, video_id, progress_callback=None):
        return {
            "status": "needs_review",
            "video_id": video_id,
            "violations": ["hook_speed", "escalation"],
            "message": "The script needs another look — the opening is slow to hook the "
                       "viewer; the story doesn't escalate — it plateaus or sags partway through.",
        }


def test_autobuild_stops_immediately_on_needs_review_with_honest_message():
    """THE fix: a needs_review script result must stop the chain on THIS
    iteration (never fall through to `continue` and mask itself as the
    generic 'Paused at ready_for_scripting.' no-progress message)."""
    set_calls = []

    def _fake_set_task_status(video_id, status, message=None, error=None, *, tenant_id, task_type="pipeline"):
        set_calls.append({"video_id": video_id, "status": status, "message": message, "tenant_id": tenant_id})

    fake_ex_holder = []

    def _executor_factory(tenant_id):
        ex = _FakeExecutorNeedsReview(tenant_id)
        fake_ex_holder.append(ex)
        return ex

    fake_pe = types.ModuleType("pipeline_executor")
    fake_pe.PipelineExecutor = _executor_factory

    fake_rp = types.ModuleType("routes.pipeline")
    fake_rp._set_task_status = _fake_set_task_status
    fake_rp._clear_task_status = lambda *a, **k: None

    async def _fast_sleep(*_a, **_k):
        return None

    with patch.dict(sys.modules, {"pipeline_executor": fake_pe, "routes.pipeline": fake_rp}):
        with patch("asyncio.sleep", _fast_sleep):
            step = actions.make_autobuild_step(TENANT, VIDEO, target="pictures")
            asyncio.run(step())

    ex = fake_ex_holder[0]
    # Only ONE _get_video call after entering the loop iteration that ran the
    # script (the fetch at the top of that same iteration) — if the code had
    # fallen through to `continue`, a SECOND _get_video call (the next loop
    # iteration) would have happened, landing on the generic no-progress stop
    # instead of this one's honest needs_review stop.
    assert ex.get_video_calls == 1, (
        f"expected the loop to stop within the SAME iteration that got "
        f"needs_review (1 _get_video call), got {ex.get_video_calls} — "
        "the needs_review verdict fell through to another loop pass"
    )

    # Exactly one terminal _set_task_status call (plus the initial "running"
    # start_msg from _run()'s very first line) — never "completed"/"Paused at
    # ready_for_scripting." (the old generic no-progress message).
    terminal = [c for c in set_calls if c["status"] != "running"]
    assert len(terminal) == 1, f"expected exactly one terminal status call, got {terminal}"
    assert terminal[0]["status"] == "needs_review", (
        f"expected the honest needs_review status, got {terminal[0]['status']!r}"
    )
    assert "needs another look" in terminal[0]["message"]
    assert "Paused at" not in terminal[0]["message"], (
        "must not fall back to the generic no-progress message — that's "
        "exactly the silent-looking stall this fix replaces"
    )
    print("✅ test_autobuild_stops_immediately_on_needs_review_with_honest_message")


def test_autobuild_still_fails_hard_on_a_real_script_failure():
    """Sanity/regression: an actual failure (not needs_review) must still
    stop with status='failed', unaffected by this change."""
    set_calls = []

    def _fake_set_task_status(video_id, status, message=None, error=None, *, tenant_id, task_type="pipeline"):
        set_calls.append({"status": status, "message": message})

    class _FailingExecutor:
        def __init__(self, tenant_id):
            pass

        async def _get_video(self, video_id):
            return {"status": "ready_for_scripting", "render_mode": None, "max_spend": None}

        async def run_script(self, video_id, progress_callback=None):
            return {"status": "failed", "error": "writer crashed"}

    fake_pe = types.ModuleType("pipeline_executor")
    fake_pe.PipelineExecutor = _FailingExecutor
    fake_rp = types.ModuleType("routes.pipeline")
    fake_rp._set_task_status = _fake_set_task_status
    fake_rp._clear_task_status = lambda *a, **k: None

    async def _fast_sleep(*_a, **_k):
        return None

    with patch.dict(sys.modules, {"pipeline_executor": fake_pe, "routes.pipeline": fake_rp}):
        with patch("asyncio.sleep", _fast_sleep):
            step = actions.make_autobuild_step(TENANT, VIDEO, target="pictures")
            asyncio.run(step())

    terminal = [c for c in set_calls if c["status"] != "running"]
    assert len(terminal) == 1
    assert terminal[0]["status"] == "failed"
    assert terminal[0]["message"] == "writer crashed"
    print("✅ test_autobuild_still_fails_hard_on_a_real_script_failure")


def test_autobuild_passing_script_is_unaffected():
    """Sanity/regression: a script that passes quality (no needs_review key
    at all) must keep advancing exactly as before — proves the new check is
    additive, not a new gate on the happy path."""
    set_calls = []

    def _fake_set_task_status(video_id, status, message=None, error=None, *, tenant_id, task_type="pipeline"):
        set_calls.append({"status": status})

    call_count = {"n": 0}

    class _PassingExecutor:
        def __init__(self, tenant_id):
            pass

        async def _get_video(self, video_id):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return {"status": "ready_for_scripting", "render_mode": None, "max_spend": None}
            # Second pass: report a status outside BUILD_TO_PICTURES so the
            # loop stops cleanly right after the script stage advances it —
            # only the script-branch behavior is under test here.
            return {"status": "ready_for_images", "render_mode": None, "max_spend": None}

        async def run_script(self, video_id, progress_callback=None):
            # No "needs_review" key at all — the ordinary pass-through shape.
            return {"status": "ready_for_voice", "video_id": video_id}

    fake_pe = types.ModuleType("pipeline_executor")
    fake_pe.PipelineExecutor = _PassingExecutor
    fake_rp = types.ModuleType("routes.pipeline")
    fake_rp._set_task_status = _fake_set_task_status
    fake_rp._clear_task_status = lambda *a, **k: None

    async def _fast_sleep(*_a, **_k):
        return None

    with patch.dict(sys.modules, {"pipeline_executor": fake_pe, "routes.pipeline": fake_rp}):
        with patch("asyncio.sleep", _fast_sleep):
            step = actions.make_autobuild_step(TENANT, VIDEO, target="pictures")
            asyncio.run(step())

    # Must have progressed past the script stage (2 _get_video calls) and
    # completed cleanly — no "needs_review"/"failed" ever appears.
    assert call_count["n"] == 2
    statuses = [c["status"] for c in set_calls]
    assert "needs_review" not in statuses
    assert "failed" not in statuses
    assert statuses[-1] == "completed"
    print("✅ test_autobuild_passing_script_is_unaffected")


TESTS = [
    test_needs_review_normalizes_to_completed_but_flags_the_extra_field,
    test_ordinary_completion_has_needs_review_false,
    test_get_task_status_route_exposes_needs_review,
    test_failed_task_has_needs_review_false,
    test_plain_english_translates_known_universal_gates,
    test_plain_english_is_forgiving_about_casing_and_spacing,
    test_plain_english_falls_back_gracefully_for_unknown_names,
    test_autobuild_stops_immediately_on_needs_review_with_honest_message,
    test_autobuild_still_fails_hard_on_a_real_script_failure,
    test_autobuild_passing_script_is_unaffected,
]


if __name__ == "__main__":
    failed = 0
    for t in TESTS:
        try:
            t()
        except AssertionError as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
    _reset()
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)
