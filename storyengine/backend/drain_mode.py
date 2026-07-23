"""Durable application-level drain mode.

Drain mode is a deployment safety primitive, not a kill switch:

* existing work keeps running and may persist terminal state;
* reads, reviews, downloads, and task polling stay available;
* new provider/background starts are rejected before they can incur cost.

The state lives in PostgreSQL because production supports an in-process queue
when Redis is unavailable.  A fixed transaction-scoped advisory lock is shared
with generation claims.  That gives the operator a real boundary: once
``set_draining`` commits, no later generation claim can have observed
``normal``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import logging
from typing import Any, Optional

import database

logger = logging.getLogger(__name__)

MODE_NORMAL = "normal"
MODE_DRAINING = "draining"
RETRY_AFTER_SECONDS = 30

# A stable string is hashed by PostgreSQL, avoiding platform-dependent Python
# hash values. Every transition and every generation claim uses this lock.
GLOBAL_LOCK_NAME = "storyengine:application-drain:v1"


@dataclass(frozen=True)
class DrainState:
    mode: str = MODE_NORMAL
    reason: Optional[str] = None
    owner: Optional[str] = None
    changed_at: Optional[str] = None
    known: bool = True

    @property
    def draining(self) -> bool:
        return self.mode == MODE_DRAINING

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["draining"] = self.draining
        return value


class DrainModeActive(RuntimeError):
    """Raised when a new-work boundary is crossed while draining."""

    code = "system_draining"
    retryable = True

    def __init__(self, state: DrainState):
        self.state = state
        reason = f" ({state.reason})" if state.reason else ""
        self.message = (
            "StoryEngine is briefly pausing new generation for a safe deployment"
            f"{reason}. Existing work is finishing; please retry shortly."
        )
        super().__init__(self.message)

    def response_body(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "drain": self.state.to_dict(),
        }


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    try:
        return row.get(key, default)
    except AttributeError:
        try:
            return row[key]
        except (KeyError, TypeError):
            return default


def _state_from_row(row: Any, *, known: bool = True) -> DrainState:
    changed_at = _row_value(row, "changed_at")
    if changed_at is not None:
        changed_at = changed_at.isoformat() if hasattr(changed_at, "isoformat") else str(changed_at)
    return DrainState(
        mode=_row_value(row, "mode", MODE_NORMAL),
        reason=_row_value(row, "reason"),
        owner=_row_value(row, "owner"),
        changed_at=changed_at,
        known=known,
    )


async def _lock(conn: Any) -> None:
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtext($1)::bigint)",
        GLOBAL_LOCK_NAME,
    )


async def get_state(*, fail_closed: bool = False) -> DrainState:
    """Read drain state.

    Status/health reads are fail-soft by default so an old checkout can still
    start while migration 120 is being applied. New-work guards pass
    ``fail_closed=True``: a database/control-plane error must not open a paid
    work window during a deploy.
    """
    try:
        pool = await database.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT mode, reason, owner, changed_at "
                "FROM application_drain_state WHERE singleton = TRUE"
            )
            return _state_from_row(row)
    except Exception:
        logger.warning("[drain] state read failed", exc_info=True)
        if fail_closed:
            return DrainState(
                mode=MODE_DRAINING,
                reason="drain state unavailable",
                owner="system",
                known=False,
            )
        return DrainState(known=False)


async def assert_accepting_conn(conn: Any) -> DrainState:
    """Assert normal mode inside the caller's existing DB transaction.

    The shared advisory lock makes the state read atomic with generation-claim
    creation. Callers must be inside a transaction.
    """
    await _lock(conn)
    row = await conn.fetchrow(
        "SELECT mode, reason, owner, changed_at "
        "FROM application_drain_state WHERE singleton = TRUE"
    )
    state = _state_from_row(row)
    if state.draining:
        raise DrainModeActive(state)
    return state


async def assert_accepting_new_work() -> DrainState:
    """Fail closed unless the durable control state is definitely normal."""
    state = await get_state(fail_closed=True)
    if state.draining:
        raise DrainModeActive(state)
    return state


async def is_draining() -> bool:
    """Cheap, fail-closed predicate for autonomous schedulers."""
    return (await get_state(fail_closed=True)).draining


async def _set_mode(mode: str, *, reason: Optional[str], owner: Optional[str]) -> DrainState:
    if mode not in {MODE_NORMAL, MODE_DRAINING}:
        raise ValueError(f"Unsupported drain mode: {mode}")
    pool = await database.get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _lock(conn)
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
            return _state_from_row(row)


async def set_draining(*, reason: str, owner: str) -> DrainState:
    if not reason.strip():
        raise ValueError("Drain reason is required")
    if not owner.strip():
        raise ValueError("Drain owner is required")
    return await _set_mode(MODE_DRAINING, reason=reason.strip(), owner=owner.strip())


async def set_normal(*, owner: str, reason: str = "deployment complete") -> DrainState:
    if not owner.strip():
        raise ValueError("Drain owner is required")
    return await _set_mode(MODE_NORMAL, reason=reason.strip(), owner=owner.strip())


async def get_active_work() -> dict[str, int]:
    """Return durable work counts used by the deploy wait loop.

    Generation claims are counted as well as background tasks. The two can
    overlap, so ``total`` is intentionally conservative rather than a unique
    job count: deploy safety cares that every signal reaches zero.
    """
    pool = await database.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT "
            "(SELECT count(*) FROM background_tasks "
            " WHERE status IN ('pending', 'running')) AS background_tasks, "
            "(SELECT count(*) FROM generation_claims "
            " WHERE claimed_at > now() - interval '2 hours') AS generation_claims"
        )
    background = int(_row_value(row, "background_tasks", 0) or 0)
    claims = int(_row_value(row, "generation_claims", 0) or 0)
    return {
        "background_tasks": background,
        "generation_claims": claims,
        "total": background + claims,
    }


# Request prefixes that can launch providers, uploads, or long-running jobs.
# Ordinary metadata routes are deliberately absent.
_BLOCKED_MUTATION_PREFIXES = (
    "/api/pipeline",
    "/api/chat",
    "/api/autopilot",
    "/api/discovery",
    "/api/intelligence",
    "/api/model-video",
    "/api/channel-dna",
    "/api/mcp",
    "/api/agents",
)

# Queue edits remain available, but launch endpoints do not.
_BLOCKED_EXACT_OR_SUFFIXES = (
    "/api/queue/next/launch",
    "/launch",
    "/generate",
    "/regenerate",
    "/design",
    "/learn-voice",
    "/generate-seo",
    "/tag-dialogue",
    "/rewrite",
    "/recrop",
    "/fix-text",
    "/sync",
    "/push-to-drive",
    "/sync-from-drive",
    "/suggest-titles",
)

_SAFE_PIPELINE_MUTATIONS = (
    "/api/pipeline/cancel/",
    "/api/pipeline/static-qa-approve/",
    "/api/pipeline/reset/",
)


def mutation_starts_work(method: str, path: str) -> bool:
    """Pure request-boundary classifier used by middleware and tests."""
    if method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
        return False
    if any(path.startswith(prefix) for prefix in _SAFE_PIPELINE_MUTATIONS):
        return False
    if path.startswith("/api/pipeline/actions/") and path.endswith("/approve-scene"):
        return False
    if any(path.startswith(prefix) for prefix in _BLOCKED_MUTATION_PREFIXES):
        return True
    if path.startswith("/api/queue/") and path.endswith("/launch"):
        return True
    if path == "/api/queue/next/launch":
        return True
    if path.startswith("/api/youtube") and method.upper() == "POST":
        return True
    if path in {
        "/api/niche/scrape",
        "/api/learnings/extract",
        "/api/learnings/analyze-titles",
        "/api/learnings/analyze-transcripts",
        "/api/channel-profile/documents/refresh",
        "/api/onboarding/connect-youtube",
        "/api/onboarding/competitors/analyze",
    }:
        return True
    if path.startswith("/api/learnings/extract/"):
        return True
    if path.startswith("/api/videos/"):
        return any(path.endswith(suffix) for suffix in _BLOCKED_EXACT_OR_SUFFIXES)
    return False
