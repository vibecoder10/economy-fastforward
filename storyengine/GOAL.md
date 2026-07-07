# GOAL - StoryEngine: the intelligent YouTube channel-growth machine

**Mission:** one chat. A creator talks to StoryEngine like they talk to Claude, and it runs the
entire faceless-YouTube loop for them on real data: study the competition, decide what to make,
produce the whole video end to end, publish it, measure how it did, and get smarter every week.
The chat is the command center; the Autopilot + intelligence engine is the muscle.

**Target (this year):** our first 10 customers actually using the product to grow real channels.

**Status note (2026-06-30):** the old GOAL was the "v2 director correctness pass" (unify the two
image pipelines, port director machinery into coverage). That work is mostly shipped (see
"Director pass - status" below), so this file is re-centered on the real frontier: turning the
chat into the conversational front-end for the automation engine we already built, and closing the
handful of genuine gaps. Prior plan preserved in `GOAL.md.bak-20260630-075433`.

---

## Where we are - most of the machine already exists

The closed loop runs today, much of it on autopilot:

**Ingest -> Understand -> Decide -> Produce -> Publish -> Measure -> Learn -> (back to Decide)**

- **Ingest:** daily background scrape of competitor channels -> `competitor_videos` with real
  VPH/views/age (`main.py:_auto_scrape_competitors`). [DONE]
- **Understand:** the distiller pulls per-video "DNA" (hook / retention / structure / thumbnail /
  villain) into `content_intelligence`; the advisor ranks best hook/thumbnail/title/timing/topics;
  `learning_extraction` ties title/hook/script patterns to real CTR. [DONE]
- **Decide:** Autopilot scores candidates (VPH 45% / freshness 35% / intelligence 20%, plus DNA,
  niche-pattern and learnings boosts) and can auto-launch the pipeline. [DONE, but buried in the
  Advanced tab - see Frontier]
- **Produce:** the 18-stage pipeline (script -> voice -> image prompts -> storyboard -> coverage
  images -> sound -> video -> thumbnail -> render) on the unified coverage path. [DONE; Ryan marked
  clips/voice/data/thumbnails off. Remnants: shot budget + a clip-motion proof.]
- **Publish:** content-driven SEO (`youtube_publish.generate_and_store_seo`) + upload to the
  creator's OWN connected channel. [DONE; upload proven end to end 2026-06-30.]
- **Measure:** daily YouTube Analytics sync pulls real CTR, impressions, retention, avg view
  duration onto `videos` (`main.py:_auto_sync_youtube`, `youtube_sync.py`). [DONE]
- **Learn:** `_auto_extract_learnings` mines winning patterns vs CTR into the `learnings` table.
  [DONE]

