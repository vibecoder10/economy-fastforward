"""Tests for wiring the two approval gates INTO the autobuild chain
(actions.make_autobuild_step) — the follow-up the product owner asked for
after seeing the first cut: "the autobuild gap is the whole feature, not a
follow-up." Since 2026-07-27's front-door fix, typing an idea into
DirectorHome's box sends explicit_verb="build" straight into this chain —
it is now the MAIN path a video gets made, so a gate that only fires on the
conversational verb-classification path (test_approval_gates.py) does not
deliver "pause at every cheap stage" at all for that path.

This file proves, against the REAL actions.make_autobuild_step (not a
sentinel replacement — every other existing autobuild test, e.g.
test_c16a_generation_claims.py / test_autobuild_explicit_research_plan.py,
replaces this factory with a stub; this is the first to drive its actual
loop through the two new checkpoints):

  1. The chain PAUSES right after the script (before any character/
     environment generation call), the first time a video has none —
     `run_characters` is never called before the pause.
  2. The chain PAUSES again right after designing the cast+locations
     (before `generate_coverage_for_video`, the expensive per-shot picture
     generator) — `generate_coverage_for_video` is never called before
     this second pause.
  3. Resuming (re-invoking make_autobuild_step with the SAME target, the
     exact mechanism `_run_pending_action`'s "build" verb already uses) from
     a video that already has a character/environment does NOT call
     run_characters/the environments design step again — the guard that
     stops a resume from re-spending on cast/location sheets neither of
     those two functions skip-if-done on their own (verified by reading
     both: pipeline_executor.run_characters and routes.environments.
     run_environments_design_step both unconditionally DELETE-then-
     regenerate every call).
  4. Once both gates have cleared (characters_approved_at AND
     environments_approved_at both set — exactly what the approval_gate
     "yes" handshake stamps, tests/functional/test_approval_gates.py's
     test_looks_good_on_anchors_gate_stamps_approval_columns_before_
     resuming), the chain proceeds into the existing coverage/pictures
     phase unchanged.
  5. Each pause posts into the video's chat conversation via
     routes.chat._post_approval_gate_for_autobuild with resume=
     {"verb": "build", "target": target, ...} — the SAME approval_gate
     mechanism test_approval_gates.py already covers end to end (its
     test_looks_good_resumes_the_exact_quoted_action proves "Looks good!"
     resumes via _run_pending_action; this file only needs to prove THIS
     caller reaches that same seam with the right arguments, not
     re-prove the handshake itself).

No live DB, no network, no real image/text generation anywhere in this
file — pipeline_executor.PipelineExecutor and routes.environments.
run_environments_design_step are BOTH fully replaced with fakes that never
call a real API; database reads/writes go through an in-memory fake video
store. Same sys.modules-stubbing pattern test_autobuild_explicit_
research_plan.py already uses for the SAME two lazy imports
(pipeline_executor, routes.pipeline) inside this exact function.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_approval_gates_autobuild.py -q
"""
import asyncio
import os
import sys
import types
from unittest.mock import patch

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))

import actions  # noqa: E402

TENANT = "tenant-1"
VIDEO = "video-1"


class _FakeVideoDB:
    """A tiny in-memory stand-in for the `videos` / `video_characters` /
    `video_environments` tables — enough for make_autobuild_step's real
    control flow (status reads/writes, count queries, approval-column
    reads/writes) to behave exactly like the real SQL would, without a
    live DB. `run_characters`/the fake environments step mutate this SAME
    object, so a resumed run sees the truth left behind by the paused one
    — the same durable-state continuity the real Postgres row provides.
    """

    def __init__(self, **video):
        self.video = {
            "status": "ready_for_scripting",
            "render_mode": None,
            "pipeline_stages": None,
            "max_spend": None,
            "total_cost": 0,
            "characters_approved_at": None,
            "environments_approved_at": None,
            **video,
        }
        self.characters: list[dict] = []
        self.environments: list[dict] = []
        self.executed: list[tuple] = []

    async def fetch_one(self, query, *args):
        q = query
        if "pipeline_stages FROM videos" in q:
            return {"pipeline_stages": self.video.get("pipeline_stages")}
        if "SELECT status FROM videos" in q:
            return {"status": self.video.get("status")}
        if "characters_approved_at, environments_approved_at FROM videos" in q:
            return {
                "characters_approved_at": self.video.get("characters_approved_at"),
                "environments_approved_at": self.video.get("environments_approved_at"),
            }
        if "status, max_spend, total_cost FROM videos" in q:
            return dict(self.video)
        if "1 AS x FROM scripts" in q:
            return None  # voice already present — irrelevant to target="pictures"
        if "count(*) AS n FROM video_characters" in q:
            return {"n": len(self.characters)}
        if "count(*) AS n FROM video_environments" in q:
            return {"n": len(self.environments)}
        raise AssertionError(f"unexpected fetch_one: {query!r}")

    async def execute(self, query, *args):
        self.executed.append((query, args))
        if query.strip().startswith("UPDATE videos SET status="):
            self.video["status"] = args[0]
        if "characters_approved_at = COALESCE" in query and "environments_approved_at = COALESCE" in query:
            self.video["characters_approved_at"] = self.video.get("characters_approved_at") or "stamped"
            self.video["environments_approved_at"] = self.video.get("environments_approved_at") or "stamped"
        if query.strip().startswith("UPDATE videos SET environments_approved_at = NULL"):
            self.video["environments_approved_at"] = None
        return "OK"


