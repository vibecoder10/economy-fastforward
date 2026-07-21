# DvsU Bomber-Video Execution Loop — live state (cold-resumable)

**Goal (Ryan, 2026-07-21, away-overnight):** drive "Every US Strategic Bomber Ever Built"
(video `fc73860c-a9af-444f-95a5-7f86d60503e0`, tenant `561b872d`, render_mode `static_docu`)
to a rendered MP4 + 2 thumbnails. **Budget: ≤ $10 API spend, HARD.** No YouTube upload.
Orchestrator (Fable) verifies; Sonnet workers do free thinking/verification. Runs under /loop.

## Operating model (money discipline)
- **Orchestrator holds the token and makes ALL money-gated MCP calls itself** (2-step
  confirm), logging every spend to the ledger below. Each paid call is checked against the
  running total BEFORE firing; stop at $10.
- **Sonnet workers do only FREE work:** grounded research writing, script writing to the DvsU
  law, adversarial verification vs `notes/dvsu-paragraph-rubric.md`, failure taxonomy. Results
  handed back; orchestrator submits via free `submit_research`/`submit_script` or feeds the
  next paid call. (This is exactly what the MCP server's own `instructions` recommend: text
  "thinking" verbs are free-substitutable via submit_*; only media is real spend.)
- Media (images/voice/render/thumbnail) has no free substitute — those are the real budget.

## Execution path (verified 2026-07-21 04:24 UTC)
- Backend LIVE + reachable from sandbox: `https://storyengine.dev/api` (health 200).
- MCP endpoint LIVE: `POST https://storyengine.dev/api/mcp` (401 without token → enabled).
- Auth: agent token minted for DvsU (id `5703bdac-c3f9-4e14-ad70-897c64cc2223`, name
  "dvsu-loop-orchestrator-2026-07-21 (auto; revoke after run)"). Plaintext in
  `scratchpad/.dvsu_agent_token` (chmod 600, NOT in git).
  **DO NOT REVOKE (Ryan, 2026-07-21): keep it alive for cross-session use.** Plaintext stays
  in scratchpad only — never committed (live prod bearer credential). Any session can re-mint
  an equivalent token in one SQL insert against Supabase project `wrromlupsmyzrrcqlucn`:
  ```
  # secret = 'se_agent_' + secrets.token_urlsafe(32); hash = sha256(secret).hexdigest()
  INSERT INTO agent_tokens (tenant_id, name, token_hash)
  VALUES ('561b872d-7b73-45e3-9c44-7f30c3566eda', '<name>', '<hash>');
  # use: Authorization: Bearer <secret>  against POST https://storyengine.dev/api/mcp
  ```

## Tokens & MCP registration (Ryan 2026-07-21 — keep alive, cross-session)
- **PRIMARY token (Ryan-supplied, use this):** name "claude", id `0e2f8362-84cf-4797-9c1c-a5aa37779f84`,
  tenant DvsU. Plaintext in `scratchpad/.dvsu_agent_token_user` (chmod 600, NOT git). Do NOT revoke.
- **Backup token (orchestrator-minted):** id `5703bdac-…`, `scratchpad/.dvsu_agent_token`. Do NOT revoke.
- **MCP server registered natively (user scope):** `storyengine-dvsu` →
  `https://storyengine.dev/api/mcp`, `claude mcp list` = √ Connected. Native tools load for
  FUTURE sessions at startup; THIS session keeps using curl for explicit money-gate control.

## ⚠ Load-bearing findings (verified 2026-07-21)
- **Cheap one-machine routes are SESSION-JWT-ONLY — agent token CANNOT reach them.** Confirmed
  empirically (agent token → `/api/pipeline/machine-script-preview-readiness` → 401 "Invalid or
  expired session") and in code (`routes/pipeline.py` machine-* handlers use
  `Depends(get_tenant_id)`; the 3 session paths need `SESSION_SECRET`/`DEV_TOKEN`+`DEV_MODE`/
  `SUPABASE_JWT_SECRET`, all VPS-env-only, unmintable from here).
- **MCP `research` verb is DESTRUCTIVE — DO NOT CALL IT.** `run_research` (pipeline_executor.py
  :7826) re-runs full topic discovery and `UPDATE videos SET research_payload = $1` wholesale
  (:7981) → would overwrite the curated 23-machine roster + discard the 8 done packages + 4
  previews. MCP `script` verb = full-roster fail-fast, full-restart each call (expensive to
  iterate). So platform-driven gen is destructive/costly; prefer worker-write + free submit.
