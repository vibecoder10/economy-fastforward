# StoryEngine 4-Agent Audit — Full Findings

**Date:** 2026-07-17 · Four parallel codebase sweeps: copilot/generation flow, model routing/BYOK, YouTube growth loop, styles/presets. This is the EVIDENCE base behind `tasks/storyengine-wiring-fix-checklist.md` — every checklist item traces to a finding here. If a fix seems ambiguous, come back to this file before re-exploring the codebase.

---

## Sweep 1 — Copilot / generation experience

**Architecture facts:**
- StoryEngine is chat-first: home page IS the copilot (`app/page.tsx:46` → `ChatHome`). One shared chat engine (`components/chat/ChatCore.tsx`) in two personas; one shared verb registry (`backend/actions.py:38-88`, ~20 verbs) that chat AND buttons both call — copilot and UI are behaviorally identical by construction. This is the seam the router and MCP build on.
- **Producer** (home): `routes/chat.py` + `producer_prompt.py`, one Claude call/turn (direct Anthropic). Selector cards (LOOK/LENGTH/WORKFLOW), production plan → "Make it" → autobuild to pictures-review checkpoint. Scoring rubrics (VELOCITY×2, CHANNEL FIT×2, FEASIBILITY, MONETIZATION), funnel diagnosis, `profile_ops` channel management by voice (`chat.py:_apply_profile_ops` L1651), file drop-in, "analyze this video" DNA-hold (`_handle_analyze` L1464).
- **Co-pilot** (in-video dock): `chat.py:_handle_copilot` L643, agent-brain tool loop (`agent_brain.py`), classifies read/action/prompt-op. Prompt Studio (`_handle_prompt_op` L1061): view/suggest/rewrite per-shot image/motion/thumbnail prompts as editable cards. Money gate: `_confirm_card` + `_estimate_cost` on every paid verb.
- **Execution:** `pipeline_executor.py` stage methods; `status_map.py` STAGE_ORDER + prereqs (output-driven plans); arq/Redis queue with in-process fallback; SSE progress. 10-tab detail page; GuidedNextStep "one big button" (`lib/next-action.ts`).
- **Intelligence wired into producer context** (`chat.py:3191-3203`): channel intel, competitor winners, "what to make next" scored via autopilot scorer, own analytics, learned patterns; `suggested-models` L3329 (VPH-ranked "worth modeling"); style/length recommendations; scored title suggestions.

**Findings (→ checklist):**
1. Home Producer hard-requires Anthropic key (`chat.py:3176-3184`) while onboarding says Kie-only suffices; dock copilot has Kie fallback — onboarding trap. → P0.4
2. Research silently skipped in default autobuild (`actions.py:401-421`). → P0.5
3. Pictures-review checkpoint has no audio (voice deferred to finish phase). → P3.3
4. 4+ parallel create surfaces with different inputs/intelligence (home chat, /pipeline form, Model A Video, onboarding CreateVideoStep, FirstVideoFlow). → P3.3 (convergence decision)
5. Docked copilot ignores file attachments (`ChatCore.attachFiles` early-return when docked ~L359). → P0.6
6. Cost shown is estimate-from-artifact-counts; `videos.total_cost` never rolled up (`pipeline/[videoId]/page.tsx:172-200`); no budget ceiling (only 18-iteration autobuild cap). → P0.3, P3.3
7. Cold-start degrades to generic (needs competitors + Anthropic key). → P3.3
8. `COPILOT_CONFIDENCE = 0.55` (`chat.py:543`) causes clarify-loops on legitimately ambiguous paid requests. → P3.3 (tune with telemetry)

## Sweep 2 — Model routing & BYOK