class _FakeExecutor:
    """Stands in for PipelineExecutor — only the methods make_autobuild_step's
    script/characters branches actually call. `run_next_step`/coverage are
    intentionally NOT exercised by the pause tests (the whole point is that
    execution never reaches them before a pause) — coverage IS exercised by
    the "both approved -> proceeds" test via a patched
    scripts.coverage_to_app.generate_coverage_for_video.
    """

    def __init__(self, tenant_id, db: _FakeVideoDB):
        self.tenant_id = tenant_id
        self.db = db
        self.run_script_calls = 0
        self.run_characters_calls = 0
        self.run_story_bible_calls = 0

    async def _get_video(self, video_id):
        return dict(self.db.video)

    async def run_script(self, video_id, progress_callback=None):
        self.run_script_calls += 1
        # Real run_script both writes the script AND advances the video's
        # status internally (pipeline_executor.py, confirmed by reading it) —
        # jump straight to the image-prompts checkpoint, same simplification
        # test_autobuild_explicit_research_plan.py's fake makes for the
        # unrelated research branch: the voice-skip hop in between is
        # existing, unchanged, separately-tested machinery, not what this
        # file is proving.
        self.db.video["status"] = "ready_for_image_prompts"
        return {"status": "completed"}

    async def run_characters(self, video_id):
        self.run_characters_calls += 1
        self.db.characters.append({"name": "Nyla", "reference_url": "http://example/nyla.png"})
        return {"status": "completed", "message": "Cast designed: 1/1 character sheets ready."}

    async def run_story_bible(self, video_id):
        self.run_story_bible_calls += 1

    async def run_next_step(self, video_id):
        # Only reached by statuses this file's fakes never drive into
        # (everything under test resolves inside the script/image-prompts
        # branches above) — 'idle' is the loop's own clean-stop signal,
        # so a test that DID reach this unexpectedly still exits tidily
        # (visible via the task-status recorder) instead of masking a
        # bug as a silent "no gate calls" pass.
        return {"status": "idle"}


def _make_fake_pipeline_executor_module(db: _FakeVideoDB, holder: list):
    def _factory(tenant_id):
        ex = _FakeExecutor(tenant_id, db)
        holder.append(ex)
        return ex
    mod = types.ModuleType("pipeline_executor")
    mod.PipelineExecutor = _factory
    return mod


def _make_fake_routes_pipeline_module(status_calls: list):
    # Recording every _set_task_status call (not just a no-op) is what
    # catches a silent AttributeError/exception inside _run()'s try/except —
    # without this, a bug that crashes the loop would still leave
    # gate_calls==[] and read as a passing "no gate fired" assertion.
    def _record(video_id, status, message=None, error=None, *, tenant_id, task_type="pipeline"):
        status_calls.append({"status": status, "message": message, "error": error})
    mod = types.ModuleType("routes.pipeline")
    mod._set_task_status = _record
    mod._clear_task_status = lambda *a, **k: None
    return mod


