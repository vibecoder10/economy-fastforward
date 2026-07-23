"""In-process per-ASSET claim guard for concurrent picture redraws.

Chunk C1b (feat/per-card-parallel-clips, backend enabler for parallel image
redraw) — the image-redraw sibling of ``clip_asset_claims.py`` (chunk C1's
same guard for clips). Several manual redraws of ``scripts.coverage_to_app.
redraw_asset_image`` may now be in flight on the SAME video at once.
``routes/pipeline.py`` routes a targeted redraw run (one or several cards)
through a new "redraw_manual" lane that — like "clip_manual" before it —
deliberately does NOT block a second call to ITSELF: several manual redraws
must be able to regenerate different (or overlapping) cards on the same
video AT THE SAME TIME instead of queueing one-at-a-time behind the old
video-level 409.

That video-level lane relaxation alone cannot stop two OVERLAPPING redraw
runs from both picking up the SAME asset id — e.g. two per-card Redraw
clicks racing on cards {A, B} and {B, C}. Two runs redrawing the same row
at once would double the paid GPT Image 2 / nano-banana-2 / z-image spend
for that one picture AND race the final ``UPDATE assets SET image_url = ...,
video_clip_url = NULL`` write, so whichever call's write lands SECOND
silently clobbers the first (and re-nulls a clip the first call's redraw
may already have re-animated against). That double-spend/clobber is the
actual risk this module exists to close; the lane rule above only decides
who's ALLOWED to try, this module decides who actually gets to spend money
redrawing which row.

Deliberately a SEPARATE module/namespace from ``clip_asset_claims.py``,
not a shared one keyed by a "kind" prefix: a clip claim and a redraw claim
answer different questions (is this asset mid-ANIMATION vs. mid-REDRAW) and
must never accidentally cross-block each other — an asset that's already
animating its clip is not "busy" from a redraw's point of view (and vice
versa; a redraw in flight doesn't stop a *different* manual clip run from
targeting that same asset id, though in practice the UI wouldn't offer
both at once on an already-queued card). Keeping them in separate
module-level dicts makes that non-interaction true by construction instead
of by convention inside one shared dict — see tasks/deferred-verification.md
(C1b section) for the same call made explicit as a design decision, not an
oversight.

Design, and why it's safe without a lock — identical reasoning to
``clip_asset_claims.py`` (see that module's docstring for the fuller
explanation); repeated here briefly since this module has no other reader
dependency on it:

- A plain in-process ``dict[(tenant_id, video_id) -> dict[asset_id -> claimed_at]]``.
  ``claim()`` is a single synchronous function — no ``await`` inside it —
  so within one Python process asyncio's cooperative scheduling makes the
  whole "read the held set, decide who wins, write the winners back" body
  atomic.
- ``claim(ids)`` returns only the subset of ``ids`` NOT already held.
- ``release(ids)`` is idempotent and safe to call with ids never claimed.
- A claim older than ``STALE_SECONDS`` (10 minutes — same figure
  ``clip_asset_claims.STALE_SECONDS`` and ``routes/pipeline.py``'s own
  ``_STALE_TASK_SECONDS`` use, for the same "a killed worker must never
  wedge things forever" reason) is swept and silently retaken.

Deliberately in-process only, NOT a DB table like ``generation_claims.py``:
same tradeoff ``clip_asset_claims.py`` makes — these claims are held for
the seconds a single redraw call takes, scoped to exactly the assets one
call is redrawing right now, with no restart-survival requirement. If
StoryEngine ever runs more than one API process without a shared cache,
this in-process set — like ``clip_asset_claims.py`` and the rest of
``routes/pipeline.py``'s existing ``_running_tasks``/``_side_lanes``
guards — would need to move to Redis/DB; see
``tasks/deferred-verification.md`` (C1b section).
"""
from __future__ import annotations

import time
from typing import Iterable, List

# Matches clip_asset_claims.STALE_SECONDS / routes/pipeline.py's
# _STALE_TASK_SECONDS — a claim this old is treated as abandoned (crashed
# worker, killed process, an exception between claim() and the caller's own
# finally-release) and is silently swept + retaken rather than wedging the
# asset closed forever.
STALE_SECONDS = 600

# (tenant_id, video_id) -> {asset_id: claimed_at_epoch_seconds}
# Deliberately a SEPARATE dict from clip_asset_claims._claimed — a clip
# claim and a redraw claim on the same asset id must never collide (see
# module docstring).
_claimed: dict[tuple[str, str], dict[str, float]] = {}


def _sweep_stale(held: dict) -> None:
    now = time.time()
    for aid, claimed_at in list(held.items()):
        if now - claimed_at > STALE_SECONDS:
            held.pop(aid, None)


def claim(tenant_id: str, video_id: str, asset_ids: Iterable[str]) -> List[str]:
    """Claim every id in ``asset_ids`` not already held for this
    (tenant, video). Returns exactly the subset this call WON — the caller
    must only redraw those; anything else is already being redrawn
    elsewhere and must be skipped."""
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
    row's own redraw finishes) and again at the batch level as a backstop."""
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
    ones swept first). Mirrors clip_asset_claims.claimed_ids — used by
    tests to assert every claim was released once a run finishes."""
    key = (tenant_id, video_id)
    held = _claimed.get(key)
    if not held:
        return set()
    _sweep_stale(held)
    return set(held.keys())
