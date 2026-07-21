# HANDOFF — 2026-07-21 — DvsU "Every US Strategic Bomber Ever Built" (video #1) + video #2 plan

## TL;DR
First DvsU customer video driven to near-complete via MCP under a $10 cap. **Scripts (23,
passed the seeded law) and voice ($5.47) are DONE; images 22→23/23 (scene 15 regenerating);
then render + thumbnail = finished MP4.** Along the way, 4 real prod bugs in the static-docu
path were fixed and deployed. Video #2 will use the proper grounded pipeline (plan below).

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
critique, 0 violations). Voice 23/23 (Nathaniel-C, QL-46). Images 22/23 → **scene 15 (Convair
YB-60) regenerating** (transient no-URL failure; retry via targeted regen).
**Finish steps (native MCP verbs):**
1. Confirm scene 15 has an image: `SELECT ... FROM assets WHERE video_id=… AND scene=15 AND
   generation_method='static_docu' AND image_url IS NOT NULL`. If still missing, re-run
   `images(video_id, scene=15)` (quote→confirm; ~$0.03).
2. `build(video_id)` (quote→confirm) → finish phase: render Ken Burns MP4 + thumbnail (~$0.10).
   (`render` verb alone is blocked for static_docu — go through `build`.)
3. Download MP4 + thumbnail from storage; **visually verify** every machine (Visual Output
   Verification Rule) + review vs Anton's rubric (`storyengine/notes/dvsu-paragraph-rubric.md`).
Spend so far ~$6.1 real / $10 cap (voice $5.47 + ~$0.66 images).

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
- [ ] Finish video #1: scene 15 image → render → thumbnail → visual verify.
- [ ] Frontend: hide the "Generate storyboards" action for static_docu channels (backend already
      refuses; UI still shows the button).
- [ ] The DvsU "writer gap": the platform's OWN research→script writer went 0/3 on this video —
      prove/close it so video #2's grounded pipeline passes cleanly (de-risk step above).
- [ ] DvsU quality-law seed (76 rows) is LIVE (done this session); the C46c/C46e live-verify
      checklist items (Most-Hated gate, QL-66 thumbnail advisory, channel-pattern Confirm/Retire)
      still owed — see `tasks/live-verification-queue.md`.
- [ ] Agent token: Ryan pasted one in chat earlier ("claude", id 0e2f8362) — rotate when convenient.