**Model inventory (stage → model → client):** script/text = Claude Sonnet/Haiku (direct Anthropic or Kie gateway; `pipeline_constants.Models`, `kie_unified.py`); scene images = GPT Image 2 primary, Nano Banana 2 fallback, Z Image alt (`image_client.py` L523/632/870); thumbnail = Nano Banana Pro + GPT2 text-fix + Gemini director; clips = Grok (default), Seedance 2.0 Fast, Veo 3.1 Fast/Quality wired — Kling 3.0 Pro / Runway Gen-4 Turbo / Hailuo 2.3 defined but NOT wired (`channel_profile.MODEL_REGISTRY` L285-293, gate at `pipeline_executor.py` L11775-83); talking clips = InfiniteTalk; voice = ElevenLabs direct → Kie fallback; sound FX = elevenlabs/sound-effect-v2; transcription = Whisper (OpenAI) + Supadata; vision QA = Gemini 2.5 Flash/Pro → Kie Claude → Anthropic chain (`vision_client.py` TIER_MODELS L38-43).

**Routing today:** user-selectable = clip model (`video.video_model`, 4 wired), image override (`video.image_model_override` — BROKEN, see below), visual style chain (`channel_profile.load_profile()` L378-421: override > Visual Style > env > neutral), dialogue audio mode. Hardcoded = Claude tier per call site, thumbnail/sound/voice/whisper/vision models, provider policy (Anthropic-first text, always-Kie media).

**BYOK state:** vault live (`vault.py`: Fernet at rest, tenant isolation — tenant reads never fall back to server env L215-221; per-tenant env load + clearing in `pipeline_executor.py` L6155-6220); key validation probes for 6 providers (`vault.test_api_key` L425-598 incl. Kie credit balance); `/settings/keys` UI complete. Per-user keys (`PER_USER_KEYS_ENABLED`, default false): resolution logic done (L165-196), NO write path or UI.

**Findings (→ checklist):**
1. Image dropdown cosmetic: live coverage path (`scripts/coverage_to_app.py` L621/906/978) hardcodes `generate_scene_image_gpt`, never reads override; only legacy path honors it (`pipeline_executor.py` L13694). → P0.1
2. 3 dead registry models selectable-looking. → P0.2
3. Price constants duplicated (`actions.py` CLIP_COST L31 / `next-action.ts` L61-65 / `MODEL_REGISTRY.cost_per_clip`); no actual-spend ledger. → P0.3
4. Claude tier invisible + hardcoded per call site. → P3.4 (single-source the tier map; expose only if a real need appears)
5. Whisper forces an OpenAI key even in a Kie-only setup — BYOK friction. → P3.4
6. Per-user BYOK gated off with no write path/UI. → P3.4 (PRD slice, needs product call)
7. Fallback behavior is good (GPT2→nano on policy block, provider chains, KIE_ACCOUNT_BLOCKED terminal handling) — preserve it through the router refactor; `allow_fallback=False` exists for accuracy-critical paths (`static_docu`).

## Sweep 3 — YouTube growth loop

**Two parallel implementations:** legacy `skills/video-pipeline/` (Airtable + cron + Slack, single-channel) vs StoryEngine SaaS (Supabase, multi-tenant, 10 background asyncio loops in `main.py` lifespan L496-522 incl. `_auto_produce_queue` every 30 min with `FOR UPDATE SKIP LOCKED`). **SaaS side is canonical**; legacy items are wire-or-delete.

**Working today:** upload = always unlisted draft, manual publish (deliberate); SEO generator (Claude: hook line, tags, chapters — hardcoded `@Power_Doctrine` branding, needs generalizing for SaaS); performance tracker pulls Data v3 + Analytics v2 + Reporting-API bulk CSV (CTR/impressions ONLY available via bulk report job); immutable snapshots CTR_12H/24H/48H, VIEWS_24H→30D, RETENTION_48H; osiris 48h/7d post-mortems → learnings table → `LearningsEngine` prompt injection (confidence ≥40, sample ≥2); autopilot scoring/cadence/CTR-verdicts (KEEP ≥4.0 / DISCARD ≤2.5); StoryEngine scorecards convert CTR→title/thumbnail lessons, retention→script/hook lessons; UI: /autopilot cockpit, /analytics, /learnings, /discovery.

