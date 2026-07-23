# Deferred verification — reference-lookup fix

- [ ] Deploy: code fix reaches prod only after Ryan runs `scripts/se.sh deploy` (push to
      main does NOT restart the backend). Recipe: `se deploy` from the Mac, then
      `se health`. Cross-ref: checklist C3.
- [ ] Post-deploy live proof: re-run `images(fc73860c-a9af-444f-95a5-7f86d60503e0, scene=8)`
      (XB-35, ~$0.03, quote→confirm) and visually verify the render is a FLYING WING.
      Expected: image-to-image from a real XB-35 photo; asset prompt carries "[ref: ...]".
- [ ] Fail-closed proof on prod: attempt images for a machine with no reference anywhere
      (or temporarily empty cache row) → scene must persist status='blocked_no_reference'
      and NO image generated / no spend.

# Deferred verification — C1 per-card parallel clips (feat/per-card-parallel-clips)

Backend enabler chunk: POST /api/pipeline/clip/{video_id} accepts a SET of asset ids
(`asset_ids`, comma-separated or repeated) and runs them concurrently via the existing
CLIP_CONCURRENCY fan-out, without 409-blocking other manual per-card runs. Full detail,
the exact concurrency mechanism, and unit/functional test proof are in the branch's
commit message and PR description — this file only tracks what CANNOT be proven in the
sandbox (no live DB, no live Kie/Grok API, no prod).

- [ ] **Live multi-card proof (real spend, ~$0.05-0.15 for 2-3 short clips).** After
      `se deploy`: open a video with 3+ un-clipped final pictures in the Scenes tab, tap
      Run/Re-run on 2-3 different cards in quick succession (this chunk is BACKEND only —
      the UI doesn't fire multiple requests yet; use curl or the browser devtools network
      tab to fire 2-3 concurrent `POST /api/pipeline/clip/{video_id}?asset_id=<id>`
      requests, one per id, back to back). Expected: NONE of the 2nd/3rd requests return
      409; all requested cards end up with a video_clip_url; `se db "SELECT id, video_id,
      created_at FROM generation_ledger WHERE video_id='<id>' AND stage='clip' ORDER BY
      created_at DESC LIMIT 10"` shows exactly one ledger row per animated asset (no
      duplicates = no double-spend).
      Recipe (replace VIDEO/TOKEN/ASSET_A/ASSET_B):
      ```
      TOKEN=$(cat /tmp/se_token)
      curl -s -X POST "https://storyengine.dev/api/pipeline/clip/VIDEO?asset_id=ASSET_A" \
        -H "Authorization: Bearer $TOKEN" &
      curl -s -X POST "https://storyengine.dev/api/pipeline/clip/VIDEO?asset_id=ASSET_B" \
        -H "Authorization: Bearer $TOKEN" &
      wait
      ```
      Neither call should return `{"detail":"Task already running"}`.
- [ ] **Full-build-vs-manual-run live proof.** While a manual card tap (above) is still
      animating, try "Animate this scene" or the full "Animate" button on the SAME video
      in the UI → must 409 ("Task already running"), proving a full build still waits for
      an in-flight manual run rather than racing it (the "clip_manual blocks/blocked-by
      main" half of the lane rule — see routes/pipeline.py's `_is_task_active`
      "clip_manual" branch and `_manual_clip_begin`/`_manual_clip_finish`).
- [ ] **Cross-process gap (not new to this chunk, just newly relevant):** the
      `clip_manual` lane and the `clip_asset_claims` per-asset guard are BOTH in-process
      only (module-level Python dicts), same as the pre-existing `_running_tasks`/
      `_side_lanes` dicts they extend. If StoryEngine ever runs more than one API server
      process/pod without a shared cache (Redis, or a `generation_claims`-style DB table),
      two manual clip requests landing on DIFFERENT processes would not see each other's
      claims and could both animate the same asset. Today's deploy is single-process
      (`se deploy` kills+revives one uvicorn), so this is inert — flag if that ever
      changes. If it does, the fix is the same pattern `generation_claims.py` already
      uses (a DB-backed advisory-lock claim) applied per-asset instead of per-stage.
