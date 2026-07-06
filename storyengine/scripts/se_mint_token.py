#!/usr/bin/env python3
"""Mint a fresh StoryEngine session JWT on the VPS and write it to /tmp/se_token.

Driven by `se token --mint` / `se devtoken` from the Mac. Signs with
SESSION_SECRET from the parent storyengine/.env (same as the login route).
Tenant binding follows the login rule: owner membership first, then oldest
(the 2026-07-02 login-tenant bug fix - do not change the ordering).

Usage: se_mint_token.py [email]   (default ryan.ayler@gmail.com)
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

ENV_PATH = os.path.expanduser("~/projects/economy-fastforward/storyengine/.env")
TOKEN_PATH = "/tmp/se_token"
EXPIRY_DAYS = 30


def env_value(key: str) -> str:
    with open(ENV_PATH) as fh:
        for line in fh:
            line = line.strip()
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip("\"'")
    sys.exit("%s not found in %s" % (key, ENV_PATH))


async def main() -> None:
    email = sys.argv[1] if len(sys.argv) > 1 else "ryan.ayler@gmail.com"
    import asyncpg
    import jwt

    conn = await asyncpg.connect(env_value("DATABASE_URL"))
    try:
        row = await conn.fetchrow(
            """
            SELECT a.id, a.email, m.tenant_id
            FROM accounts a
            JOIN memberships m ON m.user_id = a.id
            WHERE a.email = $1
            ORDER BY (m.role = 'owner') DESC, m.created_at
            LIMIT 1
            """,
            email,
        )
    finally:
        await conn.close()
    if not row:
        sys.exit("no account/membership found for %s" % email)

    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": str(row["id"]),
            "email": row["email"],
            "tenant_id": str(row["tenant_id"]),
            "iat": now,
            "exp": now + timedelta(days=EXPIRY_DAYS),
            "iss": "storyengine",
        },
        env_value("SESSION_SECRET"),
        algorithm="HS256",
    )
    with open(TOKEN_PATH, "w") as fh:
        fh.write(token)
    print(token)


asyncio.run(main())
