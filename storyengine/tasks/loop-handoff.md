Last done: Application-level drain mode is complete and live at runtime revision 9784f39c; manual and automatic no-spend production proofs both passed, with normal mode restored and no deploy lock or active work.
Next chunk: none for this mission; future production deploys should use `se deploy <session> [--with-frontend]`, with `se drain-status` and `se undrain` available for diagnosis/recovery.
GOAL: per-card parallel clip + image generation on the pipeline page. Primary
flow (Ryan): edit prompts on several cards, hit Re-run on each, all changed ones
fire in PARALLEL — clips AND images. Full plan + Definition of Complete in
tasks/loop-checklist.md. Repo ~/economy-fastforward/storyengine.

BRANCH: feat/per-car-parallel-clips (main untouched). HEAD = 7dc6f00c.
  - C1 @ 0917d67e — backend multi-asset manual CLIP run (asset_ids, clip_manual lane).
  - C1b @ 196dd7cb — backend PARALLEL image redraw (asset_ids, redraw_manual lane,
    redraw_asset_claims). Both C1/C1b in-process claims SAFE only single-process.
  - C2 @ cb60df16 — frontend CLIP coalescing (debounced batch, queued state).
  - C3 @ 7dc6f00c — frontend IMAGE-redraw coalescing (mirrors C2) + live cost counter
    (reused CostLedgerChip/video.total_cost, no backend gap). Cross-track (clip vs
    redraw) serialized on the FE by design; backend allows them to overlap.

ALL BUILD CHUNKS DONE: C1, C1b, C2, C3 — verified in-sandbox (tsc/build/tests +
stash-proofs), committed to the branch, NOT deployed.

NEXT: C4 — Ryan-gated. Two parts, both need Ryan:
  1. STRATEGIC DEPLOY (live users 2026-07-23): se deploy restarts uvicorn and KILLS
     in-flight user builds. Check `se db` for active/in-progress user builds, deploy
     ONLY in a quiet window, honor ~/deploy.lock, Ryan watches, then one /se-smoke.
     Backend (C1/C1b) must deploy for the asset_ids paths to exist on prod.
  2. PAID LIVE PROOF (~$0.05-0.20 real Kie spend, quote+confirm first): open pipeline
     video f00ea79a-06bd-407a-a467-2f014f184744 (PocoAPoco), click 4-5 clip cards +
     1-2 image re-draws, PROVE via Network tab: ONE batched asset_ids call per track,
     parallel execution, cost counter climbs, no double-run, full-build stays
     409-exclusive. Screenshots. Then clear all deferred-verification.md items.

OPEN DECISION for Ryan: cross-track serialization. Backend permits a clip batch and
a redraw batch to run simultaneously on one video (each _is_task_active lane blocks
only on "main"); C3's FE serializes the two tracks (fires clip wave, then redraw
wave) to avoid the single status-pill slot collision. Within each track = fully
parallel. Realistic workflow (redraw image THEN animate) rarely mixes both at once.
If Ryan wants clip+image cards firing in ONE interleaved wave -> small C3b to relax
the FE dispatchInFlightRef gate. Default: keep as-is.

RESUME: invoke maestro, read this file. C4 is Ryan-gated (deploy timing + money) —
do NOT auto-deploy or fire paid live runs; surface the deploy window + cost to Ryan
and wait for his go. deferred-verification.md has the exact live recipes.
