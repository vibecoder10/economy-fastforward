"""Tests for C16d (checklist §S7-8 LOW fix, docs/reports/2026-07-17-
storyengine-agent-audit-findings.md §S7): task_store.db_persist_task's
"pending" branch was a plain check-then-insert (SELECT ... WHERE job_id=$1
AND status='pending', then INSERT if not found) with no DB-level constraint
behind it — two concurrent calls for the SAME arq job_id can both pass the
SELECT before either INSERTs land (the classic TOCTOU race), producing two
background_tasks rows for one job.

Migration 094 adds a partial UNIQUE index on background_tasks(job_id) WHERE
job_id IS NOT NULL (applied live against wrromlupsmyzrrcqlucn; live
duplicate-scan beforehand found zero collisions in 468 existing rows, none of
which carry a job_id at all). db_persist_task's INSERT now carries
`ON CONFLICT (job_id) WHERE job_id IS NOT NULL DO NOTHING` to match — the
race's loser becomes a silent no-op instead of a duplicate row or a raised
UniqueViolation, preserving the function's pre-existing fail-soft contract
(this function has never raised out to a caller).

The fake `execute` below enforces the same uniqueness Postgres now does
(mirrors tests/functional/test_generation_ledger.py's C16c fake-DB pattern):
a second INSERT for a job_id already present only becomes a no-op when the
query text itself carries "ON CONFLICT" — so this suite would fail against
the pre-fix source (a plain INSERT with no such clause) by landing a real
duplicate row, proving the test is a genuine regression guard.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c16d_task_store_job_id_conflict.py -q
"""
import asyncio
import os
import sys
import types

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

BACKGROUND_TASKS_ROWS: list[dict] = []


async def _fake_fetch_one(query: str, *args):
    if "WHERE job_id = $1 AND status = 'pending'" in query:
        (job_id,) = args
        # Snapshot the SELECT's result FIRST, then yield — this is what
        # actually reproduces the TOCTOU race: both `asyncio.gather`'d
        # callers must read "no existing row" BEFORE either reaches the
        # INSERT below. Yielding (via sleep(0)) only AFTER computing the
        # result (rather than before) is what lets caller B's read land
        # while caller A is still mid-flight, instead of A running its SELECT
        # + INSERT to completion in one uninterrupted turn (which would let
        # A's own row silently satisfy B's later SELECT — hiding the race
        # this test exists to reproduce, independent of whether the fix
        # under test does anything at all).
        if job_id is None:
            # Real Postgres: `job_id = NULL` is never true (SQL NULL
            # semantics) — a NULL job_id can never match this SELECT,
            # unlike Python's `None == None`. Getting this wrong here would
            # make the fake report a false "already pending" hit that real
            # Postgres never would.
            result = None
        else:
            result = next(
                ({"id": r["id"]} for r in BACKGROUND_TASKS_ROWS
                 if r["job_id"] == job_id and r["status"] == "pending"),
                None,
            )
        await asyncio.sleep(0)  # yield to the scheduler so the race can interleave
        return result
    if "WHERE video_id = $1 AND status = 'running'" in query:
        return None
    return None


async def _fake_execute(query: str, *args):
    if "INSERT INTO background_tasks" in query:
        tenant_id, video_id, task_type, status, message, job_id, attempt = args
        is_dup = job_id is not None and any(r["job_id"] == job_id for r in BACKGROUND_TASKS_ROWS)
        # Mirrors migration 094 + tests/functional/test_generation_ledger.py's
        # identical C16c convention exactly: only a query that actually
        # carries the ON CONFLICT clause gets deduped here. Pre-fix (the
        # state at HEAD before this chunk), NEITHER the unique index NOR
        # this ON CONFLICT clause existed — a duplicate INSERT simply
        # SUCCEEDED, landing a second row (the real S7-8 bug). That's why
        # the "no ON CONFLICT" branch below falls through to appending
        # unconditionally, not raising — raising would model a DB that
        # already had the constraint without the code catching up, which
        # is a state this repo was never actually in.
        if "ON CONFLICT" in query and "job_id" in query.split("ON CONFLICT")[1].split("DO")[0]:
            if is_dup:
                return "INSERT 0 0"  # ON CONFLICT ... DO NOTHING fired
        BACKGROUND_TASKS_ROWS.append({
            "id": f"row-{len(BACKGROUND_TASKS_ROWS)}", "tenant_id": tenant_id,
            "video_id": video_id, "task_type": task_type, "status": status,
            "message": message, "job_id": job_id, "attempt": attempt,
        })
        return "INSERT 0 1"
    return "OK"


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


