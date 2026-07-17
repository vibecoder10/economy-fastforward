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
