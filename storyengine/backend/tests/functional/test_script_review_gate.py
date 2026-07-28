"""Tests for job 3 (typed-consent for the approval_gate) and job 4 (the
script-review card that surfaces a needs_review verdict IN THE CHAT) from
the "surface" plan (2026-07-28, branch feat/chat-one-window).

Job 3 root problem: the approval_gate card's "Looks good!"/"Not yet" buttons
had no typed-text equivalent — a creator who ANSWERED THE GATE IN WORDS
("looks good", "not yet") instead of tapping fell straight through to the
general classifier, which had no idea a gate was even open.

Job 4 root problem (verified live, video 67a87d3c-59be-4d6b-9317-
3ca6c69520eb): a needs_review verdict from the script quality critic only
ever reached `background_tasks` (a live SSE banner the stepper can show) —
never the actual chat transcript. "The run correctly stopped... he never
saw it. From his seat the app looked frozen."

None of the names this file imports/patches (`chat._post_script_review_
message`, `chat._REWRITE_RE`/`_USE_ANYWAY_RE`, the `"script_review"`
selections key, or `chat._gate_question_text`) exist on `main` — every test
below raises AttributeError on an unpatched checkout, the same non-vacuous
proof test_approval_gates.py's own docstring calls out.

Style matches test_approval_gates.py exactly (same `_summary`/`_claims`/
`_RecordingBackgroundTasks`/`_run_copilot_turn` helpers, duplicated here so
this file stays self-contained like every other file in this suite): real
`actions`/`routes.chat` modules, `database`/`generation_claims` monkeypatched
— no live DB, no network.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_script_review_gate.py -q
"""
import asyncio
import os
import sys
import types
from unittest.mock import AsyncMock, patch

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))

import actions  # noqa: E402
import generation_claims  # noqa: E402
import routes.chat as chat  # noqa: E402

TENANT = "tenant-1"
VIDEO = "video-1"


def _summary(**over):
    base = {
        "title": "Slow English", "status": "ready_for_image_prompts", "length_min": 1.0,
        "model": "grok-imagine", "scenes": 8, "boards": 0, "voiced": 0,
        "max_scene": 8, "pics": 0, "clips": 0, "cast": 0, "envs": 0,
        "chars_approved": False, "envs_approved": False,
        "spent": 0.0, "total_cost": 0.0, "max_spend": None,
        "validation": "", "render_style": None, "render_mode": None,
        "plays_sfx": True, "sfx_blocked_reason": None,
    }
    base.update(over)
    return base


class _RecordingBackgroundTasks:
    def __init__(self):
        self.calls = []

    def add_task(self, fn, *a, **k):
        self.calls.append((fn, a, k))


def _claims(acquire_result=True):
    return types.SimpleNamespace(
        acquire=AsyncMock(return_value=acquire_result),
        release=AsyncMock(return_value=None),
        stage_for_verb=generation_claims.stage_for_verb,
    )


EXECUTED = []


async def _fake_execute(query, *args):
    EXECUTED.append((query, args))
    return "OK"


def _run_copilot_turn(body, state=None, summary=None, claims=None, char_count_row=None):
    EXECUTED.clear()
    state = state if state is not None else {}
    transcript = []
    bg = _RecordingBackgroundTasks()

    async def _fake_summary(*_a, **_k):
        return summary or _summary()

    async def _fake_actions_fetch_one(query, *a):
        if "video_characters" in query:
            return char_count_row or {"n": 0}
        raise AssertionError(f"unexpected actions.fetch_one call: {query}")

    with patch.object(chat, "_copilot_summary", _fake_summary), \
         patch.object(chat, "execute", _fake_execute), \
         patch.object(actions, "fetch_one", _fake_actions_fetch_one), \
         patch.object(chat, "generation_claims", claims or _claims(acquire_result=True)):
        result = asyncio.run(
            chat._handle_copilot(body, "conv-1", TENANT, transcript, state, VIDEO, bg)
        )
    return result, state, bg


