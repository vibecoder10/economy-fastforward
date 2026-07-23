# Loop checklist — Beta UX + four public production styles (Milestone 1)

## Definition of Complete
1. A new user must explicitly choose one of four generically named, clearly described production styles before creation: Bilingual Character Animation, Simple-Language Animation, Photo Documentary, or Animated Investigative Documentary. No customer or YouTube channel name appears as a public style.
2. The chosen style is one persisted per-video contract covering render mode, script profile, visual profile, image density, animation, language, dubbing, segmentation, camera, quality laws, and the future image-source dimension. Its label, description, media estimate, and BYOK cost warning follow the video through both creation flows, the finish page, and every co-pilot surface.
3. All runtime AI use is BYOK. StoryEngine never silently falls back to a StoryEngine-funded provider key, and every paid generation path still requires the existing quote and explicit confirmation.
4. The docked co-pilot never looks stalled: it acknowledges long work promptly, consumes live task progress, shows useful scene/image counters, and displays a compact sequential “you are here” pipeline map with the selected style.
5. Each public style activates the intended existing pipeline shape. Photo Documentary safely mirrors the shared public documentary profile and retains its multi-image static/Ken Burns behavior; Animated Investigative Documentary targets roughly one visual per sentence or meaningful visual cue.
6. The finish and onboarding surfaces tell the truth: static work is not pushed to animate, full-video and per-scene animation actions are visually distinct, voice timing and progress are clear, and users without Drive see that StoryEngine storage is not guaranteed long-term.
7. Focused backend/frontend tests, stash-proof where new tests can prove causality, production builds, and a no-spend first-user browser walkthrough pass. The verified implementation is published as its own draft PR; paid four-style generations and production deployment remain explicit later approval gates.

## Milestone 2 boundary — separate PR, not part of this loop
- **Custom Film** is the later chat-hidden composer. A user describes the film in chat; StoryEngine privately composes the public profiles’ underlying knobs per section, explains the assembled plan and BYOK estimate in plain English, and asks for approval before generation. No exposed “advanced knobs” form and no Custom Film implementation belongs in Milestone 1.

## Decisions
- **DEC-CHOICE-COPY — resolved 2026-07-23**
  - Decision: public labels are **Bilingual Character Animation**, **Simple-Language Animation**, **Photo Documentary**, and **Animated Investigative Documentary**. Milestone 2 is **Custom Film**.
  - Descriptions:
    - Bilingual Character Animation — “Animated character stories with dialogue in two languages and natural dubbed voices.”
    - Simple-Language Animation — “Simple-language animated stories built for learners and clear comprehension.”
    - Photo Documentary — “Item-by-item narration using still images, captions, and slow cinematic pan-and-zoom.”
    - Animated Investigative Documentary — “Investigative narration with a fresh animated visual for nearly every sentence or visual cue.”
    - Custom Film — “Describe the film in chat; StoryEngine assembles the right styles, voices, languages, and motion section by section.”
  - Estimate copy: creation surfaces show calculated media counts and BYOK cost from duration/profile rather than freezing guessed counts into descriptions.
  - Context: the original labels were customer/YouTube channel names and did not describe the production technique.
  - Alternatives: retain channel brands; use marketing names unrelated to pipeline shape.
  - Why this won: the labels explain what StoryEngine will actually make and remain safe as public reusable profiles.
- **DEC-PUBLIC-PHOTO-PROFILE — resolved 2026-07-23**
  - Decision: mirror the existing documentary configuration as a public profile style. The tenant-private DvsU row is not queried cross-tenant; a canonical shared profile is the public source, and the original channel references the same profile.
  - Context: `channel_profiles` is tenant-isolated, while this style must be public and stay synchronized.
  - Alternatives: copy a fixed snapshot; read another tenant’s row at runtime.
  - Why this won: one public source stays current without violating tenant isolation.
