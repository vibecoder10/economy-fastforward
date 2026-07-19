"""Functional test for Cycle 58: plan-limit enforcement regression lock.

The bug shape being prevented: `check_plan_limits(tenant_id, action)`
is the ONLY thing that stops a free-plan tenant from creating
unlimited videos (or unlimited render minutes). If a refactor drops
the `await check_plan_limits(...)` call from any of the 3 video-create
entry points or the render entry point — either by accident or by a
"temporarily disable during debugging" commit that gets merged — free
users get unlimited pipeline spend and the whole paid-tier structure
collapses.

The current enforcement shape (across 5 entry points):

  # videos create / pipeline create / discovery launch / autopilot launch
  await check_plan_limits(tenant_id, "video")
  ...do the thing...
  await increment_usage(tenant_id, "videos_created")

  # render
  await check_plan_limits(tenant_id, "render")

Losing the check = revenue leak. Losing `increment_usage` = limit
never triggers (counter stays at 0 forever). Either one breaks the
paid tier.

This test pins:
  - `check_plan_limits` still defined in billing.py and still raises
    HTTPException 402 on over-limit paths.
  - Every known create-entry route still calls `check_plan_limits`
    with action="video" BEFORE any DB insert.
  - The render entry still calls with action="render".
  - `increment_usage` still exists and is called after successful
    creates (videos.py + pipeline.py).

C53 (checklist P4.2-d) added `routes/autopilot.py::launch_candidate` to the
guarded-entry-points list below: it was the ONE video-create route this lock
never covered, and it's the path C51's unattended auto_draft dial level and
C52's `accept_proposal` both funnel through — an unguarded launch_candidate
meant autopilot could create unlimited videos for a free-plan tenant with no
human in the loop to notice. See
tests/test_c53_launch_candidate_gates.py for the behavioral (non-AST) proof
that the gate actually fires and blocks the launch.
"""
import ast
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _billing_py() -> Path:
    return _backend_root() / "routes" / "billing.py"


def _videos_py() -> Path:
    return _backend_root() / "routes" / "videos.py"


def _pipeline_py() -> Path:
    return _backend_root() / "routes" / "pipeline.py"


def _discovery_py() -> Path:
    return _backend_root() / "routes" / "discovery.py"


def _autopilot_py() -> Path:
    return _backend_root() / "routes" / "autopilot.py"


def _pipeline_executor_py() -> Path:
    return _backend_root() / "pipeline_executor.py"


def _mcp_py() -> Path:
    return _backend_root() / "routes" / "mcp.py"


def test_check_plan_limits_defined_and_raises_402():
    """The function must still exist, still raise 402 (Payment Required)
    when over limit for both action types. 402 is the frontend's cue to
    show the upgrade modal — a 4xx drift (e.g. 403, 429) means the UI
    no longer offers upgrade, and the plan page is unreachable from the
    error state."""
    text = _billing_py().read_text()
    tree = ast.parse(text)
    fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "check_plan_limits":
            fn = node
            break
    assert fn is not None, (
        "Cycle 58 regression — `check_plan_limits` no longer defined in "
        "routes/billing.py. Every paid-plan gate in the codebase "
        "collapses; free users get unlimited pipeline spend."
    )
    src = ast.unparse(fn)
    # Must raise HTTPException with status_code=402 at least twice
    # (once for video, once for render)
    status_402_count = len(re.findall(r"status_code\s*=\s*402", src))
    assert status_402_count >= 2, (
        f"Cycle 58 regression — `check_plan_limits` raises 402 only "
        f"{status_402_count} times (expected >=2: video + render paths). "
        "Frontend upgrade modal won't fire on the missing path."
    )
    # Both action branches must still be present
    assert '"video"' in src or "'video'" in src, (
        "Cycle 58 regression — `check_plan_limits` no longer branches on "
        "action=='video'. Video creation path is unguarded."
    )
    assert '"render"' in src or "'render'" in src, (
        "Cycle 58 regression — `check_plan_limits` no longer branches on "
        "action=='render'. Render path is unguarded — free users burn "
        "compute with no ceiling."
    )
    print("✅ test_check_plan_limits_defined_and_raises_402")