- [ ] **C3 note — image redraw fan-out (requirement 5, deliberately NOT built here):**
      `POST /api/pipeline/redraw-image/{video_id}?asset_id=` (routes/pipeline.py, calls
      `scripts.coverage_to_app.redraw_asset_image`) takes exactly ONE required `asset_id`
      today — no candidate SQL, no semaphore fan-out, no `asyncio.gather`, unlike the clip
      route. Extending it to a set is a real feature (new fan-out + its own concurrency/
      claim story for image regeneration, likely wanting the SAME clip_asset_claims-style
      per-asset guard, or a sibling `redraw_asset_claims`), not a trivial copy of this
      chunk's pattern — left for chunk C3 rather than rabbit-holed here.
- [ ] **UI status-pill accuracy during overlapping manual runs (cosmetic, not a spend/
      safety issue):** `routes/pipeline.py`'s `_running_tasks` dict is one slot per
      (tenant, video) — when 2+ manual clip runs overlap, whichever run's `_set_task_status`
      write landed last "owns" the status-poll pill, and `_clear_task_status`'s lane check
      means an earlier-finishing run's cleanup can blank the pill while a later run is
      still animating. The underlying spend/clobber safety (clip_asset_claims) is unaffected
      — this only affects what the polling UI displays mid-run. Worth a look when the
      frontend chunk (fires several manual requests) lands, if the UI needs a truthful
      "N of M cards animating" indicator rather than one shared pill.
      **C2 note:** the frontend chunk below deliberately sidesteps this for its OWN
      dispatches — it coalesces into one call and never fires a second overlapping call
      from the same tab (queues instead, see below) — but the pill-multiplexing risk
      above still applies if a SECOND tab or an agent fires a manual run at the same time.
      Flagged again in C2's own list below.

# Deferred verification — C2 frontend per-card coalescing (feat/per-card-parallel-clips)

Frontend chunk: `frontend/src/hooks/use-clip-trust-ladder.ts` (`animateOne`,
`dispatchPendingClips`, `pendingClipRef`, `queuedClipIds`) + the SegmentCard wiring in
`frontend/src/components/production/ScenesWorkspaceTab.tsx`. Per-card Run/Re-run now
queues into a Map, debounces ~500ms (capped at 2000ms of continuous clicking), and fires
ONE `POST /api/pipeline/clip/{video_id}?asset_ids=a,b,c` (or the original singular
`asset_id=` for a lone click) instead of blocking a second click while the first is in
flight. `npx tsc --noEmit` and `npm run build` both pass clean (see PR/commit for output).
No live backend, DB, or paid API was reachable in this sandbox — everything below needs a
real browser against a real video.

