# Director Surface Implementation Plan (v2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the chat surface into a **style workbench** - the place a creator invents a channel style, watches it get built, fixes it shot by shot with the cost/quality dial in plain view, and locks the result as a reusable recipe that autopilot runs from then on.

**Architecture:** A new `DirectorSurface` replaces `ChatHome` at `/` and `/chat`. Chat stays permanently on the left; a canvas on the right shows the film at three altitudes (Board, Shot, Timeline). `/pipeline/[videoId]` is not touched. Everything the canvas needs already exists in the API; most of this plan is surfacing, not building.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript, Tailwind v4 (`@theme`, no JS config), TanStack Query v5. Backend: FastAPI, Postgres/Supabase, FFmpeg, Remotion.

---

## The Product Thesis (read this before any task)

The video is not the deliverable. **The locked channel style is.** A creator uses this surface once to design a look, then autopilot produces against it indefinitely.

Two things make that work, and both must be visible on screen:

**1. The cost/quality dial.** The platform is built around two wired video models:

| Model id | Name | Tier | 6s clip |
|---|---|---|---|
| `grok-imagine` | Grok Imagine (default) | draft | **$0.09** |
| `seedance-2-fast` | Seedance 2.0 (Cinematic) | standard | **$0.60** |

That is a **6.7x spread**. On a 150-shot video: all-Grok $13.50, all-Seedance $90, ten heroes on Seedance with the rest Grok about $18.60. Grok gets 80-90% of the quality for a fraction of the price, and choosing which shots earn Seedance is the decision that sets both the budget and the ceiling. **That decision currently lives in a 10px monospace chip that looks like a label.** Making it a real, visible, satisfying control is the single highest-value thing in this plan.

Also wired: `veo-3.1-fast` ($0.30/8s), `veo-3.1-quality` ($1.25/8s). Unwired and must stay unselectable: Kling 3.0 Pro, Runway Gen-4 Turbo, Hailuo 2.3 Standard (`wired=False` in `MODEL_REGISTRY`).

**2. Style as a saved, reusable object.** Four production profiles exist today, each mirroring a real channel: Bilingual Character Animation, Simple-Language Animation, Photo Documentary, Animated Investigative Documentary (PocoAPoco, DvsU, Power Doctrine, Easy English). **Custom Film is not a fifth profile - it is the style generator**, letting the system compose a new style per section out of the same toolkit so a creator is not stuck picking one of four channels that already exist. From the creator's side that reads as five choices: four presets, or invent one.

The saved output of that invention is a **recipe** (`custom_film_recipes`) - versioned, immutable, signature-deduped, tenant-scoped. **It already exists and has no UI at all.** Today you save one by typing `save ... as "X"` into chat. That table is the channel-style object the whole autopilot story rests on, and it needs a library screen.

**The rest of the stack, for context:** GPT Image 2 for images (Nano Banana 2 and Z Image also selectable), ElevenLabs for voice, Suno for music (not built yet), Remotion for the through-layer that blends stills, video, and animated graphics.

---

## How The Canvas Must Behave (the reference experience)

Four screenshots of OpenArt's Director were the source for this. The teardown is in the session notes; these are the behaviors that are non-negotiable.

**1. Chat never leaves.** It is a permanent left column at every stage, from first prompt to final cut. Not a modal, not a page you navigate away from.

**2. The canvas follows the pipeline, automatically.** The creator never hunts for a tab. As each stage completes, the canvas shows that stage's output:

| Stage running | Canvas shows |
|---|---|
| Characters | The cast sheets as they render |
| Environments | The location plates |
| Storyboards | The boards per scene |
| Pictures / Clips | The board filling in with shots |
| Render | The timeline and the cut |

Drive this off `getProductionGuide`, which already returns per-stage `state` (`done` / `in_progress` / `not_started` / `skipped_by_format`) and a `next_step`. The altitude tabs stay available for manual override, but the default view should already be the right one.

**3. Work is visible while it happens.** Assets appear one tile at a time inside the chat status card as they land - stills, and audio with an inline player. Not a spinner, then everything at once.

**4. Every batch gets a review gate.** When a stage finishes, chat presents a compact card ("Characters x 2, Locations x 4") with **View** and **Looks good!**. View opens a full-pane gallery grouped and **named** - `CHARACTERS · 2`, `LOCATIONS · 4`, with each tile captioned (Milo, Wayan, SF Bedroom, Bali Terrace Clearing). Approval is one button, always the same button.

**5. Anything can be regenerated by just saying so.** "no I want a desert scene", "an ice castle", "an indian boy", "a mexican grandma" - typed into chat, against whatever is on screen. The verbs already exist (`redo_character_sheet`, `edit_character`, `redo_environment`, `edit_environment`, `redraw_shot`, `regenerate_scene_text`). What is missing is chat knowing what the creator is looking at, which Task 1.2 and Task 5.4 supply via `ui_context`.

