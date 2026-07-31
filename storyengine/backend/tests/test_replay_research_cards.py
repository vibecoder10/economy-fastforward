"""G5: machine_research_cards roster-index recovery tool.

Offline coverage for scripts/replay_research_cards.py against a fake
asyncpg-shaped connection (fetchrow/fetch/execute) - no network, no real
database, no paid API calls. Proves the three things the G5 chunk requires:

1. A colliding-pair upsert (two roster entries sharing a machine_key) keeps
   both rows once ON CONFLICT targets roster_index instead of machine_key.
2. Replay recovers a dropped row from the still-intact JSONB
   research_payload.unit_research_cards, and is idempotent (a second replay
   over the now-repaired state finds nothing left to recover).
3. A reader that previously resolved a card by machine_key still resolves
   correctly for BOTH members of a colliding pair after the row exists.
"""
import asyncio
import json

import pipeline_executor as pe
from scripts import replay_research_cards as replay


def _card(machine: str, thesis: str = "A sufficiently long spoken thesis about this machine.") -> dict:
    return {
        "unit": machine,
        "engineering_thesis": thesis,
        "why_this_unit_deserves_a_paragraph": "",
        "surprising_fact": "",
        "source_notes": [],
        "evidence_segments": [],
    }


class FakeConn:
    """Duck-types the tiny slice of asyncpg.Connection replay_research_cards
    uses: fetchrow, fetch, execute, and an async-context-manager transaction()."""

    def __init__(self, video_row, compact_rows):
        self.video_row = video_row
        self.compact_rows = {row["roster_index"]: dict(row) for row in compact_rows}
        self.executed: list[tuple] = []

    async def fetchrow(self, query, *args):
        assert "FROM videos" in query
        return dict(self.video_row) if self.video_row else None

    async def fetch(self, query, *args):
        assert "FROM machine_research_cards" in query
        return [dict(row) for row in self.compact_rows.values()]

    async def execute(self, query, *args):
        assert "ON CONFLICT (tenant_id, video_id, roster_index)" in query
        (_tenant_id, _video_id, machine_key, machine_name, roster_index, card_json, validation_json) = args
        self.compact_rows[roster_index] = {
            "roster_index": roster_index,
            "machine_key": machine_key,
            "machine_name": machine_name,
            "card": json.loads(card_json),
            "validation": json.loads(validation_json),
        }
        self.executed.append((query, args))
        return "INSERT 0 1"

    def transaction(self):
        return _NoopTransaction()


class _NoopTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


# The exact roster item 9 / roster item 13 display names from the confirmed
# prod collision on video d2e37cd6-521a-43aa-a14d-ce096a783c1e (verified
# live via `se db`, re-derived through the real _unit_display_name /
# _normalized_unit_code pipeline - both collapse to machine_key CVA01).
_COLLIDING_A = "CVA-01 predecessors Audacious class / Malta class"
_COLLIDING_B = "CVA-01 Queen Elizabeth class (1960s design) CVA-01 class"


def _colliding_roster_video(tenant_id="tenant-a", video_id="video-a"):
    roster = ["Boeing XB-15", _COLLIDING_A, _COLLIDING_B]
    payload = {
        "documentary_style": "designed_vs_used",
        "unit_roster": roster,
        "unit_research_cards": [
            _card("Boeing XB-15"),
            _card(_COLLIDING_A),
            _card(_COLLIDING_B),
        ],
    }
    return {"id": video_id, "tenant_id": tenant_id, "research_payload": payload}, roster


def test_colliding_pair_normalizes_to_the_same_machine_key():
    """Sanity-check the fixture actually reproduces the real collision -
    if _normalized_unit_code ever changes shape, this test file should be
    the first thing to fail, not a confusing downstream assertion."""
    assert pe._normalized_unit_code(_COLLIDING_A) == pe._normalized_unit_code(_COLLIDING_B)


