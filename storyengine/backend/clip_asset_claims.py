"""In-process per-ASSET claim guard for concurrent clip generation.

Chunk C1 (feat/per-card-parallel-clips, backend enabler): several manual
runs of ``pipeline_executor.run_clip_generation`` may now be in flight on
the SAME video at once. ``routes/pipeline.py`` routes a targeted per-card/
multi-card run through a new "clip_manual" lane that — unlike every other
lane in ``_is_task_active`` — deliberately does NOT block a second call to
ITSELF (that's the whole point of the feature: several clip cards animate
in parallel instead of one at a time behind a video-level 409).

That video-level lane relaxation alone cannot stop two OVERLAPPING runs
from both picking up the SAME asset id — e.g. two per-card clicks racing
on cards {A, B} and {B, C}, or a manual click racing a scene/full-video
build that hasn't finished yet. Two runs animating the same row at once
would double the paid Grok/Veo/Seedance spend for that one shot AND race
the final ``UPDATE assets SET video_clip_url = ...`` write, so whichever
call's write lands SECOND silently clobbers the first — even if the first
was the better take. That double-spend/clobber is the actual risk this
module exists to close; the lane rule above only decides who's ALLOWED to
try, this module decides who actually gets to spend money on which row.

Design, and why it's safe without a lock:

- A plain in-process ``dict[(tenant_id, video_id) -> dict[asset_id -> claimed_at]]``.
  ``claim()`` is a single synchronous function — no ``await`` inside it —
  so within one Python process asyncio's cooperative scheduling makes the
  whole "read the held set, decide who wins, write the winners back" body
  atomic: nothing else can run between those steps and race it. Every
  caller in this codebase (``run_clip_generation``) calls ``claim()`` once
  per batch, synchronously, right before it starts any paid work — never
  after an ``await``.
- ``claim(ids)`` returns only the subset of ``ids`` NOT already held —
  those are the only ones the caller may animate. Anything left out is
  already being animated by another in-flight run; the caller must skip
  it, never process it a second time.
- ``release(ids)`` is idempotent and safe to call with ids that were never
  claimed (no-op for those) — so a belt-and-suspenders release from more
  than one place (per-row, AND a batch-level cleanup) can never double-free
  or raise.
- A claim older than ``STALE_SECONDS`` (10 minutes — matches
  ``routes/pipeline.py``'s own ``_STALE_TASK_SECONDS`` for the same
  "a killed worker must never wedge things forever" reason) is swept and
  silently retaken on the next ``claim()`` call. This is the self-heal
  net for the one gap synchronous code can't close on its own: an
  exception between ``claim()`` and the eventual ``release()`` (a crash,
  a killed worker, a bug) would otherwise wedge that asset closed until
  the process restarts. Every real caller still releases explicitly in a
  ``finally`` — this sweep is insurance, not the primary mechanism.

Deliberately in-process only, NOT a DB table like ``generation_claims.py``:
these claims are held for the seconds-to-minutes one clip generation call
takes, scoped to exactly the assets one call is animating right now — there
is no restart-survival requirement (unlike the whole-STAGE claims
``generation_claims.py`` protects, which can span a long-running whole-video
build and must survive a deploy). If StoryEngine ever runs more than one
API process without a shared cache, this in-process set — like the rest of
``routes/pipeline.py``'s existing ``_running_tasks``/``_side_lanes``
guards — would need to move to Redis/DB; see
``tasks/deferred-verification.md``.
"""
from __future__ import annotations

import time
from typing import Iterable, List

# Matches routes/pipeline.py's _STALE_TASK_SECONDS — a claim this old is
# treated as abandoned (crashed worker, killed process, an exception
# between claim() and the caller's own finally-release) and is silently
# swept + retaken rather than wedging the asset closed forever.
STALE_SECONDS = 600

# (tenant_id, video_id) -> {asset_id: claimed_at_epoch_seconds}
_claimed: dict[tuple[str, str], dict[str, float]] = {}


def _sweep_stale(held: dict) -> None:
    now = time.time()
    for aid, claimed_at in list(held.items()):
        if now - claimed_at > STALE_SECONDS:
            held.pop(aid, None)


def claim(tenant_id: str, video_id: str, asset_ids: Iterable[str]) -> List[str]:
    """Claim every id in ``asset_ids`` not already held for this
    (tenant, video). Returns exactly the subset this call WON — the caller
    must only animate those; anything else is already in flight elsewhere
    and must be skipped."""
    key = (tenant_id, video_id)
    held = _claimed.setdefault(key, {})
    _sweep_stale(held)
    now = time.time()
    won = [a for a in asset_ids if a not in held]
    for a in won:
        held[a] = now
    return won


def release(tenant_id: str, video_id: str, asset_ids: Iterable[str]) -> None:
    """Best-effort, idempotent release. Safe to call more than once, and
    safe to call with ids this caller never actually won (no-op for
    those) — every real call site releases both per-row (as soon as that
    row's own work finishes) and again at the batch level as a backstop."""
    key = (tenant_id, video_id)
    held = _claimed.get(key)
    if not held:
        return
    for a in asset_ids:
        held.pop(a, None)
    if not held:
        _claimed.pop(key, None)


def claimed_ids(tenant_id: str, video_id: str) -> set:
    """Read-only snapshot of ids currently claimed for this video (stale
    ones swept first). Not used by the current callers, but is the hook a
    future full-video/scene candidate query could filter through if it
    ever needs to skip an asset a manual run already has in flight instead
    of relying on the video-level lane block — see the module docstring
    and tasks/deferred-verification.md."""
    key = (tenant_id, video_id)
    held = _claimed.get(key)
    if not held:
        return set()
    _sweep_stale(held)
    return set(held.keys())
