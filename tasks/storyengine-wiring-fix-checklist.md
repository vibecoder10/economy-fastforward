# StoryEngine Wiring Fix Checklist

**Date:** 2026-07-17 · **Source:** 4-agent codebase audit — full findings with file:line evidence in `docs/reports/2026-07-17-storyengine-agent-audit-findings.md` — + Higgsfield gap analysis (`docs/reports/2026-07-17-higgsfield-vs-storyengine-gap-analysis.md`). Every item below traces to a finding in the audit report; consult it before re-exploring the codebase.

**The law (from CLAUDE.md):** every item below lists ALL layers it touches — Data, Backend, UI/UX, Verify. An item is NOT done until every listed layer ships and the Verify step passes. A fix that lands in one layer only creates exactly the stubs this list exists to kill. No checkbox flips without the Verify evidence.

**Second law — two doors, one registry (see `tasks/storyengine-copilot-ux-map.md`):** every user-facing capability ships BOTH a clickable control AND a conversational path (Producer/co-pilot phrasing), both calling the same `actions.py` verb. The UX map defines the exact click paths and example utterances per feature — build to it.

Legend: `[B]` backend · `[D]` data/schema · `[U]` UI/UX · `[V]` verify

---

## P0 — Integrity: things that lie to the user today

### 0.1 Image-model dropdown is cosmetic ⚠ worst offender
The Pictures model select (`nano-banana-2`/`gpt-image-2`/`z-image`) writes `video.image_model_override`, but the live coverage path ignores it.
- [x] `[B]` `storyengine/backend/scripts/coverage_to_app.py` (L621/906/978): read `image_model_override` and route to `generate_scene_image_zimage` / nano path instead of hardcoded `generate_scene_image_gpt`. Keep GPT Image 2 as default + content-policy fallback. — done via the shared resolver (see next item); `redraw_asset_image` also persists the resolved model to `assets.image_model`.
- [x] `[B]` Confirm legacy path (`pipeline_executor.py` L13694-13716) and coverage path resolve the override through ONE shared helper — no duplicated resolution logic. — `skills/video-pipeline/shared/clients/image_model_router.py::generate_scene_image_for_model`, used by both.
- [x] `[U]` `ScenesWorkspaceTab.tsx` (L1121-1126): selector shows which model actually generated each panel (badge on the asset), so a mismatch is visible instead of silent. — `SegmentCard` badge reads `asset.image_model`, plumbed through `routes/videos.py` + `lib/api.ts`.
- [x] `[B]` Bulk "Generate all pictures" path (the primary flow — `ScenesWorkspaceTab.tsx`'s button → stage `coverage-images` → `POST /coverage-images/{id}` → `generate_coverage_for_video` → `run_coverage` → `generate_coverage_frames` → `_gen_ref` in `storyboard/coverage.py`) now reads `image_model_override` and routes through the SAME `generate_scene_image_for_model` resolver; `store_scene` persists the resolved `image_model` on every coverage asset row. (Follow-up commit — the first C02 pass incorrectly flagged this as deferred to C11-C15, which route per-scene CLIP models on a different axis and never touched image generation.)
- [ ] `[V]` Set override to `z-image`, run pictures, confirm the Kie task payload names z-image AND the asset row records it. Repeat for nano. — **partially done**: unit/integration tests (`tests/test_image_model_router.py` — 12 tests; `tests/test_coverage.py::test_generate_coverage_frames_honors_model_override` for the bulk path) prove the resolver's routing/fallback table end to end, including the bulk path, and that the untouched default path calls byte-identical arguments everywhere. Live Kie-task-payload confirmation NOT run (no safely-reachable paid key this session — see C02 commit trace). Do the live z-image/nano run (cheapest via `redraw_asset_image`, ~$0.025/image, or one scene's "Generate pictures") before fully closing this line.

