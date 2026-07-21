# HANDOFF - 2026-07-21 - The filter war ended: nano previews, GPT pictures, doctrine locked in stone

## State
- Prod: 30646ced deployed, healthy. main == origin == local. All work committed and live.
- BOTH PocoAPoco videos have COMPLETE storyboards:
  - El Mercado (65a8021e-eafa-4cff-94dc-31982ae7b63d): 16/16 boards. Ryan ruled its sheets stay as-is (drawn pre-balanced-chunking; minor picture-anchor offset accepted).
  - Spanish Class (cd5d2883-427e-4bfb-854d-8849d025d444): 18/18 boards. b5 was the first-ever nano board (landed first try after 14+ GPT rejections).
- Night's spend: roughly $2-3 total in landed sheet draws; every rejection cost $0.

## The final architecture (locked, deployed, documented)
- ALL storyboard sheets draw on nano-banana-2 (SHEET_DRAW_MODEL in coverage_to_app.py, no_gpt_fallback=True - a nano failure can never reroute onto the filtered GPT endpoint). Uniform sketch layer, no OpenAI moderation. NOTE: nano leans photoreal vs the 3D-cartoon channel style - acceptable for previews, tune later if Ryan wants.
- Real per-shot PICTURES stay GPT Image 2, now with up to 2 FREE re-rolls on zero-cost filter rejections before the nano fallback. Discovery: the GPT-with-refs path (what pictures use) had NO nano fallback at all before 30646ced.
- Belt-and-suspenders, all deployed: hard 6-panel balanced sheets (sheet_chunk_sizes = one boundary source for chunking AND picture anchoring), caption-free sheets, prop/brand/gesture neutralizers (preview set + LOCKED LOCATION now neutralized too), 4-class free retry ladder (moderation 400 / sensitive 422 / Kie 500 / ref-fetch), auto-sweeper (2 spaced passes over missing boards + dictionary escalation on sweep 2), per-board error surfacing (scripts.storyboard_errors + red chips in Scenes UI), text-free cast-generation prompts, vps-deploy.sh refuses to deploy over active generations without --force.
- The law: storyengine/docs/SHEET-MODERATION-LAW.md (10 rules + 4 ops rules, commit-level evidence).
- Both cast references are clean text-free sheets (Ryan drive id 1UpoVF9taFoWBtT7PIkwREHPZYhc-IgOF, Vanessa 1C91qU57ScKkGXmsw_8STsKXN1kC8xNbB), installed in the channel profile (locked) and both videos.

## Next actions (start here)
1. Ryan reviews both videos' storyboards in the UI (the gate), then Generate Pictures - El Mercado first. Pictures now have the re-roll + nano net; expect smooth runs.
2. Restart El Mercado's interrupted pictures run if not already done (skip-if-done keeps drawn frames).
3. Optional polish: tune nano sheet style adherence (previews lean photoreal vs the 3D-cartoon look).
4. Optional: frontend already shows error chips; verify visually on a real blocked board when one occurs.

## Open threads (carried from 2026-07-20, still open)
- Seedance live clip test (~$0.60) - Spanish video now AT pictures-ready; payload fix deployed but unproven.
- billing.py LIMIT-1-no-ORDER-BY x3; SSE stream home-tenant bug; OAuth wrapper for claude.ai Connectors; MCP confirm_failed error; research/script ledger rows; agent_tokens.created_by; voice fixes stash; youtube_quota toordinal bug (STILL spamming logs); UX papercuts.
- Ryan owes: rotate the agent token pasted in chat; Stripe price naming; VPS password rotation.
- Cast upload dropzone (b280fe13) never live-verified end-to-end with a real 200 (backend deployed since - quick UI check someday).

## Gotchas learned this session (full detail in memory: storyengine-storyboard-sheet-moderation)
- OpenAI two-stage moderation: input blocks deterministic, OUTPUT blocks random per-draw - a composite sheet is judged whole, one borderline panel poisons the board. That asymmetry is WHY previews moved to nano.
- The filter reads text INSIDE reference images, and i2i is stricter than t2i.
- A staged prop gets DRAWN into every panel ("a knife on the cutting board" in FIXED SET = knife in 30 panels); wording swaps don't help when the drawn IMAGE is the trigger (utensil close-up still renders as a knife).
- Kie's failCode in task records is the UPSTREAM OpenAI error; Kie docs list only envelope codes. Kie also throws transient 500s ("Internal Error") and ref-fetch failures under load - all 0-credit, all retried free now.
- kill -9 restarts strand generation_claims rows AND leave ghost active_tasks counters (only a restart clears the counter). Deploy guard now blocks deploys over active tasks.
- Two Claude sessions on one box WILL collide (a deploy killed a paid pictures run; a restart killed a board ladder). The deploy guard helps; coordination discipline still required.
- se token is owner-tenant only; client-tenant API calls need the X-Active-Tenant header.
- Per-board redo: POST /api/pipeline/storyboard-images/{vid}?scene=S&beat=B - redraws ONE board from the SAVED plan, never re-plans. Scene-level (no beat) RE-PLANS and wipes the scene's boards.
