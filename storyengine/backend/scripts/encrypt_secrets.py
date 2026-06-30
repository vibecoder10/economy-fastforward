#!/usr/bin/env python3
"""One-time backfill: encrypt any plaintext rows in the `secrets` table.

Run this ONCE on the VPS after SECRETS_MASTER_KEY is set and the backend is
restarted, so existing keys (stored plaintext before encryption-at-rest shipped)
get encrypted in place. It is idempotent: rows already carrying the `enc::`
marker are left untouched, so re-running is safe.

    python scripts/encrypt_secrets.py --dry-run   # report only, no writes
    python scripts/encrypt_secrets.py             # encrypt plaintext rows

Refuses to run if SECRETS_MASTER_KEY is unset/invalid (there'd be nothing to
encrypt with). Back up the table first:
    pg_dump "$DATABASE_URL" -t secrets > secrets_backup.sql
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

# Make `import vault` / `import database` work when run from anywhere.
BACKEND = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(BACKEND))


def load_env_file(path: Path) -> None:
    """Mirror run_migrations_strict: pull the parent storyengine/.env into os.environ."""
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


async def backfill(dry_run: bool) -> int:
    import vault
    from database import fetch_all, execute, close_pool

    if vault._fernet() is None:
        print("ERROR: SECRETS_MASTER_KEY is not set or invalid — nothing to encrypt with.")
        print("Set it in the environment first, then re-run.")
        return 1

    rows = await fetch_all("SELECT name, value FROM secrets ORDER BY name")
    total = len(rows)
    already = sum(1 for r in rows if (r.get("value") or "").startswith(vault._ENC_PREFIX))
    empty = sum(1 for r in rows if not r.get("value"))
    plaintext = [r for r in rows if r.get("value") and not r["value"].startswith(vault._ENC_PREFIX)]

    print(f"Found {total} secret(s): {already} already encrypted, "
          f"{empty} empty, {len(plaintext)} plaintext to encrypt.")

    if not plaintext:
        print("Nothing to do — all secrets already encrypted.")
        await close_pool()
        return 0

    for r in plaintext:
        name = r["name"]
        if dry_run:
            print(f"  [dry-run] would encrypt: {name}")
            continue
        enc = vault._encrypt(r["value"])
        # Round-trip guard: never write a value we can't read back.
        if vault._decrypt(enc) != r["value"]:
            print(f"  SKIP {name}: round-trip check failed, leaving it untouched.")
            continue
        await execute("UPDATE secrets SET value = $1, updated_at = now() WHERE name = $2", enc, name)
        print(f"  encrypted: {name}")

    print("Dry run complete — no changes written." if dry_run
          else f"Done — encrypted {len(plaintext)} secret(s).")
    await close_pool()
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Encrypt plaintext rows in the secrets table.")
    ap.add_argument("--dry-run", action="store_true", help="Report only; write nothing.")
    args = ap.parse_args()

    # Load the parent .env (DATABASE_URL + SECRETS_MASTER_KEY live there on the VPS).
    load_env_file(BACKEND.parent / ".env")
    load_env_file(BACKEND / ".env")

    raise SystemExit(asyncio.run(backfill(args.dry_run)))


if __name__ == "__main__":
    main()