**6. Everything is surfaced.** Media lives in Google Drive today, reachable only through the `/api/media/drive` proxy and scattered across per-stage tabs. The canvas rail must present it the way a creator thinks about it - as folders: **Media, Voice, Music, Cast & World**. Browsable, filterable, and reusable, so a still or a take can be pulled into a shot rather than regenerated.

---

## What Changed From v1 Of This Plan

v1 was researched against a branch 90 commits behind `main` and missed the entire Custom Film system. If you read v1, discard these parts of it:

| v1 said | Reality on `main` |
|---|---|
| Chat progress is a coarse 5-row checklist | Replaced by `ChatPipelineMap.tsx` - an 11-step strip, live-connection badge, profile header, task banner. **Extend it, do not replace it.** |
| We must build an approval gate card | `CustomFilmApprovalCard` exists and is rich. **Generalize it.** |
| No clip durations are stored anywhere | True for normal videos. **False for Custom Film**, which has `actual_duration_ms` + `timing_transform` on `custom_film_asset_provenance`. Copy that pattern. |
| Four render paths | **Five.** Custom Film is checked first in `run_render`. |
| Timeline v1 needs volume, speed, multi-lane audio | **Descoped to trim, reorder, basic transitions.** |
| Custom Film hides model and price by design | **Reversed by product decision** - see "The Transparency Reversal" below. |

**This plan cites symbol names, not line numbers.** v1's line numbers were wrong by up to 393 lines after branch drift. Grep for the symbol.

---

## The Transparency Reversal (do this deliberately, not quietly)

Custom Film was built to expose no provider, model, per-unit price, internal profile id, or raw knob to the creator. This is enforced by tests - see `storyengine/tasks/loop-checklist.md` and `backend/tests/functional/test_custom_film_frontend_map.py`.

**Product decision, 2026-07-24: that rule is reversed for cost and model.** The creator pays for these generations on their own kie.ai key, so the dial must be theirs to see and turn. The scaling story is unsellable otherwise.

What changes:
- **Models and prices become visible everywhere**, including inside Custom Film.
- **Per-section profile mix becomes visible** in creator-safe language. You cannot author a style blind. Follow the precedent already set by `sectionFeel()` in `ChatPipelineMap.tsx`, which turns raw knobs into phrases like "Grounded still-image documentary treatment."

What does **not** change:
- Provider plumbing, internal ids like `neutral_v1`, and raw knob JSON stay hidden. Creator-safe labels only.

**Before writing UI that breaks it, update the tests that assert the old invariant, in their own commit, with a message pointing at this decision.** Do not delete a test to make a screen work.

---

## What We Already Have (surface it, do not rebuild it)

| Capability | Where it lives | Status |
|---|---|---|
| Per-shot model override | `ModelOverrideSheet` in `ScenesWorkspaceTab.tsx` | Buried in a chip. **This is the dial.** |
| Hero-shot flag | `Asset.hero_shot` boolean | Exists, barely surfaced |
| Real per-model prices | `getVideoActions` returns `prices` | Reuse, never hardcode |
| "vs $X all-premium" comparison | `ConfirmActionCard` | Already computed |
| Per-shot camera preset | `CameraPresetSheet` | Buried in a chip |
| Image + motion prompt editing | Collapsed `<details>` in `SegmentCard` | Buried |
| AI prompt rewrite | `improvePrompt` | Wired, invisible |
| Redraw with coalescing + 409 retry | `redrawOne` in `frontend/src/hooks/use-clip-trust-ladder.ts` | **Use this hook.** Rolling your own double-charges. |
| Storyboard lightbox | `BoardLightbox` in `ScenesWorkspaceTab.tsx` | Not exported |
| Animatic preview | `AnimaticPlayer.tsx` | Reusable as-is |
| Saved style recipes | `custom_film_recipes` table + chat commands | **Zero UI. Biggest gap.** |
| Pipeline progress strip | `ChatPipelineMap.tsx` | Good. Extend it. |
| Custom Film approval | `CustomFilmApprovalCard` in `ChatCore.tsx` | Rich. Generalize it. |
| Section mix display | `customFilmSectionViews()` in `ChatPipelineMap.tsx` | Exists |
| Xfade transition grouping | `build_transition_plan` / `group_by_cuts` / `build_group_join_filter_complex` in `render_static_ffmpeg.py` | Built, unreachable from clip paths. **Port for Phase 7.** |
| Clip duration probe pattern | `_timing_transform` in `custom_film_production_runner.py` | Copy for normal videos |

**Genuinely missing:** a recipe library screen, a shot inspector, a cost dial, a timeline, and true clip durations on the normal path.

---

## Phases

