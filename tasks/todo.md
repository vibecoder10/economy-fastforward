# Task Tracking

## ⟳ LOOP PROGRESS (read this first — resume point)
- **Last done:** C01a · Schema/migration hygiene. schema.sql refreshed to live (11 missing tables added, dead `title_tests` removed); migration `050` reconstructed with its exact applied filename (permanent no-op — runner skips already-applied filenames, verified `main.py:329`); ad-hoc `secrets`/`static_reference_cache` brought into tracked migration `082` (CREATE TABLE IF NOT EXISTS); RLS enabled on `secrets`/`static_reference_cache`/`channel_video_retention` via `083`. ⚠ `083` is the ONE live-effect change (flips RLS on 2 open tables) — proven safe: backend role bypasses RLS (secrets already runs RLS-on/0-policies live & works). Merged to main (`3845043`), pushed & will auto-deploy. If any static-docu/retention read breaks post-deploy, `083` is the suspect.
- **Next chunk:** C02 · P0.1 image-model override honored on coverage path + asset model badge. Parent: checklist §0.1 (`coverage_to_app.py` L621/906/978 ignores `image_model_override`, hardcodes `generate_scene_image_gpt`). Two doors: UX map — Pictures model select. `[V]`: set override to z-image, run pictures, confirm Kie payload + asset row name z-image. Code chunk (not docs) → hold on branch unless clearly deploy-safe.
- **Branch:** work + push on `claude/story-engine-build-loop-tfdg8n` (NOT the stale `sgnm8l` name in the loop docs — that branch doesn't exist); ff-merge deploy-safe chunks to main.

## Handoff — 2026-07-17 (Higgsfield teardown + full build plan COMPLETE → next session BUILDS)

**Mission:** StoryEngine becomes the main competitor to Higgsfield (higgsfield.ai).
Differentiation: open BYOK (user's own keys at true cost — Higgsfield's MCP/API locks billing
into their credits) + YouTube-native publishing with a performance feedback loop (Higgsfield
has NO social integrations — their agent makes clips; ours runs a channel). The copilot should
feel like Higgsfield's best trick: talk to it like a co-writing partner and it just makes what
you want — with our mapped shots.

### What this session produced (all on main, nothing pending)
This was a research + planning session. NO product code was changed. Five docs were produced,
all committed to main and cross-referenced:

1. `docs/reports/2026-07-17-higgsfield-vs-storyengine-gap-analysis.md` — the research.
   Higgsfield teardown (product / promotion / prompt-routing), 13-dimension comparison table,
   8 ranked recommendations. Claims labeled [verified] (survived adversarial checks) vs
   [reported]. Do NOT re-run research; do NOT trust Higgsfield price points beyond July 2026.
2. `docs/reports/2026-07-17-storyengine-agent-audit-findings.md` — THE EVIDENCE. Full
   findings of the 4-agent StoryEngine sweep (copilot flow, model routing/BYOK, growth loop,
   styles/presets) with file:line references. Every checklist item traces to a finding here —
   consult it before re-exploring the codebase; do NOT re-run the audit.
3. `tasks/storyengine-wiring-fix-checklist.md` — THE WORK QUEUE. P0→P3, every item mapped
   to `[D]`ata / `[B]`ackend / `[U]`I layers with a `[V]`erify step. An item is not done until
   every listed layer ships AND Verify passes with evidence. P3.4 holds the audit findings
   that aren't part of the router build (quota guard, own-video VPH, per-user BYOK slice,
   Whisper-key friction, hardcoded Claude tiers, Power-Doctrine-branded SEO).
4. `tasks/storyengine-copilot-ux-map.md` — HOW USERS TOUCH EACH FEATURE. Per feature: the
   clickable door (exact controls/click paths) AND the conversational door (example
   utterances), plus the MCP server spec (§7) and the conversational quality bar.
5. `tasks/storyengine-knowledge-map.md` — THE ROUTER. Where to look by task, when to reuse
   vs re-verify knowledge, and the queue of 6 NOT-yet-run sweeps (security/tenancy, schema
   drift, queue reliability, render path, frontend state, multi-tenant branding) each with
   its just-in-time trigger tied to a checklist phase. Run pending sweeps as ONE Sonnet
   Explore agent each when their trigger fires; append results to the audit findings report.
6. `tasks/research-to-build-map.md` — NO INSIGHT WASTED. Traceability matrix: every research
   insight → disposition (BUILD-NOW w/ checklist ref, BUILD-LATER w/ backlog ref, GROWTH
   play G1-G5, PARKED w/ revisit trigger, or REJECTED w/ reason). Maintenance rule: new
   research gets rows here in the same commit, or it's a process bug.
7. CLAUDE.md + tasks/lessons.md — subagent model policy (see Session rules below).

### Build order (work the checklist top-down)
1. **P0 first — integrity bugs that lie to users today.** Cosmetic image-model dropdown
   (`scripts/coverage_to_app.py` hardcodes `generate_scene_image_gpt`, never reads
   `video.image_model_override`); 3 dead models in `MODEL_REGISTRY` (Kling 3.0 Pro, Runway
   Gen-4 Turbo, Hailuo 2.3); cost counter wrong (prices duplicated in `actions.py` +
   `lib/next-action.ts` + `MODEL_REGISTRY`, no actual-spend ledger, `videos.total_cost`
   never rolled up); home Producer hard-requires Anthropic key (`routes/chat.py` ~3176)
   breaking Kie-only tenants; research silently skipped in default autobuild
   (`actions.py` L401-421); docked co-pilot drops file attachments (`ChatCore.attachFiles`
   early-returns when docked ~L359).
2. **P1 — the copilot router.** Decision table as data (`GET /api/models` with best_for/tier/
   cost/wired) → per-scene routing (scene intent from existing `camera_selector.py` purpose
   tags → routed_model + routing_reason columns) → model badges with "why" + one-tap override
   in ScenesWorkspaceTab → draft-cheap/finalize-expensive verbs with itemized quotes.
3. **P2 — surface the buried machinery.** Style gallery from the 5 Python visual profiles
   (styles become DB rows; DELETE the duplicated 6-preset lists in `visual-presets.ts` and
   `producer_prompt.VISUAL_PRESETS`); camera-move chips from the 40+ catalog; script voice
   selection; **StoryEngine MCP server (P2.4)** — expose the `actions.py` verb registry to
   external agents, per-user tokens, BYOK pass-through, quote+confirm_token money gate.
4. **P3 — learning loops + stub cleanup.** Per-preset CTR/retention tracking (the moat);
   legacy stubs get wired or deleted, no third option (momentum/retention placeholders
   returning 50.0 in `confidence_scorer.py`; `learning_extractor` CTR TODO;
   `get_competitor_title_patterns()` returning "").

### Key architectural decisions (also in tasks/decisions.md — do not re-litigate)
- **Two doors, one registry:** every capability = clickable control + conversational path,
  both calling the same `actions.py` verb; MCP becomes the third door on the same registry.
- **Router routes by declared outcome, not model name;** always shows "why"; override always
  one tap away; per-scene not per-video.
- **Ledger is truth, estimates are hints:** actual per-generation spend recorded from API
  responses; single price source; Est → Actual shown in UI.
- **Styles are data, not code:** DB-backed preset catalog; Python profiles remain the runtime
  engine behind it.

### Session rules established (in CLAUDE.md, follow them)
- **Subagent model policy:** premium model (Fable/Opus tier) for main-loop orchestration/
  synthesis ONLY; ALL fan-out subagents get explicit `model: "sonnet"` (Agent calls and
  workflow `agent()` opts). This session burned ~4M premium tokens by not doing this.
- Docs-only commits were fast-forward merged to main with Ryan's explicit approval; code
  changes go through the normal branch flow — main must stay deployable (VPS auto-pulls
  hourly).

### Watch-outs for the builder
- The StoryEngine SaaS backend (`storyengine/backend`) is canonical; `skills/video-pipeline/`
  is the legacy Airtable side. When both implement a thing, fix the SaaS side; legacy stubs
  are wire-or-delete decisions, not silent parallel maintenance.
- Frontend/backend duplicated constants are the #1 drift source found (prices, presets,
  wired-model lists). Every fix should END with one source of truth + derived consumers.
- Money gate is sacred: no new path (router, MCP, finalize) may spend without a quote and
  explicit confirm — extend `_estimate_cost`/confirm cards, don't fork them.
- Per the checklist's Definition of Done: `[V]` evidence required, `npx tsc --noEmit` clean,
  SYSTEM_STATE.md updated for structural changes, checklist box ticked in the same commit
  as the fix.

**Opener for next session:** "Read the handoff in tasks/todo.md, then start at P0.1 of
tasks/storyengine-wiring-fix-checklist.md, building UX to tasks/storyengine-copilot-ux-map.md."

## Handoff - 2026-07-16 (Modal close wedge FIXED - on main, NOT pushed, NOT deployed)

The shared Modal (`ui/modal.tsx`) never unmounted after close: AnimatePresence held the exited
backdrop + card in the DOM forever (keyless fragment root; framer-motion 12.38 + React 19.2), so
an invisible `fixed inset-0 z-50` layer blocked every click after closing any dialog. Fixed at all
3 sites and verified like a user on local dev against the prod API (se devtoken ladder):

- `ui/modal.tsx` - backdrop and card are now two KEYED direct children of AnimatePresence (covers
  ModelVideoModal, pipeline Delete + New Video modals, discovery Manage Channels + Launch). Added
  `data-testid="modal-backdrop"` / `"modal-card"` for future smoke tests.
- `ReadinessCheck.tsx` + `FirstVideoFlow.tsx` - each rolled its own copy of the same broken shape;
  root is now ONE motion.div owning the only exit, backdrop is a plain div, card keeps its enter
  spring (no exit). `pipeline/page.tsx` mounts got explicit keys. data-testids added.
- Proof: pre-fix reproduced locally (React state closed, DOM stuck, backdrop intercepted a real
  click on "New Video"); post-fix all three dialogs open AND close clean via Escape, X button, and
  the readiness->create cascade; zero full-screen blockers left in DOM; `tsc --noEmit` clean.
- Deploy note: frontend-only change, needs `se deploy <session> --with-frontend` when Ryan ships it.
- `confirm.tsx` header comment updated (bug fixed); moving it back onto Modal is optional.
- ⚠ Same broken fragment shape still exists un-fixed in `components/detail-panel.tsx`,
  `components/storyboard/panel-detail.tsx`, `components/nav/bottom-tabs.tsx` (More menu) - same
  latent wedge, fix with the same pattern + a browser walk.

## Handoff — 2026-07-13 (DVsU Anton one-machine pipeline)

Current DVsU bomber proof state:

- `fc73860c-a9af-444f-95a5-7f86d60503e0` has a locked 23-machine roster.
- The old four-beat evidence-sentence preview shape is intentionally retired. It was fact-safe but visibly unlike Anton.
- Current StoryEngine machine research cards use Anton schema-v3 evidence slots: required `identity_origin`, `scale_specs`, `build_reality`, `service_reality`, `memorable_fact`; optional `engineering_intent`, `role_category`, `combat_reality`, `tradeoff_or_limit`, `human_detail`, `historical_meaning`, `transition_hook`, `onscreen_label`. The final sentence is paragraph-derived synthesis, not a researched meaning beat.
- Verified raw source packages now label each fetched excerpt with `SOURCE_TIER`; required Anton slots can use Tier 1-3 support, but Tier 4 caution/general sources cannot carry required evidence by themselves.
- Current StoryEngine machine script preview expects one 95-120 word paragraph plus `claim_map` spans. Validation checks exact span presence, required slot coverage, per-span/paragraph number support, unsupported designations, high-risk terms, sentence count, final-line length, and static DVsU paragraph rules.
- The deterministic extractive fallback is disabled. If the model cannot produce an Anton-quality claim-mapped paragraph after repair, the preview must fail for review instead of saving safe filler.
- Target-machine preview now filters the hydrated compact/legacy card set back to only the requested machine before building the story plan, so other roster cards are not loaded into the proof prompt.
- StoryEngine UI now exposes exact `evidence_segments` on each researched machine card and returns/showcases failed `machine-script-preview` audits instead of hiding them behind an HTTP error. This lets the operator inspect the source excerpt map before accepting or rerunning.
- Local no-spend proof passed with real fetched XB-15 sources from Boeing Images, National Museum of the USAF, and Pacific Wrecks: 99 words, no research-card errors, no validator warnings.
- VPS read-only check: backend service is active and running from checkout `e288cec8`; the DB still has the old saved XB-15 preview marked `passed=false`, `word_count=122`, with warnings for too many numbers, overlong final sentence, high-risk terms, and word count. This is good: the system is not treating the old preview as acceptable.
- New note/spec file: `storyengine/notes/dvsu-anton-single-machine-pipeline.md` maps Anton desktop materials, the first three Strategic Bomber paragraphs, the research slot contract, script JSON contract, and isolation rule.

Next safe action: after Ryan approves deploy + paid Anthropic preview rerun, deploy the local ahead commits, run only `/api/pipeline/machine-script-preview/{video_id}` for `Boeing XB-15` through the StoryEngine UI/API, and inspect the paragraph plus evidence map in-app. Do not run the full roster script until that preview passes Ryan's quality bar.

## Handoff — 2026-06-22 (chat-first creative producer)

Shipped the chat-first pivot: StoryEngine now opens to a ChatGPT-style producer
chat (at `/`) that turns one sentence into questions → selector cards → a
production plan → an approved video, then runs the pipeline. Full plan + status:
`storyengine/GOAL.md` (Phases 1-3 done; 4 = channel intelligence, 5 = follow-up
edits still to build).

- New: `backend/routes/chat.py` (intake + spec→create_video + pipeline kickoff),
  `backend/producer_prompt.py` (producer brain, direct Anthropic via tenant Vault
  key), `migration 060_chat_conversations`, `frontend/.../chat/ChatHome.tsx`.
- Changed: `status_map.py` (5 friendly states + SSE `friendly` field), sidebar
  (Chat / Dashboard / Advanced), login+onboarding land on chat.
- Deploy: this commit MERGED the prod working-tree snapshot (branch
  `vps-live-20260622`) with the chat work — zero conflicts. Migration 060
  auto-applies on backend restart. The chat producer needs each tenant to have a
  direct `anthropic_api_key` in their profile/Vault.
- TODO next: rotate the GitHub PAT in the VPS git remote URL (plaintext); build
  Phases 4-5; the deterministic panel-aspect backstop below still stands.

## ★ NEW SESSION BUILD PLAN — next-up work (queued, not started)

