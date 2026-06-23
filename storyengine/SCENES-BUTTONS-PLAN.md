# Scenes Page Button System — Simplification Plan

> **For agentic workers:** implement task-by-task. Steps use `- [ ]` checkboxes. Verify each phase on the VPS (local preview can't reach the authed pipeline page).

**Goal:** Replace the tangled, duplicated, partly-broken button set on the video pipeline page with ONE clear path: each scene has a single large primary button that advances it (Storyboard → Pictures → Animate), one stage-aware bulk button, and one top guide that agrees with the workspace.

**Architecture:** The page today runs TWO competing mental models at once — an old "guided" engine and the new coverage workspace — plus two progress bars. This plan unifies them onto the new coverage model, removes duplicate triggers, fixes the dead buttons, and sets a clear visual hierarchy (one big primary action, everything else small or in the ⋯ menu).

**Tech stack:** Next.js (App Router), React, Tailwind, lucide-react icons. No new dependencies.

---

## STATUS (2026-06-23) — built + deployed live on the VPS

- ✅ **Phase 1 — Scenes tab buttons.** One big primary per scene (1·Generate storyboard → 2·Generate pictures → 3·Animate scene), Animate folded into the primary, Redo demoted to small secondary, ONE stage-aware header bulk button (replaces the broken "Generate all scenes" + "Animate the rest"). File: `ScenesWorkspaceTab.tsx`.
- ✅ **Phase 2 — Guide aligned (additive, low-risk).** Added `scenesWithPictures`; the guide now routes to "Create your pictures" (`coverage-images`) when scenes still lack pictures instead of a premature "Animate scene 1". Old 3×3 paths untouched. Files: `next-action.ts`, `GuidedNextStep.tsx`. NOTE: did NOT rip out `storyboard-extract` (old flow still needs it) — chose the additive guard over a risky shared-engine rewrite.
- ✅ **Phase 4 — Cost counter.** `Est. Cost` now shows a live estimate = pictures × $0.08 + clips × per-model rate, computed on the frontend from real assets (backend never rolled up `videos.total_cost`). File: `[videoId]/page.tsx`.
- ⏸️ **Phase 3 — Stepper vs tabs.** DEFERRED. It's a passive 13-stage status display vs the 10 editing tabs — mild redundancy, not the duplicate-action problem. Reworking risks the status view for little gain. Do only if Ryan wants it.

Backups on the VPS: `*.bakP1-*`, `*.bakP2-*`, `*.bakP4-*` next to each file. Verify visually at `/pipeline/<id>` (local preview can't reach the authed page).

---

## The diagnosis (what's wrong today)

### The page has FOUR overlapping control systems
1. **PipelineStepper** — 13 dots (IDEA → … → PUBLISHED). `PipelineStepper.tsx`. Looks clickable, is passive.
2. **GuidedNextStep banner** — the big green "next up" CTA. `GuidedNextStep.tsx`, driven by `lib/next-action.ts`.
3. **Tab bar** — 10 tabs (1·Research … 10·Results). `[videoId]/page.tsx:531`.
4. **ScenesWorkspaceTab** — the per-scene buttons + bulk buttons + a ⋯ menu. `ScenesWorkspaceTab.tsx`.

Three of these number the same journey differently (13 dots vs 10 tabs vs "step X of 10" in the banner).

### Two mental models that disagree
- **The guide** (`next-action.ts`) still runs on the OLD flow: `storyboards` → `grids` → **`storyboard-extract`** → animate. The `storyboard-extract` stage does not apply to the new coverage flow at all.
- **The workspace** (`ScenesWorkspaceTab`) runs the NEW coverage flow: storyboard sheet (`storyboard-images`) → real pictures (`coverage-images`) → animate.

So the green banner can tell you to do a step that the workspace has already replaced (e.g. "Animate scene 1" while the cards still say "Generate storyboard"), or trigger a dead stage.

### Duplicate triggers for the same action
- **Animate** has 5 entry points: banner "Animate scene 1", banner "Animate the rest", workspace "Animate the rest", per-scene "Animate this scene · $X", and tap-a-picture.
- **Generate pictures** has 4: banner "Create your storyboard" / "Finish making your pictures", header "Generate all scenes", per-scene "Generate scene", and click-an-empty-board-slot.

### Confirmed broken button
- **"Generate all scenes"** (`ScenesWorkspaceTab.tsx:955`) SHOWS when `scenesNeedWork` is true (`!hasStoryboardPrompt || gridCount===0`, line 360) but DOES NOTHING because its handler filters `work = scenes.filter(s => s.storyboardGridCount === 0)` (line 490) and returns early when that's empty (line 491). The cheap one-image storyboard writes a board but no prompt, so `hasStoryboardPrompt` stays false forever → the button shows forever and no-ops every time. **This is the "generate scenes buttons don't work" you hit.**

### Screenshot evidence
- Shot 1–2: scene 2 said "Regenerate" with nothing visible, scene 3 said "Generate scene" — the single-boolean button couldn't tell "has a storyboard" from "is finished."
- Shot 4: header shows "Generate all scenes" (purple) + per-scene "Regenerate" + "Animate this scene · $1.20" + the green banner "Animate scene 1" all at once — four primary-weight buttons competing, and "Generate all scenes" is the dead one.

---

## The design (one clear path)

### Principle: one primary action, visible at a time
Each scene has exactly ONE large primary button showing its next step. Everything else is either small/secondary or tucked in the ⋯ menu. The journey reads the same everywhere.

### Per-scene lifecycle — ONE primary button, color = stage
| Scene state | Primary button (large) | Color | Action |
|---|---|---|---|
| No storyboard | **1 · Generate storyboard** | purple | `storyboard-images` (cheap sheet) |
| Storyboard, no pictures | **2 · Generate pictures** | orange | `coverage-images` (real frames) |
| Pictures, not animated | **3 · Animate scene · $X** | green | animate this scene's pictures |
| Fully animated | small **Redo** (ghost) only | — | regenerate pictures |

- Numbered prefixes (1·/2·/3·) make the order obvious.
- "Generate scene" → renamed **"Generate pictures"** (clearer: it draws the shot pictures).
- The per-scene **Animate** folds into this same primary slot (stage 3), so there's no separate competing "Animate this scene" button — it IS the primary when pictures are ready.
- Tap-a-picture-to-animate stays (it's a fine per-picture shortcut), but it's no longer duplicated by a same-weight scene button.
- A small secondary **Redo** sits beside the primary only once a stage is complete (low visual weight).

### One bulk button (header) — stage-aware
Replace BOTH "Generate all scenes" and workspace "Animate the rest" with ONE button that mirrors what most scenes need next:
- If any scene has no storyboard → **"Generate all storyboards"**
- Else if any scene has no pictures → **"Generate all pictures"**
- Else if any picture isn't animated → **"Animate everything · $X"**
- Else → hidden (nothing to do)

It must be driven by the SAME predicate it acts on (fixing the show/do bug): compute the work list once, label and enable from that list, hide when empty.

### One guide, aligned to the coverage flow
`next-action.ts` is rewritten so its scene-stage steps match the workspace exactly:
- `storyboard-images` = "Create your storyboards"
- `coverage-images` = "Create your pictures"
- animate = "Animate your scenes"
- **Remove the `storyboard-extract` step** (dead in coverage).

The banner then always points at the real next workspace action — never a dead stage.

### One progress system
- Keep the **tab bar** as the navigation (it's the real one).
- Make **PipelineStepper** mirror the same 10 steps (or collapse it to a thin progress line). No more 13-vs-10 mismatch. (Lowest priority — polish.)

### Visual hierarchy (sizing)
- **Primary** (one per scene, one bulk): `text-sm font-semibold px-5 py-2.5 rounded-lg`, filled, stage color. Bigger than today's `text-xs px-3 py-2`.
- **Secondary** (Redo, Unlock): `text-xs` ghost/outline.
- **Destructive/rare** (Clear all storyboards, Delete all pictures, Re-write motion, Skip ahead): stay in the ⋯ menu only.

---

## File structure

| File | Responsibility | Change |
|---|---|---|
| `frontend/src/components/production/ScenesWorkspaceTab.tsx` | per-scene + bulk buttons | bulk of the work |
| `frontend/src/lib/next-action.ts` | the guide engine | re-align to coverage flow |
| `frontend/src/components/production/GuidedNextStep.tsx` | guide banner | drop dead `storyboard-extract` call |
| `frontend/src/components/production/PipelineStepper.tsx` | top progress dots | (Phase 3) reconcile to 10 steps |

---

## Phase 1 — Fix the Scenes tab (biggest win, self-contained)

### Task 1: Fix the dead bulk button + make it stage-aware
**Files:** Modify `ScenesWorkspaceTab.tsx` (`scenesNeedWork` ~line 360, the header button ~line 955, `handleGenerateAllScenes` ~line 488).

- [ ] **Step 1:** Add a single derived "bulk next action" before the return:
```ts
// One stage-aware bulk action. Driven by the SAME lists it acts on, so the
// button never shows when there's nothing to do (fixes the no-op bug).
const needStoryboard = scenes.filter((s) => s.storyboardGridCount === 0);
const needPictures   = scenes.filter((s) => s.storyboardGridCount > 0 && s.assets.every((a) => !a.image_url));
const bulk =
  needStoryboard.length ? { stage: "storyboard-images", label: `Generate all storyboards (${needStoryboard.length})`, scenes: needStoryboard } :
  needPictures.length   ? { stage: "coverage-images",   label: `Generate all pictures (${needPictures.length})`,   scenes: needPictures } :
  null;
```
- [ ] **Step 2:** Replace the header button (line 955) to render from `bulk` (hide when `null`), running each `bulk.scenes` through `bulk.stage` via the existing chain queue.
- [ ] **Step 3:** Delete the old `scenesNeedWork` const and the old `handleGenerateAllScenes` body that filtered only `gridCount===0`; point the new button at a `handleBulk(bulk)` that enqueues `bulk.scenes`.
- [ ] **Step 4:** Verify (deploy, Phase-1 verify block): with 3/3 boards and 0 pictures, the header shows "Generate all pictures (2)" and clicking it actually runs.

### Task 2: One primary button per scene (3-stage), Animate folded in
**Files:** Modify `ScenesWorkspaceTab.tsx` scene-card button block (~lines 1100–1155).

- [ ] **Step 1:** Make the primary a single switch on scene state:
  - `assets.some(image_url)` && pending animate → **3 · Animate scene · $X** (green) → existing `animateScene`
  - else `assets.some(image_url)` (all animated) → small **Redo** ghost only
  - else `storyboardGridCount > 0` → **2 · Generate pictures** (orange) → `handleGenerateRealImages`
  - else → **1 · Generate storyboard** (purple) → `handleGenerateScene`
- [ ] **Step 2:** Remove the separate same-weight "Animate this scene" button (it becomes the stage-3 primary). Keep tap-a-picture-to-animate.
- [ ] **Step 3:** Apply primary sizing (`text-sm font-semibold px-5 py-2.5`); make Redo small ghost.
- [ ] **Step 4:** Verify each scene shows exactly one big primary matching its true state.

### Task 3: Remove the workspace "Animate the rest" duplicate
**Files:** `ScenesWorkspaceTab.tsx` (~lines 964–972).

- [ ] **Step 1:** Delete the workspace "Animate the rest" button — covered by the stage-aware bulk (Task 1) once pictures exist (extend `bulk` with an `animate` branch).
- [ ] **Step 2:** Extend `bulk` with: else if any picture un-animated → `{ kind:"animate", label:`Animate everything · $${remainingCost}`, ... }` wired to `animateAll`.
- [ ] **Step 3:** Verify: only one "animate everything" control exists, in the header.

### Task 4: Confirm the ⋯ menu holds only rare/destructive actions
**Files:** `ScenesWorkspaceTab.tsx` advanced menu (~lines 994–1059).

- [ ] **Step 1:** Keep in ⋯: Re-write motion directions, Edit motion instructions, Delete all final pictures, Clear ALL storyboards, Skip ahead. No primary actions in the menu.
- [ ] **Step 2:** Verify nothing in the menu duplicates a primary button.

**Phase 1 verify (deploy):** scp the file, `npm run build` on the VPS, restart frontend (plain kill MainPID), hard-reload `/pipeline/<id>`. Walk scene 3 (storyboard → pictures → animate) and confirm one big primary per step + a working header bulk button.

---

## Phase 2 — Align the guide to the coverage flow

### Task 5: Rewrite scene-stage steps in `next-action.ts`
**Files:** Modify `frontend/src/lib/next-action.ts` (steps ~128–201).

- [ ] **Step 1:** Replace the `grids` / `storyboard-prompts` / `extract` scene steps with coverage steps:
  - need storyboard → `{ key:"storyboards", label:"Create your storyboards", stage:"storyboard-images", tab:"scenes" }`
  - need pictures → `{ key:"pictures", label:"Create your pictures", stage:"coverage-images", tab:"scenes" }`
  - need animate → keep `clips-taste` / `clips-rest`
- [ ] **Step 2:** Delete the `storyboard-extract` step and its `finalsMissing` extract branch.
- [ ] **Step 3:** In `GuidedNextStep.tsx:127`, remove the hardcoded `runPipelineStage(video.id, "storyboard-extract")` branch.
- [ ] **Step 4:** Verify the banner's "next" always matches the workspace's next primary (no dead steps).

**Phase 2 verify:** on a fresh video, the green banner walks Storyboard → Pictures → Animate in lockstep with the scene cards.

---

## Phase 3 — Reconcile progress display (polish, optional)

### Task 6: Make PipelineStepper match the 10 tabs
**Files:** `PipelineStepper.tsx`, `[videoId]/page.tsx:471`.

- [ ] **Step 1:** Either map the stepper to the same 10 tab steps, or replace it with a thin "Step N of 10" line. Remove the 13-vs-10 mismatch.
- [ ] **Step 2:** Verify one consistent step count across stepper, tabs, and banner.

---

## Out of scope
- The generation logic itself (storyboard sheet, coverage) — unchanged; this is buttons/flow only.
- The animation trust-ladder semantics (tap = one, bulk = all) — preserved, just de-duplicated.
- Backend routes — unchanged (Phase-1/2 reuse `storyboard-images`, `coverage-images`, animate).

## Verification note
All visual verification happens on the VPS — local preview can't load the authed `/pipeline` page. Each phase: scp changed files → `npm run build` on VPS → restart frontend → hard-reload → click through.
