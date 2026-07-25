# HANDOFF - 2026-07-24 - Director Chat Phase 0 shipped and verified (not deployed)

## State
- Prod: unchanged, nothing deployed this session. All work is local on branch `feat/director-chat`.
- Branch: `feat/director-chat`, 5 commits off `main`@f7eaab1a. Build clean (0 errors, 0 warnings,
  34 routes), `npx tsc --noEmit` exits 0.
- **Phase 0 of DIRECTOR-CHAT-PLAN.md is COMPLETE and independently verified.** Tailwind v4 `@theme`
  tokens in `frontend/src/app/globals.css` (additive, +43/-0); shared components harvested out of
  `ScenesWorkspaceTab.tsx` into `frontend/src/components/canvas-shared/`; `frontend/src/hooks/
  use-video-refresh.ts` created and adopted by nobody. Evidence in `tasks/DIRECTOR-CHAT-CHECKLIST.md`.
- **Local `main` is 3 commits behind `origin/main`** - PR #474 "Run approved Custom Films through
  final assembly" landed after this branch was cut. Fetch and merge before Phase 1.
- Custom Film remains under active development by another session. Phase 0 touched none of it;
  Phase 5.3 of the plan is the first chunk that will.

## Next action (start here cold)
Phase 1 of `~/economy-fastforward/storyengine/DIRECTOR-CHAT-PLAN.md` - "Shell and Style Library"
(Director context + surface layout, chat on the left, Style Library home showing saved recipes plus
the four presets, canvas header with cost pill). Ryan has NOT yet approved starting Phase 1 - ask first.

Before starting: `git checkout main && git pull --no-rebase && git checkout feat/director-chat &&
git merge main` to pick up the 3 new origin commits.

## Open threads
- **Ryan owes (carried from 2026-07-23, still open):** re-roll s113/s114/s122 in the UI
  ($0.27) and re-render scene 1 (free), then regrade vs his C-. Pre-check before animating
  more: `se db "SELECT image_index, motion_gate_status FROM assets WHERE
  video_id='f00ea79a-06bd-407a-a467-2f014f184744' AND scene=1 AND (video_prompt IS NULL OR
  motion_gate_status='blocked')"` must return 0 rows. If the regrade passes: scenes 2-3 via
  Generate all storyboards.
- **SFX may never reach rendered video** - `sound_effect_url` appears to be read only by the
  legacy Remotion path, not by render_stitch or render_perform. If true, creators pay
  ElevenLabs for audio that never lands. A background session was spawned to verify; check it.
- **Transparency reversal owed:** plan Phase 5.3 exposes model + price inside Custom Film,
  which reverses a tested invariant. Update the asserting tests in their own commit; never
  delete one to make a screen work.
- Two unresolved API gaps found while planning, both filed inside the plan: no select-variant
  endpoint on `routes/assets.py`, and recipes may be chat-command-only with no REST route.
- Picture-QA vision pass: still NOT built. Pre-spend audits remain text-only.
- Carried: budget cap has no UI; est-cost formula misses script/storyboard spend;
  `_run_static_script_hold` writes no ledger row; token/password rotations owed.

## Gotchas learned this session
- **Check branch drift before researching anything.** `git rev-list --left-right --count
  main...HEAD`. This session surveyed a checkout 90 commits stale and produced a plan whose
  line numbers were wrong by up to 393 lines - one instruction would have sliced a component
  in half. Fix: cite symbol names, never line numbers. Saved to memory.
- A subagent verifying that cited *symbols* still exist is a weak check - it misses everything
  that was *added* next to them. Ask reviewers to check the target branch for new work too.
- `git worktree add --detach <path> main` is the cheap way to give survey agents a clean read
  of a branch without disturbing the working checkout.
- HANDOFF.md was uncommitted here, so "overwrite it, git has history" was false. Read before
  overwriting; the 2026-07-23 content was carried forward above, backup in session scratchpad.
- The plan's own instructions can be stale even when freshly written. Task 0.2 told the worker to
  rename `MediaLightbox` -> `BoardLightbox`; main had already done it. Task 0.3's query-key list was
  short by 4 keys. Brief workers to grep and verify the spec, not just execute it.
- Verifying a Tailwind v4 `@theme` block by grepping compiled CSS is worthless - JIT strips unused
  classes, so absence proves nothing. Compile `globals.css` through Tailwind's own `compile()` API
  with an explicit candidate list instead. That is what proved `--color-red` does not shadow
  `--color-red-500`.
