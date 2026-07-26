# HANDOFF - 2026-07-26 (evening) - unified baseline LIVE in prod, verified in browser

## Last done (evidence-dense)
**Chunk scope:** land the merged local baseline on `main` and deploy it to prod, then verify like
a real user. Ryan pre-approved the prod deploy.

1. **main unified with feat/director-chat.** Local `main` was stale (diverged 2/109 vs
   `origin/main`) — backed up to branch `main-before-reset-backup`, then hard-reset to
   `origin/main` (`cd7b7d80`), then merged `feat/director-chat` in. The merge was a clean
   **fast-forward** (feat/director-chat already contained origin/main, so no conflicts, no manual
   resolution needed) landing at `28afc1f4`. Pushed: `git push origin main` ->
   `cd7b7d80..28afc1f4  main -> main`. **main is now the single source of truth, in sync with
   feat/director-chat's tip.**

2. **Pre-deploy health gate (`se health`):** clear. `active_work: {background_tasks: 0,
   generation_claims: 0, total: 0}`, no deploy lock, drain mode normal. Safe to deploy.

3. **Deployed:** `se deploy osiris-director-chat-unify --with-frontend`. Drain enabled, no active
   work to wait on, `git pull --ff-only` -> `cd7b7d80 -> 28afc1f4`, migrations
   `total=147 applied=147 pending=0` (no new migrations needed — confirms 133-138 were already
   applied as expected), backend restarted and healthy, worker restarted with matching code parity,
   frontend rebuilt (`next build --webpack`, 34 routes) and restarted, HTTP 200. Drain returned to
   normal automatically. Post-deploy `se health`: backend + frontend active, api healthy, deploy
   lock clear, last deploy line shows `cd7b7d80 -> 28afc1f4 --with-frontend`.

4. **Verified live in a browser as a real user** (storyengine.dev, signed in via a real JWT for
   the owner tenant):
   - `GET /api/custom-film/recipes` -> **200** `{"recipes":[]}` (both direct curl to the backend
     and observed live through the frontend's own network calls). This was 404 before this deploy
     — confirmed fixed.
   - Director surface at `/`: "Your saved styles" shows "0 saved", gold dashed card "You haven't
     saved a style yet", no red error box.
   - **Codex's Scene Control still works post-merge** — the highest-risk regression this deploy
     could have caused. `/scene-control/17454567-0605-4249-8598-482b4240243e` renders fully:
     Film Foundations (story throughline, dialogue ownership, visual grammar, recurring cast,
     recurring environment, technique boundaries, all LOCKED/Approved), Scene 1 with 5 shots,
     shot inspection detail. No 500, no blank screen, no console errors. Network log confirms
     `GET .../scene-control` -> 200.
   - Opened a real (empty) video's Director canvas ("Below the Forecast"). Altitude control
     (Shot/Scene/Timeline) and right rail (Media/Voice/Music/Cast/Environments) all switch state
     correctly with clean empty-state copy, no console errors. One UX note: the Timeline altitude
     view renders a static illustrative mockup of clips/narration/music explicitly labeled "New —
     doesn't exist in the product yet" — honestly labeled, but worth a real design pass so a user
     can't mistake it for live data.
   - **Not clicked (zero spend authorized):** Build/"Finish the video" ($0.25 cost chip present),
     redraw, animate, render. See `tasks/DIRECTOR-CHAT-DEFERRED.md` items 3-4 for what's still open.

## Prior chunk (local merge, not yet deployed at the time)
**Chunk scope:** get `feat/director-chat` to a clean, merged, verified local baseline against
`origin/main` (which carries Codex's Custom Film "Scene Control" work, PRs #521/#522/#523,
migrations 135-138, live in prod behind `CUSTOM_FILM_SCENE_CONTROL_V1=true`). Local work only -
no push, no deploy, no VPS, no migrations applied, no money spent.

1. **Committed loose work already in the tree** (commit `78feecd7`):
   - `tasks/DIRECTOR-CHAT-DEFERRED.md` - a prior agent's notes on its aborted 2026-07-26 merge
     attempt (it hit the same two conflicts this chunk resolved, and stopped without resolving them).
   - `tasks/director-mockup/index.html` - the approved Director UI mockup, referenced by name in
     code comments in `StyleLibrary.tsx`.
   - Left untracked on purpose (per instruction): `tasks/ref-dryrun-2026-07-21.txt` (unrelated
     scratch from a different task) and `storyengine/.claude/` (a stale nested worktree).

2. **Merged `origin/main` (tip `cd7b7d80`) into `feat/director-chat`** (merge commit `5ec15e7c`).
   Exactly the two conflicts `git merge-tree` predicted, both mechanical "keep both sides":
   - `backend/main.py`: both branches added a router import + `app.include_router(...)` line.
     Kept BOTH - Director's `custom_film` router (unconditional, prefix `/api/custom-film`) AND
     Codex's `custom_film_scene_control` router (flag-gated on `CUSTOM_FILM_SCENE_CONTROL_V1`,
     prefix `/api/custom-film/{video_id}/scene-control`). Confirmed by reading the resolved file:
     both modules imported in the same `from routes import (...)` block, both registered, Codex's
     env-flag gate preserved exactly as it was on main.
   - `tasks/deferred-verification.md`: both branches had appended different sections at the same
     point. Kept both in full (Director's Phase 0 section + Codex's M9 Scene Control section).
   - Confirmed after merge: migrations 133-138 all present in `backend/migrations/`;
     `routes/custom_film.py` and `routes/custom_film_scene_control.py` both exist.