| Phase | Delivers | Why here |
|---|---|---|
| 0 | Tokens, harvested components, shared hook | No visible change. Everything depends on it. |
| 1 | The shell + Style Library home | The frame, and the recipe screen that does not exist. |
| 2 | **The Board + the cost dial** | The money phase. Proves the thesis. |
| 3 | Shot inspector | Unbury everything. Biggest usability win. |
| 4 | Lock as channel style | Closes the loop to autopilot. Small - the table exists. |
| 5 | Chat upgrades | Extend `ChatPipelineMap`, generalize the approval card. |
| 6 | Clip duration truth + readable timeline | Cannot lay out a timeline on guessed numbers. |
| 7 | Trim, reorder, transitions | Descoped EDL. Largest remaining build. |

**Phases 0 to 4 are the core loop: invent, see, fix, lock. If the plan stalls after Phase 4, the product thesis is still proven.**

Phases 0 to 3 are specified as bite-sized steps. Phases 4 to 7 are at task granularity with interfaces pinned; expand them into steps before executing.

---

# PHASE 0: Foundations

Unchanged from v1 and still valid - those files did not move. Three independent tasks.

## Task 0.1: Tailwind v4 theme tokens
Add an `@theme` block to `frontend/src/app/globals.css` immediately after `@import "tailwindcss";`, mirroring the existing `:root` variables so tokens become utility classes. There is no `tailwind.config.*` and Tailwind v4 does not use one. Rename `--text-primary` to `--color-ink` (so it generates `text-ink`, not `text-text-primary`); leave the old variables untouched so nothing breaks. Re-read the hex values off `globals.css` before writing them.

Verify with a throwaway `<div className="bg-surface text-ink border border-edge rounded-card p-4">`, then `npm run build` and confirm `/` and `/pipeline` look identical.

**Rule for the rest of the plan: new components use these classes. No new inline `style={{}}` color props.**

## Task 0.2: Harvest shared components
Move out of `ScenesWorkspaceTab.tsx` into a new `frontend/src/components/canvas-shared/`: `BoardLightbox` (rename `MediaLightbox`, export it), `ModelOverrideSheet`, `CameraPresetSheet` (with `describeCameraMove` and `humanizeCameraId`), `SecureAudioPlayer`, and the pure parsers `parseShotPlan` / `parseStoryboardPromptBlocks` / `parseEnforcedPlan`. Re-import them. `SegmentCard` moves too, as `ShotCard`.

Grep for each symbol first to get real boundaries. `MediaLightbox` renders a bare `<img>`, so keep the "caller must pass a URL already through `toDisplayImageUrl`" contract as a doc comment.

This is a refactor. Walk the Scenes tab afterward and confirm the lightbox, model chip, and camera chip behave identically. Any difference is a bug.

## Task 0.3: `useVideoRefresh` hook
Create `frontend/src/hooks/use-video-refresh.ts` invalidating every per-video key in one call: `video`, `video-script`, `video-assets`, `video-actions`, `production-guide`, `segments`, `video-characters`, `video-environments`, `dialogue-map`, `video-ledger`. Grep the existing inline key literals first to confirm the list - there is no key factory.

**Do not adopt it inside `pipeline/[videoId]/page.tsx`.** That page is out of scope. The Director is its first consumer.

---

# PHASE 1: Shell and Style Library

**Gate:** you land on `/`, see your saved styles and the four presets, pick one or open an existing video, and get chat beside a canvas.

## Task 1.1: Director context and surface

**Files:** create `frontend/src/components/director/DirectorContext.tsx`, `DirectorSurface.tsx`, `CanvasEmptyState.tsx`

- [ ] **Step 1: Context**

```tsx
export type Altitude = "board" | "shot" | "timeline";

interface DirectorState {
  selectedVideoId: string | null;
  setSelectedVideoId: (id: string | null) => void;
  altitude: Altitude;
  setAltitude: (a: Altitude) => void;
  focusedShotId: string | null;   // assets.id
  setFocusedShotId: (id: string | null) => void;
}
```

Provider + `useDirector()` that throws outside the provider.

- [ ] **Step 2: Layout**

`selectedVideoId === null` renders `DirectorHome` full width. Otherwise a two-column grid: chat `min-w-[380px] max-w-[460px] w-[38%]`, canvas fills the rest, stacking below `lg`.

- [ ] **Step 3: Empty state**

`Clapperboard` glyph, "Your video will land here.", and a low-opacity ghost timeline behind it so the destination reads before anything exists.

- [ ] **Step 4: Verify + commit**

Point `/chat` at it temporarily, confirm chat renders with no console errors, screenshot.

## Task 1.2: ChatCore reports and receives the current video

**Why:** `turn()` hard-nulls `video_id` and `ui_context` in home mode, and `createdVideoId` is internal state the parent cannot read. Both were re-confirmed on `main`.