- **DEC-BYOK — resolved 2026-07-23**
  - Decision: every user supplies their own provider credentials. No StoryEngine-funded inference fallback.
  - Context: StoryEngine is software, not a subsidized generation service.
  - Alternatives: StoryEngine-paid runtime inference; consumer-subscription reuse.
  - Why this won: spend stays with the user who initiates it and the boundary is supportable in a multi-tenant SaaS.
- **DEC-MILESTONE-SPLIT — resolved 2026-07-23**
  - Decision: Milestone 1 gets its own PR before any Custom Film work. Milestone 1 surfaces the four existing pipeline shapes as required selectors and fixes the urgent co-pilot/finish/Drive UX. Milestone 2 composes those components invisibly through chat.
  - Why this won: urgent first-user fixes and existing pipeline productization ship without being blocked by the new per-section composition engine.
- **DEC-PAID-DEPLOY-GATES — resolved 2026-07-23**
  - Decision: no paid generation and no production deployment without a fresh quote and Ryan’s explicit approval. Local no-spend work proceeds autonomously.

## Assumptions
- The shared public profile is versioned. New Photo Documentary videos resolve the latest public profile and persist a per-video snapshot so an in-flight or completed video cannot silently change later.
- The four preset cards expose simple calculated media/cost summaries; implementation knobs remain internal.
- Existing videos with no explicit style preserve their current inferred behavior. The required pick applies to new creation.
- The implementation branch is `agent/storyengine-beta-ux-styles`, isolated at `/Users/ryanayler/economy-fastforward-beta-ux`; the dirty `feat/per-card-parallel-clips` checkout is untouched.

## Chunks
- [x] M0 SWEEP [D][B][U][V] Re-pin every quoted anchor against merged `origin/main`, trace all creation/chat/finish/runtime consumers, identify the migration and test seams, and record baseline checks before changing behavior.
      Evidence: `origin/main` is the direct parent of plan commit `8cd501cc`; the isolated worktree contains no product edits. Finish-page anchors remain in `ScenesWorkspaceTab.tsx` (`No voice yet` ~1350, portal command bar ~1492, per-scene animation ~1801), but the merged UI already moved progress into the StageRail portal. `ChatCore.tsx` already imports `usePipelineSSE`, yet only home `CreatedCard` subscribes (~1919); the dock still explicitly assumes the surrounding page owns progress (~286–288). The onboarding creator still sends no style, while the returning-user modal exposes three separate optional axes (image look, look engine, script profile). Existing `style_preset_id` means a new high-level selector must use a distinct `production_style` name. The create route still infers `static_docu` from tenant identity and stores no unified per-video contract. Merged Photo Documentary code already targets three views with two required (`static_docu_contract.py`), superseding the plan's stale one-image claim. `_coverage_shape` still returns a generic three-moment plan for narration-only scenes before the eight-second dialogue branch, so investigative density must be style-aware rather than a global pacing change. Tenant-scoped `vault.get_secret` never falls back to server environment keys, and `get_text_client_for_tenant` fails without the tenant's Anthropic/Kie key, confirming BYOK is an existing invariant to preserve. Migration 121 is next after application-drain migration 120. Baseline focused backend suites passed 41/41, TypeScript passed, and the full 34-route Next production build passed.
- [x] M1 STYLE CONTRACT [D][B][V] Build the single public style/profile schema, versioned Photo Documentary mirror, BYOK provider contract, per-video style snapshot, API serialization, and compatibility behavior for legacy videos.
      Evidence: migration 121 and the fresh schema define one RLS-protected system catalog distinct from visual-look presets, seed exactly the four generic public profiles with every locked production knob and `requires_byok = true`, link recognized static-documentary channels to `photo_documentary` without copying or reading tenant-private identity JSON, and add a versioned immutable snapshot to each newly styled video. The authenticated catalog API never consults `channel_profiles`; create-video validates active public IDs, stores the ID/version/snapshot, serializes the contract back to the frontend, and preserves legacy callers when the field is absent until both first-party selectors land in M3. Focused contract/style/schema tests pass 26/26, Python compilation passes, TypeScript passes, and the 34-route Next production build passes. With the implementation stashed but its new tests retained, collection fails on the missing `production_styles` module; restored, the new suite passes 10/10. The full implementation suite records 2,588 passed with the same 14 failures plus one collection error as exact base `8cd501cc`, whose run records 2,578 passed and the identical failure set—no new regression. No live migration, provider call, or deployment occurred.
