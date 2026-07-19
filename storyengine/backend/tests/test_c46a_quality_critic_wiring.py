"""C46a wiring locks: the generalized quality-critic hook inside
pipeline_executor.py.

Covers what tests/test_script_quality.py can't (that file is the pure
script_quality.py unit — no DB, no PipelineExecutor):

  - _grade_and_maybe_revise_script: absorbs the ONE grading call (no
    double-grading), sources rules_text from script_templates, persists
    edited scenes back to the `scripts` table + videos.script, attaches
    violations to videos.script_validation, reverts video status via
    hold_status when still needs_review after the bound.
  - run_script's THREE call sites: plain brief_translator path (gates the
    final status advance on the verdict), modeled path (passes hold_status
    since _run_modeled_script already advanced status before grading runs),
    and the static-docu roster path (telemetry-only, never gates).
  - user_supplied bypass: the critic must never run for a creator-supplied
    script (user_script.py's "creator's word is final" contract).

Local/no-spend: every Claude call is a fake client; every DB call is a fake
fetch_one/fetch_all/execute dispatched by query text, matching the pattern
tests/test_machine_documentary_hold.py already uses.
"""

import asyncio
import json

import pipeline_executor as pe


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


def _json_pass():
    return '{"verdict": "pass", "score": 90, "failing_gates": [], "rewrite_guidance": ""}'


def _json_revise():
    return json.dumps({
        "verdict": "revise", "score": 50,
        "failing_gates": ["hook speed"], "rewrite_guidance": "Open on the stake.",
    })


async def _noop(*_args, **_kwargs):
    return None


def _base_video(**overrides):
    video = {
        "id": "video-1",
        "video_title": "Title",
        "script": "Scene one text. Scene two text.",
        "script_validation": None,
        "executive_hook": None,
        "hook_script": None,
        "status": "ready_for_scripting",
    }
    video.update(overrides)
    return video


def _make_executor(video, anthropic, *, fetch_all_scenes=None, extra_fetch_one=None):
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
            return extra_fetch_one
        return None

    async def fake_fetch_all(query, *args):
        if "FROM scripts" in query:
            return fetch_all_scenes or []
        return []

    import database  # noqa: F401 - ensure module resolvable before patching pe's names

    executor.__dict__["_writes"] = writes
    return executor, fake_execute, fake_fetch_one, fake_fetch_all, writes


# ---------------------------------------------------------------------------
# _grade_and_maybe_revise_script — direct unit coverage
# ---------------------------------------------------------------------------

def test_absorbs_the_single_grade_call_no_double_grading(monkeypatch):
    video = _base_video()
    anthropic = FakeAnthropic([_json_pass()])
    executor, fake_execute, fake_fetch_one, fake_fetch_all, writes = _make_executor(
        video, anthropic,
        fetch_all_scenes=[
            {"scene": 1, "scene_text": "Scene one text."},
            {"scene": 2, "scene_text": "Scene two text."},
        ],
    )
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)

    result = asyncio.run(executor._grade_and_maybe_revise_script("video-1"))

    assert result == {"needs_review": False, "violations": []}
    assert len(anthropic.calls) == 1, "exactly one grading call — never a second grade_script call"
    # script_validation gains the quality_critic record; no scene edits happened.
    validation_writes = [w for w in writes if "script_validation" in w[0]]
    assert len(validation_writes) == 1
    saved = json.loads(validation_writes[0][1][0])
    assert saved["quality_critic"]["passed"] is True
    assert not any("DELETE FROM scripts" in w[0] for w in writes), "a pass verdict must not touch scene rows"


def test_sources_rules_text_from_script_templates_structure(monkeypatch):
    video = _base_video()
    anthropic = FakeAnthropic([_json_pass()])
    executor, fake_execute, fake_fetch_one, fake_fetch_all, writes = _make_executor(
        video, anthropic,
        fetch_all_scenes=[{"scene": 1, "scene_text": "Scene text."}],
        extra_fetch_one={"structure": "Always cold-open on a ticking clock."},
    )
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)

    asyncio.run(executor._grade_and_maybe_revise_script("video-1"))

    assert "Always cold-open on a ticking clock." in anthropic.calls[0]["system_prompt"]
    assert "CHANNEL RULES" in anthropic.calls[0]["system_prompt"]