# ---------------------------------------------------------------------------
# 1. Job 3 — the gate copy is a genuine question, not a bare status line, and
#    it does NOT invite a "drop in your own character/scene" affordance that
#    isn't actually wired (verified separately against the real code paths —
#    see the branch's report).
# ---------------------------------------------------------------------------

def test_script_gate_question_asks_a_real_question_and_names_a_real_option():
    text = chat._gate_question_text("script", "~$0.10")
    assert "?" in text, "must read as a genuine question, not a status line"
    assert "tell me what" in text.lower()
    assert "add a character" not in text.lower()
    assert "drop in" not in text.lower()
    print("✅ test_script_gate_question_asks_a_real_question_and_names_a_real_option")


def test_anchors_gate_question_asks_a_real_question_and_quotes_the_cost():
    text = chat._gate_question_text("anchors", "~$1.20")
    assert "?" in text
    assert "~$1.20" in text
    assert "select" in text.lower(), "must point at a REAL affordance (select a character/location), not a fake one"
    print("✅ test_anchors_gate_question_asks_a_real_question_and_quotes_the_cost")


# ---------------------------------------------------------------------------
# 2. Job 3 — typed consent for a pending approval_gate: "looks good"/"not
#    yet" typed in words must do exactly what tapping the button does.
# ---------------------------------------------------------------------------

def test_typed_looks_good_resumes_the_gate_same_as_the_button():
    body = chat.ChatTurnRequest(video_id=VIDEO, message="looks good")
    state = {"pending_approval_gate": {
        "gate_kind": "script",
        "resume": {"verb": "characters", "scene": None, "change": "", "length_min": None},
    }}
    fake_step_factory = lambda *a, **k: "sentinel-characters-callable"  # noqa: E731
    claims = _claims(acquire_result=True)

    with patch.object(chat, "_make_copilot_step", fake_step_factory):
        result, state, bg = _run_copilot_turn(body, state=state, claims=claims)

    assert len(bg.calls) == 1, "a typed 'looks good' must resume the gate's quoted action"
    assert bg.calls[0][0] == "sentinel-characters-callable"
    assert state["pending_approval_gate"] is None
    print("✅ test_typed_looks_good_resumes_the_gate_same_as_the_button")


def test_typed_not_yet_clears_the_gate_without_spending():
    body = chat.ChatTurnRequest(video_id=VIDEO, message="not yet")
    state = {"pending_approval_gate": {
        "gate_kind": "script",
        "resume": {"verb": "characters", "scene": None, "change": "", "length_min": None},
    }}
    claims = _claims(acquire_result=True)

    result, state, bg = _run_copilot_turn(body, state=state, claims=claims)

    assert bg.calls == []
    claims.acquire.assert_not_awaited()
    assert state["pending_approval_gate"] is None
    print("✅ test_typed_not_yet_clears_the_gate_without_spending")


def test_typed_change_request_falls_through_to_the_classifier_not_swallowed():
    """'make the second scene at night' is neither 'looks good' nor 'not
    yet' — it must NOT be silently eaten by the gate handshake. It falls
    through to the ordinary classifier (which is what actually resolves a
    scene-text edit) — proven here by the fact this does NOT resume the
    pending gate's action (no background task scheduled by the typed-consent
    path) and does NOT crash."""
    body = chat.ChatTurnRequest(video_id=VIDEO, message="make the second scene at night")
    state = {"pending_approval_gate": {
        "gate_kind": "script",
        "resume": {"verb": "characters", "scene": None, "change": "", "length_min": None},
    }}
    claims = _claims(acquire_result=True)

    # The classifier needs a text client; keyless tenant -> the friendly
    # key-prompt reply, itself proof this reached the classifier branch
    # rather than being consumed by the gate's typed-consent shortcut.
    async def _no_client(*_a, **_k):
        return None

    fake_kie = types.ModuleType("kie_unified")
    fake_kie.get_text_client_for_tenant = _no_client

    with patch.dict(sys.modules, {"kie_unified": fake_kie}):
        result, state, bg = _run_copilot_turn(body, state=state, claims=claims)

    assert bg.calls == [], "a change request must not resume the OLD pending gate action"
    assert "API key" in result.assistant_text
    print("✅ test_typed_change_request_falls_through_to_the_classifier_not_swallowed")


