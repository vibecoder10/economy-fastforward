# Loop: per-card parallel clip/image generation on the pipeline page

Goal: let Ryan click Run / Re-run on individual clip cards and fire SEVERAL at
once so they generate in PARALLEL, instead of being blocked one-at-a-time by the
video-level task lock. Scope (Ryan, 2026-07-23): clips AND per-card image redraw;
instant per-card Run (no select-mode); no per-click cost gate, live cost counter.

## Key recon facts (why this is smaller than "add buttons")
- Per-asset animate endpoint ALREADY exists: POST /api/pipeline/clip/{video_id}
  ?asset_id=&force=  (routes/pipeline.py:1691). Card tap already animates one clip;
  hover redo already re-runs with force=true (ScenesWorkspaceTab.tsx:2010/2474).
- Clip gen is ALREADY concurrent within one run: asyncio.gather over
  Semaphore(CLIP_CONCURRENCY, default 6) (pipeline_executor.py:12701/13151).
- THE BLOCKER: video-level 409 lock — routes/pipeline.py:1727 _is_task_active,
  backed by generation_claims keyed (tenant, video, lane). Two runs on one video
  can't overlap -> feels serial. No per-asset lock; per-card state inferred from
  assets.video_clip_url (present=done).
- Frontend: SegmentCard in components/production/ScenesWorkspaceTab.tsx:2268;
  refresh = 3s task poll (use-task-poller.ts) -> invalidate ["video-assets"].
  In-flight tracked in client Sets generatingClipIds/failedClipIds
  (use-clip-trust-ladder.ts:46). No multi-select pattern exists.

## Chosen approach (Fable): batch, don't unlock
Clicked cards coalesce into ONE run_clip_generation scoped to that SET of asset
ids, reusing the existing 6-wide fan-out + the "animate the rest" auto-resume
loop. Keeps the global cost/rate cap; never double-animates an asset; full-scene
/full-video builds stay mutually exclusive. Do NOT rework the lock per-asset.

## Definition of Complete (grade against THIS)
0. PRIMARY FLOW (Ryan, confirmed): edit the prompts on several cards, hit Re-run on each, and ALL the changed cards regenerate in parallel — for BOTH clip re-runs AND image re-draws. The current one-at-a-time behavior (video 409 lock) is gone.
1. Each clip card has Run (animate from image) + Re-run (force) that starts THAT clip on click.
2. Clicking Run on several cards runs them in parallel (up to CLIP_CONCURRENCY); extra clicks queue and start as slots free — no 409, no one-at-a-time wall.
3. Same instant-parallel behavior for regenerating a card's still image (redraw).
4. A live cost counter shows spend accumulating as clips/images finish; the per-video budget cap still backstops.
5. Manual runs never double-animate an asset and never collide with / corrupt a full-scene or full-video build.
6. Proven by clicking multiple cards on the running app — parallel execution + counter shown in screenshots.

## Chunks
- [x] C1 (S) [B][V] — Backend multi-asset manual clip run. DONE @ commit 0917d67e on
      feat/per-car-parallel-clips. asset_ids param (id = ANY($3::uuid[])); new
      clip_manual lane (mutually exclusive with full "main" builds, ref-counted, but
      never self-blocks); in-process per-asset claim (clip_asset_claims.py) prevents
      double-animate. 28 new tests, stash-proof 17/19, suite 14-fail baseline
      unchanged +28 pass. SAFETY: sound ONLY under single-process deploy — VERIFIED
      prod runs one uvicorn worker (no --workers). CAVEAT: if scaled to N workers,
      move the asset claim to the generation_claims cross-process table. redraw-image
      NOT extended here (no fan-out infra) -> C1b.
- [x] C1b (S) [B][V] — Backend PARALLEL image redraw. DONE @ commit 196dd7cb on
      feat/per-card-parallel-clips. redraw-image now accepts asset_ids (id =
      ANY($3::uuid[])); new redraw_manual lane (mirrors clip_manual, ref-counted,
      never self-blocks); sibling in-process per-asset claim (redraw_asset_claims.py)
      prevents double-draw; new redraw_asset_images() fans out under IMAGE_CONCURRENCY
      (default 6) via asyncio.gather. Singular asset_id path preserved byte-for-byte
      (claim-guarded passthrough, equality-tested). 33 new tests; stash-proof 14/16
      lane (+2 deliberate regression-locks) + 2 new files error at collection when
      reverted; suite 14-fail baseline unchanged, +33 pass, 0 regressions. SAFETY:
      in-process claim safe ONLY single-process (documented SYSTEM_STATE.md §C1b +
      deferred-verification.md §C1b) — if scaled to N workers, move to generation_claims.
      Live proof (real Kie spend, concurrent-curl 409, ledger no-dup) deferred to C4.
- [x] C2 (S) [U][V] — Frontend instant-parallel per-card Run/Re-run for CLIPS.
      DONE @ commit cb60df16 on feat/per-car-parallel-clips. animateOne now queues
      into pendingClipRef Map + 500ms debounce (cap 2000ms) -> ONE call with
      asset_ids for 2+, singular asset_id for 1. Removed the if(running) gate;
      in-flight tracked via a live ref (fixed a stale-closure bug). queuedClipIds ->
      "Queued…" overlay. Partial-failure reconcile: onComplete refetches + marks
      still-clipless batch ids failed. tsc clean + next build OK (34 routes). No
      jest/vitest in repo -> documented trace (see deferred-verification.md). Live
      proof = C4. Backend asset-claim (C1) is the double-spend safety net regardless
      of FE behavior.
- [ ] C3 (S) [U][V] — Frontend: same instant-parallel treatment for per-card image
      redraw + a live cost counter on the page (video.total_cost / ledger delta,
      updates on each completion).
- [ ] C4 (V, S Explore) — E2E: se devtoken + local dev vs prod API, drive UI:
      click 4-5 clip cards + 1-2 redraws, prove parallel run + cost counter climbs +
      no double-run + full-build exclusion; screenshots. THEN gated prod deploy —
      STRATEGIC (LIVE USERS as of 2026-07-23): se deploy restarts uvicorn and KILLS
      in-flight user builds. Before deploying: (1) check for active user builds via
      `se db` (in-progress/generating videos) and deploy ONLY in a quiet window with
      none in flight; (2) honor ~/deploy.lock; (3) Ryan watches; (4) one /se-smoke
      pass after. Also clear all deferred-verification.md items (incl. C1b live proof).
      Prod lock + live users = high blast radius.

Notes / lessons: (append as we learn)