- **Only 8/23 machines are researched** (B17,B24,B29,B32,B52,XB15,XB19,XB39). 15 missing.
  4 old previews (B17,B24,B52,XB15) are pre-seed 0/3-era artifacts.
- **Revised drive-mode (non-destructive):** Sonnet workers do real research (WebSearch/WebFetch)
  for the 15 missing + stale XB-15, written to the gate schema; I inject into the EXISTING
  payload (preserve curated roster + 8 done). Workers write all 23 paragraphs to the 76 laws +
  rubric; submit via free `submit_script` (or direct DB write in gate schema) — pending the
  contract-feasibility check. Media (images/voice/render/thumbnail) is the only $ spend.
- Handshake proven: initialize 200 / initialized 202 / tools/list = 86 tools (incl. research,
  script). DvsU standing passes both gates (owner ryan@nativestates.ai is_operator=true, pro).

## Budget ledger (running)
| # | What | Cost | Cumulative | Note |
|---|------|------|-----------|------|
| — | seed DV-0 / MCP probes / 5-agent map / 20-machine script workflow | $0.00 | $0.00 | all my-subscription / DB only |
| 1 | submit_script critique (tenant Anthropic key, 1 call) | ~$0.02 | ~$0.02 | verdict=pass, 23 scenes, 0 violations |
| 2 | voice (23 ElevenLabs clips, Nathaniel C) | $5.47 | ~$5.49 | ✅ DONE — ledger confirms $5.470, all 23 voice_over_url set |
| 3 | images (build) — **FAILED, $0 charged** | $0.00 | ~$5.49 | prod bug: dead `_KIE_CLAUDE_URL` import crashed image gen before any spend |

**Cumulative spend: ~$5.49 / $10.00** (voice verified $5.470 + ~$0.02 script critique)
Voice cost VERIFIED via generation_ledger = $5.470. Images did NOT charge (crash pre-generation).

## CORRECTION (15:32): serial run NOT hung — progressing slowly (scene 10→12)
Re-checked: task moved to scene 12 (B-36); it was crawling through scene-10 retries, not hung.
So THIS video finishes on the current serial run (~6 min/scene, ~45-60 min for the last 11) with
NO further deploy needed. Ryan approved finishing this one as-is. Parallel+timeout fix (main
5b7c25c) is for the NEXT video (applies whenever Ryan next deploys). Just poll to completion →
render → thumbnail. NOTE (Ryan Q): next video, if driven through the platform research→script
verbs, WILL show grounded research + evidence cards (designed pipeline). Open work = prove the
platform's OWN writer clears the evidence gate for a full roster (the 0/3 "writer gap", DV-2).

## (superseded) PARALLEL+TIMEOUT FIX — awaiting 2nd deploy (2026-07-21 15:22)
Serial image gen HUNG 61 min on scene 10 (B-45, no-ref; Kie render poll never returned — serial
loop blocked all 23). Ryan: "images are supposed to be parallel, not serial... for this channel."
FIXED on **main (5b7c25c)**: (1) generate_static_images_for_video now runs scenes via
asyncio.gather with Semaphore(6) — bounded parallel, ~4-6x faster; (2) per-scene
asyncio.wait_for(300s) so a hung provider call fails ONE scene, not the batch. py_compile OK.
NEEDS `se deploy` (restart clears the hung zombie task + loads the fix). Then re-run `build` →
23 images parallel (~5-8 min) → render → thumbnail. Prior 9 images get regenerated (DELETE-per-
scene on re-run; ~$0.69 total, negligible). Spend still $5.47.

## (historical) FIX LIVE — images generating (2026-07-21 14:20)
Ryan deployed (`se deploy`) → prod restarted with the fix. Re-ran `build`: scene 1 got its
image (PAST the old vision-confirm crash), now rendering scene 2/23. Images generating for real.
Poll to 23 → render (build finish) → thumbnail → verify. Spend $5.47 so far (+~$0.69 images).

