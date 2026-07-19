"""Tests for C28 (checklist P2.4c — Settings "Agent access" UI + "via agent"
attribution chip, tasks/storyengine-copilot-ux-map.md §7).

C26/C27 shipped the agent-tokens mint/list/revoke routes and the full
MCP-dispatched verb surface, attributing every agent-driven paid dispatch as
`generation_claims.claimed_by = "agent:<name>:<verb...>"` (routes/mcp.py's
`caller=f"agent:{name}"` threaded into `_run_pending_action` ->
`generation_claims.acquire`). That attribution was previously invisible to
the frontend: the task-status poller (`GET /api/pipeline/task/{video_id}`,
what GuidedNextStep's running banner watches via the C19a shared task
watcher) never surfaced it.

This pins the two pieces C28 adds:

  1. `generation_claims.get_claimed_by()` — a new read-only lookup (fail-SOFT,
     unlike acquire()/is_blocked() which fail closed for money safety; a
     UI-only lookup has no such requirement): returns the most recent
     non-stale claim's claimed_by for a video, None if no claim or on any DB
     error, and ignores rows older than the existing 2h staleness window.

  2. `routes.pipeline._agent_name_from_claimed_by()` — the pure parser that
     turns "agent:<name>:<verb...>" into "<name>" and anything else (the
     "chat:..." default, None) into None (the fail-safe the chip relies on
     — an absent/None `via_agent` means no chip is rendered).

  3. `GET /api/pipeline/task/{video_id}` (`routes.pipeline.get_task_status`):
     carries the additive `via_agent` field — populated only while the task
     is actually "running" (a finished task's claim is already released),
     None for a chat-held or absent claim, and tenant-scoped (a claim
     belonging to a different tenant never leaks across via get_claimed_by's
     own tenant_id filter — proven at the generation_claims layer directly,
     matching the pattern test_cross_tenant_task_isolation.py already pins
     for the rest of this task-status machinery).

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c28_agent_attribution.py -q
"""
import os
import sys
import time
from unittest.mock import AsyncMock, patch

_BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.abspath(_BACKEND))

import types

for stub_mod in ("database", "auth"):
    if stub_mod not in sys.modules:
        m = types.ModuleType(stub_mod)
        if stub_mod == "database":
            async def _noop(*a, **kw):
                return None
            m.fetch_one = _noop
            m.fetch_all = _noop
            m.execute = _noop
            m.get_pool = _noop
        if stub_mod == "auth":
            async def _get_tenant_id(*a, **kw):
                return "stub"
            m.get_tenant_id = _get_tenant_id
        sys.modules[stub_mod] = m

if "pipeline_executor" not in sys.modules:
    pe = types.ModuleType("pipeline_executor")

    class _Stub:
        def __init__(self, *a, **kw):
            pass

    pe.PipelineExecutor = _Stub
    sys.modules["pipeline_executor"] = pe

import generation_claims  # noqa: E402
from routes import pipeline as pipeline_mod  # noqa: E402

TENANT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TENANT_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
VIDEO_ID = "video-c28"


def _reset():
    pipeline_mod._running_tasks.clear()


# =============================================================================
# Part 1 — routes.pipeline._agent_name_from_claimed_by: pure parser
# =============================================================================

def test_agent_name_parsed_from_single_verb_claim():
    assert pipeline_mod._agent_name_from_claimed_by("agent:claude-fable:draft_pass") == "claude-fable"
    print("✅ test_agent_name_parsed_from_single_verb_claim")


def test_agent_name_parsed_from_build_target_claim():
    # actions.py formats build claims as f"{caller}:build:{target}" —
    # "agent:<name>:build:<target>" splits (maxsplit=2) into
    # ["agent", "<name>", "build:<target>"] — parts[1] is still just the name.
    assert pipeline_mod._agent_name_from_claimed_by("agent:my-bot:build:script") == "my-bot"
    print("✅ test_agent_name_parsed_from_build_target_claim")