**What IS verified — a documented code trace (no test framework installed; see note at
bottom on why one wasn't added):**

- *N clicks → one call.* `animateOne` (use-clip-trust-ladder.ts ~176-194) never dials the
  network itself — it only mutates `pendingClipRef` (a plain `Map<id, force>`) and
  (re)arms `clipFlushTimerRef` via `setTimeout(..., CLIP_BATCH_DEBOUNCE_MS)`. Every
  additional click inside that window clears and re-arms the SAME timer
  (`if (clipFlushTimerRef.current) clearTimeout(...)`), so only the LAST click's timer
  ever fires. When it does, `dispatchPendingClips` (~149-170) drains the whole Map in one
  shot: `Array.from(pendingClipRef.current.entries())`, builds one `params` object —
  `asset_ids: ids.join(",")` for 2+, plain `asset_id: ids[0]` for exactly one — and makes
  exactly one `startClipTask` → `runPipelineStage` → one `fetch` call. Clicking 3 cards
  180ms apart produces 1 network call with 3 ids; clicking 1 card produces 1 call with the
  original singular shape.
- *queued → running → done/failed.* `queuedClipIds` (state, mirrors `pendingClipRef`'s
  keys) is set the instant a card is clicked (~180) and cleared the instant a batch is
  actually dispatched (~159, inside `dispatchPendingClips`, BEFORE the network call) —
  so a card is "queued" from click until dispatch, then `generatingClipIds` takes over
  (set inside `startClipTask` right before `runPipelineStage`, ~127) — so "running" from
  dispatch until the shared task-status poll reports completed/failed. SegmentCard
  (ScenesWorkspaceTab.tsx ~2018-2049) renders `isQueued` (Clock icon, dimmed picture, no
  spinner) strictly before `isGenerating` (spinner) strictly before `isFailed` (red "Try
  again") — the three are mutually exclusive by construction (dispatchPendingClips clears
  queued before generatingClipIds is set; onFailed/the C2 reconciliation below only ever
  add to failedClipIds AFTER generatingClipIds is cleared).
- *Never blocked.* The old `if (running) { toast.info(...); return; }` gate that lived at
  the top of `startClipTask` is GONE from the per-card path — `animateOne` has no `running`
  check at all now; only `dispatchPendingClips` checks `runningRef.current`, and if true it
  just leaves the batch queued (no toast, no error) for the running→idle effect (~237-252)
  to retry. `animateScene`/`animateAll` are untouched and still show that toast (by design
  — out of scope, see the C2 task brief).
- *Follow-up batch on free.* The running→idle `useEffect` (~237-252) now has two branches:
  resume-loop (unchanged, "Animate the rest") OR, if that's not active,
  `pendingClipRef.current.size > 0` → `dispatchPendingClips()`. So clicking cards WHILE a
  build is running (or while a previous per-card batch is still in flight) queues them
  silently and they fire the instant the task-status poll observes the slot go idle.
- *Stale-closure fix (found during self-review, fixed before commit):* `startClipTask`'s
  own busy-check originally read the closed-over `running` state, which would have been
  the value from the render that scheduled the `setTimeout`, not "now" — the debounce
  callback fires outside React's render cycle. Fixed by reading `runningRef.current`
  (updated synchronously every render) in both `dispatchPendingClips` and `startClipTask`,
  so the two checks can never disagree. Left as an inline comment at both call sites.

**What is NOT verified (needs a live browser + real video + prod deploy — do NOT deploy
from this chunk):**

- [ ] **Coalescing, visually, in the real UI.** Recipe: `se deploy` this branch's frontend
      (after C2 is merged/reviewed — this chunk does not deploy), open a video with 3+
      un-clipped final pictures in the Scenes tab, open Chrome DevTools → Network, tap
      Run on card A then Re-run/Run on cards B and C within ~1s. Expected: exactly ONE
      `POST /api/pipeline/clip/{video_id}?asset_ids=<A>,<B>,<C>` (or `&force=true` if any
      of B/C already had a clip) — NOT three separate requests. Each of A/B/C should show
      the Clock "Queued…" overlay for well under a second, then the spinner, then either
      the clip or (if it genuinely fails) the red "Try again" overlay.
- [ ] **Partial-failure reconciliation, live.** Force one card in a multi-card batch to
      fail (e.g. a motion-gate-blocked shot with no video_prompt mixed into the same
      click-batch as a normal card) and confirm the failing card gets the red "Try again"
      overlay even though the OTHER card(s) in the same batch succeeded — this is the new
      `onComplete` reconciliation in ScenesWorkspaceTab.tsx (fetches fresh assets after a
      batch completes, marks any id from that batch still missing `video_clip_url` as
      failed) since a mixed-result batch reports overall `status: "completed"` from the
      backend (`pipeline_executor.run_clip_generation`: "completed" whenever `done > 0`,
      never per-asset). Watch for a Network tab GET to `/api/assets` (or whatever
      `getVideoAssets` hits) firing right after the batch's terminal poll.
- [ ] **"Animate this scene" / "Animate the rest" still work unchanged.** Both were left
      untouched code-wise (still call `startClipTask` directly, still toast+block on
      `running`) — confirm this in the live UI: tap "Animate this scene" while nothing else
      is running (should proceed immediately, unchanged), then tap it again immediately
      after tapping a per-card Run elsewhere (should show the existing "Hang on — still
      working" toast, unchanged behavior, since scene/all deliberately were NOT moved onto
      the queue).
- [ ] **Cross-tab / cross-agent overlap.** This chunk only serializes ITS OWN dispatches
      (one call in flight per browser tab at a time — see the transition-effect retry
      above). If a SECOND tab, or an agent via the MCP `animate` tool, fires a manual clip
      run on the same video while this tab has one in flight, the shared single-slot
      task-status pill (flagged in C1's own deferred list above) can still show a
      misleading "done" while the other tab's run is still going. Not a spend/safety bug
      (clip_asset_claims still protects against double-animating an asset) — just a
      cosmetic multiplexing gap C1 already flagged and C2 doesn't fix. Worth a real
      two-tabs-on-one-video test in C4 if that's a workflow anyone actually uses.
- [ ] **Debounce/max-wait timing feel.** CLIP_BATCH_DEBOUNCE_MS=500,
      CLIP_BATCH_MAX_WAIT_MS=2000 (use-clip-trust-ladder.ts) are reasoned defaults, not
      user-tested — confirm 500ms feels responsive (not laggy) for a single-card tap
      (worst case: one click waits 500ms before its own spinner appears, vs. instant
      before C2) and that editing+re-running several cards in a realistic pace (a few
      seconds apart while reading/typing) still coalesces as intended rather than firing
      one request per card.
- [ ] **No test framework installed.** `frontend/package.json` has no jest/vitest/RTL —
      "test" is Playwright (e2e only, needs a live server). Adding one is a real dependency
      change (blocked by the "ask before installing packages" rule this session runs
      under) so C2 shipped a documented trace instead of a unit test, per the C2 brief's
      explicit "test OR trace" option. If a unit-test harness is ever added to this repo,
      `dispatchPendingClips`/`animateOne`'s debounce-and-coalesce logic (pure, ref-driven,
      no DOM) would be a clean first candidate to cover.

# Deferred verification — C1b backend parallel image redraw (feat/per-card-parallel-clips)

Backend enabler chunk, the image-redraw sibling of C1: POST /api/pipeline/redraw-image/
{video_id} now accepts a SET of asset ids (`asset_ids`, comma-separated or repeated,
alongside the pre-existing `asset_id`) and runs them concurrently via a new
IMAGE_CONCURRENCY fan-out (`scripts/coverage_to_app.py::redraw_asset_images`), guarded by
a new `redraw_asset_claims.py` per-asset claim (sibling of C1's `clip_asset_claims.py`) and
a new "redraw_manual" lane (sibling of C1's "clip_manual") in routes/pipeline.py's
`_is_task_active`. This resolves the C3 note C1 left in this file (§"image redraw fan-out,
requirement 5, deliberately NOT built here") — built as its own chunk (C1b) rather than the
originally-numbered C3, since the parent loop resequenced it. Full detail, the exact
concurrency mechanism, and unit/functional test proof are in the branch's commit message
and SYSTEM_STATE.md's §C1b entry — this file only tracks what CANNOT be proven in the
sandbox (no live DB, no live Kie image-gen API, no prod).

- [ ] **Live multi-card proof (real spend, ~$0.10-0.15 for 2-3 GPT Image 2 redraws at the
      2K tier, $0.05 each).** After `se deploy`: open a video with 3+ drawn pictures in the
      Scenes tab, tap Redraw on 2-3 different cards in quick succession (this chunk is
      BACKEND only — the UI doesn't fire multiple requests yet; use curl or the browser
      devtools network tab to fire 2-3 concurrent
      `POST /api/pipeline/redraw-image/{video_id}?asset_id=<id>` requests, one per id, back
      to back). Expected: NONE of the 2nd/3rd requests return 409; all requested cards end
      up with a fresh image_url (and video_clip_url cleared); `se db "SELECT id, video_id,
      created_at FROM generation_ledger WHERE video_id='<id>' AND stage='image' ORDER BY
      created_at DESC LIMIT 10"` shows exactly one ledger row per redrawn asset (no
      duplicates = no double-spend).
      Recipe (replace VIDEO/TOKEN/ASSET_A/ASSET_B):
      ```
      TOKEN=$(cat /tmp/se_token)
      curl -s -X POST "https://storyengine.dev/api/pipeline/redraw-image/VIDEO?asset_id=ASSET_A" \
        -H "Authorization: Bearer $TOKEN" &
      curl -s -X POST "https://storyengine.dev/api/pipeline/redraw-image/VIDEO?asset_id=ASSET_B" \
        -H "Authorization: Bearer $TOKEN" &
      wait
      ```
      Neither call should return `{"detail":"Task already running"}`. Also try the NEW
      multi-id shape in one call: `POST .../redraw-image/VIDEO?asset_ids=ASSET_A,ASSET_B`
      and confirm both redraw and the ledger still shows exactly 2 rows (not 1 shared row,
      not 0).
- [ ] **Full-build-vs-manual-redraw live proof.** While a manual redraw (above) is still
      in flight, try "Redo Scene N's pictures" or any full-scene/full-video build on the
      SAME video in the UI → must 409 ("Task already running"), proving a full build still
      waits for an in-flight manual redraw rather than racing it (the "redraw_manual
      blocks/blocked-by main" half of the lane rule — see routes/pipeline.py's
      `_is_task_active` "redraw_manual" branch and `_manual_redraw_begin`/
      `_manual_redraw_finish`).
- [ ] **Clip run vs. redraw run independence, live.** With a manual clip animate (C1) in
      flight on a video, fire a manual redraw on the SAME video (a DIFFERENT asset) →
      must NOT 409 (the two lanes are independent — see SYSTEM_STATE.md §C1b). Then the
      reverse: redraw in flight, fire a clip animate → must also not 409.
- [ ] **Cross-process gap (inherited from C1, not new to this chunk):** the
      `redraw_manual` lane and the `redraw_asset_claims` per-asset guard are BOTH
      in-process only (module-level Python dicts), same limitation as C1's `clip_manual`/
      `clip_asset_claims`. If StoryEngine ever runs more than one API server process/pod
      without a shared cache (Redis, or a `generation_claims`-style DB table), two manual
      redraw requests landing on DIFFERENT processes would not see each other's claims and
      could both redraw the same asset. Today's deploy is single-process (`se deploy`
      kills+revives one uvicorn), so this is inert — flag if that ever changes. If it does,
      the fix is the same pattern `generation_claims.py` already uses (a DB-backed
      advisory-lock claim) applied per-asset instead of per-stage — same fix C1's own note
      already calls for on the clip side; if this is ever done, do BOTH claim modules at
      once rather than fixing one and leaving the other stale.
- [ ] **Message-text edge case (known, deliberate, low-risk):** a redraw for an
      asset_id that doesn't exist under this (video_id, tenant_id) now returns
      `{"status": "failed", "error": "picture not found"}` for a single id via
      `redraw_asset_images`' own candidate-scoping check, same literal string the old
      direct call produced — but a MULTI-id request where every id is bogus returns the
      new generic `"no matching pictures found for the requested ids"` instead (there is
      no pre-C1b precedent for that shape, since a multi-id redraw request didn't exist
      before). Never reachable from the current UI (which only ever sends a real
      `asset_id` for one card); worth a glance if C3 (frontend) ever surfaces a raw error
      string to the user for this path.
- [ ] **UI status-pill accuracy during overlapping manual redraws (cosmetic, not a spend/
      safety issue) — same pre-existing gap C1 flagged for clips:** `routes/pipeline.py`'s
      `_running_tasks` dict is one slot per (tenant, video) — when 2+ manual redraw runs
      overlap, whichever run's `_set_task_status` write landed last "owns" the status-poll
      pill. The underlying spend/clobber safety (`redraw_asset_claims`) is unaffected —
      this only affects what the polling UI displays mid-run. Same note as C1's own list;
      worth a look together when a frontend chunk for redraw coalescing (this chunk's C2
      counterpart) is built.
