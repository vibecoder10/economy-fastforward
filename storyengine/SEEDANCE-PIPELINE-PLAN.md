# GOAL — StoryEngine coverage storyboards + two animation routes

## ⏯ RESUME HERE (handoff, end of 2026-06-22)

**One-line state:** the storyboard step is now ONE cheap GPT Image 2 image, wired to the UI. Ryan was about to click **"Generate scene 1"** to test it. Everything below is deployed + live on the VPS.

**Test vehicle:** video "Dragon Rider Off the Cliff" — id `e05303ed-31c0-41c8-8ed2-31fc4467fb12`, tenant `ee93e6d1-a9cc-44c3-81e9-84adee8329aa`. 3 scenes. Old coverage frames/boards were CLEARED (clean slate). Characters WARRIOR + DRAGON are LOCKED (photoreal 4-view sheets + precise descriptions).

**The locked flow (Ryan's vision):**
1. Lock characters → 4-view reference sheets (done for Dragon Rider). `coverage_to_app.py --redo-characters`.
2. **Storyboard = ONE GPT Image 2 image** (whole sheet, cheap/fast ~$0.10/1-2min) → the "do I like the story direction?" test. `generate_storyboard_sheet_for_scene` — WIRED to the UI "Generate scene" button.
3. Approve → **generate the REAL per-shot images** (`generate_coverage_for_video` = master+angles coverage, GPT Image 2, anchored on locked cast). EXISTS but NOT wired to a button yet — **next task**.
4. Animate (Phase 2/3): grok per-shot OR seedance whole-sheet (simple prompt — spec in LOCKED ARCHITECTURE). Not built.

**Immediate next steps:** (a) confirm Ryan's "Generate scene 1" produced a good one-image storyboard; (b) wire a "generate real images" UI action → `generate_coverage_for_video`; (c) then the animate routes.

**Where the code is (all on VPS `~/projects/economy-fastforward`, deploy by scp):**
- `storyengine/backend/scripts/coverage_to_app.py` — stage fns: `generate_storyboard_sheet_for_scene` (one-image storyboard, WIRED), `generate_coverage_for_video` (real per-shot frames, NOT wired), `redo_characters`, `populate_characters`, `set_scene_board`, `load_character_bible`. Also a CLI.
- `storyengine/backend/routes/pipeline.py` — storyboard-images route → calls `generate_storyboard_sheet_for_scene` (clean file; safe to edit).
- `skills/video-pipeline/storyboard/coverage.py` — coverage core (directive, frames, cast). `skills/video-pipeline/shared/clients/image_client.py` — `generate_scene_image_gpt` + `generate_thumbnail_gpt2`; VALID_SCENE_MODELS always includes `gpt-image-2`. `skills/video-pipeline/images/run.py` — standard pipeline defaults to gpt-image-2.
- frontend `components/production/ScenesWorkspaceTab.tsx` (model selectors surfaced at top; generate handlers call storyboard-images directly) + `CharactersTab.tsx` (full sheet + click-to-expand lightbox).
- Reference prompts on Ryan's Desktop: `storyboard-prompt.md`, `character-creation-prompt.md` (the "burger" prompts; storyboard one has a [GAP] to fill).

**DEPLOY/OPS GOTCHAS (read before touching prod):**
- Restart backend with **`kill -9 $(systemctl show -p MainPID --value storyengine-backend.service)`** — NEVER plain `kill` (uvicorn graceful-drains forever on the polling frontend → 502 + stale 409 lock). Frontend: plain `kill` MainPID is fine; rebuild first (`cd frontend && npm run build`). `systemctl restart` needs sudo (unavailable). Backend :8001, frontend :3001, both systemd, user clawd.
- **Launch-readiness agent has WIP in `pipeline_executor.py` — DO NOT scp/edit it.** image_client.py / images/run.py / routes/pipeline.py were clean.
- Redis is DOWN → tasks run in-process. Killing mid-task leaves a stale `background_tasks` 'running' row → 409 "task already running" → clear: `UPDATE background_tasks SET status='failed' WHERE video_id=… AND status IN ('running','pending')`.
- `STORAGE_BACKEND=supabase` set in storyengine/.env + backend/.env (backend has NO Drive creds; bucket=`assets`). main.py loads `storyengine/.env`.
- Tenant Claude: `from kie_unified import get_text_client_for_tenant`; for the DIRECT-Anthropic client pass model `claude-sonnet-4-6` (its built-in default id is stale → 404). Kie key: `from vault import get_secret('kie_ai_api_key', tenant)`.
- GPT Image 2 is SLOW (~min/frame, 10-min poll cap) — never generate many frames sequentially for a preview. Repo `.env` Anthropic key is DEAD (use the tenant path). `python3` not `python` on the Mac.

Full detail in the **Log** at the bottom + memory `storyengine-coverage-phase1.md`.

---


**North star:** StoryEngine makes videos whose cuts feel like real coverage (several cinematic angles of the same moment), via two routes off one shared storyboard: a cheap any-length **grok** route and a short coherent **Seedance one-shot** route.
**Success looks like:** a grok any-length video and a Seedance short both render with smooth coverage cuts; the route is selectable; the existing 3×3 flow + per-panel Seedance stay as fallbacks (no regression for live tenants).
**Status:** Storyboard FORMAT locked by Ryan 2026-06-22 (burger-style shot list). Building: storyboard writer → render into app → UI route selector → grok route → Seedance whole-sheet route.
**Updated:** 2026-06-22

Proven groundwork: the beats+coverage approach and the Seedance whole-sheet one-shot are both proven in the content-engine skill (`~/.claude/skills/content-engine`, fishing v2 + Phase 0). This is porting that into StoryEngine.

## LOCKED ARCHITECTURE (confirmed by Ryan 2026-06-22, via the content-engine blueprint)
At video creation, a **UI selector** picks the animation route. **Both routes build the EXACT SAME storyboard** — a "burger-style" cinematic SHOT LIST (the format Ryan approved; sample at `~/Desktop/dragon-rider-storyboard.html`):
- numbered panels, a timecode per shot (from each shot's `cut`), a caption under each (action / Expression / Mood), clean grid layout.
- **Coverage is built IN** to the sequence: a moment appears as consecutive shots (master + matched angles), then the next moment. One readable shot list — you see exactly every shot.
- Modeled on the content-engine spec: each shot = {description, shot_type, cut (s on screen), motion, optional dialogue, role master|angle}.

The selector ONLY changes how that storyboard is animated:
- **Grok route** — generate each shot's image, animate each, trim to `cut`, stitch → any length.
- **Seedance route** — upload the WHOLE storyboard sheet as the reference → Seedance (2.0 Fast) one-shots the clip (per scene). The PROMPT stays SIMPLE and lets the storyboard do the lifting (Ryan's spec 2026-06-22). Locked prompt: "Use the reference storyboard into a complete animation film, preserving character consistency, and visual style. Smooth camera movement and natural storytelling. No text or subtitles. Audio: diegetic sound only — natural ambience, environmental foley, and subject-driven sound." (NB: this whole-sheet route is NEW vs the content-engine, whose seedance is per-shot.)

Render: build the burger HTML, screenshot to PNG via **headless chromium (already on the VPS)**, store as the app board (`scripts.storyboard_N_url`). Storage = Supabase (backend has no Drive creds for standalone scripts). Tenant Claude via `get_text_client_for_tenant`; direct-Anthropic model = `claude-sonnet-4-6`.

Locked decisions (2026-06-22): coverage is a NEW mode (current 3×3 storyboard stays as fallback). Plan lives here, NOT in StoryEngine GOAL.md (the launch-readiness agent owns that).

---

## Phase 0 — Per-panel Seedance animator  `[done]`
Goal: Seedance selectable as the pricey per-clip animator (drop-in for grok).
- [x] Deployed + verified live on the VPS (`video_model=seedance-2-fast`); see [[storyengine-seedance-deploy]].
Done when: a video set to seedance-2-fast animates per-panel on prod. ✓ (script→storyboards proven; picker frontend still owed, see Phase 4.)

## Phase 1 — Coverage storyboard generator  `[done]`
Goal: the storyboard step produces coverage — per beat, several matched cinematic angles of the SAME moment.
- [x] Ported beats/coverage prompting from content-engine into a NEW module `skills/video-pipeline/storyboard/coverage.py` (NOT bot.py — kept the 3×3 file untouched so it can't collide with the launch-readiness agent's WIP). Per moment: a master + 2-4 matched angles (ELS/WS/MS/MCU/CU/ECU/OTS/INSERT).
- [x] Matched angles via reference-chaining: master anchored on cast sheet, each angle anchored on [cast sheet, master frame] + "only the camera angle changes" — reuses the existing `image_client.generate_with_reference` (no change to image_client.py / pipeline_executor.py).
- [x] Coverage panels saved with angle/shot-type metadata (`coverage.json` per scene). Auto-builds a cast sheet from the story bible when no cast is locked (Ryan's call) so coverage always has an anchor. Gated: reachable only via the new CLI; 3×3 flow untouched. (DB/Image-record storage deferred to Phase 2, where the animator consumes the frames.)
Done when: a test scene yields 3-4 matched angles that clearly read as the same moment. ✓
**Proof (2026-06-22):** Dragon Rider mini-scene, 3 moments, ~$0.65. ~10/11 frames matched cleanly (same character, same instant, different camera). Found + fixed one failure: tight face-recompose angles (MCU/CU) could invent a SECOND person when the master framed the subject small — fixed with a single-subject guard on the angle prompt (re-proven: the MCU that had 2 people now has 1) + a light retry (also softens nano-banana's "flagged as sensitive" frame drops). Second fix: tight recomposes drifted to 2D/painterly (a photoreal MCU came out cartoonish) because the coverage prompts carried NO style instruction and the neutral profile adds none. Fixed with a STYLE LOCK on EVERY frame (master + angles), mirroring generate_contact_sheet — locks each frame to the cast sheet's rendering style (photoreal cast → photoreal frames). Re-proven photoreal on both the medium and the tight insert. So coverage realism is driven by the cast sheet's style, which is the right generic behavior for any channel.

## Phase 2 — Grok route on coverage (any length)  `[todo]`
Goal: animate each coverage panel individually, stitch → any-length video with coverage cuts.
- [ ] Point the per-panel clip stage at coverage panels; reuse existing animate + FFmpeg stitch.
- [ ] Verify cuts read as coverage across multiple scenes.
Done when: a multi-scene video stitches with smooth coverage cuts.

## Phase 3 — Seedance route on coverage (short, one-shot)  `[todo]`
Goal: lay a scene's coverage panels into one high-res sheet → one-shot Seedance → coherent clip.
- [ ] Compose coverage panels into one high-res storyboard sheet (GPT Image 2; the 3×3 preview is too low-res).
- [ ] Seedance route: feed the whole sheet → one clip per scene → stitch scenes. Gate scenes ≤15s on this route.
Done when: a short one-shots coherent clips from coverage sheets.

## Phase 4 — Deploy + route picker  `[todo]`
Goal: ship it.
- [ ] Surgical patch to the VPS (clean-base + my-edits, like Phase 0).
- [ ] Frontend route/mode picker + the still-owed Seedance picker option (needs the Next.js rebuild skipped in Phase 0).
Done when: routes are selectable in the app and both produce video on prod.

---

## Log
- 2026-06-22 — STORYBOARD = ONE IMAGE (Ryan's redirect; the 12-separate-frames approach was too slow/expensive for a preview). The storyboard step is now a CHEAP/FAST single GPT Image 2 image of the whole sheet (Claude writes the burger-style sheet prompt → GPT Image 2 draws all panels in one image, anchored on the locked cast). `scripts/coverage_to_app.py:generate_storyboard_sheet_for_scene`; the storyboard-images route calls IT now (not generate_coverage_for_video). Flow: cheap storyboard preview → Ryan approves the direction → THEN generate the real per-shot images (generate_coverage_for_video stays for that step, to be wired to its own button). GPT Image 2 per-frame is slow (~min each, 10-min poll cap) so 12 sequential = 30+ min — that's why the preview must be one image. NEXT: Ryan clicks Generate scene 1 (one image, ~$0.10, ~1-2 min) → review → wire a 'generate real images' action.
- 2026-06-22 — COVERAGE WIRED INTO THE UI (Phase 4 core). The "Generate scene"/"Generate all scenes" buttons now run the coverage flow end-to-end in-app. Backend: `routes/pipeline.py` storyboard-images route `_run()` calls new `scripts/coverage_to_app.py:generate_coverage_for_video(video_id, tenant_id, scene, progress)` instead of `executor.run_storyboard_images` (stays out of the WIP-locked pipeline_executor). That fn anchors frames on the LOCKED video_characters 4-view sheets (cast_url now accepts a LIST → coverage.py handles it) + the bible, GPT Image 2, stores assets + renders the burger board. Frontend: handleGenerateScene/AllScenes now call storyboard-images DIRECTLY (dropped the standard "storyboards" prompt step — coverage self-plans). STORAGE: set `STORAGE_BACKEND=supabase` in storyengine/.env + backend/.env (the backend had NO Drive creds, so storage.upload_bytes was failing → coverage-in-backend now uploads to Supabase). Added scripts/__init__.py so the route can import the stage. Stale-lock root cause (earlier "nothing happened" = 409): plain `kill` left uvicorn draining; always `kill -9`. NEXT: Ryan clicks Generate scene 1 in the UI (paid, ~$1-1.5, GPT Image 2) → verify cast lock holds, then scenes 2-3.
- 2026-06-22 — GPT IMAGE 2 = MAIN MODEL (Ryan's call). It holds the cast's identity from the sheet far better than nano-banana (per the codebase A/B note) → directly helps consistency. Wired everywhere: added `gpt-image-2` to `ImageClient.VALID_SCENE_MODELS` (always-merged so the profile can't drop it) + `generate_scene_image_gpt`; `images/run.py` routes it AND defaults to it when no override; the Scenes picture selector defaults to it; the coverage flow (coverage.py `_gen_ref`→`generate_thumbnail_gpt2`, cast sheet→gpt text-to-image) + character sheets/portraits (`coverage_to_app.py`) all use it. Kie models: `gpt-image-2-image-to-image` (with ref) / `gpt-image-2-text-to-image` (no ref). Still nano: standard "Redesign Cast" (routes/characters.py PORTRAIT_MODEL) + environments — flip later if wanted.
- 2026-06-22 — CONSISTENCY FIX. Scenes 2-3 drifted (warrior in leather/helmet, dragon recoloured) because the writer never saw the locked cast — it freelanced the look and the image model painted the words. Fix: (a) feed the locked cast to the writer as a BINDING bible + rule "copy each character's exact appearance verbatim into every shot" (coverage.py); (b) rebuilt WARRIOR + DRAGON as photoreal 4-VIEW reference sheets via the locked character-creation prompt (`coverage_to_app.py --redo-characters`) + tightened their descriptions (precise: warrior=gunmetal plate/cobalt trim/eagle crest/navy cloak; dragon=jet-black obsidian/charcoal wings ember-red veining/molten gold eyes/swept horns). Cast must be LOCKED before regenerating scenes (Ryan: "restart everything", do characters first). NEXT: confirm warrior/dragon style match → regenerate all scenes anchored on the per-character 4-view sheets + bible. Warrior first came out painterly (Ryan: "i said realistic") → hardened the CHARACTER_SHEET_STYLE to "a real photograph, NOT painting/illustration/concept-art" + regenerate FRESH text-to-image (no painterly anchor leaking back), via `--redo-characters --character WARRIOR`. Both now realistic + style-matched + locked.
- 2026-06-22 — Storyboard FORMAT locked (burger-style) + rendered into the app. `coverage_to_app.py --complete` now renders each scene's coverage frames as the burger board (numbered/timecoded/captioned HTML → PNG via headless chromium on the VPS) and sets `scripts.storyboard_1_url`. Gotcha: snap chromium is sandboxed — embed frames as base64 + run under $HOME (not /tmp) + `--headless=new`. Dragon Rider scene 1 board live + verified. NEXT: scenes 2-3 (~$1.20), then the storyboard WRITER (full content-engine-style shot list: per-shot narrative caption + Expression + Mood + cut), then UI route selector, then grok + Seedance routes.
- 2026-06-22 — Phase 0 done (per-panel Seedance live on VPS). Planned coverage architecture; locked: coverage = new mode, grok route first. Phase 1 next.
- 2026-06-22 — Phase 1 done + proven. New module `storyboard/coverage.py` (directive + parser + reference-chaining gen + auto-build cast + CLI) and `tests/test_coverage.py`. bot.py / image_client.py / pipeline_executor.py all untouched. Proof: Dragon Rider mini-scene (~$0.65), matched angles confirmed; fixed an invented-second-person failure on tight face recomposes + a 2D/cartoon style-drift (added STYLE LOCK to every frame). Repo .env ANTHROPIC_API_KEY is DEAD (401) — directive Claude path runs on the VPS via the tenant Kie gateway, not locally.
- 2026-06-22 — COVERAGE NOW VISIBLE IN THE APP (Ryan's ask). New standalone runner `storyengine/backend/scripts/coverage_to_app.py` runs coverage for a video's scene on the VPS (tenant Claude via `get_text_client_for_tenant`, tenant Kie key for images), uploads frames to **Supabase Storage** (`STORAGE_BACKEND=supabase` — the backend has NO Drive OAuth creds for a standalone script), and INSERTs them as new `assets` rows (image_index 100+, generation_method='coverage', masters→hero_shot). Additive + idempotent (re-run deletes only prior coverage rows for the scene); the video's 23 original rows untouched. `--reuse` uploads frames already on disk without regenerating. Scene 1 of "Dragon Rider Off the Cliff" DONE: 12 photoreal frames (3 moments × 4 angles) stored + verified reachable. Two runtime fixes found live: direct-Anthropic default model id `claude-sonnet-4-20250514` 404s → pass `claude-sonnet-4-6`; parser made tolerant of `- MASTER WS:` (no brackets / multi-word shot types). NEXT: Ryan confirms scene 1 in the app, then run scenes 2-3 (`--scene 2`, `--scene 3`). Then Phase 2 (animate the coverage frames).
