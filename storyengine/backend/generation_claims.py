"""DB-backed generation claims — the money-safety lock chunk C16a builds.

Problem (audit S7-1 CRITICAL, docs/reports/2026-07-17-storyengine-agent-audit-
findings.md §S7): the chat-driven autobuild/copilot dispatch
(``routes/chat.py``'s ``_handle_approve``/``_run_pending_action`` ->
``actions.py``'s ``make_autobuild_step``/``make_action_step``) scheduled paid
background work via a bare ``background_tasks.add_task(...)`` with ZERO
concurrency guard — zero grep hits for the existing guard anywhere in
chat.py/actions.py. A double-tap or a retried chat turn scheduled two
concurrent ``_run`` loops on the same video -> double paid generation. The
only existing guard (``_running_tasks``/``_side_lanes`` dicts,
``routes/pipeline.py``:139/152) is in-process only: wiped on every restart,
and chat never consulted it at all (S7-6 MED, folded into this chunk).

This module is the fix for both: a small DB table (``generation_claims``,
migration 092) that chat AND the manual ``routes/pipeline.py`` (+
``videos.py``/``environments.py``/``characters.py``) endpoints both consult
before dispatching paid work — a claim held by either path now blocks the
other, and the claim survives a restart (a DB row, unlike an in-process
dict, doesn't vanish on deploy).

Lane vocabulary (deliberately reused, not reinvented): ``routes/pipeline.py``
already treats "main" as the one exclusive lane every full-pipeline stage
(script/storyboards/images/render/...) runs in, and voice/characters/
thumbnail (also environments, at the routes/environments.py layer) as
independent side lanes that block "main" and are blocked by it, but never by
each other (see ``_is_task_active``'s lane semantics, routes/pipeline.py
~L365-388). Chat's whole-video autobuild chain is exactly a "main"-lane
operation — it walks the same stages a manual main-lane click would — so it
claims stage="main" too, not a separate "autobuild" label. That is the
granularity choice this chunk makes: a manual "Generate Script" click and a
chat-driven autobuild run must genuinely conflict, and they only will if
they claim the identical stage name. A single-stage copilot verb that has
its own independent lane in the existing system ("voice", "characters",
"thumbnail") claims that lane's own name; every other verb (script,
storyboards, images, animate, sound, render, research, upload, build) claims
"main", matching how routes/pipeline.py already treats them today (see
``stage_for_verb``).

Fail-soft vs fail-closed (explicit split, per the C16a spec): a DB outage
must never OPEN the double-spend window, but it also must not need to be the
reason nothing in the app works. ``acquire()`` and ``is_blocked()`` both
DENY (return "busy" -> caller refuses/treats-as-active) on any unexpected DB
error rather than silently letting a second paid run through — this is the
fail-CLOSED-for-spend rule. ``release()`` is the opposite: best-effort only
(logs, never raises) — a failed DELETE just leaves a row that the next
acquire's stale sweep (>2h) clears on its own, so a release hiccup degrades
to "this video is locked for up to 2h", never a permanent wedge and never a
double-spend.
"""
from __future__ import annotations

import logging
from typing import Optional

# `import database` (not `from database import get_pool`) deliberately: many
# test files stub a bare-bones `database` module (only execute/fetch_one) in
# sys.modules before importing modules that reach this one transitively
# (e.g. actions.py's make_autobuild_step/make_action_step lazily import this
# module). Resolving `database.get_pool` at CALL time instead of import time
# means a stub missing get_pool only ever raises inside acquire()/release()/
# is_blocked() — where it's already caught and handled (fail-closed for
# acquire/is_blocked, fail-soft for release) — never as an ImportError at
# `import generation_claims` itself.
import database
import drain_mode

logger = logging.getLogger(__name__)

# A claim older than this is treated as abandoned (crashed worker, killed
# process, restart mid-run) and is swept + retaken rather than wedging the
# video forever. Matches the "~2h" figure the C16a spec calls for.
STALE_HOURS = 2

# Verbs/lanes independent of the exclusive "main" lane — mirrors
# routes/pipeline.py's _lane_begin/_is_task_active side-lane vocabulary
# exactly, so a DB claim and the in-process dict never disagree about what
# counts as a side lane vs "main".
SIDE_LANES = frozenset({"voice", "characters", "environments", "thumbnail"})


def stage_for_verb(verb: Optional[str]) -> str:
    """Map a copilot verb (or None/anything else, including the whole-video
    autobuild chain) onto the claim's stage/lane name. Side-lane verbs keep
    their own name (voice, characters, thumbnail); everything else —
    including "build" (autobuild) and any verb without an independent lane
    today (script, storyboards, images, animate, sound, render, research,
    upload) — claims "main", matching the exclusive lane every one of those
    already runs in under routes/pipeline.py's in-process guard.
    """
    if verb in SIDE_LANES:
        return verb
    return "main"


