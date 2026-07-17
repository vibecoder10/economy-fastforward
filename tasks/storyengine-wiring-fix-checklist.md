# StoryEngine Wiring Fix Checklist

**Date:** 2026-07-17 · **Source:** 4-agent codebase audit — full findings with file:line evidence in `docs/reports/2026-07-17-storyengine-agent-audit-findings.md` — + Higgsfield gap analysis (`docs/reports/2026-07-17-higgsfield-vs-storyengine-gap-analysis.md`). Every item below traces to a finding in the audit report; consult it before re-exploring the codebase.

**The law (from CLAUDE.md):** every item below lists ALL layers it touches — Data, Backend, UI/UX, Verify. An item is NOT done until every listed layer ships and the Verify step passes. A fix that lands in one layer only creates exactly the stubs this list exists to kill. No checkbox flips without the Verify evidence.

**Second law — two doors, one registry (see `tasks/storyengine-copilot-ux-map.md`):** every user-facing capability ships BOTH a clickable control AND a conversational path (Producer/co-pilot phrasing), both calling the same `actions.py` verb. The UX map defines the exact click paths and example utterances per feature — build to it.

Legend: `[B]` backend · `[D]` data/schema · `[U]` UI/UX · `[V]` verify

---

## P0 — Integrity: things that lie to the user today

### 0.1 Image-model dropdown is cosmetic ⚠ worst offender
The Pictures model select (`nano-banana-2`/`gpt-image-2`/`z-image`) writes `video.image_model_override`, but the live coverage path ignores it.
- [ ] `[B]` `storyengine/backend/scripts/coverage_to_app.py` (L621/906/978): read `image_model_override` and route to `generate_scene_image_zimage` / nano path instead of hardcoded `generate_scene_image_gpt`. Keep GPT Image 2 as default + content-policy fallback.
- [ ] `[B]` Confirm legacy path (`pipeline_executor.py` L13694-13716) and coverage path resolve the override through ONE shared helper — no duplicated resolution logic.
- [ ] `[U]` `ScenesWorkspaceTab.tsx` (L1121-1126): selector shows which model actually generated each panel (badge on the asset), so a mismatch is visible instead of silent.
- [ ] `[V]` Set override to `z-image`, run pictures, confirm the Kie task payload names z-image AND the asset row records it. Repeat for nano.

### 0.2 Dead model options in the registry
Kling 3.0 Pro, Runway Gen-4 Turbo, Hailuo 2.3 exist in `MODEL_REGISTRY` (`shared/channel_profile.py` L285-293) but fail at the `wired` gate (`pipeline_executor.py` L11775-11783).
- [ ] `[B]` Add `wired: bool` to the registry entries — single source of truth; delete the separate hardcoded `wired` set.
- [ ] `[U]` Frontend `WIRED_MODELS` (`ScenesWorkspaceTab.tsx` L46-50) must be DERIVED from a backend endpoint (`GET /api/models`), not a hand-copied list. Unwired models: hidden, or shown "coming soon" — never selectable.
- [ ] `[V]` curl `/api/models` matches what the dropdown renders; selecting every listed model generates without the "isn't available yet" error.

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
- [ ] `[B]` Keep the default, but record `research_skipped=true` on the video/plan.
- [ ] `[U]` Plan card + pipeline page show "Research: skipped (script writes from topic) — Run research" chip with one-tap enable. Copilot mentions it in the plan summary.
- [ ] `[V]` Create default video → chip visible; tap → research stage runs and chip clears.

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
