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
6. Characters tab is real per-video customization (cast lock) — competitive with Soul ID; don't rebuild, market it.

---

## Cross-cutting conclusions
1. **The #1 pattern:** capability built in one layer, never wired to the layers users touch. Hence the checklist's layer law and the UX map's two-door law.
2. **The #2 pattern:** frontend/backend duplicated constants (prices, presets, wired lists) drifting. Every fix ends with one source of truth.
3. **The architecture is ready for the copilot-router/MCP plan:** verb registry + scene intent tags + vault + SSE already exist; the build is mostly wiring + surfacing, not new engines.