def _blocked(stage: str, active: set) -> bool:
    """Same rule _is_task_active applies to the in-process dict: "main" is
    blocked by ANY active stage (including a side lane still running); a
    side lane is blocked by "main" or by itself, never by a different side
    lane (voice can run while thumbnail generates)."""
    if "main" in active:
        return True
    if stage == "main":
        return bool(active)
    return stage in active


async def _active_stages(conn, tenant_id: str, video_id: str) -> set:
    rows = await conn.fetch(
        "SELECT stage FROM generation_claims WHERE tenant_id = $1 AND video_id = $2",
        tenant_id, video_id,
    )
    return {r["stage"] for r in rows}


async def acquire(tenant_id: str, video_id: str, stage: str, claimed_by: Optional[str] = None) -> bool:
    """Atomically take the claim for (tenant_id, video_id, stage), applying
    the same main/side-lane blocking rule the in-process dict uses.

    TOCTOU-free: a per-video Postgres advisory transaction lock
    (``pg_advisory_xact_lock``) serializes every acquire attempt for this
    video — including attempts for a DIFFERENT stage, which a plain per-row
    ``INSERT ... ON CONFLICT`` could never see, since a conflict only fires
    for the exact same (tenant_id, video_id, stage) key — around the whole
    stale-sweep-then-check-then-insert sequence below, inside one
    transaction. A stale claim's retake can't race a fresh acquire either:
    the DELETE and the INSERT happen under the same lock in the same
    transaction. Fails CLOSED (returns False) on any DB error.
    """
    try:
        pool = await database.get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                # The global drain lock must be taken BEFORE the per-video
                # lock. set_draining() takes the same global lock, updates the
                # singleton row, and commits. Once that call returns, no later
                # paid claim can have observed normal mode.
                await drain_mode.assert_accepting_conn(conn)
                # Advisory lock keyed on the VIDEO (not the stage) — this is
                # what makes cross-stage blocking (main vs. a side lane)
                # TOCTOU-free: every acquire for this video, whatever stage
                # it's for, serializes through this one lock.
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtext($1)::bigint)",
                    f"{tenant_id}:{video_id}",
                )
                await conn.execute(
                    "DELETE FROM generation_claims WHERE tenant_id = $1 AND video_id = $2 "
                    "AND claimed_at < now() - interval '2 hours'",
                    tenant_id, video_id,
                )
                active = await _active_stages(conn, tenant_id, video_id)
                if _blocked(stage, active):
                    return False
                row = await conn.fetchrow(
                    "INSERT INTO generation_claims (tenant_id, video_id, stage, claimed_by) "
                    "VALUES ($1, $2, $3, $4) "
                    "ON CONFLICT (tenant_id, video_id, stage) DO NOTHING "
                    "RETURNING stage",
                    tenant_id, video_id, stage, claimed_by,
                )
                return row is not None
    except drain_mode.DrainModeActive:
        raise
    except Exception:
        logger.exception(
            "[generation_claims] acquire failed tenant=%s video=%s stage=%s — "
            "DENYING the claim (fail-closed: a DB error must never open the "
            "double-spend window)", tenant_id, video_id, stage,
        )
        return False


async def release(tenant_id: str, video_id: str, stage: str) -> None:
    """Best-effort release — never raises. A failed release just leaves the
    row for the next acquire's stale sweep (>2h) to clear; it degrades to a
    temporary lock on this one stage, never a permanent wedge and never a
    double-spend."""
    try:
        pool = await database.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM generation_claims WHERE tenant_id = $1 AND video_id = $2 AND stage = $3",
                tenant_id, video_id, stage,
            )
    except Exception:
        logger.warning(
            "[generation_claims] release failed tenant=%s video=%s stage=%s — "
            "row will self-clear via the 2h stale sweep on the next acquire",
            tenant_id, video_id, stage, exc_info=True,
        )


async def get_claimed_by(tenant_id: str, video_id: str) -> Optional[str]:
    """Read-only lookup of the most recent active (non-stale) claim's
    ``claimed_by`` label for this video — UI attribution ONLY (checklist
    P2.4c/C28's "via agent" chip), never used for access control (mirrors
    the module docstring/migration comment: claimed_by is "free-text debug
    label ... never used for access control").

    Fail-SOFT, unlike acquire()/is_blocked(): returns None on any DB error.
    A chip that fails to render must never affect anything else — there is
    no money-safety reason to fail closed here.
    """
    try:
        pool = await database.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT claimed_by FROM generation_claims WHERE tenant_id = $1 AND video_id = $2 "
                "AND claimed_at > now() - interval '2 hours' ORDER BY claimed_at DESC LIMIT 1",
                tenant_id, video_id,
            )
            return row["claimed_by"] if row else None
    except Exception:
        logger.warning(
            "[generation_claims] get_claimed_by failed tenant=%s video=%s — "
            "returning None (fail-soft: UI attribution only, never gates access)",
            tenant_id, video_id, exc_info=True,
        )
        return None


