"""Lock: a blocked/out-of-credit Kie key fails fast + actionable, and a dead
worker's zombie task gets reaped.

Kie is the single upstream for text+image+video+voice, so a banned or
credit-exhausted key is the most likely way a paying customer's pipeline dies
in week one. Before this work it failed opaquely ("images still pending") and
burned the whole retry budget. And a worker that died mid-stage left a 'running'
row that blocked a 1-job-plan tenant until the API restarted.

Invariants pinned:
  1. is_kie_block() detects the opaque signals; humanize_error() maps them to an
     actionable "fix your Kie key" message.
  2. The image client raises the KIE_ACCOUNT_BLOCKED marker (not a silent None)
     and the images bot aborts the run on it.
  3. The worker treats a Kie block as TERMINAL — no arq retry.
  4. The periodic reaper exists with a threshold beyond the longest job timeout
     and is wired into the app lifespan.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import error_utils


def _backend() -> Path:
    return Path(__file__).resolve().parents[2]


def _repo_root() -> Path:
    # .../economy-fastforward/storyengine/backend/tests/functional/<this>
    return Path(__file__).resolve().parents[4]


def test_is_kie_block_detects_signals():
    blocked = [
        "用户已被封禁",
        "KIE_ACCOUNT_BLOCKED: 用户已被封禁",
        "Insufficient credit balance",
        "insufficient balance",
        "account banned",
        "余额不足",
    ]
    for s in blocked:
        assert error_utils.is_kie_block(s), f"is_kie_block missed: {s!r}"
    for ok in ["timed out", "connection refused", "500 server error", "", None]:
        assert not error_utils.is_kie_block(ok), f"is_kie_block false-positive: {ok!r}"
    print("✅ test_is_kie_block_detects_signals")


def test_humanize_maps_kie_block_to_actionable_copy():
    msg = error_utils.humanize_error("KIE_ACCOUNT_BLOCKED: 用户已被封禁")
    assert "Kie" in msg and "Settings" in msg, f"not actionable: {msg!r}"
    # Must be checked BEFORE the generic auth branch (a ban can read like a 401).
    msg2 = error_utils.humanize_error("Insufficient credits 401 unauthorized")
    assert "Kie" in msg2 and "Settings" in msg2, f"ban lost to auth branch: {msg2!r}"
    print("✅ test_humanize_maps_kie_block_to_actionable_copy")


def test_image_client_raises_marker_and_bot_aborts():
    ic = (_repo_root() / "skills/video-pipeline/shared/clients/image_client.py").read_text()
    assert "KIE_BLOCK_MARKER" in ic and "_is_kie_block" in ic, "image_client lost the block detector"
    assert re.search(r"raise\s+RuntimeError\(f?\"\{KIE_BLOCK_MARKER\}", ic), (
        "poll_for_completion must RAISE the marker on a block (not return None)"
    )
    run = (_repo_root() / "skills/video-pipeline/images/run.py").read_text()
    assert 'KIE_ACCOUNT_BLOCKED" in str(e)' in run and "raise" in run, (
        "images bot must re-raise a Kie block to abort the run (not swallow per-item)"
    )
    print("✅ test_image_client_raises_marker_and_bot_aborts")


def test_worker_treats_kie_block_as_terminal_no_retry():
    src = (_backend() / "worker.py").read_text()
    assert "_terminal_failure" in src, "worker lost _terminal_failure"
    assert "is_kie_block" in src, "_terminal_failure must key off is_kie_block"
    # Both failure paths must short-circuit (return) on terminal BEFORE the raise
    # that triggers arq's retry.
    assert src.count("_terminal_failure(error_msg)") >= 2, (
        "both the failed-status and except branches must check _terminal_failure"
    )
    # The terminal branches return; the non-terminal ones raise.
    assert "return result" in src and "raise RuntimeError(error_msg)" in src, (
        "terminal failure must return (no retry); non-terminal must still raise"
    )
    print("✅ test_worker_treats_kie_block_as_terminal_no_retry")


def test_reaper_threshold_safe_and_wired():
    pipe = (_backend() / "routes" / "pipeline.py").read_text()
    m = re.search(r"STALE_TASK_THRESHOLD_MIN\s*=\s*(\d+)", pipe)
    assert m, "STALE_TASK_THRESHOLD_MIN not defined"
    threshold = int(m.group(1))
    # Longest arq job timeout is 7200s = 120min; threshold must exceed it so the
    # reaper never kills a legitimately long-running render.
    assert threshold > 120, (
        f"reaper threshold {threshold}min must exceed the 120min max job timeout"
    )
    assert "async def reap_stale_running_tasks" in pipe, "reaper function missing"
    assert "status IN ('running', 'pending')" in pipe, "reaper must target running+pending"

    main = (_backend() / "main.py").read_text()
    assert "reap_stale_running_tasks" in main, "reaper not imported in main"
    assert "asyncio.create_task(_auto_reap_stale_tasks())" in main, "reaper task not started"
    assert "reaper_task.cancel()" in main, "reaper task not cancelled on shutdown"
    print("✅ test_reaper_threshold_safe_and_wired")


TESTS = [
    test_is_kie_block_detects_signals,
    test_humanize_maps_kie_block_to_actionable_copy,
    test_image_client_raises_marker_and_bot_aborts,
    test_worker_treats_kie_block_as_terminal_no_retry,
    test_reaper_threshold_safe_and_wired,
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