_stub("database", fetch_one=_fake_fetch_one, execute=_fake_execute)

import task_store  # noqa: E402


def _reset():
    BACKGROUND_TASKS_ROWS.clear()


def test_concurrent_pending_persists_for_same_job_id_lands_one_row():
    """Simulates the TOCTOU race directly: both calls see no existing
    pending row (as they would if they raced the SELECT before either
    INSERTed), then both attempt the INSERT with the SAME job_id. Only one
    row must land, and neither call may raise."""
    _reset()
    job_id = "thumbnail:vid1:1"

    async def _persist():
        await task_store.db_persist_task(
            "tenant-1", "vid1", "thumbnail", "pending",
            message="thumbnail queued", job_id=job_id, attempt=1,
        )

    async def _race():
        # Both tasks reach the INSERT with no prior row visible — the exact
        # TOCTOU window db_persist_task's own SELECT-then-INSERT can't close
        # on its own; the DB-level constraint is the actual backstop.
        await asyncio.gather(_persist(), _persist())

    asyncio.run(_race())

    matching = [r for r in BACKGROUND_TASKS_ROWS if r["job_id"] == job_id]
    assert len(matching) == 1, (
        f"expected exactly one row for job_id={job_id!r}, got {len(matching)} — "
        "the ON CONFLICT DO NOTHING backstop didn't catch the race")


def test_sequential_calls_second_one_is_silent_no_op_via_pending_check():
    """The common (non-racing) path: db_persist_task's own SELECT check
    already catches a second call once the first row is visible — proves
    the fast-path early-return is untouched by the ON CONFLICT addition."""
    _reset()
    job_id = "voice:vid2:1"
    asyncio.run(task_store.db_persist_task(
        "tenant-1", "vid2", "voice", "pending", job_id=job_id, attempt=1))
    asyncio.run(task_store.db_persist_task(
        "tenant-1", "vid2", "voice", "pending", job_id=job_id, attempt=1))

    matching = [r for r in BACKGROUND_TASKS_ROWS if r["job_id"] == job_id]
    assert len(matching) == 1


def test_null_job_id_rows_are_never_deduped():
    """The in-process BackgroundTasks fallback path never sets job_id (0 of
    468 live rows do, per the C16d migration's pre-apply scan) — two such
    rows for the SAME video/stage must both persist; NULL is never a
    conflict, by design (mirrors migration 093's identical NULL-kie_task_id
    reasoning for generation_ledger)."""
    _reset()
    asyncio.run(task_store.db_persist_task(
        "tenant-1", "vid3", "render", "pending", job_id=None, attempt=1))
    asyncio.run(task_store.db_persist_task(
        "tenant-1", "vid3", "render", "pending", job_id=None, attempt=1))

    assert len(BACKGROUND_TASKS_ROWS) == 2


def test_db_persist_task_never_raises_on_a_hard_db_error(monkeypatch):
    """Pre-existing fail-soft contract, unchanged by this fix: any exception
    from execute() is swallowed, never propagated to the caller."""
    _reset()

    async def _boom(*a, **kw):
        raise RuntimeError("simulated DB outage")

    monkeypatch.setattr(task_store, "execute", _boom)
    asyncio.run(task_store.db_persist_task(
        "tenant-1", "vid4", "script", "pending", job_id="script:vid4:1", attempt=1))
    # No exception raised — that's the whole assertion.


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