- [ ] **Step 1:** Add props `onVideoCreated?: (id: string) => void` and `activeVideoId?: string | null`.
- [ ] **Step 2:** Fire `onVideoCreated?.(res.video_id)` alongside the existing `setCreatedVideoId(res.video_id)`.
- [ ] **Step 3:** In the `sendChatTurn` call, change to:

```tsx
video_id: docked ? videoId ?? null : req.video_id ?? activeVideoId ?? null,
ui_context: docked ? uiContext ?? null : uiContext ?? null,
```

- [ ] **Step 4:** Walk `/chat` before and after. Confirm `video_id` is still `null` with nothing selected, and that creating a video still works. **The backend may branch on `video_id` presence** - keep `activeVideoId` null until a video is genuinely selected.
- [ ] **Step 5:** Commit.

## Task 1.3: Style Library (the home screen)

**This is the screen that does not exist today, and it is the point of the product.**

**Files:** create `frontend/src/components/director/DirectorHome.tsx`, `StyleLibrary.tsx`

- [ ] **Step 1: Find the recipe API**

```bash
cd ~/economy-fastforward/storyengine/backend && grep -rn "custom_film_recipes" routes/ *.py | grep -v test | head -20
```

Recipes are currently created and listed through chat commands parsed by `_custom_film_recipe_command` in `routes/chat.py` (`list` / `rename` / `archive` / `save ... as "X"` / `reuse the saved recipe "X" for ...`). **Determine whether a REST endpoint exists.** If it does not, this task ships read-only over whatever listing exists, and a `GET /api/custom-film/recipes` endpoint gets filed as its own backend task. Do not invent an endpoint inside a frontend phase.

- [ ] **Step 2: Three rows**

1. **Your styles** - saved recipes. Name, the section-mix shape, when it was last used, and a "Use this" action. Empty state explains what a style is and points at chat.
2. **Starting points** - the four production profiles from `production_style_profiles`, reusing `ProductionStyleSelector`'s labels and icons. These are the known-good channel looks.
3. **Or invent one** - a prompt that starts a Custom Film conversation in chat.

- [ ] **Step 3: Recent videos**

`useQuery({ queryKey: ["videos"], queryFn: () => getVideos() })` as a horizontal card row: `thumbnail_url` through `toDisplayImageUrl`, title, status pill, relative `updated_at`. Click sets `selectedVideoId`. **Today the chat surface has no way at all to reopen an existing video** - this fixes that.

- [ ] **Step 4: Route swap**

`frontend/src/app/page.tsx` returns `<DirectorSurface />` for authenticated users (leave the `<LandingPage />` branch). `frontend/src/app/chat/page.tsx` likewise. Delete `ChatHome.tsx`.

- [ ] **Step 5:** Pass `onVideoCreated={(id) => setSelectedVideoId(id)}` so a video created in chat opens the canvas automatically.
- [ ] **Step 6:** Walk it, screenshot, commit.

## Task 1.4: Canvas header

Segmented `Board | Shot | Timeline`. Right side: aspect pill (read-only this phase), **live cost pill** from `getVideoLedger` showing `total_cost` with a `by_stage` popover, and the Build button from `getVideoActions` (`build_target` gives the label, `cost_text` the popover) wired to `runBuild` behind a confirm.

Poll the ledger only while work is running. Note the ledger query must read the **sibling** video query's status (`videoQuery.data?.status`), not `query.state.data?.status` as the pipeline page does - that difference is intentional:

```tsx
refetchInterval: () => {
  const s = videoQuery.data?.status;
  if (!s || TERMINAL_STATUSES.has(s)) return false;
  return 5000;
},
```

Cross-check the number against `CostLedgerChip` on `/pipeline/:id` for the same video. The pipeline page is the reference.

**Phase 1 gate: walk it as a user, screenshots, before Phase 2.**

---

# PHASE 2: The Board and the Cost Dial

**Gate:** you can look at a whole film, see exactly which shots cost what, flip a shot to hero, and watch the total move.

**This phase is the product.** Everything it needs exists; nothing surfaces it.

**Data:** scenes from `getVideoScript` (de-dupes by scene number - always use it). Boards are five nullable `storyboard_N_url` columns on the scene row. Shots from `getVideoAssets` as `Asset[]`, keyed by `(scene, image_index)`. Prices from `getVideoActions().prices`.

## Task 2.1: The board

**Files:** create `frontend/src/components/director/BoardAltitude.tsx`

- [ ] **Step 1:** Query `["video-script"]`, `["video-assets"]`, `["video-actions"]`, `["models"]`. Group assets by scene, sort by `image_index`.
- [ ] **Step 2:** Scene rows - number, first line of `scene_text` as the beat, collapse chevron, approve tick wired to `approveScene`. Board strip through `toDisplayImageUrl` opening `MediaLightbox`. Then a `ShotCard` grid.
- [ ] **Step 3:** **Collapse scenes past the first three by default.** We render 40+ scenes and 150+ shots; OpenArt's four-scene layout does not survive that. Measure before virtualizing.
- [ ] **Step 4:** `onTap` sets `focusedShotId` and switches to the Shot altitude.
- [ ] **Step 5:** Redraw goes through `redrawOne`. Read that hook first - it owns coalescing and 409 retry.

