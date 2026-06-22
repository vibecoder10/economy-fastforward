# GOAL - StoryEngine: chat-first creative producer ("ChatGPT for video creation")

**North star:** A new user describes a video in one sentence and StoryEngine, acting like a creative producer, gathers what's missing conversationally and runs the whole pipeline under the hood. Conversation + progress become the interface; the pipeline becomes an implementation detail. (Feeds the company goal: first 10 customers actually using it.)
**Success looks like:** A cold-start user types "make me a video about a dragon who finds a lonely owner, becomes his best friend, and goes on an adventure," answers a few selector cards, approves a production plan, and gets a finished video in Review - without ever seeing the dashboard or understanding a single pipeline stage.
**Status:** Phases 1-3 of 6 CODE COMPLETE + build/offline verified (backend intake engine + chat-first frontend + live friendly progress). All three are gated on ONE backend+frontend deploy + migration 060 for the live proof. Ryan added a direct Anthropic key to his profile. Plan approved 2026-06-22.
**Updated:** 2026-06-22

Full plan (with architecture + verified file references): `~/.claude/plans/streamed-zooming-pascal.md`

---

## Decisions locked (with Ryan, 2026-06-22)
1. **Brain = guided producer intake**, not an autonomous agent. Claude runs the Step 1-8 flow; post-creation edits route through the existing `claude_orchestrator`.
2. **Surface = chat becomes home.** `/` is the chat; dashboard moves to `/dashboard`; existing pages tuck under an "Advanced" nav group.
3. **Done bar = build now, prove on working stages.** Kie.ai (image/video) may be banned; intake + script work today. Full image/video validated the moment Kie is restored.
4. **Plan file = this is the new north star;** the old "lock the visual chain" plan folds in below as **Track B**. Old GOAL.md backed up (GOAL.md.bak-20260622-092738).

## Architecture (verified against the code)
- Intake is a **separate layer** from the orchestrator (orchestrator needs a video_id; intake ends in `create_video`).
- **One Claude call per chat turn, structured JSON out** (not streamed, not tool-use): `{assistant_text, phase, questions?, cards?, plan?}`. Copy `originality.py:356-383` direct-Anthropic + fence-strip + fail-soft. Use a DIRECT `ANTHROPIC_API_KEY` so a Kie outage never blocks intake.
- **Spec -> video:** backend derives `pipeline_stages` from the workflow card (Full->None, Research Only->[research], Script Only->[script], Script+Assets->[script,images], Custom->picked), runs it through `normalize_stage_plan` (status_map.py:283), then calls `create_video` as a function (videos.py:182) and schedules `run_next_step` (create_video does NOT auto-start).
- **Friendly progress:** 5 UI states mapped in status_map.py, fed to the UI via a `friendly` field on the existing SSE `stage_change` event (consumed by `use-pipeline-sse.ts`).

---

## Phase 1 - Producer brain (backend intake engine)  `[code complete; live proof pending deploy]`
Goal: one `/api/chat` endpoint that turns a sentence into questions -> cards -> plan -> created video + kicked-off pipeline.
- [x] `backend/routes/chat.py` - APIRouter `/api/chat`, `chat_turn` handler; load/create conversation, intake vs. follow-up branch, on approve map spec -> CreateVideoRequest -> `create_video` -> schedule `run_next_step`. Pydantic models here.
- [x] `backend/producer_prompt.py` - PRODUCER_SYSTEM_PROMPT + build_system_prompt(channel_brief) + call_producer() (direct Anthropic, fence-strip, fail-soft + self-test).
- [x] `backend/migrations/060_chat_conversations.sql` - one JSONB-transcript table, tenant-scoped + RLS; appended to schema.sql. (059 was taken -> numbered 060.)
- [x] Registered router in `backend/main.py`; appended FRIENDLY_STATE + FRIENDLY_STATE_ORDER + friendly_state() to `backend/status_map.py`.
- [x] Verified offline: py_compile all touched files; logic checks pass (friendly_state, workflow->stages via real normalize_stage_plan, spec->CreateVideoRequest, jsonb coercion, fail-soft). routes/chat.py imports clean.
- [ ] LIVE PROOF (needs deploy gate): apply migration 060 to prod DB + a live ANTHROPIC_API_KEY, then `curl POST /api/chat` (dragon sentence) -> questions -> cards -> plan; `approve` creates a real video with the right `pipeline_stages` and status advances. Spends ~1-2 Claude calls (~$0.02).
Reuse confirmed: `create_video` + `CreateVideoRequest`, `normalize_stage_plan`/`first_status_for_plan`, `PipelineExecutor.run_next_step`, originality.py call pattern. Every chat query carries `WHERE tenant_id = $1` (manual isolation).