- [x] M2 RUNTIME PRESETS [B][V] Apply each preset through the existing render/script/dialogue/language/dubbing paths and tune Animated Investigative Documentary to sentence/visual-cue density without resurrecting the retired storyboard engine.
      Evidence: create-video now translates the persisted profile dimensions—not public profile names—onto the existing render, script, visual, and dialogue-audio seams; explicit styles override legacy channel inference while unstyled videos preserve it. Bilingual character work uses the existing performed-dialogue plus speech-to-speech voice-lock path; simple-language work uses performed single-language clips; Photo Documentary selects the canonical static stage plan and existing three-view/two-required Ken Burns contract; Animated Investigative Documentary binds the desktop-canonical `power_doctrine_v2` script profile and `cinematic_illustration` visual profile. The desktop integration copy's canonical Power Doctrine script profile is byte-identical to the merged profile (`e87947da7ece7483f8c8c16c3dd750d085018c18`), and its old sentence → image prompt → image → motion prompt flow is preserved functionally on the merged coverage path: cue text and image prompt are stored together, the motion writer consumes both and stores `video_prompt`, then clip generation consumes that prompt. Style-aware cue density produces 50 frames for a roughly 700-word/50-sentence proof while folding trivial fragments; legacy narration density remains unchanged. Direct coverage/static image generation now requires the initiating tenant's Kie key and refuses an operator environment fallback. The focused runtime suite passes 10/10, the broader style/runtime suite passes 358/358, Python compilation and TypeScript pass, and the complete 34-route Next production build passes. With the runtime implementation hidden and its new tests retained, collection fails at the missing tenant-key gate; restored, all 10 new tests pass. The full suite records 2,598 passed with the same 14 failures plus one collection error as the M1/base baseline—ten added passes and no new failure. No provider call, live migration, or deployment occurred.
- [ ] M3 CREATION UX [U][V] Add the required four-card selector, descriptions, calculated media/BYOK estimates, and no-default validation to both onboarding and main creation flows.
- [ ] M4 CO-PILOT TRUTH [B][U][V] Wire docked SSE progress, improve script/voice/image messages and counters, add the sequential stage map, and keep the selected style visible in all co-pilot modes.
- [ ] M5 FINISH + DRIVE UX [U][V] Clarify animation actions, progress placement, voice-at-the-end, static-video treatment, style identity, and honest no-Drive storage messaging.
- [ ] M6 FINAL + PR [V][G] Re-grade all seven criteria as a first-time user, run relevant full regressions/builds and a no-spend browser walkthrough, update deferred proof recipes, commit the verified result, push, and open a draft PR to `main`.

## Previous completed missions

# Loop checklist — Application-level drain mode

## Definition of Complete
1. An operator can atomically place all StoryEngine generation into `draining` before checking active work, with durable state shared by every backend process and an explicit reason/owner/timestamp.
2. While draining, reads, reviews, downloads, health checks, and existing task polling remain available, but every new research, image, voice, clip, render, upload, autopilot, and other provider/background start is rejected before cost or work begins with one retryable machine-readable response.
3. Existing tasks continue and can persist their terminal state; the deploy path waits for `active_tasks = 0`, deploys, verifies health, and reliably restores `normal` on success or failure.
4. Operators have clear `se drain`, `se drain-status`, and `se undrain` recovery commands, and the standard `se deploy` path uses them automatically without requiring Redis.
5. Users see a global maintenance banner, generation actions are disabled where the shared production controls render them, and any remaining race is handled by the authoritative backend response.
6. Focused stash-proof tests, relevant backend/frontend regressions, a production build, and a live no-spend drain/deploy/undrain proof pass without starting a paid pipeline or interrupting customer work.