# ---------------------------------------------------------------------------
# 3. Job 4 — _post_script_review_message: the needs_review verdict as a
#    normal, persisted chat turn (not just a task-status string).
# ---------------------------------------------------------------------------

def test_post_script_review_message_persists_a_normal_chat_turn_with_two_options():
    conv_row = {"id": "conv-9", "transcript": [], "state": {}}

    async def fake_conversation_for_video(_tenant, _video):
        return conv_row

    persisted = {}

    async def fake_persist(conversation_id, tenant_id, transcript, state, phase, video_id=None):
        persisted["conversation_id"] = conversation_id
        persisted["transcript"] = transcript
        persisted["state"] = state

    msg = ("The script needs another look — the opening is slow to hook the viewer; "
           "the story doesn't escalate — it plateaus or sags partway through")

    with patch.object(chat, "_conversation_for_video", fake_conversation_for_video), \
         patch.object(chat, "_persist", fake_persist):
        asyncio.run(chat._post_script_review_message(TENANT, VIDEO, msg))

    assert persisted, "must persist a turn — a silent needs_review is the exact bug this fixes"
    assert persisted["state"]["pending_script_review"] is True
    assert persisted["state"]["pending_action"] == {
        "verb": "script", "scene": None, "change": "", "length_min": None,
    }
    turn = persisted["transcript"][-1]
    assert turn["role"] == "assistant"
    import json as _json
    payload = _json.loads(turn["content"])
    # The owner's own quoted rejection reason must appear verbatim in the
    # chat message — not just in a task-status field he never looks at.
    assert "opening is slow to hook the viewer" in payload["assistant_text"]
    assert "story doesn't escalate" in payload["assistant_text"]
    card = payload["cards"][0]
    assert card["id"] == "script_review"
    values = {o["value"] for o in card["options"]}
    assert values == {"rewrite", "use_anyway"}
    print("✅ test_post_script_review_message_persists_a_normal_chat_turn_with_two_options")


def test_post_script_review_message_missing_conversation_is_a_safe_no_op():
    async def fake_conversation_for_video(_tenant, _video):
        return None

    with patch.object(chat, "_conversation_for_video", fake_conversation_for_video):
        asyncio.run(chat._post_script_review_message(TENANT, VIDEO, "whatever"))
    # No exception, nothing else to assert — the point is it doesn't crash.
    print("✅ test_post_script_review_message_missing_conversation_is_a_safe_no_op")


# ---------------------------------------------------------------------------
# 4. Job 4 — the script_review handshake (turn 2): "Rewrite it" resumes the
#    pending 'script' verb; "Use it anyway" runs the existing free 'advance'
#    verb/runner. Both via buttons (selections) AND typed text.
# ---------------------------------------------------------------------------

def _advance_runner_stub(calls):
    async def _fake_advance(tenant_id, video_id, background_tasks, pending):
        calls.append((tenant_id, video_id))
        return "Done — skipped ahead. Say “build it” anytime and I'll take it from here."
    return _fake_advance


def test_script_review_button_rewrite_resumes_the_pending_script_verb():
    body = chat.ChatTurnRequest(video_id=VIDEO, selections={"script_review": "rewrite"})
    state = {
        "pending_script_review": True,
        "pending_action": {"verb": "script", "scene": None, "change": "", "length_min": None},
    }
    fake_step_factory = lambda *a, **k: "sentinel-script-callable"  # noqa: E731
    claims = _claims(acquire_result=True)

    with patch.object(chat, "_make_copilot_step", fake_step_factory):
        result, state, bg = _run_copilot_turn(body, state=state, claims=claims)

    assert len(bg.calls) == 1
    assert bg.calls[0][0] == "sentinel-script-callable"
    assert state["pending_script_review"] is None
    assert state["pending_action"] is None
    print("✅ test_script_review_button_rewrite_resumes_the_pending_script_verb")