**Findings (→ checklist):**
1. Scorer placeholders: `momentum` and `retention` return 50.0 (`core/confidence_scorer.py`) while weights treat them as real. → P3.2
2. `learning_extractor.run_daily_extraction()` stubbed ("# TODO: Integrate with Airtable to get actual CTR data"); `LEARNINGS.md` shows "Videos produced: 0". → P3.2
3. `osiris/learnings_engine.get_competitor_title_patterns()` returns `""`. → P3.2
4. YouTube quota (10k units/day ≈ 6 uploads) documented but not enforced in code. → P3.4
5. VPH computed for competitors only, never for own videos — scorecards compare apples to oranges. → P3.4
6. Legacy autopilot memory markdown has no viewer; legacy CLI loop requires Slack approval + manual publish — fine, but decide deprecation explicitly rather than maintaining two brains. → P3.2 umbrella

## Sweep 4 — Styles / presets / templates

**What exists (rich, buried):** 5 Python `VisualProfile`s (`shared/profiles/visual/`): neutral_v1 (default, style injected via `VISUAL_STYLE_DESCRIPTION` env — the seam `pipeline_executor._export_visual_style()` feeds), holographic_hud (3-variable system, people-stripping regexes), cinematic_dossier (Dossier/Schema/Echo 60/22/18), clay_mannequin (chest-glow arc), cinematic_illustration (5 scene types, 11 archetypes). Each profile: 11 config sections (image_gen models, style system, rotation/anti-clustering, figure rules, LLM scene-description prompt, animation motion templates, thumbnail, ken_burns numbers, metadata incl. cost tier). 3 `ScriptProfile`s (neutral, power_doctrine_v1/v2). 40+ camera-move catalog (`camera_moves.py`: motion_prompt + image_setup + best_for + model_support contracts) with "earn the move" selector (`camera_selector.py`: REVEAL/SCALE/ISOLATION/ESTABLISH/PAYOFF else static); animation prompt rules (verb-first, ≤2 elements, banned filler); Ken Burns calculator; transition engine (act→dip-to-black, style→0.8s crossfade).

**Findings (→ checklist):**
1. UI exposes only 6 shallow free-text presets (`visual-presets.ts` + duplicated `producer_prompt.VISUAL_PRESETS`); the 5 rich profiles have NO picker; only bridge is the env-var seam. → P2.1
2. Styles are code not data: new style = Python module + registry + redeploy. → P2.1
3. Camera catalog auto-only, invisible; no user-pickable moves, no previews. → P2.2
4. Script profiles env-only, not in product. → P2.3
5. No preview of composed result before spend (only static preset icons). → P2.1 gallery previews + P1.3 draft pass are the answer
6. Characters tab is real per-video customization (cast lock) — competitive with Soul ID; don't rebuild, market it. → G5 (research-to-build map)

---

## Cross-cutting conclusions
1. **The #1 pattern:** capability built in one layer, never wired to the layers users touch. Hence the checklist's layer law and the UX map's two-door law.
2. **The #2 pattern:** frontend/backend duplicated constants (prices, presets, wired lists) drifting. Every fix ends with one source of truth.
3. **The architecture is ready for the copilot-router/MCP plan:** verb registry + scene intent tags + vault + SSE already exist; the build is mostly wiring + surfacing, not new engines.

---

## S6 — Schema & data integrity sweep (2026-07-17)

**Trigger:** knowledge map §3, run before the first P0.3 migration (`generation_ledger`) so new tables piggyback on a verified base. **Scope:** schema.sql vs live drift, orphaned tables/columns, missing indexes for ledger/preset/scorecard/routing query patterns, migration-history coherence.

**Live Supabase comparison: RAN.** Project `wrromlupsmyzrrcqlucn` ("youtuber", us-east-1, Postgres 17.6) via `mcp__Supabase__list_tables` (verbose), `list_migrations`, and read-only `execute_sql` against `information_schema.columns` / `pg_indexes` / `_migrations`. Not a static-only sweep.