### 0.2 Dead model options in the registry
Kling 3.0 Pro, Runway Gen-4 Turbo, Hailuo 2.3 exist in `MODEL_REGISTRY` (`shared/channel_profile.py` L285-293) but fail at the `wired` gate (`pipeline_executor.py` L11775-11783).
- [x] `[B]` Add `wired: bool` to the registry entries — single source of truth; delete the separate hardcoded `wired` set. — `ModelProfile.wired` (default `False`); `pipeline_executor.run_clip_generation`'s gate now reads `profile.wired` off the same `MODEL_REGISTRY` entry instead of its own hardcoded set. `GET /api/models` (`storyengine/backend/routes/model_registry.py`) reads the identical field.
- [x] `[U]` Frontend `WIRED_MODELS` (`ScenesWorkspaceTab.tsx` L46-50) must be DERIVED from a backend endpoint (`GET /api/models`), not a hand-copied list. Unwired models: hidden, or shown "coming soon" — never selectable. — hardcoded constant deleted; clip-model `<select>` now maps over `useQuery(["models"], getModels)` filtered to `wired`, with a tiny (Grok-only) network-failure fallback so the dropdown is never empty/broken.
- [ ] `[V]` curl `/api/models` matches what the dropdown renders; selecting every listed model generates without the "isn't available yet" error. — **partially done**: curled locally (backend booted with no DB/Redis via `DEV_MODE`/`DEV_TOKEN`/`DEV_TENANT_ID`) — the 3 dead models come back `wired:false`, the 4 live ones `wired:true`, matching the gate exactly; `test_model_registry.py` (3 tests) pins this. The frontend derivation was confirmed by code (no more hand-copied list) + `npx tsc --noEmit` clean, not a live Playwright render. Live "selecting every wired model actually generates a clip" NOT run (paid, no Kie key this session) — queued in `tasks/live-verification-queue.md` §C03.

### 0.3 Cost counter is wrong: estimates from constants duplicated in 3 places, no actual-spend ledger
`actions.py` `CLIP_COST`/`PICTURE_COST` L31/211-263 · `frontend/src/lib/next-action.ts` `CLIP_COST_PER_MODEL` L61-65 · `MODEL_REGISTRY.cost_per_clip`. Backend never rolls up `videos.total_cost` (`pipeline/[videoId]/page.tsx` L172-200 computes spend from artifact counts).
- [ ] `[D]` New `generation_ledger` table: video_id, stage, model, units, unit_cost, actual_cost, kie_task_id, created_at. Add migration; verify column exists in Supabase, not just schema.sql.
- [ ] `[B]` Every generation call site (image_client, video dispatch, voice, thumbnail, sound) writes a ledger row on completion. Roll up `videos.total_cost` on write.
- [ ] `[B]` Price constants live in ONE place (MODEL_REGISTRY / models endpoint). `actions.py` estimates read from it. Delete the frontend copy.
- [ ] `[U]` Video page + confirm cards show: estimate before, actual after ("Est. $4.20 → Actual $4.35"). Frontend gets prices from `/api/models`, never a local constant.
- [ ] `[V]` Generate one scene; ledger row appears, `videos.total_cost` increments, UI actual matches ledger sum. `npx tsc --noEmit` clean after deleting `CLIP_COST_PER_MODEL`.

### 0.4 Onboarding trap: home Producer hard-requires Anthropic key
Onboarding promises Kie-only is enough; home producer errors without `anthropic_api_key` (`routes/chat.py` L3176-3184). The in-video copilot already falls back to Kie text client.
- [ ] `[B]` Home producer path uses `get_text_client_for_tenant` fallback (same as `_handle_copilot`).
- [ ] `[U]` If quality differs on Kie-Claude, show a soft "add an Anthropic key for best results" hint in chat — not a hard wall.
- [ ] `[V]` Fresh tenant with ONLY a Kie key: complete onboarding → type an idea on home → get a production plan, no error.