async def acquire_channel(tenant_id: str, stage: str = "dna", claimed_by: Optional[str] = None) -> bool:
    """Channel-level (video-less) counterpart to acquire(), for tenant-wide
    learners — today only ``channel_dna.learn_channel`` (checklist C41) —
    that rebuild ``channel_profiles.channel_identity`` and have no single
    ``video_id`` to key a claim on. This is the fix C40's decisions.md note
    flagged ("if concurrent-write races on this column become a real problem
    later ... once C41's ingestion orchestrator can run"): two learn_channel
    runs (or a learn + an identity-editing chat op sharing the same stage)
    for the same tenant now genuinely serialize instead of racing the
    fetch-then-write in channel_dna_meta.stamp_identity_write.

    Stores the claim row with ``video_id = NULL`` and enforces uniqueness via
    the ``(tenant_id, stage) WHERE video_id IS NULL`` partial index
    (migration 104) — a DIFFERENT index than the per-video acquire() uses, so
    this never contends with (or is blocked by) any video-scoped claim.
    Mirrors acquire()'s exact discipline otherwise: TOCTOU-free per-tenant
    advisory transaction lock, a 2h stale sweep, fail-CLOSED (returns False)
    on any DB error.
    """
    try:
        pool = await database.get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await drain_mode.assert_accepting_conn(conn)
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtext($1)::bigint)",
                    f"{tenant_id}:channel:{stage}",
                )
                await conn.execute(
                    "DELETE FROM generation_claims WHERE tenant_id = $1 AND video_id IS NULL "
                    "AND stage = $2 AND claimed_at < now() - interval '2 hours'",
                    tenant_id, stage,
                )
                row = await conn.fetchrow(
                    "INSERT INTO generation_claims (tenant_id, video_id, stage, claimed_by) "
                    "VALUES ($1, NULL, $2, $3) "
                    "ON CONFLICT (tenant_id, stage) WHERE video_id IS NULL DO NOTHING "
                    "RETURNING stage",
                    tenant_id, stage, claimed_by,
                )
                return row is not None
    except drain_mode.DrainModeActive:
        raise
    except Exception:
        logger.exception(
            "[generation_claims] acquire_channel failed tenant=%s stage=%s — "
            "DENYING the claim (fail-closed: a DB error must never open the "
            "double-spend/double-write window)", tenant_id, stage,
        )
        return False


async def release_channel(tenant_id: str, stage: str = "dna") -> None:
    """Best-effort release for a channel-level claim taken by
    acquire_channel() — never raises, same fail-soft contract as release():
    a failed DELETE just leaves the row for the next acquire_channel()'s
    stale sweep (>2h) to clear."""
    try:
        pool = await database.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM generation_claims WHERE tenant_id = $1 AND video_id IS NULL AND stage = $2",
                tenant_id, stage,
            )
    except Exception:
        logger.warning(
            "[generation_claims] release_channel failed tenant=%s stage=%s — "
            "row will self-clear via the 2h stale sweep on the next acquire_channel",
            tenant_id, stage, exc_info=True,
        )


async def is_blocked(tenant_id: str, video_id: str, stage: str) -> bool:
    """Read-only check used by routes/pipeline.py's ``_is_task_active`` so
    the DB is consulted as the authority alongside the in-process dict fast
    path. Ignores stale (>2h) rows without sweeping them — a plain read must
    not mutate state; a genuinely stale claim is swept the next time
    anything calls ``acquire()`` for this video. Fails CLOSED (returns True
    -> caller treats the lane as busy) on any DB error, matching
    ``acquire()``'s fail-closed rule.
    """
    try:
        pool = await database.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT stage FROM generation_claims WHERE tenant_id = $1 AND video_id = $2 "
                "AND claimed_at > now() - interval '2 hours'",
                tenant_id, video_id,
            )
            active = {r["stage"] for r in rows}
            return _blocked(stage, active)
    except Exception:
        logger.exception(
            "[generation_claims] is_blocked check failed tenant=%s video=%s "
            "stage=%s — treating the lane as BUSY (fail-closed)",
            tenant_id, video_id, stage,
        )
        return True