## Task 2.2: The cost dial

**Files:** create `frontend/src/components/director/CostDial.tsx`; modify `ShotCard.tsx`, `BoardAltitude.tsx`

- [ ] **Step 1: Per-shot cost badge**

Every `ShotCard` shows its resolved model and that model's real price for this video's clip length, from `MODEL_REGISTRY` via `getModels()` / `getVideoActions().prices`. **Never hardcode a price.** Hero shots (`asset.hero_shot`) get a visually distinct treatment - a border or badge, not just a word.

- [ ] **Step 2: Hero toggle**

One click on a shot card toggles hero. Wire it to the existing model-override path (`set_shot_model_override` / the `/model-override` route on `backend/routes/assets.py`). Confirm what hero actually means in the router before wiring: grep `hero_shot` across `backend/` to see whether it drives routing directly or only annotates.

- [ ] **Step 3: The dial itself**

A header strip over the board showing three live totals:

```
All draft (Grok)      $13.50    150 shots
Heroes on Seedance    $18.60    10 heroes / 140 draft     <- current
All cinematic         $90.00    150 shots
```

Numbers computed from real per-model prices and the current per-shot assignment. Changing a shot updates it immediately. This is the scaling story on screen.

- [ ] **Step 4: Bulk actions**

"Make all draft", "Make the hero shots cinematic", "Reset to recommended". Each quotes its delta and confirms before writing. The recommendation already exists - `ConfirmActionCard` computes hero-scene routing notes and an all-premium comparison; reuse that logic rather than re-deriving it.

- [ ] **Step 5: Verify**

Flip a shot to hero, confirm the total moves, reload `/pipeline/:id` and confirm the override persisted. Screenshot the dial with real numbers.

## Task 2.3: The Asset Library rail (your Drive, surfaced)

**Files:** create `frontend/src/components/director/AssetRail.tsx`

Today a creator's generated media is scattered across per-stage tabs and otherwise lives in Google Drive behind the `/api/media/drive` proxy. There is no one place to see everything this video has made. This rail is that place, and it is pinned right at **all three altitudes**.

- [ ] **Step 1: Four folder tabs**

| Tab | Source | Tile shows |
|---|---|---|
| **Media** | `getVideoAssets` - `image_url`, `video_clip_url` | Thumb, duration badge if a clip, scene/shot label |
| **Voice** | `getVideoScript` `voice_over_url` + `getDialogueMap` | Speaker or narrator, duration, inline player |
| **Music** | Not built (Suno later) | Empty state naming what will live here |
| **Cast & World** | `getVideoCharacters`, `getEnvironments` | Named portrait / plate, grouped CHARACTERS then LOCATIONS |

Every URL goes through `toDisplayImageUrl` / `toDisplayVideoUrl`. Audio needs `getAudioToken` and the hand-built `${API_URL}/api/videos/{id}/audio/{scene}?token=` pattern - see `AnimaticPlayer.tsx`.

- [ ] **Step 2: Filters**

`USED IN` (which scene or shot), `TYPE` (still / clip / voice), `SOURCE` (generated / uploaded / project cast). These mirror what a creator actually asks: "where did I use that?" and "what did I upload versus what did the system make?"

- [ ] **Step 3: Click behavior**

Click opens `MediaLightbox`. From the Shot altitude, a tile should also be assignable to the focused shot, so an existing asset can be reused instead of paid for again. **Check whether an assign path exists before building it** - if not, ship browse-only and file the endpoint.

- [ ] **Step 4: Verify freshness**

Add a character in chat and confirm the rail updates through `useVideoRefresh`. If it does not, the chat turn is not refreshing - fix that, do not add a poll.

## Task 2.4: Canvas follows the pipeline

- [ ] **Step 1:** Query `["production-guide", videoId]` and derive the stage currently `in_progress` (or the last `done` if idle).
- [ ] **Step 2:** Map stage to default view per the table in "How The Canvas Must Behave". Set the altitude and the rail tab automatically when the stage changes.
- [ ] **Step 3:** **Never fight the creator.** Once they click an altitude tab manually, stop auto-switching for that session until they return to the auto view. Auto-advance that steals focus mid-edit is worse than no auto-advance.
- [ ] **Step 4:** Verify by running a real video through and watching the canvas move on its own from cast, to locations, to boards, to the cut. Screenshot the transitions.

**Phase 2 gate: this is the demo. Screenshot the dial and the canvas following a live run.**

---

# PHASE 3: Shot Inspector

**Gate:** every control for a shot is on one screen with nothing to expand.

## Task 3.1: The inspector