## Assumptions
- Drain state is global across tenants and stored in PostgreSQL because production currently runs with Redis unavailable and in-process background tasks.
- `draining` blocks only new work that can launch providers, uploads, or long-running background tasks; ordinary reads and non-generation metadata edits stay available.
- The rejection contract is HTTP 503 with `code: "system_draining"`, a human message, and `Retry-After`; clients should treat it as temporary rather than a failed video.
- Ryan’s “implement this” authorizes the tested production deployment and live no-spend drain toggle proof, but not any paid research/image/voice/video/render run or YouTube upload.

## Chunks
- [x] D0 SWEEP [D][B][U][O][V] Map every new-work entry seam, active-task persistence law, frontend generation surface, deploy race, and migration convention before changing behavior.
      Evidence: production runs the supported Redis-less in-process queue; `/api/health` previously counted only `background_tasks.status = running`; `generation_claims` is the durable paid-work seam for chat/autobuild while manual pipeline starts converge on `_is_task_active` and `_enqueue_or_fallback`; autonomous schedulers live in `main.py`; the sanctioned deploy checked active work before acquiring its lock, leaving an API race; frontend generation controls converge partly on `ActionButton` and the static-documentary rail. Migration 120 is the next ordered migration and `storyengine/schema.sql` is the fresh-install authority.
- [x] D1 [D][B][V] Build one durable drain contract and authoritative pre-cost guard.
      [D] Add the singleton control state with normal/draining, reason, owner, and timestamps.
      [B] Expose status through health, preserve terminal writes for existing tasks, and reject every new provider/background claim before work begins.
      [V] Focused fail-open/fail-closed, concurrency, response-contract, and route/claim coverage tests with stash-proof.
      Evidence: migration 120 and `drain_mode.py` provide the RLS-protected global singleton, owner/reason/timestamp metadata, shared advisory transaction lock, retryable `system_draining` response, fail-closed new-work reads, and conservative active-work counts. Generation claims take the global lock before per-video/channel claims; pipeline dispatch repeats the guard; request classification covers pipeline/chat/autopilot/agent/provider routes while preserving reads, reviews, cancel/reset, and ordinary video edits; autonomous provider cycles pause. Focused + schema-drift suites pass 52/52. With implementation hidden and new tests retained, collection fails on missing `drain_mode`, proving the tests are non-vacuous.
- [x] D2 [O][V] Make deployment drain, wait, recover, and reopen safely.
      [O] Add status/drain/undrain operator commands and integrate them into the sanctioned deploy wrapper with traps, timeout, active-task detail, and no-force safety.
      [V] Shell/static tests plus a local fake-control integration prove ordering and recovery when pull/build/health fails.
      Evidence: `drain_control.py` operates directly against PostgreSQL even when the API is down and exposes status/drain/undrain/wait with two-zero settle checks. `se.sh` exposes `drain`, `drain-status`, and `undrain`. `vps-deploy.sh` now acquires the operator lock, drains before inspecting active work, never lets `--force` bypass the wait, verifies backend health while drain remains on, verifies the frontend when requested, and undrains/releases the lock from an EXIT/INT/TERM trap. Shell syntax and static ordering pass; the fake-VPS integration passes 2/2, including a simulated `git pull` failure that exits nonzero but still undrains and removes the lock.
- [x] D3 [U][V] Make draining visible and non-confusing to users.
      [U] Add a globally polled banner, disable shared generation controls, and normalize the backend 503 into a retryable message.
      [V] Pure state/response tests, TypeScript, and the production frontend build.
      Evidence: the root provider polls health every five seconds and reacts immediately to a structured drain 503; authenticated users see the global safe-update banner with active-work context. `ApiError` preserves status/code/retryability/Retry-After, shared `ActionButton` supports a drain-aware generation marker, the Anton static-documentary Run All control and 13 core research/script/voice/image/sound/render controls are marked, and YouTube generation/upload controls are disabled without disabling review/edit actions. The focused frontend wiring contract passes, TypeScript passes, and the complete Next production build succeeds across all 34 static/dynamic routes.
