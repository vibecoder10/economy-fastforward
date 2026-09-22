# Plan - In-pipeline chat co-pilot (talk to your video while you build it)

> Written 2026-06-23 by the session that built the onboarding key walkthrough.
> To be EXECUTED in a fresh session. This doc is self-contained: read it top to
> bottom and you have everything you need to start.

## The goal in one line

Put the assistant chat window **inside the video pipeline page**
(`/pipeline/<videoId>`), scoped to that one video, as a collapsible right-hand
dock. The creator can talk to it about the video AND have it run any pipeline
action by voice ("animate scene 2", "redo the thumbnail", "make it shorter",
"render it now"). Anything that costs money or overwrites work asks for a
one-tap confirm first.

## Decisions locked with Ryan (2026-06-23)

1. **Full co-pilot from day one.** The chat can trigger every pipeline action
   conversationally (script, storyboards, images, animate per-scene, stitch,
   render, advance, skip, reset) plus answer questions about the video's state.
2. **Collapsible right dock.** A panel that slides in when you tap a Chat button.
   Pipeline content stays full-width when closed; shrinks only while open.
   Remembers open/closed.
3. **Confirm paid/destructive, auto free.** Free reads and explanations run
   instantly. Anything that spends money (animate, render, image/voice gen) or
   overwrites work (rewrite script, redo thumbnail, reset) shows a one-tap
   "Do it - ~$X" confirm card first. Matches Ryan's "ask before anything that
   costs money" rule and protects a new customer from surprise spend.

---

## What already exists (DO NOT rebuild these)

The backend is most of the way there. Verified by reading the code 2026-06-23.

- **Conversations already store a `video_id`.** Table `chat_conversations`
  (migration `060_chat_conversations.sql`): columns `tenant_id`, `video_id`
  (nullable), `transcript` JSONB, `state` JSONB, `phase`. Per-tenant isolation is
  manual (`WHERE tenant_id = $1`) on every query.
- **`/api/chat` already routes by mode** (`backend/routes/chat.py:1223-1238`):
  - onboarding step-machine when `state.mode=="onboarding"`,
  - **follow-up edits when the conversation has a `video_id`** (`_handle_followup`,
    `chat.py:396-441`),
  - producer intake (free Claude) otherwise.
- **Follow-up edits already work** (`_handle_followup` + `_classify_followup`,
  `chat.py:314-441`). One direct-Claude call maps free text to a stage + change,
  applies it to a guidance column, and re-runs that stage via `PipelineExecutor`.
  Current stages it knows (`FOLLOWUP_STAGES`, `chat.py:325-330`): `script`
  (writer_guidance), `images` (image_style_override), `thumbnail`
  (thumbnail_prompt), `render`. Length edits write `videos.video_length_minutes`.
- **Chat actions reuse the SAME `PipelineExecutor` the page buttons call.**
  Approval path calls `create_video()` + `run_next_step()`; follow-up calls
  `run_<stage>()`. No separate pipeline code (`chat.py:149-207, 263-311`).
- **Request/response models** (`chat.py:64-79`): request = `{conversation_id,
  message, selections, approve, start_onboarding}`. Response = `{conversation_id,
  assistant_text, cards, plan, ready_to_create, video_id, phase}`. There is **no
  `video_id` in the request yet** - we add one.
- **Keyless-tenant handling** already exists from the onboarding work
  (`MissingGenerationKeyError`, softened message pointing at the chat). Reuse it.
- **The chat UI** is `frontend/src/components/chat/ChatHome.tsx`. `turn()`
  (lines 129-151) posts to `/api/chat` via `sendChatTurn` and renders
  `assistant_text` + `cards` + `plan`. Card types `single`/`multi`
  (`api.ts:2283-2310`). `renderRich` linkifies `[text](url)` and bolds `**x**`;
  `maskSecret` hides pasted keys. Conversation id cached in localStorage
  (`CHAT_CID_KEY = "se_chat_cid"`).
- **The pipeline page** is `frontend/src/app/pipeline/[videoId]/page.tsx`
  (~675 lines, `"use client"`). Loads the video via `useQuery(getVideo(videoId))`,
  polls every 5s while processing, plus SSE (`usePipelineSSE`) and a task poller
  (`useTaskPoller`, `/api/pipeline/task/{videoId}`). Layout: left sidebar (60px)
  + `flex-1` main content capped at `max-w-[1400px]`. **No right-panel precedent
  yet, but adding one is a low-effort Tailwind grid change.** Tailwind + CSS vars
  (`var(--turquoise)` etc.), dark theme only. Client-side cost estimate already
  computed in the page (lines ~173-184) - reuse it for the confirm card.

---

## Architecture decisions (the spine of the build)

### A. One continuous thread per video (find-or-create by video_id)

When the dock opens on `/pipeline/<videoId>`, it should resume the SAME
conversation that created the video if there is one, so it remembers the whole
backstory. If none exists (older video, or created outside chat), create a fresh
conversation already bound to that `video_id`.