def test_chat_claim_is_not_attributed_to_an_agent():
    assert pipeline_mod._agent_name_from_claimed_by("chat:draft_pass") is None
    assert pipeline_mod._agent_name_from_claimed_by("chat:build:finish") is None
    assert pipeline_mod._agent_name_from_claimed_by("chat:approve") is None
    print("✅ test_chat_claim_is_not_attributed_to_an_agent")


def test_none_and_empty_claimed_by_is_not_attributed():
    assert pipeline_mod._agent_name_from_claimed_by(None) is None
    assert pipeline_mod._agent_name_from_claimed_by("") is None
    print("✅ test_none_and_empty_claimed_by_is_not_attributed")


def test_agent_prefix_with_no_name_segment_is_not_attributed():
    # Defensive: an "agent:" claimed_by with nothing after it (shouldn't
    # happen — routes/mcp.py always resolves a real token name — but the
    # parser must not explode or fabricate a name).
    assert pipeline_mod._agent_name_from_claimed_by("agent:") is None
    print("✅ test_agent_prefix_with_no_name_segment_is_not_attributed")


# =============================================================================
# Part 2 — generation_claims.get_claimed_by: fail-soft read-only lookup
# =============================================================================

class _FakeConn:
    def __init__(self, store: dict, should_fail: bool = False):
        self.store = store  # (tenant_id, video_id) -> (claimed_by, claimed_at epoch)
        self.should_fail = should_fail

    async def fetchrow(self, query, *args):
        if self.should_fail:
            raise RuntimeError("simulated DB outage")
        tenant_id, video_id = args
        entry = self.store.get((tenant_id, video_id))
        if entry is None:
            return None
        claimed_by, claimed_at = entry
        if time.time() - claimed_at > generation_claims.STALE_HOURS * 3600:
            return None
        return {"claimed_by": claimed_by}


class _FakePoolCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *a):
        return False


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _FakePoolCtx(self._conn)


def _patch_pool(store: dict, should_fail: bool = False):
    fake_pool = _FakePool(_FakeConn(store, should_fail))

    async def _fake_get_pool():
        return fake_pool

    return patch.object(generation_claims.database, "get_pool", _fake_get_pool)


async def test_get_claimed_by_returns_the_live_claim():
    store = {("t1", "v1"): ("agent:my-bot:draft_pass", time.time())}
    with _patch_pool(store):
        result = await generation_claims.get_claimed_by("t1", "v1")
    assert result == "agent:my-bot:draft_pass"
    print("✅ test_get_claimed_by_returns_the_live_claim")


async def test_get_claimed_by_none_when_no_claim():
    with _patch_pool({}):
        result = await generation_claims.get_claimed_by("t1", "v1")
    assert result is None
    print("✅ test_get_claimed_by_none_when_no_claim")


async def test_get_claimed_by_ignores_stale_rows():
    store = {("t1", "v1"): ("agent:my-bot:draft_pass", time.time() - (3 * 3600))}  # 3h old
    with _patch_pool(store):
        result = await generation_claims.get_claimed_by("t1", "v1")
    assert result is None, "a stale (>2h) claim must not be surfaced as attribution"
    print("✅ test_get_claimed_by_ignores_stale_rows")


async def test_get_claimed_by_fails_soft_on_db_error():
    with _patch_pool({}, should_fail=True):
        result = await generation_claims.get_claimed_by("t1", "v1")  # must not raise
    assert result is None, "get_claimed_by must fail SOFT (return None), never raise — UI-only lookup"
    print("✅ test_get_claimed_by_fails_soft_on_db_error")


