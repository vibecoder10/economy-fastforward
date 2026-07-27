# HANDOFF - 2026-07-27 Director Phase 2 Board, Cost Dial, and Workspace Layout

## State
- Prod: 28afc1f4 deployed and healthy
- Branch: `claude/vibrant-franklin-502811` at commit 719c4d61 (NOT merged to main, NOT deployed)
- Work completed: Director Phase 2 Tasks 2.1 (Director Board), 2.2 (Cost Dial), plus three follow-on workspace layout changes Ryan requested on 2026-07-27
  - Board: `SceneAltitudeView.tsx` upgraded in place, swapped local `ShotTile` for `canvas-shared/ShotCard.tsx`, scenes past #3 collapse by default, zero paid generation
  - Cost Dial: new `CostDial.tsx` with three live totals, one-click per-shot model override, three bulk actions with cost deltas and confirm dialogs
  - Layout follow-ons: sidebar restored on Director routes, sidebar collapse now reclaims width, resizable and hideable Director columns with drag and keyboard controls
  - All verified locally with real data and screenshots, reload-persistence checked, Ryan personally tested the resizable columns on 2026-07-27 and confirmed both dragging and collapse work
  - Backend 43 failed / 3364 passed / 1 error (vs 43/3359/1 baseline), +5 new Cost Dial tests, zero regressions

## Next action (start here cold)
Director Phase 2 Tasks 2.3 (Asset Rail) and 2.4 (canvas follows the pipeline) are the natural next chunk. Ryan is holding the deploy deliberately and reviewing locally. Do not deploy without asking him again.

Open items you'll encounter: (1) `POST /api/assets/batch-model-override` is new backend code NOT deployed, so the bulk buttons 404 against prod API; (2) left chat column spinner never resolves, pre-existing; (3) shot-card price badges clip when sidebar expanded and canvas near floor (resolves if you collapse sidebar or widen canvas).

## Open threads
- Remotion font gap (resolved-but-blocked): `npm install` in `remotion-video/` installed `@fontsource/noto-sans` and cleared the missing-font error at `custom_film_remotion.py:526`, but the same 28 tests now fail one line later at `:532` with `CustomFilmContractError: Custom Film Remotion renderer implementation is incomplete` - needs its own chunk.
- Branch `agent/custom-film-director-loop` still holds 19 unique lines of Codex test work NOT on main - parked.