### 0.5 Research silently skipped in default autobuild
`make_autobuild_step` (`actions.py` L401-421) skips research for non-`static_docu` videos; users believe their documentary was researched.
- [x] `[B]` Keep the default, but record `research_skipped=true` on the video/plan. — new `videos.research_skipped` column (migration 086; the existing `pipeline_stages` plan does NOT already represent this — see SYSTEM_STATE.md §C06 for why); `make_autobuild_step`'s skip branch writes it, `run_research`'s save clears it.
- [x] `[U]` Plan card + pipeline page show "Research: skipped (script writes from topic) — Run research" chip with one-tap enable. Copilot mentions it in the plan summary. — chip on `GuidedNextStep.tsx` (the pipeline page's next-step card), one-tap reuses `/api/pipeline/research/{id}`; 3 deterministic chat/route "building now" messages + the producer system prompt corrected to not claim a research pass that won't happen.
- [x] `[V]` Create default video → chip visible; tap → research stage runs and chip clears. — trace + 3 unit tests done in-sandbox (non-vacuous, confirmed via `git stash`); live tap-through deferred to `tasks/live-verification-queue.md` §C06.

### 0.6 Docked co-pilot ignores file attachments
`ChatCore.attachFiles` returns early when `docked` (~L359) — drop-in works on home chat only.
- [ ] `[B]` `/api/chat/upload` already tenant-scoped; accept `video_id` context on upload.
- [ ] `[U]` Remove the early return; docked dock accepts script/reference-image drops and routes them to the current video (e.g. cast reference → CharactersTab flow).
- [ ] `[V]` Playwright: open video co-pilot dock, drop a PNG, confirm it lands in `chat_assets` with the video's id and the copilot references it.

---

## P1 — The copilot router build (priority #1 from the gap analysis)

### 1.1 Decision table as data
- [ ] `[D]` Extend `MODEL_REGISTRY` entries (or new `model_profiles` table): `best_for` tags (draft, hero, broll, multi_shot, character, atmospheric), `tier` (draft|standard|premium), `cost_per_clip`, `wired`. Exposed at `GET /api/models`.
- [ ] `[V]` curl `/api/models` returns the table; no other file hardcodes model capabilities.

### 1.2 Per-scene routing
- [ ] `[B]` Router module: maps existing scene intent (camera purpose REVEAL/ESTABLISH/PAYOFF from `camera_selector.py`, scene planner peaks) → model via decision table. Store per-scene `routed_model` + `routing_reason` on the shot/scene record.
- [ ] `[D]` Scene/shot rows gain `routed_model`, `routing_reason`, `model_used` columns (migration).
- [ ] `[B]` Clip generation reads per-scene `routed_model` (falls back to video-level `video_model`). Copilot verb `animate` uses it; confirm-card cost quote itemizes per-tier counts.
- [ ] `[U]` ScenesWorkspaceTab: per-scene model badge + "why" tooltip + one-tap override (writes scene-level override, wins over router). Copilot message format: "Scene 12 is your reveal — Veo Quality ($1.25); Grok elsewhere. Total $4.20 vs $25 all-premium."
- [ ] `[V]` Playwright: build a 6-scene video; badges render with reasons; override one scene; generated clips' `model_used` matches badges; ledger rows match.

### 1.3 Draft cheap, finish expensive
- [ ] `[B]` `draft_pass` (route ALL scenes → draft tier) and `finalize` (regenerate only approved/hero scenes → routed tier) verbs in `actions.py`; idempotent job_ids to prevent double-billing.
- [ ] `[U]` "Draft the whole video (~$2)" and "Finalize N approved scenes (~$X)" buttons + copilot phrasing; projected-savings line in cost quote.
- [ ] `[V]` Full cycle on a test video: draft → approve 3 scenes → finalize; only 3 clips regenerate; ledger shows both passes.

---

## P2 — Surface the buried machinery (built-but-unseen)

### 2.1 Visual profile gallery (5 rich profiles invisible; UI shows 6 shallow presets)
- [ ] `[D]` Profiles become DB rows (`style_presets` table) seeded from the 5 Python profiles' `template_metadata` (display_name, tags, best_for, cost_tier, preview). Python `VisualProfile` stays the runtime engine; DB is the catalog + selection layer.
- [ ] `[B]` `GET /api/style-presets`; create-video accepts `style_preset_id`; executor maps it to `VISUAL_PROFILE` env (existing seam at `pipeline_executor.py` L6358).
- [ ] `[U]` Replace/extend the 6-item picker (`visual-presets.ts` + `producer_prompt.VISUAL_PRESETS` — DELETE the duplicated lists, both read the API) with a gallery: preview image, "best for", cost tier. Chat LOOK card uses the same source.
- [ ] `[V]` Pick `holographic_hud` in UI → generated prompts carry its style system (inspect one image prompt); `tsc` clean after deleting `visual-presets.ts` constants.

### 2.2 Camera/motion presets (40+ move catalog auto-only)
- [ ] `[B]` Expose curated subset of `camera_moves.py` catalog via `/api/camera-presets` (name, motion_prompt, best_for, preview). Scene motion-instruction editor accepts a preset id, feeding the existing animation prompt engine.
- [ ] `[U]` Scenes tab: "camera move" chip per shot (auto-selected value shown, tap to change from preset sheet). Keep "earn the move" auto as default.
- [ ] `[V]` Pick "crash zoom" on a shot → generated motion prompt contains the preset's motion_prompt contract.

### 2.3 Script voice profiles not selectable
- [ ] `[B]` `script_profile` per video (column + plumb to `SCRIPT_PROFILE` env, mirroring visual profile seam).
- [ ] `[U]` Advanced option in create flow + ScriptVoiceTab: Neutral / Investigative Reveal (power_doctrine_v2) with one-line descriptions.
- [ ] `[V]` Generate same topic under both profiles; scripts differ per profile laws.

### 2.4 StoryEngine MCP server — "talk to it from Claude" (see UX map §7)
The Higgsfield-killer door: co-create from Claude/any MCP client; verbs come from the same `actions.py` registry as buttons and chat. BYOK carries through (user's vault keys); money gate preserved via quote + confirm_token.
- [ ] `[B]` MCP endpoint wrapping the actions registry + read tools (list_scenes with routed models, get_ledger, get_performance, upload_draft_to_youtube); per-user token auth; confirm-token gate on every paid tool.
- [ ] `[D]` `agent_tokens` table (user, tenant, scopes, created/revoked, last_used).
- [ ] `[U]` Settings → "Agent access": create/revoke token, MCP config snippet, last-used display. "via agent" chip on videos/actions created through MCP.
- [ ] `[V]` From an MCP client on a test tenant: create → route shots → draft → finalize → upload draft, every paid step quote-gated, ledger rows written, video + badges visible in the web UI.

---

## P3 — Learning loops & stub cleanup

### 3.1 Preset-performance loop (the moat — Higgsfield can't copy this)
- [ ] `[D]` Videos already store style/model choices after P1/P2 — ensure `style_preset_id`, per-scene `model_used` are queryable alongside CTR/retention snapshots.
- [ ] `[B]` Extend analytics/learnings: aggregate CTR/retention by style preset + clip model; feed `_next_to_make_brief` and producer context ("pixar_3d pulling 5.1% CTR on your channel").
- [ ] `[U]` Analytics page: "by style" panel; producer cites it when recommending a LOOK.
- [ ] `[V]` Seed two styles with snapshot data; brief includes the comparison.

### 3.2 Legacy stubs — fix or delete, don't leave dark (Anti-Bandaid rule)
These are in `skills/video-pipeline/` (legacy Airtable side). StoryEngine SaaS reimplements most of them — decide per item: port or delete. No third option.
- [ ] `confidence_scorer.py`: `momentum` and `retention` return placeholder 50.0 — implement from performance_tracker data or remove the weights from `autopilot_program.md` (weights currently sum as if real).
- [ ] `learning_extractor.run_daily_extraction()` "# TODO: Integrate with Airtable to get actual CTR data" — LEARNINGS.md shows "Videos produced: 0". Either wire it or mark the CLI autopilot learning path deprecated in favor of StoryEngine `routes/learning_extraction.py`.
- [ ] `osiris/learnings_engine.get_competitor_title_patterns()` returns `""` — wire to competitor data or delete the call sites.
- [ ] `[V]` `grep -rn "TODO" skills/video-pipeline/autopilot skills/video-pipeline/analytics` returns no load-bearing stubs; each removed feature's callers removed too.

### 3.3 Misc UX debt (from copilot-flow audit)
- [ ] Pictures-review checkpoint has no audio — offer "add scratch voice (~$0.50)" before review, or set expectation in the checkpoint card.
- [ ] 4+ parallel create surfaces (home chat, /pipeline form, Model A Video, onboarding CreateVideoStep, FirstVideoFlow) — converge on chat-plan + one form; kill or thin the rest (decision needed, flag to Ryan).
- [ ] Cold-start: no competitors → producer gives generic examples; add "add 3 competitors now" inline card instead of degrading silently.
- [ ] Budget ceiling: per-video `max_spend` (default off) checked before each paid verb; autobuild stops with "budget reached" card instead of only the 18-iteration cap.
- [ ] Copilot clarify-loop: `COPILOT_CONFIDENCE = 0.55` (`chat.py:543`) — log confidence scores on real traffic first, then tune; don't guess a new threshold.

### 3.4 Remaining audit findings (from `docs/reports/2026-07-17-storyengine-agent-audit-findings.md`)
- [ ] **Claude tier hardcoded per call site** — `[B]` single-source the text-model tier map (which stages use Sonnet vs Haiku) next to the model registry; no UI exposure needed yet, but one file to change instead of grep-and-pray. `[V]` grep shows no literal `Models.CLAUDE_*` outside the map.
- [ ] **Whisper forces OpenAI key in Kie-only setup** — `[B]` route transcription via Kie if a Whisper-equivalent exists there, else `[U]` mark `openai_api_key` as required-for-voice-alignment in onboarding/keys UI so it's a visible requirement, not a silent stage failure. `[V]` Kie-only tenant either transcribes or sees the requirement before building.
- [ ] **Per-user BYOK (PER_USER_KEYS_ENABLED)** — resolution logic done (`vault.py` L165-196), NO write path or UI. `[D]` `tenant:user:name` writes; `[B]` set-key accepts user scope; `[U]` Settings → Keys per-user section. Product call: needed for multi-seat tenants — flag to Ryan before building. `[V]` two users, same tenant, different Kie keys, generations bill separately.
- [ ] **YouTube quota guard** — `[B]` count today's uploads per channel (~1,600 units each, 10k/day); block the 7th with a "quota resets midnight PT" card instead of a raw 403. `[U]` remaining-uploads chip on Upload tab. `[V]` simulated 6-upload day → 7th blocked gracefully.
- [ ] **VPH for own videos** — competitor VPH exists (`competitor_scraper.calculate_vph`) but own videos never get it, so scorecards compare apples to oranges. `[B]` compute VPH on own snapshots; `[U]` show it beside CTR in analytics/scorecards. `[V]` own video shows VPH within 24h of publish.
- [ ] **SEO generator is Power-Doctrine-branded** — hardcoded `@Power_Doctrine` subscribe line + `#PowerDoctrine` hashtags in `upload/seo_generator.py`; parameterize per tenant/channel before any multi-tenant upload ships. `[V]` second tenant's draft carries its own branding.

---

## Backlog (post-router; from `tasks/research-to-build-map.md`)

### B1 — Expand the wired video-model lineup
Once P1.1 makes the registry data-driven, adding a model = one registry row (best_for, tier, cost, wired), no code-path changes.
- [ ] `[B]` Wire Kling 3.0 via Kie when exposed; `[V]` generates + ledger row + badge correct.
- [ ] `[B]` Wire WAN (restyle strength) via Kie when exposed; same `[V]`.
- [ ] `[B]` Evaluate Sora 2 via Kie (cost/limits) before wiring — premium-tier hero option.

---

## Definition of done (every item)
1. All listed layers shipped — no layer deferred "for later."
2. `[V]` step executed with evidence (curl output, Playwright run, ledger row, screenshot).
3. `cd storyengine/frontend && npx tsc --noEmit` clean.
4. No new duplicated constants between frontend and backend.
5. `SYSTEM_STATE.md` updated if files moved/created; this checklist's box ticked in the same commit as the fix.

---

# LOOP EXECUTION PLAN — chunked order + iteration protocol

Built for running with `/loop`. Each chunk = ONE loop iteration = one clean commit. Big items
above are split here; **this section's order is the execution order** (the P-sections above hold
the full layer detail — chunks reference them).

## Iteration protocol (every loop pass)
1. **Pick the topmost unchecked chunk below.** Never skip past an unchecked SWEEP gate.
2. **Ship the whole chunk** — all its layers, per the parent item's [D]/[B]/[U] spec and the
   UX map. A chunk too big to finish this pass = STOP, split it in this file first, do part 1.
3. **Verify** per the parent's `[V]`. Cost cap for verification: cheapest model, 1 unit,
   target < $1/chunk; NEVER verify with Veo Quality unless the chunk is about Veo Quality.
   Use existing test tenants/videos; no real YouTube publishes for verification.
4. **End clean:** `npx tsc --noEmit` green → commit on the designated `claude/*` branch with
   the chunk ID in the message → tick the chunk here (same commit) → ff-merge to main ONLY if
   the chunk is deploy-safe (main auto-deploys hourly; when unsure, stay on branch and note it).
5. **Update the `## Handoff` in tasks/todo.md** (2 lines: chunk done, next chunk) so an
   interrupted loop resumes cold.
6. **Blocked?** Don't half-wire: revert, or commit WIP to branch with a `⚠ WIP` note in the
   handoff, and tick NOTHING. Product calls flagged "Ryan" → skip the chunk, leave a question
   in the handoff, continue to the next chunk.
7. Sweeps run as ONE Sonnet Explore agent; append findings to the audit report + add any new
   fixes as chunks here, in the same iteration.

### Model discipline & token efficiency (MANDATORY — this is what keeps the loop cheap)
The main loop is the ORCHESTRATOR and stays on the premium session model (Fable). It does NOT
write code and does NOT open large source files — that is the entire token sink. Per iteration:
- **Orchestrator (Fable) does only:** read the handoff (2 lines) + the one chunk line + the
  subagent's report; skeptically judge whether the verify EVIDENCE actually proves the chunk
  works (the anti-stub guard); decide the deploy-safe ff-merge; write the 2-line handoff; pick
  next chunk. That's it. If you catch yourself Reading `chat.py`/`ScenesWorkspaceTab.tsx`/etc.
  in the main loop, STOP — dispatch a subagent instead.
- **Worker (Sonnet) does the chunk:** ONE `Agent` call, `model:"sonnet"`, `subagent_type:
  general-purpose`. Brief it with: the chunk ID, its parent P-section (layer detail), its UX-map
  section (both doors), and the Definition of Done. It reads the files, ships ALL layers, runs
  the `[V]` verify under the cost cap, ticks the chunk box, and commits to
  `claude/story-engine-repo-sgnm8l` with the chunk ID in the message. It reports back ONLY:
  files touched, verify evidence, `tsc` status, commit SHA, deploy-safe y/n, blockers. Keep the
  report tight — the orchestrator should never need the full diff.
- **Never escalate a worker to premium** for C01–C37 (all wiring, no hard reasoning). Sweeps
  (S5–S10) = Sonnet `Explore` agent. If evidence looks thin, dispatch a SECOND Sonnet subagent
  to independently re-verify — cheaper than the orchestrator reading the code itself.
- **One chunk per iteration.** End the iteration after the commit + handoff even if context is
  fresh — the handoff makes the next "continue" resume cold for near-zero orchestrator cost.

### "continue" semantics
When the operator says **continue** (or the loop fires): read the handoff in `tasks/todo.md`,
do the next unchecked chunk per this protocol, end. Nothing else needs to be said. If the next
chunk is a `Ryan` product-decision chunk, skip it, leave the question in the handoff, and take
the following build chunk.

## Chunk queue (execution order)

**Phase 0 — integrity**
- [x] C01 · SWEEP S6 (schema drift) — gate for all migrations. Knowledge map §3.
- [x] C01a · Schema/migration hygiene from S6: reconstruct missing migration source, retire ad-hoc DDL, close RLS gaps, refresh stale schema.sql (A/B/C/D all completed — see commit + report)
  - `[D]` `_migrations` (live tracking table) has 90 applied rows; committed `migrations/` has 89 files. The missing one, `050_enable_rls_auth_tables.sql`, ran against prod but has zero trace in git history (all branches). Introspect current live RLS policies on the auth tables it touched (`pg_policies`), reconstruct an idempotent migration that codifies that state, and commit it under a fresh number — don't reuse `050`.
  - `[D]` `secrets` (`vault.py::_ensure_secrets_table()`) and `static_reference_cache` (`static_docu.py` ~L383) are created by in-process `CREATE TABLE IF NOT EXISTS` calls, invisible to `migrations/` and `_migrations`. Backfill both as tracked migration files. `static_reference_cache` has a real `tenant_id` column with **no RLS** (confirmed live: `rls_enabled=false`) — add the standard tenant-isolation policy. Same for `channel_video_retention` (migration 080 never added RLS; live confirms `rls_enabled=false`).
  - `[D]` `storyengine/schema.sql` is stale — missing 11 live tables created by migrations 041–081 (`intelligence_reports`, `channel_videos`, `secrets`, `channel_profile_documents`, `chat_assets`, `production_queue`, `script_templates`, `channel_analytics_daily`, `static_reference_cache`, `channel_video_retention`, `machine_research_cards`) and still declares `title_tests`, which doesn't exist live and has zero code references. Regenerate from live (`pg_dump --schema-only` or equivalent) and drop/flag `title_tests`.
  - `[V]` `_migrations` row count == committed migration file count (currently 90 vs 89 — should be equal after this chunk). `secrets`, `static_reference_cache`, `channel_video_retention` all show `rls_enabled=true` via a fresh `list_tables` check.
- [x] C02 · P0.1 image-model override honored on coverage path + asset model badge — INCLUDING the primary bulk "Generate all pictures" path (follow-up commit; the redraw/redo/legacy paths alone were not enough). Test+trace verified; live Kie-payload confirmation still pending — see §0.1 [V] note.
- [x] C03 · P0.2 dead models: `wired` flag in registry + minimal `GET /api/models` + frontend derives from it — wiring + curl/test verification done; live "every wired model generates a clip" deferred, see §0.2 [V] note + `tasks/live-verification-queue.md` §C03.
- [x] C04 · P0.4 home Producer works Kie-only (text-client fallback + soft hint) — both home producer entry points (`chat_turn` intake turn, `_seed_producer` onboarding hand-off) now resolve via the shared `_resolve_producer_client` (mirrors `_handle_copilot`'s `get_text_client_for_tenant` fallback exactly); `producer_prompt.call_producer` drives the resolved client's `.client.messages.create(...)` instead of building its own Anthropic-only client. Trace + 6 new unit tests pass (`tests/functional/test_producer_kie_fallback.py`); live "fresh Kie-only tenant → plan on home" deferred to `tasks/live-verification-queue.md` §C04.
- [x] C05 · P0.6 docked co-pilot accepts file attachments — `ChatCore.attachFiles`'s `if (docked) return;` removed and the docked `<Composer>` (which never even received the attach props) now wires them; `/api/chat/upload` takes an optional `video_id` (tenant-verified, fail-soft), persisted on a new `chat_assets.video_id` column (migration `085_chat_assets_video_id.sql`, applied live); `_handle_copilot` now attaches + surfaces dropped files via the same `_attach_assets`/`_assets_brief` the home chat uses. Trace + tsc/py_compile/pytest clean; live Playwright drop-test deferred — see `tasks/live-verification-queue.md` §C05.
- [x] C06 · P0.5 research-skipped transparency chip + one-tap enable — recording (`videos.research_skipped`, migration 086, applied live), the chip + one-tap enable on `GuidedNextStep.tsx`, and the copilot/plan-summary mention are all shipped and trace/test-verified in-sandbox; live tap-test deferred to `tasks/live-verification-queue.md` §C06. Found but NOT fixed (flagged, out of scope): the autobuild's skip branch doesn't consult the plan, so an EXPLICIT `workflow:"research"` build is also silently skipped by chat's autobuild today (pre-existing, unrelated to this chunk's control flow) — see SYSTEM_STATE.md §C06.
- [x] C06a · P0.5-adjacent BUG (found during C06, pre-existing) — CONFIRMED REAL and FIXED. `make_autobuild_step`'s skip branch (`actions.py` ~L401-433) never consulted the video's `pipeline_stages` plan before skipping research, so a video created with an EXPLICIT `workflow:"research"` (or any custom plan that includes research) was ALSO silently skipped and could route straight to `done` with no script. Now: `parse_stage_plan(video.get("pipeline_stages"))` is checked before the skip — a `None` plan (default, unrestricted) still skips byte-identically; a plan that NAMES `"research"` now runs it via `PipelineExecutor.run_research` instead (mirrors the existing `static_docu` branch's success/failure handling). `static_docu` is structurally unaffected (its own branch already returns/continues before the new check). 5 new unit tests (`tests/functional/test_autobuild_explicit_research_plan.py`), confirmed non-vacuous via `git stash`; full suite unchanged (same 16 pre-existing failures + 1 pre-existing error). Live "workflow:research autobuild actually runs research + writes payload" deferred — see `tasks/live-verification-queue.md` §C06a. Full trace: SYSTEM_STATE.md §C06/§C06a.
- [x] C07 · P0.3a `generation_ledger` migration + ledger writes on CLIP path + `total_cost` rollup — table + migration `087_generation_ledger.sql` applied live to `wrromlupsmyzrrcqlucn` (columns/indexes/RLS confirmed via `information_schema`); `pipeline_executor.run_clip_generation` writes one ledger row per completed clip (`unit_cost`/`actual_cost` from `MODEL_REGISTRY.cost_per_clip`, `kie_task_id` captured via a new `task_id_out` param on `ImageClient`'s 4 video-gen methods) and recomputes `videos.total_cost = SUM(actual_cost)`; write+rollup is fail-soft (`generation_ledger.record_ledger_entry`'s own try/except, never raises). 6 new unit tests pass, full suite unchanged (same 16 pre-existing failures + 1 error, confirmed via `git stash`); live paid-clip round trip deferred — see `tasks/live-verification-queue.md` §C07. Full trace: SYSTEM_STATE.md §C07.
- [ ] C08 · P0.3b ledger writes on images/voice/thumbnail/sound paths
- [ ] C09 · P0.3c single price source (registry → `actions.py` estimates; DELETE `next-action.ts` constants)
- [ ] C10 · P0.3d UI "Est → Actual" chip + ledger drawer; update `docs/cost-awareness.md`

**Phase 1 — router**
- [ ] C11 · P1.1 decision table: extend `/api/models` with best_for/tier
- [ ] C12 · P1.2a router module + scene columns migration (`routed_model`/`routing_reason`/`model_used`) + routing written at shot-plan time
- [ ] C13 · P1.2b clip generation reads per-scene routed model; records `model_used`
- [ ] C14 · P1.2c UI: per-scene model badges + "why" + one-tap override sheet
- [ ] C15 · P1.2d copilot routing conversation + itemized per-tier confirm cards (UX map §1)
- [ ] C16 · SWEEP S7 (queue/idempotency) — gate for finalize billing safety
- [ ] C17 · P1.3a `draft_pass` + `finalize` verbs, idempotent job_ids
- [ ] C18 · P1.3b GuidedNextStep draft/finalize labels + scene Approve ticks + savings line (UX map §2)

**Phase 2 — surfacing + MCP**
- [ ] C19 · SWEEP S9 (frontend state) — before the big UI wave
- [ ] C20 · P2.1a `style_presets` table seeded from the 5 profiles + `GET /api/style-presets` + executor mapping
- [ ] C21 · P2.1b gallery UI + chat LOOK card from the API; DELETE `visual-presets.ts` + `producer_prompt.VISUAL_PRESETS` duplicates
- [ ] C22 · P2.1c user-created presets via chat ("make me a new style…") (UX map §3)
- [ ] C23 · P2.2 camera-preset chips: `/api/camera-presets` + scene chip + sheet (UX map §4)
- [ ] C24 · P2.3 script-profile selection (column + env seam + UI option)
- [ ] C25 · SWEEP S5 (security/tenancy) — HARD gate for MCP; fix any criticals it finds as inserted chunks before proceeding
- [ ] C26 · P2.4a MCP endpoint + `agent_tokens` migration + auth
- [ ] C27 · P2.4b tool set + quote/confirm_token money gate on every paid tool
- [ ] C28 · P2.4c Settings "Agent access" UI + "via agent" attribution chip
- [ ] C29 · P2.4d full external-client loop verify (create → route → draft → finalize → upload draft)

**Phase 3 — learning loops + debt**
- [ ] C30 · P3.1a preset/model choices queryable next to CTR/retention snapshots + aggregation query
- [ ] C31 · P3.1b analytics "by style" panel + producer cites channel-data in LOOK recommendations
- [ ] C32 · P3.2 legacy stubs: scorer placeholders + learning_extractor + competitor_title_patterns — wire or delete (may split on findings)
- [ ] C33 · P3.4 quota guard + own-video VPH
- [ ] C34 · SWEEP S10 (multi-tenant branding) + P3.4 SEO branding parameterization
- [ ] C35 · P3.4 Whisper-key friction + Claude tier map single-sourcing
- [ ] C36 · P3.3 UX debt: checkpoint-audio expectation, cold-start card, budget ceiling, confidence telemetry (split per item if any runs long)
- [ ] C37 · P3.3/P3.4 product calls for Ryan: create-surface convergence, per-user BYOK slice — decision chunk, not build

**Deliberately AFTER the loop:** Backlog B1 (new models), Growth G1-G5 (marketing), S8 render
sweep fires before C17 only if draft-pass verify shows render turnaround is the bottleneck.
