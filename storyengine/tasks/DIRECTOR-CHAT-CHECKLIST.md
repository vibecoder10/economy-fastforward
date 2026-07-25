# DIRECTOR CHAT - Phase 0 (Foundations) checklist

Plan: `~/economy-fastforward/storyengine/DIRECTOR-CHAT-PLAN.md` (564 lines, v2, approved)
Started: 2026-07-24 | Branch: `feat/director-chat` off `main`

## ASSUMPTIONS (set by Fable, no user block)
- Scope is **Phase 0 only**. Phases 1-7 are parked; report and stop after Phase 0.
- **Nothing deploys.** Local branch work only, no VPS touch.
- Another session owns Custom Film (backend + custom-film components). Phase 0 touches
  none of it. Any worker that finds itself editing a `custom_film_*` file STOPS and reports.

## DEFINITION OF COMPLETE (graded against this, not the boxes)
1. Branch `feat/director-chat` exists off an up-to-date `main`, with the three Phase 0
   tasks committed on it (separate commits).
2. `npm run build` passes on the merged branch, zero new errors vs the pre-change baseline.
3. **Scenes tab behaves identically** after the harvest refactor - lightbox opens, model
   chip works, camera chip works - proven by clicking in a browser, with screenshots.
4. `@theme` tokens generate real utility classes (`bg-surface text-ink border-edge
   rounded-card`), and `/` plus `/pipeline` look unchanged.
5. `use-video-refresh.ts` exists, invalidates the grep-confirmed key list, and is adopted
   by nobody yet (`pipeline/[videoId]/page.tsx` untouched).
6. Zero files touched that the Custom Film session owns. Nothing deployed.

## CHUNKS

- [x] **C1 (H) [G]** Branch setup. `git checkout main && git pull && git checkout -b
      feat/director-chat`. Report exactly what the pull did to the ahead-1 commit
      (`c3b05d51`, the plan itself). Record the pre-change build baseline.
- [x] **C2 (S) [U][V]** *(PARALLEL with C3)* **Task 0.2 - harvest shared components.**
      Own worktree. Move `BoardLightbox`(<-`MediaLightbox`), `ModelOverrideSheet`,
      `CameraPresetSheet` (+`describeCameraMove`, `humanizeCameraId`), `SecureAudioPlayer`,
      `SegmentCard`(->`ShotCard`), and parsers `parseShotPlan` /
      `parseStoryboardPromptBlocks` / `parseEnforcedPlan` out of `ScenesWorkspaceTab.tsx`
      into new `frontend/src/components/canvas-shared/`. Grep each symbol for real
      boundaries FIRST (plan line numbers are stale - cite symbols only). Keep the
      "caller must pass a URL already through `toDisplayImageUrl`" contract as a doc
      comment on the lightbox. Build + walk the Scenes tab in a browser + screenshots.
- [x] **C3 (S) [U][V]** *(PARALLEL with C2)* **Tasks 0.1 + 0.3.**
      Own worktree. (0.1) `@theme` block in `frontend/src/app/globals.css` right after
      `@import "tailwindcss";`, mirroring existing `:root` vars, re-reading hex values off
      the file; rename `--text-primary` -> `--color-ink`; leave old vars untouched.
      (0.3) create `frontend/src/hooks/use-video-refresh.ts` invalidating every per-video
      key in one call - grep the inline key literals to confirm the list. Do NOT adopt it
      anywhere. Two separate commits.
- [x] **C4 (H) [G][V]** Merge both lane branches into `feat/director-chat`, run
      `npm run build`, report clean or the exact errors. No force, no rebase surgery.
- [x] **C5 (S) [V]** Fresh-eyes verify of the Definition of Complete above by an agent
      that never saw the build. Browser walk + screenshots.

## LESSONS (feed into later briefs)
- Plan cites symbols, never line numbers - a stale checkout made v1's line numbers wrong
  by up to 393 lines. Always grep for the symbol.
- A reviewer checking "do the cited symbols still exist" is a weak check; it misses what
  was *added* next to them. Ask reviewers to look for new work on the target branch too.

## PARKED (do not start without a go)
- Phases 1-7 of DIRECTOR-CHAT-PLAN.md.
- Carried open threads live in `HANDOFF.md` (re-roll s113/s114/s122, SFX-never-renders
  check, transparency-reversal test updates, picture-QA vision pass).

## OUTCOME — 2026-07-24: Phase 0 COMPLETE (independently verified)

Branch `feat/director-chat`, 5 commits off `main`@f7eaab1a:
- 9451f98a Task 0.1 Tailwind v4 @theme tokens
- 1040985d Task 0.3 useVideoRefresh hook
- 22c4d334 Task 0.2 harvest shared canvas components
- 2db3f486 / fbc4a38e lane merges

All six Definition-of-Complete criteria PASS, verified by a fresh agent that did not build it:
- Clean rebuild (`rm -rf .next`) = 0 errors, 0 warnings, 34 routes, TypeScript runs and passes;
  `npx tsc --noEmit` exits 0 independently.
- Live browser walk on video f32ed182-be1f-4a24-a8de-bb8db4ac88df: BoardLightbox, ModelOverrideSheet
  and CameraPresetSheet all open with correct data and close; 73 shot cards render; zero console
  errors; cost ledger byte-identical before and after (nothing was spent).
- @theme collision risk CLEARED: compiled globals.css through Tailwind's own compiler. `--color-red`
  and `--color-red-500` are separate namespaced keys, so `bg-red-500` etc. are untouched, and the
  frontend has ZERO bare-color class usages for the new tokens to affect.
- Hook invalidates 14 keys (the plan's 10 + `roster-dashboard`, `video-characters-gate`,
  `drive-script-status`, `project-cast` found by grep). Imported by nobody;
  `pipeline/[videoId]/page.tsx` untouched.
- Diff is exactly 10 files, all under `frontend/src/`. Nothing near Custom Film or backend Python.

Plan corrections found while executing (fix these in the plan if it is ever re-run):
- Task 0.2's `MediaLightbox` -> `BoardLightbox` rename was ALREADY DONE on main. It was a pure move.
- Task 0.3's key list was incomplete by 4 keys (listed above).

Carried risks for whoever starts Phase 1:
- Local `main` is now 3 commits behind `origin/main` (PR #474 "Run approved Custom Films through
  final assembly" landed at 22:42, after this branch was cut at 22:16). Fetch and merge before Phase 1.
- Lane branches `feat/director-chat-tokens` and `feat/director-chat-harvest` are merged but not
  deleted. Safe to delete.
- Misclick hazard for future verifiers: on an unanimated shot the DOM puts an inert
  prompt-disclosure toggle immediately next to the real "Animate · $0.09" button in tab order.
  Cross-check the cost ledger after any click.

## 2026-07-25: Mockup approved, Phase 1 scoped
Clickable mockup at `tasks/director-mockup/index.html` - Ryan reviewed and approved it. Build
Phase 1 against it. All product decisions and the Phase 1 scope shift are recorded in `HANDOFF.md`.
Key finding that reshaped Phase 1: zero Custom Film recipes have ever been saved, so the valuable
build is the SAVE action, not the library shelf.
