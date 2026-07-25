# HANDOFF - 2026-07-24 - Director surface planned (no code shipped); prior clip-quality work still open

## State
- Prod: `00c04cb5` healthy (se health: backend+frontend active, api healthy, active_tasks 0,
  no deploy lock). Last deploy 2026-07-25T04:59:14Z `m7-custom-film-inference-diagnostics`
  (8a51b1b3 -> 00c04cb5). **Custom Film is under active development by another session -
  check before touching those files.**
- Branch: `feat/per-card-parallel-clips`, **90 commits behind main**. Uncommitted: `HANDOFF.md`
  (this file). main is at `b7944b46`.
- What happened this session: **planning only, zero code shipped, nothing deployed.**
  - Tore down 32 screenshots of OpenArt's Director mode (notes in session scratchpad).
  - Surveyed our chat surface, render paths, and the Custom Film system against `main`.
  - Wrote `DIRECTOR-CHAT-PLAN.md` (v2) - 8 phases, reviewed and approved.
  - Product decisions recorded in memory (`storyengine-director-surface-thesis`).

## Next action (start here cold)
Execute Phase 0 of `~/economy-fastforward/storyengine/DIRECTOR-CHAT-PLAN.md`. Read the whole
plan first, especially "Before You Start" and "The Product Thesis". Branch off main:

    git checkout main && git pull && git checkout -b feat/director-chat

Phase 0 is three independent, no-visible-change tasks: Tailwind v4 `@theme` tokens in
`frontend/src/app/globals.css`; harvest `BoardLightbox` / `ModelOverrideSheet` /
`CameraPresetSheet` / `SegmentCard` / parsers out of `ScenesWorkspaceTab.tsx` into a new
`frontend/src/components/canvas-shared/`; create `frontend/src/hooks/use-video-refresh.ts`.

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
