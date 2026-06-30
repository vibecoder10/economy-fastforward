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

**Phase A - Surface the loop in chat (the through-line).** Let the chat read, run, and narrate the
existing engine: "what's working on my competitors" (done), "what should I make next" (drive
Autopilot candidates + scoring), "how did my last video do" (read the analytics sync), "what have
we learned" (read learnings), and run a modeled build. This unifies everything we already have
behind the command center. Mostly wiring, little new intelligence.

**Phase B - Idea -> score -> pick (G2).** The daily driver: pull real competitor winners, generate
ideas, score them (extend Autopilot's breakdown with feasibility/monetization), recommend the top
2 with the angle + the one differentiator, all in chat. Do before onboarding customers.

**Phase C - Close the loop in chat (G5 + G1).** Conversational performance diagnosis on synced
analytics ("low impressions vs low CTR vs low retention -> the fix"), and the content-gap +
opportunity map. This is what makes the product get smarter about THEIR channel every week - the
moat for "10 customers actually using it."

**Phase D - Depth (G3 + G4).** Explicit hook engineering; strategic calendar + shorts repurposing.

**Phase E - Director remnants (parallel, cheap-first).** D1 shot budget (no spend, the real win),
then the gated D2 Scene-1 clip proof (~$1-2).

**Sequencing:** A first (it ties the whole machine together and rides on today's chat work), then
B, then C. D and E run alongside as capacity allows. Each phase proven by a real run on prod, never
a self-test (the anti-rot rule that kept this project honest).

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
- 2026-06-30: Re-centered GOAL on the intelligence command center. Shipped (backend, prod): chat
  models outside videos on real YouTube Data API data (fixed the generic-channel fallback); full
  profile control from chat (add/remove competitors + edit channel name/niche/audience/look);
  setup + competitor-performance read-back; flexible co-thinking producer (saved channel is a
  default, not a cage); competitor-winners brief injected every turn. Mapped the 10-step faceless
  workflow onto the real system - finding: ~8 of 10 already exist (Autopilot + distillation +
  learnings + analytics), so the plan is to surface them in chat (Phase A) + close 5 gaps
  (G1-G5) + 2 director remnants (D1 shot budget, D2 clip proof). Commits a4991cc8, 22505e98,
  8edb89c7, 0ea3e5f1. (Older director-pass log preserved in GOAL.md.bak-20260630-075433.)