- [x] D4 FINAL + DEPLOY [O][V] Re-grade all six criteria, fast-forward main, wait for a quiet window, deploy without force, and live-test drain blocks a no-cost claim while reads/health remain available before restoring normal.
      Evidence: the focused drain/schema/claim suite passes 52/52, the route-compatibility regression passes 38/38, the fake-VPS deploy integration passes, Python/shell compilation and diff checks pass, TypeScript passes, and the complete Next build passes. The full functional suite passes 1,751 tests; its 14 failures plus one collection error reproduce on exact base `4b540fb7` (unrelated legacy discovery/model-video/YouTube/string-lock debt), while every drain-caused regression was repaired. Main fast-forwarded to `9784f39c`; production deployed without force during a verified zero-work window, migration 120 applied, backend/front end are healthy, and the frontend is HTTP 200. Live manual drain kept `/api/health` at 200, returned HTTP 503 + `system_draining` + `retryable: true` + `Retry-After: 30` for a synthetic unauthenticated generation probe, allowed the safe review route to reach ordinary auth, then restored normal so the same probe returned ordinary 401. A no-change live deploy through the new wrapper proved automatic drain, two-zero settlement, backend restart, health verification while still drained, undrain, and lock release. Active work remained zero and no provider/upload call was made. Verdict: **Complete**.

## Previous completed mission

# Anton DVsU launch-feedback refinement

## Definition of Complete
1. Every newly generated aircraft unit plans three complementary, historically grounded images and can still render when one view fails: a three-quarter identification view, an elevated/top-oblique view, and a narration-relevant detail view.
2. Every aircraft gets one animated on-screen title card with its name, operator/service years, and one or two sourced key specs; the card is composited in video assembly, never baked into the generated image.
3. Ken Burns movement alternates a slow push-in and slow pull-out, eased smoothly across the full image hold: no lateral wandering, looping “breathing” wobble, early finish, freeze, or direction reversal.
4. The change is isolated to the `static_docu` channel style, preserves old one-image DvsU projects, and keeps the fail-closed verified-reference/QA laws intact.
5. No paid research, image, voice, clip, or render-provider calls are made in this loop. Local no-spend tests plus a synthetic multi-image render prove the user-visible result; production deployment and paid regeneration remain explicit later gates.
6. The verified branch is deployed through the normal StoryEngine production path, the live backend health check passes, and the production frontend serves the new build without triggering a paid pipeline run.

## Assumptions
- Anton’s four numbered notes are the acceptance standard; no additional design decision is needed before implementation.
- New units target three images and require at least two successful views. Existing one-image units remain renderable until Ryan chooses to regenerate them.
- The canonical DvsU image law under `/Users/ryanayler/Desktop/Designed vs used/` remains authoritative for variant accuracy, verified references, photorealism, and clean source images.
- Work stays on isolated branch `codex/anton-dvsu-feedback`; no deploy, push, database mutation, or paid pipeline run is authorized.
- Ryan subsequently authorized production deployment on 2026-07-23. This authorizes the normal deploy/restart/smoke path only; it does not authorize a paid research, image, voice, clip, render, or YouTube run.

## Chunks
- [x] C0 SWEEP [D][B][U][V] Trace Anton’s current static-documentary path from subject metadata through image generation, picture review, render config, Remotion composition, and motion math.
      Evidence: captions default off in `render_static.py`; `_STUDIO_PROMPT` requests a pure side profile; `generate_static_images_for_video` writes only `image_index=1`; `Scene.tsx` adds a sinusoidal wobble; Ken Burns `speed_multiplier` can finish motion before the hold ends; the existing Remotion scene model already supports multiple images per narration scene.
