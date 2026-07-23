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