**Files:** create `frontend/src/components/director/ShotAltitude.tsx`

- [ ] **Step 1: Navigator.** Not OpenArt's horizontal filmstrip - that works for four shots and breaks at 150. A `Scene N / Shot M` dropdown grouped by scene with thumbnails, prev/next buttons, and left/right keys.
- [ ] **Step 2: Preview.** 16:9. `video_clip_url` through `toDisplayVideoUrl` if present, else `image_url` through `toDisplayImageUrl`, else an empty-shot state.
- [ ] **Step 3: Promote every control.** A labeled panel, not chips:

| Row | Source |
|---|---|
| Model + price + hero toggle | `ModelOverrideSheet`, prices from `getVideoActions` |
| Camera move | `CameraPresetSheet` |
| Image prompt | Always-visible textarea + Improve + Redraw with price |
| Motion prompt | Always-visible textarea + Improve + Save |
| Shot type / hero | `asset.shot_type`, `asset.hero_shot` |
| Dialogue | `asset.assigned_dialogue` |

Keep the existing save calls (`updateImagePrompt`, `updateVideoPrompt`, `improvePrompt`). Nothing new is built here - it is made visible.

- [ ] **Step 4: Action bar.** `Redraw picture` | `Animate` | `Fix crop` | `Delete clip` | `Delete picture`, each showing its real price. Redraw via `redrawOne`, animate via `runPipelineStage`, crop via `recropAsset`, delete via `deleteClip`. Paid actions confirm with the quote.
- [ ] **Step 5: Verify against `/pipeline/:id`.** Change a camera preset here, reload there, confirm it stuck.

## Task 3.2: Shot versions (read-only)

`getImageVariants(videoId, scene, index)` exists with **zero consumers**. Render its results as a thumbnail column beside the preview, current marked. Clicking opens `MediaLightbox`.

**Resolved:** `backend/routes/assets.py` exposes only `/approve`, `/reject`, `/video-prompt`, `/image-prompt`, `/model-override`, `/camera-preset`, `/batch-approve`. **There is no select-variant endpoint.** Ship read-only and file the endpoint as a separate backend task.

**Phase 3 gate: walk and screenshot.**

---

# PHASE 4: Lock As Channel Style

**Task granularity. Expand before executing.**

**Gate:** a creator finishes a video and turns it into a named style autopilot can run.

**This closes the loop and is small, because `custom_film_recipes` already exists** - versioned, immutable, signature-deduped per tenant, with a partial unique index preventing the same mix being saved twice.

## Task 4.1: Save this style
A terminal action on the canvas: name it, confirm the section mix, save. Backed by whatever the chat command `save ... as "X"` already calls. Surface the signature-dedupe result honestly - if this mix is already saved, say so and offer the existing one.

## Task 4.2: Reuse a style
From the Style Library, "Use this" starts a new video pre-bound to that recipe, the way `reuse the saved recipe "X" for ...` does in chat today.

## Task 4.3: Hand to autopilot
Connect a locked style to the autopilot config so scheduled videos produce against it. Read `frontend/src/app/autopilot/page.tsx` and the autopilot backend first - **do not assume the wiring exists.** If it does not, this task becomes a spec for it.

## Task 4.4: Rename and archive
The chat vocabulary already supports `rename` and `archive`. Give them buttons.

---

# PHASE 5: Chat Upgrades

**Task granularity. Expand before executing.**

**Hard constraint, re-verified on `main`:** SSE emits exactly two events, `stage_change` and `task_progress`, from a 3-second polling loop in `backend/routes/pipeline.py`. `task_progress` carries one free-text `message` per video. **There is no per-asset event.** For live asset tiles, poll `["video-assets", videoId]` while `task_progress.status === "running"` and diff. Do not open a third EventSource - `PipelineNotificationProvider` and the dock already subscribe.

## Task 5.1: Extend `ChatPipelineMap`
It already gives an 11-step strip, live-connection badge, profile header, and task banner. Add: an elapsed timer, and asset tiles appearing as they land. Do not rebuild it.

## Task 5.2: Generalize the approval card, and the review gallery
`CustomFilmApprovalCard` is the strongest card in the app - sections grid, per-beat blueprint, money block with hard ceiling, two buttons. Extract its shape into a reusable `approval_gate` kind for script, cast, environments, boards, and final cut. Adding a card kind is three edits in `ChatCore.tsx`: the `CardKind` union, the `cardKind()` dispatch, and `ACTION_CARD_RENDERERS`.

Two halves, per the reference experience:
- **In chat, a compact card**: a collage thumb, a count line ("Characters x 2, Locations x 4"), and two buttons - **View** and **Looks good!**. After the creator answers, drop the primary button and echo their choice as a normal user bubble. That is the audit trail.
- **View opens a full-pane gallery in the canvas**, grouped and **named**: a `CHARACTERS · 2` heading over captioned tiles (Milo, Wayan), then `LOCATIONS · 4` (SF Bedroom, Bali Terrace Clearing). Names matter - an unlabeled grid of faces is not reviewable.

