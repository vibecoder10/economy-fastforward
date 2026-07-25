# HANDOFF - 2026-07-25 - Director Phase 0 shipped; mockup APPROVED; Phase 1 ready to build

## State
- Prod: nothing deployed this session. All work local on branch `feat/director-chat`.
- **Phase 0 of DIRECTOR-CHAT-PLAN.md is COMPLETE and independently verified** (see
  `tasks/DIRECTOR-CHAT-CHECKLIST.md` for the evidence). Build clean, `npx tsc --noEmit` exits 0.
- **A clickable mockup of the whole Director surface is built and Ryan APPROVED it.**
  `tasks/director-mockup/index.html` - one self-contained file, no deps, not committed.
  **Build Phase 1 against this mockup.** It is the agreed target, not a suggestion.
- `main` is behind `origin/main` (was 11 behind at last check). Fetch and merge before starting.

## DO NOT DEPLOY - a concurrent Codex session has a paid job held mid-flight
Another session owns Custom Film and is running a live dry-run with roughly $8.52 already spent
and held. `se deploy` restarts uvicorn and KILLS in-flight user builds. Nothing deploys until
Ryan says that job is finished. Local work only.

Files that session is actively in - do not edit, and expect conflicts if you do:
- `backend/custom_film_production_runner.py`, `backend/custom_film_contract.py`,
  `backend/custom_film_planner.py` (hottest file in the repo), `custom_film_compositor.py`,
  `custom_film_section_runtime.py`, `custom_film_remotion.py`
- `frontend/src/components/chat/ChatCore.tsx` <- **they touched this and Phase 1 Task 1.2 needs it.**
  Make that edit tiny and put it in its own commit.
- `frontend/src/lib/custom-film-approval-truth.ts` and its spec
- `tasks/loop-checklist.md`, `tasks/loop-handoff.md`, `SYSTEM_STATE.md` - they touch all three in
  EVERY commit. Do not write them. (Note: a 2026-07-24 bookkeeping commit already wrote
  `tasks/loop-handoff.md` on this branch - expect one small conflict there at merge time.)

## Product decisions Ryan made this session - these are settled, do not relitigate
1. **The four profiles are a PARTS BIN, not four options.** Custom Film's planner is the
   intelligence layer that picks, per section, which channel's structure / writing / visuals to
   use. The home screen says "pick a known look, or just describe it and watch it compose one."
   Describing it is the SMART path, not the fallback.
2. **All internal jargon is banned from the UI.** Ryan's channel code-names mean nothing to a
   customer. Use these labels:
   - Bilingual Character Cartoon (was PocoAPoco)
   - Simple-Language Cartoon (was Easy English)
   - Animated Investigation (was DvsU)
   - Photo Documentary (was Power Doctrine)
   And write the three planner dials as English sentences, never field names:
   **"Built like** an investigation - **Written like** simple language - **Looks like** a photo
   documentary." Sweep for any other jargon; a word that needs explaining is a bug.
3. **Third path on the home screen: "Clone a video."** Paste a link, see what the system detected,
   type your twist ("do it with this Pokemon"), drop reference images, Build, plus an "Automate
   this" toggle. **Framing that matters: this is the ON-RAMP, not a copy machine.** After the
   first clone the product should push the creator toward their own characters and branding.
   Much of this exists already - `_describe_scene_style` in `backend/routes/model_video.py`
   samples real mid-video frames and never defaults to "animated" on real footage; cast sheets
   already solve character consistency. New parts are the twist prompt and reference-image intake.
4. **Right rail is five tabs:** `Media | Voice | Music | Cast | Environments`. Environments is
   top-level, not a sub-box. Media splits by type inside it: Storyboards / Images / Videos.
5. **The model/cost control is TWO controls, and neither hardcodes a vendor name.**
   - A **quality dial** with outcome words: Draft / Balanced (you set how many hero shots) /
     Cinematic. Prices under each are CALCULATED live from the wired-model registry, never typed.
   - A **"pick the model" panel**: Auto (system assigns per shot within budget, the default) or
     Lock-to-one ("use Veo 8 for everything").
   Both render from the existing model registry so a newly wired model just appears, with a
   **"New"** badge, and cannot silently become the default. Three override levels, broad to
   narrow: dial -> lock-to-one -> per-shot chip.
   **Shot chip label:** plain word big, vendor name small - `Draft - $0.09` with *Grok Imagine*
   underneath.
6. **Style auto-routing: suggest, but keep the human tap.** The four-profile pick is a hard gate
   that refuses video creation without a tap, and that guard stays. A wrong auto-pick can send a
   creator down a $90 path they did not choose. Use the existing `recommended_value` /
   `recommended_hint` card mechanism as the precedent.

## Next action (start here cold)
**Build Phase 1** of `~/economy-fastforward/storyengine/DIRECTOR-CHAT-PLAN.md` - "Shell and Style
Library" - against the approved mockup at `tasks/director-mockup/index.html`.

First: `git fetch && git checkout main && git pull --no-rebase && git checkout feat/director-chat
&& git merge main`.

Scope was SHIFTED this session by a real finding: `SELECT count(*) FROM custom_film_recipes` = 0.
**Nobody has ever saved a style, because the only way to save one is typing a magic phrase into
chat.** So Phase 1's value is NOT the shelf, it is the save button.

- **Highest value: a visible "Lock this as a style" action.** Make saving obvious and the library
  fills itself. In the mockup it is a gold button, always visible on the canvas - deliberately loud
  while the count is zero.
- **"Your saved styles" ships as an honest, well-designed empty state.** Do not fake rows.
- **There is NO REST endpoint to list recipes, and the chat "list recipes" command WRITES to the
  DB** (takes locks, appends two conversation turns) - it can never be a read path. A new route is
  needed: `backend/routes/custom_film.py` with `GET /api/custom-film/recipes`, registered in
  `backend/main.py`, as a **strict read-only consumer of `list_active_recipes(tenant_id)`** which
  already exists in `backend/custom_film_contract.py` with zero production callers.
  **Do NOT modify `custom_film_contract.py`** - it is the concurrent session's hottest file.
- **"Last used" is not answerable.** There is no `last_used_at` column and no video->recipe link
  (`videos` has no `recipe_id`). Drop that field. Section mix lives inside the `recipe` JSONB and
  must be parsed to display.
- `GET /api/production-styles` already returns the four profiles with labels and estimates - the
  "starting points" row is ready today.
- Rename the middle altitude tab from "Board" to **"Scene"** to match the target UI.

Phase 1 has 4 tasks (1.1 context+surface, 1.2 ChatCore reports the current video, 1.3 Style
Library home, 1.4 canvas header). Task 1.2 touches `ChatCore.tsx` - keep it tiny and isolated.

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
- Messages sent to a running worker can land AFTER it has finished the relevant part. A late
  instruction to restructure the mockup's right rail silently did not apply; a grep caught it.
  Verify a worker's claim against the artifact, never against its report alone.
