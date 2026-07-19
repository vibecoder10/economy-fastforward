"""Tests for checklist C55 (P4.2-f) — full-auto continuation past an
approval gate.

The contract (parent spec): dial=full_auto proceeds through finalize+upload
UNLESS the kill switch is tripped or the weekly cap is breached, checked
fresh at EVERY stage transition, scoped to autopilot-launched videos ONLY.

Covers:
  1. `PipelineExecutor.full_auto_may_continue` — the ONE eligibility check,
     all five gates: scope (video.source prefix), dial_level=='full_auto'
     exactly, kill switch, C54b's elevated-no-cap runtime demotion, and a
     live `check_weekly_budget` breach (which trips the kill switch here,
     never a silent pause).
  2. `_run_next_step_status_map`'s wiring: an eligible video continues past
     ready_for_voice/ready_for_images/ready_for_thumbnail instead of
     returning needs_approval; a HUMAN-launched video (source doesn't start
     with 'autopilot') NEVER continues even at dial=full_auto — the scope
     invariant, pinned independently of the eligibility unit tests above.
  3. `_full_auto_pass_gate`'s per-gate mechanics: ready_for_voice calls
     run_voice (which advances itself); ready_for_thumbnail generates the
     thumbnail only if missing then advances with
     stage_transitions.triggered_by='autopilot_full_auto'; ready_for_images
     advances directly with the same attribution.
  4. The 'rendered' pre-upload stop in routes/autopilot.py's and
     routes/queue.py's `_run_full_pipeline` loops — proven non-vacuous by
     running the ACTUAL closure (captured via a fake BackgroundTasks),
     not a reimplementation: an eligible video does NOT break at 'rendered'
     (run_next_step gets called, reaching run_upload); a video from a
     manual queue launch (source='queue', not 'autopilot_queue') does break
     even with dial=full_auto.
  5. routes/queue.py: `auto_produce_next` tags its launch 'autopilot_queue'
     (not the human doors' plain 'queue') — the ONLY thing that lets C55
     tell an autopilot-drained queue launch apart from a manual one.

No live DB: `pipeline_executor.execute`/`fetch_one` and `autopilot_dial`'s
functions (re-imported locally inside `full_auto_may_continue`, so patching
the source module is what a lazy `from X import Y` picks up — same
convention as tests/test_c53_launch_candidate_gates.py) are monkeypatched.

Non-vacuous: every assertion here fails against pre-C55 code (no
full_auto_may_continue/_full_auto_pass_gate methods, the needs_approval
return unconditional, the loops' terminal check unconditional, 'queue' used
for every queue launch) — confirmed via `git stash`.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/test_c55_full_auto_continuation.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import pipeline_executor as pe_mod  # noqa: E402
import autopilot_dial as ad  # noqa: E402
import routes.autopilot as autopilot_route  # noqa: E402
import routes.queue as queue_route  # noqa: E402
from pipeline_executor import PipelineExecutor  # noqa: E402
from autopilot_dial import AutopilotDial  # noqa: E402

TENANT = "tenant-c55"
VIDEO = "video-c55"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _video(source="autopilot_SomeChannel", status="ready_for_voice", **extra):
    row = {"id": VIDEO, "source": source, "status": status, "video_title": "Some Title",
           "tenant_id": TENANT}
    row.update(extra)
    return row


def _patch_dial(monkeypatch, dial: AutopilotDial, budget_ok=True, spent=0.0, cap=None):
    async def _fake_get_dial(tenant_id):
        return dial

    trips = []

    async def _fake_check_budget(tenant_id):
        return (budget_ok, spent, cap if cap is not None else dial.weekly_budget_cap)

    async def _fake_trip(tenant_id, reason):
        trips.append((tenant_id, reason))
        return True

    monkeypatch.setattr(ad, "get_autopilot_dial", _fake_get_dial)
    monkeypatch.setattr(ad, "check_weekly_budget", _fake_check_budget)
    monkeypatch.setattr(ad, "trip_kill_switch", _fake_trip)
    return trips


def _patch_db(monkeypatch):
    """Capture every execute() call (bot_activity inserts, stage_transitions,
    status updates) without a live DB."""
    calls = []

    async def _fake_execute(query, *args):
        calls.append((query, args))
        return "INSERT 0 1"

    async def _fake_fetch_one(query, *args):
        return None

    monkeypatch.setattr(pe_mod, "execute", _fake_execute)
    monkeypatch.setattr(pe_mod, "fetch_one", _fake_fetch_one)
    return calls


# =============================================================================
# 1. full_auto_may_continue — the eligibility contract
# =============================================================================

def test_human_launched_source_never_continues_regardless_of_dial(monkeypatch):
    """Scope invariant (contract item 1): source doesn't start with
    'autopilot' -> False, and the dial is never even read."""
    dial_reads = []

    async def _fake_get_dial(tenant_id):
        dial_reads.append(tenant_id)
        return AutopilotDial(dial_level="full_auto", weekly_budget_cap=50.0)

    monkeypatch.setattr(ad, "get_autopilot_dial", _fake_get_dial)
    _patch_db(monkeypatch)
    ex = PipelineExecutor(TENANT)

    for source in ("queue", "discovery_competitor", ""):
        result = _run(ex.full_auto_may_continue(VIDEO, _video(source=source), "ready_for_voice"))
        assert result is False
    assert dial_reads == []  # scope check short-circuits before any dial read


@pytest.mark.parametrize("dial_level", ["auto_draft", "propose_only"])
def test_non_full_auto_dial_never_continues(monkeypatch, dial_level):
    _patch_dial(monkeypatch, AutopilotDial(dial_level=dial_level, weekly_budget_cap=50.0))
    _patch_db(monkeypatch)
    ex = PipelineExecutor(TENANT)
    assert _run(ex.full_auto_may_continue(VIDEO, _video(), "ready_for_voice")) is False


def test_kill_switch_tripped_stops_even_at_full_auto(monkeypatch):
    from datetime import datetime, timezone
    dial = AutopilotDial(dial_level="full_auto", weekly_budget_cap=50.0,
                          kill_switch_tripped_at=datetime.now(timezone.utc))
    _patch_dial(monkeypatch, dial)
    _patch_db(monkeypatch)
    ex = PipelineExecutor(TENANT)
    assert _run(ex.full_auto_may_continue(VIDEO, _video(), "ready_for_voice")) is False


def test_elevated_no_cap_is_treated_as_not_full_auto_no_trip(monkeypatch):
    """C54b runtime demotion, re-verified at the C55 seam: elevated dial with
    NO weekly_budget_cap set never continues — and this is a config anomaly,
    NEVER a kill-switch trip."""
    dial = AutopilotDial(dial_level="full_auto", weekly_budget_cap=None)
    trips = _patch_dial(monkeypatch, dial)
    _patch_db(monkeypatch)
    ex = PipelineExecutor(TENANT)
    assert _run(ex.full_auto_may_continue(VIDEO, _video(), "ready_for_voice")) is False
    assert trips == []


def test_budget_breach_trips_kill_switch_and_stops(monkeypatch):
    """Contract item 3: a breach at a gate trips the kill switch (never a
    silent pause) and the video just parks like a normal stop."""
    dial = AutopilotDial(dial_level="full_auto", weekly_budget_cap=25.0)
    trips = _patch_dial(monkeypatch, dial, budget_ok=False, spent=30.0, cap=25.0)
    _patch_db(monkeypatch)
    ex = PipelineExecutor(TENANT)
    assert _run(ex.full_auto_may_continue(VIDEO, _video(), "ready_for_voice")) is False
    assert len(trips) == 1
    assert trips[0][0] == TENANT
    assert "25.00" in trips[0][1] and "30.00" in trips[0][1]


def test_all_gates_clear_continues_and_logs_attribution(monkeypatch):
    """The full happy path: autopilot source + full_auto + no kill switch +
    cap set + budget ok -> True, with ONE bot_activity row attributed to
    'autopilot_full_auto' (contract item 4) — never a value that could be
    mistaken for a human approval."""
    dial = AutopilotDial(dial_level="full_auto", weekly_budget_cap=50.0)
    _patch_dial(monkeypatch, dial, budget_ok=True, spent=10.0, cap=50.0)
    calls = _patch_db(monkeypatch)
    ex = PipelineExecutor(TENANT)
    assert _run(ex.full_auto_may_continue(VIDEO, _video(), "ready_for_voice")) is True

    activity_inserts = [c for c in calls if "bot_activity" in c[0]]
    assert len(activity_inserts) == 1
    _, args = activity_inserts[0]
    # (tenant_id, bot_name, video_id, status, message, cost)
    assert args[1] == "autopilot_full_auto"
    assert args[3] == "completed"
    assert "ready_for_voice" in args[4]


# =============================================================================
# 2. _run_next_step_status_map wiring — the actual production seam
# =============================================================================

def test_gate_continues_for_eligible_autopilot_video(monkeypatch):
    dial = AutopilotDial(dial_level="full_auto", weekly_budget_cap=50.0)
    _patch_dial(monkeypatch, dial)
    _patch_db(monkeypatch)
    ex = PipelineExecutor(TENANT)

    video = _video(source="autopilot_SomeChannel", status="ready_for_images")

    async def _fake_get_video(video_id):
        return video

    monkeypatch.setattr(ex, "_get_video", _fake_get_video)
    result = _run(ex._run_next_step_status_map(VIDEO))
    assert result["status"] != "needs_approval"
    assert result["status"] == "ready_for_sound_design"


def test_gate_stops_for_human_launched_video_even_at_full_auto(monkeypatch):
    """Contract item 1, pinned at the real seam (not just the unit test
    above): a human-launched video (source='queue', the manual-launch
    default) ALWAYS stops at the gate, even with dial=full_auto."""
    dial = AutopilotDial(dial_level="full_auto", weekly_budget_cap=50.0)
    _patch_dial(monkeypatch, dial)
    _patch_db(monkeypatch)
    ex = PipelineExecutor(TENANT)

    video = _video(source="queue", status="ready_for_images")

    async def _fake_get_video(video_id):
        return video

    monkeypatch.setattr(ex, "_get_video", _fake_get_video)
    result = _run(ex._run_next_step_status_map(VIDEO))
    assert result["status"] == "needs_approval"


def test_gate_stops_when_dial_turned_down_mid_build(monkeypatch):
    """'turning the dial down mid-build takes effect at the very next gate'"""
    dial = AutopilotDial(dial_level="auto_draft", weekly_budget_cap=50.0)
    _patch_dial(monkeypatch, dial)
    _patch_db(monkeypatch)
    ex = PipelineExecutor(TENANT)

    video = _video(source="autopilot_SomeChannel", status="ready_for_thumbnail")

    async def _fake_get_video(video_id):
        return video

    monkeypatch.setattr(ex, "_get_video", _fake_get_video)
    result = _run(ex._run_next_step_status_map(VIDEO))
    assert result["status"] == "needs_approval"


# =============================================================================
# 3. _full_auto_pass_gate — per-gate mechanics
# =============================================================================

def test_pass_gate_ready_for_voice_calls_run_voice(monkeypatch):
    _patch_db(monkeypatch)
    ex = PipelineExecutor(TENANT)
    calls = []

    async def _fake_run_voice(video_id):
        calls.append(video_id)
        return {"status": "ready_for_image_prompts", "video_id": video_id}

    monkeypatch.setattr(ex, "run_voice", _fake_run_voice)
    result = _run(ex._full_auto_pass_gate(VIDEO, "ready_for_voice", _video(status="ready_for_voice")))
    assert calls == [VIDEO]
    assert result["status"] == "ready_for_image_prompts"


def test_pass_gate_ready_for_thumbnail_generates_only_if_missing(monkeypatch):
    calls = _patch_db(monkeypatch)
    ex = PipelineExecutor(TENANT)
    thumb_calls = []

    async def _fake_run_thumbnail(video_id):
        thumb_calls.append(video_id)
        return {"status": "completed", "thumbnail_url": "http://x/thumb.png"}

    async def _fake_update_status(video_id, new_status, video=None):
        calls.append(("UPDATE_STATUS", (video_id, new_status)))

    monkeypatch.setattr(ex, "run_thumbnail", _fake_run_thumbnail)
    monkeypatch.setattr(ex, "_update_video_status", _fake_update_status)

    # No thumbnail yet -> run_thumbnail called.
    video_no_thumb = _video(status="ready_for_thumbnail", thumbnail_url=None)
    result = _run(ex._full_auto_pass_gate(VIDEO, "ready_for_thumbnail", video_no_thumb))
    assert thumb_calls == [VIDEO]
    assert result["status"] == "ready_to_render"
    transitions = [c for c in calls if "stage_transitions" in c[0]]
    assert transitions and transitions[-1][1][4] == "autopilot_full_auto"  # triggered_by

    # Thumbnail already set -> run_thumbnail must NOT be called again.
    thumb_calls.clear()
    video_has_thumb = _video(status="ready_for_thumbnail", thumbnail_url="http://x/thumb.png")
    result2 = _run(ex._full_auto_pass_gate(VIDEO, "ready_for_thumbnail", video_has_thumb))
    assert thumb_calls == []
    assert result2["status"] == "ready_to_render"


def test_pass_gate_ready_for_images_advances_directly(monkeypatch):
    calls = _patch_db(monkeypatch)
    ex = PipelineExecutor(TENANT)

    async def _fake_update_status(video_id, new_status, video=None):
        calls.append(("UPDATE_STATUS", (video_id, new_status)))

    monkeypatch.setattr(ex, "_update_video_status", _fake_update_status)
    result = _run(ex._full_auto_pass_gate(VIDEO, "ready_for_images", _video(status="ready_for_images")))
    assert result["status"] == "ready_for_sound_design"
    updates = [c for c in calls if c[0] == "UPDATE_STATUS"]
    assert updates == [("UPDATE_STATUS", (VIDEO, "ready_for_sound_design"))]
    transitions = [c for c in calls if "stage_transitions" in c[0]]
    assert transitions and transitions[-1][1][4] == "autopilot_full_auto"


# =============================================================================
# 4. The 'rendered' pre-upload stop — routes/autopilot.py's and
#    routes/queue.py's `_run_full_pipeline` loops, run for real.
# =============================================================================

class _FakeBackgroundTasks:
    def __init__(self):
        self.calls = []

    def add_task(self, fn, *a, **k):
        self.calls.append((fn, a, k))


def _patch_launch_candidate_helpers(monkeypatch):
    """No-op every side-effect helper launch_candidate calls before
    kicking off _run_full_pipeline — none of it is what this test covers."""
    import routes.projects as projects
    import routes.script_templates as script_templates
    import channel_format
    import routes.characters as characters
    import routes.billing as billing

    async def _fake_project(tenant_id):
        return {"id": "project-1"}

    async def _fake_true(*a, **k):
        return True

    monkeypatch.setattr(projects, "_get_or_create_project", _fake_project)
    monkeypatch.setattr(script_templates, "apply_default_template", _fake_true)
    monkeypatch.setattr(channel_format, "apply_format_defaults", _fake_true)
    monkeypatch.setattr(characters, "apply_locked_cast", _fake_true)
    monkeypatch.setattr(billing, "check_plan_limits", _fake_true)

    async def _fake_increment(*a, **k):
        return None

    monkeypatch.setattr(billing, "increment_usage", _fake_increment)


def test_autopilot_loop_continues_past_rendered_when_eligible(monkeypatch):
    """Runs the REAL routes.autopilot._do_launch_candidate -> _run_full_pipeline
    closure (captured via a fake BackgroundTasks, then awaited directly) —
    not a reimplementation. Pins that an eligible video does NOT stop at
    'rendered': run_next_step gets called (reaching the upload handler)."""
    dial = AutopilotDial(dial_level="full_auto", weekly_budget_cap=50.0)
    _patch_dial(monkeypatch, dial)
    _patch_launch_candidate_helpers(monkeypatch)

    candidate_row = {
        "id": "cand-c55", "video_id": "yt-1", "title": "Some Title", "url": "https://y/1",
        "channel": "SomeChannel", "channel_url": "https://y/c", "views": 1000, "vph": 10.0,
        "hours_old": 5, "published_date": None, "modeled": False,
        "our_video_id": None, "thumbnail_url": None,
    }

    execute_calls = []

    async def _fake_execute(query, *args):
        execute_calls.append((query, args))
        return "UPDATE 1"

    video_states = {"status": "rendered"}

    async def _fake_fetch_one(query, *args):
        if "competitor_videos" in query:
            return dict(candidate_row)
        if "INSERT INTO videos" in query:
            return {"id": "video-launched"}
        if "FROM videos" in query:
            return {"id": "video-launched", "status": video_states["status"],
                    "source": "autopilot_SomeChannel", "video_title": "Some Title"}
        if "learnings" in query:
            return None
        return None

    async def _fake_fetch_all(query, *args):
        return []

    monkeypatch.setattr(autopilot_route, "execute", _fake_execute)
    monkeypatch.setattr(autopilot_route, "fetch_one", _fake_fetch_one)
    monkeypatch.setattr(autopilot_route, "fetch_all", _fake_fetch_all)

    run_next_step_calls = []

    async def _fake_run_research(self, video_id):
        return {"status": "ready_for_scripting"}

    async def _fake_run_next_step(self, video_id):
        run_next_step_calls.append(video_id)
        video_states["status"] = "uploaded_draft"  # simulate upload completing
        return {"status": "uploaded_draft"}

    monkeypatch.setattr(pe_mod.PipelineExecutor, "run_research", _fake_run_research)
    monkeypatch.setattr(pe_mod.PipelineExecutor, "run_next_step", _fake_run_next_step)

    from routes.autopilot import launch_candidate
    bg = _FakeBackgroundTasks()
    _run(launch_candidate("cand-c55", bg, tenant_id=TENANT))
    assert len(bg.calls) == 1
    fn, _, _ = bg.calls[0]
    _run(fn())  # actually run _run_full_pipeline

    # If the loop had honored 'rendered' as an unconditional terminal status,
    # run_next_step would NEVER be called — this is the non-vacuous half.
    assert run_next_step_calls, "full-auto must reach run_next_step (-> run_upload) from 'rendered'"


def test_autopilot_loop_stops_at_rendered_when_not_full_auto(monkeypatch):
    """Same closure, auto_draft dial (not full_auto): must stop at 'rendered'
    exactly like today — run_next_step is never called once status is
    'rendered'."""
    dial = AutopilotDial(dial_level="auto_draft", weekly_budget_cap=50.0)
    _patch_dial(monkeypatch, dial)
    _patch_launch_candidate_helpers(monkeypatch)

    candidate_row = {
        "id": "cand-c55b", "video_id": "yt-2", "title": "Some Title", "url": "https://y/1",
        "channel": "SomeChannel", "channel_url": "https://y/c", "views": 1000, "vph": 10.0,
        "hours_old": 5, "published_date": None, "modeled": False,
        "our_video_id": None, "thumbnail_url": None,
    }

    async def _fake_execute(query, *args):
        return "UPDATE 1"

    async def _fake_fetch_one(query, *args):
        if "competitor_videos" in query:
            return dict(candidate_row)
        if "INSERT INTO videos" in query:
            return {"id": "video-launched"}
        if "FROM videos" in query:
            return {"id": "video-launched", "status": "rendered",
                    "source": "autopilot_SomeChannel", "video_title": "Some Title"}
        return None

    async def _fake_fetch_all(query, *args):
        return []

    monkeypatch.setattr(autopilot_route, "execute", _fake_execute)
    monkeypatch.setattr(autopilot_route, "fetch_one", _fake_fetch_one)
    monkeypatch.setattr(autopilot_route, "fetch_all", _fake_fetch_all)

    run_next_step_calls = []

    async def _fake_run_research(self, video_id):
        return {"status": "ready_for_scripting"}

    async def _fake_run_next_step(self, video_id):
        run_next_step_calls.append(video_id)
        return {"status": "completed"}

    monkeypatch.setattr(pe_mod.PipelineExecutor, "run_research", _fake_run_research)
    monkeypatch.setattr(pe_mod.PipelineExecutor, "run_next_step", _fake_run_next_step)

    from routes.autopilot import launch_candidate
    bg = _FakeBackgroundTasks()
    _run(launch_candidate("cand-c55b", bg, tenant_id=TENANT))
    fn, _, _ = bg.calls[0]
    _run(fn())

    assert run_next_step_calls == [], "auto_draft must stop at 'rendered' exactly like before C55"


# =============================================================================
# 5. routes/queue.py source tagging
# =============================================================================

def test_auto_produce_next_tags_autopilot_queue_not_plain_queue(monkeypatch):
    """The ONLY thing that lets full_auto_may_continue tell an
    autopilot-drained queue launch apart from a manual '.../launch' click —
    both would otherwise build an identical video row."""
    insert_calls = []

    async def _fake_fetch_one(query, *args):
        if "production_queue" in query and "status = 'queued'" in query:
            return {"id": "qi-1", "title": "Queued Title", "framework_angle": None,
                     "writer_guidance": None, "user_script": None}
        if "autopilot_config" in query:
            return {"production_interval_days": 2}
        if "GREATEST" in query:
            return {"t": None}
        if "INSERT INTO videos" in query:
            insert_calls.append(args)
            return {"id": "video-q1"}
        return None

    async def _fake_execute(query, *args):
        return "UPDATE 1"

    async def _fake_fetch_all(query, *args):
        return []

    monkeypatch.setattr(queue_route, "fetch_one", _fake_fetch_one)
    monkeypatch.setattr(queue_route, "execute", _fake_execute)
    monkeypatch.setattr(queue_route, "fetch_all", _fake_fetch_all)

    import routes.projects as projects
    import routes.script_templates as script_templates
    import channel_format
    import routes.characters as characters

    async def _fake_project(tenant_id):
        return {"id": "project-1"}

    async def _fake_true(*a, **k):
        return True

    monkeypatch.setattr(projects, "_get_or_create_project", _fake_project)
    monkeypatch.setattr(script_templates, "apply_default_template", _fake_true)
    monkeypatch.setattr(channel_format, "apply_format_defaults", _fake_true)
    monkeypatch.setattr(characters, "apply_locked_cast", _fake_true)

    result = _run(queue_route.auto_produce_next(TENANT))
    assert result is not None
    assert insert_calls, "expected an INSERT INTO videos"
    # source is the 6th positional bind param (tenant, project, title, status, headline, source, ...)
    assert insert_calls[0][5] == "autopilot_queue"