**One button, everywhere, always the same.** Script, cast, environments, boards, cut. The creator should never have to learn what "approve" looks like twice.

## Task 5.3: Show the dial in Custom Film approval
Per the transparency reversal: add per-section model and cost detail to the approval card, and make the section profile mix visible in creator-safe language. **Update the tests asserting the old invariant in their own commit.**

## Task 5.4: Canvas-aware chat, and regenerate-by-saying-so

**This is the behavior the whole reference experience rests on:** a creator types "no I want a desert scene", "an ice castle", "an indian boy", "a mexican grandma" and the thing on screen changes.

Two halves:

**(a) Chat must know what is on screen.** With `activeVideoId` flowing (Task 1.2), extend `ui_context` beyond the docked chat's `{ tab }` to carry what the canvas is showing: `{ altitude, scene, index, focusedAssetId, railTab, selectedEntityId }`. The backend already accepts a `ui_context` object; widen the type in `ChatTurnRequest` and read it in `routes/chat.py`.

**(b) The producer must route plain language to the right verb.** The verbs all exist: `redo_character_sheet`, `edit_character`, `redo_environment`, `edit_environment`, `redraw_shot`, `edit_shot_image_prompt`, `regenerate_scene_text`. What is missing is the mapping from "an indian boy" plus "the creator is looking at character Milo" to `edit_character(id, description)`.

Build it as a card, not a silent action: the producer proposes the change, quotes the price, and the creator confirms. `PromptProposalCard` is the existing precedent - an editable textarea plus Apply / Cancel. **Regeneration costs money; never fire it straight off a sentence.**

- [ ] Verify by walking it: open a character in the rail, type "make him a mexican grandma", confirm the card proposes the edit against the right entity with a price, approve, and confirm the rail updates.

**Known small bug to fix while here:** `quality_rules_draft` is emitted as a yes/no confirm card with a `body`, but is absent from `cardKind()`, so it renders as a plain radio list and its `body` never displays.

## Task 5.5: Show which engine actually ran
Custom Film picks Remotion only at 1920x1080, 24fps, with a valid executable beat plan; otherwise it silently falls back to FFmpeg. The approval badge is a **prediction**. The journaled truth is `custom_film_assemblies.manifest->>'render_engine'` and is never shown. Surface the real one, with the reason when it degraded.

---

# PHASE 6: Clip Duration Truth and a Readable Timeline

**Task granularity. Expand before executing.**

**Why:** normal videos store no true clip duration. `assets.duration_seconds` is a planned target from a lookup table in `~/economy-fastforward/skills/video-pipeline/storyboard/coverage.py` (wide 3.5s / medium 2.5s / closeup 1.6s). `assets.video_duration` is the whole-second length we asked for. Real durations are probed at render time by `_probe_duration` and discarded, then `_trim_dead_space` cuts more silence nobody records.

**Custom Film already solved this.** `custom_film_asset_provenance` carries `assigned_duration_ms` (the slot), `actual_duration_ms` (ffprobe truth), and `timing_transform` (`none | trim | repeat_then_trim | static_hold`), write-once by trigger. Copy the pattern from `_timing_transform` in `custom_film_production_runner.py`.

## Task 6.1: Store the probe
Add `assets.clip_duration_probed NUMERIC` in a new migration (**check `backend/migrations/` for the current highest - it was 131 on 2026-07-24**). Write it in the same UPDATE in `backend/pipeline_executor.py` that already writes `video_clip_url` and `clip_speech_start`/`clip_speech_end` - grep `SET video_clip_url`. The bytes are in memory there and `measure_speech_bounds` already runs just above.

**Naming:** `videos.clip_duration_seconds` already exists as a per-video config field. Different table, different meaning. Do not reuse the name.

## Task 6.2: Backfill
Probe existing `video_clip_url` values. Run through `se`, off-peak, never during a generation.

## Task 6.3: Expose it
Add to the assets response in `backend/routes/videos.py` and to `Asset` in `frontend/src/lib/api.ts`.

## Task 6.4: Readable timeline
`TimelineAltitude.tsx` - ruler with timecodes, a video lane of blocks sized by `clip_duration_probed`, an audio lane from `getDialogueMap`, and **a third lane for the Remotion through-layer** where graphics blend over the footage. Scrubbable playhead. Click a block to jump, double-click to open the shot.

Do not copy `RenderTab.tsx`'s Scene Timeline - its durations are a `wordCount / 2.5` heuristic and it is read-only chips.

**Ship this even if Phase 7 slips.** Orientation is most of a timeline's value.

---

# PHASE 7: Trim, Reorder, Transitions

**Task granularity. Expand before executing.**