def _make_fake_routes_chat_module(gate_calls: list):
    async def _fake_post_gate(tenant_id, video_id, gate_kind, resume):
        gate_calls.append({"tenant_id": tenant_id, "video_id": video_id,
                            "gate_kind": gate_kind, "resume": resume})
    mod = types.ModuleType("routes.chat")
    mod._post_approval_gate_for_autobuild = _fake_post_gate
    return mod


def _make_fake_routes_environments_module(db: _FakeVideoDB, holder: list):
    async def _fake_design(video, tenant_id, progress=None):
        holder.append(1)
        db.environments.append({"name": "Warren", "reference_url": "http://example/warren.png"})
        return {"status": "completed", "message": "Environments designed: 1/1 references ready."}
    mod = types.ModuleType("routes.environments")
    mod.run_environments_design_step = _fake_design
    return mod


def _run_autobuild(db: _FakeVideoDB, *, target: str = "pictures", coverage=None):
    """Drive actions.make_autobuild_step(...)() to completion against fakes —
    same asyncio.sleep patch-out test_autobuild_explicit_research_plan.py
    uses (the real _run() sleeps ~20s in its finally block)."""
    ex_holder: list = []
    gate_calls: list = []
    env_calls: list = []
    status_calls: list = []
    fake_pe = _make_fake_pipeline_executor_module(db, ex_holder)
    fake_rp = _make_fake_routes_pipeline_module(status_calls)
    fake_rc = _make_fake_routes_chat_module(gate_calls)
    fake_re = _make_fake_routes_environments_module(db, env_calls)

    async def _fast_sleep(*_a, **_k):
        return None

    coverage_calls = []

    async def _fake_coverage(video_id, tenant_id, progress=None):
        coverage_calls.append((video_id, tenant_id))
        if coverage:
            return coverage
        return {"status": "completed"}

    fake_coverage_mod = types.ModuleType("scripts.coverage_to_app")
    fake_coverage_mod.generate_coverage_for_video = _fake_coverage

    with patch.dict(sys.modules, {
        "pipeline_executor": fake_pe,
        "routes.pipeline": fake_rp,
        "routes.chat": fake_rc,
        "routes.environments": fake_re,
        "scripts.coverage_to_app": fake_coverage_mod,
    }), patch.object(actions, "fetch_one", db.fetch_one), \
         patch.object(actions, "execute", db.execute), \
         patch("asyncio.sleep", _fast_sleep):
        step = actions.make_autobuild_step(TENANT, VIDEO, target=target)
        asyncio.run(step())

    failures = [c for c in status_calls if c["status"] == "failed"]
    assert not failures, f"the loop must not silently fail — got {failures}"
    return {
        "executor": ex_holder[0] if ex_holder else None,
        "gate_calls": gate_calls,
        "env_calls": env_calls,
        "coverage_calls": coverage_calls,
        "status_calls": status_calls,
    }


# ---------------------------------------------------------------------------
# 1. Checkpoint 1 (script gate): pauses right after the script, before ANY
#    character/environment/coverage call.
# ---------------------------------------------------------------------------

def test_pauses_after_script_before_designing_cast():
    db = _FakeVideoDB(status="ready_for_scripting")
    result = _run_autobuild(db)

    assert result["executor"].run_script_calls == 1
    assert result["executor"].run_characters_calls == 0, "must NOT design the cast before the script gate is approved"
    assert result["env_calls"] == [], "must NOT design locations before the script gate is approved"
    assert result["coverage_calls"] == [], "must NOT spend on pictures before the script gate is approved"
    assert db.video["status"] == "ready_for_image_prompts", "the script's own status advance is real and durable"
    assert len(result["gate_calls"]) == 1
    gate = result["gate_calls"][0]
    assert gate["gate_kind"] == "script"
    # Reuses the SAME approval_gate mechanism, not a second one: resuming
    # is a "build" verb resume, exactly what _run_pending_action's existing
    # build branch (and hence the untouched approval_gate handshake) knows
    # how to schedule.
    assert gate["resume"] == {"verb": "build", "target": "pictures", "scene": None, "change": "", "length_min": None}
    print("✅ test_pauses_after_script_before_designing_cast")


def test_finish_target_never_hits_the_script_gate():
    """target='finish' runs on a video long past this checkpoint (pictures
    already exist) — must never re-enter the ready_for_scripting branch's
    gate check. Status starts past BUILD_TO_PICTURES so the loop's own
    normal 'nothing left to do at this altitude' logic exits fast; script
    is never re-run and no gate fires."""
    db = _FakeVideoDB(status="ready_for_thumbnail")
    result = _run_autobuild(db, target="finish")

    assert result["gate_calls"] == []
    print("✅ test_finish_target_never_hits_the_script_gate")