**Headline result: no drift on the columns the P0.3 ledger work actually touches.** `videos.total_cost`, `videos.image_model_override`, `videos.image_style_override`, `videos.pipeline_stages` all exist live with the expected types. `generation_ledger`, `style_presets`, and `agent_tokens` (C07/C20/C26) correctly do not exist yet — nothing to collide with. The base is verified for the ledger migration to land on **with three caveats below that should be cleaned up first**, because they're cheap and because piling new tracked migrations on top of an already-incomplete migration history makes the incompleteness harder to unwind later.

### Findings

1. **HIGH — one applied migration has no source file anywhere.** `_migrations` (the app's own tracking table, populated by `main.py::_run_pending_migrations()`) has **90** applied rows; the committed `storyengine/backend/migrations/` directory has **89** files. The delta is `050_enable_rls_auth_tables.sql` — recorded as applied in prod, sequenced between `049_memberships_rls.sql` and `050_extraction_flags.sql`, but the file does not exist in the working tree, and `git log --all` (all branches, `--diff-filter=D`) finds zero trace of it ever being committed and deleted. Whatever RLS policy that migration added to prod is currently live and working (spot-checked: `accounts`, `users` show `rls_enabled=true`) but **unreproducible** — a disaster-recovery rebuild from `migrations/` alone would silently skip it. Action: introspect the live RLS state on the auth tables (`pg_policies`), reconstruct an idempotent migration file that codifies it, and commit it under a new number (don't reuse `050`, that slot is provenance evidence).

2. **MEDIUM — two live tables bypass the tracked migration mechanism entirely, and both are missing RLS.** `secrets` (`vault.py::_ensure_secrets_table()`) and `static_reference_cache` (`static_docu.py`, ~L383) are created via in-process `CREATE TABLE IF NOT EXISTS` at call time, not via a `migrations/*.sql` file — so they're invisible to the `_migrations` audit trail and to `schema.sql`. Live: `secrets.rls_enabled = false`, `static_reference_cache.rls_enabled = false`. `secrets` tenant-scopes itself via a `tenant_id:name` string convention inside the `name` column rather than RLS, which is a deliberate design in `vault.py` (fine on its own) — but `static_reference_cache` has a real `tenant_id UUID` column and PRIMARY KEY `(tenant_id, machine_key)` with **no RLS policy**, unlike every other tenant-scoped table in the schema. Action: backfill both into tracked `migrations/` files (documents what already exists in prod) and add a tenant-isolation RLS policy to `static_reference_cache` matching the pattern used everywhere else (`tenant_id = current_setting('app.tenant_id', true)::uuid OR tenant_id IN (SELECT tenant_id FROM memberships WHERE user_id = auth.uid())`).

3. **MEDIUM — `channel_video_retention` (migration 080) ships with no RLS.** It's tenant-keyed (`tenant_id UUID PRIMARY KEY`) but migration 080 never adds an `ENABLE ROW LEVEL SECURITY` / policy, and live confirms `rls_enabled = false`. Low current risk (no route reads it per-tenant with a scoped connection today) but it's a tenant-config table sitting open next to ledger/cost tables about to get more traffic. Fold into finding #2's cleanup pass.

4. **LOW — `schema.sql` is stale and mis-labeled "canonical."** Root `CLAUDE.md` and `storyengine/CLAUDE.md` both call it the source of truth for DB shape, but the app never executes it — `main.py::_run_pending_migrations()` only ever runs `migrations/*.sql`, tracked in `_migrations`. Consequently `schema.sql` is missing 11 tables that exist live and are actively used (`intelligence_reports`, `channel_videos`, `secrets`, `channel_profile_documents`, `chat_assets`, `production_queue`, `script_templates`, `channel_analytics_daily`, `static_reference_cache`, `channel_video_retention`, `machine_research_cards` — all created by migrations 041–081), and it still declares `title_tests`, a table that does not exist live and has zero references anywhere in `backend/`. Action: regenerate `schema.sql` from the live DB (or `pg_dump --schema-only`) as a periodic snapshot, and drop or clearly flag `title_tests` as vestigial.