def test_script_review_button_use_anyway_runs_the_advance_runner():
    body = chat.ChatTurnRequest(video_id=VIDEO, selections={"script_review": "use_anyway"})
    state = {
        "pending_script_review": True,
        "pending_action": {"verb": "script", "scene": None, "change": "", "length_min": None},
    }
    claims = _claims(acquire_result=True)
    advance_calls = []

    with patch.dict(chat._ACTION_RUNNERS, {"advance": _advance_runner_stub(advance_calls)}):
        result, state, bg = _run_copilot_turn(body, state=state, claims=claims)

    assert advance_calls == [(TENANT, VIDEO)], "'Use it anyway' must run the real 'advance' runner"
    assert bg.calls == [], "advance is free/immediate — it must not go through the paid background-task path"
    assert state["pending_script_review"] is None
    assert "skipped ahead" in result.assistant_text
    print("✅ test_script_review_button_use_anyway_runs_the_advance_runner")


def test_typed_rewrite_it_matches_the_button_behavior():
    body = chat.ChatTurnRequest(video_id=VIDEO, message="rewrite it")
    state = {
        "pending_script_review": True,
        "pending_action": {"verb": "script", "scene": None, "change": "", "length_min": None},
    }
    fake_step_factory = lambda *a, **k: "sentinel-script-callable"  # noqa: E731
    claims = _claims(acquire_result=True)

    with patch.object(chat, "_make_copilot_step", fake_step_factory):
        result, state, bg = _run_copilot_turn(body, state=state, claims=claims)

    assert len(bg.calls) == 1
    assert bg.calls[0][0] == "sentinel-script-callable"
    assert state["pending_script_review"] is None
    print("✅ test_typed_rewrite_it_matches_the_button_behavior")


def test_typed_use_it_anyway_matches_the_button_behavior():
    body = chat.ChatTurnRequest(video_id=VIDEO, message="use it anyway")
    state = {
        "pending_script_review": True,
        "pending_action": {"verb": "script", "scene": None, "change": "", "length_min": None},
    }
    claims = _claims(acquire_result=True)
    advance_calls = []

    with patch.dict(chat._ACTION_RUNNERS, {"advance": _advance_runner_stub(advance_calls)}):
        result, state, bg = _run_copilot_turn(body, state=state, claims=claims)

    assert advance_calls == [(TENANT, VIDEO)]
    assert state["pending_script_review"] is None
    print("✅ test_typed_use_it_anyway_matches_the_button_behavior")


# ---------------------------------------------------------------------------
# 5. Wiring: actions.make_autobuild_step and actions.make_action_step both
#    post the SAME script_review chat card on a needs_review verdict — not
#    just a task-status string.
# ---------------------------------------------------------------------------

def test_autobuild_posts_script_review_chat_message_on_needs_review():
    review_msg = ("The script needs another look — the opening is slow to hook the "
                  "viewer; the story doesn't escalate — it plateaus or sags partway through.")

    class _FakeExecutorNeedsReview:
        def __init__(self, tenant_id):
            self.tenant_id = tenant_id

        async def _get_video(self, video_id):
            return {"status": "ready_for_scripting", "render_mode": None, "max_spend": None}

        async def run_script(self, video_id, progress_callback=None):
            return {"status": "needs_review", "video_id": video_id,
                    "violations": ["hook_speed", "escalation"], "message": review_msg}

    fake_pe = types.ModuleType("pipeline_executor")
    fake_pe.PipelineExecutor = _FakeExecutorNeedsReview

    set_calls = []

    def _fake_set_task_status(video_id, status, message=None, error=None, *, tenant_id, task_type="pipeline"):
        set_calls.append({"status": status, "message": message})

    fake_rp = types.ModuleType("routes.pipeline")
    fake_rp._set_task_status = _fake_set_task_status
    fake_rp._clear_task_status = lambda *a, **k: None

    fake_rc = types.ModuleType("routes.chat")
    post_calls = []

    async def _fake_post_script_review(tenant_id, video_id, message):
        post_calls.append((tenant_id, video_id, message))
    fake_rc._post_script_review_message = _fake_post_script_review

    async def _fast_sleep(*_a, **_k):
        return None

    with patch.dict(sys.modules, {"pipeline_executor": fake_pe, "routes.pipeline": fake_rp,
                                   "routes.chat": fake_rc}):
        with patch("asyncio.sleep", _fast_sleep):
            step = actions.make_autobuild_step(TENANT, VIDEO, target="pictures")
            asyncio.run(step())

    assert post_calls == [(TENANT, VIDEO, review_msg)], (
        "a needs_review verdict from the autobuild chain must ALSO reach the "
        "chat transcript, not just the task-status row"
    )
    terminal = [c for c in set_calls if c["status"] != "running"]
    assert terminal[0]["status"] == "needs_review"
    print("✅ test_autobuild_posts_script_review_chat_message_on_needs_review")