# ---------------------------------------------------------------------------
# 2. Checkpoint 2 (anchors gate): designs cast+locations (cheap), then
#    pauses BEFORE coverage (the expensive per-shot picture generator).
# ---------------------------------------------------------------------------

def test_designs_cast_and_locations_then_pauses_before_coverage():
    db = _FakeVideoDB(status="ready_for_image_prompts")
    result = _run_autobuild(db)

    assert result["executor"].run_characters_calls == 1, "must design the cast once, cheaply, before the gate"
    assert len(result["env_calls"]) == 1, "must design the locations once, cheaply, before the gate"
    assert result["coverage_calls"] == [], "must NOT draw the (expensive) pictures before the anchors gate is approved"
    assert len(db.characters) == 1 and len(db.environments) == 1
    assert len(result["gate_calls"]) == 1
    gate = result["gate_calls"][0]
    assert gate["gate_kind"] == "anchors"
    assert gate["resume"] == {"verb": "build", "target": "pictures", "scene": None, "change": "", "length_min": None}
    # The gate is what's supposed to stamp approval (via the "Looks good!"
    # handshake, tested separately in test_approval_gates.py) — a mere
    # pause must NOT silently auto-approve, unlike the old COALESCE-stamp
    # behavior this checkpoint replaces.
    assert db.video["characters_approved_at"] is None
    assert db.video["environments_approved_at"] is None
    print("✅ test_designs_cast_and_locations_then_pauses_before_coverage")


def test_resuming_does_not_redo_the_cast_or_locations():
    """The core 'must not redo paid work' proof: a video that already has a
    character and an environment (the paused-and-not-yet-approved state,
    OR a genuine resume where design succeeded but the process was
    interrupted before the gate posted) must NOT call run_characters or
    the environments step again — neither function skips-if-done on its
    own, so this guard is the only thing standing between a resume and a
    second, wasted charge."""
    db = _FakeVideoDB(
        status="ready_for_image_prompts",
        characters_approved_at=None, environments_approved_at=None,
    )
    db.characters.append({"name": "Nyla", "reference_url": "http://example/nyla.png"})
    db.environments.append({"name": "Warren", "reference_url": "http://example/warren.png"})

    result = _run_autobuild(db)

    assert result["executor"].run_characters_calls == 0, "already has a character — must not regenerate"
    assert result["env_calls"] == [], "already has an environment — must not regenerate"
    assert result["coverage_calls"] == [], "still not approved — must still pause, not proceed"
    assert len(result["gate_calls"]) == 1
    assert result["gate_calls"][0]["gate_kind"] == "anchors"
    print("✅ test_resuming_does_not_redo_the_cast_or_locations")


def test_both_approved_proceeds_into_coverage_unchanged():
    """Once the anchors gate has cleared (both approval columns set — what
    the approval_gate 'yes' handshake stamps), the chain proceeds into the
    EXISTING coverage/pictures phase exactly as it always did — no gate,
    no re-design."""
    db = _FakeVideoDB(
        status="ready_for_image_prompts",
        characters_approved_at="2026-01-01T00:00:00Z",
        environments_approved_at="2026-01-01T00:00:00Z",
    )
    db.characters.append({"name": "Nyla", "reference_url": "http://example/nyla.png"})
    db.environments.append({"name": "Warren", "reference_url": "http://example/warren.png"})

    result = _run_autobuild(db)

    assert result["executor"].run_characters_calls == 0
    assert result["env_calls"] == []
    assert result["gate_calls"] == [], "an already-approved video must not see the gate again"
    assert len(result["coverage_calls"]) == 1, "the existing coverage phase must still run once both gates cleared"
    assert db.video["status"] == "ready_for_images"
    print("✅ test_both_approved_proceeds_into_coverage_unchanged")