5. **NOTE (not actionable, no chunk) — shared Supabase project.** `list_migrations` (the Supabase-CLI-tracked history) returned 48 migrations, **none of which correspond to StoryEngine** — they're all `udc_*` (a completely separate product: teams, cofounder chat, landing pages, billing, campus city blocks) living in the same `public` schema of the same project. 34 `udc_*` tables coexist with the 41 StoryEngine tables. This is a shared-tenancy-at-the-project-level fact worth knowing (a schema-wide `list_tables`/`get_advisors` call surfaces both products at once, and a runaway query or leaked service-role key exposes both) but out of scope to fix here — flagging for whoever owns S5 (security sweep) to decide if project-level separation is warranted.

6. **NOTE — no missing indexes found for the query patterns C07/C08/C20/C26 are about to add**, because the tables they target (`generation_ledger`, `style_presets`, `agent_tokens`) don't exist yet. Forward-looking guidance for those chunk authors rather than a standalone fix: give `generation_ledger` a composite index on `(video_id)` and `(tenant_id, created_at)` up front (mirrors the existing `idx_assets_video_status` / `idx_bg_tasks_video` pattern) rather than adding it as an afterthought once rollup queries are slow. Also worth noting: `stage_transitions.cost` and `bot_activity.cost` are pre-existing, narrower cost-tracking columns that predate and partially overlap `generation_ledger` — C07's author should explicitly decide whether historical cost data backfills into the ledger or the two systems coexist un-reconciled.

**Verdict:** base is verified clean for the columns/tables the ledger migration touches directly. The three schema-hygiene gaps (missing migration file, untracked ad-hoc tables, stale schema.sql) are real but self-contained — bundled into a new chunk `C01a` below rather than blocking C07/C08.

---

# S7 · Queue/Idempotency sweep (C16, 2026-07-18) — gate findings for C17 draft/finalize

**Verdict: NOT safe to build C17 on today's queue.** Two execution systems exist; only one has
idempotency. The arq/job_queue.py system (`make_job_id` → arq `_job_id` dedup, `keep_result=86400`)
is well-built — but the ACTUAL production path (chat → `make_autobuild_step`/`make_action_step` →
`PipelineExecutor` directly, and `scripts/coverage_to_app.generate_coverage_for_video` for images)
never touches it: no idempotency key, no cross-call dedup, no concurrency guard. Pre-C17 fixes
required in order: S7-1, S7-2, S7-5; hardening S7-3/S7-4/S7-6; hygiene S7-7/8/9 may ride along.

- **S7-1 CRITICAL — chat-driven autobuild path has zero concurrency guard.** `routes/chat.py:530/:691/:697-698`
  schedule `_make_autobuild_step`/`_make_copilot_step` via bare `background_tasks.add_task` with NO
  `_is_task_active` gate (zero grep hits in chat.py/actions.py; contrast `routes/pipeline.py:1276/:920`).
  Double-tap or retried chat turn → two concurrent `_run` loops → double paid generation. Fix: claim/gate
  at `_handle_approve`/`_run_pending_action` dispatch (see S7-6 for the DB-backed form). → chunk C16a