async def test_get_claimed_by_is_tenant_scoped():
    """A claim held under tenant A must never surface for tenant B's lookup
    — mirrors the tenant-isolation contract test_cross_tenant_task_isolation.py
    already pins for the rest of this task-status machinery."""
    store = {(TENANT_A, VIDEO_ID): ("agent:someone-elses-bot:draft_pass", time.time())}
    with _patch_pool(store):
        a_result = await generation_claims.get_claimed_by(TENANT_A, VIDEO_ID)
        b_result = await generation_claims.get_claimed_by(TENANT_B, VIDEO_ID)
    assert a_result == "agent:someone-elses-bot:draft_pass"
    assert b_result is None, "tenant B must not see tenant A's claim attribution"
    print("✅ test_get_claimed_by_is_tenant_scoped")


# =============================================================================
# Part 3 — GET /api/pipeline/task/{video_id}: the additive via_agent field
# =============================================================================

async def test_task_status_carries_via_agent_when_claim_is_agent_held():
    _reset()
    pipeline_mod._set_task_status(VIDEO_ID, "running", "Drafting scenes...", tenant_id=TENANT_A)
    with patch.object(pipeline_mod, "generation_claims", types.SimpleNamespace(
            get_claimed_by=AsyncMock(return_value="agent:claude-fable:draft_pass"))):
        result = await pipeline_mod.get_task_status(VIDEO_ID, tenant_id=TENANT_A)
    assert result["status"] == "running"
    assert result["via_agent"] == "claude-fable"
    print("✅ test_task_status_carries_via_agent_when_claim_is_agent_held")


async def test_task_status_via_agent_absent_when_claim_is_chat_held():
    _reset()
    pipeline_mod._set_task_status(VIDEO_ID, "running", "Drafting scenes...", tenant_id=TENANT_A)
    with patch.object(pipeline_mod, "generation_claims", types.SimpleNamespace(
            get_claimed_by=AsyncMock(return_value="chat:draft_pass"))):
        result = await pipeline_mod.get_task_status(VIDEO_ID, tenant_id=TENANT_A)
    assert result["via_agent"] is None, "a chat-held claim must not render an agent chip"
    print("✅ test_task_status_via_agent_absent_when_claim_is_chat_held")


async def test_task_status_via_agent_absent_when_no_claim_at_all():
    _reset()
    pipeline_mod._set_task_status(VIDEO_ID, "running", "Drafting scenes...", tenant_id=TENANT_A)
    with patch.object(pipeline_mod, "generation_claims", types.SimpleNamespace(
            get_claimed_by=AsyncMock(return_value=None))):
        result = await pipeline_mod.get_task_status(VIDEO_ID, tenant_id=TENANT_A)
    assert result["via_agent"] is None
    print("✅ test_task_status_via_agent_absent_when_no_claim_at_all")


async def test_task_status_never_looks_up_claim_when_not_running():
    """Only worth a DB round-trip while something is actually running — a
    finished/idle task's claim is already released and would resolve to None
    anyway, so a completed/failed task must not pay for the lookup."""
    _reset()
    pipeline_mod._set_task_status(VIDEO_ID, "completed", "Done.", tenant_id=TENANT_A)
    get_claimed_by_mock = AsyncMock(return_value="agent:should-not-be-called:draft_pass")
    with patch.object(pipeline_mod, "generation_claims", types.SimpleNamespace(
            get_claimed_by=get_claimed_by_mock)):
        result = await pipeline_mod.get_task_status(VIDEO_ID, tenant_id=TENANT_A)
    get_claimed_by_mock.assert_not_called()
    assert result["via_agent"] is None
    print("✅ test_task_status_never_looks_up_claim_when_not_running")


async def test_task_status_idle_response_still_has_no_via_agent_key_crash():
    """The idle (no task at all) branch returns early with a 3-key dict —
    pin that it still round-trips cleanly (no via_agent KeyError anywhere
    downstream) even though this branch predates C28 and deliberately keeps
    its original shape (idle has nothing to attribute)."""
    _reset()
    result = await pipeline_mod.get_task_status(VIDEO_ID, tenant_id=TENANT_A)
    assert result == {"status": "idle", "message": None, "error": None}
    print("✅ test_task_status_idle_response_still_has_no_via_agent_key_crash")


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