- [x] C1 [D][B][M][V] Build the three-view aircraft asset contract.
      [D] Source-grounded caption specs and explicit view roles.
      [B] Three per-unit assets, per-view prompts, independent QA/parking, minimum-two success rule, idempotent scene redraw, legacy compatibility.
      [M] Honest three-image cost estimates for static-documentary picture/build confirmations.
      [V] Focused no-spend backend tests, including fail-closed reference behavior and partial-view success.
      Evidence: commit `9c05cb8a`; stash-proof new suite failed 4/4 against the old implementation and passed 4/4 restored; static-docu/render-static suite passed 127/127. No provider call, database write, deploy, or paid run occurred.
- [x] C2 [B][R][V] Render multiple views, the one-per-aircraft title card, and cinematic motion.
      [B] Gather 1–3 ordered static assets per scene and split the narration hold without duplicating audio.
      [R] Enable the fixed overlay by default, add the specs line and one-time card animation, and alternate full-duration smoothstep push-in/pull-out Ken Burns moves with no lateral drift or wobble.
      [V] Backend config tests, TypeScript check, and a short local synthetic Remotion render inspected at multiple frames.
      Evidence: commit `56efe09c`; stash-proof new tests failed 4/4 against the old renderer and passed 12/12 restored; the broader render-static suite passed 42/42. A local 240-frame Remotion proof rendered successfully and was inspected across all three view changes. The title card remains continuous over view rotation, the movement alternates centered push-in/pull-out with smoothstep easing, and the final scale is reached only at the last frame. Remotion bundling succeeded; the full TypeScript check reaches only the unchanged pre-existing `MusicBed.tsx:153` `startFrom` error, reproduced on the base checkout.
- [x] C3 [U][V] Make the Pictures and Render UI tell the new truth.
      [U] Group 2–3 views into one aircraft card, show view roles/specs and per-view QA actions, compute readiness per unit, and update one-image copy/counts.
      [V] Frontend typecheck/build plus focused state tests or extracted pure helpers where practical.
      Evidence: commit `d1be7660`; the extracted readiness contract passed 4/4 focused tests and failed without the new helper during stash-proof. Pictures now groups ordered view tiles per aircraft, exposes view roles/specs and per-view approval, and distinguishes a render-ready 2/3 set from a blocked 1/3 set. Stage and Render gating use the same helper, TypeScript passed with no errors, and the complete Next production build passed with the required local `NEXT_PUBLIC_API_URL`.
- [x] C4 FINAL SWEEP [V] Re-grade all five Definition-of-Complete criteria from a first-time operator/viewer path.
      Run focused suites, full relevant backend baseline, Remotion and frontend builds, inspect git diff/blast radius, record any paid/live proof as deferred, and give an explicit Complete/Partial verdict.
      Evidence: all five criteria pass within the authorized no-spend scope. The combined static-documentary/render regression suite passed 131/131; the frontend readiness suite passed 4/4; Python compilation, frontend TypeScript, the full Next production build, and the Remotion bundle all passed. The synthetic 240-frame MP4 proves the three-view timing, continuous title card, and smooth alternating motion without provider calls. Final blast radius is 23 files, isolated to the static-documentary contract, renderer, Remotion overlay/motion, operator UI, tests, and Maestro state. Verdict: **Complete** for code and no-spend verification; the explicitly deferred production redraw/render remains a later paid/deploy approval gate, not hidden unfinished work.
- [x] C5 DEPLOY [O][V] Publish the verified branch through the standard StoryEngine deployment path.
      [O] Deploy backend and frontend with the repository deployment wrapper; do not invoke any pipeline generation or upload action.
      [V] Confirm the deploy command completes, the live backend health endpoint returns healthy, the production frontend responds, and the deployed checkout identifies the expected commit.
      Evidence: deployment waited behind a genuine customer image-generation task until `active_tasks` fell from 1 to 0; no force flag was used. `se.sh deploy anton-dvsu-feedback --with-frontend` fast-forwarded production from `69ea7499` to `3a980674`, built the full Next frontend, restarted both exact service units, and released the lock. Post-startup verification returned backend `healthy` with database/storage true and active tasks 0, frontend HTTP 200, deployed revision `3a980674`, and live static-documentary constants `target=3`, `minimum=2`. No paid pipeline or upload was initiated by this deployment.

