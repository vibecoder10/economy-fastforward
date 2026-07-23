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
- [ ] D2 [O][V] Make deployment drain, wait, recover, and reopen safely.
      [O] Add status/drain/undrain operator commands and integrate them into the sanctioned deploy wrapper with traps, timeout, active-task detail, and no-force safety.
      [V] Shell/static tests plus a local fake-control integration prove ordering and recovery when pull/build/health fails.
- [ ] D3 [U][V] Make draining visible and non-confusing to users.
      [U] Add a globally polled banner, disable shared generation controls, and normalize the backend 503 into a retryable message.
      [V] Pure state/response tests, TypeScript, and the production frontend build.
- [ ] D4 FINAL + DEPLOY [O][V] Re-grade all six criteria, fast-forward main, wait for a quiet window, deploy without force, and live-test drain blocks a no-cost claim while reads/health remain available before restoring normal.

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
