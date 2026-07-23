# Loop checklist — Anton DvsU launch-feedback refinement

## Definition of Complete
1. Every newly generated aircraft unit plans three complementary, historically grounded images and can still render when one view fails: a three-quarter identification view, an elevated/top-oblique view, and a narration-relevant detail view.
2. Every aircraft gets one animated on-screen title card with its name, operator/service years, and one or two sourced key specs; the card is composited in video assembly, never baked into the generated image.
3. Ken Burns movement alternates a slow push-in and slow pull-out, eased smoothly across the full image hold: no lateral wandering, looping “breathing” wobble, early finish, freeze, or direction reversal.
4. The change is isolated to the `static_docu` channel style, preserves old one-image DvsU projects, and keeps the fail-closed verified-reference/QA laws intact.
5. No paid research, image, voice, clip, or render-provider calls are made in this loop. Local no-spend tests plus a synthetic multi-image render prove the user-visible result; production deployment and paid regeneration remain explicit later gates.

## Assumptions
- Anton’s four numbered notes are the acceptance standard; no additional design decision is needed before implementation.
- New units target three images and require at least two successful views. Existing one-image units remain renderable until Ryan chooses to regenerate them.
- The canonical DvsU image law under `/Users/ryanayler/Desktop/Designed vs used/` remains authoritative for variant accuracy, verified references, photorealism, and clean source images.
- Work stays on isolated branch `codex/anton-dvsu-feedback`; no deploy, push, database mutation, or paid pipeline run is authorized.

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
- [ ] C3 [U][V] Make the Pictures and Render UI tell the new truth.
      [U] Group 2–3 views into one aircraft card, show view roles/specs and per-view QA actions, compute readiness per unit, and update one-image copy/counts.
      [V] Frontend typecheck/build plus focused state tests or extracted pure helpers where practical.
- [ ] C4 FINAL SWEEP [V] Re-grade all five Definition-of-Complete criteria from a first-time operator/viewer path.
      Run focused suites, full relevant backend baseline, Remotion and frontend builds, inspect git diff/blast radius, record any paid/live proof as deferred, and give an explicit Complete/Partial verdict.

## Lessons
- The prior “clean frames” toggle directly contradicted Anton’s launch feedback and the desktop DvsU on-screen-text standard; title metadata belongs in a fixed assembly overlay, not in the generated picture.
- Multiple images do not require duplicating script/voice scenes: Remotion already supports several `image_index` entries under one `scene_number` and plays one scene audio track across them.
- Ryan clarified the Ken Burns grammar as slow pan in / slow pan out; implement this as alternating cinematic push-in and pull-out moves, not lateral pans or tilts.