def test_revise_edits_same_draft_and_persists_scenes(monkeypatch):
    video = _base_video()
    edited_raw = "@@@SCENE 1@@@\nAt 2am the alarm went off.\n@@@SCENE 2@@@\nScene two text."
    anthropic = FakeAnthropic([_json_revise(), edited_raw, _json_pass()])
    executor, fake_execute, fake_fetch_one, fake_fetch_all, writes = _make_executor(
        video, anthropic,
        fetch_all_scenes=[
            {"scene": 1, "scene_text": "Hey everyone, welcome back."},
            {"scene": 2, "scene_text": "Scene two text."},
        ],
    )
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)

    result = asyncio.run(executor._grade_and_maybe_revise_script("video-1"))

    assert result == {"needs_review": False, "violations": []}
    assert any("DELETE FROM scripts" in w[0] for w in writes)
    inserts = [w for w in writes if "INSERT INTO scripts" in w[0]]
    assert len(inserts) == 2
    assert inserts[0][1][3] == "At 2am the alarm went off."
    script_writes = [w for w in writes if w[0].strip().startswith("UPDATE videos SET script = ")]
    assert len(script_writes) == 1
    assert script_writes[0][1][0] == "At 2am the alarm went off.\n\nScene two text."


def test_still_failing_after_bound_is_needs_review_with_violations_attached(monkeypatch):
    video = _base_video()
    still_bad = "@@@SCENE 1@@@\nstill weak\n@@@SCENE 2@@@\nstill weak two"
    anthropic = FakeAnthropic([
        _json_revise(), still_bad, _json_revise(), still_bad, _json_revise(),
    ])
    executor, fake_execute, fake_fetch_one, fake_fetch_all, writes = _make_executor(
        video, anthropic,
        fetch_all_scenes=[
            {"scene": 1, "scene_text": "weak one"},
            {"scene": 2, "scene_text": "weak two"},
        ],
    )
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)

    result = asyncio.run(executor._grade_and_maybe_revise_script("video-1"))

    assert result["needs_review"] is True
    assert result["violations"] == ["hook speed"]
    validation_writes = [w for w in writes if "script_validation" in w[0]]
    saved = json.loads(validation_writes[-1][1][0])
    assert saved["quality_critic"]["passed"] is False
    assert saved["quality_critic"]["violations"] == ["hook speed"]
    assert not any("status = $1" in w[0] and "UPDATE videos SET status" in w[0] for w in writes), (
        "no hold_status was given — must not touch videos.status"
    )


def test_needs_review_with_hold_status_reverts_video_status(monkeypatch):
    video = _base_video()
    still_bad = "@@@SCENE 1@@@\nstill weak\n@@@SCENE 2@@@\nstill weak two"
    anthropic = FakeAnthropic([
        _json_revise(), still_bad, _json_revise(), still_bad, _json_revise(),
    ])
    executor, fake_execute, fake_fetch_one, fake_fetch_all, writes = _make_executor(
        video, anthropic,
        fetch_all_scenes=[
            {"scene": 1, "scene_text": "weak one"},
            {"scene": 2, "scene_text": "weak two"},
        ],
    )
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)

    result = asyncio.run(executor._grade_and_maybe_revise_script(
        "video-1", hold_status="ready_for_scripting",
    ))

    assert result["needs_review"] is True
    status_writes = [w for w in writes if w[0].strip().startswith("UPDATE videos SET status = ")]
    assert len(status_writes) == 1
    assert status_writes[0][1][0] == "ready_for_scripting"


def test_no_client_returns_falsy_so_legacy_callers_keep_advancing(monkeypatch):
    """A caller (or an old test) that ignores the return value and never
    checks it must keep the pre-C46a 'always advance' behavior — proven by
    the fact this returns {} (falsy) rather than raising or blocking."""
    video = _base_video()
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": None})()

    async def fake_fetch_one(query, *args):
        return dict(video) if "FROM videos" in query else None

    monkeypatch.setattr(pe, "fetch_one", fake_fetch_one)

    result = asyncio.run(executor._grade_and_maybe_revise_script("video-1"))
    assert result == {}


# ---------------------------------------------------------------------------
# run_script wiring — plain path gates the final status advance
# ---------------------------------------------------------------------------