3. **Backend tests** (`./venv/bin/python -m pytest tests/ -q`, Python 3.11 venv):
   - **Post-merge: 43 failed, 3359 passed, 1 error** (93s).
   - **Pre-merge baseline** (`3ae64c98`, same suite, same venv, via a throwaway worktree):
     **39 failed, 3092 passed, 1 error** (69s). The stale "~16 failures" note in project memory
     is NOT the current baseline - this run supersedes it.
   - Diffed failure name lists exactly: **0 fixed, 4 new** (`comm -13/-23` on sorted FAILED/ERROR
     lines). All 4 new failures are in `tests/functional/test_custom_film_remotion.py`:
     `test_exact_legacy_renderer_bundle_is_accepted_centrally_and_preserved[...]` (x2 params),
     `test_unknown_legacy_bundle_is_rejected_by_every_identity_gate`,
     `test_source_clip_dialogue_captions_allow_silent_visual_gaps`.
   - **Root-caused, not just observed:** these 4 test functions do not exist at all in the
     pre-merge branch's `test_custom_film_remotion.py` (`grep -n` for the function names returns
     nothing) - they were added by origin/main's own commits. Ran them in isolation against a
     clean `origin/main`-only worktree (no merge involved): **same 4 tests fail there too**, same
     error every time - `custom_film_contract.CustomFilmContractError: Custom Film Remotion local
     font assets are missing` (a missing local `.woff2` file, a sandbox/environment gap, not a
     logic defect). **Conclusion: the merge introduced zero new failures of its own** - it just
     inherited 4 pre-existing origin/main failures caused by a missing local asset. Not fixed here
     (out of this chunk's scope - it's an environment setup gap on origin/main, unrelated to the
     Director/Codex merge, and not "clearly mechanical" within this branch).
   - The pre-existing `test_validator_error_parsing.py::test_api_key` ERROR is identical
     pre- and post-merge (same 1 error both runs).

4. **Frontend typecheck**: `npx tsc --noEmit` - clean, 0 errors.

5. **Frontend build**: `npm run build` (`next build --webpack`) - clean, compiled successfully,
   34 routes generated, including `/scene-control/[videoId]` (Codex's new route, confirmed present
   in the build output) alongside all of Director's existing routes.

6. Merge commit created locally (`5ec15e7c`). **Not pushed. Not deployed. No migration applied.**

## KNOWN OPEN ITEM (RESOLVED 2026-07-26 evening — see top of file)
`GET /api/custom-film/recipes` used to exist only on the branch and 404 on prod. Fixed by the
deploy documented at the top of this file: confirmed live 200 on prod.

## Next chunk
1. **Spend gate:** `tasks/DIRECTOR-CHAT-DEFERRED.md` items 3-4 are still open — the Build/Finish
   button end to end (needs an actual paid click, get Ryan's go-ahead + cost quote first) and a
   populated Scene altitude view (needs a real video with drawn scenes, compare against
   `tasks/director-mockup/index.html`).
2. **Design follow-up (low priority, not blocking):** the Timeline altitude view's placeholder
   mockup is honestly labeled "New — doesn't exist in the product yet" but still worth a real
   pass so it can't be mistaken for live data.
3. Optional cleanup (not required for deploy): the 4 font-asset-caused failures in
   `test_custom_film_remotion.py` could be fixed by adding the missing local `.woff2` font file(s)
   to the sandbox/CI environment so those Remotion contract tests can actually run - low priority,
   pre-existing on origin/main, not introduced by Director's work.
4. A separate cleanup chunk still owns removing stale worktrees/branches - `storyengine/.claude/`
   (stale nested worktree), and now two backup branches: `backup/feat-director-chat-pre-mainmerge-20260726`
   and `main-before-reset-backup` (the old, now-superseded local `main` tip, kept only as a safety
   net from tonight's reset — safe to delete once nobody needs it).

## Verification commands (for a cold re-check)
```
cd ~/economy-fastforward/storyengine/backend && ./venv/bin/python -m pytest tests/ -q
cd ~/economy-fastforward/storyengine/frontend && npx tsc --noEmit && npm run build
```
