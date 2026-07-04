#!/usr/bin/env python3
"""se db helper - run SQL against the StoryEngine Postgres. Lives on the VPS.

SQL comes in on stdin (avoids all ssh quoting problems). Driven locally by
storyengine/scripts/se.sh ("se db"). Read-only by default: only SELECT / WITH /
SHOW / EXPLAIN run unless --write is passed. Rows print as JSON lines.
"""
import asyncio
import json
import os
import sys

ENV_PATH = os.path.expanduser("~/projects/economy-fastforward/storyengine/.env")
READ_VERBS = ("select", "with", "show", "explain")
MAX_ROWS = 500


def database_url() -> str:
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("DATABASE_URL="):
                    return line.split("=", 1)[1].strip().strip("\"'")
    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL not found in %s or env" % ENV_PATH)
    return url


async def main() -> None:
    sql = sys.stdin.read().strip()
    if not sql:
        sys.exit('no SQL on stdin. usage: se db [--write] "SQL"')
    write_ok = "--write" in sys.argv
    verb = sql.lstrip("(").split(None, 1)[0].lower()
    if verb not in READ_VERBS and not write_ok:
        sys.exit("blocked: '%s' is a write - rerun as: se db --write \"...\"" % verb)

    import asyncpg

    conn = await asyncpg.connect(database_url())
    try:
        if verb in READ_VERBS:
            rows = await conn.fetch(sql)
            for r in rows[:MAX_ROWS]:
                print(json.dumps(dict(r), default=str))
            if len(rows) > MAX_ROWS:
                print("-- truncated, %d more rows" % (len(rows) - MAX_ROWS), file=sys.stderr)
            print("-- %d rows" % len(rows), file=sys.stderr)
        else:
            print(await conn.execute(sql))
    finally:
        await conn.close()


asyncio.run(main())
