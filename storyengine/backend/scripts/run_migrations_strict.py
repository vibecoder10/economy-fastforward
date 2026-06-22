#!/usr/bin/env python3
"""Run StoryEngine SQL migrations with hard failure on the first error.

Use this during Supabase cutovers instead of relying only on app startup,
because startup logs migration errors as non-blocking warnings.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

import asyncpg


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
MIGRATIONS = BACKEND / "migrations"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


async def run_migrations(database_url: str, dry_run: bool = False) -> None:
    conn = await asyncpg.connect(database_url)
    try:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS _migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
        await conn.execute("ALTER TABLE _migrations ENABLE ROW LEVEL SECURITY")
        await conn.execute("REVOKE ALL ON _migrations FROM anon")
        await conn.execute("REVOKE ALL ON _migrations FROM authenticated")

        rows = await conn.fetch("SELECT filename FROM _migrations")
        applied = {row["filename"] for row in rows}
        files = sorted(MIGRATIONS.glob("*.sql"))
        pending = [path for path in files if path.name not in applied]

        print(f"migrations_dir={MIGRATIONS}")
        print(f"total={len(files)} applied={len(applied)} pending={len(pending)}")
        for path in pending:
            print(f"pending {path.name}")

        if dry_run:
            return

        for path in pending:
            sql = path.read_text()
            print(f"applying {path.name}")
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO _migrations (filename) VALUES ($1)",
                    path.name,
                )
        print("migrations complete")
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_env_file(ROOT / ".env")
    load_env_file(BACKEND / ".env")

    database_url = args.database_url or os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required")

    asyncio.run(run_migrations(database_url, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
