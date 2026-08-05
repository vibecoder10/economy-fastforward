"""D15-3 (closes D15-1's "one road" gap): backend/routes/pipeline.py's two
draw routes — POST /storyboard-images/{video_id} and POST
/coverage-images/{video_id} — used to call scripts.coverage_to_app's
generate_storyboard_sheet_for_scene / generate_coverage_for_video DIRECTLY,
bypassing PipelineExecutor.run_storyboard_sheet / run_coverage_images (the
same wrappers chat's verbs, the MCP tools, and ClaudeOrchestrator's dispatch
already go through) — so a button-initiated draw never picked up the
cross-cutting checks those wrappers enforce (the flag-gated Frame Arbiter
judging pass on run_storyboard_sheet; the voicefix money gate + static_docu
redirect on run_coverage_images).

Before this chunk, `run_storyboard_sheet(self, video_id, scene=None)` and
`run_coverage_images(self, video_id, scene=None)` had NO `beat`, `plan_only`,
or `progress` parameters at all — while the storyboard-images route's `beat`
(redraw ONE board slot) and `plan_only` (plan-without-drawing) query params
are live buttons (ScenesWorkspaceTab.tsx:847/861/875), not dead params, and
both routes' `progress_callback` feeds the live per-scene status text the
frontend's task poller shows mid-run. Routing the button straight through the
OLD wrapper signature would have silently broken plan_only (would draw and
spend money), beat (would redraw the whole sheet instead of one slot), and
progress (task poller would go silent for the whole run). This chunk adds
`beat=None, plan_only=False, progress=None` to both wrapper signatures
(pipeline_executor.py, matching the underlying scripts.coverage_to_app
functions' own defaults exactly) and forwards them straight through — see
that file's own D15-3 docstring additions on both methods.

This file proves, with NO live DB and NO paid calls (every DB/network/paid
boundary monkeypatched or mocked):

  (1) Existing-caller parity — actions.py/claude_orchestrator.py only ever
      pass (video_id, scene): calling the wrappers that same way is
      byte-identical to before this chunk (the underlying function receives
      the exact (None, False, None) defaults; the returned dict is
      unchanged).
  (2) Progress forwarding — the `progress` callable passed to either wrapper
      reaches the underlying generate_* function and gets invoked with
      per-scene status text, proving both routes' task-poller updates
      survive the swap from a direct call to the executor.
  (3) COST-REGRESSION GUARD (non-negotiable per the chunk brief) — a REAL
      call through PipelineExecutor.run_storyboard_sheet into the REAL
      generate_storyboard_sheet_for_scene (only the DB layer and the actual
      paid image call, generate_scene_image_for_model, are mocked):
        - plan_only=True NEVER invokes generate_scene_image_for_model
          (zero draw calls — the plan-only dry run stays zero-spend through
          the new route).
        - beat=2 (a per-board redo on a 2-board scene) invokes
          generate_scene_image_for_model EXACTLY ONCE — the single slot
          asked for, not the whole sheet. The real board-chunking math
          (_plan_sheet_prompts / sheet_chunk_sizes, owned by the D15-2
          worker's coverage_to_app.py territory) is monkeypatched to a fixed
          2-board shape so this proof doesn't depend on — and can't be
          broken by — that internal algorithm changing under this test.
  (4) Arbiter guard — with the D5/A6 flag ON and scoped to the exact
      (video, scene) under test: plan_only=True and beat=2 do NOT trigger
      frame_arbiter_hook.run_after_storyboard_sheet (no pixels landed for
      plan_only; a beat-scoped redraw would re-judge every board in the
      scene and could trigger the repair ladder's own reroll of a slot the
      user didn't touch — see pipeline_executor.py's own comment on the
      guard). The plain (beat=None, plan_only=False) call shape — the ONLY
      shape any caller used before this chunk — still reaches the hook,
      proving the guard is additive, not a narrowing of D5/A6's existing
      behavior (already covered by test_d5_a6_arbiter_hook.py; re-asserted
      here against the NEW signature for belt-and-suspenders).

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_d15_3_wrapper_param_forwarding.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import pipeline_executor as pe_mod  # noqa: E402
from pipeline_executor import PipelineExecutor  # noqa: E402
import frame_arbiter_hook as hook  # noqa: E402
from scripts.coverage_to_app import _scene_text_hash  # noqa: E402

TENANT = "tenant-d15-3"
VIDEO = "video-d15-3"
SCENE = 1

SCENE_TEXT = "The city lights flicker as rain falls onto empty streets."
DIRECTIVE = (
    "[MOMENT 1 | rain falls on empty streets]\n"
    "- MASTER [WS]: Wide shot of rain-soaked streets, neon reflections shimmering.\n"
    "- ANGLE [MCU]: Close on droplets streaking down a window pane.\n"
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _video_row(**extra) -> dict:
    row = {
        "id": VIDEO, "tenant_id": TENANT, "video_title": "D15-3 Video",
        "aspect": "16:9", "image_style_override": None, "visual_style": None,
        "image_model_override": None, "render_style": None,
        "video_model": "grok-imagine", "dialogue_audio": "voice_over",
        "render_mode": None, "skip_voice": True, "status": "ready_for_images",
    }
    row.update(extra)
    return row


def _set_arbiter_scope(monkeypatch, *, enabled=True, video=VIDEO, scene=SCENE):
    if enabled:
        monkeypatch.setenv("FRAME_ARBITER_A6_ENABLED", "true")
    else:
        monkeypatch.delenv("FRAME_ARBITER_A6_ENABLED", raising=False)
    monkeypatch.setenv("FRAME_ARBITER_A6_VIDEO_ID", video)
    monkeypatch.setenv("FRAME_ARBITER_A6_SCENE", str(scene))
    monkeypatch.delenv("FRAME_ARBITER_A6_REDRAW_ENABLED", raising=False)


# =============================================================================
# (1) Existing-caller parity — actions.py/claude_orchestrator.py's call shape.
# =============================================================================

def test_run_storyboard_sheet_scene_only_call_forwards_new_defaults_unchanged(monkeypatch):
    """actions.py ACTIONS["storyboards"] and claude_orchestrator.py call this
    as executor.run_storyboard_sheet(video_id, scene=N) — no beat, no
    plan_only, no progress. Must reach generate_storyboard_sheet_for_scene
    with EXACTLY the (beat=None, plan_only=False, progress=None) defaults it
    always got, and return that function's dict unmodified (arbiter flag is
    off in this test, so no additive key)."""
    monkeypatch.delenv("FRAME_ARBITER_A6_ENABLED", raising=False)

    async def _fake_fetch_one(query, *args):
        return _video_row()

    monkeypatch.setattr(pe_mod, "fetch_one", _fake_fetch_one)

    underlying = AsyncMock(return_value={"status": "completed", "message": "Storyboard ready"})
    with patch("scripts.coverage_to_app.generate_storyboard_sheet_for_scene", underlying):
        result = _run(PipelineExecutor(TENANT).run_storyboard_sheet(VIDEO, scene=SCENE))

    underlying.assert_awaited_once_with(
        VIDEO, TENANT, scene=SCENE, beat=None, plan_only=False, progress=None)
    assert result == {"status": "completed", "message": "Storyboard ready"}


def test_run_coverage_images_scene_only_call_forwards_new_default_unchanged(monkeypatch):
    """Same proof for run_coverage_images: actions.py ACTIONS["images"] /
    claude_orchestrator.py call it as executor.run_coverage_images(video_id,
    scene=N) — no progress. Must reach generate_coverage_for_video with
    progress=None (the same as before this param existed) and return its
    dict unmodified. skip_voice=True keeps this test scoped to parameter
    forwarding, not the voicefix gate (that gate has its own dedicated test
    file, test_voicefix_image_money_gate.py)."""
    async def _fake_fetch_one(query, *args):
        return _video_row(skip_voice=True)

    monkeypatch.setattr(pe_mod, "fetch_one", _fake_fetch_one)

    underlying = AsyncMock(return_value={"status": "completed", "message": "Pictures ready"})
    with patch("scripts.coverage_to_app.generate_coverage_for_video", underlying):
        result = _run(PipelineExecutor(TENANT).run_coverage_images(VIDEO, scene=SCENE))

    underlying.assert_awaited_once_with(VIDEO, TENANT, scene=SCENE, progress=None)
    assert result == {"status": "completed", "message": "Pictures ready"}


def test_run_coverage_images_voicefix_gate_error_is_user_facing_marked(monkeypatch):
    """D15-3 finding, fixed in the same file: routes/pipeline.py's
    POST /coverage-images/{video_id} (the "Generate pictures" button) never
    went through this gate before this chunk, so its error dict never flowed
    through routes/pipeline.py's _set_task_status — which runs every failed
    status's error through error_utils.humanize_error at the write boundary,
    flattening any UNMARKED string to the generic "Something went wrong"
    fallback. Without error_utils.user_facing() wrapping this message, the
    button would correctly block the spend but tell the user nothing about
    why (found via test_d15_3_route_dispatch.py's route-level test, before
    this fix landed). Proves the fix directly on the real code path: the
    returned error string carries the marker prefix (so it survives
    _set_task_status's funnel verbatim) with the actionable text intact."""
    from error_utils import USER_FACING_PREFIX

    async def _fake_fetch_one(query, *args):
        return _video_row(skip_voice=False)

    async def _fake_fetch_all(query, *args):
        if "FROM scripts" in query:
            return [{"voice_over_url": None, "dialogue_segments": None, "scene": SCENE}]
        return []

    monkeypatch.setattr(pe_mod, "fetch_one", _fake_fetch_one)
    monkeypatch.setattr(pe_mod, "fetch_all", _fake_fetch_all)

    boom = AsyncMock(side_effect=AssertionError(
        "generate_coverage_for_video must never be called when the voice gate blocks"))
    with patch("scripts.coverage_to_app.generate_coverage_for_video", boom):
        result = _run(PipelineExecutor(TENANT).run_coverage_images(VIDEO, scene=SCENE))

    boom.assert_not_awaited()
    assert result["status"] == "failed"
    assert result["error"].startswith(USER_FACING_PREFIX)
    assert "Missing voice for scene 1" in result["error"]


# =============================================================================
# (2) Progress forwarding — the callable reaches the underlying function and
# fires with per-scene text, proving both routes' task-poller updates survive
# the swap from a direct call to the executor wrapper.
# =============================================================================

def test_run_storyboard_sheet_forwards_progress_callable_with_per_scene_text(monkeypatch):
    monkeypatch.delenv("FRAME_ARBITER_A6_ENABLED", raising=False)

    async def _fake_fetch_one(query, *args):
        return _video_row()

    monkeypatch.setattr(pe_mod, "fetch_one", _fake_fetch_one)

    async def _fake_generate(video_id, tenant_id, scene=None, beat=None, plan_only=False, progress=None):
        if progress:
            progress(f"Scene {scene}: planning the shots…")
            progress(f"Scene {scene}: board 1 is up")
        return {"status": "completed", "message": "ok"}

    seen: list = []
    with patch("scripts.coverage_to_app.generate_storyboard_sheet_for_scene", _fake_generate):
        _run(PipelineExecutor(TENANT).run_storyboard_sheet(VIDEO, scene=SCENE, progress=seen.append))

    assert seen == [f"Scene {SCENE}: planning the shots…", f"Scene {SCENE}: board 1 is up"]


def test_run_coverage_images_forwards_progress_callable_with_per_scene_text(monkeypatch):
    async def _fake_fetch_one(query, *args):
        return _video_row(skip_voice=True)

    monkeypatch.setattr(pe_mod, "fetch_one", _fake_fetch_one)

    async def _fake_generate(video_id, tenant_id, scene=None, progress=None,
                              only_scenes=None, section_contract=None):
        if progress:
            progress(f"Scene {scene}: drawing the storyboarded plan (GPT Image 2)…")
        return {"status": "completed", "message": "ok"}

    seen: list = []
    with patch("scripts.coverage_to_app.generate_coverage_for_video", _fake_generate):
        _run(PipelineExecutor(TENANT).run_coverage_images(VIDEO, scene=SCENE, progress=seen.append))

    assert seen == [f"Scene {SCENE}: drawing the storyboarded plan (GPT Image 2)…"]


# =============================================================================
# (3) COST-REGRESSION GUARD — real generate_storyboard_sheet_for_scene, only
# the DB layer and the actual paid draw call are mocked.
# =============================================================================

class SpyDB:
    """Same convention as test_d3_59_plan_only_dry_run.py's SpyDB — records
    execute() calls, serves canned fetch_one/fetch_all rows. No real DB."""

    def __init__(self, *, coverage_directive: str = None, coverage_directive_hash: str = None):
        self.execute_calls: list = []
        self._directive = coverage_directive
        self._hash = coverage_directive_hash

    async def fetch_one(self, query, *args):
        if "FROM videos WHERE id=$1" in query:
            return _video_row()
        if "coverage_directive, coverage_directive_hash FROM scripts" in query:
            return {"id": "script-1", "coverage_directive": self._directive,
                    "coverage_directive_hash": self._hash}
        raise AssertionError(f"unexpected fetch_one query: {query}")

    async def fetch_all(self, query, *args):
        # S6-A added a "location" column to this SELECT's column list
        # (scripts.location, migration 144) — match the shared WHERE
        # clause tail so this fixture is robust to the exact column list.
        if "FROM scripts WHERE video_id=$1 AND tenant_id=$2 AND scene IS NOT NULL " \
           "AND scene_text IS NOT NULL ORDER BY scene" in query:
            return [{"scene": SCENE, "scene_text": SCENE_TEXT, "location": None}]
        if "FROM video_characters" in query:
            return []
        raise AssertionError(f"unexpected fetch_all query: {query}")

    async def execute(self, query, *args):
        self.execute_calls.append((query, args))
        return "OK"


def _coverage_to_app_patches(spy: SpyDB, *, image_client_mock, extra_board_count: int = None):
    patches = [
        patch("scripts.coverage_to_app.fetch_one", spy.fetch_one),
        patch("scripts.coverage_to_app.fetch_all", spy.fetch_all),
        patch("scripts.coverage_to_app.execute", spy.execute),
        patch("scripts.coverage_to_app.get_secret", AsyncMock(return_value="fake-kie-key")),
        patch("scripts.coverage_to_app.get_text_client_for_tenant", AsyncMock(return_value=object())),
        patch("scripts.coverage_to_app.claude_model_for_direct_client", lambda c: "fake-model"),
        patch("scripts.coverage_to_app.scene_aware_bible", AsyncMock(return_value=None)),
        patch("scripts.coverage_to_app._approved_envs", AsyncMock(return_value=[])),
        patch("scripts.coverage_to_app.generate_coverage_directive", AsyncMock(return_value=DIRECTIVE)),
        patch("scripts.coverage_to_app.generate_scene_image_for_model", image_client_mock),
        patch("scripts.coverage_to_app._stable_url", AsyncMock(return_value="https://stable/final.png")),
        patch("scripts.coverage_to_app.record_ledger_entry", AsyncMock(return_value=None)),
    ]
    if extra_board_count is not None:
        # Decouple this cost-regression proof from coverage_to_app's real
        # moment->board chunking math (_plan_sheet_prompts / sheet_chunk_sizes,
        # D15-2 territory that can legitimately change shape under this test):
        # force a fixed N-board shape so "beat=2 draws exactly one of N boards"
        # is proven against a KNOWN board count, not a guessed one.
        fake_prompts = [f"board {i} prompt" for i in range(1, extra_board_count + 1)]
        fake_sizes = [1] * extra_board_count
        patches.append(patch("scripts.coverage_to_app._plan_sheet_prompts", lambda *a, **k: list(fake_prompts)))
        patches.append(patch("scripts.coverage_to_app.sheet_chunk_sizes", lambda *a, **k: list(fake_sizes)))
    return patches


def test_plan_only_true_through_the_executor_never_invokes_the_paid_image_client(monkeypatch):
    monkeypatch.delenv("FRAME_ARBITER_A6_ENABLED", raising=False)
    spy = SpyDB()
    image_client = AsyncMock(
        side_effect=AssertionError("plan_only=True must NEVER reach the paid draw call"))
    patches = _coverage_to_app_patches(spy, image_client_mock=image_client)

    async def _fake_get_video(*_a, **_k):
        return _video_row()

    monkeypatch.setattr(PipelineExecutor, "_get_video", _fake_get_video)

    for p in patches:
        p.start()
    try:
        result = _run(PipelineExecutor(TENANT).run_storyboard_sheet(VIDEO, scene=SCENE, plan_only=True))
    finally:
        for p in patches:
            p.stop()

    assert result["status"] == "completed", result
    assert "nothing drawn" in result["message"]
    image_client.assert_not_awaited()


def test_beat_redraw_through_the_executor_draws_exactly_one_of_two_boards(monkeypatch):
    monkeypatch.delenv("FRAME_ARBITER_A6_ENABLED", raising=False)
    # A saved plan already exists (coverage_directive + matching hash) — the
    # precondition generate_storyboard_sheet_for_scene requires for a
    # beat-scoped redo (it refuses to re-plan on a beat call).
    spy = SpyDB(coverage_directive=DIRECTIVE, coverage_directive_hash=_scene_text_hash(SCENE_TEXT))
    image_client = AsyncMock(return_value=("https://fake-storage.example/board.png", "gpt-image-2"))
    patches = _coverage_to_app_patches(spy, image_client_mock=image_client, extra_board_count=2)

    async def _fake_get_video(*_a, **_k):
        return _video_row()

    monkeypatch.setattr(PipelineExecutor, "_get_video", _fake_get_video)

    for p in patches:
        p.start()
    try:
        result = _run(PipelineExecutor(TENANT).run_storyboard_sheet(VIDEO, scene=SCENE, beat=2))
    finally:
        for p in patches:
            p.stop()

    assert result["status"] == "completed", result
    image_client.assert_awaited_once()
    # The ONE call drew board 2's prompt, not board 1's.
    _ic, _model, prompt_arg = image_client.await_args.args[:3]
    assert prompt_arg.startswith("board 2 prompt"), prompt_arg


# =============================================================================
# (4) Arbiter guard — plan_only/beat never reach the hook; the plain call
# shape still does (belt-and-suspenders re-assertion against the new
# signature, alongside test_d5_a6_arbiter_hook.py's own coverage).
# =============================================================================

def test_arbiter_hook_never_fires_for_a_plan_only_call_even_when_flag_is_scoped_in(monkeypatch):
    """Tracks CALLS to the hook directly (not just the absence of a
    "frame_arbiter" key) — run_after_storyboard_sheet is called inside a
    try/except that swallows any exception it raises (advisory contract,
    pipeline_executor.py), so a boom-on-call assertion would be silently
    masked by that swallow and this test would pass even with the D15-3
    guard neutered. An AsyncMock call-count assertion isn't fooled by that."""
    _set_arbiter_scope(monkeypatch, enabled=True, video=VIDEO, scene=SCENE)

    async def _fake_fetch_one(query, *args):
        return _video_row()

    monkeypatch.setattr(pe_mod, "fetch_one", _fake_fetch_one)

    hook_call = AsyncMock(return_value={"scene": SCENE, "sheets": []})
    monkeypatch.setattr(hook, "run_after_storyboard_sheet", hook_call)

    underlying = AsyncMock(return_value={"status": "completed", "message": "plan ready, nothing drawn yet"})
    with patch("scripts.coverage_to_app.generate_storyboard_sheet_for_scene", underlying):
        result = _run(PipelineExecutor(TENANT).run_storyboard_sheet(VIDEO, scene=SCENE, plan_only=True))

    hook_call.assert_not_awaited()
    assert "frame_arbiter" not in result


def test_arbiter_hook_never_fires_for_a_beat_scoped_redraw_even_when_flag_is_scoped_in(monkeypatch):
    """Same call-tracking approach as the plan_only test above, and for the
    same reason (the hook's own exception swallow would mask a boom-based
    assertion)."""
    _set_arbiter_scope(monkeypatch, enabled=True, video=VIDEO, scene=SCENE)

    async def _fake_fetch_one(query, *args):
        return _video_row()

    monkeypatch.setattr(pe_mod, "fetch_one", _fake_fetch_one)

    hook_call = AsyncMock(return_value={"scene": SCENE, "sheets": []})
    monkeypatch.setattr(hook, "run_after_storyboard_sheet", hook_call)

    underlying = AsyncMock(return_value={"status": "completed", "message": "board 2 is up"})
    with patch("scripts.coverage_to_app.generate_storyboard_sheet_for_scene", underlying):
        result = _run(PipelineExecutor(TENANT).run_storyboard_sheet(VIDEO, scene=SCENE, beat=2))

    hook_call.assert_not_awaited()
    assert "frame_arbiter" not in result


def test_arbiter_hook_still_fires_for_the_plain_full_scene_call_when_flag_is_scoped_in(monkeypatch):
    """The ONE call shape every caller used before this chunk (beat=None,
    plan_only=False) must be UNCHANGED by adding the new params — the guard
    is additive, not a narrowing of D5/A6's existing behavior."""
    _set_arbiter_scope(monkeypatch, enabled=True, video=VIDEO, scene=SCENE)

    async def _fake_fetch_one(query, *args):
        return _video_row()

    monkeypatch.setattr(pe_mod, "fetch_one", _fake_fetch_one)

    hook_call = AsyncMock(return_value={"scene": SCENE, "sheets": []})
    monkeypatch.setattr(hook, "run_after_storyboard_sheet", hook_call)

    underlying = AsyncMock(return_value={"status": "completed", "message": "sheet ready"})
    with patch("scripts.coverage_to_app.generate_storyboard_sheet_for_scene", underlying):
        result = _run(PipelineExecutor(TENANT).run_storyboard_sheet(VIDEO, scene=SCENE))

    hook_call.assert_awaited_once_with(TENANT, VIDEO, SCENE)
    assert result["frame_arbiter"] == {"scene": SCENE, "sheets": []}


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