- Backend: on a turn with `video_id` set and no `conversation_id`, look up
  `chat_conversations WHERE tenant_id=$1 AND video_id=$2 ORDER BY updated_at DESC
  LIMIT 1`. Reuse it, or insert a new row with that `video_id` and
  `phase="created"`. This is the source of truth.
- Frontend: cache the resolved id per video under `se_chat_cid_<videoId>` so a
  reload is instant, but always trust the id the backend returns.
- Do NOT reuse the global home-chat `se_chat_cid` for the dock - that one is the
  tenant-level onboarding/creation thread.

### B. A real co-pilot action router (supersedes the thin follow-up layer)

Today `_handle_followup` only knows 4 edit stages. Full co-pilot needs the whole
action surface. Build `_handle_copilot(body, conv_id, tenant_id, transcript,
state, video_id)` that runs whenever `video_id` is set (replaces the current
`_handle_followup` branch at `chat.py:1229`; fold the existing FOLLOWUP_STAGES
logic into it so nothing regresses).

One classifier call (direct Claude, same pattern as `_classify_followup`) maps the
message + a compact **current-state summary** to one of:

- `read` - a question about the video ("how much has this cost?", "what's left?",
  "why is scene 3 blurry?"). Answer immediately with one Claude call; no action.
- `action` - one of the pipeline verbs below, with optional target (scene number)
  and optional change text.

Action verbs map to the **existing** `PipelineExecutor` methods / `runPipelineStage`
stages (confirm exact names at build - see Open Items): `script`, `storyboards`,
`images`, `video-generation` (animate; supports a per-scene target), `thumbnail`,
`sound`, `render`/stitch, plus meta verbs `advance`, `skip`, `reset`.

Feed the classifier a compact state summary so answers are smart and actions get
gated correctly (e.g. refuse "animate" before storyboards exist): video status,
which `pipeline_stages` are done, scene/asset counts, cost so far. All of this is
already on the video row + assets - fetch it the same way `getVideo` does.

### C. The confirm handshake (two turns for paid/destructive, one for free)

Add a `pending_action` object to `state` JSONB:
`{verb, methods, params, scene?, cost_estimate, label}`.

- **Free / read actions** execute on turn 1 and reply immediately.
- **Paid or destructive actions** (animate, images, voice, render, script
  rewrite, thumbnail redo, reset): turn 1 stores `pending_action` and returns a
  new **confirm action card** describing the action + `~$X` + Confirm / Cancel.
  No work runs yet.
- Turn 2 with `selections = {confirm_action: "yes"}` runs `pending_action`
  (queue the executor methods as a background task exactly like
  `_make_stage_step`, `chat.py:175-207`), clears it, and replies "On it...".
  `{confirm_action: "no"}` clears it and acknowledges.

Cost estimate: reuse the page's client estimate logic, or compute server-side
from scene/clip counts and the selected models. A rough but honest number is
fine; label it "~$X".

### D. Live progress without reinventing it

When the chat kicks off a stage, the pipeline page is ALREADY watching: the 5s
`useQuery` poll, `usePipelineSSE`, and `useTaskPoller` will reflect progress in
the stepper and tabs. The dock just needs to show a short "working on it" state
(reuse the `CreatedCard` live-progress pattern from ChatHome). Do not build a new
progress system.

---

## Phases

### Phase 0 - Extract a shared chat core (so it lives in two places cleanly)

The frontend audit flagged real blockers to dropping `ChatHome` into a 420px
panel: a `fixed bottom` composer, `max-w-3xl` everywhere, and a full-viewport
welcome screen.

- Pull the reusable engine out of `ChatHome.tsx` into a `ChatCore` (message
  thread + `turn()` + `SelectorCards` + `renderRich` + `maskSecret` +
  `CreatedCard`). Both the home page and the dock render it.
- Add props: `videoId?: string`, `docked?: boolean`.
- In `docked` mode: composer `fixed` -> `absolute` inside a `position: relative`
  panel; `max-w-3xl` -> `w-full`/`max-w-none`; hide the welcome hero, show a
  minimal "Ask about this video..." prompt instead.
- Add `video_id` to `ChatTurnRequest` (TS in `api.ts:2295`) and pass it on every
  `turn()` when in docked mode.

Done when: the home chat is unchanged in behavior, and `ChatCore` renders
correctly inside a narrow relative container in isolation.

### Phase 1 - Backend: video-scoped conversation + co-pilot router

- Add `video_id: Optional[str]` to `ChatTurnRequest` (`chat.py:64`).
- Find-or-create the conversation by `video_id` (decision A).
- Build `_handle_copilot` (decision B): classifier -> read vs action; absorb the
  existing `FOLLOWUP_STAGES`; add storyboards / images / animate(scene) / sound /
  render / advance / skip / reset; gate actions on current state.
