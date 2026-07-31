"""Recovery tool for machine_research_cards rows dropped by a machine_key
collision (the identity bug fixed by migration
149_machine_research_cards_roster_index_identity.sql).

Before migration 149, machine_research_cards was upserted
ON CONFLICT (tenant_id, video_id, machine_key) - but two DISTINCT locked
roster entries can legitimately derive the same _normalized_unit_code, e.g.
  "Audacious class / Malta class"  -> CVA01
  "CVA-01 class"                   -> CVA01
so the second colliding write silently clobbered the first row instead of
the two coexisting. The JSONB research_payload.unit_research_cards list was
never keyed by machine_key (only this compact table was), so it still has
every entry intact - this script re-derives the missing/wrong compact-table
rows from that JSONB source of truth, keyed by roster_index (migration
149's row identity), using the exact same resolver
(pe._roster_index_for_identity) and upsert statement
(pe._upsert_machine_research_card's SQL) production code uses, so it can
never disagree with what the running backend would compute.

Default is a DRY RUN: it reports what it WOULD change without writing
anything. Pass --apply to actually write. Idempotent: running it twice with
--apply is a no-op the second time (every roster slot's stored
machine_key/machine_name already matches, so nothing is in the "recover"
list).

This script is NOT run automatically by anything (no cron, no startup
hook, no migration) and must never be wired into one - it is a manual
recovery tool, invoked by a human against one video_id at a time.

Usage:
  python3 scripts/replay_research_cards.py --video-id <uuid> --tenant-id <uuid>
  python3 scripts/replay_research_cards.py --video-id <uuid> --tenant-id <uuid> --apply
  python3 scripts/replay_research_cards.py --video-id <uuid> --tenant-id <uuid> --apply --json

The confirmed prod damage case (video d2e37cd6-521a-43aa-a14d-ce096a783c1e,
21 -> 23 rows expected) has its exact invocation and expected before/after
counts recorded in tasks/deferred-verification.md - this script is
deliberately NOT run against prod by this chunk's worker (read-only DB
access only, per the G5 cost cap).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

try:
    from dotenv import load_dotenv
    load_dotenv(_BACKEND / ".env")
except Exception:
    pass

import pipeline_executor as pe  # noqa: E402


def _json_field(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


def _card_identity(card: dict) -> Any:
    return card.get("unit") or card.get("machine") or card.get("name") or card.get("designation") or ""


async def build_replay_plan(conn: Any, tenant_id: str, video_id: str) -> dict[str, Any]:
    """Read-only: compute what replay would do, without writing anything.

    `conn` needs only async `fetchrow(query, *args)` and `fetch(query,
    *args)` methods (the asyncpg.Connection surface this script uses) -
    tests pass a lightweight fake instead of a real database.
    """
    video_row = await conn.fetchrow(
        "SELECT id, tenant_id, research_payload FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video_row:
        return {"status": "failed", "error": f"Video not found for tenant: {video_id}"}
    video_row = dict(video_row)
    payload = _json_field(video_row.get("research_payload")) or {}
    if not isinstance(payload, dict):
        return {"status": "failed", "error": "research_payload is missing or invalid"}
    roster = [
        pe._unit_display_name(item) for item in (payload.get("unit_roster") or [])
        if pe._unit_display_name(item)
    ]
    if not roster:
        return {"status": "failed", "error": "No locked unit_roster found in research_payload"}
    cards = payload.get("unit_research_cards")
    cards = cards if isinstance(cards, list) else []

    existing_rows = [
        dict(row) for row in (
            await conn.fetch(
                "SELECT roster_index, machine_key, machine_name, validation FROM machine_research_cards "
                "WHERE tenant_id = $1 AND video_id = $2",
                tenant_id, video_id,
            )
        )
    ]
    existing_by_index = {row["roster_index"]: row for row in existing_rows}

    recover: list[dict[str, Any]] = []
    unchanged: list[dict[str, Any]] = []
    missing_card: list[dict[str, Any]] = []

    for index, machine in enumerate(roster, start=1):
        card = next(
            (
                c for c in cards
                if isinstance(c, dict)
                and pe._roster_index_for_identity(roster, _card_identity(c)) == index
            ),
            None,
        )
        if card is None:
            missing_card.append({"roster_index": index, "machine": machine})
            continue
        existing = existing_by_index.get(index)
        expected_key = pe._normalized_unit_code(machine)
        if (
            existing is not None
            and existing.get("machine_key") == expected_key
            and existing.get("machine_name") == machine
        ):
            unchanged.append({"roster_index": index, "machine": machine})
            continue
        source_package = pe._verified_source_package_for_machine(payload, machine)
        warnings = pe._research_card_contract_warnings(
            machine, card, source_package, require_source_package=True
        )
        validation = {
            "machine": machine,
            "passed": not warnings,
            "warnings": warnings,
            "recovered_by": "replay_research_cards",
        }
        recover.append({
            "roster_index": index,
            "machine": machine,
            "had_existing_row": existing is not None,
            "existing_machine_key": (existing or {}).get("machine_key"),
            "existing_machine_name": (existing or {}).get("machine_name"),
            "validation": validation,
            "card": card,
        })

    return {
        "status": "completed",
        "video_id": video_id,
        "tenant_id": tenant_id,
        "roster_count": len(roster),
        "before_row_count": len(existing_rows),
        "after_row_count": len(unchanged) + len(recover),
        "recover": recover,
        "unchanged": unchanged,
        "missing_card": missing_card,
    }


async def apply_replay_plan(conn: Any, tenant_id: str, video_id: str, plan: dict[str, Any]) -> int:
    """Write every 'recover' entry using the exact same upsert SQL
    _upsert_machine_research_card uses (ON CONFLICT on roster_index -
    migration 149's row identity). Returns the number of rows written.

    `conn` needs only an async `execute(query, *args)` method.
    """
    written = 0
    for entry in plan.get("recover") or []:
        machine = entry["machine"]
        machine_key = pe._normalized_unit_code(machine)
        await conn.execute(
            """INSERT INTO machine_research_cards
             (tenant_id, video_id, machine_key, machine_name, roster_index, card, validation)
           SELECT $1, v.id, $3, $4, $5, $6::jsonb, $7::jsonb
           FROM videos v WHERE v.id = $2 AND v.tenant_id = $1
           ON CONFLICT (tenant_id, video_id, roster_index) DO UPDATE SET
             machine_key = EXCLUDED.machine_key,
             machine_name = EXCLUDED.machine_name,
             card = EXCLUDED.card,
             validation = EXCLUDED.validation,
             updated_at = now()""",
            tenant_id, video_id, machine_key, machine,
            entry["roster_index"], json.dumps(entry["card"]), json.dumps(entry["validation"]),
        )
        written += 1
    return written


def _print_human(plan: dict[str, Any], applied: bool) -> None:
    if plan.get("status") != "completed":
        print(f"FAILED: {plan.get('error')}")
        return
    print(f"Video {plan['video_id']} (tenant {plan['tenant_id']}) - locked roster: {plan['roster_count']} machine(s)")
    print(f"machine_research_cards rows before: {plan['before_row_count']}")
    print(f"unchanged (already correct): {len(plan['unchanged'])}")
    if plan["missing_card"]:
        print(f"missing card in research_payload (cannot recover - needs real research): {len(plan['missing_card'])}")
        for item in plan["missing_card"]:
            print(f"  - slot {item['roster_index']}: {item['machine']}")
    verb = "recovered" if applied else "would recover"
    print(f"{verb}: {len(plan['recover'])}")
    for item in plan["recover"]:
        if not item["had_existing_row"]:
            state = "row missing"
        else:
            state = f"wrong identity (was {item['existing_machine_key']!r}/{item['existing_machine_name']!r})"
        print(f"  - slot {item['roster_index']}: {item['machine']} ({state})")
    print(f"machine_research_cards rows after: {plan['after_row_count']}" + ("" if applied else " (projected)"))
    if not applied and plan["recover"]:
        print("\nDry run only - no rows written. Re-run with --apply to write.")


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    import asyncpg

    database_url = args.database_url or os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required (or pass --database-url)")
    conn = await asyncpg.connect(database_url)
    try:
        plan = await build_replay_plan(conn, args.tenant_id, args.video_id)
        if plan.get("status") == "completed" and args.apply and plan["recover"]:
            async with conn.transaction():
                await apply_replay_plan(conn, args.tenant_id, args.video_id, plan)
        return plan
    finally:
        await conn.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Recover machine_research_cards rows dropped by a machine_key collision (migration 149)."
    )
    parser.add_argument("--video-id", required=True, help="Video UUID to repair.")
    parser.add_argument("--tenant-id", required=True, help="Tenant UUID that owns the video.")
    parser.add_argument("--database-url", help="Override DATABASE_URL env var.")
    parser.add_argument("--apply", action="store_true", help="Actually write. Default is a dry run.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    plan = asyncio.run(_run(args))

    if args.json:
        print(json.dumps(plan, indent=2, default=str))
    else:
        _print_human(plan, applied=args.apply)

    return 0 if plan.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
