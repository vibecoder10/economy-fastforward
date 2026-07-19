"""Durable pass identity for `draft_pass`/`finalize` — chunk C17 (checklist
§1.3 "Draft cheap, finish expensive", S7 design requirements in
docs/reports/2026-07-17-storyengine-agent-audit-findings.md §S7).

Problem this solves, distinct from generation_claims.py: the claim table
(migration 092) guards CONCURRENT double-dispatch (two requests racing at
the same instant) — it is acquired at dispatch and released the moment the
background run ends, so it says nothing about a SEQUENTIAL repeat: the same
"finalize" request arriving again after the first run already completed and
released its claim. The S7 design requirement calls for a job key of
``(video_id, stage, pass, scene_set_hash)`` specifically so that request can
be told apart from a legitimate SECOND finalize (more scenes approved since,
or the routing changed) — "a bare (stage, video_id) key would wrongly dedup
a legitimate second finalize."

``scene_set_hash`` is the (scene, target_model_id) pairs for the pass,
hashed — NOT just the scene numbers — because a routing change (a manual
model_override edit between two finalize calls) on an otherwise-identical
scene set must also count as a new, legitimate pass, not a duplicate.

Design: a row is written to ``generation_passes`` ONLY on successful
completion (never before dispatch, unlike generation_claims) — a failed run
must always be retryable with the identical scene set, so nothing is
recorded for it. The concurrency case (two requests for the identical pass
racing each other) is NOT this module's job: generation_claims' "main" lane
claim already serializes that (only one of the two can even start), so by
the time either would reach ``mark_done`` here, they're no longer racing.
This module answers exactly one question — "has this EXACT pass already
been completed?" — and answers it fail-OPEN (False / "not done yet") on any
DB error, deliberately the opposite of generation_claims' fail-CLOSED rule:
a lookup hiccup here must never permanently block a legitimate pass (worst
case is one avoidable repeat, not a wedge); generation_claims already owns
preventing the concurrent double-spend that would actually cost money.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Iterable

import database

logger = logging.getLogger(__name__)


def scene_set_hash(pairs: Iterable[tuple[int, str]]) -> str:
    """Deterministic identity for a pass: sorts (scene, target_model_id)
    pairs before hashing, so caller-side ordering never matters — the SAME
    approved-scene set at the SAME target models always yields the SAME
    hash (same key -> dedup), while a LARGER/different set or a routing
    change yields a DIFFERENT hash (new key -> a legitimate new pass)."""
    ordered = sorted((int(scene), str(model_id)) for scene, model_id in pairs)
    raw = "|".join(f"{scene}:{model_id}" for scene, model_id in ordered)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


async def already_done(tenant_id, video_id, pass_name: str, scene_hash: str) -> bool:
    """True only if this EXACT (video, pass, scene_set_hash) has already
    completed successfully. Fails OPEN (False) on any DB error — see module
    docstring for why that's the right direction here."""
    try:
        pool = await database.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM generation_passes WHERE tenant_id = $1 AND video_id = $2 "
                "AND pass = $3 AND scene_set_hash = $4",
                tenant_id, video_id, pass_name, scene_hash,
            )
            return row is not None
    except Exception:
        logger.exception(
            "[generation_passes] already_done check failed tenant=%s video=%s pass=%s — "
            "treating as NOT done (fail-open: a lookup error must never permanently "
            "block a legitimate pass; generation_claims already prevents the concurrent "
            "double-spend case)", tenant_id, video_id, pass_name,
        )
        return False


async def mark_done(tenant_id, video_id, pass_name: str, scene_hash: str) -> None:
    """Record a pass as completed. Best-effort (never raises) — same
    fail-soft rationale as generation_claims.release(): a failed write here
    just means a future identical repeat isn't recognized as a duplicate,
    never that money is double-spent (the claim already prevented that for
    the run that just finished)."""
    try:
        pool = await database.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO generation_passes (tenant_id, video_id, pass, scene_set_hash) "
                "VALUES ($1, $2, $3, $4) "
                "ON CONFLICT (tenant_id, video_id, pass, scene_set_hash) DO NOTHING",
                tenant_id, video_id, pass_name, scene_hash,
            )
    except Exception:
        logger.warning(
            "[generation_passes] mark_done failed tenant=%s video=%s pass=%s — "
            "a future identical repeat may not be caught as a duplicate",
            tenant_id, video_id, pass_name, exc_info=True,
        )