- **S7-2 CRITICAL — images/coverage has no skip-if-done guard.** `coverage_to_app.py:1401-1520` re-runs
  paid `run_coverage()` for EVERY scene on every invocation (only the directive TEXT is cached via
  `coverage_directive_hash`, L1461-1466; `store_scene`'s delete-first is post-spend hygiene, not a guard).
  Voice (`voice/run.py:87-89`), sound (`sound_bot.py:79`), clips (`supabase_adapter.py:747-769`
  `video_url IS NULL`) all have guards — images is the one paid stage without. This is the exact stage
  `finalize` calls; today a re-invoke re-bills every scene. Fix: scene allowlist + skip scenes with
  completed frames and unchanged hash. → chunk C16b
- **S7-3 HIGH — thumbnail: no skip-if-done, no idempotency.** Three paths (`pipeline_executor.py:14304-14318/
  :14620-14630/:14680-14694`) unconditionally regenerate + ledger-bill with kie_task_id=None. → chunk C16d
- **S7-4 HIGH — arq stages hardcode `attempt=1`** (`routes/pipeline.py:479`); after one completed run the
  job_id is "exists" for 24h (`keep_result=86400`, arq refuses), and the `job_id is None` branch silently
  returns 200 with no fallback/signal (`:481-487`). Legit manual re-runs no-op silently for 24h; only
  `main.py:481` restart-recovery ever bumps attempt. → chunk C16d
- **S7-5 HIGH — `generation_ledger` has no uniqueness backstop.** No UNIQUE on kie_task_id (087 migration),
  plain INSERT in `record_ledger_entry` (`generation_ledger.py:59-65`); only clips populate kie_task_id
  (`pipeline_executor.py:12375`). `total_cost` SUM-recompute is race-safe arithmetically but REPORTS a
  double-spend rather than preventing it. Fix: unique index (video_id, stage, kie_task_id) WHERE NOT NULL +
  ON CONFLICT DO NOTHING + thread provider task ids through all stages. → chunk C16c
- **S7-6 MED — the only existing guard is in-process and restart-fragile.** `_running_tasks`/`_side_lanes`
  dicts (`routes/pipeline.py:139/:152`); wiped on deploy; never consults `background_tasks` for arq jobs.
  Precedent for the fix exists: `routes/queue.py` uses `FOR UPDATE SKIP LOCKED` (`main.py:383`). → folded into C16a
- **S7-7 MED — Redis-down fallback silently strips all dedup** (`routes/pipeline.py:494-495`; matches
  docs/failure-modes.md:20 but that entry doesn't note idempotency is lost). Surface degraded state. → C16d
- **S7-8 LOW — `db_persist_task` check-then-insert race**, no unique index on background_tasks.job_id
  (`task_store.py:46-52`, `schema.sql:930-944`). → C16d
- **S7-9 LOW — resumability is undocumented per stage:** resumable = voice, sound, clips; full-restart-and-
  rebill = images/coverage (until C16b), thumbnail (until C16d). Document in failure-modes. → C16d

**C17 design requirements derived (build on C16a-c):** DB-backed claim keyed (video_id, stage, pass) taken
at chat dispatch; scene-level skip-if-done so "finalize N approved scenes" regenerates exactly N; job key =
(video_id, stage, pass, scene_set_hash) — a bare (stage, video_id) key would wrongly dedup a legitimate
second finalize; kie_task_id threaded everywhere + ledger constraint as last-resort backstop; either fix
attempt-bumping if routing through arq, or skip arq and rely on claim+constraint (consistent with how the
paid pipeline actually runs).

---

# S9 · Frontend-state sweep (C19, 2026-07-19) — gate findings for the Phase 2 UI wave (C20-C24)

**Verdict: C20 (backend gallery) safe now. S9-1 + S9-2 must land before C21-C23; S9-4/S9-5 are
design constraints INSIDE C21; S9-3/6/7/8 are riders.** Clean bill on the two scariest checks: no
query-key collisions with different fetchers, and NO paid action leaves stale UI (every path runs
useTaskWatcher.onComplete→refreshAll or explicit invalidateQueries — GuidedNextStep.refreshAll is
the most complete set in the codebase).

- **S9-1 HIGH — duplicate task-watcher polling.** GuidedNextStep (always rendered, page.tsx:705) AND
  the active tab EACH mount useTaskWatcher (3s setInterval on the same getPipelineTaskStatus) —
  2x identical polls today, every production tab repeats the pattern, Phase 2 chips would make it
  4-5x. Fix: hoist ONE watcher to pipeline/[videoId]/page.tsx, pass down. → chunk C19a
- **S9-2 MED — GuidedNextStep cost line reads the mutable CLIP_COST_PER_MODEL module cache**
  (next-action.ts:68/76-78 via clipCost()) — the exact one-render-stale anti-pattern
  ScenesWorkspaceTab already works around (its own comment, ~L262-288); banner can show $0.30
  fallback or a PREVIOUS video's price on first paint. It already fetches videoActions.prices.clip —
  use it reactively. → chunk C19a
- **S9-3 MED — ChatCore card rendering dispatches by string-matching card.id at 4 scattered sites**
  (L201, 460-479, 685-691, 1349) in a 1638-line file; no kind/renderer lookup. Constraint folded
  into C21 (introduce the lookup BEFORE adding the LOOK card type).
- **S9-4 MED — style-preset <img> tags lack the onError fallback standard** (ChatCore.tsx:1399-1404,
  pipeline/page.tsx:1383-1388; contrast SceneBoardsGrid's C15b pattern). Constraint folded into C21.
- **S9-5 LOW — two parallel style systems:** hardcoded VISUAL_PRESETS (2 readers) vs profile/page.tsx's
  server-backed VisualStyle CRUD (["visualStyles"]). C21 must reconcile (decision inside C21).
- **S9-6 LOW — dead code:** 10/12 files in components/video-detail/ have zero imports; production/
  ScriptTab.tsx (1114 lines, superseded, carries a frozen field-name bug) dead; storyboards/page.tsx
  route orphaned. Name collisions already exist. → chunk C19b (delete)
- **S9-7 MED — ScenesWorkspaceTab.tsx is 2399 lines**; clip trust-ladder/auto-resume state machine
  (~L530-1099) should extract to a hook before C22/23 add chips there. Constraint noted on C22.
- **S9-8 LOW — 3 stacked freshness mechanisms on ["video-assets"]** during a running task (watcher
  invalidation + 5s refetchInterval + SSE) — redundancy compounds with S9-1's fix. Fold into C19a.

---

# S5 · Security/tenancy sweep (C25, 2026-07-19) — HARD gate findings for the MCP build (C26-C29)

**Verdict: C26 NOT safe to start until S5-1 lands; S5-3/S5-4 are C26 DESIGN LAWS; S5-2 resolves
before C27 locks the tool set; S5-5/6/7 queued (C25b); S5-8 is a prod env check (live queue).**
Calibration: tenant scoping is the NORM across ~30 spot-checked route files; vault/key-reveal is
rate-limited+audit-logged+tenant-scoped; money gate is a single unforked path; SQLi has one choke
point with a regression test; dev bypass needs DEV_TOKEN+DEV_MODE. The proxy is the one real gap.

- **S5-1 BLOCKER — Drive media proxy: zero auth + tenant-blind allowlist.** `routes/media.py:137`
  `serve_drive_file` has NO verify_token/get_tenant_id (registered bare, main.py:610); `_is_allowed()`
  (media.py:37-76) checks the file id against assets/scripts/videos/video_characters/chat_assets/
  projects ACROSS THE WHOLE DB, no tenant clause; `/api/media/` is rate-limit-exempt (rate_limit.py:45).
  Today: narrow leak (needs a leaked/guessed 33-44-char id). Post-MCP: tool results carry these URLs
  to external processes/logs forever, no revocation. Fix: tenant dependency + `tenant_id = $2` in every
  EXISTS clause. → chunk C25a (BLOCKS C26)
- **S5-2 HIGH — unconfirmed `remember` writes = two-hop indirect-prompt-injection foothold.**
  `chat.py:1092-1096` routes remember/forget around the confirm card to `_save_preference` (verbatim,
  channel-wide, hydrated every turn). Chained with `_compute_channel_intel` (chat.py:2648-2724)
  distilling COMPETITOR-controlled titles into `hook_pattern` hydrated verbatim into system prompts —
  a crafted public title could plant a durable standing instruction, silently under MCP. No tenant
  crossing, no direct spend (money gates are code-level), but: MCP v1 must EXCLUDE memory-writing
  tools or confirm-gate them + surface agent-originated writes (C28 "via agent" chip). → constraint on C27
- **S5-3 HIGH — session JWTs are unrevocable (30d stateless)** — acceptable for browsers, WRONG
  precedent for agent_tokens; UX map already requires per-token revoke. Fix: DB-row-backed tokens
  (revoked_at IS NULL checked per request). → C26 design law
- **S5-4 HIGH — agent tokens must be a DISTINCT auth dependency on an explicit MCP-route allowlist,**
  never a 4th token type inside the shared verify_token — else an external token could immediately call
  `/api/settings/keys/{name}/reveal` (returns decrypted BYOK keys; tenant-scoped but reachable by
  anything satisfying the generic dependency) — worse than spending money, since THAT is gated and
  key-reveal isn't. → C26 design law
- **S5-5 MED — SQLi regression lock omits 4 dynamic-column files** (characters.py:396, environments.py:390,
  queue.py:346, chat.py:2005/2311 — all currently safe by manual read). Fix: add to AUDIT_FILES. → C25b
- **S5-6 MED — check-then-mutate drops the tenant clause** in visual_styles.py:416/448/453
  (activate/delete verify ownership in a prior SELECT then mutate by bare id). Not exploitable today,
  fragile under refactor. Fix: repeat the tenant/project clause in every mutating WHERE. → C25b
- **S5-7 MED — /api/health/detailed fails OPEN when HEALTH_TOKEN unset** (main.py:659-669). Fail closed. → C25b
- **S5-8 LOW — vault plaintext fallback when SECRETS_MASTER_KEY unset** (vault.py:64-66, documented).
  CONFIRM the env var is actually set in prod before C26 widens DB-leak blast radius. → live queue (VPS check)

---

# S10 · Multi-tenant branding sweep (C34, 2026-07-19) — findings

**Verdict: 3 fix chunks (C34a upload-fallback FIRST AND ALONE; C34b voice+Slack; C34c thumbnail/title/category).**
Clean: the native SEO/upload path (youtube_publish.py), engine_templates/identity/prompt_defaults (regression-tested
de-branded), script/visual profiles (neutral defaults, C24-pinned), frontend copy. All leaks are LEGACY FALLBACKS.

- **S10-1 HIGH/CRITICAL — upload fallback ships a tenant's video onto Ryan's own channel.** `pipeline_executor.py
  :15201-15227` run_upload falls through to the legacy bot when `channel_profiles.youtube_refresh_token` is NULL
  (no gate in routes/pipeline.py:2085-2124). Legacy `upload/seo_generator.py:16/28/41/207` hardcodes
  @Power_Doctrine subscribe CTA + #PowerDoctrine hashtags + "geopolitics channel" SEO prompt, written into the
  TENANT'S videos row; `upload/youtube_uploader.py:30-33,43` uses the SHARED VPS OAuth token files (Ryan's channel,
  category 25) and BYPASSES the C33 quota guard. Fix: delete the fallback branch / hard-block with "connect your
  YouTube channel first". → C34a
- **S10-2 HIGH — default ElevenLabs voice is Ryan's cloned voice** (`pipeline_constants.py:415` G17SuINrv2H9FC6nvetn;
  executor restores process default when no vault override, pipeline_executor.py:6245-6279). Fix: explicit voice
  choice at onboarding, stock-voice default. → C34b
- **S10-3 MED — SlackClient posts tenant content to Ryan's workspace** (slack_client.py:17 C0A9U1X8NSW, global env
  token; thumbnail/run.py + upload/run.py post tenant titles/thumbnails/URLs). Fix: no-op Slack for SaaS tenant
  runs. → C34b
- **S10-4 HIGH — thumbnail fallback template is a geopolitical world map** (`thumbnail/selector.py` Template A
  default + geo keyword vocabulary; reachable for any new tenant without channel_videos history via
  pipeline_executor.py:14838-14851). Fix: niche-neutral default / select via tenant niche. → C34c
- **S10-5 LOW-MED — title_generator.py:41 hardcoded "Economy FastForward finance channel" system prompt** —
  shadowed today by _load_prompt_overrides but an unguarded regression trap. Fix: neutral default at source. → C34c
- **S10-6 MED — computed YouTube category silently dropped** (`youtube_publish.py` computes category_id in SEO,
  then always uploads _DEFAULT_CATEGORY "27"). Fix: persist + pass through. → C34c
