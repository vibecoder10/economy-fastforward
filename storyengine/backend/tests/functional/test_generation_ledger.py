"""Lock: generation_ledger.record_ledger_entry() writes one ledger row and
recomputes videos.total_cost from SUM(actual_cost) — never an incremental
add — and never raises even when the DB write fails (checklist §0.3/C07,
tasks/storyengine-wiring-fix-checklist.md).

No network, no real DB: `database` is stubbed with an in-memory fake that
mirrors exactly what the two SQL statements in record_ledger_entry() do —
INSERT a row into a list, UPDATE total_cost via a real SUM over that list
(not a running counter) — so a bug that swapped the recompute for an
increment would show up as a failing assertion here, not a passing one for
the wrong reason.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_generation_ledger.py -q
"""
import asyncio
import os
import sys
import types

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, _BACKEND)


# --- in-memory fake `database` module (generation_ledger.py imports
# `execute` from it eagerly at module load, so this must be stubbed first) --

LEDGER_ROWS: list[dict] = []
VIDEOS: dict[str, dict] = {}
RAISE_ON_INSERT = False


async def _fake_execute(query: str, *args):
    if "INSERT INTO generation_ledger" in query:
        if RAISE_ON_INSERT:
            raise RuntimeError("simulated DB outage on ledger insert")
        tenant_id, video_id, stage, model, units, unit_cost, actual_cost, kie_task_id = args
        LEDGER_ROWS.append({
            "tenant_id": tenant_id, "video_id": video_id, "stage": stage,
            "model": model, "units": units, "unit_cost": unit_cost,
            "actual_cost": actual_cost, "kie_task_id": kie_task_id,
        })
        return "INSERT 0 1"
    if "UPDATE videos SET total_cost" in query:
        (video_id,) = args
        # Mirrors the real SQL: total_cost = SUM(actual_cost) over EVERY
        # ledger row for this video — recomputed fresh, not incremented.
        total = sum(r["actual_cost"] for r in LEDGER_ROWS if r["video_id"] == video_id)
        VIDEOS.setdefault(video_id, {})["total_cost"] = total
        return "UPDATE 1"
    raise AssertionError(f"unexpected query in fake db: {query}")


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


_stub("database", execute=_fake_execute)

import generation_ledger  # noqa: E402


def _reset():
    global RAISE_ON_INSERT
    LEDGER_ROWS.clear()
    VIDEOS.clear()
    RAISE_ON_INSERT = False


# --- tests -----------------------------------------------------------------

def test_ledger_row_written_with_correct_fields():
    """(a) a generation_ledger row is written with the right
    stage/model/costs/kie_task_id."""
    _reset()
    asyncio.run(generation_ledger.record_ledger_entry(
        tenant_id="tenant-1", video_id="video-1", stage="clip",
        model="grok-imagine", units=1, unit_cost=0.10, actual_cost=0.10,
        kie_task_id="kie-task-abc",
    ))
    assert len(LEDGER_ROWS) == 1
    row = LEDGER_ROWS[0]
    assert row == {
        "tenant_id": "tenant-1", "video_id": "video-1", "stage": "clip",
        "model": "grok-imagine", "units": 1, "unit_cost": 0.10,
        "actual_cost": 0.10, "kie_task_id": "kie-task-abc",
    }
    print("✅ test_ledger_row_written_with_correct_fields")


def test_total_cost_equals_ledger_sum_after_one_write():
    """(b) videos.total_cost equals SUM(ledger.actual_cost)."""
    _reset()
    asyncio.run(generation_ledger.record_ledger_entry(
        tenant_id="tenant-1", video_id="video-1", stage="clip",
        model="grok-imagine", units=1, unit_cost=0.15, actual_cost=0.15,
        kie_task_id="kie-task-1",
    ))
    assert VIDEOS["video-1"]["total_cost"] == 0.15
    print("✅ test_total_cost_equals_ledger_sum_after_one_write")


