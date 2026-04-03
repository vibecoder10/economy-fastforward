"""Database connection to Supabase PostgreSQL via asyncpg."""

import os
import re
import asyncpg
from typing import Optional

_SAFE_COLUMN_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def safe_column(name: str) -> str:
    """Validate a column name before use in dynamic SQL.

    Prevents SQL injection via column names in f-string queries.
    Only allows lowercase alphanumeric + underscore, must start with a letter.
    """
    if not _SAFE_COLUMN_RE.match(name):
        raise ValueError(f"Invalid column name: {name!r}")
    return name

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    """Get or create the connection pool."""
    global _pool
    if _pool is None:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL not set")
        _pool = await asyncpg.create_pool(database_url, min_size=0, max_size=10)
    return _pool


async def close_pool():
    """Close the connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def fetch_all(query: str, *args):
    """Execute query and return all rows as list of dicts."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *args)
        return [dict(row) for row in rows]


async def fetch_one(query: str, *args):
    """Execute query and return single row as dict."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, *args)
        return dict(row) if row else None


async def execute(query: str, *args):
    """Execute a query (INSERT/UPDATE/DELETE)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.execute(query, *args)
