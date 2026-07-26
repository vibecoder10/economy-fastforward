# HANDOFF - 2026-07-26 - feat/director-chat merged with origin/main, VERIFIED locally; still nothing deployed

## Last done (evidence-dense)
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

## KNOWN OPEN ITEM
`GET /api/custom-film/recipes` exists only on this branch and has never been deployed, so it
404s on current prod. Merging this branch (done locally now) is what fixes that - it still needs
an actual `se deploy` to take effect in prod, which this chunk deliberately did not do.

## Next chunk
1. Get Ryan's go-ahead, then `se deploy` this merged branch (frontend + backend) through the
   normal drain-aware path. Do NOT deploy during any in-flight paid generation - check
   `se health`'s `active_work` first.
2. After deploy, re-run the two checks in `tasks/DIRECTOR-CHAT-DEFERRED.md` item 1 (the
   `/api/custom-film/recipes` 200 + empty-state UI check) - they were blocked pending this merge.
3. Optional cleanup (not required for deploy): the 4 font-asset-caused failures in
   `test_custom_film_remotion.py` could be fixed by adding the missing local `.woff2` font file(s)
   to the sandbox/CI environment so those Remotion contract tests can actually run - low priority,
   pre-existing on origin/main, not introduced by Director's work.
4. A separate cleanup chunk (not this one) still owns removing stale worktrees/branches - this
   chunk left `storyengine/.claude/` (stale nested worktree) and the backup branch
   `backup/feat-director-chat-pre-mainmerge-20260726` untouched, as instructed.

## Verification commands (for a cold re-check)
```
cd ~/economy-fastforward/storyengine/backend && ./venv/bin/python -m pytest tests/ -q
cd ~/economy-fastforward/storyengine/frontend && npx tsc --noEmit && npm run build
```