## Lessons
- The prior “clean frames” toggle directly contradicted Anton’s launch feedback and the desktop DvsU on-screen-text standard; title metadata belongs in a fixed assembly overlay, not in the generated picture.
- Multiple images do not require duplicating script/voice scenes: Remotion already supports several `image_index` entries under one `scene_number` and plays one scene audio track across them.
- Ryan clarified the Ken Burns grammar as slow pan in / slow pan out; implement this as alternating cinematic push-in and pull-out moves, not lateral pans or tilts.
# Loop: per-card parallel clip/image generation on the pipeline page

Goal: let Ryan click Run / Re-run on individual clip cards and fire SEVERAL at
once so they generate in PARALLEL, instead of being blocked one-at-a-time by the
video-level task lock. Scope (Ryan, 2026-07-23): clips AND per-card image redraw;
instant per-card Run (no select-mode); no per-click cost gate, live cost counter.

## Key recon facts (why this is smaller than "add buttons")
- Per-asset animate endpoint ALREADY exists: POST /api/pipeline/clip/{video_id}
  ?asset_id=&force=  (routes/pipeline.py:1691). Card tap already animates one clip;
  hover redo already re-runs with force=true (ScenesWorkspaceTab.tsx:2010/2474).
- Clip gen is ALREADY concurrent within one run: asyncio.gather over
  Semaphore(CLIP_CONCURRENCY, default 6) (pipeline_executor.py:12701/13151).
- THE BLOCKER: video-level 409 lock — routes/pipeline.py:1727 _is_task_active,
  backed by generation_claims keyed (tenant, video, lane). Two runs on one video
  can't overlap -> feels serial. No per-asset lock; per-card state inferred from
  assets.video_clip_url (present=done).
- Frontend: SegmentCard in components/production/ScenesWorkspaceTab.tsx:2268;
  refresh = 3s task poll (use-task-poller.ts) -> invalidate ["video-assets"].
  In-flight tracked in client Sets generatingClipIds/failedClipIds
  (use-clip-trust-ladder.ts:46). No multi-select pattern exists.

## Chosen approach (Fable): batch, don't unlock
Clicked cards coalesce into ONE run_clip_generation scoped to that SET of asset
ids, reusing the existing 6-wide fan-out + the "animate the rest" auto-resume
loop. Keeps the global cost/rate cap; never double-animates an asset; full-scene
/full-video builds stay mutually exclusive. Do NOT rework the lock per-asset.

## Definition of Complete (grade against THIS)
0. PRIMARY FLOW (Ryan, confirmed): edit the prompts on several cards, hit Re-run on each, and ALL the changed cards regenerate in parallel — for BOTH clip re-runs AND image re-draws. The current one-at-a-time behavior (video 409 lock) is gone.
1. Each clip card has Run (animate from image) + Re-run (force) that starts THAT clip on click.
2. Clicking Run on several cards runs them in parallel (up to CLIP_CONCURRENCY); extra clicks queue and start as slots free — no 409, no one-at-a-time wall.
3. Same instant-parallel behavior for regenerating a card's still image (redraw).
4. A live cost counter shows spend accumulating as clips/images finish; the per-video budget cap still backstops.
5. Manual runs never double-animate an asset and never collide with / corrupt a full-scene or full-video build.
6. Proven by clicking multiple cards on the running app — parallel execution + counter shown in screenshots.

## Chunks
- [x] C1 (S) [B][V] — Backend multi-asset manual clip run. DONE @ commit 0917d67e on
      feat/per-car-parallel-clips. asset_ids param (id = ANY($3::uuid[])); new
      clip_manual lane (mutually exclusive with full "main" builds, ref-counted, but
      never self-blocks); in-process per-asset claim (clip_asset_claims.py) prevents
      double-animate. 28 new tests, stash-proof 17/19, suite 14-fail baseline
      unchanged +28 pass. SAFETY: sound ONLY under single-process deploy — VERIFIED
      prod runs one uvicorn worker (no --workers). CAVEAT: if scaled to N workers,
      move the asset claim to the generation_claims cross-process table. redraw-image
      NOT extended here (no fan-out infra) -> C1b.