def test_plain_path_short_circuits_to_needs_review(monkeypatch):
    payload = {}
    video = {
        "video_title": "Animated story",
        "render_mode": "animated",
        "status": "ready_for_scripting",
        "research_payload": payload,
    }

    class FakePipeline:
        def __init__(self):
            self.script_allowed_speakers = None
            self.script_format_contract = None

        async def run_brief_translator(self):
            return {"new_status": "ready_for_voice"}

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = FakePipeline()

    async def fake_get_video(_video_id):
        return video

    async def fake_fetch_all(*_a, **_k):
        return []

    calls = {"update_status": 0}

    async def fake_update_status(*_a, **_k):
        calls["update_status"] += 1

    async def fake_grade(_video_id, *_a, **_k):
        return {"needs_review": True, "violations": ["hook speed"]}

    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(executor, "_ensure_initialized", _noop)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_log_activity", _noop)
    monkeypatch.setattr(executor, "_log_transition", _noop)
    monkeypatch.setattr(executor, "_update_video_status", fake_update_status)
    monkeypatch.setattr(executor, "_inject_learnings_into_writer_guidance", _noop)
    monkeypatch.setattr(executor, "_load_prompt_overrides", _noop)
    monkeypatch.setattr(executor, "_grade_and_maybe_revise_script", fake_grade)
    monkeypatch.setattr(executor, "_load_idea_from_video", lambda _video_id: None)
    monkeypatch.setattr(executor, "_skip_disabled_next", lambda _video, status: status)

    result = asyncio.run(executor.run_script("video-test"))

    assert result == {
        "status": "needs_review", "video_id": "video-test", "violations": ["hook speed"],
        "message": "Quality critic still flags issues after the edit-loop bound: hook speed",
    }
    assert calls["update_status"] == 0, "a needs_review verdict must not advance the stage"


def test_plain_path_pass_still_advances_when_grade_returns_falsy(monkeypatch):
    """Backward-compat: a grade call that returns {} (no client, e.g.) must
    not block the pipeline — matches pre-C46a 'silent nudge' behavior."""
    video = {
        "video_title": "Animated story",
        "render_mode": "animated",
        "status": "ready_for_scripting",
        "research_payload": {},
    }

    class FakePipeline:
        script_allowed_speakers = None
        script_format_contract = None

        async def run_brief_translator(self):
            return {"new_status": "ready_for_voice"}

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = FakePipeline()

    async def fake_get_video(_video_id):
        return video

    async def fake_fetch_all(*_a, **_k):
        return []

    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(executor, "_ensure_initialized", _noop)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_log_activity", _noop)
    monkeypatch.setattr(executor, "_log_transition", _noop)
    monkeypatch.setattr(executor, "_update_video_status", _noop)
    monkeypatch.setattr(executor, "_inject_learnings_into_writer_guidance", _noop)
    monkeypatch.setattr(executor, "_load_prompt_overrides", _noop)
    monkeypatch.setattr(executor, "_grade_and_maybe_revise_script", lambda *_a, **_k: _noop())
    monkeypatch.setattr(executor, "_load_idea_from_video", lambda _video_id: None)
    monkeypatch.setattr(executor, "_skip_disabled_next", lambda _video, status: status)

    result = asyncio.run(executor.run_script("video-test"))
    assert result["status"] == "ready_for_voice"


# ---------------------------------------------------------------------------
# run_script wiring — modeled path passes hold_status and reverts on failure
# ---------------------------------------------------------------------------

def test_modeled_path_passes_hold_status_and_short_circuits_on_needs_review(monkeypatch):
    video = {
        "video_title": "Modeled video",
        "source": "modeled",
        "script_system_prompt": "STYLE PROMPT",
        "status": "ready_for_scripting",
    }

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {})()

    async def fake_get_video(_video_id):
        return video

    async def fake_run_modeled_script(_video_id, _video):
        return {"status": "ready_for_voice", "video_id": _video_id, "new_status": "ready_for_voice"}

    captured = {}

    async def fake_grade(_video_id, regenerate=None, *, hold_status=None):
        captured["hold_status"] = hold_status
        captured["regenerate"] = regenerate
        return {"needs_review": True, "violations": ["payoff"]}

    monkeypatch.setattr(executor, "_ensure_initialized", _noop)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_log_activity", _noop)
    monkeypatch.setattr(executor, "_inject_learnings_into_writer_guidance", _noop)
    monkeypatch.setattr(executor, "_run_modeled_script", fake_run_modeled_script)
    monkeypatch.setattr(executor, "_grade_and_maybe_revise_script", fake_grade)

    result = asyncio.run(executor.run_script("video-test"))

    assert result == {
        "status": "needs_review", "video_id": "video-test", "violations": ["payoff"],
        "message": "Quality critic still flags issues after the edit-loop bound: payoff",
    }
    assert captured["hold_status"] == "ready_for_scripting", (
        "the modeled path already advanced status before grading — hold_status must be passed"
    )
    assert captured["regenerate"] is not None