## Phase 2 - Chat-first surface (frontend)  `[code complete; live proof pending deploy]`
Goal: a new user lands on chat, types one sentence, answers cards, approves, sees the video created - no dashboard.
- [x] `frontend/src/app/page.tsx` authed branch now renders `<ChatHome/>` (was the Production Overview dashboard). NOTE: a richer `/dashboard` route already existed (onboarding-aware: WelcomeQuest, FirstRunChecklist) and is where login/onboarding landed - so I pointed the sidebar "Dashboard" there instead of moving the old overview. Old Production Overview kept exported-but-unused in page.tsx (cleanup task spawned).
- [x] `frontend/src/components/chat/ChatHome.tsx` - welcome screen + example prompts, message thread, composer, `SelectorCards`, `ProductionPlanCard` ("Make it"), created-confirmation. Reuses GlassCard/ActionButton/tokens/Framer Motion.
- [x] `frontend/src/lib/api.ts` - `sendChatTurn()` + Chat types.
- [x] `sidebar.tsx` - "Chat" at `/` (top), "Dashboard" -> `/dashboard`, everything else under an "Advanced" heading. Extracted `renderNavItem`.
- [x] Made chat the true landing: login + onboarding redirects changed `/dashboard` -> `/`.
- [x] Verified: `tsc --noEmit` clean; `npm run build` clean (all 33 routes compile incl. / and /dashboard).
- [ ] LIVE PROOF (deploy gate): with the backend deployed (Phase 1) + a token, load `/`, drive the dragon sentence -> cards -> plan -> created video; screenshot. (SE authed pages can't be browsed locally - documented limitation; build is the local gate.)
Done when: from `/`, the dragon sentence drives intake to an approved plan + created video (browser-verified, screenshot); existing pages reachable under Advanced.

## Phase 3 - Friendly progress in chat  `[code complete; live proof pending deploy]`
Goal: after approval, chat shows a live plain-English progress tracker.
- [x] Added `friendly` to the SSE `stage_change` event (routes/pipeline.py) via `friendly_state()`; added `friendly` to SSEStageChangeEvent type.
- [x] CreatedCard in ChatHome.tsx renders the live 5-state tracker off `usePipelineSSE` (done/active/pending), with graceful failure surfacing (Kie/stage errors -> "ask me to try again", not a crash).
- [x] Verified: backend py_compile + friendly_state check; frontend tsc + next build clean.
- [ ] LIVE PROOF (deploy gate): approve in chat, watch the tracker advance off the real pipeline.
Done when: approving shows live friendly progress driven by the real pipeline (proven through script); failed stages surface gracefully.

## Phase 4 - Channel intelligence in the producer  `[todo]`
Goal: with a channel connected, the producer's titles/hooks/thumbnail directions + length reflect proven channel patterns.
- [ ] `backend/producer_channel_brief.py` - build_channel_brief() reusing `discovery._get_learnings_context`, top competitor videos by VPH, the `projects` row. Fail-open.
- [ ] Inject the brief into the producer system prompt.
Done when: a tenant with learnings gets channel-aware titles/hooks; a tenant with no channel gets a sensible generic plan.

## Phase 5 - Conversational follow-up edits  `[todo]`
Goal: after a video exists, follow-up messages drive the pipeline through chat.
- [ ] chat.py forwards post-creation turns to `claude_orchestrator.decide/execute`.
- [ ] ~20-line fix in `claude_orchestrator.py`: seed decisions from the populated `skill_to_method` map + status_map instead of the empty external registry.
Done when: a follow-up ("make it shorter", "redo the thumbnail") triggers the correct stage re-run and reports back in plain English.

## Phase 6 - Polish + full-pipeline proof (Kie-gated)  `[todo]`
Goal: a brand-new user creates a finished video from a single sentence, chat alone.
- [ ] Empty/loading/error states, mobile layout, Advanced discoverability.
- [ ] End-to-end finished-video proof the moment Kie.ai is restored.
Done when: cold-start user -> one sentence -> finished video in Review, no dashboard needed.

---

## Track B - output quality (folded-in visual chain)  `[parallel, Kie-blocked]`
Makes the *output* trustworthy while the chat work makes the *experience* trustworthy. Carried over verbatim from the prior GOAL.md.

- **Phase B1 - kill invented-character bug, lock scenes 1-2 storyboards** `[done 2026-06-20]` - per-beat CLOSED CAST from script speakers, temp 0.9->0.35, high-precision validator, documentary leak removed. Scenes 1-2 grids viewed + adversarially verified PASS. Proof video 3d5aa0ca, tenant ee93e6d1.
  - Residual: the bot.py fix is a LIVE working-tree edit on the VPS (backup bot.py.bak-20260620-045936) - commit it to the repo so a git pull can't clobber it.
- **Phase B1.5 - grid layout + narration-drift fixes** `[deployed, rebuild Kie-blocked]` - strict even 3x3 grids; fixed the duplicate-title data bug (4 methods in supabase_adapter.py now filter video_id + exclude deleted); 3d5aa0ca's own 53 image prompts generated. BLOCKED rebuilding scenes 1-2 storyboards by the Kie.ai Claude gateway ban ("用户已被封禁"). Needs Ryan to fix the Kie.ai account.
- **Phase B2 - lock the canon (production bible)** `[todo]` - character/env/prop continuity everything cites; tighten location `scenes_present`.
- **Phase B3 - Scene 2 full chain to clips** `[todo]` - extract panels, image-set gate, clips (i2v motion-only), scene review.
- **Phase B4 - scale to all scenes** `[todo]` - repeat the gated chain for scenes 3-8 with cross-scene continuity.

---

## Log
- 2026-06-22 - Phase 3 code complete. SSE stage_change now carries a `friendly` state; chat's CreatedCard renders the live 5-state tracker (done/active/pending) with graceful Kie/stage-error surfacing. Also fixed a real gap: the producer reads a DIRECT Anthropic key, but Ryan's key lives in the per-tenant Vault - so chat.py now loads `anthropic_api_key` from Vault and passes it to call_producer (clear "add a key" message if absent). Backend py_compile + frontend tsc/build all clean. Ready for the single deploy + live proof.
- 2026-06-22 - Phase 2 code complete. Chat is now the home screen (ChatHome.tsx: welcome + examples, thread, composer, selector cards, production-plan card, created confirmation); sidebar reorganized (Chat / Dashboard / Advanced group); login + onboarding now land on chat. Discovered a pre-existing /dashboard route (onboarding-rich) that login/onboarding already used -> pointed sidebar "Dashboard" there; left the legacy Production Overview exported-but-unused (cleanup task spawned). tsc + next build both clean (33 routes). Live proof batched with Phase 1 into one deploy.
- 2026-06-22 - Phase 1 code complete. Built backend/routes/chat.py (intake + follow-up branches, spec->create_video mapping, pipeline kickoff), backend/producer_prompt.py (producer system prompt + direct-Anthropic call_producer, fail-soft, self-test), migration 060 + schema.sql, status_map FRIENDLY_STATE + friendly_state(), main.py router. py_compile clean; offline logic checks all pass; routes/chat.py imports clean. Live HTTP proof pending a backend deploy + migration apply (prod DB + ~$0.02 Claude) - holding for Ryan's go per the prod/cost rule.
- 2026-06-22 - New north star set: chat-first creative producer. Comprehensive planning session run; architecture verified against the code (claude_orchestrator + pipeline_executor reused; intake is a new separate layer; structured-JSON turns; create_video called as a function; friendly-state SSE). Plan approved, 6 phases + Track B. Old GOAL.md (visual chain) backed up to GOAL.md.bak-20260622-092738 and folded in as Track B. Starting Phase 1 (backend intake engine).
- 2026-06-20 - (Track B1) Phase done. Structural invented-character fix in skills/video-pipeline/storyboard/bot.py; all gates PASS on scenes 1-2, verified by direct viewing + adversarial review.
- 2026-06-19 - (Track B) Confirmed the storyboard directive (not per-shot prompts) invented people; built the structural fix.