def test_all_video_create_entrypoints_guarded():
    """Four entry points create videos: `POST /videos`, `POST /pipeline`
    (create_idea), `POST /discovery/{id}/launch`, and
    `POST /autopilot/launch/{id}` (launch_candidate — added C53; this is
    also the path C51's auto_draft loop and C52's accept_proposal call, so
    it runs unattended, not just from a human click). Each MUST call
    `check_plan_limits(tenant_id, "video")` before any INSERT. Missing
    the call on even one path = free users (or an unattended autopilot
    loop) route around the limit."""
    entry_points = [
        (_videos_py(), "create_video"),
        (_pipeline_py(), "create_idea"),
        (_discovery_py(), "launch_idea"),
        (_autopilot_py(), "launch_candidate"),
    ]
    failures: list[str] = []
    for path, fn_name in entry_points:
        text = path.read_text()
        tree = ast.parse(text)
        found = None
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == fn_name:
                found = node
                break
        if found is None:
            # Function renamed — we can't verify. Flag it so the test
            # author updates this list.
            failures.append(
                f"  - {path.name}: function `{fn_name}` not found — if "
                "renamed, update this test with the new name."
            )
            continue
        src = ast.unparse(found)
        if not re.search(
            r"check_plan_limits\s*\([^)]*,\s*['\"]video['\"]",
            src,
        ):
            failures.append(
                f"  - {path.name}::{fn_name} no longer calls "
                "`check_plan_limits(..., 'video')`. Free-tier cap lost "
                "on this entry point."
            )
    assert not failures, (
        "Cycle 58 regression — video-create entry points no longer "
        "enforce plan limits:\n" + "\n".join(failures)
    )
    print("✅ test_all_video_create_entrypoints_guarded")


def test_render_entrypoint_guarded():
    """The render entry point is the ONE spot where render-minute cap
    is enforced. Dropping it = free users burn through unlimited Remotion
    compute."""
    text = _pipeline_py().read_text()
    tree = ast.parse(text)
    fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_render":
            fn = node
            break
    assert fn is not None, (
        "Cycle 58 regression — `run_render` no longer defined in "
        "routes/pipeline.py. If renamed, update this test and verify "
        "the new handler still calls check_plan_limits(..., 'render')."
    )
    src = ast.unparse(fn)
    assert re.search(
        r"check_plan_limits\s*\([^)]*,\s*['\"]render['\"]",
        src,
    ), (
        "Cycle 58 regression — `run_render` no longer calls "
        "`check_plan_limits(..., 'render')`. Render-minute cap lost; "
        "free plan becomes unlimited compute."
    )
    print("✅ test_render_entrypoint_guarded")


def test_plan_check_precedes_mutation():
    """The check must come BEFORE any DB INSERT / row creation. If a
    refactor moves the check after the insert, the limit is enforced
    only after the over-limit row is already persisted — effectively
    "one free extra video per overage attempt.\""""
    entry_points = [
        (_videos_py(), "create_video"),
        (_pipeline_py(), "create_idea"),
    ]
    failures: list[str] = []
    for path, fn_name in entry_points:
        text = path.read_text()
        tree = ast.parse(text)
        fn = None
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == fn_name:
                fn = node
                break
        if fn is None:
            continue
        src = ast.unparse(fn)
        check_pos = src.find("check_plan_limits")
        # Find the first INSERT-ish pattern — either INSERT INTO or the
        # executor's create_idea() invocation (`.create_idea(` avoids
        # matching the outer function's own `async def create_idea(`
        # signature line).
        insert_pos = -1
        for pat in [r"INSERT\s+INTO\s+videos", r"\.create_idea\s*\("]:
            m = re.search(pat, src)
            if m and (insert_pos == -1 or m.start() < insert_pos):
                insert_pos = m.start()
        if insert_pos == -1:
            continue  # No mutation in body — nothing to order
        if check_pos == -1 or check_pos > insert_pos:
            failures.append(
                f"  - {path.name}::{fn_name} now performs a mutation "
                "before `check_plan_limits` runs. The limit must block "
                "BEFORE any row lands in videos."
            )
    assert not failures, (
        "Cycle 58 regression — plan check is no longer the first thing "
        "in the handler:\n" + "\n".join(failures)
    )
    print("✅ test_plan_check_precedes_mutation")


def test_increment_usage_called_after_create():
    """`increment_usage` is what advances the counter that
    check_plan_limits reads against. If it's not called after a
    successful create, the counter stays at 0 and the limit never fires
    — even over-plan users get unlimited videos."""
    entry_points = [
        (_videos_py(), "create_video"),
        (_pipeline_py(), "create_idea"),
    ]
    failures: list[str] = []
    for path, fn_name in entry_points:
        text = path.read_text()
        tree = ast.parse(text)
        fn = None
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == fn_name:
                fn = node
                break
        if fn is None:
            continue
        src = ast.unparse(fn)
        if not re.search(
            r"increment_usage\s*\([^)]*,\s*['\"]videos_created['\"]",
            src,
        ):
            failures.append(
                f"  - {path.name}::{fn_name} no longer calls "
                "`increment_usage(..., 'videos_created')`. Counter won't "
                "advance; plan limit becomes effectively infinite."
            )
    assert not failures, (
        "Cycle 58 regression — counter no longer advances on create:\n"
        + "\n".join(failures)
    )
    print("✅ test_increment_usage_called_after_create")