- Implement the confirm handshake + `pending_action` state (decision C).
- Reuse `PipelineExecutor` methods and the `_make_stage_step` background-task +
  `_set_task_status` plumbing so the existing live trackers pick it up.
- Keyless tenant: return the friendly "add your key" message, not a crash.

Done when: a simulated run (mock DB + Claude + executor, like
`/tmp/se_key_sim.py`) proves: read returns an answer; a free action runs; a paid
action returns a confirm card then runs only after `confirm_action:"yes"`; an
illegal action ("animate" with no storyboards) is refused politely; tenant
isolation holds.

### Phase 2 - Frontend: the collapsible dock on the pipeline page

- Add a Chat toggle button to `pipeline/[videoId]/page.tsx` (near the Est. Cost /
  header). Wrap the tab content in a grid: `grid-cols-[1fr]` closed,
  `grid-cols-[1fr_420px]` open. Animate the panel in/out. Persist open/closed in
  localStorage (e.g. `se_pipeline_chat_open`).
- Render `<ChatCore videoId={videoId} docked />` in the panel.
- Render the new confirm action card (Confirm "~$X" / Cancel) - extend the card
  renderer with an `action` card kind, or model it as a `single`-select card with
  two options the backend reads back as `confirm_action`.
- Optional nice-to-have: pass the current tab/scene as light context so the dock
  can tailor suggestions (on Scenes tab, offer "animate this scene"). Keep it
  additive; not required for v1.

Done when: open the dock on a real video, ask a question and get an answer, run a
free action, run a paid action -> confirm card -> execute -> the stepper/tab
updates live via the existing pollers.

### Phase 3 - Safety, isolation, deploy, live test

- Local: `tsc --noEmit` + `npm run build` (frontend); `py_compile` + the
  simulated handler run.
- Confirm a keyless tenant gets the friendly key prompt inside the dock.
- **Deploy gate (ASK RYAN first).** Push main FROM LOCAL, VPS `git pull --ff-only`,
  rebuild frontend, `kill -9` backend restart, poll `/api/health`. Follow the VPS
  deploy discipline in memory `[[storyengine-deploy-restart-gotcha]]` and
  `[[storyengine-onboarding-key-walkthrough]]` (build the frontend from a CLEAN
  `origin/main` worktree if another agent has live WIP on the shared tree;
  hardlink node_modules with `cp -al`, copy `.env.local`, hot-swap `.next`).
- **Live test (ASK RYAN, costs a few cents).** On a real video: open dock, ask
  "how much has this cost?", request a free read, request "animate scene 1" ->
  confirm card shows ~$X -> confirm -> watch the clip generate and the stepper
  move. Screenshot each gate.

Done when: a creator can sit on the pipeline page and run their whole video by
talking to the dock, with money-spending actions gated, proven on prod with
screenshots.

---

## Reuse (don't rebuild)

- `chat_conversations` table + `_persist` (`chat.py:136-144`) - storage.
- `_handle_followup` / `_classify_followup` (`chat.py:314-441`) - the classifier
  pattern and edit-application; fold into `_handle_copilot`.
- `PipelineExecutor.run_<stage>` + `_make_stage_step` + `_set_task_status`
  (`chat.py:149-207`) - same functions the page buttons call.
- `getVideo` data shape + the page's cost-estimate logic - state summary + cost.
- `ChatHome` internals (`turn`, `SelectorCards`, `renderRich`, `maskSecret`,
  `CreatedCard`) - extract into `ChatCore`.
- `useQuery`/`usePipelineSSE`/`useTaskPoller` on the page - live progress, free.

## Open items to confirm at build (do not guess for prod)

- **Exact stage names + per-scene targeting.** Confirm how `runPipelineStage`
  / the executor addresses a single scene for "animate scene 2" (likely the
  `params?` arg on `runPipelineStage(videoId, stage, params)`, or a scene/asset
  id). Read `ScenesWorkspaceTab` and the `/api/pipeline/{stage}/{videoId}` route.
- **Server-side cost estimate.** Decide whether to compute it in the backend or
  send the page's client estimate up with the turn. Either is fine; pick one.
- **Card kind for confirm.** New `action` card type vs reusing a `single`-select
  card. Smallest change wins.

## Risks / honest flags

- This is the most "agentic" surface in the product - a sentence now triggers
  real spend. The confirm handshake is the safety net; test the refuse-illegal
  and confirm-before-spend paths hard before prod.
- Two chat entry points (home + dock) share one engine after Phase 0. Regression
  risk on the home/onboarding flow - re-run the onboarding sim after the refactor.
- Touches prod and costs a few cents for the live test. Gated on Ryan's go,
  separately, for deploy and for the live test.

## Where this sits

Extends the chat-first pivot (`[[storyengine-chat-first-pivot]]`) and the
follow-up-edit layer (Phase 5). Natural next GOAL.md phase after Phase 7
(onboarding key walkthrough). Add it to `GOAL.md` when the new session starts.
