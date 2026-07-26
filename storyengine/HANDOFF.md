# HANDOFF - 2026-07-25 - Director Phase 1 built and verified; still nothing deployed

## State
- Prod: **nothing deployed this session.** Prod is unchanged from where the last session left it.
- Branch: `feat/director-chat`, clean. Merged `origin/main` at `a13ec7c3` (drift was 35/9; one
  conflict in `tasks/loop-handoff.md`, resolved by taking main's version since another session
  owns that file). `npx tsc --noEmit` exits 0, `npm run build` clean at 34 routes.
- Untracked and intentionally uncommitted: `tasks/director-mockup/`, `storyengine/.claude/`,
  `tasks/ref-dryrun-2026-07-21.txt`, `frontend/next-env.d.ts` (generated).

**Phase 1 of DIRECTOR-CHAT-PLAN.md is COMPLETE.** A reviewer who never saw the build walked the
running app and graded all 7 acceptance criteria PASS. Ten commits:

- `458fba73` Director context, surface shell, canvas empty state
- `b5925e83` ChatCore reports and receives the current video (9 lines, isolated)
- `f1e29d0f` Read-only `GET /api/custom-film/recipes`
- `32bab748` Director home and Style Library
- `8cd98a13` Canvas header, five-tab rail, gold "Lock this as a style"
- `23674f51` Serve the Director surface at `/` and `/chat`
- `9d210181` Pin the undocked chat composer (2 lines, isolated)
- `da3c1dfe` Keep the canvas header usable below desktop width
- `a55b9781`, `5b30053f` Checklist, deferred checks, follow-ups

## DO NOT DEPLOY - the concurrent Codex session's paid job status is still unconfirmed
That session had roughly $8.52 spent and held mid-flight. `se deploy` restarts uvicorn and KILLS
in-flight builds. **Ask Ryan whether that job finished before any deploy.** Same file ownership
still applies: `backend/custom_film_*.py`, `frontend/src/lib/custom-film-approval-truth.ts`,
`tasks/loop-checklist.md`, `tasks/loop-handoff.md`, `SYSTEM_STATE.md`. `ChatCore.tsx` is shared -
this session's two edits are small and already committed separately.

## Next action (start here cold)
**Deploy Phase 1, but only after Ryan confirms the Codex job is done.** Two checks in
`tasks/DIRECTOR-CHAT-DEFERRED.md` can only close after a deploy, and both are cheap:
1. `curl -s -H "Authorization: Bearer $(cat /tmp/se_token)" http://76.13.119.181:8001/api/custom-film/recipes`
   must return 200 with `{"recipes": []}`.
2. Load `/` signed in. The saved-styles card must show the gold "You haven't saved a style yet"
   empty state and "0 saved", NOT the red error box it correctly shows today.

If deploying is still blocked, start Phase 2 of `DIRECTOR-CHAT-PLAN.md` instead (the Board/Scene
altitude and the cost dial), and read `tasks/DIRECTOR-CHAT-CHECKLIST.md` first - its
"Known follow-ups after Phase 1" section lists six items with file paths.

## Open threads
- **Right rail is unreachable below the `lg` breakpoint.** Stacked layout has no scroll chain.
  `app/page.tsx` + `app/chat/page.tsx` wrap the surface in `fixed inset-0`, and `RightRail.tsx` is
  a flat `w-[340px] flex-none`. The mockup is desktop-only by design so this was never in Phase 1
  scope, but it bites the first phone user. Highest-value follow-up.
- **Backend still serves internal channel code names.** `GET /api/production-styles` returns
  "Bilingual Character Animation" etc. The frontend maps them to Ryan's approved labels in
  `CHANNEL_CARDS` in `DirectorHome.tsx`. That is a stopgap; fix at the source.
- **Ryan owes (carried from 2026-07-23):** re-roll s113/s114/s122 in the UI ($0.27) and re-render
  scene 1 (free), then regrade vs his C-. Pre-check before animating more: `se db "SELECT
  image_index, motion_gate_status FROM assets WHERE video_id='f00ea79a-06bd-407a-a467-2f014f184744'
  AND scene=1 AND (video_prompt IS NULL OR motion_gate_status='blocked')"` must return 0 rows.
- **SFX may never reach rendered video** - `sound_effect_url` appears to be read only by the legacy
  Remotion path, not render_stitch or render_perform. A background session was spawned; check it.
- **Transparency reversal owed:** plan Phase 5.3 exposes model + price inside Custom Film, which
  reverses a tested invariant. Update the asserting tests in their own commit; never delete one.
- Recipes REST route is now DONE (was an open API gap). Still open: no select-variant endpoint on
  `routes/assets.py`.
- Picture-QA vision pass still NOT built. Carried: budget cap has no UI; est-cost formula misses
  script/storyboard spend; `_run_static_script_hold` writes no ledger row; token/password rotations.

## Gotchas learned this session
- **Subagents can silently build in a different git worktree than intended.** Two chunks wrote into
  `.claude/worktrees/gifted-hopper-a9c28d` instead of the main checkout. Their reports were accurate;
  the files just were not where the rest of the work was. Caught only on fan-in, when a commit job
  found the files missing. Every brief must state the ABSOLUTE working directory and make the worker
  verify the branch before writing. Verify against the destination tree, never the report alone.
- **TanStack Query v5 has a state where `isLoading` and `isError` are both false**
  (`status:"pending", fetchStatus:"paused"`). Branching on those shortcuts made an API failure render
  as an empty state, which lies to the user. Branch on `status` and `fetchStatus` directly.
- **`position: fixed` in a child can be scoped from the parent** by giving the parent a transform,
  which makes it a containing block. Fixes layout escape without editing a shared file. But it also
  traps every other fixed overlay that child renders - check for those before shipping it.
- **Verify Director work against a production build, not `npm run dev`.** React Strict Mode's
  double-invoke wedges the home-chat spinner in dev only. Use `npm run build && npx next start -p 3001`.
- The approved mockup OVERRODE the written plan in three places (altitude tabs are
  `Shot | Scene | Timeline` not `Board | Shot | Timeline`; five rail tabs not four; no "last used"
  field). When a mockup and a plan disagree, the thing Ryan clicked and approved wins.
