# One Pipeline, Three Doors - Parity Audit + Unification Plan (2026-07-01)

## North star (updated 2026-07-01 after Ryan's direction)

This is not just a verb router. The end state is **Claude for StoryEngine**: one
agent brain that works three jobs with the same tools -

1. **Copilot** - sits in the video dock, answers anything, runs any stage on command
2. **Automater** - "finish it" and it drives the whole pipeline itself, pausing at
   checkpoints and spend gates
3. **Commander** - operates across ALL videos and the whole channel: paste ANY
   YouTube URL and it can analyze that video (structure, hook, style, thumbnail,
   pacing) and recreate it as ours, plan the calendar, launch candidates

The phases below build toward that. Phases 1-5 build the tool belt (every action
callable from one registry, by chat, by button, by agent). Phases 6-7 build the
brain (a real tool-using agent loop) and the analyze-and-recreate power.

The goal underneath: chat, the co-pilot dock, and the visual UI buttons all do the
same things and all run the exact same pipeline code. Three doors, one engine,
one brain.

## Part 1 - What the audit found

Full route inventory: 252 backend routes, ~118 used by the frontend, ~200 UI actions.
Chat surface: routes/chat.py (~3,360 lines).

### The good news: the engine is already shared

All three doors already end at the same place, `PipelineExecutor`:

- UI buttons -> `routes/pipeline.py` (`POST /api/pipeline/{stage}/{video_id}`) -> `PipelineExecutor.run_*`
- Co-pilot dock + home chat -> `POST /api/chat` -> `COPILOT_ACTIONS` registry (chat.py:615) -> the same `PipelineExecutor.run_*`
- Chat video creation ("Make it") -> `_handle_approve` -> the same `create_video()` that `POST /api/videos` uses

So there is no second pipeline to kill. The problem is thinner: the *action layer*
(what can be triggered, what it costs, what it needs first) lives in three places
and the three doors expose different subsets of it.

### Gaps: UI can do it, chat cannot

The copilot registry has 10 verbs (script, characters, storyboards, images, voice,
animate, sound, thumbnail, render, build). Missing verbs the UI has buttons for:

1. **research** - no copilot verb (autobuild runs it silently, but you can't say "run research")
2. **SEO + upload** - UploadTab can generate SEO, edit it, and upload to YouTube; chat can't
3. **approvals** - approve cast, approve environments, skip environments, approve/reject an asset
4. **per-shot fixes** - recrop, fix-text, delete a clip
5. **lock / unlock story**
6. **Drive script sync** - push to Drive / sync from Drive
7. **targeted scene edit** - "change scene 3's text to X" (chat can only rewrite the whole script with guidance)
8. **command-center actions** - launch an autopilot candidate, refresh discovery ideas,
   run a competitor scrape, extract learnings. Home chat can *talk about* these
   (quick actions) but cannot *do* them.

### Gaps: chat can do it, UI cannot

1. **Autobuild chaining** - "build it to pictures" / "finish it" runs the whole
   chain in one background task (`_make_autobuild_step`, chat.py:241). The UI only
   has one-step-at-a-time (`run-next`). There is no "Build it" button and no HTTP
   endpoint for the chainer at all - it is trapped inside chat.py.
2. **Prompt studio** - view / suggest / AI-rewrite any image, motion, thumbnail, or
   script prompt, then one-tap apply + regenerate. UI has raw text fields only.
3. **Follow-up edits** - "make it shorter", "make the thumbnail more aggressive"
   (appends guidance and re-runs one stage). UI requires manual field editing.
4. **Reference-URL modeling** - chat fetches real YouTube metadata and grounds the
   proposal in it; the UI model-video path is static.

### Divergences and duplication (the real risks)

1. **The action registry lives inside chat.py.** COPILOT_ACTIONS (verbs, costs,
   prerequisites, edit-ability) and the autobuild chainer are chat-private. The UI
   cannot reach them, so any new stage must be wired twice.
2. **Three price lists.** Cost estimates exist in chat.py `_estimate_cost` (:747),
   in the frontend Est. Cost counter, and in `/api/skills/pipeline/cost`. They will
   drift; the confirm card and the UI counter can quote different prices today.
3. **A fourth, legacy door.** `POST /api/pipeline/orchestrate` (pipeline.py:1910)
   and `POST /api/agents/videos/{id}/run` (agents.py:74) are older Claude-orchestrator
   routes. The frontend does not call them. Dead weight and a bypass around the
   confirm-card cost gating.
4. **Inconsistent cost gating.** In the dock, paid actions show a confirm card.
   The home CreatedCard path (docked=false) runs the same paid actions immediately
   with no confirm (chat.py ~798-867).
5. **Duplicate routes.** Onboarding status exists twice (/api/dashboard/onboarding/status
   and /api/onboarding/status); task status exists twice (/api/agents/{id}/task and
   /api/pipeline/task/{id}).

## Part 2 - The plan

### Phase 1 - Extract the action layer (the keystone)
Move COPILOT_ACTIONS + prerequisites + cost table + the autobuild chainer out of
chat.py into a new `backend/actions.py`. One registry: verb -> executor methods,
cost, needs, edit-ability, checkpoint logic. Chat imports it; new HTTP endpoints
expose it:
- `GET /api/pipeline/actions/{video_id}` - available verbs, server-computed costs, what's blocked and why
- `POST /api/pipeline/build/{video_id}?target=pictures|finish` - the autobuild chainer, now callable by anyone
No behavior change yet, pure extraction + two new routes.

### Phase 2 - Chat reaches UI parity
Add the missing verbs to the registry and the copilot classifier: research, seo,
upload, approve_cast, approve_environments, skip_environments, recrop, fix_text,
lock, unlock, drive_push, drive_sync, and targeted scene edit. Fix the gating hole:
CreatedCard paid actions get the same confirm card as the dock. Home chat gets
command-center verbs (launch candidate, refresh ideas, scrape, extract learnings)
routed to the existing route functions.

### Phase 3 - UI reaches chat parity
- "Build to pictures" / "Finish it" buttons on the pipeline page -> `POST /api/pipeline/build`
- Est. Cost counter and confirm cards both read `GET /api/pipeline/actions` (kill the frontend price table)
- "Improve prompt" button next to image/motion/thumbnail prompt fields -> the same
  prompt-studio suggest/rewrite functions, exposed via one small endpoint

### Phase 4 - Retire the legacy door
410 the old orchestrator routes (/api/pipeline/orchestrate, /api/pipeline/orchestrate/decide,
/api/agents/videos/{id}/run) after confirming nothing calls them in prod logs.
Dedupe the double onboarding-status and task-status routes.

### Phase 5 - Prove it
One test video driven three ways on prod: a UI button, a dock command, a home chat
command for the same stage. Confirm identical executor path in logs, identical cost
quotes, and that "Build it" from the button behaves exactly like "build it" in chat.
Zero or near-zero spend (use script/free stages plus one cheap image stage).

### Phase 6 - The agent brain (Claude for StoryEngine)
Replace the one-shot copilot classifier with a real tool-using agent loop. One
brain serves the dock, the home chat, and (later) Hermes standalone:
- Tools = the Phase 1 action registry (write tools) + read tools: video state,
  assets, script, analytics, competitor intel, channel profile
- Multi-step: it can look at the video, decide, act, look again - not one
  classify-and-fire
- Same spend rules everywhere: paid tools always route through the confirm card,
  with real costs from the registry
- Commander scope: home chat gets cross-video tools (list videos, launch autopilot
  candidate, refresh discovery, scrape competitors, calendar plan)

### Phase 7 - Analyze any video, recreate it
One command: paste any YouTube URL anywhere (home chat, dock, or a UI button) ->
full video DNA -> a modeled spec -> autobuild. Wire together the pieces that
already exist and fix the known gap:
- FIX: pasted URL outside a video currently never fetches the video (chat.py just
  stuffs the URL string into the spec) - fetch metadata + transcript every time
- DNA distillation: reuse /api/intelligence/distill-url (transcript, hooks,
  structure), the style classifier, and the thumbnail JSON-blueprint pipeline as
  one "analyze" step with a visible report ("here's why this video works")
- Recreate: analysis feeds the producer spec (title pattern, length, structure,
  style, thumbnail blueprint) -> approve -> autobuild to pictures
- Same flow callable on any competitor video card ("Make one like this" gets the
  full DNA treatment, not just metadata)

## Status

- [x] Phase 1 - extract action layer (BUILT 2026-07-01, local, not yet deployed):
      backend/actions.py now owns the verb registry, prices, prerequisite gates,
      cost estimator, video summary, and both step factories; chat.py imports them
      under the old names (zero behavior change, ~440 lines removed); new routes
      GET /api/pipeline/actions/{video_id} + POST /api/pipeline/build/{video_id}.
      35/35 backend tests pass; both route modules import clean. Prod proof owed.
- [ ] Phase 2 - chat parity verbs + gating fix
- [ ] Phase 3 - UI build button + shared costs + improve-prompt
- [ ] Phase 4 - retire legacy orchestrator routes
- [ ] Phase 5 - three-door proof on prod
- [ ] Phase 6 - agent brain (copilot / automater / commander)
- [ ] Phase 7 - analyze any video + recreate it