def test_pipeline_executor_run_render_guarded():
    """C57 audit finding: `test_render_entrypoint_guarded` above only pins
    the HTTP door (routes/pipeline.py::run_render). But chat's "render"/
    "build" verbs and MCP's SAME tools (both dispatch through
    actions.py -> actions.make_action_step/make_autobuild_step) call
    `PipelineExecutor.run_render` DIRECTLY — bypassing that route (and its
    check_plan_limits call) entirely. Before C57, chat/MCP/autopilot's
    full-auto continuation loop (which also reaches this method via
    `run_next_step`'s status-map dispatch) could render past the plan's
    render-minute cap with zero enforcement. C57 moved the gate into this
    ONE method every caller converges on. Losing it here again reopens the
    exact same bypass for chat AND MCP at once."""
    text = _pipeline_executor_py().read_text()
    tree = ast.parse(text)
    fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_render":
            fn = node
            break
    assert fn is not None, (
        "C57 regression — `PipelineExecutor.run_render` no longer defined "
        "in pipeline_executor.py. If renamed, update this test."
    )
    src = ast.unparse(fn)
    assert re.search(r"check_plan_limits\s*\([^)]*,\s*['\"]render['\"]", src), (
        "C57 regression — `PipelineExecutor.run_render` no longer calls "
        "`check_plan_limits(..., 'render')`. Chat's render/build verbs, "
        "MCP's SAME tools, and autopilot's full-auto continuation all call "
        "this method directly (not the HTTP route) — the render-minute cap "
        "is unenforced for all three the moment this check is dropped."
    )
    print("✅ test_pipeline_executor_run_render_guarded")


def test_mcp_create_video_dispatches_through_gated_route():
    """C57 plan-gate audit: MCP's `create_video` tool must keep calling the
    REAL `routes.videos.create_video` (which `test_all_video_create_
    entrypoints_guarded` above already pins to `check_plan_limits(...,
    'video')`) rather than a second, parallel INSERT that could silently
    drift out of that gate's coverage."""
    text = _mcp_py().read_text()
    tree = ast.parse(text)
    fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_call_create_video":
            fn = node
            break
    assert fn is not None, (
        "C57 regression — routes/mcp.py::_call_create_video not found. If "
        "renamed, update this test."
    )
    src = ast.unparse(fn)
    assert "create_video as _create_video_route" in src or "routes.videos" in src, (
        "C57 regression — MCP's create_video tool no longer imports "
        "routes.videos.create_video. If it now does its own INSERT, it may "
        "have silently lost the check_plan_limits('video') gate that route "
        "carries."
    )
    assert re.search(r"_create_video_route\s*\(", src), (
        "C57 regression — MCP's create_video tool no longer CALLS the real "
        "routes.videos.create_video — the plan-limit gate lives inside "
        "that function; a tool that stops calling it stops being gated."
    )
    print("✅ test_mcp_create_video_dispatches_through_gated_route")


def test_mcp_accept_autopilot_proposal_dispatches_through_gated_launch():
    """C57 plan-gate audit: MCP's `accept_autopilot_proposal` tool must keep
    calling `routes.autopilot.accept_proposal`, which itself calls
    `launch_candidate` — the function `test_all_video_create_entrypoints_
    guarded` above already pins to `check_plan_limits(..., 'video')` (C53).
    An MCP tool that stopped calling accept_proposal (e.g. reimplementing
    the launch inline) would silently exit that gate's coverage — this is
    the exact risk decisions.md's C57 entry flagged and asked this chunk to
    verify, not just assume."""
    text = _mcp_py().read_text()
    tree = ast.parse(text)
    fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_call_accept_autopilot_proposal":
            fn = node
            break
    assert fn is not None, (
        "C57 regression — routes/mcp.py::_call_accept_autopilot_proposal "
        "not found. If renamed, update this test."
    )
    src = ast.unparse(fn)
    assert "from routes.autopilot import accept_proposal" in src, (
        "C57 regression — MCP's accept_autopilot_proposal tool no longer "
        "imports routes.autopilot.accept_proposal — if it now launches some "
        "other way, verify it still funnels through launch_candidate's "
        "check_plan_limits('video') gate."
    )
    assert re.search(r"(?<!_)accept_proposal\s*\(", src), (
        "C57 regression — MCP's accept_autopilot_proposal tool no longer "
        "CALLS routes.autopilot.accept_proposal — the plan-limit gate lives "
        "downstream of that call (via launch_candidate); a tool that stops "
        "calling it stops being gated."
    )
    print("✅ test_mcp_accept_autopilot_proposal_dispatches_through_gated_launch")


TESTS = [
    test_check_plan_limits_defined_and_raises_402,
    test_all_video_create_entrypoints_guarded,
    test_render_entrypoint_guarded,
    test_plan_check_precedes_mutation,
    test_increment_usage_called_after_create,
    test_pipeline_executor_run_render_guarded,
    test_mcp_create_video_dispatches_through_gated_route,
    test_mcp_accept_autopilot_proposal_dispatches_through_gated_launch,
]


def main() -> int:
    failed = 0
    for t in TESTS:
        try:
            t()
        except AssertionError as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