# ---------------------------------------------------------------------------
# run_script wiring — static-docu roster path: telemetry only, never gates
# ---------------------------------------------------------------------------

def test_static_docu_roster_path_calls_telemetry_but_never_gates(monkeypatch):
    video = {
        "video_title": "Designed vs Used: Strategic Bomber Lessons",
        "render_mode": "static_docu",
        "status": "ready_for_scripting",
        "research_payload": {
            "documentary_style": "designed_vs_used",
            "unit_roster": ["Boeing XB-15", "Boeing B-17", "Convair B-36"],
        },
    }

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {})()

    hold_result = {"status": "ready_for_voice", "video_id": "video-test", "new_status": "ready_for_voice"}

    async def fake_get_video(_video_id):
        return video

    async def fake_fetch_all(*_a, **_k):
        return []

    async def fake_hold(_video_id, _video, _roster):
        return hold_result

    telemetry_calls = []

    async def fake_telemetry(video_id, result):
        telemetry_calls.append((video_id, result))

    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(executor, "_ensure_initialized", _noop)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_log_activity", _noop)
    monkeypatch.setattr(executor, "_inject_learnings_into_writer_guidance", _noop)
    monkeypatch.setattr(executor, "_load_prompt_overrides", _noop)
    monkeypatch.setattr(executor, "_run_static_script_hold", fake_hold)
    monkeypatch.setattr(executor, "_telemetry_quality_critique", fake_telemetry)
    monkeypatch.setattr(executor, "_load_idea_from_video", lambda _video_id: None)

    async def forbidden_grade(*_a, **_k):
        raise AssertionError("static-docu roster path must not run the full critic+edit loop")

    monkeypatch.setattr(executor, "_grade_and_maybe_revise_script", forbidden_grade)

    result = asyncio.run(executor.run_script("video-test"))

    assert result == hold_result
    assert telemetry_calls == [("video-test", hold_result)]


def test_telemetry_critique_skips_on_failed_hold_result(monkeypatch):
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": FakeAnthropic([])})()

    async def forbidden_record(*_a, **_k):
        raise AssertionError("must not record telemetry when the hold itself failed")

    monkeypatch.setattr(executor, "_record_applied_retention", forbidden_record)

    asyncio.run(executor._telemetry_quality_critique("video-1", {"status": "failed", "error": "x"}))


def test_telemetry_critique_records_grade_without_editing(monkeypatch):
    video = _base_video()
    anthropic = FakeAnthropic([_json_revise()])
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": anthropic})()

    async def fake_get_video(_video_id):
        return video

    recorded = []

    async def fake_record(video_id, grade, regenerated):
        recorded.append((video_id, grade.verdict, regenerated))

    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_record_applied_retention", fake_record)

    asyncio.run(executor._telemetry_quality_critique(
        "video-1", {"status": "ready_for_voice", "new_status": "ready_for_voice"},
    ))

    assert len(anthropic.calls) == 1, "telemetry is one grading call, never an edit loop"
    assert recorded == [("video-1", "revise", False)]


# ---------------------------------------------------------------------------
# user_supplied bypass (user_script.py's "creator's word is final" contract)
# ---------------------------------------------------------------------------

def test_user_supplied_script_never_reaches_the_critic(monkeypatch):
    video = {
        "video_title": "Creator's own video",
        "status": "ready_for_scripting",
        "script": "The creator wrote every word of this.",
        "script_source": "user_supplied",
    }

    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {})()

    async def fake_get_video(_video_id):
        return video

    async def forbidden_grade(*_a, **_k):
        raise AssertionError("user_supplied scripts must bypass the critic entirely")

    monkeypatch.setattr(executor, "_ensure_initialized", _noop)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_log_activity", _noop)
    monkeypatch.setattr(executor, "_log_transition", _noop)
    monkeypatch.setattr(executor, "_update_video_status", _noop)
    monkeypatch.setattr(executor, "_grade_and_maybe_revise_script", forbidden_grade)
    monkeypatch.setattr(executor, "_skip_disabled_next", lambda _video, status: status)

    result = asyncio.run(executor.run_script("video-test"))

    assert result == {"status": "ready_for_voice", "video_id": "video-test"}
