"""Functional test for SEC-SSE-001: prove _running_tasks is keyed by
(tenant_id, video_id), not video_id alone.

Before the fix, two tenants who ever coincidentally chose (or were assigned)
the same video_id would see each other's task state via:

  - /api/pipeline/task/{video_id} returning the wrong tenant's status
  - /api/pipeline/stream emitting another tenant's task_progress events
  - collision overwrites: tenant-A starting a task would clobber tenant-B's
    in-progress state for the same video_id

The fix keys the dict by the (tenant_id, video_id) tuple. This test pins the
contract so a future refactor can't silently collapse back to the old shape.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Stub out heavy imports the same way test_error_humanization.py does, so this
# file can run standalone without database or pipeline executor modules.
import sys as _sys
import types

for stub_mod in ("database", "auth"):
    if stub_mod not in _sys.modules:
        m = types.ModuleType(stub_mod)
        if stub_mod == "database":
            async def _noop(*a, **kw):
                return None
            m.fetch_one = _noop
            m.fetch_all = _noop
            m.execute = _noop
        if stub_mod == "auth":
            async def _get_tenant_id(*a, **kw):
                return "stub"
            m.get_tenant_id = _get_tenant_id
        _sys.modules[stub_mod] = m

if "pipeline_executor" not in _sys.modules:
    pe = types.ModuleType("pipeline_executor")

    class _Stub:
        def __init__(self, *a, **kw): pass

    pe.PipelineExecutor = _Stub
    _sys.modules["pipeline_executor"] = pe

# status_map is a pure module (stdlib only) — import the real one. Stubbing it
# left an incomplete fake in sys.modules that broke pipeline.py's imports here
# and poisoned other tests that import the real status_map symbols.


from routes import pipeline as pipeline_mod
from routes import agents as agents_mod


TENANT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TENANT_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
SHARED_VIDEO_ID = "shared-vid-001"


def _reset():
    pipeline_mod._running_tasks.clear()
    agents_mod._running_tasks.clear()


# ───────────────────────── pipeline.py ─────────────────────────

def test_pipeline_same_video_id_different_tenants_isolated():
    """Two tenants with the same video_id must get DIFFERENT task state."""
    _reset()
    pipeline_mod._set_task_status(SHARED_VIDEO_ID, "running", "tenant A's work", tenant_id=TENANT_A)
    pipeline_mod._set_task_status(SHARED_VIDEO_ID, "running", "tenant B's work", tenant_id=TENANT_B)

    a_state = pipeline_mod._get_task_status(SHARED_VIDEO_ID, TENANT_A)
    b_state = pipeline_mod._get_task_status(SHARED_VIDEO_ID, TENANT_B)

    assert a_state is not None, "tenant A state missing"
    assert b_state is not None, "tenant B state missing"
    assert a_state["message"] == "tenant A's work"
    assert b_state["message"] == "tenant B's work"
    # Critical: each tenant sees their own state, not the other's.
    assert a_state["message"] != b_state["message"]
    print("✅ test_pipeline_same_video_id_different_tenants_isolated")


def test_pipeline_tenant_b_cannot_read_tenant_a_task():
    """If only tenant A has a running task, tenant B must see no task."""
    _reset()
    pipeline_mod._set_task_status(SHARED_VIDEO_ID, "running", "A only", tenant_id=TENANT_A)

    a_state = pipeline_mod._get_task_status(SHARED_VIDEO_ID, TENANT_A)
    b_state = pipeline_mod._get_task_status(SHARED_VIDEO_ID, TENANT_B)

    assert a_state is not None
    assert b_state is None, f"tenant B saw tenant A's task state: {b_state!r}"
    print("✅ test_pipeline_tenant_b_cannot_read_tenant_a_task")


def test_pipeline_tenant_b_clear_does_not_affect_tenant_a():
    """A _clear_task_status call from tenant B must not wipe tenant A's state."""
    _reset()
    pipeline_mod._set_task_status(SHARED_VIDEO_ID, "running", "A state", tenant_id=TENANT_A)
    pipeline_mod._clear_task_status(SHARED_VIDEO_ID, TENANT_B)

    a_state = pipeline_mod._get_task_status(SHARED_VIDEO_ID, TENANT_A)
    assert a_state is not None, "tenant B's clear_task_status wiped tenant A"
    assert a_state["message"] == "A state"
    print("✅ test_pipeline_tenant_b_clear_does_not_affect_tenant_a")