def test_static_docu_is_never_gated():
    """static_docu videos never design a cast/locations at all (their own
    three-view branch, unchanged) — neither checkpoint may fire for this
    render_mode, at either the script or the image-phase point. Falls
    through into the EXISTING (unchanged, pre-this-feature) static_docu
    image branch, which imports the real `static_docu` module — stubbed
    here purely so that unrelated, untouched code path can complete inside
    this pure-unit harness (no DATABASE_URL available); it is not part of
    what this test is proving."""
    fake_static_docu = types.ModuleType("static_docu")

    async def _fake_static_gen(video_id, tenant_id, progress=None):
        return {"status": "completed"}
    fake_static_docu.generate_static_images_for_video = _fake_static_gen

    db = _FakeVideoDB(status="ready_for_scripting", render_mode="static_docu")
    with patch.dict(sys.modules, {"static_docu": fake_static_docu}):
        result = _run_autobuild(db)
    assert result["gate_calls"] == [], "static_docu must never see either gate"
    assert result["executor"].run_characters_calls == 0
    print("✅ test_static_docu_is_never_gated (script phase)")

    db2 = _FakeVideoDB(status="ready_for_image_prompts", render_mode="static_docu")
    with patch.dict(sys.modules, {"static_docu": fake_static_docu}):
        result2 = _run_autobuild(db2)
    assert result2["gate_calls"] == []
    assert result2["executor"].run_characters_calls == 0
    print("✅ test_static_docu_is_never_gated (image phase)")


def test_nothing_to_gate_skips_straight_through():
    """A script with genuinely no recurring characters AND no recurring
    locations (run_characters/env design both come back empty) has nothing
    to review — auto-stamp both columns (matching skip_environments'
    existing "no distinct locations, unlocked" philosophy) and proceed,
    rather than showing an empty 'Characters x 0, Locations x 0' gate."""
    class _EmptyExecutor(_FakeExecutor):
        async def run_characters(self, video_id):
            self.run_characters_calls += 1
            return {"status": "failed", "error": "No recurring characters found in this script."}

    db = _FakeVideoDB(status="ready_for_image_prompts")
    ex_holder: list = []
    gate_calls: list = []

    def _factory(tenant_id):
        ex = _EmptyExecutor(tenant_id, db)
        ex_holder.append(ex)
        return ex

    fake_pe = types.ModuleType("pipeline_executor")
    fake_pe.PipelineExecutor = _factory
    status_calls: list = []
    fake_rp = _make_fake_routes_pipeline_module(status_calls)
    fake_rc = _make_fake_routes_chat_module(gate_calls)

    async def _fake_design_empty(video, tenant_id, progress=None):
        return {"status": "failed", "error": "No recurring locations found in the script — this video can skip environment design."}
    fake_re = types.ModuleType("routes.environments")
    fake_re.run_environments_design_step = _fake_design_empty

    coverage_calls = []

    async def _fake_coverage(video_id, tenant_id, progress=None):
        coverage_calls.append(1)
        return {"status": "completed"}
    fake_cov = types.ModuleType("scripts.coverage_to_app")
    fake_cov.generate_coverage_for_video = _fake_coverage

    async def _fast_sleep(*_a, **_k):
        return None

    with patch.dict(sys.modules, {
        "pipeline_executor": fake_pe, "routes.pipeline": fake_rp,
        "routes.chat": fake_rc, "routes.environments": fake_re,
        "scripts.coverage_to_app": fake_cov,
    }), patch.object(actions, "fetch_one", db.fetch_one), \
         patch.object(actions, "execute", db.execute), \
         patch("asyncio.sleep", _fast_sleep):
        step = actions.make_autobuild_step(TENANT, VIDEO, target="pictures")
        asyncio.run(step())

    failures = [c for c in status_calls if c["status"] == "failed"]
    assert not failures, f"the loop must not silently fail — got {failures}"
    assert gate_calls == [], "nothing to review -> no gate shown"
    assert db.video["characters_approved_at"] is not None
    assert db.video["environments_approved_at"] is not None
    assert len(coverage_calls) == 1, "must still proceed into coverage, not stall forever"
    print("✅ test_nothing_to_gate_skips_straight_through")


if __name__ == "__main__":
    test_pauses_after_script_before_designing_cast()
    test_finish_target_never_hits_the_script_gate()
    test_designs_cast_and_locations_then_pauses_before_coverage()
    test_resuming_does_not_redo_the_cast_or_locations()
    test_both_approved_proceeds_into_coverage_unchanged()
    test_static_docu_is_never_gated()
    test_nothing_to_gate_skips_straight_through()
    print("All tests passed!")