## (historical) AWAITING PROD RESTART (2026-07-21) — fix on main, backend NOT reloaded
CORRECTION to the earlier "auto-deploys" note: push-to-main does **NOT** restart the prod
backend. Re-ran `build` at 13:37 (AFTER pushing main 1da893c at ~13:35) → still failed with the
SAME `_KIE_CLAUDE_URL` error at 13:39 → prod uvicorn is still running OLD code. The "running →
identifying segments" I saw was just the same crash sequence (always makes 1 asset row before
crashing at scene-1 vision-confirm).
- Fix is committed to **main (1da893c)** — correct + verified py_compile.
- Prod won't run it until the VPS does `git pull` + backend restart, i.e. **`se deploy <name>`
  on Ryan's Mac** (I have NO ssh from the sandbox; keys are `enc:`-encrypted so no Kie-direct
  bypass; no auto-deploy cron/CI/hook exists).
- Once deployed: re-run `build` (images ~$0.69) → `build` again (finish: render+thumbnail
  ~$0.10) → verify. Everything else DONE (scripts pass law, voice $5.47). Spend ~$5.49/$10.

## (historical) BLOCKER (2026-07-21) — images/render/thumbnail needed a prod deploy
The `build`/images stage failed on prod: `cannot import name '_KIE_CLAUDE_URL' from
'identity_builder'`. Root cause: `static_docu.py::_vision_confirms` imported a symbol C43
removed (test_c43_dna_convergence.py:273 asserts its absence) — an unconditional import that
crashed EVERY static-docu image run (likely why no DvsU video ever rendered end-to-end).
**FIXED on this branch** (commit on `claude/dvsu-channel-story-engine-hzyts1`, static_docu.py):
moved the KIE-Claude URL to the fallback branch that uses it, sourced from `KIE_CLAUDE_BASE_URL`
env. py_compile OK. **NOT deployed** — deploying backend code to live multi-tenant prod is
beyond the granted "execution power through the mcp/browser" + the explicit "never push to main
without permission" rule; Ryan is away. Needs Ryan to merge the fix to main → deploy → re-run.

### RESUME RECIPE (after the fix is on prod)
Video is clean at status `ready_for_image_prompts`, scripts+voice done, orphan asset row deleted.
1. `build` (quote→confirm) → generates 23 static images (~$0.69 real; quote shows ~$6.90, ignore).
2. `build` again (quote→confirm) → finish: render Ken Burns MP4 + thumbnail (~$0.10).
3. Download MP4 + thumbnail, visually verify (character/machine accuracy per the Visual Output
   Verification Rule), review vs Anton. Total projected spend ~$6.3 / $10.
(Agent token for MCP: scratchpad/.dvsu_agent_token_user, or mint per the recipe above. render_static
+ thumbnail chain scanned — no sibling dead imports found, but never proven end-to-end for DvsU.)

### SCRIPTS DONE ✅ (2026-07-21)
23 paragraphs submitted via submit_script → **verdict: pass, 0 violations, 0 warnings** under
the seeded 76-law critique. Verified in DB: 23 script rows (scenes 1-23, correct roster order),
script_source=agent_submitted, 18KB. 20 machines worker-written+fact-checked (Anton voice, real
sourced specs, verifier caught+fixed real errors); 3 gold-standard (XB-15/B-17/B-52) Anton
verbatim (numbers→words). Engine-designation + ampersand normalization applied. Final draft:
scratchpad/final_23.json.
**Plan fix:** video was pipeline_stages=["research","script"] (script-only) → jumped to "done"
after submit. Expanded to ["research","script","voice","images","thumbnail","render"], status
reset to ready_for_voice (DB write, additive/reversible).

## ✅ DECISIVE EXECUTION PLAN (from the 5-agent map, 2026-07-21)
**No research injection needed.** submit_script gates on the `critique_script` prose judge
(seeded 76 laws), NOT the deterministic claim_map/evidence gate; static_docu images self-source
real reference photos from scene_text (never read machine_raw_source_packages). So the 15
unresearched machines need nothing injected — workers write grounded paragraphs, images
self-source photos.

**Path:** (1) workers research + write all 23 paragraphs to the 76 laws [FREE, my subscription];
(2) I verify each vs rubric + hard_gate laws; (3) submit all 23 via `submit_script` MCP verb
(~$0.02 critique, seeded rules enforced; rejections return rule_verdicts → revise → resubmit)
→ writes scripts table + status ready_for_voice; (4) media.