def test_pipeline_tenant_b_set_does_not_overwrite_tenant_a():
    """Tenant B setting the 'same' video_id must not clobber tenant A's state."""
    _reset()
    pipeline_mod._set_task_status(SHARED_VIDEO_ID, "running", "A started first", tenant_id=TENANT_A)
    pipeline_mod._set_task_status(SHARED_VIDEO_ID, "failed", "B failed", tenant_id=TENANT_B)

    a_state = pipeline_mod._get_task_status(SHARED_VIDEO_ID, TENANT_A)
    b_state = pipeline_mod._get_task_status(SHARED_VIDEO_ID, TENANT_B)

    assert a_state["status"] == "running", f"tenant A state corrupted by B: {a_state!r}"
    assert a_state["message"] == "A started first"
    assert b_state["status"] == "failed"
    print("✅ test_pipeline_tenant_b_set_does_not_overwrite_tenant_a")


def test_pipeline_dict_keys_are_tuples_not_strings():
    """Contract check: a future refactor that drops tenant from the key
    would make this test fail immediately."""
    _reset()
    pipeline_mod._set_task_status(SHARED_VIDEO_ID, "running", "x", tenant_id=TENANT_A)

    keys = list(pipeline_mod._running_tasks.keys())
    assert len(keys) == 1
    key = keys[0]
    assert isinstance(key, tuple), f"_running_tasks key is not a tuple: {type(key)}"
    assert key == (TENANT_A, SHARED_VIDEO_ID), f"unexpected key shape: {key!r}"
    print("✅ test_pipeline_dict_keys_are_tuples_not_strings")


# ───────────────────────── agents.py ─────────────────────────

def test_agents_same_video_id_different_tenants_isolated():
    """Same SEC-SSE-001 shape in routes/agents.py — cover it too."""
    _reset()
    agents_mod._set_task(SHARED_VIDEO_ID, "running", "agent tenant A", tenant_id=TENANT_A)
    agents_mod._set_task(SHARED_VIDEO_ID, "completed", "agent tenant B", tenant_id=TENANT_B)

    a = agents_mod._get_task(SHARED_VIDEO_ID, TENANT_A)
    b = agents_mod._get_task(SHARED_VIDEO_ID, TENANT_B)

    assert a["message"] == "agent tenant A"
    assert b["message"] == "agent tenant B"
    assert a["status"] == "running"
    assert b["status"] == "completed"
    print("✅ test_agents_same_video_id_different_tenants_isolated")


def test_agents_tenant_b_cannot_see_tenant_a_task():
    _reset()
    agents_mod._set_task(SHARED_VIDEO_ID, "running", "A only", tenant_id=TENANT_A)

    a = agents_mod._get_task(SHARED_VIDEO_ID, TENANT_A)
    b = agents_mod._get_task(SHARED_VIDEO_ID, TENANT_B)

    assert a is not None
    assert b is None
    print("✅ test_agents_tenant_b_cannot_see_tenant_a_task")


# ───────────────────────── runner ─────────────────────────

TESTS = [
    test_pipeline_same_video_id_different_tenants_isolated,
    test_pipeline_tenant_b_cannot_read_tenant_a_task,
    test_pipeline_tenant_b_clear_does_not_affect_tenant_a,
    test_pipeline_tenant_b_set_does_not_overwrite_tenant_a,
    test_pipeline_dict_keys_are_tuples_not_strings,
    test_agents_same_video_id_different_tenants_isolated,
    test_agents_tenant_b_cannot_see_tenant_a_task,
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
    _reset()
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
