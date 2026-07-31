"""G5: machine_research_cards keyed by roster_index, not machine_key.

Before migration 149_machine_research_cards_roster_index_identity.sql, the
table's PRIMARY KEY was (tenant_id, video_id, machine_key), and
_upsert_machine_research_card's ON CONFLICT target matched. machine_key is
_normalized_unit_code(_unit_display_name(machine)) - a lossy derivation two
DISTINCT locked roster entries can share. Confirmed prod collision on video
d2e37cd6-521a-43aa-a14d-ce096a783c1e: roster item 9
({"name": "Audacious class / Malta class", "designation": "CVA-01
predecessors"}) and roster item 13 ({"name": "CVA-01 class", "designation":
"CVA-01 Queen Elizabeth class (1960s design)"}) both display-name/normalize
to machine_key CVA01 (_unit_display_name glues designation+name together;
_unit_code's designation-pattern match then finds "CVA-01" in BOTH glued
strings even though the two roster entries are otherwise unrelated). So the
second colliding write silently clobbered the first row. The migration
moves the PK to (tenant_id, video_id, roster_index) - the locked roster's
own 1:1 slot number - and _upsert_machine_research_card's ON CONFLICT
target moves with it.

These tests use a real in-memory ON-CONFLICT simulation (same convention as
tests/test_c65_feature_board.py's FakeDB) instead of just asserting on SQL
text, so they are a genuine regression lock: if anyone reverts the ON
CONFLICT target, these tests actually lose a row and fail, not just fail a
string match.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_g5_machine_research_cards_roster_index.py -q
"""
import asyncio
import json

import pipeline_executor as pe

# The exact roster item 9 / roster item 13 display names from the confirmed
# prod collision on video d2e37cd6-521a-43aa-a14d-ce096a783c1e (verified
# live via `se db` against research_payload->unit_roster on 2026-07-30 and
# re-derived through the real _unit_display_name/_normalized_unit_code
# pipeline - not hand-picked strings).
_COLLIDING_A = "CVA-01 predecessors Audacious class / Malta class"
_COLLIDING_B = "CVA-01 Queen Elizabeth class (1960s design) CVA-01 class"


def test_colliding_pair_shares_a_machine_key():
    """Fixture sanity check: if _normalized_unit_code ever stops colliding
    these two, every other test in this file is testing nothing."""
    assert pe._normalized_unit_code(_COLLIDING_A) == pe._normalized_unit_code(_COLLIDING_B)


class _RosterIndexKeyedTable:
    """In-memory simulation of machine_research_cards with the REAL (post
    migration 149) PRIMARY KEY (tenant_id, video_id, roster_index) ON
    CONFLICT semantics - executes the exact SQL string
    _upsert_machine_research_card issues, so a regression to the old
    conflict target is caught by the SQL shape, not just by row count."""

    def __init__(self):
        self.rows: dict[tuple, dict] = {}
        self.videos: set[tuple] = {("tenant-a", "video-a")}

    async def execute(self, query: str, *args):
        if "INSERT INTO machine_research_cards" in query:
            assert "ON CONFLICT (tenant_id, video_id, roster_index) DO UPDATE" in query
            assert "ON CONFLICT (tenant_id, video_id, machine_key)" not in query
            tenant_id, video_id, machine_key, machine_name, roster_index, card_json, validation_json = args
            if (tenant_id, video_id) not in self.videos:
                return "INSERT 0 0"
            key = (tenant_id, video_id, roster_index)
            self.rows[key] = {
                "machine_key": machine_key,
                "machine_name": machine_name,
                "roster_index": roster_index,
                "card": json.loads(card_json),
                "validation": json.loads(validation_json),
            }
            return "INSERT 0 1"
        if "UPDATE machine_research_cards" in query:
            assert "roster_index = $3" in query
            assert "machine_key = $3" not in query
            tenant_id, video_id, roster_index, validation_json = args
            key = (tenant_id, video_id, roster_index)
            if key in self.rows:
                self.rows[key]["validation"] = json.loads(validation_json)
                return "UPDATE 1"
            return "UPDATE 0"
        raise AssertionError(f"unhandled query: {query}")


