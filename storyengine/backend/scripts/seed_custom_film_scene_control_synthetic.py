"""Operator-only deterministic Scene Control seed.

This command has no provider or queue seam. It requires --apply before any
database write and marks every inserted record synthetic.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from custom_film_scene_control import seed_synthetic_one_scene  # noqa: E402
from database import get_pool  # noqa: E402


async def _run(tenant_id: str, video_id: str | None, *, apply: bool) -> int:
    if not apply:
        print(
            json.dumps(
                {
                    "apply": False,
                    "tenant_id": tenant_id,
                    "video_id": video_id,
                    "message": "Dry run only. Re-run with --apply to seed synthetic records.",
                },
                indent=2,
            )
        )
        return 0
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        result = await seed_synthetic_one_scene(
            conn,
            tenant_id=tenant_id,
            video_id=video_id,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument(
        "--video-id",
        help="Optional target UUID. Omit to create the tenant's deterministic synthetic video.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Persist a synthetic director, locks, Scene 1, and locked Scene 2. "
            "No provider work is performed."
        ),
    )
    args = parser.parse_args()
    return asyncio.run(_run(args.tenant_id, args.video_id, apply=args.apply))


if __name__ == "__main__":
    raise SystemExit(main())
