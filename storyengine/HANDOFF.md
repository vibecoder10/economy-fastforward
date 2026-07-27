# HANDOFF - 2026-07-26 Consolidated Director UI + Codex Custom Film into one baseline

## Superseded

This handoff describes the state BEFORE the D2 board/cost-dial mission and the D3 chat-fix mission. The current source of truth is the `## Active mission - D3 DIRECTOR CHAT IS THE PRODUCT` section at the top of `tasks/loop-checklist.md`.

## State
- Prod: a181a7cf deployed, healthy (deployed via `se deploy ... --with-frontend`)
- Branch: main @ a181a7cf - clean (one intentional untracked file: storyengine/tasks/ref-dryrun-2026-07-21.txt)
- What shipped this session:
  - Merged Codex's Custom Film Scene Control (origin/main cd7b7d80, PRs #521-523, migrations 135-138) with the Director UI branch (feat/director-chat, 22 unique commits) into one baseline on main. Two shallow conflicts (backend/main.py, tasks/deferred-verification.md), both resolved keep-both.
  - Deployed cd7b7d80 -> 28afc1f4 via `se deploy osiris-director-chat-unify --with-frontend`. Verified in a browser.
  - GET /api/custom-film/recipes now returns 200 {"recipes":[]} in prod (it 404'd before - the route existed only on the unmerged branch).
  - Codex's Scene Control verified still working post-merge: GET /api/custom-film/{video_id}/scene-control returns real data (film locks approved, synthetic:false).
  - Rescued 3 pieces of stranded work, all now pushed to origin: fix/videodetail-aspect-ratio (b3ed4857), preserve/custom-film-continuation-script (5f2a8d42, a 656-line untracked operator script), fix/youtube-granular-quota (8f103527, already remote).
  - Cleaned up: deleted 3 dead branches, removed 6 stale worktrees incl. one nested inside the tracked tree, pruned 4 dead worktree records.
  - Test baseline re-measured: 43 failed / 3364 passed / 1 error (re-measure before trusting; a newer session reported 3370 passed). Pre-merge was 39/3092/1. The 4-delta is inherited from origin/main, not a regression.

## Next action (start here cold)
Build Phase 2 of the Director surface (Board + Cost Dial). Plan file is /Users/ryanayler/economy-fastforward/storyengine/DIRECTOR-CHAT-PLAN.md (repo root, NOT under tasks/).

CRITICAL correction to that plan: the cost dial must NOT toggle `assets.hero_shot`. That column has zero effect on price or model routing (verified: shared/model_router.py never reads it; it only affects render_static.py picture priority and render_perform.py dialogue ordering). The dial must write `assets.model_override` via the existing PATCH /api/assets/{asset_id}/model-override route (backend/routes/assets.py). Prices come from getVideoActions().prices (keyed by model id) and getModels() - never hardcode.

Also: do NOT create a new BoardAltitude.tsx. frontend/src/components/director/SceneAltitudeView.tsx already IS the board - upgrade it in place (swap its local ShotTile for canvas-shared/ShotCard.tsx, add model/cost badge, add default-collapse past scene 3 which is not implemented).

## Open threads
- Remotion font gap - 28 tests in backend/tests/.../test_custom_film_remotion.py cannot run at all: @fontsource/noto-sans is declared in remotion-video/package.json but not installed in remotion-video/node_modules. Try `npm install` in remotion-video/. Pre-existing, not caused by the merge, but that coverage gives zero signal today.
- Build / "Finish the video" button never exercised end to end - costs money, zero spend was authorized this session.
- Scene altitude never seen populated - the test video (17454567-0605-4249-8598-482b4240243e) has 0 scenes/0 shots. Needs a real video with drawn scenes.
- Branch agent/custom-film-director-loop holds 19 unique lines of Codex test work (a test rename in test_custom_film_scene_control.py + 6 lines in a seed script) NOT on main. Parked - decide whether to land it.
- Timeline altitude is a static mockup with fake colored blocks, honestly labeled but a user could misread it as real data. Needs a design pass.
- Codex session is stopped. Ryan is working through the Director UI from here.