def test_autobuild_chat_post_failure_does_not_fail_the_build():
    """Fail-soft: a chat-post exception must not blow up the pipeline stage."""
    class _FakeExecutorNeedsReview:
        def __init__(self, tenant_id):
            pass

        async def _get_video(self, video_id):
            return {"status": "ready_for_scripting", "render_mode": None, "max_spend": None}

        async def run_script(self, video_id, progress_callback=None):
            return {"status": "needs_review", "video_id": video_id, "message": "needs another look"}

    fake_pe = types.ModuleType("pipeline_executor")
    fake_pe.PipelineExecutor = _FakeExecutorNeedsReview

    set_calls = []

    def _fake_set_task_status(video_id, status, message=None, error=None, *, tenant_id, task_type="pipeline"):
        set_calls.append({"status": status})

    fake_rp = types.ModuleType("routes.pipeline")
    fake_rp._set_task_status = _fake_set_task_status
    fake_rp._clear_task_status = lambda *a, **k: None

    fake_rc = types.ModuleType("routes.chat")

    async def _boom(*_a, **_k):
        raise RuntimeError("db is down")
    fake_rc._post_script_review_message = _boom

    async def _fast_sleep(*_a, **_k):
        return None

    with patch.dict(sys.modules, {"pipeline_executor": fake_pe, "routes.pipeline": fake_rp,
                                   "routes.chat": fake_rc}):
        with patch("asyncio.sleep", _fast_sleep):
            step = actions.make_autobuild_step(TENANT, VIDEO, target="pictures")
            asyncio.run(step())  # must not raise

    assert set_calls[-1]["status"] == "needs_review"
    print("✅ test_autobuild_chat_post_failure_does_not_fail_the_build")


def test_direct_script_verb_also_posts_script_review_chat_message():
    """A plain 'rewrite the script' tap OUTSIDE the autobuild chain
    (actions.make_action_step) must reach the SAME chat card — the needs_
    review shape is identical regardless of caller."""
    review_msg = "The script needs another look — the story doesn't escalate."

    class _FakeExecutor:
        def __init__(self, tenant_id):
            pass

        async def run_script(self, video_id, progress_callback=None):
            return {"status": "needs_review", "video_id": video_id, "message": review_msg}

    fake_pe = types.ModuleType("pipeline_executor")
    fake_pe.PipelineExecutor = _FakeExecutor

    fake_rp = types.ModuleType("routes.pipeline")
    fake_rp._set_task_status = lambda *a, **k: None
    fake_rp._clear_task_status = lambda *a, **k: None

    fake_rc = types.ModuleType("routes.chat")
    post_calls = []

    async def _fake_post_script_review(tenant_id, video_id, message):
        post_calls.append((tenant_id, video_id, message))
    fake_rc._post_script_review_message = _fake_post_script_review

    # actions.make_action_step's `_run` does `import generation_claims`
    # LOCALLY (inside the closure, not a module-level name on `actions`) —
    # patch.object(actions, "generation_claims", ...) has nothing to patch;
    # the real target is sys.modules["generation_claims"], same as how
    # pipeline_executor/routes.pipeline are faked above.
    fake_gc = types.ModuleType("generation_claims")
    fake_gc.release = AsyncMock(return_value=None)
    fake_gc.stage_for_verb = generation_claims.stage_for_verb

    async def _fast_sleep(*_a, **_k):
        return None

    with patch.dict(sys.modules, {"pipeline_executor": fake_pe, "routes.pipeline": fake_rp,
                                   "routes.chat": fake_rc, "generation_claims": fake_gc}):
        with patch("asyncio.sleep", _fast_sleep):
            step = actions.make_action_step(TENANT, VIDEO, [("run_script", False)])
            asyncio.run(step())

    assert post_calls == [(TENANT, VIDEO, review_msg)]
    print("✅ test_direct_script_verb_also_posts_script_review_chat_message")