def test_second_write_accumulates_via_recompute_not_increment():
    """(c) a second write for the same video accumulates correctly, AND the
    accumulation is provably a recompute (SUM over the ledger) rather than
    `total_cost += x`: seed a stale total_cost that did NOT come from the
    ledger (as every pre-C07 video's total_cost=0 default effectively was —
    never rolled up from real spend) and confirm the first ledger write
    REPLACES it with the ledger sum instead of adding to it."""
    _reset()
    VIDEOS["video-1"] = {"total_cost": 999.0}  # stale/legacy value, not from the ledger

    asyncio.run(generation_ledger.record_ledger_entry(
        tenant_id="tenant-1", video_id="video-1", stage="clip",
        model="grok-imagine", units=1, unit_cost=0.10, actual_cost=0.10,
        kie_task_id="kie-task-1",
    ))
    assert VIDEOS["video-1"]["total_cost"] == 0.10, (
        "recompute must REPLACE total_cost with SUM(ledger), not increment "
        f"a stale value — got {VIDEOS['video-1']['total_cost']}"
    )

    asyncio.run(generation_ledger.record_ledger_entry(
        tenant_id="tenant-1", video_id="video-1", stage="clip",
        model="seedance-2-fast", units=1, unit_cost=0.30, actual_cost=0.30,
        kie_task_id="kie-task-2",
    ))
    assert len(LEDGER_ROWS) == 2
    assert VIDEOS["video-1"]["total_cost"] == 0.40, (
        f"expected SUM(0.10, 0.30) == 0.40, got {VIDEOS['video-1']['total_cost']}"
    )
    print("✅ test_second_write_accumulates_via_recompute_not_increment")


def test_other_videos_are_not_touched_by_a_videos_write():
    """Rollup is scoped to the video_id in the row — a clip on video-2 must
    never change video-1's total_cost."""
    _reset()
    asyncio.run(generation_ledger.record_ledger_entry(
        tenant_id="tenant-1", video_id="video-1", stage="clip",
        model="grok-imagine", units=1, unit_cost=0.10, actual_cost=0.10,
    ))
    asyncio.run(generation_ledger.record_ledger_entry(
        tenant_id="tenant-1", video_id="video-2", stage="clip",
        model="grok-imagine", units=1, unit_cost=0.20, actual_cost=0.20,
    ))
    assert VIDEOS["video-1"]["total_cost"] == 0.10
    assert VIDEOS["video-2"]["total_cost"] == 0.20
    print("✅ test_other_videos_are_not_touched_by_a_videos_write")


def test_fail_soft_never_raises_and_never_partially_applies():
    """(d) a forced ledger-write exception does NOT propagate — the caller
    (a clip generation that already cost real money) must get control back
    normally. Also confirms the failed INSERT leaves no row and no rollup
    (nothing to roll back, since fail-soft catches before either statement's
    effect could half-apply against a real DB — here, simply that neither
    fake-db table changed)."""
    global RAISE_ON_INSERT
    _reset()
    RAISE_ON_INSERT = True

    result = asyncio.run(generation_ledger.record_ledger_entry(
        tenant_id="tenant-1", video_id="video-1", stage="clip",
        model="grok-imagine", units=1, unit_cost=0.10, actual_cost=0.10,
        kie_task_id="kie-task-1",
    ))  # must not raise

    assert result is None
    assert LEDGER_ROWS == []
    assert "video-1" not in VIDEOS
    print("✅ test_fail_soft_never_raises_and_never_partially_applies")


def test_kie_task_id_defaults_to_none_when_not_captured():
    """Some call sites (e.g. a talking-clip model whose createTask call
    never yields a taskId before falling back) legitimately have nothing to
    report — the column is nullable and the helper must accept that."""
    _reset()
    asyncio.run(generation_ledger.record_ledger_entry(
        tenant_id="tenant-1", video_id="video-1", stage="clip",
        model="grok-imagine", units=1, unit_cost=0.10, actual_cost=0.10,
    ))
    assert LEDGER_ROWS[0]["kie_task_id"] is None
    print("✅ test_kie_task_id_defaults_to_none_when_not_captured")


TESTS = [
    test_ledger_row_written_with_correct_fields,
    test_total_cost_equals_ledger_sum_after_one_write,
    test_second_write_accumulates_via_recompute_not_increment,
    test_other_videos_are_not_touched_by_a_videos_write,
    test_fail_soft_never_raises_and_never_partially_applies,
    test_kie_task_id_defaults_to_none_when_not_captured,
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
