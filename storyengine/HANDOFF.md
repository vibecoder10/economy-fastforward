# HANDOFF — 2026-07-21 — DvsU "Every US Strategic Bomber Ever Built" (video #1) + video #2 plan

## TL;DR — START HERE (fresh thread)
First DvsU customer video, driven via MCP under a $10 cap. **Scripts (23, passed the seeded law)
and voice ($5.47) are DONE and good.** Images are **NOT ready — DO NOT RENDER**: 22/23 generated,
but the no-reference obscure prototypes rendered as the WRONG AIRCRAFT (see below). Along the way,
4 real static-docu prod bugs were fixed + deployed (parallel gen, timeout, dead import, scene-scoped
regen). **Immediate next task: visual audit all 23 images → re-render the wrong ones with correct
reference photos → then render MP4 + thumbnail.** Video #2 uses the grounded pipeline (plan below).

### ⚠ THE IMAGE ACCURACY PROBLEM (why we stopped)
Reference-backed common aircraft (XB-15, B-17, B-52, B-24, B-29…) render CORRECTLY — clean
white-studio side profiles of the right plane. But machines with **no auto-found reference photo**
— the flying-wing prototypes especially — render as **generic conventional bombers, i.e. the wrong
aircraft**. CONFIRMED wrong: scene 8 (Northrop XB-35 flying wing → conventional tailed bomber),
scene 13 (Northrop YB-49 flying wing → conventional 4-tail aircraft). Likely also wrong: scene 9
(YB-35), and any other no-reference machine. Root cause: `static_docu` auto-sources a reference
(Wikipedia lead image → Commons), and when it finds/verifies none it falls back to GPT
text-to-image, which hallucinates a generic bomber; vision-QA can't verify a machine it has no
reference for, so it ships it flagged. This is the DvsU accuracy failure ("audience knows every
rivet"). **Fix path:** audit all 23 (download Drive image_urls, view them); for each wrong one,
find a CORRECT reference photo (Wikipedia has good XB-35/YB-49/YB-35 photos) and re-render JUST that
scene image-to-image (`images(video_id, scene=N)` now targets one scene, post-deploy 2d54d6f). Also
minor: facing direction (some left, some right) + dimensions (1672×941 vs 1280×720) inconsistent.
Scene 15 (Convair YB-60, no-ref) failed then a regen spun 7 min → killed via DB (may linger till a
backend restart). **PROCESS LESSON: visually verify every image (download + view) BEFORE declaring
done — the CLAUDE.md Visual Output Verification Rule. Do not assume a `git push` deployed — confirm
the running code changed (a push does NOT restart the backend; Ryan must `se deploy`).**

- Video: `fc73860c-a9af-444f-95a5-7f86d60503e0` · tenant `561b872d-7b73-45e3-9c44-7f30c3566eda`
  ("Designed Vs Used") · render_mode `static_docu` · 23-machine bomber roster.
- Working branch: `claude/dvsu-channel-story-engine-hzyts1` · **PR #457** (push commits to update it).
- Deep logs: `tasks/dvsu-bomber-loop.md` (live loop state + ledger) · `tasks/dvsu-finish-plan.md`
  (strategy + video #2 method) · this file (session-to-session handoff).

## How to connect (another session)
- **MCP server** `storyengine-dvsu` is registered in user config → `https://storyengine.dev/api/mcp`
  (native tools `mcp__storyengine-dvsu__*`: build, images, render, thumbnail, voice, get_video,
  get_ledger, submit_script, submit_research, etc.). `claude mcp list` = √ Connected.
- **Agent token** (DvsU-scoped, keep alive — Ryan's instruction, do NOT revoke): plaintext in
  `scratchpad/.dvsu_agent_token_user` (that session's scratchpad; ephemeral). Re-mint any time via
  Supabase: `INSERT INTO agent_tokens (tenant_id,name,token_hash) VALUES ('561b872d-…','<name>',
  sha256('se_agent_'+token_urlsafe(32)))`; use `Authorization: Bearer se_agent_<secret>`.
- **DB**: Supabase MCP `execute_sql`, project `wrromlupsmyzrrcqlucn` (this IS prod). Read/write.
- **Paid verbs**: 2-step (call w/o confirm_token → quote; call again with it → run). Static-docu
  quotes OVERSTATE ~10× (generic-coverage math): real = images $0.03/scene @1K, thumbnail $0.05,
  voice $0.30/1k-char, render compute-only. Verify real spend in `generation_ledger` (note: static
  images + research/script Claude are NOT ledgered — use code prices).

## DEPLOY MECHANISM (critical — learned the hard way)
- **No SSH from the cloud sandbox; keys are `enc:`-encrypted (no local Kie/ElevenLabs use).**
- **Pushing to `main` does NOT auto-deploy** — the StoryEngine backend (uvicorn) keeps running old
  code until restarted. There is no auto-deploy cron/CI/hook.
- **To ship code: push to main, then Ryan runs `scripts/se.sh deploy <name>` on his Mac** (git pull
  + backend restart). That's the only path. A restart kills in-process background tasks (honor the
  VPS coordination rule / deploy.lock). Ryan authorized: "you can always push to production."

## Video #1 — state + how to finish
Status `ready_for_images` (review gate). Scripts 23/23 (`agent_submitted`, passed seeded 76-law
critique, 0 violations) ✅. Voice 23/23 (Nathaniel-C, QL-46) ✅. Images 22/23 present but **several
are the WRONG AIRCRAFT** (see "IMAGE ACCURACY PROBLEM" above) — **NOT render-ready**. Scene 15
(YB-60) has no image at all.
**Finish steps (in order):**
1. **Visual audit all 23** — `SELECT scene, image_url FROM assets WHERE video_id=… AND
   generation_method='static_docu' AND image_url IS NOT NULL ORDER BY scene`; download each Drive
   url (curl `-L` on `uc?id=…&export=download`), downscale (Pillow — `pip install Pillow`; no
   PIL/imagemagick/ffmpeg preinstalled) to <256KB, and VIEW each. Produce a right/wrong list.
2. **Re-render the wrong ones with a correct reference**: for each wrong/missing machine, find a
   real reference photo (Wikipedia article lead image is best), then `images(video_id, scene=N)`
   (quote→confirm, ~$0.03/scene, targets ONE scene post-2d54d6f). If auto-sourcing keeps failing
   on an obscure machine, the reference may need to be seeded into `static_reference_cache`
   (tenant_id, machine_key, hosted_url, source_url) so the render goes image-to-image from it.
   `machine_key = _normalized_unit_code(name)` (e.g. XB-35→`XB35`, YB-49→`YB49`, YB-60→`YB60`).
3. Only once all 23 are the RIGHT aircraft in the white-studio style: `build(video_id)`
   (quote→confirm) → finish phase renders Ken Burns MP4 + thumbnail (~$0.10). (`render` verb alone
   is blocked for static_docu — go via `build`.)
4. Download MP4 + thumbnail; **visually verify** + review vs Anton's rubric
   (`storyengine/notes/dvsu-paragraph-rubric.md`).
Spend so far ~$6.1 real / $10 cap (voice $5.47 + ~$0.66 images). Re-renders ~$0.03 each.

### IMPORTANT caveat about video #1's scripts (Ryan is aware)
Scripts were **agent-written + fact-checked by agents + submitted via `submit_script`** — which
gates on the *prose critic*, NOT the platform's research→evidence→claim_map grounding gate. So the
facts are checked but NOT bound to stored verified sources; the platform's Research tab shows "NOT
RUN" for 15 machines. Ryan approved finishing #1 this way. **Video #2 must use the real grounded
pipeline** (below).

## Bugs fixed + deployed this session (all in static-docu path — likely why no DvsU video ever
rendered end-to-end before)
- `_KIE_CLAUDE_URL` dead import in `static_docu._vision_confirms` (C43 removed the symbol) — crashed
  ALL static image gen. Fixed: use `KIE_CLAUDE_BASE_URL` env in the fallback branch. (main 1da893c)
- Serial image gen → **bounded-parallel** `asyncio.gather` Semaphore(6). (main 966adaf)
- **Per-scene 300s timeout** (a Kie render poll hung 61 min on a no-ref machine, blocking the batch).
  (main 5b7c25c)
- **Scene-scoped static regen**: `run_coverage_images` now routes static_docu → static path with
  `only_scenes` (was mis-wired to generic coverage); + `run_storyboard_sheet` refuses for
  static_docu (Ryan: storyboards don't apply to this channel — frontend button-hide still TODO).
  (main 2d54d6f)
All on main; deployed via Ryan's `se deploy`. py_compile clean; no venv in sandbox so full pytest
not run — **run `cd storyengine/backend && ./venv/bin/python -m pytest tests/ -q` on the Mac.**

## Video #2 plan (Ryan approved — "agent-researches → inject as VERIFIED → platform grounds")
Full method in `tasks/dvsu-finish-plan.md` §"VIDEO #2 PLAN". Summary:
1. Agent researches each machine (real WebFetch, per-fact source URLs, adversarial fact-check).
2. Inject as the platform's evidence per machine — `machine_raw_source_packages[key]` (≥6 traceable
   verbatim excerpts, ≥2 URLs, ≥1 Tier-1/2, source_capture_method, source_variant_selection,
   4 required Anton slots distinct) + `machine_research_cards` row (schema_v3, evidence_segments).
   Exact contract mapped in the audit (research-schema). Inject via jsonb_set/upsert
   (non-destructive, roster-snapshot guard) — the per-machine `/machine-research-one` route is
   session-JWT-only (agent token can't reach it, by design). Result: each machine reads **VERIFIED**.
3. Ground the script against that evidence via claim_map so it clears the FULL `_run_static_script_
   hold` gate (two-source numeric grounding QL-18/19), not just the prose critic.
4. Then voice → images (now parallel) → render.
**DE-RISK on ONE machine first** (XB-15) before a full roster. **Blocked on: a title for video #2.**

## Open items / TODO
- [ ] **Video #1 image accuracy (BLOCKER):** visual-audit all 23 → re-render wrong-aircraft
      scenes (≥ 8/XB-35, 13/YB-49, prob 9/YB-35, 15/YB-60-missing) with correct references →
      then render MP4 + thumbnail. Do NOT render with wrong aircraft in it.
- [ ] Deeper fix (channel-wide): improve `static_docu` reference-sourcing for obscure/no-reference
      machines (flying wings, prototypes) so it doesn't fall back to hallucinated text-to-image —
      OR gate no-reference scenes to require an operator-supplied reference before render.
- [ ] Frontend: hide the "Generate storyboards" action for static_docu channels (backend already
      refuses; UI still shows the button).
- [ ] The DvsU "writer gap": the platform's OWN research→script writer went 0/3 on this video —
      prove/close it so video #2's grounded pipeline passes cleanly (de-risk step above).
- [ ] DvsU quality-law seed (76 rows) is LIVE (done this session); the C46c/C46e live-verify
      checklist items (Most-Hated gate, QL-66 thumbnail advisory, channel-pattern Confirm/Retire)
      still owed — see `tasks/live-verification-queue.md`.
- [ ] Agent token: Ryan pasted one in chat earlier ("claude", id 0e2f8362) — rotate when convenient.