def test_colliding_pair_upsert_keeps_both_rows_keyed_by_roster_index(monkeypatch):
    table = _RosterIndexKeyedTable()
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-a"

    async def fake_execute(query, *args):
        return await table.execute(query, *args)

    monkeypatch.setattr(pe, "execute", fake_execute)

    asyncio.run(executor._upsert_machine_research_card(
        "video-a", _COLLIDING_A, 2,
        {"unit": _COLLIDING_A, "engineering_thesis": "A's thesis."}, {"passed": True},
    ))
    asyncio.run(executor._upsert_machine_research_card(
        "video-a", _COLLIDING_B, 3,
        {"unit": _COLLIDING_B, "engineering_thesis": "B's thesis."}, {"passed": True},
    ))

    # The old bug: this would be 1 (second write clobbers the first).
    assert len(table.rows) == 2
    slot_a = table.rows[("tenant-a", "video-a", 2)]
    slot_b = table.rows[("tenant-a", "video-a", 3)]
    assert slot_a["machine_name"] == _COLLIDING_A
    assert slot_a["card"]["engineering_thesis"] == "A's thesis."
    assert slot_b["machine_name"] == _COLLIDING_B
    assert slot_b["card"]["engineering_thesis"] == "B's thesis."
    # They legitimately share a machine_key - that's the whole point: the
    # row identity no longer depends on it being unique.
    assert slot_a["machine_key"] == slot_b["machine_key"]


def test_reupserting_the_same_roster_slot_updates_in_place_not_a_new_row(monkeypatch):
    """ON CONFLICT ... DO UPDATE still works: re-saving the SAME roster slot
    (e.g. a repair pass) overwrites that slot's row rather than adding a
    second one."""
    table = _RosterIndexKeyedTable()
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-a"

    async def fake_execute(query, *args):
        return await table.execute(query, *args)

    monkeypatch.setattr(pe, "execute", fake_execute)

    asyncio.run(executor._upsert_machine_research_card(
        "video-a", _COLLIDING_B, 3, {"unit": _COLLIDING_B, "engineering_thesis": "first pass."}, {"passed": False},
    ))
    asyncio.run(executor._upsert_machine_research_card(
        "video-a", _COLLIDING_B, 3, {"unit": _COLLIDING_B, "engineering_thesis": "repaired pass."}, {"passed": True},
    ))

    assert len(table.rows) == 1
    row = table.rows[("tenant-a", "video-a", 3)]
    assert row["card"]["engineering_thesis"] == "repaired pass."
    assert row["validation"]["passed"] is True


def test_update_validation_scoped_to_roster_index_never_touches_the_other_colliding_row(monkeypatch):
    """_update_machine_research_validation (the no-spend readiness self-heal
    write) must refresh ONLY the roster slot it was called for. A
    machine_key-scoped WHERE would have updated BOTH colliding rows with one
    machine's verdict."""
    table = _RosterIndexKeyedTable()
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-a"

    async def fake_execute(query, *args):
        return await table.execute(query, *args)

    monkeypatch.setattr(pe, "execute", fake_execute)

    asyncio.run(executor._upsert_machine_research_card(
        "video-a", _COLLIDING_A, 2, {"unit": _COLLIDING_A}, {"passed": True, "warnings": []},
    ))
    asyncio.run(executor._upsert_machine_research_card(
        "video-a", _COLLIDING_B, 3, {"unit": _COLLIDING_B}, {"passed": True, "warnings": []},
    ))

    asyncio.run(executor._update_machine_research_validation(
        "video-a", _COLLIDING_B, 3, {"machine": _COLLIDING_B, "passed": False, "warnings": ["fresh failure"]},
    ))

    slot_a = table.rows[("tenant-a", "video-a", 2)]
    slot_b = table.rows[("tenant-a", "video-a", 3)]
    assert slot_a["validation"] == {"passed": True, "warnings": []}  # untouched
    assert slot_b["validation"] == {"machine": _COLLIDING_B, "passed": False, "warnings": ["fresh failure"]}