**The chat brain (today, 2026-06-30, commits a4991cc8..0ea3e5f1):** models a pasted outside video
on its REAL data (title/views/runtime/topic, not the creator's persona); full profile control
(add/remove competitors + edit channel name/niche/audience/look, writing to the real tables);
reads back the current setup AND live competitor performance with numbers; and behaves as a
flexible co-thinking partner (the saved channel is a default, not a cage). All proven on prod.

---

## The frontier: the intelligence command center

Key realization: the famous "10 ChatGPT prompts for faceless YouTube" workflow is the MANUAL
version of what Autopilot + distillation + learnings + analytics already do automatically on live
data. We are not missing the workflow. The two real moves are:

1. **Make the chat the conversational front-end to the engine we already built.** Today that
   intelligence lives in Advanced tabs (Autopilot / Competitors / Discovery / Learnings /
   Analytics) the user has to go click through. The command-center vision = let the chat DRIVE and
   NARRATE the loop (read it, run it, explain it) in plain conversation.
2. **Close the handful of genuine gaps** the workflow exposes (below).

### The 10-step workflow, slotted into the real system

| # | Workflow step | Where it lives in StoryEngine | Status |
|---|---|---|---|
| 1 | Competitor analysis | `_auto_scrape_competitors` + distiller `content_intelligence` + advisor + `_auto_analyze_competitor_titles` + `channel_intel` | EXISTS. Gap: content-gap finder, opportunity map, comment sentiment |
| 2 | Viral idea finding | `/discovery` ideas + Autopilot candidates (VPH-filtered, DNA-enriched) | EXISTS. Gap: per-idea monetization ceiling, emotional-hook label, "overdone" flag |
| 3 | Idea/title scoring | Autopilot `calculate_confidence_with_breakdown` (VPH/Freshness/Intelligence) | EXISTS, different axes. Gap: feasibility + monetization + competition-density axes; not exposed in chat |
| 4 | Transcript forensics | `distiller.distill_full_video_dna` (hook/retention/structure DNA) | EXISTS. Gap: transcript supply is flaky; chat modeling path doesn't read the DNA yet |
| 5 | Script writing | Script Bot + `engine_templates` + learnings injection + the 55KB ruleset | EXISTS |
| 6 | Thumbnail + title analysis | distiller `thumbnail_dna` (vision) + advisor best-thumbnail + Thumbnail Bot modeling | EXISTS (analysis + generation) |
| 7 | Hook engineering | distiller `hook_dna` + learnings hook patterns + Script Bot hook | PARTIAL. Gap: explicit 5-variation + retention-spike + click-off-flag step |
| 8 | VO + edit + b-roll | Voice Bot + Storyboard/Coverage (shot-by-shot) + Sound + Video Gen | EXISTS (we execute it, not brief a human) |
| 9 | Calendar + repurpose | Calendar tab (view) + Autopilot cadence + advisor `best_timing` | PARTIAL. Gap: strategic topic-sequenced planner; shorts/repurposing MISSING |
| 10 | SEO + post-video | SEO: `generate_and_store_seo` (EXISTS). Post-video: `_auto_sync_youtube` real stats + learnings loop (EXISTS) | Gap: chat-facing "diagnose why this underperformed and what to fix" |

### The real backlog (gaps only)

- **G1 - Content-gap + opportunity map (#1):** synthesize from the DNA we already store (what the
  niche's audience wants that competitors skip; where a new channel can enter and win). Comment
  sentiment needs new comment scraping - treat as optional.
- **G2 - Expose decision-making in the chat (#2/#3):** surface "what should I make next, scored and
  ranked" conversationally (Autopilot's scoring is buried in the Advanced tab), and add the missing
  axes (production feasibility, monetization, competition density).
- **G3 - Explicit hook engineering (#7):** a real step that writes 5 hooks, picks the strongest,
  places retention spikes at ~1/3 and ~2/3, and flags likely click-off lines.
- **G4 - Strategic calendar + shorts repurposing (#9):** a topic-sequenced 30-day plan (easy wins
  first, fatigue gaps) and a clips-to-shorts repurposing path.
- **G5 - Conversational post-video diagnosis (#10.2):** the analytics are synced; turn them into
  "here's why it underperformed and the one fix" in chat, feeding the learnings loop.
- **Director remnants (from the v2 pass):** **D1** per-scene shot budget (cap ~6-10 moments;
  today an 8-scene video can balloon to ~290 frames / ~$14 in images); **D2** the gated paid
  Scene-1 CLIP proof (motion / lip-sync / consistency in actual video - the one thing still
  unproven).

---

## Phases (the plan we execute against)

**Phase A - Surface the loop in chat (the through-line). [SHIPPED 2026-06-30, main @ fc476ad6]**
Let the chat read, run, and narrate the
existing engine: "what's working on my competitors" (done), "what should I make next" (drive
Autopilot candidates + scoring), "how did my last video do" (read the analytics sync), "what have
we learned" (read learnings), and run a modeled build. This unifies everything we already have
behind the command center. Mostly wiring, little new intelligence.

**Phase B - Idea -> score -> pick (G2). [SHIPPED 2026-06-30, main @ 101616f4]** The daily driver: pull real competitor winners, generate
ideas, score them (extend Autopilot's breakdown with feasibility/monetization), recommend the top
2 with the angle + the one differentiator, all in chat. Do before onboarding customers.

**Phase C - Close the loop in chat (G5 + G1). [SHIPPED 2026-06-30, main @ 5e8d898e]** Conversational performance diagnosis on synced
analytics ("low impressions vs low CTR vs low retention -> the fix"), and the content-gap +
opportunity map. This is what makes the product get smarter about THEIR channel every week - the
moat for "10 customers actually using it."

**Phase D - Depth (G3 + G4).** Explicit hook engineering; strategic calendar + shorts repurposing.

**Phase E - Director remnants (parallel, cheap-first).** D1 shot budget `[DONE 2026-07-02,
main @ 5e415b56]`: _coverage_shape is the per-scene budget (dialogue = one master-only frame
per turn + wide/cutaway, hard cap SCENE_FRAME_BUDGET=12; visual = 3 moments x 2-3 angles) AND
enforce_shot_budget trims the planner's output in CODE before image spend - proven live: the
planner ignored the prompt (16 moments/33 frames vs a 12/0 budget) and got trimmed to 12/12
with zero dialogue lines lost. Worst-case image spend per chatty 8-scene video drops from
~$14-20 to ~$5. REMAINING: the gated D2 Scene-1 clip proof (~$1-2) - Ryan drives via UI.

**Phase F - Chat asset intake ("drop it in the chat"). [ALL 6 SHIPPED + PROVEN 2026-07-02, main @ d52606fa]** Creators drop
files into the home chat and the chat files them into the engine (full plan approved 2026-07-02,
branch feat/chat-asset-intake). Decisions: CSV->queue first; autopilot drains the queue before its
own scored picks; locked cast on Profile/Visual Styles with a Lock toggle; ONE house script
template per channel.
- F1 intake layer: upload + parse (csv/pdf/text/image, chat_assets, mig 073) + producer awareness. `[done]` Proven on prod 2026-07-02: CSV + PDF uploaded via /api/chat/upload, rows stored+bound+Drive-backed, producer described both correctly and honestly said filing isn't wired yet.
- F2 production queue: CSV -> ordered calendar queue -> autopilot consumes queue-first (mig 074). `[done]` Proven on prod 2026-07-02: "queue these" chat op queued 3 CSV titles in order; calendar served them as the first slots; Build launched the front item; auto_produce_next held while in-flight/not-due and claimed the correct next item once due. Live proof caught + fixed: op belonged in the profile_ops schema, a swallowed elif, and soft-deleted videos blocking the lane.
- F3 verbatim user script: use a supplied script, skip generation (videos.script_source, mig 075). `[done]` Proven on prod 2026-07-02: PDF script -> chat op created the video with both scenes VERBATIM (ready_for_voice, user_supplied); run_script passed through without rewriting a word. FOLLOW-UP SHIPPED same day (main @ d196792e): unmarked scripts get a SEMANTIC scene split (one model call, one beat/machine/location per scene, guided by the locked channel segmentation, verbatim-guarded - any word change discards it for the word-count fallback). Proven: an unmarked 3-machine review split into exactly one scene per machine, text verbatim. Creator-marked SCENE headings still always win.
- F4 house script template: analyze an example, apply to every generated script (mig 076). `[done]` Proven on prod 2026-07-02: "remember this format" distilled real imperative format instructions (hook/structure/pacing/sign-off) and every new video carries them in script_system_prompt (verified). CAVEAT worth a follow-up: the brief_translator's own act/angle machinery competes with the template, so generated scripts follow it loosely, not strictly - to make the house format DOMINATE, inject it into the writer stage itself, not just the system prompt.
- F5 locked channel cast: uploaded sheets = brand assets, characters stage auto-skips (mig 077). `[done]` Proven on prod 2026-07-02: chat locked dropped sheets (vision named "Milo" from the sheet itself), run_characters imported + auto-approved + built the cast sheet with ZERO generation. Fixed live: media-proxy allowlist didn't cover chat uploads (vision/cast-sheet 404s).
- F6 channel format lock: visual_format locked + fed into creation defaults. `[done]` Proven on prod 2026-07-02: one chat sentence locked a 4-field format; a bare-title video defaulted to flat_2d.

Phase F remaining follow-ups (not blockers): make the house script FORMAT dominate the writer
stage (F4 caveat - it currently rides the system prompt and competes with brief_translator's own
act machinery); attachments in the video-scoped dock (home-chat only today); shorts repurposing
(deferred from G4).

**Sequencing:** A first (it ties the whole machine together and rides on today's chat work), then
B, then C. D and E run alongside as capacity allows. Each phase proven by a real run on prod, never
a self-test (the anti-rot rule that kept this project honest).

**Phase G - First customer: DvsU (Designed vs Used) profile build-out + beta. [IN PROGRESS 2026-07-07]**
Anton's channel (youtube.com/@designedused, monetized, 175 videos) is customer #1. He handed over a
10-doc standards package (source of truth: `Agent Vault/Projects/storyengine/designed-vs-used/`);
his only future input is a list of titles. Tenant 561b872d, static_docu render mode.
- G1 encode the standards: all six tenant prompt slots hand-written from the docs (script,
  research, thumbnail, video_motion, sound_curation, sound_generation) + profile fields +
  format_locked. `[done 2026-07-07 - live on prod, verified via /api/system-prompts: 6/6 CUSTOM]`
- G2 fixed narrator voice: vault->env wiring for elevenlabs_voice_id/model_id/voice_style
  (was silently ignored), multilingual-v2 pin + style honored in the client, .env defaults
  restored for tenants without overrides. `[done 2026-07-07, main @ 34f276c3, deployed +
  test_narrator_voice_wiring.py ALL PASS on prod]` OPEN: tenant has NO direct elevenlabs_api_key
  (Kie roster rejects custom voices) - Ryan decides whose key goes in before the beta.
- G3 beta test video "Most Hated Tanks by Their Own Crews Ever": walk gate by gate in the UI,
  cost ~$5-10 (needs Ryan's yes), judge against the package checklists + his real scripts.
  NOT uploaded to his channel without Ryan/Anton review. `[todo]`
- G4 production: Anton's first 3-5 real titles through the same flow; monitor 2-3 weeks;
  enhancements (thumbnail A/B via YouTube Experiments, autopilot scoring on his format table)
  only after baseline parity. `[todo]`

---

## Director pass - status (the prior GOAL, condensed)

The 2026-06-24 "two diverged pipelines" root cause is largely resolved. Coverage is the single live
image/clip path; legacy grid routes return 410; dead pages removed.

- Phase 0 (unify on coverage): DONE + deployed + publicly verified.
- Phase 1 (real data / dead-video pruning): DONE; remnants = own-channel ingestion + a one-time
  prod purge of old zero-view rows.
- Phase 2 (always-on channel intelligence): DONE (mig 066 `channel_intel`, rich brief every turn).
- Phase 3 (style detect -> recommend -> apply): DONE (proven universal: live-action -> realistic,
  animated -> pixar_3d).
- Phase 4 (length): PARTIAL - default anchors to the channel median; still owed: anchor on the
  SPECIFIC modeled video's runtime and unify with the model_video exact-runtime path.
- Phase 10 (Scene-1 storyboard acceptance gate): PASSED 2026-06-29 (distinct angles, story
  progression, locked cast/env/style across 36 frames). Diagnostic finding: the audit was stale;
  Phases 5/8/9 are effectively handled in coverage (downgraded to spot-check). The real remaining
  work is D1 (shot budget) and D2 (clip-motion proof) - carried into Phase E above.
- Render page + Upload page: DONE + proven (render stitched a 44-clip portrait MP4; SEO + per-tenant
  upload proven end to end, 2026-06-30).

---

## Reference - grok-imagine prompting rules (for the clip path, D2)

kie.ai gateway. Base `https://api.kie.ai`, `POST /api/v1/jobs/createTask`, `Authorization: Bearer
<key>`. Models: `grok-imagine/image-to-video` (I2V), `text-to-video`, `image-to-image`. Grok
Imagine 1.5.

1. Prompt is a motion script, not a description: `[subject + motion] + [camera + move] +
   [light/atmosphere shift]`. Do not re-describe what is already in the frame.
2. Front-load the camera move and key action; lighting/atmosphere last.
3. Never contradict the input frame (a seated subject cannot run). #1 cause of warping.
4. No negative prompts - say what you want, positively.
5. One concrete camera move per clip (dolly/push-in, pull-back, pan, tilt, tracking, crane,
   orbit, dolly-zoom, slow zoom, handheld). Add "Unfixed lens" when moving, "Fixed lens" when locked.
6. Quantify motion with adverbs/beats ("slowly", "one step back, turns head 30 degrees"). Mood
   words give the model nothing to animate.
7. Sequence actions in order; "Shot Switch" for an intentional cut inside one clip.
8. Shot type up front; for I2V the framing is the input image, so aim the camera move, don't reframe.
9. `duration` 6-30s, per request (vary by shot). I2V wants a STRING ("6"), T2V a NUMBER (6).
10. `@imageN ` (1-based + trailing space). I2V uses only the FIRST image as the motion reference;
    keep character identity in the PANEL (coverage cast anchor), not a second @image.
11. `resolution` 480p/720p; `aspect_ratio` 2:3/3:2/1:1/16:9/9:16 (I2V follows the input image).
    English-only, max 5000 chars.
12. Async: `createTask` returns `taskId`; result via `callBackUrl` webhook or poll.

## Reference - Scene-1 acceptance gate (kept)

A scene is "right" when the storyboard shows distinct camera angles, progresses the story forward,
and defines characters + location well, held consistent across frames. Verify by screenshot before
any clip spend.

---

## Out of scope (for now)
- Seedance (grok-imagine first).
- Comment-sentiment scraping (optional add to G1).
- Multi-language until the Slow Spanish channel is the active model.

## Log
- 2026-07-07: Phase G (first customer DvsU) started and G1+G2 landed same day: six hand-written
  prompt overrides live on the DvsU tenant (6/6 CUSTOM via API), profile filled, format locked,
  package archived to the vault; narrator-voice vault wiring fixed + deployed (main @ 34f276c3,
  voice/model/style secrets set, all tests pass on prod). Blockers for G3 beta: tenant needs a
  direct elevenlabs_api_key, and the ~$5-10 run cost needs a yes.
- 2026-07-02 (later): Phase F COMPLETE - all 6 sub-phases shipped + proven on prod in one day
  (final @ d52606fa). The chat now files dropped assets for real: CSV titles -> production_queue
  -> calendar-first slots -> autopilot drains queue-first (proven incl. the FOR UPDATE SKIP
  LOCKED claim + in-flight/cadence guards); PDF scripts -> verbatim videos (scene-split, zero
  rewriting, run_script passes through); "remember this format" -> house script template applied
  at every creation door; character sheets -> locked channel cast (vision-named, auto-approved,
  generation skipped - queue videos no longer park at the cast gate once locked); one sentence
  locks the channel format and defaults every build's look. Live-proof bugs fixed along the way:
  producer ops must live in the OUTPUT FORMAT schema (model invented a sibling key), a swallowed
  elif broke profile ops, soft-deleted videos blocked the queue lane, media-proxy allowlist
  missed chat uploads, stale KIE model id 404'd direct-API calls.
- 2026-07-02: Phase F started (chat asset intake, plan approved). F1 SHIPPED + PROVEN on prod
  (main @ 5f8bca95, deployed via the new scripts/vps-deploy.sh): drop a CSV/PDF into home chat,
  chat_assets row + Drive copy + honest producer read-back all verified live. Also shipped the
  VPS deploy coordination protocol (deploy.lock + single deploy script + CLAUDE.md rule,
  main @ d100e51f) after sessions kept restarting over each other's builds. Next: F2 production
  queue.
- 2026-06-30: Re-centered GOAL on the intelligence command center. Shipped (backend, prod): chat
  models outside videos on real YouTube Data API data (fixed the generic-channel fallback); full
  profile control from chat (add/remove competitors + edit channel name/niche/audience/look);
  setup + competitor-performance read-back; flexible co-thinking producer (saved channel is a
  default, not a cage); competitor-winners brief injected every turn. Mapped the 10-step faceless
  workflow onto the real system - finding: ~8 of 10 already exist (Autopilot + distillation +
  learnings + analytics), so the plan is to surface them in chat (Phase A) + close 5 gaps
  (G1-G5) + 2 director remnants (D1 shot budget, D2 clip proof). Commits a4991cc8, 22505e98,
  8edb89c7, 0ea3e5f1. (Older director-pass log preserved in GOAL.md.bak-20260630-075433.)
- 2026-06-30: Phase A SHIPPED (main @ fc476ad6) - chat now drives the loop: `_loop_brief` injects
  what-to-make-next (scored 0-100 via Autopilot's confidence fn), the creator's own published-video
  analytics, and learnings into the producer every turn; "mastered faceless YouTube" framing.
  Proven live (ranked picks, honest "nothing synced yet", real proven-formula readout).
- 2026-06-30: Phase B SHIPPED (main @ 101616f4) - idea -> score -> pick. Producer scores options
  (competitor winners, fresh angles, AND pasted ideas) on velocity x2 / channel-fit x2 / feasibility
  / monetization, ranks them, names a pick + runner-up with the exact title, hook, and the one
  differentiator, then offers to build the winner. Proven live: a clean scorecard for competitor
  winners, and correctly tanked two off-niche pasted ideas while picking the on-format one.
  NEXT: Phase C (G5 conversational post-video diagnosis + G1 content-gap / opportunity map).
- 2026-06-30: Phase C SHIPPED (main @ 5e8d898e) - closed the loop in chat. G5 post-video diagnosis:
  funnel logic (impressions -> CTR -> retention) on the creator's own synced analytics, names the
  one biggest fix, drafts a better title; honest "nothing synced yet" + accepts pasted stats.
  Proven live: correctly diagnosed 62k impr / 2.1% CTR / 24% retention as a packaging problem with
  a quantified fix. G1 opportunity map: covered territory + 3-5 ranked adjacent gaps with
  why-it-wins + differentiator, from real competitor data. Proven live (School / family-twist /
  workplace / doctor / friendship gaps for the ESL niche). Phases A+B+C of the command center are
  now all shipped. REMAINING backlog: G3 hook engineering, G4 strategic calendar + shorts
  repurposing, D1 per-scene shot budget, D2 Scene-1 clip-motion proof.
- 2026-06-30: G4 strategic calendar SHIPPED (main @ 06f71076) - "plan + one-click build" (Ryan's
  pick; shorts repurposing deferred). GET /api/dashboard/calendar/plan sequences the top unmodeled
  competitor winners (reusing the autopilot scoring engine) into dated slots paced to cadence,
  easy-wins-first, channel-spread to avoid fatigue; Calendar page renders "Your strategic plan" with
  a one-click Build per slot (launchCandidate -> pipeline); producer gained a "plan ahead" capability.
  Proven live (15 slots / 30 days). Also: account-unlock bug fixed (unlimited tier missing from the
  frontend plan gate, main @ df488f2e). REMAINING: shorts repurposing, D1 shot budget, D2 clip proof.
