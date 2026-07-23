GOAL: per-card parallel clip + image generation on the pipeline page. Primary
flow (Ryan): edit prompts on several cards, hit Re-run on each, all changed ones
fire in PARALLEL — clips AND images. Full plan + Definition of Complete in
tasks/loop-checklist.md. Repo ~/economy-fastforward/storyengine.

BRANCH: feat/per-card-parallel-clips (main untouched). HEAD = 196dd7cb.
  - C1 @ 0917d67e — backend multi-asset manual CLIP run (asset_ids, clip_manual
    lane, in-process per-asset claim). SAFE only single-process; prod verified 1
    uvicorn worker. CAVEAT: if scaled to N workers, move claim to generation_claims.
  - C2 @ cb60df16 — frontend clip coalescing (debounced batch, queued state).
  - C1b @ 196dd7cb — backend PARALLEL image redraw (asset_ids fan-out under
    IMAGE_CONCURRENCY, redraw_manual lane, redraw_asset_claims per-asset guard,
    singular path preserved). 33 tests, stash-proof + suite clean. Same
    single-process caveat as C1. Live proof deferred to C4.

DONE: C1, C2, C1b.  NEXT: C3.

- [ ] C3 (S)[U] — frontend: same instant-parallel coalescing for per-card image
  redraw (mirror C2's animateOne/debounce/queued pattern in use-clip-trust-ladder.ts,
  now POSTing asset_ids to redraw-image) + a LIVE COST COUNTER on the page
  (video.total_cost / ledger delta, updates per completion).
- [ ] C4 (V, Explore) — E2E drive-through + GATED, STRATEGIC deploy. LIVE USERS now
  (2026-07-23): se deploy restarts uvicorn and KILLS in-flight user builds. Before
  deploy: check `se db` for active/in-progress user builds, deploy ONLY in a quiet
  window, honor ~/deploy.lock, Ryan watches, then one /se-smoke. Open pipeline video
  f00ea79a-06bd-407a-a467-2f014f184744 (PocoAPoco), click 4-5 clip cards + 1-2 image
  re-draws, PROVE: one batched asset_ids call in Network tab, parallel execution, cost
  counter climbs, no double-run, full-build stays 409-exclusive. Screenshots. Clear
  deferred-verification.md items.

RESUME: invoke maestro, read this file, take C3. Write a self-contained C3 brief
(the C1b backend contract is live: POST /api/pipeline/redraw-image/{video_id}
?asset_ids=a,b,c comma-separated, singular ?asset_id= still works). Judge on
stash-proof + suite-vs-baseline. NOTHING deploys until C4 + a quiet window + Ryan's
eyes (live users). deferred-verification.md has the live recipes.
