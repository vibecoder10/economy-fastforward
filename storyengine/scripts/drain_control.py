#!/usr/bin/env python3
"""Operator CLI for StoryEngine's PostgreSQL-backed application drain.

Runs on the VPS through ``se drain|drain-status|undrain``. It intentionally
uses asyncpg directly, so it remains usable even if the API process is down.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys


REPO = Path(__file__).resolve().parents[2]
ENV_FILES = (REPO / "storyengine" / ".env", REPO / "storyengine" / "backend" / ".env")
GLOBAL_LOCK_NAME = "storyengine:application-drain:v1"


def _load_env() -> None:
    for path in ENV_FILES:
        if not path.exists():
            continue
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def _json(value: object) -> None:
    print(json.dumps(value, default=str, separators=(",", ":")))


async def _set_mode(conn, mode: str, reason: str, owner: str) -> dict:
    async with conn.transaction():
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext($1)::bigint)",
            GLOBAL_LOCK_NAME,
        )
        row = await conn.fetchrow(
            "INSERT INTO application_drain_state "
            "(singleton, mode, reason, owner, changed_at) "
            "VALUES (TRUE, $1, $2, $3, now()) "
            "ON CONFLICT (singleton) DO UPDATE SET "
            "mode = EXCLUDED.mode, reason = EXCLUDED.reason, "
            "owner = EXCLUDED.owner, changed_at = now() "
            "RETURNING mode, reason, owner, changed_at",
            mode,
            reason,
            owner,
        )
    return dict(row)


async def _status(conn) -> dict:
    state = await conn.fetchrow(
        "SELECT mode, reason, owner, changed_at "
        "FROM application_drain_state WHERE singleton = TRUE"
    )
    work = await conn.fetchrow(
        "SELECT "
        "(SELECT count(*) FROM background_tasks "
        " WHERE status IN ('pending', 'running')) AS background_tasks, "
        "(SELECT count(*) FROM generation_claims "
        " WHERE claimed_at > now() - interval '2 hours') AS generation_claims"
    )
    state_dict = dict(state) if state else {
        "mode": "normal",
        "reason": None,
        "owner": None,
        "changed_at": None,
    }
    work_dict = {key: int(value or 0) for key, value in dict(work).items()}
    work_dict["total"] = work_dict["background_tasks"] + work_dict["generation_claims"]
    return {
        "drain": {**state_dict, "draining": state_dict["mode"] == "draining"},
        "active_work": work_dict,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


async def _run(args: argparse.Namespace) -> int:
    _load_env()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2

    import asyncpg

    conn = await asyncpg.connect(database_url)
    try:
        if args.command == "drain":
            await _set_mode(conn, "draining", args.reason, args.owner)
            _json(await _status(conn))
            return 0
        if args.command == "undrain":
            await _set_mode(conn, "normal", args.reason, args.owner)
            _json(await _status(conn))
            return 0
        if args.command == "status":
            _json(await _status(conn))
            return 0
        if args.command == "wait":
            deadline = asyncio.get_running_loop().time() + args.timeout
            quiet_observations = 0
            while True:
                current = await _status(conn)
                _json(current)
                if current["active_work"]["total"] == 0:
                    quiet_observations += 1
                    if quiet_observations >= args.settle:
                        return 0
                else:
                    quiet_observations = 0
                if asyncio.get_running_loop().time() >= deadline:
                    print(
                        f"timed out waiting for active work after {args.timeout}s",
                        file=sys.stderr,
                    )
                    return 3
                await asyncio.sleep(args.interval)
    finally:
        await conn.close()
    return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    drain = sub.add_parser("drain")
    drain.add_argument("--reason", required=True)
    drain.add_argument("--owner", required=True)

    undrain = sub.add_parser("undrain")
    undrain.add_argument("--reason", default="deployment complete")
    undrain.add_argument("--owner", required=True)

    sub.add_parser("status")

    wait = sub.add_parser("wait")
    wait.add_argument("--timeout", type=int, default=7200)
    wait.add_argument("--interval", type=float, default=5)
    wait.add_argument(
        "--settle",
        type=int,
        default=2,
        help="consecutive zero-work observations required",
    )
    return parser


def main() -> int:
    return asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