def test_replay_recovers_a_dropped_colliding_row(monkeypatch):
    """Simulates the pre-migration-153 damage directly: the compact table has
    only ONE row for the colliding pair (roster slot 2 present, slot 3 -
    silently clobbered by the old machine_key ON CONFLICT - missing), while
    research_payload.unit_research_cards still has both cards intact. Replay
    must recover exactly the missing slot and leave the correct one alone."""
    video_row, roster = _colliding_roster_video()
    # Slot 1 (XB-15) and slot 2 (_COLLIDING_A) are correctly stored under
    # their own roster_index. Slot 3 (_COLLIDING_B) is MISSING - the
    # simulated clobber.
    compact_rows = [
        {"roster_index": 1, "machine_key": pe._normalized_unit_code("Boeing XB-15"),
         "machine_name": "Boeing XB-15", "card": _card("Boeing XB-15"), "validation": {"passed": True}},
        {"roster_index": 2, "machine_key": pe._normalized_unit_code(_COLLIDING_A),
         "machine_name": _COLLIDING_A, "card": _card(_COLLIDING_A), "validation": {"passed": True}},
    ]
    conn = FakeConn(video_row, compact_rows)

    plan = asyncio.run(replay.build_replay_plan(conn, "tenant-a", "video-a"))
    assert plan["status"] == "completed"
    assert plan["roster_count"] == 3
    assert plan["before_row_count"] == 2
    assert [item["roster_index"] for item in plan["unchanged"]] == [1, 2]
    assert len(plan["recover"]) == 1
    recovered = plan["recover"][0]
    assert recovered["roster_index"] == 3
    assert recovered["machine"] == _COLLIDING_B
    assert recovered["had_existing_row"] is False
    assert not plan["missing_card"]
    assert plan["after_row_count"] == 3

    written = asyncio.run(replay.apply_replay_plan(conn, "tenant-a", "video-a", plan))
    assert written == 1
    assert set(conn.compact_rows.keys()) == {1, 2, 3}
    slot3 = conn.compact_rows[3]
    assert slot3["machine_name"] == _COLLIDING_B
    assert slot3["machine_key"] == pe._normalized_unit_code(_COLLIDING_B)
    # Recovered row's machine_key legitimately collides with slot 2's - this
    # is exactly the case roster_index-as-identity must tolerate.
    assert slot3["machine_key"] == conn.compact_rows[2]["machine_key"]
    assert conn.compact_rows[2]["machine_name"] == _COLLIDING_A  # untouched


def test_replay_is_idempotent(monkeypatch):
    """A second replay over the now-repaired state finds nothing left to
    recover - re-running the tool after a successful --apply is a no-op."""
    video_row, roster = _colliding_roster_video()
    compact_rows = [
        {"roster_index": 1, "machine_key": pe._normalized_unit_code("Boeing XB-15"),
         "machine_name": "Boeing XB-15", "card": _card("Boeing XB-15"), "validation": {"passed": True}},
        {"roster_index": 2, "machine_key": pe._normalized_unit_code(_COLLIDING_A),
         "machine_name": _COLLIDING_A, "card": _card(_COLLIDING_A), "validation": {"passed": True}},
    ]
    conn = FakeConn(video_row, compact_rows)

    first_plan = asyncio.run(replay.build_replay_plan(conn, "tenant-a", "video-a"))
    asyncio.run(replay.apply_replay_plan(conn, "tenant-a", "video-a", first_plan))
    assert len(first_plan["recover"]) == 1

    second_plan = asyncio.run(replay.build_replay_plan(conn, "tenant-a", "video-a"))
    assert second_plan["recover"] == []
    assert second_plan["before_row_count"] == 3
    assert second_plan["after_row_count"] == 3
    assert sorted(item["roster_index"] for item in second_plan["unchanged"]) == [1, 2, 3]

    written_again = asyncio.run(replay.apply_replay_plan(conn, "tenant-a", "video-a", second_plan))
    assert written_again == 0
    assert conn.executed  # only from the FIRST apply
    assert len(conn.executed) == 1


def test_replay_reports_a_card_it_cannot_recover():
    """If the JSONB payload itself never had a card for a roster slot (a
    genuinely never-researched machine, not a clobbered write), replay must
    say so rather than fabricate a card."""
    roster = ["Boeing XB-15", _COLLIDING_A, _COLLIDING_B]
    payload = {
        "unit_roster": roster,
        "unit_research_cards": [_card("Boeing XB-15"), _card(_COLLIDING_A)],  # slot 3's card missing too
    }
    video_row = {"id": "video-a", "tenant_id": "tenant-a", "research_payload": payload}
    conn = FakeConn(video_row, [
        {"roster_index": 1, "machine_key": pe._normalized_unit_code("Boeing XB-15"),
         "machine_name": "Boeing XB-15", "card": _card("Boeing XB-15"), "validation": {"passed": True}},
        {"roster_index": 2, "machine_key": pe._normalized_unit_code(_COLLIDING_A),
         "machine_name": _COLLIDING_A, "card": _card(_COLLIDING_A), "validation": {"passed": True}},
    ])

    plan = asyncio.run(replay.build_replay_plan(conn, "tenant-a", "video-a"))
    assert plan["recover"] == []
    assert plan["missing_card"] == [{"roster_index": 3, "machine": _COLLIDING_B}]
    assert plan["after_row_count"] == 2