Forward work for a fresh session. Each = what + where. Priority order.
(DONE this session: research toggle → 14g; env style-lock + voice toggle → 14h;
structured image prompts → 14i; scene-vs-thumbnail style split → 14j; clip-pipeline
resilience (was #1) → 14k.)

1. **Deterministic panel-aspect backstop** (aspect feature enforcement — owed; task #10).
   The image model can return the wrong aspect even when asked; force each cropped
   panel to the chosen aspect in storyboard extraction/upscale. Needs a paid test
   to tune (pad vs crop). ⚠ CORRECTION from the verify run: clips are portrait
   because **Grok reshapes** them (the still panels were 16:9 already) — so the
   real aspect lever is the **Grok clip stage**, not the image stage. See
   [[storyengine-aspect-ratio]].

2. **voice_over / Remotion aspect support** (deferred from the aspect feature).
   aspect_ratio flows through grok_native (stitch) but NOT Remotion —
   `remotion-video/src/Root.tsx` + `renderConfig` hardcode 1920x1080, so portrait
   voice_over videos render letterboxed.

3. **Extend stage toggles to the rest of the pipeline** ✅ **DONE + DEPLOYED + VERIFIED
   IN PROD (2026-06-16, commit `ced64159`).** The original "add `skip_<stage>` columns"
   framing was SUPERSEDED: the general per-video `pipeline_stages` plan (commits
   `d11b63e2`/`b4de08f4`) already made every step toggleable at creation, reroutes the
   pipeline around turned-off steps at the `_update_video_status` chokepoint, and the
   per-video page already hides a turned-off step's tab (`tabVisible`/`TAB_STAGES` —
   so "pipeline-page reflection still owed" was already done). The only real remaining
   work was "harden each gate," which this commit did:
   - **Backend:** new `status_map` helpers `parse_stage_plan` + `stage_enabled_in_plan`,
     and a `_require_stage_enabled(video, stage)` guard wired into **12** manual
     trigger endpoints in `routes/pipeline.py` (research, voice, dialogue-voice, clip,
     sound-prompts, sound-effects, video-scripts, video-generation, generate-video-prompts,
     thumbnail, render, upload). A disabled step now returns a clear 400 instead of
     running the bot + burning Kie credits + persisting an artifact. Full-pipeline videos
     (plan NULL) are untouched. 8 new unit tests (21/21 pass).
   - **Frontend:** the shared Scenes tab (`ScenesWorkspaceTab.tsx`) showed for an
     images-only plan (Scenes = images OR video) but still exposed Animate controls →
     a `videoStageEnabled` flag now hides every animate/clip affordance (card hover
     "Animate", tap-to-animate, "Animate this scene", "Animate the rest", the clip
     counter, the ⋯ Clips/Speaking-voices/motion block, and the silent motion-prompt
     auto-run) when the `video` stage is off. Picture workspace stays. tsc + build clean.
   See [[storyengine-pipeline-stage-plan]]. Open follow-up: `split` (deterministic, free
   timing) is intentionally NOT gated — a no-voice/images-only video may still need scene
   timing for the visual timeline.

4. **Env style polish — small remainders.** Structured prompts (14i) fixed the gross
   drift (verified: 2D→3D and photoreal→3D both lock). Open: (a) `fence_line_rubbish`
   and other "bad-side"/grungy scenes still come back more 2D-outlined than 3D — re-roll
   confirmed it's systematic; add a "stay soft 3D CG even when grungy/bad-side" nudge to
   the env prompt. (b) The stronger lever if any drift remains is a VISUAL anchor: pass
   the character cast sheet to `_generate_environment` as `image_input` (the Kie field
   for refs) with "match the art style/medium only, keep the location empty" — needs a
   paid test (risk: it pulls a character in).
   Also: the per-panel builder hardcodes `_CHARACTER_PREFIX/_ENVIRONMENT_PREFIX =
   "Cinematic 2D animated illustration of"` (image_prompts/engine/prompt_builder.py
   :284,289) ignoring image_style_override — a latent 2D-vs-3D contradiction for any
   video that uses the per-panel path (clip videos use the storyboard-grid path, so
   it didn't bite here, but worth reconciling).

5. **Bidirectional script ↔ Google Drive sync** ✅ **DONE + VERIFIED IN PROD (2026-06-15,
   commit 94d732ec).** Spec: [`tasks/script-drive-sync-spec.md`](script-drive-sync-spec.md).
   Shipped Phase 1 (Push) + Phase 2 (Pull) + cheap part of Phase 3 (modifiedTime "Drive
   edited" badge). Build: migration 053 (`videos.drive_script_doc_id/_synced_at/
   _doc_modified_at`); `GoogleClient.replace_document_body/read_document_text/
   get_file_modified_time`; `POST .../script/push-to-drive`, `POST .../script/sync-from-drive`,
   `GET .../script/drive-status` (routes/videos.py); ScriptTab Drive card (Edit/Update in
   Drive, Open Doc, Sync, badge, conflict "Sync anyway"). Per-tenant client uses
   `GOOGLE_OAUTH_CLIENT_ID` (mints the tenant token) w/ `GOOGLE_CLIENT_ID` fallback. Scene
   map = `### SCENE n` markers; Pull fails loud (422) if missing; changed scenes clear
   voice/image/clip (mirror delete_clip). Verified live on the "SLOW ENGLISH" video:
   editable scene-delimited Doc in Drive, edit→Sync updated scene 12 + cleared its voice
   (snapshot+restored byte-identical). **Required Google Docs API enabled on OAuth project
   802685987716 — done 2026-06-15.** Backend deployed; frontend UI deploys with the next
   web build. Open follow-ups: (a) `drive_newer` reads true ~1-2s after a push (Drive
   modifiedTime settles post-batchUpdate) — cosmetic, self-heals; (b) Pull maps onto
   EXISTING scenes only (a Doc-added scene is skipped); (c) re-push at a stale doc_id (user
   trashed the Doc) → 502, could recreate on 404.

6. **Auto-detect text cards → "Fix all text cards"** (fast-follow to 14l; Ryan: "manual
   now, auto later"). The manual per-card "Fix text" (GPT Image 2) is DONE + verified.
   Now make it automatic: tag title/word-card beats at the image-prompt stage (add a
   `title_card` scene_type in `scene_expander.py`, or an `assets.is_text_card` flag) — the
   LLM already follows a "use a word/title card" rule (story_bible.py:267) so it knows when
   it's making one — then a "Fix all text cards" batch that runs GPT Image 2 on the flagged
   panels (reuse `run_fix_text_card`). Keep the GPT Image 2 prompt LEAN (long prompts → Kie
   500s; see 14l).

7. **De-Power-Doctrine the GLOBAL defaults** (multi-tenant correctness — owed). Ryan's own
   tenant is now fixed (see the 2026-06-16 Power-Doctrine-leak handoff), but the platform-wide
   defaults still hardcode the old geopolitics channel, so a FRESH signup inherits it:
   `storyengine/backend/prompt_defaults.py` SCRIPT/RESEARCH/THUMBNAIL personas literally say
   "Power Doctrine"/"Economy FastForward" + a 6-act geopolitical-exposé structure, and
   `skills/video-pipeline/title_patterns.json` (`power_doctrine_adaptations`, `master_formulas`
   — imported by autopilot/research/discovery-scanner/learnings) is the same channel's title
   science. Real fix = make the base templates niche-neutral + channel-driven. NOTE the in-app
   meta-prompt flow (`routes/system_prompts.py`) only rewrites VOICE and is told to keep ALL
   structure EXACTLY, so it does NOT solve this. Needs a product call on the universal default.

**Context for the older items below:** the 3 content-quality fixes (char descriptions,
environment locking, recap continuity) are DONE + verified end-to-end on a real
cloned video; see the handoff below. The verify also fixed 3 bugs live
(env-directive misfire, env-image proxy allowlist, harmful clone-research).

---

## ★ HANDOFF — 2026-06-16 (Engine/Identity split — Phases 1+2 BUILT + MERGED + DEPLOYED)

Executes [`tasks/engine-identity-split-plan.md`](engine-identity-split-plan.md) — turning StoryEngine into a
"cloneable system" where the universal ENGINE (craft) is separated from the swappable per-channel
IDENTITY (voice/look). See [[storyengine-cloneable-system-vision]]. Subagent-driven; each piece
reviewer-approved.

- **Phase 1 (Foundation):** `storyengine/backend/identity.py` (`IdentityContext` + builder, projects→
  channel_profiles→neutral precedence; frameworks parsed from JSONB string), `engine_templates.py`
  (neutral craft templates + `safe_fill` — fills only the 6 identity slots, leaves `{HEADLINE}`/`{{json}}`
  untouched), and `pipeline_executor.py` (`resolve_prompt`: per-video→tenant→neutral engine template,
  then safe_fill). Overrides still win → no change for customized tenants; keyless steps now get neutral
  craft instead of None/PD.
- **Phase 2 (Text engine):** `script` (engine template + neutralized `script_generator.py` append-blocks
  + dropped the PD quota lines from the user-prompt tail), the script **validator** (PD checks —
  number-density/framework-density/wallet-401k/position-yourself — now OPT-IN via `ScriptProfile`,
  default OFF; `power_doctrine_v2` re-enables; ESL/cooking scripts pass default, fail under PD gates),
  `research` (no more "Economy FastForward (Power Doctrine)" / 19-numbers / incentive-chain), and
  `video_motion` (dropped the "never show humans" rule + missile/bomber examples; kept verb-first/
  camera-discipline/banned-filler craft). PD originals preserved verbatim in
  `tasks/engine-identity-seeds/power-doctrine.md`. 24 backend + 154 script tests green.
- **Phase 2b (ScriptProfile — the REAL gate, found by the first live ESL proof):** the script
  generation loads a `ScriptProfile` (`shared/profiles/script/`) that was hardcoded
  `DEFAULT_PROFILE_ID = "power_doctrine_v2"` — UPSTREAM of the validator (it re-armed all the gates) AND
  of the brief validator (`validate_brief` in `brief_translator/validator.py`, an LLM judge with
  documentary criteria that REJECTED a simple ESL premise before any model call → `total_cost=0`). So
  the prior "validator default OFF" was true at the class level but moot at runtime. FIX (commit
  `64b0db67`): added `shared/profiles/script/neutral_v1.py` (all PD gates off, `requires_research_brief=
  False`, `min_words=150`, neutral structure), flipped `DEFAULT_PROFILE_ID="neutral_v1"`, and made the
  brief gate profile-aware (`BriefTranslator` skips `validate_brief` when `requires_research_brief=False`).
  `power_doctrine_v2`/`v1` stay loadable (SCRIPT_PROFILE env / explicit). 161 script tests green.
  NOTE: SCRIPT_PROFILE is NOT set in the prod backend env, so tenants now resolve to `neutral_v1`.
- **Phase 3 (Titles + Thumbnails) — DONE + MERGED + DEPLOYED (commits `4c1418dd`+`048fd887`+`84bff0c3`):**
  neutralized `title_patterns.json` (kept reader keys/schema + the title SCIENCE; stripped
  `power_doctrine_adaptations`/PROXY-WAR/NATO/Machiavelli verdict map), the `TITLE_GENERATION_PROMPT`/
  `TITLE_REFINEMENT_PROMPT` + the `infer_framework_from_research` 17-framework geopolitics classifier (now
  returns ''/neutral) in `research/agent.py`, and the thumbnail `VARIABLE_FILL_SYSTEM_PROMPT` (stripped
  Economy-FastForward + CHECKMATE/WEAPONIZED power-words + bear-trap/map metaphors). Promoted
  `engine_templates.py` `title`+`thumbnail` to real neutral craft; `prompt_defaults.THUMBNAIL_SYSTEM_PROMPT`
  → engine_templates. Reviewer-approved (craft preserved, JSON neutral at runtime, no PD fallback). 24+161+22 tests green.
- **Phase 4 (Images) — DONE + MERGED + DEPLOYED + PROVEN LIVE (commit `faa0e4c8`, 2026-06-17):**
  neutralized the visual engine. New `shared/profiles/visual/neutral_v1.py` (style-agnostic: empty medium
  prefix + technical-only suffix, `allow_human_figures=True`, NO national archetypes, neutral scene
  system-prompt with non-political examples, empty metaphor table). Flipped the visual default at all 7
  spots → `neutral_v1` (the real gate; backend never set `VISUAL_PROFILE` before, so this also fixed a
  latent "tenants can't switch styles" bug). `prompt_builder.py` constants neutralized; equipment-integrity
  now profile opt-in (ON for `cinematic_illustration`, OFF for neutral); an unknown/stale profile id resolves
  to neutral, NEVER holographic. `anthropic_client.py` holographic system/user prompt fires only for explicit
  `holographic_hud`; profile-None fallback now neutral. `storyboard/bot.py` `_KF_*` + keyframe footer
  neutralized. **QUICK store (Open Question 1, Ryan picked it):** the channel's free-text look is injected at
  build time via `VISUAL_STYLE_DESCRIPTION` (per-video `image_style_override` wins, else
  `IdentityContext.visual_style`/channel `style_description`); backend exports it on every image stage
  (`_load_idea` per-run reset + `_export_visual_style` on run_prompts/run_images/storyboard). `cinematic_
  illustration`/`holographic_hud`/`clay_mannequin` stay loadable opt-in presets. Reviewer-approved (2 delivery
  bugs found + fixed). PROVEN: deployed code on prod, fed Ryan's "Slow English" ESL identity, emits image
  prompts in the channel look with ZERO Power Doctrine across all 5 scene types.
- **Still tracked (separate later tasks):** `_generate_cinematic_direction` (PD act-structure
  ORDINARY-PERSON/OPERATOR/ARCHITECT/PROPHET) in `research/agent.py`; `title_idea/curiosity_gap/
  gap_title_engine.py` (`MF_FORMULAS` CHOKE POINT / "Weaponized [Geography]"); the PRE-EXISTING
  `title_patterns.json` loader path bug (a fix is staged uncommitted in `discovery/scanner.py` +
  `research/agent.py` — `Path.resolve().parent.parent`); and a cleanup of 18 pre-existing stale
  *holographic-era* unit tests in `image_prompts/engine/tests/` (red on `origin/main` before Phase 4).
- **Next:** Phase 5 (clone seeds the voice + creator-direction layer).

---

## ★ HANDOFF — 2026-06-16 ("Power Doctrine" leak in title/idea generation — FIXED + DEPLOYED + VERIFIED IN PROD)

Ryan: "when I generate an example title it still uploads my old Power Doctrine channel —
it's locked in." ROOT CAUSE was THREE stacked things (NOT a stale cache):

1. **DATA** — his authoritative `projects` row was still `name="Power Doctrine",
   niche="Tech"` (channel_profiles said TOPAI/technology, but the idea engine now prefers
   `projects` per commits `6ba6896a`/`1978a894`). So every generator was told the channel IS
   Power Doctrine. → Renamed `projects` + `channel_profiles` to `name="Slow English",
   niche="Beginner English learning (ESL)"` (Ryan's call — it's a throwaway example channel,
   editable live in Profile; the name is FREE TEXT, not pulled from a YouTube connection).

2. **CODE** — `routes/discovery.py _build_discovery_prompt` hardcoded a geopolitics "Master
   Formula" voice (PROXY WAR/NATO/PBOC examples, Machiavellian frameworks, "How [Country]
   Secretly…", neg-framing-+63%, 55-char ceiling). Even pointed at ESL competitors it reframed
   kids' English videos into "How SWIFT Sanctions Broke Russia's War Machine". → Genericized:
   the title rules, `framework` field, and JSON example are now niche-neutral + driven by
   `{ch_niche}` and the competitor titles, with an explicit "NEVER reframe into
   politics/geopolitics unless that IS the niche" guard. Commit `2fd1f6d1`, deployed (backend
   restart only — backend-only change). py_compile clean.

3. **LATENT** — `tenant_prompt_defaults` was EMPTY for his tenant, so a real video render would
   fall back to the hardcoded Power Doctrine script/research/thumbnail personas in
   `prompt_defaults.py`. → Seeded his tenant with ESL starter prompts for `script`/`research`/
   `thumbnail` (the resolver is PER-KEY; `video_motion`/`sound_*` stay on the neutral defaults).

**VERIFIED end-to-end on prod:** cleared his 20 stale geopolitical ideas, `POST
/api/discovery/refresh` → 5 fresh ideas, ALL clean ESL ("Are You a Good Guest or a Bad Guest?
| Slow English (A1-A2)", "They Laughed at the Quiet Girl… Then This Happened", thumbs
"GOOD vs BAD"/"SO JEALOUS!"). Zero geopolitics. Frameworks now "good vs bad contrast story",
not "Hegemonic Transition Theory".

**GitHub hygiene:** repo was already even with `origin/main` (nothing unpushed). Gitignored
`*.tsbuildinfo` (untracked the churning frontend cache) + auto-gen `docs/product-brain.md`;
committed the hand-written `docs/storyengine-creator-flow-ux-map.md`.

⚠ **STILL OPEN (systemic — see build-plan item 7):** the GLOBAL defaults are still Power
Doctrine. `prompt_defaults.py` templates + `skills/video-pipeline/title_patterns.json` hardcode
the old geopolitical channel, so a FRESH tenant inherits it until the base templates are made
niche-neutral. Ryan's tenant is clean; the platform default is not.

**Deploy gotcha learned:** `kill -9 $(pgrep -f "uvicorn main:app")` self-matches when run from
an SSH command whose argv contains that literal string — it kills its own shell. The uvicorn
procs still died + systemd revived them (confirmed: old PIDs gone, fresh proc serving new code),
but for a clean restart run the kill from a script FILE on the VPS (its argv is `bash file.sh`),
or use a `[u]vicorn`-style bracket pattern, to avoid the self-match.

---

## ★ HANDOFF — 2026-06-16 (New Video = idea/title generator + free channel mgmt + "Generate from my channels" UNBLOCKED end-to-end — ALL DEPLOYED)

New feature area (the CREATE/idea surface, not the render pipeline). 8 commits on `main`,
all deployed to prod (storyengine.dev). North star unchanged: the title (next to the
thumbnail) decides a video's success, so the create flow should *generate* metric-backed
ideas, not force the creator to type a topic.

**Commits (oldest→newest):** `e0b4fdd3` `c5da2f66` `eb9c62db` `f369a4f6` `d38c64d1`
`f4ec72bc` `49ed96ad` `340be6f0`.

**(1) New Video modal is now a title/idea generator (frontend).** `app/pipeline/page.tsx`
(the returning-creator "New Video" modal). Topic field is OPTIONAL (no more red `*`; Create
still needs a title, typed OR picked). Under it:
- **"Ideas from your example channels"** — pre-loads `getDiscoveryIdeas("fresh")` on modal
  open; each row = best title option + score + the competitor it's modeled on + its VPH.
  Pick → fills title + carries the idea's `our_angle` into writer guidance. Empty states:
  mining spinner, "Generate from my channels" (triggers `refreshDiscoveryIdeas`), and now
  surfaces `discoveryStatus.error` (e.g. "add a key") instead of failing silently (`c5da2f66`).
- **"Suggest titles for this"** — appears when a topic is typed; calls `suggestTitles(topic)`.
- `suggestTitles` in `lib/api.ts` now NORMALIZES the response (backend can return bare
  strings) → `{title, thumbnail_text, score}`; this also un-broke FirstVideoFlow/CreateVideoStep
  which were rendering `s.title` on raw strings (blank rows).

**(2) Free example-channel management + Profile IA.** New shared component
`components/channels/ExampleChannels.tsx` (add-by-URL / delete / re-sync), used BOTH on the
Profile page and inline in the New Video modal ("Manage channels" toggle / no-channels state).
Nav relabels (routes unchanged): **"Settings" → "Profile"** (`/settings`, H1 too) with an
**Example channels** section at the top; **"Visual Profile" → "Visual Styles"** (`/profile`)
to kill the name clash (`sidebar.tsx`, `bottom-tabs.tsx`). Channel CRUD is now FREE — the
`/api/niche/*` endpoints were never backend-gated; the heavy `/competitors` analytics page
stays Pro (`PRO_PATHS` in `AuthenticatedShell.tsx`). See [[storyengine-channels-profile-ia]].

**(3) LLM provider router for titles/ideas (backend).** `suggest_titles` (`routes/videos.py`)
and discovery (`routes/discovery.py`) now call `kie_unified.get_text_client_for_tenant(tenant)`
— tenant's own Anthropic key → `AnthropicDirectClient`, else their `kie_ai_api_key` →
`KieClaudeClient` (kie.ai is the "one key for everything", same path scripts/onboarding use),
else a clear "add a key" 400. Both use `await client.generate(prompt, model=, max_tokens=)`.
Model = **Sonnet 4.6** for titles/ideas (Ryan's call after a side-by-side: tiny outputs, the
cost delta vs Haiku is pennies, Sonnet's hooks are sharper). **`kie_unified.py` is now committed**
(was VPS-only though onboarding already imported it — committing it un-broke fresh clones).
kie model facts (live-probed): `claude-haiku-4-5` works (~10s, cheap), `claude-sonnet-4-6`
works (~35s), `claude-3-5-haiku-*` 422 on kie. The `CLAUDE_MODEL_ALIASES` fix (`d38c64d1`)
stops Haiku being silently upgraded to Sonnet — keep Haiku for bulk/script work later.
See [[storyengine-tenant-api-keys]].

**(4) "Generate from my channels" UNBLOCKED — the big one.** It was returning 0 ideas. Root
cause was NOT in this feature: **YouTube bot-blocks the VPS datacenter IP**, so the yt-dlp
per-video scrape got 0 views / no dates → VPH 0 → discovery's `VPH >= 50` filter rejected
everything. Fixed two ways:
  a. **Competitor scraping switched to the official YouTube Data API** (`49ed96ad`). New
     `backend/youtube_data_api.py` (`fetch_channel_videos`); `_run_scrape` (`routes/niche.py`)
     uses it when `YOUTUBE_API_KEY` is set (lazy import, falls back to yt-dlp otherwise),
     skipping the bot-blocked per-video call. ~3 quota units/channel; one server key reads
     PUBLIC data for all tenants (competitor data is public — no per-user OAuth, and quota is
     per-PROJECT not per-user so OAuth wouldn't help anyway). KEY: created in GCP project
     **storyengineagent** ("Competitor Scrape (StoryEngine)", restricted to YouTube Data API
     v3), lives as `YOUTUBE_API_KEY` in `storyengine/.env` on the VPS (gitignored).
  b. **Fixed a latent `UnboundLocalError: json`** (`340be6f0`) in `_run_discovery_generation`
     — a redundant `import json` inside an `if distilled_summary` branch made `json` local to
     the whole function, so `json.dumps()` at the insert threw and EVERY generated idea was
     silently dropped. Was masked until the scrape finally produced eligible videos.
  **VERIFIED end-to-end on prod:** re-scraping Ryan's "Slow English" example channel via the
  API revealed its videos actually have 80k–400k views / VPH 174–1795 (the "0 views" was
  ENTIRELY the bot-block) → discovery generated + saved **5 idea cards** (real competitor
  matches, appeal 7–9, 3 scored titles each). The engine takes the competitor's winning
  FORMAT ("Good vs Bad" comparison) and reframes it into the channel's niche (AI/tech/geopol
  from `channel_profiles`). See [[storyengine-youtube-scrape-botblock]].

**Gotchas for next session:**
- Ryan's tenant `ee93e6d1-…` has a **kie.ai key, NO Anthropic key**; plan=`null` (free tier)
  → generation runs via kie.ai/Sonnet.
- **Local dev preview can't reach authed pages** (login gate); verify with `tsc --noEmit` +
  `next build`, not the browser. See [[storyengine-local-preview-auth]].
- **Standalone VPS debug scripts** must load `storyengine/.env` first (for `DATABASE_URL`) or
  `vault.get_secret` silently returns None. Pattern used all session: read `../.env`, then
  `from vault import get_secret, fetch_all`.
- Deploy unchanged: push `main` → on VPS `git pull --ff-only` → restart. Backend SIGTERM
  STALLS (SSE drains) → escalate to `kill -9 MainPID`; systemd `Restart=always` revives. The
  frontend stops cleanly. `127.0.0.1:8001` works on the VPS (NOT `localhost` → that's IPv6
  `::1`; uvicorn binds IPv4 `0.0.0.0`).

**Open / next feature set (queued):**
1. **Add real popular channels in Ryan's niche** (operational, not code). His only example
   channel is the test "Slow English" one — it works (it has real views), but ideas come out
   reframed into the channel-profile niche. For on-target ideas, add the competitors he
   actually models. `fetch_channel_videos` handles channel-id, `@handle`, `/user/`, and falls
   back to `search.list` (100 quota units) for `/c/` custom URLs.
2. **Route SCRIPT writing through the same resolver** + a cheaper model. Scripts/onboarding
   currently use the env/default Sonnet path; `get_text_client_for_tenant` + Haiku-for-bulk
   would cut cost and unify on "one key". This is where Haiku's savings actually matter (long
   outputs), unlike titles.
3. **Discovery thresholds may be too strict** — `VPH >= 50` AND `hours_old <= 720` (30d). An
   infrequently-posting (but good) channel can yield 0 eligible videos. Consider relaxing the
   recency window or adding a raw-views fallback when velocity is unavailable. (Ryan was
   offered "rank by raw views" earlier and chose to fix the scraper first — revisit if real
   channels still come up empty.)
4. **Cheaper/faster kie model for titles at scale** — currently Sonnet (~13–35s via kie). If
   the inline "Suggest titles" latency annoys, `claude-haiku-4-5` is ~10s and ~3× cheaper
   (one-line model swap in `routes/videos.py`).
5. **Cosmetic:** a stale orphan `competitor_videos` row (a Rick Astley video, vph 0, no date)
   survives re-scrapes because it's not in the channel's current uploads — harmless, filtered
   out by discovery; delete if tidying.
6. **yt-dlp transcripts still bot-blocked** — only matters if/when transcript-level "content
   DNA" distillation is wanted (the idea engine doesn't need it). Same cookies/proxy fix as
   documented, OR an Apify/transcript-API path — separate, lower priority.

---

## ★ HANDOFF — 2026-06-14m (portrait/reference retry — one flake can't block approve — DONE + DEPLOYED)

The verify-run bug: `design_characters` / `design_environments` generated each portrait/
reference ONCE; on any failure (Kie hiccup, SSL, vision refusal) they dropped it silently,
leaving an empty card that BLOCKED approve ("Maria has no image yet"). Fixed: each item now
retries 3× with backoff before giving up (`routes/characters.py` ~286, `routes/environments.py`
~253). Persistent failures still surface via the per-card Regenerate + the clear approve error.
Happy path unchanged (succeeds first try). Commit `35729cec`, deployed. ⚠ Not paid-tested
(would need to force a transient failure mid-design) — low-risk retry wrapper, py_compile clean.

---

## ★ HANDOFF — 2026-06-14l (Part 2: "Fix text" via GPT Image 2 — DONE + DEPLOYED + verified)

Legible title/word cards. Ryan chose MANUAL-first. A per-card **"Fix text"** hover button
(Type icon) on each picture redraws just that card via GPT Image 2 (`gpt-image-2-image-to-
image` through Kie, the same model the thumbnails use). Scenes stay on nano-banana.
Commits `22a22383` + `7f14e7df`, deployed.
- `pipeline_executor.run_fix_text_card(video_id, asset_id)`: loads the panel, redraws via
  `generate_thumbnail_gpt2` (current panel = art-style/layout ref + a LEAN prompt for the
  wording), persists to Drive, replaces `assets.image_url` in place, clears the stale clip.
- `POST /api/videos/{video_id}/assets/{asset_id}/fix-text` (mirrors recrop) + frontend
  button + `fixTextAsset` api.
- VERIFIED on a bird panel (then restored exactly — bird untouched): GPT Image 2 rendered
  perfectly legible, correctly-spelled text ("How can I help you today?" + a clean speech
  bubble) in the 3D Pixar style. ⚠ LEARNING: a long/noisy prompt → Kie returns
  `failCode 500 "Internal Error"` (0 credits charged); the LEAN prompt (cap style+wording
  to ~280 chars each) succeeds. Keep fix-text/GPT-Image-2 prompts short.
- Bonus finding: GPT Image 2 nails clean SPEECH BUBBLES on scene panels too — a possible
  future lever for ESL caption/dialogue frames, not just title cards.

NEXT (Ryan's fast-follow): **auto-detect text cards** — tag title/word-card beats at the
image-prompt stage (a `title_card` scene_type or `assets.is_text_card`) and add a "Fix all
text cards" batch, so it's not purely manual. (Queue item below.)

---

## ★ HANDOFF — 2026-06-14k (clip-pipeline resilience — queue #1 — DONE + DEPLOYED)

The "Animate the rest" fragilities (no resume on restart, one error kills the batch,
stuck clips hog slots). Commit `99112390`, deployed (backend restart + frontend rebuild).
Key insight: the backend is ALREADY additive + durable (each clip writes
`assets.video_clip_url` immediately; a re-run only does the missing ones) — so resume =
re-trigger, no checkpoint table needed.
- **Frontend auto-resume** (`ScenesWorkspaceTab.tsx`): "Animate the rest" loops the
  additive backend until nothing's left — surviving restarts/transients with no re-click,
  no double-charge. Guards: 25-round cap, halt after 2 no-progress rounds, Stop cancels.
- **Per-clip isolation** (`pipeline_executor._safe_one`): a raised error (SSL/Drive/DB/
  timeout) is counted, never aborts the batch.
- **Per-clip deadline** (`_gen`=`asyncio.wait_for 420s`): stuck Grok job frees its slot
  in ~7 min, retried next round.
Verified FREE: py_compile + tsc clean, deployed healthy. ⚠ Full restart-mid-run / forced-
failure proof needs a real paid clip run — safe to do on the next "Animate the rest"
(additive + guarded). See [[storyengine-clip-pipeline-fragilities]].

---

## ★ HANDOFF — 2026-06-14j (scene style from frames, thumbnail style from thumbnail — DONE + DEPLOYED + verified)

Ryan's correction to 14i: the VIDEO's scene style must be read from a real **video
frame**, not the thumbnail (a YouTube thumbnail is a punched-up click asset — split-
screen collages, bold text — a bad proxy for the scenes). Thumbnail style stays
read from the thumbnail. Commit `f06bd437`, deployed.

`model_video.py:_generate_modeled_pack` now runs TWO vision passes:
- **SCENE** ← `_describe_scene_style` over 3 real mid-video frames (`i.ytimg.com/vi/
  <id>/hq1..3.jpg` — same CDN as thumbnails, so it bypasses the yt-dlp bot-check) →
  `image_dna` / `visual_style_brief` / every scene image_prompt.
- **THUMBNAIL** ← `_describe_thumbnail_style` → `thumbnail_dna` / `thumbnail_prompt` only.
The pack prompt labels both and routes each to the right fields; scene-style failure
is a loud blocker (falls back to thumbnail at worst), never silent.

VERIFIED: cloned ref `cfIHXpqOLxw` into a throwaway → scene style = "Pixar 3D, golden-
hour, supermarket interiors", thumbnail style = "split-screen, bold outlined text" —
correctly different. Bonus: yt-dlp was bot-blocked on the server yet scene style still
classified (CDN frames bypass it). Throwaway deleted. See [[storyengine-style-classifier-bulletproof]].

⚠ Minor pre-existing cosmetic: the oembed-fallback blocker still says "modeled from
the title, channel, and thumbnail only" even though scene FRAMES are now used too —
harmless, low priority.

---

## ★ HANDOFF — 2026-06-14i (structured prompts + bulletproof style classifier — DONE + DEPLOYED)

**(1) Structured image prompts — DONE (commit `226a5f0f`, deployed + image-verified).**
Replaced the prose char/env prompts (where the style clause got buried → drift) with
a structured JSON spec whose FIRST slots are `art_style` + `render_medium`, IDENTICAL
in both `routes/characters.py:_generate_portrait` and `routes/environments.py:
_generate_environment` → cast and locations lock to one medium. The GPT Image 2 skill's
#1 lesson, on nano-banana-2. VERIFIED by regenerating `13c334b5`'s drifted envs and
eyeballing the PNGs: maple_street (flat-2D→3D Pixar), toms_living_room (photoreal→3D
Pixar), garden_lawn (2D→3D Pixar) all clean. ⚠ `fence_line_rubbish` (a "bad-side" scene)
came back improved but more 2D-illustrated/outlined than the others — the style_dna's
"bold outlines" + bad-side grunge pulls the medium flatter. Open: re-roll it, or add a
"stay 3D CG even when grungy/bad-side" nudge. front_doorstep_morning was already fine;
classroom_title_card is a TEXT card → leave for Part 2 (GPT Image 2 routing).

**(2) Clone style-classifier bulletproofed — DONE (commit `ce4443bb`, deployed).** Ryan's
requirement: a shared-link clone must always classify the source's TRUE style (incl.
realistic/live-action), never silently default to animated — that's what lets us
reproduce ANY style. `model_video.py`: the thumbnail vision pass (`_describe_thumbnail_style`)
now retries 3×; a failed classification appends a creator-facing **blocker** (was silent
text-guess fallback); the observation prompt forces an explicit `MEDIUM:` label and forbids
defaulting to animated; the pack example is de-biased. See [[storyengine-style-classifier-bulletproof]].

**Still open from this thread:** Part 2 = route TEXT frames (title/word cards, signs) to
GPT Image 2 via Kie (`gpt-image-2-image-to-image`, already wired for thumbnails) for legible
lettering — Ryan approved direction; needs text-frame detection (cleanest: tag title-card
beats in the story bible). And the structured-prompt pattern could extend to the per-panel
builder's hardcoded `_CHARACTER_PREFIX/_ENVIRONMENT_PREFIX` (queue item 6).

---

## ★ HANDOFF — 2026-06-14h (env style-lock + voice toggle — DONE + DEPLOYED + verified)

Two asks from Ryan while reviewing the "Living in a House" video (`13c334b5`).

**(1) Env style not locking — FIXED (commit `0a5aa384`, deployed).** The env
reference images drifted across flat-2D and photorealistic even though this video's
`image_style_override` explicitly forbids both ("3D Pixar-style… No photorealism…
no flat 2D vector illustration"). Root cause: `routes/environments.py
_generate_environment` appended the style as a TRAILING "Visual style: …" clause;
an empty establishing shot is style-ambiguous so the model ignored it (characters
survive the same shape because "3D Pixar character" is unambiguous). Fix: lead with
the art style, tie it to the character art's medium, add an explicit "don't switch
medium — no photorealism, no flat 2D" lock (mirrors the storyboard grid's STYLE
LOCK). Prompt-only → affects NEW/REGENERATED env refs. **Ryan: Redo the drifted
env cards (maple_street_exterior, shared_driveway, garden_lawn) to pick it up.** If
it still drifts, see queue item 6 (visual anchor — needs a paid test).

**(2) AI voice-over now optional — DONE (commit `0a5aa384`, deployed + live-verified).**
First creation-time STAGE toggle (Ryan chose creation-time over live per-stage).
grok_native (clip) videos carry their own baked-in audio, so render_stitch ignores
`voice_over_url` — narration was generated-but-unused for them. Now skippable:
- migration `052` `videos.skip_voice` (applied to prod) + `CreateVideoRequest.skip_voice`
  + persisted in `create_video`.
- `pipeline_executor._skip_disabled_next(video, natural_next)` — a finished script
  advances past `ready_for_voice` straight to `ready_for_image_prompts` when
  skip_voice (both script paths routed through it); both voice gates (image-prompts
  @~1699, image-gen @~2384) are satisfied without narration. Generalizes to other
  stages (queue item 5).
- Frontend "Add AI voice-over?" toggle on BOTH create surfaces (onboarding +
  dashboard modal). Default ON → unchanged behavior.
- Live-verified on prod: skip_voice=true persists; skip_voice→idea_logged,
  skip_research+skip_voice→ready_for_scripting (test rows soft-deleted). Pre-checks:
  py_compile + tsc clean. ⚠ Safe for CLIP videos; a documentary/Ken-Burns video with
  skip_voice would render silent (its narration IS the audio) — UI copy frames it as
  "No narration · Clips' own audio".

---

## ★ HANDOFF — 2026-06-14g (research toggle for typed topics — DONE, not yet deployed)

Build-plan item #1 (Ryan's ask). For typed-topic videos, research is now OPTIONAL
at creation — a "Research this topic first?" choice. Default = research ON (status
`idea_logged`, unchanged). Skip → video lands straight at `ready_for_scripting`,
same as clones; the standard script bot writes from title + writer_guidance +
framework_angle (verified: `skills/video-pipeline/script/run.py:100-121` already
builds a full brief when `research_payload` is empty — "not set — legacy idea").

Touched (byte-identical default behavior — `skip_research` defaults False everywhere):
- `backend/models.py` — `CreateVideoRequest.skip_research: bool = False`.
- `backend/routes/videos.py:create_video` — `initial_status = ready_for_scripting if
  skip_research else idea_logged`; INSERT renumbered to bind status as a param.
- `frontend/src/lib/api.ts` — `createVideo({ …, skip_research? })`.
- `frontend/src/components/onboarding/CreateVideoStep.tsx` — "Research this topic
  first?" two-button picker (mirrors the aspect picker), `needsResearch` state,
  sends `skip_research: !needsResearch`.
- `frontend/src/app/pipeline/page.tsx` — SAME toggle in the dashboard "New Video"
  modal's Advanced options (the repeat-creator flow — onboarding runs once). NOTE:
  this modal still lacks the aspect picker (aspect only shipped in onboarding) — a
  small consistency gap if anyone wants to close it.

DEPLOYED + LIVE-VERIFIED (2026-06-14, commit `2aa68514` on prod). Backend
restarted + frontend rebuilt/restarted; public edge 200. Live end-to-end test
against prod: `POST /api/videos {skip_research:true}` → `ready_for_scripting`;
default → `idea_logged` (test rows soft-deleted). Pre-checks: `py_compile`
(backend) + `tsc --noEmit` clean. Note: the deploy restart also cleared a stale
in-memory "running" task flag that had video `13c334b5` ("Living in a House")
jammed at `ready_for_storyboard_extraction` (storyboard-image batch died ~1.5h
prior without clearing it — the no-resume fragility in [[storyengine-clip-pipeline-fragilities]]);
it's unblocked now.

---

## ★ HANDOFF — 2026-06-14f (content-quality: ALL 3 FIXES DONE; paid verify next)

**Fix #3 — forward-continuity + recap — DONE (commit `dcf46f9d`, deployed + restarted).**
The image-plan/description prompts had "find the primary verb, show that action" with no
story-state notion, so vocab-recap narration ("Word six: Bandage…") got literally re-staged
(bird re-bandaged after release). Added two rules at BOTH prompt stages
(`script/story_bible.py` scene_blocks plan + `script/brief_translator/scene_expander.py`
description writer): FORWARD CONTINUITY (no re-staging a resolved state) + RECAP/OUTRO/CTA
narration → word cards / character-to-viewer / resolved-callback, never re-enact the problem.
Prompt-only; affects NEW videos.

**All 3 content-quality fixes are DONE + deployed.** Ryan approved a PAID end-to-end verify
(a NEW small test video, NOT the bird) to confirm: Fix #1 (real char descriptions), Fix #2
(2-ref env conditioning holds the room without softening faces), Fix #3 (recap shows word
cards, not re-staging). Recommended bounded test = run a new video THROUGH STORYBOARD GRIDS
only (~$1–3), inspect the grids, before any clip spend (~$7+).

---

## ★ HANDOFF — 2026-06-14e (content-quality: Fix #1 + Fix #2 DONE; Fix #3 next)

**Fix #2 — ENVIRONMENT LOCKING — DONE (commit `f1d0490b`, deployed: migration 051
applied to prod, backend restarted + booted with the new router, frontend rebuilt).**
Scenes drifted because environments were only text labels with no locked image. Now
mirrors character locking:
- `video_environments` table (per `story_bible.locations[]`) + `videos.environments_approved_at`
  gate + `assets.location_id` (structured per-panel location). Migration `051`.
- `routes/environments.py` (clone of characters.py) + a new **Environments tab** (between
  Characters and Scenes) design/approve a reference image per location (nano-banana-2,
  16:9, "no people" establishing shot, ~$0.025 each, 2–4/video).
- **Keystone:** `image_prompts/run.py` now persists `block_location_id` onto each asset
  (`assets.location_id`, via `supabase_adapter`); `_row_to_image` surfaces it. THIS is the
  reliable beat→location key (the bible's scene_blocks/location_ids don't map cleanly to
  the final beats — they're a planning layer).
- **Conditioning:** each storyboard grid resolves its dominant `location_id` from its
  panels and passes ONE location ref alongside the cast sheet (exactly 2 refs — ≥3 dilutes
  the character lock). `bot._resolve_env_ref_for_images` + the `generate_contact_sheet`
  "last image is the location" directive. **Opt-in** — no approved environments = byte-
  identical to before.
- Verified FREE: migration live, backend boots + `/environments` route 200, the env-ref
  resolver unit-tested (dominant/opt-out/unmapped/empty), frontend compiles + serves.
- ⚠ **STILL NEEDS ONE PAID NEW TEST VIDEO** to validate conditioning QUALITY (do 2 refs hold
  the room without softening faces?). If faces soften, the fallback is prompt-only env (drop
  the env image — one-line revert in `bot.py`). Do NOT regen the bird.

**Fix #3 — recap/continuity beats — NOT started (task #13).** Scene-8 vocab recap re-stages
resolved plot (Tom re-bandaging the bird after release). Smaller, free, self-contained.

(Fix #1 — character-description refusal bug — DONE, see below.)

---

## ★ HANDOFF — 2026-06-14d (content-quality tightening; Fix #1 of 3 DONE)

Ryan watched the rendered bird video (B−) and flagged 3 issues to tighten before
launch. Diagnosis is grounded (read the script, the storyboard prompts, AND the
images). Working ONE AT A TIME, review each before spend.

**Fix #1 — character-description refusal bug — DONE (commit `d7a67c1c`, live).**
Every `video_characters.description` was an AI refusal ("I'm unable to access or
view files…"). The character-design **vision pass** (`routes/characters.py` ~557,
`vision_call`) hit Kie's Claude gateway silently dropping the image; `_try_kie_claude`
has no ingestion guard, so the refusal was saved as the description → no facial text
anchor. Cascade: storyboard-prompt gen then **invented** outfits ("Tom: red t-shirt"
when the real reference is a **light-blue** fox tee) → fought the reference → drift.
Fix: centralized refusal detector in `skills/video-pipeline/shared/clients/vision_client.py`
(`_looks_like_refusal`) — refusal replies now treated as provider failures. Regenerated
all 6 bird descriptions from the real portraits (accurate now). ⚠ Does NOT retroactively
fix the bird's already-generated panels — visible gain needs panel+prompt REGENERATION.

**Fix #2 — environment reference images (task #12, NOT started).** Environments are
text labels only (`SUNNY_GARDEN`, `VET_EXAMINATION_ROOM`) — no locked image, re-invented
each panel. Ryan's idea: generate one ref image per environment, condition panel gen on it.

**Fix #3 — recap/continuity beats (task #13, NOT started).** Script is correct; the
scene-8 vocabulary recap (panels 10–21) re-illustrates words literally — "bandage" =
Tom re-wrapping the bird AFTER it flew free. Recap/outro beats must not re-stage resolved
plot (word cards / kids-to-camera / labeled callbacks); add bird-state awareness.

**Also found:** aspect correction — panels are 16:9 (1376×768); clips are portrait because
**Grok reshapes** them (ignores input aspect) → the aspect lever is the CLIP stage, not
the image stage. And a style contradiction: grids say "3D Pixar CG", per-panel image_prompt
says "2D animated illustration".

---

## ★ HANDOFF — 2026-06-14c (aspect ratio chosen at creation; bird is clean vertical)

Commit `8ed98340`, deployed (backend restarted + frontend rebuilt + prod DB migrated).

**Bird video `f32ed182-…` is now a clean VERTICAL video** (728×1080, no distortion,
in sync, plays in-app). Its clips are physically portrait (73/74 × 464×688), so
vertical is correct — Ryan agreed to roll with it. `aspect_ratio` column set to `9:16`.

**New: aspect ratio is a first-class creation choice.**
- `videos.aspect_ratio` column (`'16:9'|'9:16'`, default 16:9, CHECK). Migration
  `add_videos_aspect_ratio` applied to prod (existing rows backfilled to 16:9).
- Picker on the create screen (`CreateVideoStep.tsx`, by the length picker:
  "What shape should the video be?" 16:9 / 9:16). `CreateVideoRequest.aspect_ratio`
  (Literal) + create INSERT (`routes/videos.py:180`). Verified live: 9:16 stores
  9:16, default stores 16:9, invalid → 422.
- Flows into the **storyboard grid request** (executor sets `pipeline.aspect_ratio`
  → `run_images` → `run_storyboard_images` → `generate_contact_sheet`, was hardcoded
  "16:9") and the **thumbnail** (`run_thumbnail` clone path + `_build_thumbnail_clone_prompt`).
- **Render needs NO column wiring** — `render_stitch` auto-detects orientation by
  probing the actual clips (robust for legacy/mismatched content). The column drives
  generation; render follows the pixels.

**STILL OWED — deterministic panel-aspect backstop (task #10, needs a paid test gen):**
The image model (Kie/nano-banana) returned PORTRAIT for the bird even though the grid
was requested at 16:9 — so requesting the aspect is necessary but NOT sufficient. The
guarantee layer is forcing each cropped panel to the chosen aspect (scale+pad or
center-crop) in the storyboard extraction/upscale path, so Grok clips (which inherit
the image shape — Grok has no aspect param) come out right. NOT built: it needs one
real 16:9 video run through generation to observe + tune (pad vs crop), and there's a
`generate_scene_image`/`upscale_panel` signature mismatch to resolve. **9:16 likely
works already** (model defaults portrait); **16:9 is the unproven case.** Don't claim
16:9 generation works until that test is run. Voice_over/Remotion aspect also deferred.

---

## ★ HANDOFF — 2026-06-14b (render FROZEN-FRAME bug fixed + final video plays in-app)

Two follow-ups after the stitch shipped (commit `985c507a`, deployed: backend
restarted + frontend rebuilt):

1. **Frozen-frame bug FIXED.** Ryan's first stitched download froze on frame 1
   in QuickTime while audio played. Cause: `-c copy` concat keeps only the FIRST
   clip's H.264 parameter set (avcC) in the MP4 header; each Grok clip has its own
   SPS/PPS (+ an mjpeg attached-pic track + unset mov timescale), so strict players
   freeze (ffmpeg/VLC were lenient and hid it). `render_stitch.py` `_concat` now
   **re-encodes** to one clean H.264 stream (`-map 0:v:0 -map 0:a:0`, libx264
   veryfast, CFR 24, clean timescale). ~50s for the 9-min bird video. Re-rendered:
   final is now 48.6MB, single h264+aac, frames verified advancing. **No stream-copy
   fast path anymore** — it's a footgun for these clips. Preset/crf/fps via
   `STITCH_X264_PRESET`/`STITCH_X264_CRF`/`STITCH_FPS` env.
2. **Final video now plays IN-APP.** It was broken: the player fed the raw Drive
   `uc?export=download` URL into `<video>` (won't stream). Fixes: allowlist
   `final_video_url` in the media proxy (`routes/media.py` `_ALLOWLIST_SQL`); add
   HTTP **Range/206** to `serve_drive_file` (`_download_range`) so `<video>` streams
   + seeks; new `toDisplayVideoUrl` (`frontend/src/lib/utils.ts`) + `RenderTab.tsx`
   route the player through `/api/media/drive/<id>`. Verified: proxy returns 206 with
   correct Content-Range; full fetch is a valid mp4. Ryan should hard-refresh the
   Render tab to see it.

20-concurrent note: with re-encode the 4-core VPS is the ceiling (~17 min for the
last of 20 simultaneous 9-min renders, vs 60–90 min EACH on old Remotion). The
ffmpeg semaphore (`STITCH_FFMPEG_CONCURRENCY`, default 3) queues the burst.

---

## ★ HANDOFF — 2026-06-14 (RENDER SOLVED for grok_native — FFmpeg stitch is LIVE)

Read this first. Supersedes the render sections below (their *file-lines* are
still accurate, but RENDER is no longer blocked for grok_native).

**What shipped (deployed to prod, commits `0085c448` + `75f847c6`):**
- New **FFmpeg clip-stitch render path** for grok_native videos. Every grok_native
  clip already carries Grok's baked-in audio, so the "render" is just the clips
  concatenated in (scene, image_index) order — no Remotion, no
  `render_config.json`/Whisper, no `Scene.tsx` muted-clip+narrator bug. Code:
  `storyengine/backend/render_stitch.py` (`stitch_video()`); wired in
  `pipeline_executor.py` `run_render` → branches `grok_native` → `_run_stitch_render`,
  else legacy Remotion (unchanged). The route (`/api/pipeline/render/<id>`) and the
  render fast-path are IDENTICAL — no new endpoint.
- **Bird video `f32ed182-…` is now `rendered`.** `final_video_url` set (Drive),
  102MB, h264 736x400 + AAC 48kHz, **539.1s**, audio verified present
  (mean −30 dB). Real production path: ~27s start→finish, method=`copy` (stream-copy).
- **Built for ~20 concurrent renders** (Ryan's explicit ask): per-render `tempfile`
  dir (no shared `public/` collision like Remotion had), a per-worker GoogleClient
  download pool (httplib2 is NOT thread-safe — one shared connection raced and
  crashed; fixed in `75f847c6`), and a process-wide ffmpeg semaphore
  (`STITCH_FFMPEG_CONCURRENCY`, default 3) so the re-encode fallback can't melt the
  4-core box. Stress-tested **4 concurrent stitches → 4/4 OK, load 0.50→0.89** (CPU
  is nowhere near the limit; stream-copy is ~free). At true 20× the ceilings become
  Drive download bandwidth + RAM (each render holds ~100MB final bytes in memory for
  upload) — both have headroom (13Gi free), but streaming the upload is the obvious
  next optimization if needed.

**Still owed / not done here:**
- **voice_over videos still hit the Remotion blockers** (missing `render_config.json`
  crash + `Scene.tsx`). Only grok_native is on the new path. Wire `run_audio_sync`
  (or stitch+narrator-mux) if a voice_over video needs to render.
- **Clip-pipeline fragility fix** (no resume / one-blip-kills-batch / 10-min
  slow-poll) is STILL UNFIXED — see the fragilities section below. Separate from render.
- Thumbnail character-fidelity issue (generic look-alikes) still open — see below.

---

## ★ HANDOFF — 2026-06-14 (clips DONE, thumbnail built, RENDER is next)

Read this first. The "▶ NEXT GOAL" and older handoffs below are still correct on
render *details/file-lines* but their status numbers are STALE.

**Bird video `f32ed182-be1f-4a24-a8de-bb8db4ac88df`, tenant `ee93e6d1-…`. State now (prod DB):**
- **All 74/74 clips animated** (was 8/74). Finished this session with a server-side
  per-scene → per-asset runner because the "Animate the rest" button kept dying
  mid-batch (see fragilities note below). grok_native, so Grok's dialogue is baked
  into the clips.
- **Thumbnail built + live.** status `ready_for_thumbnail`. The in-app **Regenerate**
  button (`production/ThumbnailTab.tsx` → POST `/api/pipeline/thumbnail/<id>`) now runs a
  **reference-clone**: cast sheet (`character_reference_url`) fed FIRST + the modeled
  YouTube thumbnail (`reference_url` → `img.youtube.com/vi/<id>/maxresdefault.jpg`)
  SECOND/layout-only, driven by the editable **`thumbnail_prompt`**. Model = **GPT Image 2**
  (`gpt-image-2-image-to-image` via kie.ai, `image_client.generate_thumbnail_gpt2`),
  nano-banana-pro fallback. Code: `pipeline_executor.py` `run_thumbnail` +
  `_build_thumbnail_clone_prompt`; commits **80fc65db, 29c59d22, 8fcc7fd6** (all deployed).
- **Thumbnail OPEN ISSUE (Ryan rejected current quality):** the generated people are
  generic Pixar look-alikes, NOT the exact cast-sheet characters — faces/builds/outfits
  differ, Dr. May loses her East-Asian design. Root cause: one 6-up cast sheet is weak
  conditioning; the model invents faces. Options offered (Ryan deferred to do the render):
  (1) per-character reference crops [strongest generative lock], (2) composite the real
  character art [exact chars but stiff poses], (3) accept type-accurate. NOTE: the video's
  own scene panels ALSO drift from the sheet — broader character-consistency gap, not just
  the thumbnail.

**NEXT STEP = RENDER. Two real code blockers remain (now MORE relevant — all clips are grok_native):**
1. **HARD BLOCKER — `timing/<id>/render_config.json` missing → instant crash.**
   `render/run.py:141` raises RuntimeError if `skills/video-pipeline/timing/<video_id>/render_config.json`
   is absent, and the prod pipeline never calls `run_audio_sync`. FIX: run audio-sync for
   this video (run `render/run_audio_sync.py` for the video_id on the VPS, or wire it into
   the render preflight). Whisper must be installed where it runs.
2. **grok_native audio will be wrong.** `remotion-video/src/Scene.tsx:260` hardcodes
   `muted` on every clip and `Main.tsx` always plays the ElevenLabs narrator. This video is
   grok_native (dialogue baked into the clips) → render would mute the clips and play only
   the narrator. FIX: thread `dialogue_audio` + a per-scene "speaking" flag from the videos
   row → `render/upload/run_package.py` props.json + render_config → `Scene.tsx`; drop
   `muted` and duck/suppress the narrator on grok_native speaking scenes; keep voice_over
   unchanged. Preview with `cd remotion-video && npm run studio` before a full render.

**Render fast path (after the two fixes):** Approve & Advance (Thumbnail tab) to
`ready_to_render`, then POST `/api/pipeline/render/<id>` → ~10–20 min `npx remotion render`
in `remotion-video/`, uploads mp4 to Drive, sets `videos.final_video_url`, status→rendered.
Poll `GET /api/pipeline/status/<id>`. **Do NOT deploy/restart during the render (no resume).**
Then check the audio; optional `POST /api/pipeline/upload/<id>` → private YouTube draft.

**Infra (NEW this session — operating prod from Ryan's Mac):**
- `ssh storyengine-vps` (user `clawd`, key `~/.ssh/storyengine_vps`). Project
  `/home/clawd/projects/economy-fastforward`.
- **Deploy = git push main (Mac) → on VPS `git pull --ff-only` + restart.** No passwordless
  sudo, so restart = `kill -9 $(pgrep -f "uvicorn main:app")` and systemd `Restart=always`
  revives it (~10–15s). Verify: `curl localhost:8001/api/pipeline/task/<id>`.
- Token `/tmp/se_token` (re-minted, 7-day). API `localhost:8001`. Prod DB = Supabase
  `wrromlupsmyzrrcqlucn` (via Supabase MCP). API keys (KIE/OpenAI/…) live in the `secrets`
  vault TABLE, hydrated to env at runtime — NOT in `.env`/`/proc`; a standalone script must
  `vault.get_secret(...)` or inherit the running uvicorn process's env. No OpenAI key set —
  GPT image runs through kie.ai's `KIE_AI_API_KEY`.
- **Clip pipeline still FRAGILE + UNFIXED** (Ryan approved fixing it but we did the thumbnail
  instead): all-clips batch has no resume (a restart/crash/SSL blip kills it), clips slow-poll
  ~10 min, a just-completed task lingers 30s and 409s the next tap. Regenerate clips
  scene-by-scene / per-asset, never one giant batch.

---

## ▶ NEXT GOAL (Ryan, explicit): finish the bird video to THUMBNAIL + RENDER on the VPS

Read this section, then the full handoff below. Recon for this was done by a
4-agent workflow (thumbnail/render/state/banner) with adversarial blocker
verification — the findings below are verified, not guesses.

**Where the bird video is right now (prod DB, confirmed):** status
`ready_for_video_generation`, dialogue_audio `grok_native`, 74/74 pictures,
**8/74 clips**, no thumbnail, no final video, `render_config.json` MISSING.

**The honest situation:**
- THUMBNAIL works today (no code needed). It makes 3 options from text (no
  vision). The fancy Gemini "best-of-3" 4th image is skipped because Ryan's
  tenant has no Gemini key — that's fine, you still get a thumbnail.
- RENDER has **two real problems** that must be handled before a good render:
  1. **HARD BLOCKER — the timing file is missing and nothing makes it.**
     `render/run.py:141` raises `RuntimeError` ("Audio sync must run before
     rendering") if `skills/video-pipeline/timing/<video_id>/render_config.json`
     doesn't exist. It doesn't for this video, and the production LightPipeline
     NEVER calls `run_audio_sync` (only the old image-prompts stage did). So a
     plain render request CRASHES instantly. FIX: wire `run_audio_sync` so it
     runs for Supabase videos (add a standalone trigger, or run
     `render/run_audio_sync.py` for this video_id on the VPS), OR add it to the
     render preflight. Whisper must be installed where it runs. This is the #1
     job before render will do anything.
  2. **AUDIO WILL BE WRONG for grok_native — code fix in Remotion.**
     `remotion-video/src/Scene.tsx:260` hardcodes `muted` on every clip and
     `Main.tsx` always plays the ElevenLabs narrator track. For this video the
     Grok dialogue is baked INTO the clips — render mutes it and plays only the
     narrator, the opposite of grok_native. `grep dialogue_audio remotion-video`
     = 0 hits. FIX: thread `dialogue_audio` (+ a per-scene "speaking" flag) from
     the videos row → `render/upload/run_package.py` props.json + render_config →
     `Scene.tsx`; drop `muted` and suppress/duck the narrator on grok_native
     speaking scenes. Keep current behavior for voice_over. Preview with
     `cd remotion-video && npm run studio` before a full VPS render.

**Phantom blockers — DO NOT chase these (verified false):**
- Plan/billing gate: tenant is at 0/120 render-minutes, passes clean.
- No Redis on the VPS: render runs in-process via BackgroundTasks fine — just
  don't deploy/restart during the ~10–20 min render (it has no resume).
- Kie-Claude vision drift: does NOT touch the thumbnail stage (text-only gen).

**Fast path to a render (exact calls; `T=$(cat /tmp/se_token)` on the VPS,
base `http://localhost:8001`, header `Authorization: Bearer $T`):**
1. Clips: either finish (`POST /api/pipeline/clip/<id>` = all 66 remaining,
   ~$6.60 at $0.10/clip; or per scene `?scene=3`) OR skip
   (`PATCH /api/videos/<id>/advance?to=ready_for_thumbnail`). grok_native +
   stills get gentle zoom, so skipping is viable — but note skipped scenes have
   NO spoken dialogue (only the clips carry Grok's voice), so for a real watch
   you probably want clips finished. Ryan's call.
2. Thumbnail: `POST /api/pipeline/thumbnail/<id>` (or skip
   `?to=ready_to_render`). Advances to ready_to_render.
3. **Fix render blocker #1** (render_config) — render crashes without it.
4. Render: `POST /api/pipeline/render/<id>` → ~10–20 min `npx remotion render`
   in `remotion-video/`, uploads the mp4 to Drive, sets `videos.final_video_url`,
   status → rendered. Poll `GET /api/pipeline/status/<id>`.
5. Watch the mp4's audio — if grok_native sounds wrong, that's blocker #2.
6. (Optional) `POST /api/pipeline/upload/<id>` → private YouTube draft.

**Two still-flagged bad crops (cosmetic, won't block render):** S4.4, S6.12
(`extraction_flags=['label_leak']`) — tap "Bad crop — fix it" in the Scenes
tab to re-crop, or leave them.

**Full thumbnail/render entry points** (for when you build the fixes):
thumbnail route `routes/pipeline.py:1247` → `PipelineExecutor.run_thumbnail`
(`pipeline_executor.py:2710`) → `thumbnail/engine.py`. Render route
`routes/pipeline.py:1297` → `run_render` (`:2757`) → `render/run.py:run()` →
`npx remotion render Main` (composition in `remotion-video/src/Main.tsx`).

---

## ★ THREAD HANDOFF — read this first (2026-06-13, Scenes-workspace thread: all 4 answers shipped)

**North star (in agent memory too):** any person pastes a YouTube link → the
machine replicates that video (new script/idea) FULLY UNATTENDED. Ryan has a
queue of people wanting their channels automated; every design choice must
work without a human in the loop. Intelligence layers detect format — never
manual flags. Corollary: every pipeline element must be OPTIONAL
("sometimes they just want research, ideas and script").

**Working video:** the "Injured Baby Bird" ESL kids animation,
`f32ed182-be1f-4a24-a8de-bb8db4ac88df` (Ryan's tenant `ee93e6d1-…`).
Kie-only stack. Prod = systemd from /home/clawd/projects/economy-fastforward
(git push main → pull there; restart = kill -9 MainPID, uvicorn hangs
draining SSE). Dev repo = /home/clawd/economy-fastforward. Auth for API
test scripts: mint JWT {iss:"storyengine", sub:<account uuid>, tenant_id}
with SESSION_SECRET from PROD storyengine/.env (dev repo has NO .env;
account 381bdcc3-…, a ready token sits in /tmp/se_token on the VPS).
⚠ Clip taps within ~10s of a restart fail (cold-proxy race, see lessons
pt 12 — backoff shipped, but don't script POSTs right after a deploy).

**RYAN'S 4 ANSWERS — ALL SHIPPED + VERIFIED LIVE this thread:**
1. ONE SCENES WORKSPACE ✓ — `ScenesWorkspaceTab.tsx` replaces the separate
   Storyboard + Video Clips tabs (both DELETED). One card per scene: boards
   row (drag-drop replace, per-slot X) → animatic → narration → a
   SegmentCard grid where each story segment shows its clip (tap=play,
   hover Redo/X) OR its picture (tap=Animate ~$0.10, hover X), with the 💬
   speaker badge and the red bad-crop badge. Per-scene verbs (Plan / Draw /
   Redo boards / Start over / Animate this scene·$X), one status strip, one
   merged ⋯ Advanced. Tabs renumbered 10→9 ("4 · Scenes"); legacy tab ids
   map across; next-action targets "scenes"; default tab lands on Scenes
   through ready_for_video_generation. Verified live on prod (Playwright,
   Ryan's tenant): 8 scenes, 12/13 boards, 74/74 pictures, 7 Animate-scene
   buttons, 3 bad-crop badges, zero console errors; Scene 1 board + 4
   picture cards render (screenshots in /tmp/scenes_workspace*.png).
2. AUTO RE-ANIMATE ✓ — run_recrop_panel AND run_storyboard_extract track
   pictures replaced under an existing clip and re-run clip generation for
   exactly those (force=true, ~$0.10 each, never animating unpaid cards).
   Verified live: scene-2 re-crop → "re-animated 3/3 stale clip(s) (~$0.30)".
3. OFF-SCREEN SPEAKER RULE ✓ (supersedes "cutaway rule") — S1.4 was never a
   cutaway: its sentence carries the tail of Tom's line, so it's a SPEAKING
   card and the prompt itself summoned the boy. OFF_SCREEN_SPEAKER_RULE now
   rides every speaking prompt (verified live: legs stay at frame edge).
   motion_guard still guards NARRATION cards (cutaway → NO PEOPLE; else →
   nobody-NEW).
4. EXTRACTION VALIDATION ✓ — panel_flags (label_leak/gutter_split, 15/15 on
   real panels), separator-rect cropping (the generator drew scene 2 as
   3-top/2-WIDER-bottom — uniform crops CANNOT cut it), chip auto-trim,
   orphan guard, migration 050 assets.extraction_flags, POST
   /videos/{id}/assets/{aid}/recrop (re-cuts the whole beat, background
   task), red badge + one-tap fix wired into the Scenes workspace. Scene 2
   re-cropped 5/5 clean live; 12 orphan rows deleted + Drive copies trashed.

**What is LIVE (this thread + clips day):**
- THE SCENES WORKSPACE is now the visuals surface (see answer 1 above). The
  old VideoClipsTab/StoryboardVisualsTab are gone — don't resurrect them.
- Clip generation per the UX contract: tap card = animate ($0.10 Grok, no
  confirm), per-scene buttons, banner trust ladder, 💬 speaker badges,
  hover Redo/X, real cost math, ⋯ Advanced (model picker — grok + veo
  wired), silent motion-prompt auto-run, always-on useTaskWatcher (pill).
- All 158 dialogue segments voiced (ElevenLabs via Kie, jsonb audio_url+
  duration); cast: Tom=Finn, Lisa=Brittney, Mom=Tiffany, Dad=Brian,
  Dr.May=Bella, Bird=Emma; narrator=Mark. Casting excludes narrator voice.
- DIALOGUE AUDIO IS PER-VIDEO (migration 049 videos.dialogue_audio, toggle
  in clips ⋯ menu). Bird video = 'grok_native': NO overlay, Grok speaks the
  EXACT scripted words (native_speaking_prompt feeds only the sentences the
  card covers; match_lines is sentence-level). Ryan LOVES S1.3 native.
  'voice_over' mode (ElevenLabs overlay + ambience bed) is one toggle away.
- Clip prompts: constraints LEAD (@image1 = ground truth, no invented/
  resized characters, off-screen stays off-screen), cast sheet as @image2
  with names, style directive appended, cutaway no-people rule.
- Skip buttons live on the guided banner (white pill, "I don't need this —
  skip it →", consequence confirm, advance?to= forward jump): research,
  review, voice, clips rungs, sound, thumbnail.
- The lip-sync saga is SETTLED — read decisions.md before touching it:
  five approaches tested in one day; final = Grok full-scene + native
  voices for this video. Kling-style video lip-RETARGETING is the upgrade
  if Kie ever ships one.
- Claude-via-Kie VISION IS DEAD (gateway drift; images become file refs,
  ~272 input tokens). Parallel session rerouted vision via
  shared.clients.vision_client + canary (see pt 11 handoff below).

**VERIFIED / RESOLVED this thread (2026-06-13 early):**
- S1.4 ✓ off-screen rule holds (bird close-up stays a cutaway, audio track
  carries the line — Ryan should LISTEN to confirm the words).
- S2.2/S2.3/S2.4/S2.5 ✓ re-cropped clean (chips trimmed, split healed);
  their 3 existing clips were redone on the new pictures (~$0.30).
- Motion prompts: real coverage is 74/74 — the "86" included 12 orphan
  extraction rows (no sentence/prompt), now deleted. Stat is honest now.
- Two extra bad crops found + healed that nobody had reported: S4.4,
  S6.12 (the validator caught them; S2.3's chip too).
- SECURITY NOTE: a stale .env backup briefly hit the PUBLIC repo (force-
  rewritten in minutes; creds were for a DELETED Supabase project — dead).
  .env.bak* now gitignored. Stale local artifacts quarantined in
  ~/economy-fastforward-stale-artifacts (they had CONFLICTING migration
  numbers — never git add -A in that old Mac checkout).

**Open / next session:**
- RYAN TO REVIEW the Scenes workspace end-to-end (it's a big surface change —
  every video opens here now). Watch a re-crop on S4.4 or S6.12 (still
  flagged) and confirm the bad-crop badge → one-tap fix feels right.
- S2.2 style (semi-photoreal bird) — label bar is FIXED; redrawing the
  board would replace 4 good panels. Ryan's taste call.
- Scene 5 'Receptionist' speaks 2 lines in narrator voice (uncast walk-on).
- tag-dialogue auto-hook still modeled-path only.
- Next pipeline elements (from clips day): (b) animatic segment timeline;
  (e) render respecting dialogue_audio (grok_native clips carry their own
  audio); full keep/skip matrix so every element is obviously optional.
- Scene 5 'Receptionist' speaks 2 lines in narrator voice (uncast walk-on).
- tag-dialogue auto-hook still modeled-path only.

**Read before coding:** tasks/lessons.md pt 12 (off-screen speaker rule,
cold-proxy race, extraction rects, per-panel flag comparisons) and pts
7–10 (NULL-column .get trap, status-lag gates, Kie TTS flakes, vision
drift, watcher-not-poller×2), tasks/decisions.md (clips UX contract,
extraction-trusts-pixels, off-screen speaker, dialogue final form,
voice-over optional). Session history below.

## Handoff (2026-06-12 pt 11 — vision rerouted + canary live)

The morning's dead Kie Claude vision REVERTED on its own (12/12 repro calls
fine by evening) — classic provider drift, so the fix is structural:
- `shared/clients/vision_client.py`: ALL product vision goes through one
  provider chain (Kie Gemini 2.5 Flash with per-call ingestion proof →
  Kie Claude → direct Anthropic). 9 unit tests.
- Rerouted: model_video thumbnail pass (now a separate vision pass whose
  observation is injected into the pack prompt as TEXT — generation never
  carries an image block), storyboard `_grid_style_matches_reference`,
  characters approve-cast rewrite.
- `canaries/vision_drift.py` hourly USER systemd timer (no root; linger on)
  + ntfy alert (same topic as validator canary). Known image: red circle on
  blue at Supabase `assets/<tenant>/canary/vision_canary.png` (~$1.5/mo).
- NOT migrated (legacy YouTube pipeline, direct Anthropic SDK):
  autopilot/analysis/thumbnail_analyzer.py, video_dispatch/verify_output.py.

## Handoff (2026-06-12 pt 7 — clips UX contract locked + per-segment voice SHIPPED)

Ryan answered 8 design questions for the clips stage (full contract appended to
decisions.md as "Video Clips stage UX contract" — read it before touching the
clips tab). Headlines: three-rung trust ladder (card tap ~$0.10 → "Animate this
scene" → banner-gated "Animate everything"), Generate Prompts button dies
(prompts auto-run silently), ALL segments get clips, 💬+name badge on dialogue
cards, voice auto-chain on tap, cost confirm >$0.50 only, play-inline +
hover Redo/X on cards, strip + ⋯ Advanced replaces all six header surfaces.
Found during recon: VideoClipsTab cost is fake (86×$0.30 hardcoded = $25.80;
Grok is ~$0.10/6s → ~$8.60), the model dropdown writes videos.video_model but
the BACKEND IGNORES IT (Grok hardcoded in image_client.py:704-785), and no
single-clip endpoint exists at all — both get wired during the clips build.

STEP (a) PER-SEGMENT VOICE SYNTHESIS SHIPPED:
- backend/dialogue_voice.py: walks scripts.dialogue_segments; narrator voice
  (scripts.voice_id) for narration, video_characters.voice_name for dialogue
  (stability .45 / style .2 / speed 1.05 — client gained style+speed params),
  uploads {video}/voice/S{n}-seg{i}.mp3 via storage.upload_bytes, writes
  audio_url + duration (+voice_name) into the jsonb AFTER EVERY segment
  (resume-safe), 3 attempts/segment with 5s backoff (Kie TTS flakes
  "internal error" transiently — hit twice live), cooperative cancel.
- executor.run_dialogue_voice (auto-tags untagged videos first; narration-only
  videos complete as a no-op) + silent auto-hook after full voice runs for
  dialogue-mode videos + POST /api/pipeline/dialogue-voice/{video_id}?scene=N.
- 6 functional tests: tests/functional/test_dialogue_voice.py (module-stub
  pattern, zero network) — voice routing, resume skip, per-segment persist,
  cancel-keeps-work, scene filter, helpers.
- Bird video live: scene 1 verified (14/14 voiced; real MPEG bytes pulled via
  authorized Drive API; header duration == db duration; 19.4s timeline).
  Tom RECAST Mark→Finn (his cast voice was IDENTICAL to the narrator —
  cast_character_voices now excludes the narrator's voice from the roster);
  scripts.voice_id was an off-roster id, set to Mark explicitly. Full 8-scene
  run (158 segs, ~$1-2 TTS) launched in background — check segment counts via
  scripts.dialogue_segments before building (b).

CLIPS TAB REBUILT same session (the UX contract is now LIVE code):
- POST /api/pipeline/clip/{video_id}?asset_id=&scene=&force= — ONE endpoint
  for all three rungs (tap a card / Animate this scene / Animate everything);
  executor.run_clip_generation honors videos.video_model via MODEL_REGISTRY
  (grok + veo-3.1 fast/quality wired; others rejected with friendly copy),
  proxies panel images via PUBLIC_MEDIA_BASE/api/media/drive/{id} for Kie,
  downloads clips IMMEDIATELY (24h URL expiry) → Drive {video}/clips/
  S{nn}-{ii}.mp4 → assets.video_clip_url, semaphore(3), cancel support,
  full-run-complete advances to ready_for_thumbnail.
- GET /api/videos/{id}/dialogue-map (💬 badges), DELETE /api/videos/{id}/
  clips/{asset_id} (hover-X: clears column + trashes Drive copy).
- VideoClipsTab rebuilt: status strip + ⋯ Advanced (model picker with real
  prices, coming-soon disabled, re-run prompts, motion instructions toggle);
  scene groups with "Animate this scene · $X"; tap card = animate (~$0.10,
  no confirm), tap done card = play inline; hover Redo/X; failed = red Try
  again; 💬 speaker badges via dialogue-map substring match; motion prompts
  AUTO-RUN silently on arrival (promptlessCount guard); confirms only >$0.50.
- next-action.ts: clips trust ladder (Animate scene 1 → Animate the rest →
  thumbnail) + clipCost()/CLIP_COST_PER_MODEL as the single price source;
  GuidedNextStep passes clipsDone/clipsTotal. Old Generate Prompts/Generate
  All Clips/Advance Stage/visible dropdown/always-on prompt editor all gone.

VERIFIED LIVE ON PROD (Playwright + API, Ryan's tenant):
- Tap → $0.10 Grok clip → Drive {video}/clips/S01-01.mp4 → assets row →
  plays via media proxy (frames eyeballed: on-model Pixar Tom, real motion).
- Tab renders: "1 of 86 pictures animated · ≈ $8.50 · Grok Imagine", 8 scene
  buttons, 34 💬 badges, real card pictures, zero old surfaces, banner shows
  "Animate the rest". Console clean on warm backend (cold-start 502s are
  transient, see lessons).
- THREE live bugs found+fixed en route: assets column is duration_seconds;
  clip gate + banner keyed on lagging status strings (bird video =
  ready_for_images with 86/86 finals); GET /api/videos/{id} SELECTed
  story_locked_at but never passed it to VideoDetail → banner re-offered
  Lock forever (one-line constructor fix).

STEP (c) DIALOGUE SPEAKING CLIPS SHIPPED (same day, Ryan: "S1.2 got no
dialogue — fix"): backend/clip_dialogue.py — norm/match_lines pairs a card's
sentence_text with the scene's tagged dialogue lines (same containment logic
as the frontend 💬 badge), speaking_prompt() directs Grok lip movement,
mux_voice() replaces Grok's invented audio with the segment's ElevenLabs
line(s) via ffmpeg (concat for multi-line cards), strip_audio() silences
narration clips (renderer narrates over them). run_clip_generation now:
speaking cards get the speaking prompt + a clip long enough for the line +
the voice muxed in; unvoiced scenes auto-chain run_dialogue_voice first
(contract Q5); mux failures keep the raw clip with a logged warning.
3 functional tests incl. a REAL ffmpeg mux round-trip.
ALSO fixed: NULL duration_seconds rows crashed the whole video-scripts run
('.get(key, default)' ≠ NULL-safe — see lessons); clips tab switched to the
always-on useTaskWatcher (purple progress pill shows ANY running task, taps
during a run explain what's running instead of a bare 409).

LIP-SYNC, FINAL FORM (Ryan: "way off the other direction — research how
people actually do this", then "the BOY's lips moved with Lisa's line"):
dialogue clips are AUDIO-DRIVEN PORTRAIT CUT-INS. 💬 cards →
image_client.generate_talking_video (Kie `infinitalk/from-audio`: the
SPEAKER'S APPROVED PORTRAIT (video_characters.reference_url) + segment
ElevenLabs mp3 via media-proxy URLs + who-speaks prompt → talking clip,
length = audio length, $0.015/s ≈ $0.03-0.05/line, 7-10 min/clip, poll
budget 15 min). Why portrait not panel: on multi-character panels the
model animates the MOST PROMINENT face (Tom mouthed Lisa's line — Ryan
caught it watching; my still-frame check had called it wrong). Portrait =
one subject = can't miss + deterministic + the approved lip-test recipe.
Verified live on S2.1: Lisa alone, articulating, $0.03. Fallback: full
panel when speaker has no portrait (logged warning). Vision onset
detection + mux + speaker-crop all RETIRED (git history); strip_audio
stays for narration clips. Multi-line cards: first line only.

⚠ DISCOVERED: CLAUDE-VIA-KIE VISION IS DEAD (gateway drift) — images
become /mnt-style file refs the model can't see (272 input tokens, no
image; haiku refuses, sonnet preambles then ends; URL and base64 both).
Likely silently degrading: model_video thumbnail style-DNA (modeled
videos!), storyboard vision QA loop, approve-cast description rewrite.
NEEDS ITS OWN INVESTIGATION + canary. _call_claude now joins all text
blocks (content[0] truncated multi-block replies).

DIALOGUE AUDIO IS NOW PER-VIDEO (migration 049, videos.dialogue_audio,
toggle in clips ⋯ menu): 'grok_native' (bird video's setting — Grok speaks
the EXACT scripted words, native_speaking_prompt feeds only the sentences
covered by the card; no synthesis chain, full Grok audio kept) vs
'voice_over' (ElevenLabs overlay + ambience bed). match_lines is now
sentence-level (lines spanning cards — the S1.3 wrong-words bug).

RYAN'S 4 ANSWERS (2026-06-12 late — the next build's spec):
1. ONE SCENES WORKSPACE: merge storyboard + final pictures + clips into a
   per-scene view (boards, pictures, clips side by side, redo at any level).
   The separate storyboard/clips tabs collapse into it. THIS IS THE NEXT
   BIG BUILD — invoke web-design-guidelines/react skills, plan from
   tasks/decisions.md UX contract.
2. AUTO RE-ANIMATE: redoing a picture auto-regenerates its clip (~$0.10,
   cost note shown).
3. CUTAWAYS (shipped same night): no-people hard rule prepended for cards
   whose image_prompt+sentence mention no cast name and match no dialogue
   line (deterministic — no vision needed). S1.4 class.
4. BAD CROPS: extraction must VALIDATE panels (internal-gutter split check,
   label-bar [KFn|XX|Ns] leak check — white-on-black text defeats the
   brightness trim) → red 'bad crop' badge + one-tap 'Re-crop this picture'.
   Ryan hit both on S2.4/S2.5 (split across two pictures) + a label leak.
Also open: S1.4 regenerated the invented boy AGAIN even with constraints-
first prompt (before the cutaway rule shipped) — verify the cutaway rule
catches it on next redo.

SKIP V1 SHIPPED: banner shows 'I don't need this — skip it →' on optional
steps (research/review/voice/clips rungs/sound/thumbnail), inline
consequence confirm, advance?to=<status> forward-jump (validated). S1.2/
S1.3 regenerated grok_native and approved-ish by Ryan (S1.3 'love it').
NEXT: full keep/skip matrix view — every pipeline element obviously
optional per video ("sometimes they just want research/ideas/script — make
it very obvious, a skip button on certain elements"). Then: (b) animatic
segment timeline; (e) render (respecting dialogue_audio — grok_native clips
carry their own dialogue audio); (f) tag-dialogue on non-modeled path.

## Handoff (2026-06-12 pt 6 — dialogue intelligence SHIPPED, lip test PASSED)

Ryan greenlit the dialogue plan with decisions (recorded in decisions.md):
ElevenLabs character voices + Grok lips; narrator pauses; convert bird video
in place; everything must serve UNATTENDED channel automation (north-star,
also in agent memory).

DONE this session:
1. LIP TEST PASSED: Grok clip from Lisa's portrait — she visibly speaks
   (mouth movement, acting, leans to the bird Grok added from the prompt);
   muxed with a Kie/ElevenLabs line → `lisa-dialogue-test.mp4` in the bird
   video's Drive folder for Ryan to watch. Cost ~$0.06.
2. DIALOGUE INTELLIGENCE LIVE (dialogue_intelligence.py + migration 048):
   detect_dialogue_mode (whole script → character_dialogue|narration_only),
   segment_scene (ordered narrator/speaker timeline, attributions dropped,
   words verbatim, 60% retention sanity check), cast_character_voices
   (stable Kie ElevenLabs voice ID per character; curated 13-voice subset;
   full 67-voice enum + preview URLs in the session notes below).
   POST /api/videos/{id}/script/tag-dialogue + auto-hook after modeled
   script stage (best-effort). Bird video: character_dialogue, 8 scenes,
   65 dialogue lines, cast: Tom=Mark, Lisa=Brittney, Mom=Tiffany, Dad=Brian,
   Dr. May=Bella, Baby Bird=Emma. (Audit: Tom's 'Mark' is an adult voice —
   audition via https://static.aiquickdraw.com/elevenlabs/voice/<id>.mp3,
   Finn vBKc2FfBKJfcZNyEt1n6 is the boy option.)
3. Kie ElevenLabs API facts: voice param takes the ID (names rejected),
   input {text<=5000, voice, stability .45, style .2, speed 1.05 reads
   younger}; do NOT send language_code on multilingual-v2.

NEXT (in order, per the approved plan):
a. Per-segment voice synthesis: walk dialogue_segments, TTS each segment
   (narrator voice for narration, character voice_name for dialogue) via Kie,
   upload {video}/voice/S{n}-seg{i}.mp3, write audio_url+duration into the
   jsonb. Executor stage + banner progress.
b. Animatic plays the new timeline (radio-play rehearsal, $0).
c. Grok clip client in the pipeline (grok-imagine/image-to-video, duration
   STRING, mux ElevenLabs line over dialogue clips, label-bar cleanup first).
d. Per-scene "Animate this scene" + scene-gate + bulk with cost confirm.
e. Render: Remotion timeline with narration pauses + dialogue clip audio.
f. Auto-hook the NON-modeled script path too (only modeled path hooked now).

## Handoff (2026-06-12 pt 5 — extraction geometry fix, upscale policy wall, dialogue-clips plan)

Ryan: scene 2 animatic showed 3-panels-in-one and didn't rotate; scenes 7/8 had
no player; 82/85 mystery. All fixed + verified (Playwright: 8/8 players, S2
plays 6 single panels, audio rolling):
1. EXTRACTION GEOMETRY: extraction.py guessed grid layout from dark-band pixel
   detection; scene 2's 2x3 grid was misread → full-row composite crops, 3
   empty slots. Fix: `grid_layout_for(panel_count)` (mirrors bot._grid_layout),
   executor chunks scene slots 9-per-beat and passes exact rows/cols; detection
   is fallback only. Scene 2 re-extracted → 6 clean panels.
2. PER-SCENE RESUME on extraction: scenes with all slots filled are skipped.
3. UPSCALE = POLICY WALL, not a bug: nano-banana-2 refuses to regenerate
   images of CHILDREN (Google Prohibited Use policy) — all 82 upscales filtered,
   0 credits, ~40 min wasted. Auto-upscale now DISABLED (EXTRACT_AUTO_UPSCALE
   env to re-enable). Needs an ESRGAN-class non-generative upscaler on Kie for
   stills; clips path makes stills less critical.
4. AnimaticPlayer: never unmounts on audio error; retries once with fresh
   token (5-min TTL — players outlive it). Root cause of the missing 7/8
   players was the pre-fix HTML audio killing the component at mount.
5. Known warts for the clips phase: some panels keep their [KFn|MS|10s] label
   bar (white-on-black text defeats the brightness>100 trim scan — fix before
   clips, Grok will reproduce labels from reference); scene 2 gained a 6th
   slot with no sentence_text (executor inserts rows for extra real panels).
6. DB env gotcha: load backend/.env BEFORE root .env in scripts — root has a
   dead DATABASE_URL and the legacy Drive parent.

DIALOGUE-CLIPS PLAN written and reported to Ryan (NOT built — awaiting his
sign-off on: Grok-native vs ElevenLabs character voices for dialogue;
narration pauses vs ducks during dialogue; convert bird script in place).

## Handoff (2026-06-12 pt 4 — animatic player, silent extraction, dead audio fix, Grok Imagine validated)

Ryan: voice player dead on the storyboard page; extraction should be invisible
("do it in the background"); build the animatic player; switch clips to Grok
Imagine (cheaper) — research what Kie expects. All done except the Grok pipeline
wiring (researched + smoke-tested, integration is THE next build):
1. DEAD AUDIO, two root causes: (a) SecureAudioPlayer guessed
   `https://<host>:8001` for the API (unreachable port in prod); (b) the backend
   audio proxy streamed Drive PUBLIC links → HTML interstitial served as
   "200 audio/mpeg" — players sat at 0:00/0:00. Fixed: API_URL from env +
   authorized Drive API download (same as routes/media.py). Verified: real
   ID3/MPEG bytes, Playwright played scene 1 to 6.7s/28.7s.
2. ANIMATIC PLAYER (AnimaticPlayer.tsx): per-scene $0 preview — final pictures
   under the scene's narration, per-panel duration = sentence word-count share,
   caption overlay, progress bar, panel counter. Mounted on scene cards when
   finals exist; falls back to plain voice player until then. Live: 8 players.
3. SILENT EXTRACTION: Lock Story now auto-starts storyboard-extract (banner
   shows progress; visible step remains only as failure recovery, relabeled
   "Finish making your pictures"). next-action gained finalsMissing guard:
   clips step can never show for a video with 0 finals (the skip-trap Ryan
   screenshotted). Bird video: locked + extracted in background → 82/85 panels
   (3 slots skipped as blank boards — per-segment regen exists in scene
   details if they matter). Upscale ran but no _hd URLs recorded — check
   whether upscale writes in place now (cache fix makes that fine) or skipped.
4. GROK IMAGINE (clips at ~1/6 the cost) — researched on Kie docs + LIVE
   smoke test: model `grok-imagine/image-to-video`, same jobs API
   (createTask/recordInfo), input {image_urls:[proxy URL], prompt, mode:
   "normal", duration:"6"–"30" STRING, resolution:"480p"|"720p"}. Test clip
   from real S1 panel: $0.048, 31s generation, on-model Pixar look, real story
   beat (Tom kneels to the bird). 720p ≈ $0.09–0.12/clip vs Veo Fast $0.30
   (video drops $6–12 → ~$2–4). NO start/end-frame support (Veo keeps that);
   audio always baked in (strip/duck under narration); result URLs expire 24h
   (download immediately); resultJson is a JSON STRING with resultUrls.
   Veo 3.1 Lite ($0.15 flat) is the middle option.

NEXT BUILD (agreed direction): per-scene "Animate this scene" button (clips
appear beside the boards, scene 1 = motion taste-test gate before bulk run),
clip model selector defaulting to grok-imagine/image-to-video, motion presets
by shot type (LS=push-in, ECU=parallax, etc.), then bulk "animate everything".

## Handoff (2026-06-12 pt 3 — ONE-button consolidation of the pipeline page)

Ryan (with screenshot): the storyboard stage had FOUR competing "what now" surfaces
(header Run Next Step/Skip Stage, the guided banner, an 8-button action bar, a
4-step tracker with its own giant CTA) — "consolidate to one button, Apple-esque,
grandma-proof, regeneration lives on the scene cards." Shipped + verified on prod
(Playwright: every old surface gone, exactly one Next-up banner, 0 console errors):
1. GuidedNextStep banner = THE button. New `useTaskWatcher` (use-task-poller.ts)
   watches the video's task slot CONTINUOUSLY → progress + Stop appear in the
   banner no matter which control started the work. Lock Story is now executed BY
   the banner (gold button, kind "lock", zero-board guard in next-action.ts).
   Watcher fires onComplete/onFailed only on live-observed transitions
   (wasRunningRef) + epoch guard so in-flight polls can't misfire after markStarted.
2. Header: Run-next/Skip/Reset/Export → one ⋯ menu. Stepper passive.
3. Storyboard tab: stats row, action bar, tracker, toggle, inline progress banner
   all deleted. One status strip ("8 scenes · 12 of 12 boards" + Unlock when
   locked + ⋯ Advanced: model, upscale, delete finals, re-extract missing,
   start over, skip stage). Scene cards: "Plan this scene" / "Draw the pictures" /
   "Redo pictures" (slot-clears then regen, plan kept) / "Start scene over" which
   AUTO-CHAINS plan→pictures via chainRef consumed in watcher onComplete — the old
   clear-wipes-prompts dead end is gone. Stop dispatches `se:stop-requested` so
   pending chain stages stand down (cancelled reads as completed to pollers).
4. Adversarial review workflow ran (21 agents; verify phase partially hit session
   limits — self-verified the flagged races): fixed stale failure card, zero-board
   lock, menu outside-click close, watcher poll race, chain-409 retry, duplicate
   failure toasts, jargon (Final pictures / picture plans), dead computed values.
Playwright note: headless verification of prod needs /api/auth/me stubbed via
route interception (instant fulfill) — the mount-time /me fetch gets ERR_ABORTED
under headless; everything after auth proxies fine (see /tmp/verify_final.py pattern).
Known minor (documented, not fixed): banner may flicker idle for ≤3s between chain
stages (two watcher instances); switching tabs mid-chain drops the queued stage
(banner self-heals: next action becomes "Finish your storyboard").

Bird video remains: review boards → Lock the story (now the one gold button) →
Create the final pictures.

## Handoff (2026-06-12 pt 2 — per-board X delete, drop-to-replace, stale cache fix)

Ryan: "Drive images aren't what's on screen; no clean way to delete ONE storyboard
image without losing prompts; want to drag Drive images onto a board." All three done:
1. STALE SCREEN: boards regenerate IN PLACE on Drive (same file id) but the media
   proxy said max-age=86400 immutable → browser showed yesterday's pixels for a day.
   Proxy now: ETag = Drive md5Checksum, Cache-Control public no-cache, If-None-Match
   → 304 without download. Verified live (200 + md5 etag, 304 on revalidate).
   → Ryan: a hard refresh once and from then on boards are always current.
2. PER-BOARD X: DELETE /api/videos/{id}/storyboards/{scene}/{beat} clears ONE slot,
   keeps prompts + other boards, trashes the Drive copy (folder matches screen),
   guards scene status (only downgrades grids_generated→prompts_ready for in-range
   beats). Hover X on every filled board card. Bot's per-beat resume skip means
   "create storyboard" after an X only regenerates the missing slot (~$0.07).
3. DROP-TO-REPLACE: drag-drop existed but was invisible (replace-in-place + cached
   URL = nothing seemed to happen). Now: "Drop to replace this picture" overlay,
   uploads land in {video}/storyboard/S{n}-B{m}.png (replaces bot grid in place,
   was orphan grids/ folder), cache-busted <img> after upload, success/error toasts.
   Per-scene Clear confirm now warns it's a FULL redo and points at the X.
Also: trashed empty duplicate Drive video folder (created by a root-.env diagnostic
script — see lessons). Full cycle (upload→proxy-serve→X-delete→Drive-trash) verified
on prod against the bird video's unused slot 5. Tests 5/5 + 7/7, tsc clean.

Bird video remains: review boards → Lock Story → Create final pictures.

## Handoff (2026-06-12 — style drift root causes + vision QA loop)

Ryan: "scene styles still don't match, stale extracted images showing, last scene has
three of the same images." All three fixed + verified by eye:
1. STALE EXTRACTED: 74 pre-storyboard asset images (image_url set, never extracted)
   showed in the Extracted Panels section. Cleared (image_url/drive_image_url NULL,
   status pending). Drive files remain in the library.
2. DUPLICATE PANELS: the director template's HERO BEAT EXPANSION explicitly asked for
   sub-shots showing "the SAME subject — don't change what's shown" (3 crayon panels,
   4 chair holds). Rules now demand visually distinct panels / fewer keyframes + blanks.
3. STYLE DRIFT (2D/photoreal mixed with 3D): two layers —
   a. Template preamble HARDCODED "Cinematic 2D animated illustration..." (the April
      never-hardcode-style lesson again). Now interpolates profile.visual_style_directive
      (= the video's Image Style Override).
   b. Even with correct prompts everywhere, nano-banana-pro stochastically rendered
      photoreal ~1 in 4-12 grids. Instructions can't fix randomness → added a vision
      QA loop: every reference-conditioned grid is compared to the cast sheet
      (Haiku via Kie) and regenerated once on mismatch. Caught a live drift on its
      first run.
KIE CLAUDE VISION GATEWAY QUIRKS (calibrated live, see bot._grid_style_matches_reference):
   URL image sources unreliable, assistant prefill IGNORED, small max_tokens IGNORED
   on vision calls → use base64 images + parse a 'FINAL: YES/NO' closing line.
Bird video: 12/12 boards now style-consistent (audited via the calibrated checker +
eyeballed S1/S5/S8). Ready for review → Lock Story.

## Handoff (2026-06-11 pt 4 — character consistency: labeled cast sheet)

Ryan: "character styles are all over the place in the boards." Root causes + fixes:
1. SIX separate portrait refs in image_input dilute each other — model can't map
   names to faces. FIX: approve_cast composes ONE labeled cast sheet (PIL, portrait
   + name per tile) -> videos.character_reference_url; executor passes it as the
   single reference; generate_contact_sheet prompt says "match these EXACT labeled
   characters."
2. Story Bible character text diverged from approved portraits (text fought image).
   FIX: approval syncs bible descriptions to the cast.
3. Stored descriptions described what portraits were generated FROM, not what they
   show (gen takes liberties: "light blue tee" -> red). FIX: vision pass at approval
   rewrites each description from the actual portrait pixels.
Result (visually verified): all 13 boards across 8 scenes now share one cast —
same Tom/Lisa/Mom/Dad/Dr. May in every panel. Boards ready for Ryan to review+lock.
Note: per-scene storyboard CLEAR also wipes that scene's prompts — regen prompts
before grids (bit Ryan on scene 4, me on scene 1; worth auto-chaining later).
Also this session: media proxy (/api/media/drive/{id}) replaced Supabase serving
copies — Supabase bucket purged (92 objects), Drive is sole media store.

## Handoff (2026-06-11 pt 3 — grandma-proof guided flow + storage reliability)

Ryan's storyboard run silently failed + "UI is confusing, needs next-next-next."

Root causes found & fixed:
1. Kie rejected character refs ('image_input file type not supported') — the stored
   drive.google.com URLs had degraded into HTML interstitials (even lh3 CDN form).
   FIX: dual persistence — Drive stays the organized library, Supabase Storage is the
   serving copy and the URL we store (storage.py drive branch). Public 'assets' bucket
   created. Bird video backfilled (6 portraits + grids + 74 images) via authorized
   Drive download.
2. generate_with_reference poll budget was 120s; multi-ref grids take 2-4 min →
   silent 'returned None'. Budget now 450s. Misleading "$0.07 so far" log on failure
   still exists (bot.py increments cost before checking result) — minor, open.
3. Bird video storyboard now COMPLETE: 12 grids across 8 scenes (scene 4 was deleted
   by Ryan mid-debug; regenerated per-scene). Story still UNLOCKED — Ryan reviews
   boards → Lock → Create final pictures.

Guided UX (from 7-agent audit + synthesis, full report in workflow output):
- lib/next-action.ts: getNextAction() decision table → ONE plain-English next action
  per state (label, cost, tab, step N of 10).
- GuidedNextStep banner on the video page: big single CTA, live progress + Stop,
  PERSISTENT failure card with Try Again (replaces 6s toasts).
- Tabs renumbered 1·Research … 10·Results; storyboard tab buttons in plain English.

UX backlog (synthesis items not yet built): Advanced overflow menus per tab (hide
Reset/Skip/Upscale), disabled-button reason captions, per-segment failed badges with
"Fix missing pictures (N)", tab lock icons for not-ready tabs, cost-confirm pattern
for every >$0.50 action, stepper/pill unification via STATUS_LABELS. Full decision
table + per-tab hierarchy in the uiux-map workflow output.

## Handoff (2026-06-11 pt 2 — Drive consolidated under RAD Creations/Projects/Storyengine)

Everything now lives in ONE tree (Ryan's requested layout):
  Storyengine/<video title>/{characters/, storyboard/, images/} + scripts/voice/briefs in root.
- StoryEngine backend GOOGLE_DRIVE_FOLDER_ID redirected to the Storyengine folder
  (old value in storyengine/.env.bak-20260611). google_client folder lookups are now
  parent-scoped (global name search would have resurrected old folders / collided on
  generic subfolder names). Path routing: scene images + extracted panels -> images/,
  grids -> storyboard/, portraits -> characters/.
- Migrations executed (file ids unchanged, all stored URLs intact): both video folders
  moved + internally sorted; legacy 'StoryEngine Assets' uuid tree emptied + trashed;
  the legacy Power Doctrine pipeline's 'Economy Fastforward' folder moved WHOLESALE
  under Storyengine — its folder id is unchanged so the root .env and all existing
  links keep working without modification.
- Frontend renders Drive images via lh3.googleusercontent.com CDN (toDisplayImageUrl)
  since uc?export=download links don't load in <img> tags.

## Handoff (2026-06-11 — Creator Control Run shipped: Stop, Characters, Story Lock)

All three phases of docs/superpowers/specs/2026-06-10-creator-control-run.md are LIVE:
- Stop button on Visuals/Clips/Storyboard/Voice tabs; cooperative cancel keeps paid
  work, stage re-run resumes. Live-verified twice (grids stopped mid-run; a found
  cancel-eaten race + stale-clear race fixed and re-verified with a 3s cancel).
- Characters tab between Script and Storyboard: design cast → 6/6 portraits generated
  live for the bird video (Tom, Lisa, Mom, Dad, Dr. May, Baby Bird), approve gate
  blocks grids/images until approved (verified live), cast saved to project.
- Mandatory storyboard: storyboard_on_off defaults On, toggle replaced with REQUIRED
  badge, Lock Story (needs ≥1 reviewed grid) gates full image runs + extraction
  (both refusals verified live), unlock-story to iterate.
- Adversarial review pre-deploy: 11 claims refuted, 2 confirmed + fixed (cancel
  endpoint was blocked by the concurrent-job limiter; schema.sql missing
  video_characters RLS).

### Bird video state (f32ed182) — heads up
During live testing a cancel race let an image run complete: the video now sits at
ready_for_sound_design with 74 generated images (~$1.85, styled by the modeled
Pixar DNA — review them, they're likely usable). Cast is approved + saved to the
project; scene 1 has a storyboard grid; story is UNLOCKED. For a clean full-flow
test of the new gates, model a fresh video: script → Characters tab → approve →
grids → redo boards → Lock Story → Extract.

### Open items
1. Storyboard grid generation is not yet blocked AFTER lock (only images/extract are
   gated) — locking then regenerating boards is possible; unlock-to-iterate is the
   official path. Consider gating grids post-lock or auto-unlocking on grid regen.
2. Stale 'running' background_tasks rows accumulate when a task's terminal write
   misses (cleaned by recover_stale_tasks on restart) — they inflate the concurrent-
   job count between restarts.
3. voice_duration_seconds still not recorded in Kie voice mode (word-count fallback).
4. Characters tab does not auto-resume polling if the page reloads mid-design
   (background task continues; refresh shows the finished cast).

## Handoff (2026-06-10 pt 4 — voice via Kie + full click-path to ready_for_images)

Ryan: "voice uses kie as well." Shipped + verified live on the bird video (f32ed182):
- ElevenLabsClient Kie gateway mode: createTask/recordInfo jobs against
  elevenlabs/text-to-speech-multilingual-v2 (SoundClient pattern). Kie only accepts
  its OWN voice roster — off-roster ids rejected with "not within the range of
  allowed options"; falls back to "Mark" (1SM7GgM6IMuvQlz2BwM3) with a logged warning.
  Kie.ai is now the ONLY required pipeline key (anthropic + elevenlabs both optional).
- Voice click: 8/8 scenes voiced via Kie, audio in Drive. NOTE: voice_duration_seconds
  not recorded in Kie mode (engine falls back to word-count timing) — worth fixing.
- Prompts click first produced ZERO prompts: the modeled concept asset rows carry
  image_prompt values, so the engine's resume logic saw all scenes "completed."
  Fixed: full prompt runs on modeled videos clear generation_method='modeled' rows
  first (pack stays archived in original_dna). Re-run: 74 prompts across 8 scenes,
  ALL carrying the animation style (image_style_override active in the engine log).
- Current state: f32ed182 at ready_for_images with 74 styled prompts. Next click
  (Images) costs ~$1.85 kie credit + clips after — left for Ryan per cost rules.
- Watch items: prompts came out "2D animated illustration" (profile prefix blends
  with the 3D-Pixar override — consider selecting visual profile from the modeled
  DNA); story_bible column empty though the engine generated one in-run.
## Handoff (2026-06-10 pt 3 — replicate mode shipped + modeled script path)

Ryan's correction: Model A Video must REPLICATE the dropped-in video (same genre/
style/audience, sibling topic), NOT adapt it to his channel. Shipped + verified on
his video f32ed182 (ESL turtle reference fVdj037FNYI):
- Pack prompt rewritten to replicate-mode, channel profile removed, reference
  thumbnail attached as vision input. Result: "🐦😱 What Should We Do To Help The
  Injured Baby Bird? | Easy English Listening for Beginners (A2 Level)" + image DNA
  "3D Pixar/Disney CG animation style..." (observed from the thumbnail).
- New `script_dna` → `videos.script_system_prompt`; `pipeline_executor.run_script`
  branches for source='modeled' → `_run_modeled_script` (direct generation in the
  reference's style, 8 scene rows, documentary validation skipped). Verified: script
  opens "Look! A baby bird is on the ground. It cannot fly. What should we do?" —
  8 scenes, ready_for_voice.
- Click path verified end-to-end through script. Voice is next and needs Ryan's
  ElevenLabs key; then images/clips run on kie credit via existing buttons (the
  image prompts stage should honor image_style_override — NOT yet verified live,
  next test after voice).

## Handoff (2026-06-10 pt 2 — Kie-routed Claude + modeled click-through path)

Ryan's goal: paste link → modeled title/script/image DNA/video DNA → click through to a
similar finished video. Shipped and verified live on his video f32ed182 (tenant ee93e6d1):

- **All Claude calls via Kie.ai** (his directive). model_video routes kie-first; the
  PIPELINE bots too: `AnthropicClient` gateway mode via `ANTHROPIC_BASE_URL`
  (set by pipeline_executor when tenant has kie key but no anthropic key).
  Gateway traps found live: Bearer auth (SDK `auth_token`), Kie WAF blocks the SDK
  User-Agent (override it), dated model ids 422 (normalize to undated aliases),
  server-side web_search tools not executed (stripped in gateway mode), and **Kie 500s
  any non-streaming response taking >~110s — gateway mode must STREAM** (12/12 research
  calls failed non-streaming; identical call streams fine).
- **Modeled DNA steers downstream stages** via existing channels: writer_guidance
  (script), image_style_override (image prompts), thumbnail_style_override (thumbnail),
  video_motion_system_prompt (clip prompts). Pack prompt outputs explicit
  image_dna/motion_dna/thumbnail_dna. Full pack archived in original_dna (research
  stage overwrites research_payload by design). video_length_minutes now set from
  reference duration (script gen refuses to run without it).
- **Bug fixes en route:** psycopg2 UUID adapter registered in supabase_adapter
  (research save crashed: "can't adapt type 'UUID'"); rate limiter 429-storm fixed
  (read tenants.plan instead of accounts+trial → trial users got free-tier 15/min;
  also free floor now 60/min, both plan-name generations mapped).
- **Verified click-path on prod DB:** Model → idea+DNA ✓ → Research click (41KB
  payload, Kie-streamed, ~4min) ✓ → Script click (11.7KB script, editorial validation
  PASSED, ready_for_voice) ✓. Voice is the next click and needs Ryan's ElevenLabs key
  (BYOK) — that's where it correctly stops today.

### Open items
1. Ryan must add his ElevenLabs key (Settings → Keys) for voice; then images/clips run
   on his kie credit via existing buttons.
2. Script stage produced ONE scripts row holding the whole script (scene=1). Pre-existing
   script-stage behavior, not modeling-specific — verify voice/image stages handle it,
   or whether 6-scene splitting should happen here.
3. yt-dlp cookies support merged (PR #456): export YouTube cookies to
   ~/.config/storyengine/youtube_cookies.txt to unlock transcripts.
4. Other storyengine routes (learn-voice, suggest-titles, distiller) still anthropic-direct
   — task chip open ("Route all backend Claude calls through Kie.ai", partially done:
   pipeline bots + model_video covered).

## Handoff (2026-06-10 — Model A Video shipped)

### What shipped
"Model A Video" Dashboard feature: button → modal (one field: YouTube URL) →
`POST /api/model-video` creates a tenant-scoped video row at `idea_logged` and runs a
background task (extract via yt-dlp with oEmbed fallback → style-DNA distill via Haiku →
new modeled idea + prompt pack via Sonnet → persist). Pack lands in: videos fields
(title/headline, thesis, writer_guidance, title_candidates, thumbnail_prompt,
original_dna, research_payload incl. 8 scene_concepts + blockers), 8 `assets` rows
(image_prompt + video_prompt, generation_method='modeled'), `competitor_videos`
attribution upsert (our_video_id, modeled_at), best-effort Drive markdown brief.
Progress polled via existing `/api/pipeline/task/{video_id}` + `useTaskPoller`.
Retry endpoint: `POST /api/model-video/{video_id}/retry`. No migration needed.

### Verified
- Backend functional tests 6/6 (`tests/functional/test_model_video.py`), humanization suite still green
- `tsc --noEmit` clean, `npm run build` passes
- Live E2E on VPS against real DB (disposable test tenant, cleaned up): full happy path
  with mock Claude endpoint (ANTHROPIC_API_URL override), real oEmbed fallback (yt-dlp is
  bot-blocked on this VPS IP — see lessons), plan-limit 402 enforced, 401 unauthenticated,
  invalid-URL 400, missing-key actionable error
- Playwright UI E2E: button → modal → validation → failed state w/ Retry → modeled video
  visible in Pipeline list + detail page

### Known gaps / follow-ups
1. ~~No live-Claude run~~ RESOLVED same-day: Ryan clarified Claude calls go through
   Kie.ai. model_video now resolves creds kie-first (`https://api.kie.ai/claude/v1/messages`,
   Bearer auth, `stream:false` required, models claude-sonnet-4-5 / claude-haiku-4-5,
   beware 200-with-error-body) with direct-Anthropic fallback. NOTE: the rest of the
   backend (distiller, learn-voice, suggest-titles, pipeline executor) still hits
   api.anthropic.com directly with anthropic_api_key — aligning those to Kie is open work.
2. yt-dlp is bot-blocked on the VPS IP ("Sign in to confirm you're not a bot") — oEmbed
   fallback covers title/channel/thumbnail, but transcripts won't extract until cookies
   or a different egress is configured. Affects competitor scraping too, worth its own fix.
3. Videos whose modeling failed keep the "Modeling a reference video…" placeholder title
   in Pipeline; retry from the modal fixes them, but a retry affordance on the video card
   would be nicer.

## Handoff (2026-04-19 — Osiris full-autonomy overnight ship mode started)

### Context
Ryan granted full-autonomy ship-while-sleep mandate (see `~/.claude/projects/-Users-osiris-claude-agent/memory/project_storyengine_full_autonomy.md`). Single-agent (Osiris) continuous builder, Karpathy build-test-learn loop, functional tests only (no smoke-test ship gate). Daily ship log at `storyengine/daily-ship-log-YYYY-MM-DD.md`.

### Completed this cycle
- **Trial-downgrade cron (fix-roadmap 3.2)** — migration 041, `send_trial_expired` email, `check_trial_expired` task, `_auto_check_trial_expired` wired in lifespan @ 6h interval. Functional test in `backend/tests/functional/test_trial_expired.sql` green against prod Supabase.
- **Humanize error strings (frontend)** — 11 raw-error leak sites routed through `humanizeError()`. Pages: login, forgot-password, reset-password, settings/drive-callback, settings/youtube-callback, system-prompts, profile, competitors. Components: CreateVideoStep, FirstVideoFlow, storyboard-viewer. `npx tsc --noEmit` clean. Users no longer see "API error 500" or "Failed to fetch".
- **Flow B slice 1 — existing-channel detection** — new `GET /api/youtube/my-videos` endpoint fetches user's top uploads via OAuth + uploads-playlist pattern. Frontend `YouTubeConnectStep` auto-fetches + renders "We found N top-performing videos on your channel" card after OAuth succeeds. Backend functional tests (4/4 ✅) including live contract check against googleapis.com.
- **Flow B slice 2 — voice auto-learn** — new `POST /api/youtube/learn-voice` endpoint: top-5 videos → Claude Sonnet 4 voice summarization → persists `channel_profiles.style_description`. **Reordered onboarding steps** to `channel → keys → youtube → style → video` so voice-learn can pre-fill the Style step. `StyleSetupStep` shows "We drafted this from your top YouTube videos" banner when pre-filled. Backend functional test `test_learn_voice.py` (3/3 ✅) including LIVE 401 contract test against api.anthropic.com. `npx tsc --noEmit` clean.
- **Grandma-mode override audit + script bot wired (Cycle 6)** — Cycle 1's "wiring in 7 places" claim was wrong. `test_prompt_override_wiring.py` (3 tests ✅) audits via runtime + static grep. Found 1/6 bots reading their override (video_motion only). Wired the `script` bot end-to-end: `script_generator.py` (`system_prompt_override` param → `anthropic_client.generate(system_prompt=...)`) + `brief_translator/__init__.py` (both `BriefTranslator.__init__` and `translate_brief` convenience func) + `script/run.py` (passes `getattr(pipeline, "script_system_prompt", None)`). 2/6 wired after Cycle 6.
- **All 6 bots wired (Cycle 7)** — completed the grandma-mode rollout. Thumbnail bot (3 Claude call sites via `ThumbnailTitleEngine` → `TitleGenerator` + `ThumbnailPromptBuilder`, wired in `thumbnail/run.py`). Sound bots (`SoundPromptBot` now takes both `sound_curation_` and `sound_generation_` overrides, wired in `sound/run_design.py`). Research bot (`ResearchAgent` + `run_research` take override, wired at SaaS executor boundary `pipeline_executor.py:run_research`). Audit test broadened regex to match `self._pipeline.<attr>`; CONSUMER_SPEC updated. **6/6 WIRED** with a full-loop regression guard asserting all 6 stay wired.
- **Backend error humanization (Cycle 8)** — new `storyengine/backend/error_utils.py` with `humanize_error(err, context=...)` mirror of frontend `src/lib/errors.ts`. Fixed 11 HTTPException leak sites across 6 customer-facing routes (visual_styles.py × 5, intelligence.py × 1, pipeline.py × 1, system_prompts.py × 1, youtube_channel.py × 1, videos.py × 1). Raw `str(e)` / upstream-API bodies no longer reach users; all get logged at WARNING with `[humanize_error]` prefix for dev grep. Functional test `test_error_humanization.py` (8/8 ✅) including static audit regex-scan that asserts 0 raw-error leaks across all 6 customer-facing route files — acts as a regression guard for any new route added later.
- **Background-task error humanization (Cycle 9)** — closed the leak surface flagged as Cycle 8's honest gap. `_set_task_status` in `routes/pipeline.py` now humanizes at the write boundary, covering all ~15 `str(e)` call sites in one change. `routes/agents.py` agent-pipeline run uses `humanize_error(e, context="The agent pipeline hit an error")` at both the in-memory `_set_task` and the `bot_activity` INSERT. Runtime test `test_set_task_status_humanizes_failure_errors` (via FastAPI-free module stubs) proves a raw `HTTPSConnectionPool(host='api.kie.ai'...)` input never leaks into `_running_tasks['error']`. Full suite: 9/9 green. Prompt-override wiring test still 6/6 WIRED.
- **Activity-feed humanization (Cycle 10)** — uncovered a third independent leak surface: `pipeline_executor._log_activity` writes `message` to `bot_activity` which `/api/activity` returns verbatim to the UI. ~20 call sites in `pipeline_executor.py` pass `error_msg = str(e)`. Fixed with a single-line funnel guard inside `_log_activity` (`humanize_error(message)` when status=="failed"). Also fixed `/orchestrator/decide` returning `reasoning=f"Orchestrator error: {e}"`. Static-grep test added. 10/10 tests green.
- **Orchestrator result humanization (Cycle 11)** — closed the 4th and last leak funnel flagged in Cycle 10's honest gap. `claude_orchestrator.ClaudeOrchestrator.execute` previously built `OrchestratorResult(error=str(e))` on exception; now runs through `humanize_error(e, context=f"Executing {decision.skill_id} hit an error")` so `/orchestrator/execute` callers never see raw stack text. 10/10 tests still green. Four leak surfaces, four cycles, one helper, zero API growth.
- **Transcript-based voice-learn (Cycle 12)** — upgraded `/api/youtube/learn-voice` (Flow B slice 2) from titles+descriptions to actual yt-dlp transcripts. New `_fetch_transcripts_for_videos` helper runs 5 concurrent yt-dlp fetches via `asyncio.gather(run_in_executor(...))` reusing `routes.niche._extract_video_info`. Silent per-video fallback (transcript → description → `(no description)`). `TRANSCRIPT_CHAR_CAP=2000` bounds per-video context cost. Response surface adds `transcript_count` + `has_transcript` per video so frontend can show signal strength. 4 new tests (mixed prompt path, silent-fail, char-cap, template-mentions-transcripts) + 3 existing = 7/7 green in `test_learn_voice.py`. Regression suites still clean (10/10 humanize, 6/6 override-wired).
- **UI signal-strength banner (Cycle 13)** — surfaced `transcript_count` from Cycle 12 into `StyleSetupStep.tsx` with three-state copy: "learned from N transcripts (+M descriptions)" / "learned from N descriptions — add captions for sharper voice learning" / generic fallback. `api.ts` + `onboarding/page.tsx` types+state plumbing. `npx tsc --noEmit` clean.
- **Prod deploy of Cycles 8-13 (Cycle 14)** — Ryan granted SSH to VPS (clawd@76.13.119.181). Stashed dirty runtime artifacts on `~/projects/economy-fastforward`, `git pull origin main` (19 commits behind), `pip install -q`, `npm install && npm run build`, `sudo systemctl restart` both services. Migration 041 auto-applied. storyengine.dev `/` + `/api/health` + `/onboarding` all 200. Ran both functional suites against live VPS env: `test_error_humanization.py` 10/10, `test_learn_voice.py` 7/7. First time tonight's work reached production.
- **Runtime E2E activity-feed audit (Cycle 15)** — `tests/functional/test_activity_feed_no_raw_errors.py`: two passive scans against live prod DB (`bot_activity.message` + `background_tasks.error_message` for 16 raw-exception signatures — HTTPSConnectionPool, Traceback, Errno, 6 Python exception types, 3 upstream API hostnames, Connection aborted/refused/reset) + a helper-pattern pin that guards against adding a pattern to the catalog the helper can't strip. 3/3 green on VPS: 87 failed bot_activity rows + 1 failed background_task scanned, zero leaks. Closes the "needs a live backend" honest-gap flagged in Cycles 8-11.
- **Kie.ai validator hotfix (live customer bug)** — Ryan hit "Saved but validation failed" on the TOOLS onboarding step. Root cause: `vault.test_api_key` called `api.kie.ai/api/v1/user/balance` which 404s (deprecated endpoint) AND Kie.ai uses the 200-OK-with-error-body pattern, so checking HTTP status alone would still be wrong. Fixed by switching to `/api/v1/chat/credit` + parsing `{code, msg, data}` body. Ryan's key was valid all along (4335.86 credit). Shipped as commit `a61a4d2e`, pulled+restarted on VPS, verified `test_api_key` returns `{'success': True, 'message': 'Kie.ai API key valid (credit: 4335.86)'}`. 35-min turnaround screenshot→fix-live.
- **ElevenLabs validator hotfix (Ryan 2nd report)** — Same bug class. `/v1/user` requires the `user_read` scope which Ryan's TTS-only key doesn't have. Fixed by switching to `/v1/voices` (the endpoint StoryEngine actually calls for voice-picker population) + parsed the 401 body to distinguish `invalid_api_key` from `missing_permissions` for an actionable error message. Shipped as commit `bfcc9b46`. Verified green on VPS. Principle: validate against endpoints we actually use, not "hello world" endpoints.
- **TOOLS step UI fix (Cycle 17)** — Ryan's "4 keys but only 3 to enter, no Continue button" report. ElevenLabs groups two backend keys into one visual card, but the progress counter/disabled gate was counting raw keys. Switched to provider-count semantics (`renderItems.length`, `every(configured)` per grouped provider). `ApiKeysStep.tsx` commit `946ea7aa`, shipped, browser-verified live — counter reads "2 of 3 connected" and button reads "Connect all 3 tools to continue" with coherent state.
- **Dashboard WelcomeQuest — the "huge win" (Cycle 18)** — closed the "no onboarding after keys" gap. New `components/dashboard/welcome-quest.tsx` renders a three-step quest panel (add competitors → distill first insight → create first video) above the dashboard's analytics widgets, visible only while `video_count === 0`, dismissible with localStorage persistence. Backend added a `first_run: {competitor_count, distilled_count, video_count}` block to `/api/dashboard/onboarding/status`. Commit `68b9ee9d`, both services restarted on VPS, browser-verified live with all three cards rendering "0 of 3 done" on a fresh account.
- **Intelligence-teaser strategy memo (Task #24)** — Ryan's "do we let them run a free pass to get hooked?" question. Wrote a strategy memo at `storyengine/notes/intelligence-teaser-strategy-2026-04-19.md`. Recommendation: don't build the StoryEngine-funded teaser yet. BYOK already gives us a near-free hook (user's own credits cost pennies, $0 to us). First ship the UX changes shipped tonight + add event tracking, measure dropoff for two weeks, THEN decide whether to spend engineering on a funded teaser targeted at the specific dropoff point.

### Next in queue (priority order)
1. First real end-to-end customer-style render (Ryan as dogfood) — proves live output variation between two overrides end-to-end. Task #11.
2. **Audit the other `test_api_key` branches for the 200-OK-with-error-body pattern** — Anthropic, OpenAI, Gemini, ElevenLabs, Tavily all check HTTP status only. Same bug class would hit all of them if any provider silently moves to 200+JSON-code style.
3. **Synthetic canary for upstream-validator drift** — hourly cron hits `test_api_key` against known-good keys for each provider, pages on regression. Catches endpoint deprecation (like the Kie.ai one) before users see "validation failed."
4. Live yt-dlp stability test against a stable public YouTube URL (catches version drift + YouTube anti-scrape changes).
5. Fresh fix-roadmap.md rewrite against ground truth (drop items already shipped).
6. Clean-replacement override semantics — when an override is present, also strip the profile-derived voice preamble from the user-prompt body. (Current v1: override lands as `system_prompt`, preamble still in user body → Claude blends.)
7. Hourly launchd/cron wrap of Cycle 15's audit — continuous surveillance instead of ad-hoc runs.
8. Bump pydantic + pyjwt to satisfy supabase lib requirements (noted as non-fatal warnings during Cycle 14 deploy).

### Open questions for Ryan
- **Override replacement semantics:** currently the tenant override lands as Claude's `system_prompt` while the profile-derived voice preamble still lives in the user-prompt body → Claude blends the two. Clean-replacement (skip profile preamble when override present) is a follow-up decision once we measure output variation end-to-end.
- **Python-layer test harness:** backend expects local PG proxy on :55432 that isn't running on this Mac. For functional Python tests (not just SQL), either start the proxy or write tests as VPS-executable scripts.

## Handoff (2026-04-14 — PRD 3 T5 Storage + Bug Triage)

### Completed
- PRD 3 T5: Extended `storyengine/backend/storage.py` with Supabase Storage backend
  - `STORAGE_BACKEND` env var: "google_drive" (default) or "supabase"
  - Per-tenant path isolation: `{tenant_id}/{video_id}/{filename}`
  - `create_signed_url()` for time-limited access
  - All 4 acceptance criteria pass
- Investigated 5 live user errors: all routes work, errors were transient

### Next
- T12 (QA): Storage isolation verification — ready for qa-engineer
- T13 (Security): Final infrastructure audit — deps now met (T5 done)
- Consider updating `pipeline_executor.py` and `extraction.py` callers to pass `tenant_id` when `STORAGE_BACKEND=supabase`

---

## Handoff (2026-04-11 — Autopilot Intelligence + Second-Order Distillation)

### Phase 5: Intelligence Advisor (DONE)
- `storyengine/backend/distillation/advisor.py` (NEW) — IntelligenceAdvisor class
  - Queries content_intelligence aggregates for best-performing patterns
  - Returns: best hook type, thumbnail style, title structure, publish timing, top topics
  - `to_prompt_context()` formats for Claude prompt injection
  - `to_dict()` serializes for API response
  - Parallel async queries, confidence = min(1.0, sample_size / 50)
- Wired into `routes/autopilot.py` — Intelligence scoring now matches candidate DNA against niche recommendations
  - Candidates with matching hook_type get +15, title_structure +10, topics +10
  - Candidates query LEFT JOINs content_intelligence for hook_type, title_structure, topic_tags
  - New `GET /api/autopilot/recommendations` endpoint for dashboard
- Wired into `routes/discovery.py` — `_get_learnings_context()` now includes niche intelligence recommendations section

### Phase 6: Auto-Distillation + Meta-Analysis (DONE)
- `_auto_distill_intelligence()` background task in main.py (12h cycle, 25 videos/batch)
- `_auto_generate_meta_insights()` background task in main.py (24h cycle)
- `storyengine/backend/distillation/meta_analyzer.py` (NEW) — Second-order distillation
  - Gathers 10+ aggregated pattern queries (hooks, titles, thumbnails, topics, timing, controversy, tones, viral videos)
  - Sends to Claude Haiku for meta-analysis
  - Extracts: top_patterns, combination_insights, timing_strategy, contrarian_findings, niche_signature
  - Stores in `niche_meta_insights` table (upserted per tenant)
- `storyengine/backend/migrations/040_niche_meta_insights.sql` (NEW) — niche_meta_insights table
- `routes/intelligence.py` — 3 new endpoints:
  - `GET /api/intelligence/recommendations` — advisor recommendations
  - `GET /api/intelligence/meta-insights` — latest meta-analysis report
  - `POST /api/intelligence/meta-insights/generate` — trigger meta-analysis

### Phase 7: Frontend Dashboard (DONE)
- `api.ts`: New types + API functions (IntelligenceRecommendations, NicheMetaInsights, 4 new fetch functions)
- `analytics/page.tsx`: Two new panels in Niche Intelligence section:
  - **AI Recommendations** — 4-card grid: Best Hook, Best Title Structure, Best Thumbnail, Best Timing + top topics
  - **Niche Meta-Analysis** — Claude-generated report with top patterns, contrarian findings, winning combinations
  - Generate button for meta-analysis when 20+ videos distilled

### What's next:
1. **Deploy**: Restart backend to auto-apply migrations 036-040 + start background tasks
2. **Trigger backfill**: `POST /api/intelligence/backfill?batch_size=50` (or wait 12h for auto-distillation)
3. **Trigger meta-analysis**: `POST /api/intelligence/meta-insights/generate` (or wait 24h)
4. Extend distillation to video_scripts, research_payloads, agent_paper_trails
5. Add GCS archival for raw transcripts after distillation
6. Autopilot auto-launch: use recommendations to auto-select which discovery idea to launch

**Design decisions:** See `tasks/decisions.md` — ADR 2026-04-11

### Previous: Phases 1-4 (Content Intelligence Full Stack) — DONE
- Backend distillation pipeline (Haiku + Gemini Vision + OpenAI embeddings)
- 10 intelligence API endpoints + frontend UI
- Intelligence-driven scoring in autopilot + discovery

---

## Active Work

**Execution Plan:** `tasks/roadmap.md` — 18-day SaaS transformation
**Current PRD:** PRD 3 — Infrastructure (Security, Rate Limiting, Task Persistence, Logging, Health Check)
**Agent Team:** 6 agents on Opus. PRD 2 mostly complete (11/13). PRD 4 complete (15/15).

### PRD 3 Progress
- [x] **Task 1** (SEC-1, SEC-2, SEC-3): Already done by agent team — verified
- [x] **Task 2** (SEC-4, SEC-5, SEC-6): SEC-4/SEC-6 already done. SEC-5 safety comments added to all 12 f-string SQL queries
- [x] **Task 3**: Rate limiting middleware (`rate_limit.py`) — per-plan token bucket, concurrent job limits
- [x] **Task 4**: Persistent background tasks — migration 032, `_db_persist_task()` fire-and-forget, `recover_stale_tasks()` on startup
- [ ] **Task 5**: Per-tenant storage — DEFERRED (users will connect own Google Drives, not Supabase Storage)
- [x] **Task 6**: Structured JSON logging (`logging_config.py`) — all `print()` in main.py replaced with `logger.*`
- [x] **Task 7**: Health check expansion — `/api/health` checks DB + active tasks, `/api/health/detailed` with token auth
- [ ] **Task 8**: QA security verification (depends on Tasks 1-2)
- [ ] **Task 9**: QA infrastructure verification (depends on Tasks 3-7)
- [ ] **Task 10**: Frontend health status indicator (depends on Task 7)
- [ ] **Task 11**: Security final audit (depends on all tasks)

## Handoff (2026-04-10 — PRD 3 Phase 1+2 Build)

**What was built:**
- `storyengine/backend/rate_limit.py` (NEW) — Token bucket rate limiter per plan (free: 15/min, starter: 30, creator: 100, studio: 300). Concurrent pipeline job limits. Skips health/auth paths.
- `storyengine/backend/logging_config.py` (NEW) — StructuredFormatter (JSON), RequestLoggingMiddleware, error rate tracking (10/5min threshold)
- `storyengine/backend/migrations/032_background_tasks.sql` (NEW) — Persistent task tracking table with RLS
- `storyengine/backend/routes/pipeline.py` — Added `_db_persist_task()` (fire-and-forget DB writes on key transitions), `recover_stale_tasks()` (startup recovery). 61 `_set_task_status` calls now pass `tenant_id=tenant_id` for DB persistence.
- `storyengine/backend/main.py` — Wired RateLimitMiddleware + RequestLoggingMiddleware. Replaced ALL 18 `print()` with `logger.*`. Added startup task recovery. Expanded `/api/health` + new `/api/health/detailed`.
- `storyengine/schema.sql` — Added background_tasks table definition
- 10 route files — Added SEC-5 SECURITY comments to all f-string SQL queries

**Design decisions:**
- Task tracking is dual-layer: in-memory dict for real-time progress (sync-compatible with progress callbacks), DB for persistence/history. Fire-and-forget via `asyncio.create_task()`.
- Task 5 (per-tenant Supabase Storage) deferred — user wants BYOD Google Drive model.
- Rate limiting is in-memory (resets on restart) — acceptable for v1 since it's protective not billing-critical.

**What's next (Phase 3):**
- Tasks 8-9: QA verification of security + infrastructure
- Task 10: Frontend health status indicator component
- Task 11: Final security audit
- Deploy to VPS and verify migration 032 runs

**Previous:** PRD2 T1-T11 verified. PRD 4 complete (15/15).

**PRD 2 status:** 11/13 done. T12 (QA Playwright regression) and T13 (already done by qa-engineer) are the only remaining items. T12 dependencies now all met.

**PRD 4 COMPLETE** — All 15/15 tasks done.

**Still open:** 3 SEC bugs in task queue (SEC-SSE-001 cross-tenant SSE, SEC-EMAIL-001 HTML injection, SEC-KEYS-001 exception leak). These are for backend-dev.

Previous handoff (PRD 2):
All 7 PRD 2 backend tasks are committed and passing acceptance criteria:
- Task 1: Migration 029 (trial_warning_sent column)
- Task 2: Query-param token auth in auth.py for SSE connections
- Task 3: SSE stage_change events (already existed)
- Task 4: POST /keys/validate bulk API key testing with timeout
- Task 5: email_service.py shared email module + email.py stub
- Task 6: Billing receipt email on checkout (already wired)
- Task 7: email_tasks.py trial warning system (already created)
Frontend tasks 8-12 are now unblocked. Task queue is empty.

### What Shipped Today (2026-04-08)
- Billing page (`/billing`) with plan comparison, usage bars, Stripe integration
- Critical Bug Fixes PRD: all 14 tasks (6 backend, 6 frontend, 1 QA, 1 security)
- Competitors page refactored (server-side pagination, filters, sort, scrape progress)
- Error boundaries + 404 page
- Toast notification system (replaced 81 alert() calls)
- System prompt editors on pipeline tabs
- Trial countdown badge + banner
- REG24 regression sweep: 24/24 pages, 33/33 API, 9/9 tabs — 0 bugs
- UX Polish PRD backend tasks: render_minutes tracking, suggest-titles endpoint, welcome email

### Next Up (from roadmap Day 3-5)
- [ ] Plan enforcement: `tenant_usage` table, `check_plan_limits()` middleware, usage hooks
- [ ] Free trial logic: 14-day Creator trial on signup, countdown, downgrade-on-expiry
- [ ] Password reset flow: token table, email (Resend), `/reset-password` page
- [ ] Disable dev-token in production mode
- [x] Create video simplification: POST /api/videos/suggest-titles endpoint built
- [ ] Frontend: wire suggest-titles into create video flow (PRD Task 8)

---

## Blocked / Pending

### Storyboard Extraction V2 (from 2026-04-04)
- **T27-003**: Rewrite storyboard-extract endpoint for Supabase
  - Wire `extraction.py` into `pipeline_executor.py` (currently silently does nothing for Supabase videos)
  - Read grid URLs from `scripts` table → call `extract_grid()` → update `assets.image_url`
  - Grid layout is 3x2 (6 panels per grid), NOT 3x3
  - Test video: f9749bd2 ("Drones"), 6 scenes
- **T27-004/005/008**: Permanent storage for all image gen steps (Supabase Storage)

### Security Issues (from Critical Bug Fixes PRD)
- SEC-1 (CRITICAL): dev-token bypasses all auth in dev mode
- SEC-2 (HIGH): get_scene_audio skips tenant check
- SEC-3 (HIGH): API keys revealed without rate limiting
- SEC-4 (HIGH): Hardcoded IP in CORS allowlist
- SEC-5 (MEDIUM): Dynamic SQL via f-strings
- SEC-6 (MEDIUM): No audit logging for key management

### Rubric / Agent Team Improvements
- [x] Cron health audit: crons.json synced with setCadence, security-auditor wired, health checks fixed
- [x] Cadence buttons: all 6 tiers (light/normal/fast/max/turbo/ultra) now sync crontab + crons.json + UI labels
- [x] Feature 1: Concurrency guard — PID lock file + stale lock cleanup in run-agent.sh
- [x] Feature 2: Run timeout — `timeout` command wrapping Claude CLI (30min default)
- [x] Feature 3: Duration + cost tracking — timing, cost heuristic, model in activity log
- [x] Feature 4: Log viewer — `/api/logs` + `/api/logs/:agent` endpoints, dashboard modal with auto-refresh
- [x] Feature 5: Crons-controls sync — grayed out paused/OFF jobs, "Team OFF" badges
- [x] Feature 6: Runtime visualization — `/api/run-history` endpoint, calendar overlay (green/red/amber bars), Scheduled/Actual/Both toggle
- [x] Feature 7: Dashboard notifications — toast alerts polling activity log, auto-dismiss
- [x] Feature 8: Cost summary panel — `/api/cost-summary` endpoint, 24h/7d/30d cards + per-agent bar chart
- Command Center: Master ON/OFF toggle, clear queue button, task counter reset
- Activity feed: auto-scroll, WebSocket for real-time, collapse old entries
- Playwright auth fix: 13/20 QA tests skip (need shared auth intercept fixture)

---

## Latest Handoff (2026-04-08)

**What completed (PRD 2 backend):**
- Task 1: Migration 029 (trial_warning_sent column) — already existed
- Task 2: Query-param token auth for SSE — already existed
- Task 3: SSE stage_change events in /api/activity/stream — NEW: polls stage_transitions table, emits `event: stage_change` alongside `event: activity`
- Task 4: POST /api/settings/keys/validate — already existed
- Task 5: email_service.py extracted from google_auth.py — already existed (named email_service.py not email.py to avoid stdlib shadow)
- Task 6: Billing receipt email on checkout.session.completed — NEW: sends receipt via email_service after Stripe checkout
- Task 7: email_tasks.py with check_trial_warnings() — NEW: finds accounts with trial expiring in 3 days, sends warning, sets trial_warning_sent flag

**Frontend tasks UNBLOCKED:** 8, 9, 12 (depend on task 3), 11 (depends on task 4)
**QA task 14** depends on all other tasks

**Key context for next session:**
- `tasks/roadmap.md` has the full 18-day plan with daily deliverables
- `tasks/decisions.md` has settled architectural choices (10 ADRs)
- email_tasks.py needs to be wired into a background loop in main.py lifespan (not done yet — task 7 only creates the module)

Previous handoffs archived in `tasks/archive/handoffs-2026-03-to-04.md`

## Handoff (2026-04-10 — QA verification + security audit)
PRD2 Pipeline UX: 12/14 done+verified. T12 (full regression) blocked on T3/T4/T7/T10.
- BUG-USER-800807 confirmed fixed (380178b) — backend returns "Invalid or expired session", frontend suppresses auth 401s from RUBRIC
- T9 verified: trial warning wired in main.py lifespan (12h interval), email_tasks.py + migration 029 present
- T2 verified: SSE hook matches backend event shapes exactly (stage_change + task_progress), tsc clean
- T13 security audit DONE — filed 3 bugs for backend-dev:
  - SEC-SSE-001 HIGH: _running_tasks dict at pipeline.py:51 has no tenant scoping — cross-tenant leak via SSE stream
  - SEC-EMAIL-001 HIGH: email_service.py:59,110 — display_name not html.escape()'d in email templates
  - SEC-KEYS-001 MEDIUM: vault.py:326 Gemini key in URL + vault.py:356/settings.py:231 leak exception details
- Remaining: T3 (PipelineStepper), T4 (wire stepper), T7 (key validation UI), T10 (notification provider) for frontend-dev
- T12 (full QA regression) depends on all of the above

## Handoff (2026-04-10)
- PRD 2 (Pipeline UX) is active with 13 tasks, agents executing
- Fixed: ANTHROPIC_API_KEY leak ($64/day), stale progress.md, RUBRIC PRD display, agent coordination
- RUBRIC layout: two-column (queue + activity feed), tasks labeled by PRD
- Agents use OAuth now (no API key charges)
- Monitor: check cost page Apr 11 to confirm $0 API charges

## Handoff (2026-06-08 — pipeline import repair + Youtuber agent)
- **Fixed:** 5 stale shim-name imports left by 17b03be0 — pipeline now imports cleanly again (orchestrator.pipeline + all 5 touched entrypoints verified). Branch `claude/repair-pipeline-imports`. Done in an isolated git worktree (~/yt-repair) to avoid the storyengine dev-swarm's git stash/checkout/reset on the shared tree.
- **Not done / next:** smoke test was import-only (no paid run). Before relying on production: run a single-video dry pass, and reinstall the setup_cron.sh production jobs (queue/discover/autopilot) — they are NOT in the live crontab (only storyengine/agents swarm + bot_healthcheck).
- **Separate effort:** standing up a new Hermes agent profile `Youtuber` (~/.hermes/profiles/youtuber) as the YouTube production brain that drives this pipeline; multi-channel generalization planned (ChannelConfig). See ~/Desktop/Power_Doctrine Pipeline-main-integration/HERMES_REBUILD_PLAN.md.
- **Caution:** `/home/clawd/pipeline-bot/venv` (referenced by infra detect_python) does not exist; live fallback is repo-root `economy-fastforward/venv`.

## Handoff (2026-06-08 — neuter Slack for customer-facing bot)
- SlackClient no longer raises without a token; degrades to a silent no-op (enabled flag + guarded API methods). Verified: no-token instantiation + all notify_* return None, no exceptions.
- Paired with blanking SLACK_BOT_TOKEN/SLACK_APP_TOKEN in the VPS .env (gitignored) so the pipeline posts nothing to Slack. The legacy Slack listener (pipeline_control.py) is already stopped + its healthcheck cron disabled.
- Context: pipeline is being driven by the new Telegram bot @YoutubeAGI_bot (Hermes profile 'youtuber'); Slack is being retired.

## Handoff (2026-06-08 — multi-tenant ChannelConfig foundation)
- DONE: dedicated free Supabase project `youtuber` + multi-tenant schema (creators/channels/channel_config/drive_connections/videos/competitors/video_metrics, RLS on). `shared/channels/` ChannelConfig loader. Threaded into VideoPipeline + --channel flag. Verified: default-equivalent for economy_fastforward + distinct config loads for a second channel.
- NEXT: (1) per-creator Google Drive OAuth connect flow (needs a hosted OAuth callback for the Telegram UX — design decision). (2) Supabase-backed status machine so state_store='supabase' channels actually produce (videos table read/write path; today only config is multi-tenant, EFF still on Airtable). (3) wire onboarding to auto-create a creator's ChannelConfig.
- Secrets: YOUTUBER_DB_URL in VPS .env (gitignored). psycopg2-binary added to requirements.

## Handoff (2026-06-10 — yt-dlp YouTube bot-check investigation)
- DONE: confirmed VPS IP is hard-flagged by YouTube (all player clients, latest yt-dlp, PO-token provider, youtube-transcript-api all blocked — see lessons.md). Wired `YTDLP_COOKIES_FILE` + `YTDLP_PROXY` env support into routes/niche.py (`_ytdlp_antibot_opts()`); verified wiring + graceful degradation + flat-listing/oEmbed regression on real videos. Branch `claude/ytdlp-bot-check-fix`.
- ACTION NEEDED (Ryan): export YouTube cookies from a logged-in browser (Get cookies.txt extension, Netscape format), upload to the VPS (e.g. /home/clawd/.config/storyengine/youtube_cookies.txt), add `YTDLP_COOKIES_FILE=<path>` to storyengine/backend/.env, restart backend + worker. Use a throwaway/secondary Google account — YouTube can flag accounts used for scraping. Alternative: set `YTDLP_PROXY` to a residential proxy.
- After cookies/proxy are in place, re-verify: `_extract_video_info("PHe0bXAIuk0")` returns title + transcript, then check Model A Video extract, competitor scrape, voice-learn.

## Handoff (2026-06-22 — character consistency: GPT Image 2 scene images + coverage)
- DONE: GPT Image 2 is the character-lock scene-image path (`image_client.generate_scene_image_gpt`, always-available scene model). Coverage-frames-to-app store path (`scripts/coverage_to_app.py`) + pipeline route wiring + Characters / Scenes workspace UI. Committed here after being found running-but-uncommitted on the VPS.
- ALSO shipped today (separate effort): the YouTube intelligence ruleset is live - but/therefore + a 15-second hook rule in the script engine, a retention grader gate (`grade_script_with_client` routes via the tenant's `AnthropicClient` so it covers Kie-gateway tenants too), an idea scorer in chat, and a format-aware script engine that auto-applies story craft vs teaching craft per niche (verified live: ESL teaches, true-crime tells a story). See `storyengine/YOUTUBE-INTELLIGENCE-RULESET.md`.
- NEXT: the character-consistency / coverage UI may still be mid-iteration (the session was actively editing `pipeline.py` when this was committed) - verify a real coverage run end to end. The format-aware engine supersedes `tasks/engine-identity-seeds/faceless-story.md` for auto-handling channel types.

## Handoff (2026-07-12 - DVsU single-machine script proof)
- SUPERSEDED by the 2026-07-13 Anton schema-v3 handoff at the top of this file.
- The four-beat problem/decision/tradeoff/outcome sentence compiler and deterministic extractive fallback are intentionally retired for DVsU machine previews.
- Current next step remains: deploy the Anton slot + claim-map pipeline, then rerun only the XB-15 `machine-script-preview` endpoint and review the saved paragraph before touching Machine 2.

## Handoff (2026-07-13 - First DVsU machine pass UI lock)
- XB-15 is the first single-machine research + script preview pass. Keep the workflow scoped to one selected machine until the operator approves moving forward.
- Superseded UI rule: Research must show saved machine research cards and exact evidence only. Script output belongs in the Script phase, where the selected machine action writes/saves the real script block.
- Required Anton slots include `memorable_fact`; if verified one-machine research cannot source a memorable fact that supports the engineering story, the preview should fail for formula adjustment instead of producing a generic catalog paragraph.

## Handoff (2026-07-13 - DVsU selected-machine script blocks)
- Script phase should generate one selected machine at a time as a real script block, not as a Research preview.
- The selected-machine script action saves a validated paragraph into that machine's `scripts` row, updates `script_validation.script_hold`, and leaves the full roster untouched.
- Next: run Machine 2 from Script after reviewing its saved research card; do not run Machine 3 or a full roster script until Machine 2 passes.
