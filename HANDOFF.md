# HANDOFF - 2026-07-27 Director Phase 2 Board and Cost Dial built

## State
- Prod: 28afc1f4 deployed and healthy
- Branch: `claude/vibrant-franklin-502811` at commit 1d562afe (NOT merged to main)
- Work completed: Director Phase 2 Tasks 2.1 (Director Board) and 2.2 (Cost Dial)
  - Board: `SceneAltitudeView.tsx` upgraded in place, swapped local `ShotTile` for `canvas-shared/ShotCard.tsx`, scenes past #3 collapse by default, no new BoardAltitude.tsx created
  - Cost Dial: new `CostDial.tsx` with three live totals, one-click per-shot model override, three bulk actions with cost deltas and confirm dialogs
  - Both locally verified in browser with real data and screenshots, reload-persistence checked, zero paid generation triggered
  - Backend 43 failed / 3364 passed / 1 error (vs 43/3359/1 baseline), +5 new Cost Dial tests, zero regressions

## Next action (start here cold)
Director Phase 2 Tasks 2.3 (Asset Rail) and 2.4 (canvas follows the pipeline) are the natural next chunk. Ryan chose on 2026-07-26 to HOLD the deploy and see this running locally first. Do not deploy without asking him again.

The three open items you'll encounter: (1) `POST /api/assets/batch-model-override` is new backend code NOT deployed - the bulk action buttons 404 until deploy; (2) the left chat column shows a spinner that never resolves - pre-existing; (3) 32 Drive-proxied video posters take up to 15s to fill in, making the board look broken on first paint - pre-existing shared media-proxy behaviour.

## Open threads
- Remotion font gap (resolved-but-blocked): `npm install` in `remotion-video/` installed `@fontsource/noto-sans` and cleared the missing-font error at `custom_film_remotion.py:526`, but the same 28 tests now fail one line later at `:532` with `CustomFilmContractError: Custom Film Remotion renderer implementation is incomplete` - a renderer-bundle integrity check, not a dependency problem. Needs its own chunk.
- Branch `agent/custom-film-director-loop` still holds 19 unique lines of Codex test work (test rename + 6 lines in seed script) NOT on main - parked, decide whether to land it.