def test_replay_dry_run_never_writes():
    """The default (no --apply) path must not call execute at all."""
    video_row, roster = _colliding_roster_video()
    conn = FakeConn(video_row, [
        {"roster_index": 1, "machine_key": pe._normalized_unit_code("Boeing XB-15"),
         "machine_name": "Boeing XB-15", "card": _card("Boeing XB-15"), "validation": {"passed": True}},
    ])

    plan = asyncio.run(replay.build_replay_plan(conn, "tenant-a", "video-a"))
    assert len(plan["recover"]) == 2  # both colliding-pair slots missing
    assert conn.executed == []  # build_replay_plan is read-only


def test_reader_resolves_both_colliding_members_after_recovery():
    """The reader-level half of G5: once BOTH rows exist (post-replay),
    _load_machine_research_cards and enrich_research_payload_readiness must
    resolve each colliding-pair member to ITS OWN card/verdict, never the
    other's - proving the roster_index-keyed readers (not just the writer)
    handle the collision correctly."""
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-a"
    roster = ["Boeing XB-15", _COLLIDING_A, _COLLIDING_B]
    compact_rows = [
        {"machine_key": pe._normalized_unit_code("Boeing XB-15"), "machine_name": "Boeing XB-15",
         "roster_index": 1, "card": _card("Boeing XB-15"), "validation": {"passed": True}},
        {"machine_key": pe._normalized_unit_code(_COLLIDING_A), "machine_name": _COLLIDING_A,
         "roster_index": 2, "card": _card(_COLLIDING_A, "Thesis A distinct from thesis B here."),
         "validation": {"passed": True, "warnings": []}},
        {"machine_key": pe._normalized_unit_code(_COLLIDING_B), "machine_name": _COLLIDING_B,
         "roster_index": 3, "card": _card(_COLLIDING_B, "Thesis B distinct from thesis A here."),
         "validation": {"passed": True, "warnings": ["distinct advisory warning for B only"]}},
    ]

    async def fake_fetch_all(query, *_args, **_kwargs):
        if "roster_index, card, validation" in query or "roster_index, machine_name, card" in query:
            return compact_rows
        if "roster_index, validation" in query:
            return [{"roster_index": r["roster_index"], "validation": r["validation"]} for r in compact_rows]
        return compact_rows

    import pipeline_executor as pe_module
    orig_fetch_all = pe_module.fetch_all
    pe_module.fetch_all = fake_fetch_all
    try:
        legacy_payload = {
            "unit_roster": roster,
            "unit_research_cards": [
                _card("Boeing XB-15"), _card(_COLLIDING_A), _card(_COLLIDING_B),
            ],
        }

        # --- _load_machine_research_cards: both members keep their OWN card ---
        loaded = asyncio.run(executor._load_machine_research_cards("video-a", legacy_payload))
        cards_by_unit = {c["unit"]: c for c in loaded["unit_research_cards"]}
        assert cards_by_unit[_COLLIDING_A]["engineering_thesis"] == "Thesis A distinct from thesis B here."
        assert cards_by_unit[_COLLIDING_B]["engineering_thesis"] == "Thesis B distinct from thesis A here."

        # --- enrich_research_payload_readiness: each gets its OWN verdict ---
        enriched = asyncio.run(
            pe_module.enrich_research_payload_readiness("tenant-a", "video-a", dict(legacy_payload))
        )
        by_unit = {c["unit"]: c for c in enriched["unit_research_cards"]}
        assert by_unit[_COLLIDING_A]["readiness"] == {"passed": True, "warnings": []}
        assert by_unit[_COLLIDING_B]["readiness"] == {
            "passed": True, "warnings": ["distinct advisory warning for B only"],
        }
    finally:
        pe_module.fetch_all = orig_fetch_all