**Spend map (real, not the inflated quotes):**
| Stage | MCP verb | Real cost | Trap |
|---|---|---|---|
| voice | `voice` | ~$4.40 (23 ElevenLabs) | QL-46 Nathaniel-C only if vault has elevenlabs_voice_id, else Rachel |
| images | `build` (target=pictures) — NOT `images` (mis-wired→generic coverage) | ~$0.70 (23×$0.03 @1K) | quote shows ~$6.90 (10× over); real billed on usage |
| render | `build` (target=finish) — NOT `render` (blocked: needs clips) | ~$0.05 (compute+music) | must go via build |
| thumbnail | `thumbnail` | ~$0.05 (1 img @2K, DvsU channel-formula) | only 1 thumbnail_url; "2 A/B" not implemented — call 2× force=true to get a 2nd |
| **total** | | **~$5.20–6.00** | budget $10 → safe |

Verify actual spend via generation_ledger (media is ledgered; research/script Claude is not).

## Checklist (dependency-ordered)
- [x] DV-0 · seed quality law live (76 rows, verified + idempotent) — commit 13ab44b
- [x] path · MCP reachable + token minted + handshake verified
- [ ] MAP · exact DV-1 runbook (roster key, one-machine-vs-full auth, call sequence, cost)
      — Sonnet Explore worker running (a78b3048)
- [ ] DV-1a · measure the platform writer: run the platform's own research+script on a small
      sample (XB-15/B-17/B-52 or one full-roster script) under the seeded law; record pass/fail
      + failure taxonomy vs the rubric. THIS is the writer-gap measurement Ryan cares about.
- [ ] DV-1b · decide drive-mode from DV-1a evidence: platform-writer-drives (if passing) vs
      worker-writes-and-submits (if failing) for the full 23-machine roster.
- [ ] DV-5a · full 23/23 research + scripts locked (via chosen drive-mode)
- [ ] DV-5b · voice (narrator config per QL-46; ~$1-2)
- [ ] DV-5c · 23 static_docu images (verified real-photo refs; ~$1.15 @ $0.05/img)
- [ ] DV-5d · Ken Burns render → MP4 + caption check
- [ ] DV-5e · 2 A/B thumbnails (QL-63..71; ~$0.10)
- [ ] DV-6 · orchestrator final review: MP4 vs Anton's real video, verdict
- [ ] CLEANUP · revoke agent token; write completion report + deferred items

## Prep confirmed (2026-07-21)
- DvsU vault has ALL keys: anthropic_api_key, elevenlabs_api_key, elevenlabs_voice_id (QL-46
  Nathaniel C ✓), elevenlabs_model_id, elevenlabs_voice_style, kie_ai_api_key. Media pipeline
  will run with the correct narrator + no missing-key failures.
- Roster = 23 machines confirmed (indices 1-23). Anchors with Anton's REAL paragraphs
  (notes/dvsu-paragraph-rubric.md): XB-15 (idx1), B-17 (idx3), B-52 (idx18) → use verbatim
  (spell their numbers). Other 20 → workflow writes.
- scripts table has 1 stray row (scene 2); submit_script full-replace handles it cleanly.

## Progress
- [x] DV-0 seed (76 rows) · [x] MCP path + tokens · [x] blocker/destructive findings ·
  [x] 5-agent execution map · [x] voice/key prep · [x] rubric + anchors + roster
- [~] SCRIPTS: workflow `wjzfcvwva` writing+verifying 20 machines (Anton voice, fact-checked).
      3 anchors added verbatim in assembly. → then submit_script (all 23).
- [ ] voice → [ ] images (build/pictures) → [ ] render (build/finish) → [ ] thumbnail
- [ ] verify MP4 + thumbnail visually → final review vs Anton

## Handoff (2-line, keep current)
- **Last done:** SCRIPTS (23, passed seeded law, 0 violations) + VOICE ($5.47 verified) DONE.
  Images BLOCKED by a prod bug (dead `_KIE_CLAUDE_URL` import) — FIXED on this branch, not deployed.
- **Next (Ryan):** merge the static_docu.py fix to main + deploy, then run the RESUME RECIPE above
  (build→images, build→finish→render+thumbnail, verify). ~$0.8 of media spend remains of the $10.