**Scope, per the 2026-07-24 decision: trim, move cuts around, basic transitions. That is all.** No per-clip volume, no speed, no multi-lane audio mixing in v1. This is materially smaller than v1 of this plan proposed.

**What the render code says:**
- `render_stitch.py` cannot survive. `_gather_clips` orders by `(scene, image_index)` with nothing editable joined, and `_concat` builds `concat=n=N:v=1:a=1`, which structurally cannot express per-clip trim.
- `render_perform.py` is the right foundation: `_cut_shot` cuts each entry to a window, `_concat_copy` joins with a stream-copy concat demuxer, `_build_scene_track` mixes a separate audio lane, and a final mux joins them. `build_timeline` already produces `{entries, placements, total, warnings}` - it just derives it from heuristics and throws it away.
- **Transitions already exist**, in `render_static_ffmpeg.py`: `build_transition_plan`, `group_by_cuts`, `build_group_join_filter_complex`. Fade-joined runs group into one `xfade` filter_complex; hard cuts stay stream-copy. **Port this - it is not a new build.**

## Task 7.1: EDL table
New migration (check the highest first). Descoped columns:

```sql
CREATE TABLE video_edits (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
  tenant_id UUID NOT NULL,
  track TEXT NOT NULL,               -- video | audio
  position INTEGER NOT NULL,         -- its own column, never assets.image_index
  source_asset_id UUID NULL REFERENCES assets(id),
  source_url TEXT NULL,
  in_point NUMERIC NOT NULL DEFAULT 0,
  out_point NUMERIC NULL,
  transition_in JSONB NULL,          -- {type: 'cut'|'fade', duration_seconds}
  transition_out JSONB NULL,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
```

Plus `videos.edl_version INTEGER` so renders are idempotent and the executor can tell EDL from scene order.

**`position` must be its own column.** `assets.image_index` is rewritten by coverage and regeneration, so it cannot hold a user's ordering.

**RLS required in the same migration.** Shared Supabase project - see the `supabase-youtuber-shared-project-rls` memory.

## Task 7.2: EDL API
CRUD plus a seed endpoint that materializes an EDL from current scene order, so an existing video can enter the timeline without starting empty.

## Task 7.3: EDL render path
Replace `build_timeline`'s derivation with `load_edl(video_id)` returning the same dict shape; everything downstream keeps working. Thread `in_point` into `_cut_shot` as `-ss`/`-t`. Port the transition grouping so fades break the stream-copy run. Collapse `_run_perform_render` and `_run_stitch_render` into one `_run_edl_render` with an EDL branch in the `run_render` dispatch - **after** the existing Custom Film check, which runs first.

## Task 7.4: Editing UI
Trim handles, drag to reorder, a transition control between clips. Every edit writes to the EDL and the timeline re-lays-out from the response, never from optimistic local state. Renders are slow and expensive; the timeline must never promise something the render will not honor.

**Build and prove 7.1 to 7.3 headlessly first** - seed an EDL, render it, diff against the current renderer - before any UI.

---

## Risks

| Risk | Where | Mitigation |
|---|---|---|
| Stale line numbers in older notes | Everywhere | This plan cites symbols. Grep. Check branch drift before believing any number. |
| Deleting a test to make a screen work | Phase 5.3 | The transparency reversal is a product decision. Update tests in their own commit citing it. |
| Rolling a new redraw path | Phases 2, 3 | `redrawOne` owns coalescing and 409 retry. Duplicating it double-charges. |
| Hardcoding a model price | Phase 2 | Always `getVideoActions().prices` / `MODEL_REGISTRY`. Prices change. |
| Offering an unwired model in the dial | Phase 2 | Kling, Runway, Hailuo are `wired=False`. Filter them out or they will fail at generation. |
| Sending `video_id` from home chat | Task 1.2 | Live surface. Keep `activeVideoId` null until a video is selected. Walk before and after. |
| 150 shots janking the board | Phase 2 | Collapse past the first three scenes. Measure before optimizing. |
| Assuming a recipe REST API exists | Task 1.3 | Recipes are chat-command driven today. Check before building against one. |
| New `video_edits` without RLS | Task 7.1 | Shared Supabase project. Policy in the same migration. |
| EDL render diverging from the timeline | Task 7.3 | Prove headlessly before building UI. |

## Out of Scope

- `/pipeline/[videoId]` and its ten tabs.
- Visual restyle. Phase 0 fixes plumbing only; the dark turquoise and gold look stays.
- Reconciling the two aspect-ratio controls (`video.aspect_ratio` vs render `orientation`). Known problem, fix deliberately later.
- A select-variant endpoint (filed in Task 3.2).
- Suno music. Not built; leave a lane for it in Phase 6.4 and stop there.
- SFX not reaching rendered video - being verified separately as of 2026-07-24. Sound effects appear to be read only by the legacy Remotion path, which would mean creators pay for audio that never lands.