- [x] C1b (S) [B][V] — Backend PARALLEL image redraw. DONE @ commit 196dd7cb on
      feat/per-card-parallel-clips. redraw-image now accepts asset_ids (id =
      ANY($3::uuid[])); new redraw_manual lane (mirrors clip_manual, ref-counted,
      never self-blocks); sibling in-process per-asset claim (redraw_asset_claims.py)
      prevents double-draw; new redraw_asset_images() fans out under IMAGE_CONCURRENCY
      (default 6) via asyncio.gather. Singular asset_id path preserved byte-for-byte
      (claim-guarded passthrough, equality-tested). 33 new tests; stash-proof 14/16
      lane (+2 deliberate regression-locks) + 2 new files error at collection when
      reverted; suite 14-fail baseline unchanged, +33 pass, 0 regressions. SAFETY:
      in-process claim safe ONLY single-process (documented SYSTEM_STATE.md §C1b +
      deferred-verification.md §C1b) — if scaled to N workers, move to generation_claims.
      Live proof (real Kie spend, concurrent-curl 409, ledger no-dup) deferred to C4.
- [x] C2 (S) [U][V] — Frontend instant-parallel per-card Run/Re-run for CLIPS.
      DONE @ commit cb60df16 on feat/per-car-parallel-clips. animateOne now queues
      into pendingClipRef Map + 500ms debounce (cap 2000ms) -> ONE call with
      asset_ids for 2+, singular asset_id for 1. Removed the if(running) gate;
      in-flight tracked via a live ref (fixed a stale-closure bug). queuedClipIds ->
      "Queued…" overlay. Partial-failure reconcile: onComplete refetches + marks
      still-clipless batch ids failed. tsc clean + next build OK (34 routes). No
      jest/vitest in repo -> documented trace (see deferred-verification.md). Live
      proof = C4. Backend asset-claim (C1) is the double-spend safety net regardless
      of FE behavior.
- [x] C3 (S) [U][V] — Frontend: same instant-parallel treatment for per-card image
      redraw + a live cost counter. DONE @ commit 7dc6f00c on feat/per-card-parallel-clips.
      redrawOne/dispatchPendingRedraws mirror C2's clip coalescing (Map + 500ms debounce
      -> ONE asset_ids= call for 2+, singular asset_id= for 1); old if(running) redraw
      gate removed. Cost counter reused existing CostLedgerChip (video.total_cost already
      exposed) + onProgress now invalidates ["video", id] so it climbs on the ~3s task
      tick — NO backend gap. Found+fixed a cross-track dispatch race (shared
      dispatchInFlightRef). Cross-track serialization is a deliberate FE choice — backend
      _is_task_active permits clip_manual+redraw_manual to overlap (each blocks only on
      "main"); within each track cards fully parallelize. tsc clean, build 34 routes.
      Live proof -> C4.
- [ ] C4 (V, S Explore) — E2E: se devtoken + local dev vs prod API, drive UI:
      click 4-5 clip cards + 1-2 redraws, prove parallel run + cost counter climbs +
      no double-run + full-build exclusion; screenshots. THEN gated prod deploy —
      STRATEGIC (LIVE USERS as of 2026-07-23): se deploy restarts uvicorn and KILLS
      in-flight user builds. Before deploying: (1) check for active user builds via
      `se db` (in-progress/generating videos) and deploy ONLY in a quiet window with
      none in flight; (2) honor ~/deploy.lock; (3) Ryan watches; (4) one /se-smoke
      pass after. Also clear all deferred-verification.md items (incl. C1b live proof).
      Prod lock + live users = high blast radius.

Notes / lessons: (append as we learn)