def test_direct_verb_needs_review_post_scoped_to_run_script_only():
    """Belt-and-suspenders: the script-review card must not fire for some
    OTHER stage's status string — scoped to calls that actually include
    run_script."""
    class _FakeExecutor:
        def __init__(self, tenant_id):
            pass

        async def run_voice(self, video_id, scene=None, progress_callback=None):
            return {"status": "needs_review", "video_id": video_id, "message": "irrelevant"}

    fake_pe = types.ModuleType("pipeline_executor")
    fake_pe.PipelineExecutor = _FakeExecutor

    fake_rp = types.ModuleType("routes.pipeline")
    fake_rp._set_task_status = lambda *a, **k: None
    fake_rp._clear_task_status = lambda *a, **k: None

    fake_rc = types.ModuleType("routes.chat")
    post_calls = []

    async def _fake_post_script_review(tenant_id, video_id, message):
        post_calls.append((tenant_id, video_id, message))
    fake_rc._post_script_review_message = _fake_post_script_review

    fake_gc = types.ModuleType("generation_claims")
    fake_gc.release = AsyncMock(return_value=None)
    fake_gc.stage_for_verb = generation_claims.stage_for_verb

    async def _fast_sleep(*_a, **_k):
        return None

    with patch.dict(sys.modules, {"pipeline_executor": fake_pe, "routes.pipeline": fake_rp,
                                   "routes.chat": fake_rc, "generation_claims": fake_gc}):
        with patch("asyncio.sleep", _fast_sleep):
            step = actions.make_action_step(TENANT, VIDEO, [("run_voice", False)])
            asyncio.run(step())

    assert post_calls == [], "the script_review card must not fire for a non-script stage"
    print("✅ test_direct_verb_needs_review_post_scoped_to_run_script_only")


TESTS = [
    test_script_gate_question_asks_a_real_question_and_names_a_real_option,
    test_anchors_gate_question_asks_a_real_question_and_quotes_the_cost,
    test_typed_looks_good_resumes_the_gate_same_as_the_button,
    test_typed_not_yet_clears_the_gate_without_spending,
    test_typed_change_request_falls_through_to_the_classifier_not_swallowed,
    test_post_script_review_message_persists_a_normal_chat_turn_with_two_options,
    test_post_script_review_message_missing_conversation_is_a_safe_no_op,
    test_script_review_button_rewrite_resumes_the_pending_script_verb,
    test_script_review_button_use_anyway_runs_the_advance_runner,
    test_typed_rewrite_it_matches_the_button_behavior,
    test_typed_use_it_anyway_matches_the_button_behavior,
    test_autobuild_posts_script_review_chat_message_on_needs_review,
    test_autobuild_chat_post_failure_does_not_fail_the_build,
    test_direct_script_verb_also_posts_script_review_chat_message,
    test_direct_verb_needs_review_post_scoped_to_run_script_only,
]


if __name__ == "__main__":
    failed = 0
    for t in TESTS:
        try:
            t()
        except AssertionError as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)
