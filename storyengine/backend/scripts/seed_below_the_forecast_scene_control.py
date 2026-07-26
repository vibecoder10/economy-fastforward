#!/usr/bin/env python3
"""Compile the locked Below the Forecast treatment without provider work."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from custom_film_scene_storyboards import compile_below_the_forecast_fixture, seed_below_the_forecast


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=BACKEND.parent / "tasks/below-the-forecast-storyboard.md",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--tenant-id")
    parser.add_argument("--video-id")
    args = parser.parse_args()
    if args.apply:
        if not args.tenant_id:
            parser.error("--tenant-id is required with --apply")
        from database import get_pool
        async def apply():
            pool = await get_pool()
            async with pool.acquire() as conn, conn.transaction():
                return await seed_below_the_forecast(
                    conn, tenant_id=args.tenant_id, source_path=args.source,
                    video_id=args.video_id,
                )
        fixture = asyncio.run(apply())
    else:
        fixture = compile_below_the_forecast_fixture(args.source)
    rendered = json.dumps(fixture, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
