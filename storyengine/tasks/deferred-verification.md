# Deferred verification — D3-52 (chat turns + pending confirm card invisible)

- [x] **Rehydrate + stash-proof + live-path visual proof — done, not persisted as image files.**
  - Proof reached now: every proof the chunk spec asks for was actually driven in the
    in-app Browser pane (`mcp__Claude_Browser__*`, worktree dev server on
    `http://localhost:3000`, launch.json entry `storyengine-d3-52`) against the real
    prod-data fixture (video `686b4651-e495-44be-baf6-97fc6dd527e9`, GET-only, dev
    token from an existing `se devtoken` mint):
    - **Stash-proof, "before":** `git stash` (fix removed) + reload `/chat/686b4651…` →
      screenshot showed the pipeline map / script / cast / storyboards recap block
      scrolled to its bottom, with ZERO message bubbles and NO confirm card anywhere
      in the visible viewport — reproducing the reported bug exactly.
    - **Stash-proof, "after":** `git stash pop` (fix restored) + reload same URL →
      screenshot showed the full turn history (7 bubbles) AND the "Generate the
      pictures — scene 1" confirm card with its "Do it · ~$0.30" / "Cancel" buttons
      fully visible above the composer, no manual scroll.
    - **Live-path proof:** `window.fetch` monkey-patched in the dev browser (via
      `javascript_tool`) to intercept `POST /api/chat` and return a mocked
      `ChatTurnResponse` (matching `routes/chat.py`'s real confirm-card shape) for a
      new "Generate the pictures for scene 2" turn — NEVER hit prod, no real spend.
      Typed the message through the real composer (`ref_26`) and clicked the real
      Send button (`ref_27`); the new user bubble + new confirm card rendered
      immediately, fully in view, no reload. Reloaded again afterward and confirmed
      the mocked turn did NOT persist (`get_page_text` still showed the real 7-turn
      history) — the money guard held throughout: "Do it"/"Cancel" was never tapped
      on the real card or the mocked one, and no POST reached
      `https://storyengine.dev`.
    - Regression: docked co-pilot (opened via the pipeline page's "Chat with the
      co-pilot" toggle) still renders the same confirm card correctly (its own
      layout never had this bug — result cards render BEFORE the thread there, not
      after). No console errors in either layout. `npx tsc --noEmit` and
      `npm run build` both clean. Only `ChatCore.tsx` changed — no new
      dependencies.
  - What's missing: the evidence contract asks for screenshot files under
    `storyengine/tasks/evidence/d3-52/`. The `mcp__Claude_Browser__computer`
    screenshot tool returns images inline in the session transcript with no file
    path, and no cache/log directory on this Mac was found holding the raw PNG
    bytes (checked `~/Library/Caches/claude-cli-nodejs/**`, `/private/tmp/**`,
    the session scratchpad). The one attempt at a workaround (macOS
    `screencapture` on the whole screen) was aborted and the file deleted
    immediately after one test shot, because it captured the ENTIRE physical
    display — including an unrelated, live, in-progress session with private
    in-progress user content — not just the Browser pane. That is a privacy
    violation, not a viable evidence mechanism, and was not repeated.
  - Later recipe: whoever reviews this chunk should re-drive the same four steps
    above directly (they take under two minutes) and, if a file artifact is
    genuinely required, capture it with a tool that can target just the Browser
    pane's window/region specifically (not the whole screen) — e.g. a
    window-scoped capture utility, or a screenshot API that writes to disk if one
    gets added to `mcp__Claude_Browser__*` later.
  - Expected result: identical to what was already seen live — bug reproduces with
    the fix stashed, is fixed with it applied, and a live (mocked) turn renders
    without a reload.

## D3-52 follow-up (bounce): fresh-mount miss found by independent review, fixed

- [x] **Fresh-navigation scroll miss — root cause instrumented, fixed, re-verified.**
  - Proof reached now: an independent fresh-eyes sweep on merged main (`293dd507`)
    found the anchor-scroll fix from the first pass worked on reload but NOT on a
    genuinely fresh `/chat/686b4651…` navigation — DOM-verified scrollTop stuck at
    0 of scrollHeight 1869, confirm card ~1200px below the fold. Instrumented (a
    temporary `window.__d352Log` array logging effect-fire time, `checking`,
    `scrollHeight`, `clientHeight`, and `scrollTop` at each retry, later removed)
    and reproduced it directly: on first mount the scroll container isn't in the
    DOM yet (the `!started && checking` spinner branch renders instead); once
    hydrate finishes and it mounts, `scrollHeight` was STILL climbing well past
    the old fixed 180/600/1500ms retry window (logged 4681 → 4661 → 5238 → 5480
    between 2s and 4.7s after mount) because `ChatPipelineMap`,
    `ScriptResultCard`, `CastLocationsCard`, and `StoryboardGridCard` each run
    their own separate network fetch, unrelated to `messages`. The last
    scheduled retry fired before layout had actually settled, and nothing
    corrected it afterward.
  - Fix: replaced the fixed-delay retries with a `requestAnimationFrame` loop
    that keeps re-anchoring every frame — driven by the ACTUAL `scrollHeight`
    settling (20 consecutive stable frames, ~1/3s), capped at 6s — plus a
    `hasUserScrolledRef` (set via real `wheel`/`touchstart` listeners, never by
    our own programmatic `scrollTop` writes) so it stops fighting a creator who
    is actually scrolling. `checking` was added to the effect's dependency array
    as a belt-and-suspenders guard for the container-mounts-late race, even
    though instrumentation showed `setMessages`/`setChecking(false)` landing in
    the same render in the practice run measured.
  - Re-verified with the SAME merge-then-fix flow the bounce asked for
    (`git merge main` — fast-forward, no conflicts, nobody else touched
    `ChatCore.tsx`): stash-proof re-run on the merged code (bug reproduces with
    the follow-up diff stashed out, fixed with it restored — screenshots showed
    the un-fixed state scrolled to the very TOP of the thread, i.e. worse than
    "stuck partway", matching a cold scrollTop=0 render); a DOM-verified
    zero-manual-scroll probe (`getBoundingClientRect()` on the "Do it" button vs
    `window.innerHeight`, fresh tab + `force:true` reload each time, explicit
    1280x800 viewport) passed 3 consecutive fresh-navigation runs
    (`scrollTop: 372`, button `top: 616, bottom: 656`, fully inside `[0, 800]`);
    the live-path mocked-POST re-check (same technique as the first pass, a new
    "scene 2" confirm card) still renders immediately with no reload, and the
    mock was confirmed NOT to persist on reload afterward. `npx tsc --noEmit`
    and `npm run build` both clean on the final diff.
  - Real tool caveat found along the way: `mcp__Claude_Browser__javascript_tool`
    intermittently evaluates against what looks like a stale/backgrounded tab
    context (`window.innerHeight`/`innerWidth` reading `0`, `scrollHeight`
    equal to `clientHeight` — an "unconstrained layout" signature, and
    `performance.now()` reading far larger than the actual elapsed test time)
    when a tab has been repeatedly navigated or several tabs are open at once.
    Calling `resize_window` (even to a size the tab may already have) and/or
    using a single freshly-created tab per check reliably fixed it. Screenshots
    taken in the SAME moments were always accurate — this looks like a
    JS-eval-context quirk of the tool, not a page bug — but it means any
    `javascript_tool` numeric read in this environment that looks like "totally
    unconstrained/zeroed" should be treated as suspect and re-checked with a
    resize or a fresh tab before trusting it as evidence either way.
  - Pre-existing bug found, NOT fixed (out of scope for D3-52, confirmed
    unrelated to this diff): the DOCKED co-pilot (opened via the `/pipeline/
    [videoId]` page's "Chat with the co-pilot" toggle) never hydrates this
    video's real history — it shows the empty "Ask about this video…" hint
    indefinitely, and `GET /api/chat/conversation?video_id=…` never fires at
    all (checked `read_network_requests` after 5+ seconds and after a
    close/reopen toggle). Reproduced identically with the D3-52 follow-up diff
    stashed OUT (pure merged main) and stashed back IN — same broken behavior
    both times, so it predates and is independent of this chunk's changes. Not
    investigated further (out of scope for this bounce); flagging for a
    separate chunk since it means the dock's "resume this video's conversation
    on open" promise (the comment at the dock's own hydrate effect) is
    currently false for at least this video.
  - Later recipe: same screenshot-persistence gap as above — the visual proof
    (multiple screenshots per run showing the before/after difference) lives in
    the session transcript, not as files. The dock hydrate bug needs its own
    investigation: instrument `getChatConversation`'s call site in the dock's
    `useEffect` (`if (!docked || !videoId) return;`) the same way this chunk
    instrumented the scroll effect, to find why the fetch never fires for this
    video/session.
  - Expected result: identical to what was already verified — scrollTop lands
    correctly on a genuinely fresh, uncached, first-ever navigation, not just on
    reload; the live-send path still works; nothing else regressed.

# Deferred verification — Custom Film Remotion showcase layer

## M8 storyboard-driven Custom Film director loop

- [ ] **Paid character, environment, and storyboard reference proof.**
  - Proof reached now: the exact film-bible, reference, storyboard, final-picture, contract-drift, stage-BOM, named-helper, consume-once schedule, and synthetic fixture laws pass locally. No provider reference was generated.
  - Later recipe: after the M8 implementation is reviewed and Ryan approves a new exact cumulative amount, generate the smallest approved cast sheets, environment references, and storyboard set. Visually inspect every asset against the locked film bible before approving any final picture.
  - Expected result: one medium/style across the film; each recurring character retains face, body, wardrobe, and identity anchors; each environment retains architecture, palette, geography, time/weather, and prop placement; storyboard order clearly advances the story.

- [ ] **Paid shot-animation and visual-verifier proof.**
  - Proof reached now: deterministic start/middle/end evaluation, issue-code derivation, rejected-attempt persistence, idempotent replay, clean visual admission, and the no-auto-reroll boundary pass with synthetic observations. No provider clip or reroll was purchased.
  - Later recipe: with a separately approved exact cumulative cap, animate a bounded sequence containing one dialogue exchange and one silent action shot. Extract start/middle/end frames from every clip, run the visual verifier, and manually compare all frames to the approved storyboard and adjacent shots.
  - Expected result: visible action progresses within each shot; dialogue ownership and lip-sync are correct; screen direction, character identity, environment, props, and opening/closing state remain continuous; failed shots stop before Remotion and require an explicit repair decision.

- [ ] **Production deployment and human film review.**
  - Proof reached now: the strict approved-shot Remotion props/composition passes all 37 Remotion tests, TypeScript, and bundle. A local two-shot proof rendered exactly 72 video frames at 1920x1080/24 fps with separate stereo audio; its contact sheet was visually reviewed for silent motion, the inside-shot cut, alternating dialogue captions, and measured-word progression. MP4 SHA-256: `a502d53d940fe177a0ce95e78b98e1e11f93327729c2aa81cf33f1e1c648d4a4`. The v2 no-provider director proof replaces the impossible 48,000-token response with 9 initial plus 9 conditional repair operations maximum, all at or below 8,000 output tokens; a complete 50-shot fake film compiles in 9 calls, one failed batch uses only its paired tenth call, replay uses zero calls, and durable started/terminal receipts plus final execution persistence fail closed. The held chat intake is still v1 and cannot authorize v2; the production adapter, generation-ledger bridge, later-stage executors, and renderer adapter are intentionally absent. The activation flag is off and migration 135 is unapplied.
  - Later recipe: after Ryan separately authorizes deployment, use the sanctioned zero-active-work drain. Then build a short paid proof under a fresh exact cumulative approval and review the storyboard beside the finished sequence before any longer film.
  - Expected result: only storyboard-approved and verifier-approved shots enter Remotion; dialogue, third-person exposition, and silent action form one understandable through-line; no stale approval or hidden helper spend is reused.

- [ ] **Paid five-minute BYOK media substitution.**
  - Proof reached now: the versioned provider-opaque manifest, real renderer adapter, complete 300.000-second synthetic master, exact artifact verification, source-frame/audio determinism, representative 16:9 and 9:16 inspection, every 4:45–5:00 reveal second, and FFmpeg fallback are accepted locally without provider calls. No paid flagship footage exists.
  - Later recipe: refresh the accepted shared estimator immediately before generation. Only if Ryan separately approves the exact current quote with a hard `$15` cap may actual generated section media/audio/captions replace the synthetic fixtures through the same immutable manifest. Revalidate plan hash, quote-input hash, approval hash, integer film/section seconds, ordered section IDs, media/provenance hashes, and current cap before scheduling.
  - Expected result: actual assets improve the synthetic witness/source fixtures without rebuilding the composition; no provider/model internals reach Remotion; any changed duration, order, media identity, caption timing, model/provenance, or quote clears approval and fails before spend.
  - Cross-reference: checklist M3-5 and M3-6.

- [ ] **Remote publication, live migration, deployment, upload, and release.**
  - Proof reached now: the local M3 final sweep and independent review are accepted on isolated branch `agent/storyengine-remotion-showcase`; no push, PR mutation, migration, deployment, Redis/config change, Drive write, upload, or publication occurred.
  - Later recipe: Ryan must separately approve each boundary: push/draft PR; any disposable/live migration; deployment/restart/config change; Drive/upload/public release; merge. Use the sanctioned drain/deploy path only after approval and never touch Redis as part of this renderer proof.
  - Expected result: FFmpeg remains the production fallback until the Remotion proof is explicitly accepted; deployment preserves first-user Custom Film truth and no fifth public card appears.
  - Cross-reference: checklist M3-6.

## Previous deferred verification

# Deferred verification — Custom Film composer (Milestone 2)

- [ ] **Paid mixed-section provider proof.**
  - Proof reached now: the complete local/no-spend milestone is independently accepted through `682f3e12`. The immutable runtime consumes exact integer section seconds and resolved per-section dimensions only after tenant-key, drain, claim, current-cap, and exact-approval revalidation; the provider-operation journal and compositor bind current script, voice, asset, provenance, timing, caption, output, storage, and charge truth without provider-caller `custom_film` branches. A production-build browser walkthrough proved natural chat, creator-safe ordered sections, itemized BYOK estimate/cap, exact approval, section progress, and separate recipe save with no fifth selector. The deterministic synthetic four-section film is exactly 8.000 seconds, 1920x1080 at 24 fps, audible, visibly captioned, tagged `mul`, four-frame distinct, and byte-identical on rerender; human inspection also caught and fixed a Unicode caption glyph defect. Full backend proof reached 2875 passes with the exact unchanged 14-failure/one-collection-error baseline; no real provider credential or paid media call was used.
  - Later recipe: after the separate draft PR passes no-spend review, refresh the accepted five-minute showcase quote through the current shared estimator. If it remains $5.57 with a hard $15 cap, Ryan may explicitly authorize the exact BYOK run. Compare all 31 still, 28 clip, and 5 voice operations plus final artifact and ledger rows with the approved section bill of materials; any price, count, model, duration, or plan change must clear approval and produce a new quote.
  - Expected result: each section uses its compiled knobs and user-owned credentials; the final film preserves order, transitions, audio, captions, and aspect; actual ledger rows reconcile with the estimate; no StoryEngine-funded key or unapproved retry is used.
  - Cross-reference: checklist M2-3 through M2-5 and M2-7.

- [ ] **Production migration, deployment, and first-user smoke.**
  - Proof reached now: migrations 122–128 and matching fresh schema cover the Custom Film plan/section/assignment, approval/runtime/provider journal, assembly, and immutable tenant-recipe contracts. Static schema parity, migration-source tests, fake concurrency/adversarial tests, and independent reviews pass, but no migration was applied to a live PostgreSQL database. The local production-build browser smoke passed over real frontend components and accepted backend contracts. PR #459 remains the separate Milestone 1 dependency; this Milestone 2 branch has deliberately not been pushed and no draft PR, live migration, or deployment is authorized.
  - Later recipe: after Ryan approves the branch push/draft PR and both milestones are reviewed into a valid dependency order, apply migrations 121–128 twice to a disposable PostgreSQL database and compare every table, column, constraint, index, trigger, policy, and grant against `schema.sql`. Run two-tenant RLS/write-denial, backend-role revision immutability, approval-consume/runtime exactly-once concurrency, recipe rename/archive/reuse, assembly retry/readback, and delete-cascade proof. Only after separate deployment approval, drain production, deploy through the sanctioned path, verify health, and walk the no-paid first-user path before authorizing any provider stage.
  - Expected result: Custom Film stays absent from the four-card public selector; chat shows the section plan and BYOK estimate; stale approval cannot dispatch; saved recipes are tenant-private; backend/frontend return healthy and drain returns to normal.
  - Cross-reference: checklist M2-1, M2-3, M2-6, and M2-7.

- [ ] **Reusable-profile live persistence proof.**
  - Proof reached now: migration 128, the fresh schema, and accepted fake/transaction tests implement tenant-owned topic-free recipes, active name/signature uniqueness, immutable body/version/history, fresh novelty revalidation, separate save confirmation after held or legitimately consumed approval, atomic user/assistant audit, and exact fresh unapproved reuse. The real browser flow proved the separate post-approval save interaction, but no live PostgreSQL row was written.
  - Later recipe: after approved disposable/live migration, compose a genuinely mixed plan, confirm Save separately, reuse it for a different subject, and query through the sanctioned read-only DB path to verify the stored recipe contains roles/proportions/knobs/provenance but none of the first video's title, subject, script, sources, or rationale prose. Race the same signature/name from two sessions, attempt access from a second tenant, rename/archive, then reuse the active latest version.
  - Expected result: the second save is recognized as an existing recipe, the second tenant cannot read it, and reuse creates a new instantiated plan without mutating the saved version or starting generation.
  - Cross-reference: checklist M2-1, M2-2, and M2-6.

# Deferred verification — Beta UX + four public production styles (Milestone 1)

- [ ] **Paid four-style shape proof.**
  - Proof reached now: the four versioned public profiles and immutable per-video snapshot are implemented. No-spend runtime tests prove each dimension contract reaches the existing render/script/visual/dialogue seams; a roughly 700-word/50-sentence investigative proof plans 50 frames; the desktop-canonical Power Doctrine script profile is byte-identical to the merged copy and the live coverage path preserves cue + image prompt → image → stored motion prompt → clip consumption; Photo Documentary retains its existing three-view/two-required Ken Burns contract; tenant-only key gates reject a service environment fallback. All first-party form and home-chat entries require the same no-default four-card selector, calculate media counts from duration/profile, display the BYOK/quote boundary, and send the chosen ID. Docked and post-create chat display the persisted profile plus actual stage plan, consume live SSE, and receive script/voice and real image-count task messages. The local no-spend browser walkthrough proves the four creation choices, co-pilot stage/progress truth, animated finish actions, Photo Documentary's static finish, and Drive warning with no console errors; it also caught and led to removal of an animated counter and motion-prompt control from the static surface. The final focused suite passes 39/39, the broader runtime suite 358/358, M4's focused suite 71/71, and the final 34-route build plus standalone TypeScript pass. The complete backend run passes 2,602 tests with the exact known base failure set of 14 failures plus one collection error. No provider call has been made.
  - Later recipe: after the draft PR passes no-spend review and Ryan approves a quoted budget, create one shortest-supported video with each public style using the tester’s own provider keys. Confirm Bilingual Character Animation uses two-language dialogue plus dubbing; Simple-Language Animation uses clear single-language animated dialogue; Photo Documentary uses the canonical shared static profile with multiple stills and Ken Burns motion; Animated Investigative Documentary produces roughly one image and clip per meaningful visual cue. Compare the displayed pre-spend estimate with the resulting generation ledger and record discrepancies.
  - Expected result: all four videos retain the chosen label/description across creation, co-pilot, and finish; their asset shapes match the selected profile; no StoryEngine-owned credential pays for any provider call.
  - Cross-reference: checklist M1–M4 and M6.

- [ ] **Production deployment and first-user smoke.**
  - Proof reached now: migration 121 and the fresh schema pass focused schema-drift checks, but the migration has deliberately not been applied to a live database and deployment is not authorized. The finish workspace shows style identity, static-vs-animated output truth, finish-time sound/voice order, full-width live progress, and visually distinct full-video/per-scene animation. The same disconnected-Drive warning reaches all creation paths through the shared selector, the finish workspace, and Settings. The local no-spend first-user browser walkthrough proves those surfaces with no console errors or warnings; the final focused checks, standalone TypeScript, 34-route production build, and backend baseline comparison pass. Draft PR #459 contains the verified Milestone 1 implementation.
  - Later recipe: after PR merge and Ryan’s separate approval, confirm a quiet production window with `scripts/se.sh drain-status`, deploy through `scripts/se.sh deploy <session-name> --with-frontend`, verify migration 121 created `production_style_profiles` plus all three `videos.production_style_*` columns, verify `scripts/se.sh health`, then run the first-user path from creation through finish without confirming a paid stage.
  - Expected result: all four catalog rows are active and BYOK-only; backend and frontend are healthy; the required style selector, docked live progress, finish-page clarification, and Drive warning are visible; no provider generation or upload begins.
  - Cross-reference: checklist M3–M6.

## Milestone 2 is intentionally separate

Custom Film, per-section knob application, the chat-hidden planner, and its mixed-style stress render are out of Milestone 1. They require a new Maestro Definition of Complete and a separate PR after this one is reviewed.

# Deferred verification — Application drain mode

Nothing is deferred for drain mode. The no-spend live proof completed on 2026-07-23: draining preserved healthy reads, rejected a synthetic generation start with the structured retryable contract, left review traffic outside the drain, restored normal mode, and the automatic deploy wrapper completed drain/wait/restart/verify/undrain with no force and no active work.

## Previous Anton DVsU gates

Nothing is being treated as silently skipped. These checks require Ryan’s later approval because they spend money or change production.

- [ ] Paid three-view proof on one aircraft.
  - Proof reached now: local tests and a synthetic render prove the data, timing, overlay, and motion contract without external generation.
  - Later recipe: after deployment, open Anton’s DvsU video, choose one already researched aircraft, request **Redraw** in Pictures, review the displayed quote, then explicitly confirm. Expect 2–3 approved views grouped under that aircraft: three-quarter identification, elevated/top-oblique, and a detail view. A run with fewer than two approved views must stay incomplete.
  - Cross-reference: checklist C1, C3, C4.

- [ ] Production render and Anton visual review.
  - Proof reached now: a short local synthetic MP4 is rendered and frame-inspected for card content, multi-view rotation, and smooth full-duration motion. Production deployment is also verified at revision `3a980674` with backend healthy and frontend HTTP 200.
  - Later recipe: create the new Anton DVsU video, explicitly approve its quoted paid stages, and render one regenerated aircraft proof. Expect one animated title card per aircraft, 2–3 rotating views, alternating slow push-in/pull-out moves, and no visible jump, lateral wander, freeze, or wobble. Do not upload to YouTube until Anton has reviewed the production render.
  - Cross-reference: checklist C2, C3, C4.
- [ ] Deploy: code fix reaches prod only after Ryan runs `scripts/se.sh deploy` (push to
      main does NOT restart the backend). Recipe: `se deploy` from the Mac, then
      `se health`. Cross-ref: checklist C3.
- [ ] Post-deploy live proof: re-run `images(fc73860c-a9af-444f-95a5-7f86d60503e0, scene=8)`
      (XB-35, ~$0.03, quote→confirm) and visually verify the render is a FLYING WING.
      Expected: image-to-image from a real XB-35 photo; asset prompt carries "[ref: ...]".
- [ ] Fail-closed proof on prod: attempt images for a machine with no reference anywhere
      (or temporarily empty cache row) → scene must persist status='blocked_no_reference'
      and NO image generated / no spend.

# Deferred verification — C1 per-card parallel clips (feat/per-card-parallel-clips)

Backend enabler chunk: POST /api/pipeline/clip/{video_id} accepts a SET of asset ids
(`asset_ids`, comma-separated or repeated) and runs them concurrently via the existing
CLIP_CONCURRENCY fan-out, without 409-blocking other manual per-card runs. Full detail,
the exact concurrency mechanism, and unit/functional test proof are in the branch's
commit message and PR description — this file only tracks what CANNOT be proven in the
sandbox (no live DB, no live Kie/Grok API, no prod).

- [ ] **Live multi-card proof (real spend, ~$0.05-0.15 for 2-3 short clips).** After
      `se deploy`: open a video with 3+ un-clipped final pictures in the Scenes tab, tap
      Run/Re-run on 2-3 different cards in quick succession (this chunk is BACKEND only —
      the UI doesn't fire multiple requests yet; use curl or the browser devtools network
      tab to fire 2-3 concurrent `POST /api/pipeline/clip/{video_id}?asset_id=<id>`
      requests, one per id, back to back). Expected: NONE of the 2nd/3rd requests return
      409; all requested cards end up with a video_clip_url; `se db "SELECT id, video_id,
      created_at FROM generation_ledger WHERE video_id='<id>' AND stage='clip' ORDER BY
      created_at DESC LIMIT 10"` shows exactly one ledger row per animated asset (no
      duplicates = no double-spend).
      Recipe (replace VIDEO/TOKEN/ASSET_A/ASSET_B):
      ```
      TOKEN=$(cat /tmp/se_token)
      curl -s -X POST "https://storyengine.dev/api/pipeline/clip/VIDEO?asset_id=ASSET_A" \
        -H "Authorization: Bearer $TOKEN" &
      curl -s -X POST "https://storyengine.dev/api/pipeline/clip/VIDEO?asset_id=ASSET_B" \
        -H "Authorization: Bearer $TOKEN" &
      wait
      ```
      Neither call should return `{"detail":"Task already running"}`.
- [ ] **Full-build-vs-manual-run live proof.** While a manual card tap (above) is still
      animating, try "Animate this scene" or the full "Animate" button on the SAME video
      in the UI → must 409 ("Task already running"), proving a full build still waits for
      an in-flight manual run rather than racing it (the "clip_manual blocks/blocked-by
      main" half of the lane rule — see routes/pipeline.py's `_is_task_active`
      "clip_manual" branch and `_manual_clip_begin`/`_manual_clip_finish`).
- [ ] **Cross-process gap (not new to this chunk, just newly relevant):** the
      `clip_manual` lane and the `clip_asset_claims` per-asset guard are BOTH in-process
      only (module-level Python dicts), same as the pre-existing `_running_tasks`/
      `_side_lanes` dicts they extend. If StoryEngine ever runs more than one API server
      process/pod without a shared cache (Redis, or a `generation_claims`-style DB table),
      two manual clip requests landing on DIFFERENT processes would not see each other's
      claims and could both animate the same asset. Today's deploy is single-process
      (`se deploy` kills+revives one uvicorn), so this is inert — flag if that ever
      changes. If it does, the fix is the same pattern `generation_claims.py` already
      uses (a DB-backed advisory-lock claim) applied per-asset instead of per-stage.
- [ ] **C3 note — image redraw fan-out (requirement 5, deliberately NOT built here):**
      `POST /api/pipeline/redraw-image/{video_id}?asset_id=` (routes/pipeline.py, calls
      `scripts.coverage_to_app.redraw_asset_image`) takes exactly ONE required `asset_id`
      today — no candidate SQL, no semaphore fan-out, no `asyncio.gather`, unlike the clip
      route. Extending it to a set is a real feature (new fan-out + its own concurrency/
      claim story for image regeneration, likely wanting the SAME clip_asset_claims-style
      per-asset guard, or a sibling `redraw_asset_claims`), not a trivial copy of this
      chunk's pattern — left for chunk C3 rather than rabbit-holed here.
- [ ] **UI status-pill accuracy during overlapping manual runs (cosmetic, not a spend/
      safety issue):** `routes/pipeline.py`'s `_running_tasks` dict is one slot per
      (tenant, video) — when 2+ manual clip runs overlap, whichever run's `_set_task_status`
      write landed last "owns" the status-poll pill, and `_clear_task_status`'s lane check
      means an earlier-finishing run's cleanup can blank the pill while a later run is
      still animating. The underlying spend/clobber safety (clip_asset_claims) is unaffected
      — this only affects what the polling UI displays mid-run. Worth a look when the
      frontend chunk (fires several manual requests) lands, if the UI needs a truthful
      "N of M cards animating" indicator rather than one shared pill.
      **C2 note:** the frontend chunk below deliberately sidesteps this for its OWN
      dispatches — it coalesces into one call and never fires a second overlapping call
      from the same tab (queues instead, see below) — but the pill-multiplexing risk
      above still applies if a SECOND tab or an agent fires a manual run at the same time.
      Flagged again in C2's own list below.

# Deferred verification — C2 frontend per-card coalescing (feat/per-card-parallel-clips)

Frontend chunk: `frontend/src/hooks/use-clip-trust-ladder.ts` (`animateOne`,
`dispatchPendingClips`, `pendingClipRef`, `queuedClipIds`) + the SegmentCard wiring in
`frontend/src/components/production/ScenesWorkspaceTab.tsx`. Per-card Run/Re-run now
queues into a Map, debounces ~500ms (capped at 2000ms of continuous clicking), and fires
ONE `POST /api/pipeline/clip/{video_id}?asset_ids=a,b,c` (or the original singular
`asset_id=` for a lone click) instead of blocking a second click while the first is in
flight. `npx tsc --noEmit` and `npm run build` both pass clean (see PR/commit for output).
No live backend, DB, or paid API was reachable in this sandbox — everything below needs a
real browser against a real video.

**What IS verified — a documented code trace (no test framework installed; see note at
bottom on why one wasn't added):**

- *N clicks → one call.* `animateOne` (use-clip-trust-ladder.ts ~176-194) never dials the
  network itself — it only mutates `pendingClipRef` (a plain `Map<id, force>`) and
  (re)arms `clipFlushTimerRef` via `setTimeout(..., CLIP_BATCH_DEBOUNCE_MS)`. Every
  additional click inside that window clears and re-arms the SAME timer
  (`if (clipFlushTimerRef.current) clearTimeout(...)`), so only the LAST click's timer
  ever fires. When it does, `dispatchPendingClips` (~149-170) drains the whole Map in one
  shot: `Array.from(pendingClipRef.current.entries())`, builds one `params` object —
  `asset_ids: ids.join(",")` for 2+, plain `asset_id: ids[0]` for exactly one — and makes
  exactly one `startClipTask` → `runPipelineStage` → one `fetch` call. Clicking 3 cards
  180ms apart produces 1 network call with 3 ids; clicking 1 card produces 1 call with the
  original singular shape.
- *queued → running → done/failed.* `queuedClipIds` (state, mirrors `pendingClipRef`'s
  keys) is set the instant a card is clicked (~180) and cleared the instant a batch is
  actually dispatched (~159, inside `dispatchPendingClips`, BEFORE the network call) —
  so a card is "queued" from click until dispatch, then `generatingClipIds` takes over
  (set inside `startClipTask` right before `runPipelineStage`, ~127) — so "running" from
  dispatch until the shared task-status poll reports completed/failed. SegmentCard
  (ScenesWorkspaceTab.tsx ~2018-2049) renders `isQueued` (Clock icon, dimmed picture, no
  spinner) strictly before `isGenerating` (spinner) strictly before `isFailed` (red "Try
  again") — the three are mutually exclusive by construction (dispatchPendingClips clears
  queued before generatingClipIds is set; onFailed/the C2 reconciliation below only ever
  add to failedClipIds AFTER generatingClipIds is cleared).
- *Never blocked.* The old `if (running) { toast.info(...); return; }` gate that lived at
  the top of `startClipTask` is GONE from the per-card path — `animateOne` has no `running`
  check at all now; only `dispatchPendingClips` checks `runningRef.current`, and if true it
  just leaves the batch queued (no toast, no error) for the running→idle effect (~237-252)
  to retry. `animateScene`/`animateAll` are untouched and still show that toast (by design
  — out of scope, see the C2 task brief).
- *Follow-up batch on free.* The running→idle `useEffect` (~237-252) now has two branches:
  resume-loop (unchanged, "Animate the rest") OR, if that's not active,
  `pendingClipRef.current.size > 0` → `dispatchPendingClips()`. So clicking cards WHILE a
  build is running (or while a previous per-card batch is still in flight) queues them
  silently and they fire the instant the task-status poll observes the slot go idle.
- *Stale-closure fix (found during self-review, fixed before commit):* `startClipTask`'s
  own busy-check originally read the closed-over `running` state, which would have been
  the value from the render that scheduled the `setTimeout`, not "now" — the debounce
  callback fires outside React's render cycle. Fixed by reading `runningRef.current`
  (updated synchronously every render) in both `dispatchPendingClips` and `startClipTask`,
  so the two checks can never disagree. Left as an inline comment at both call sites.

**What is NOT verified (needs a live browser + real video + prod deploy — do NOT deploy
from this chunk):**

- [ ] **Coalescing, visually, in the real UI.** Recipe: `se deploy` this branch's frontend
      (after C2 is merged/reviewed — this chunk does not deploy), open a video with 3+
      un-clipped final pictures in the Scenes tab, open Chrome DevTools → Network, tap
      Run on card A then Re-run/Run on cards B and C within ~1s. Expected: exactly ONE
      `POST /api/pipeline/clip/{video_id}?asset_ids=<A>,<B>,<C>` (or `&force=true` if any
      of B/C already had a clip) — NOT three separate requests. Each of A/B/C should show
      the Clock "Queued…" overlay for well under a second, then the spinner, then either
      the clip or (if it genuinely fails) the red "Try again" overlay.
- [ ] **Partial-failure reconciliation, live.** Force one card in a multi-card batch to
      fail (e.g. a motion-gate-blocked shot with no video_prompt mixed into the same
      click-batch as a normal card) and confirm the failing card gets the red "Try again"
      overlay even though the OTHER card(s) in the same batch succeeded — this is the new
      `onComplete` reconciliation in ScenesWorkspaceTab.tsx (fetches fresh assets after a
      batch completes, marks any id from that batch still missing `video_clip_url` as
      failed) since a mixed-result batch reports overall `status: "completed"` from the
      backend (`pipeline_executor.run_clip_generation`: "completed" whenever `done > 0`,
      never per-asset). Watch for a Network tab GET to `/api/assets` (or whatever
      `getVideoAssets` hits) firing right after the batch's terminal poll.
- [ ] **"Animate this scene" / "Animate the rest" still work unchanged.** Both were left
      untouched code-wise (still call `startClipTask` directly, still toast+block on
      `running`) — confirm this in the live UI: tap "Animate this scene" while nothing else
      is running (should proceed immediately, unchanged), then tap it again immediately
      after tapping a per-card Run elsewhere (should show the existing "Hang on — still
      working" toast, unchanged behavior, since scene/all deliberately were NOT moved onto
      the queue).
- [ ] **Cross-tab / cross-agent overlap.** This chunk only serializes ITS OWN dispatches
      (one call in flight per browser tab at a time — see the transition-effect retry
      above). If a SECOND tab, or an agent via the MCP `animate` tool, fires a manual clip
      run on the same video while this tab has one in flight, the shared single-slot
      task-status pill (flagged in C1's own deferred list above) can still show a
      misleading "done" while the other tab's run is still going. Not a spend/safety bug
      (clip_asset_claims still protects against double-animating an asset) — just a
      cosmetic multiplexing gap C1 already flagged and C2 doesn't fix. Worth a real
      two-tabs-on-one-video test in C4 if that's a workflow anyone actually uses.
- [ ] **Debounce/max-wait timing feel.** CLIP_BATCH_DEBOUNCE_MS=500,
      CLIP_BATCH_MAX_WAIT_MS=2000 (use-clip-trust-ladder.ts) are reasoned defaults, not
      user-tested — confirm 500ms feels responsive (not laggy) for a single-card tap
      (worst case: one click waits 500ms before its own spinner appears, vs. instant
      before C2) and that editing+re-running several cards in a realistic pace (a few
      seconds apart while reading/typing) still coalesces as intended rather than firing
      one request per card.
- [ ] **No test framework installed.** `frontend/package.json` has no jest/vitest/RTL —
      "test" is Playwright (e2e only, needs a live server). Adding one is a real dependency
      change (blocked by the "ask before installing packages" rule this session runs
      under) so C2 shipped a documented trace instead of a unit test, per the C2 brief's
      explicit "test OR trace" option. If a unit-test harness is ever added to this repo,
      `dispatchPendingClips`/`animateOne`'s debounce-and-coalesce logic (pure, ref-driven,
      no DOM) would be a clean first candidate to cover.

# Deferred verification — C1b backend parallel image redraw (feat/per-card-parallel-clips)

Backend enabler chunk, the image-redraw sibling of C1: POST /api/pipeline/redraw-image/
{video_id} now accepts a SET of asset ids (`asset_ids`, comma-separated or repeated,
alongside the pre-existing `asset_id`) and runs them concurrently via a new
IMAGE_CONCURRENCY fan-out (`scripts/coverage_to_app.py::redraw_asset_images`), guarded by
a new `redraw_asset_claims.py` per-asset claim (sibling of C1's `clip_asset_claims.py`) and
a new "redraw_manual" lane (sibling of C1's "clip_manual") in routes/pipeline.py's
`_is_task_active`. This resolves the C3 note C1 left in this file (§"image redraw fan-out,
requirement 5, deliberately NOT built here") — built as its own chunk (C1b) rather than the
originally-numbered C3, since the parent loop resequenced it. Full detail, the exact
concurrency mechanism, and unit/functional test proof are in the branch's commit message
and SYSTEM_STATE.md's §C1b entry — this file only tracks what CANNOT be proven in the
sandbox (no live DB, no live Kie image-gen API, no prod).

- [ ] **Live multi-card proof (real spend, ~$0.10-0.15 for 2-3 GPT Image 2 redraws at the
      2K tier, $0.05 each).** After `se deploy`: open a video with 3+ drawn pictures in the
      Scenes tab, tap Redraw on 2-3 different cards in quick succession (this chunk is
      BACKEND only — the UI doesn't fire multiple requests yet; use curl or the browser
      devtools network tab to fire 2-3 concurrent
      `POST /api/pipeline/redraw-image/{video_id}?asset_id=<id>` requests, one per id, back
      to back). Expected: NONE of the 2nd/3rd requests return 409; all requested cards end
      up with a fresh image_url (and video_clip_url cleared); `se db "SELECT id, video_id,
      created_at FROM generation_ledger WHERE video_id='<id>' AND stage='image' ORDER BY
      created_at DESC LIMIT 10"` shows exactly one ledger row per redrawn asset (no
      duplicates = no double-spend).
      Recipe (replace VIDEO/TOKEN/ASSET_A/ASSET_B):
      ```
      TOKEN=$(cat /tmp/se_token)
      curl -s -X POST "https://storyengine.dev/api/pipeline/redraw-image/VIDEO?asset_id=ASSET_A" \
        -H "Authorization: Bearer $TOKEN" &
      curl -s -X POST "https://storyengine.dev/api/pipeline/redraw-image/VIDEO?asset_id=ASSET_B" \
        -H "Authorization: Bearer $TOKEN" &
      wait
      ```
      Neither call should return `{"detail":"Task already running"}`. Also try the NEW
      multi-id shape in one call: `POST .../redraw-image/VIDEO?asset_ids=ASSET_A,ASSET_B`
      and confirm both redraw and the ledger still shows exactly 2 rows (not 1 shared row,
      not 0).
- [ ] **Full-build-vs-manual-redraw live proof.** While a manual redraw (above) is still
      in flight, try "Redo Scene N's pictures" or any full-scene/full-video build on the
      SAME video in the UI → must 409 ("Task already running"), proving a full build still
      waits for an in-flight manual redraw rather than racing it (the "redraw_manual
      blocks/blocked-by main" half of the lane rule — see routes/pipeline.py's
      `_is_task_active` "redraw_manual" branch and `_manual_redraw_begin`/
      `_manual_redraw_finish`).
- [ ] **Clip run vs. redraw run independence, live.** With a manual clip animate (C1) in
      flight on a video, fire a manual redraw on the SAME video (a DIFFERENT asset) →
      must NOT 409 (the two lanes are independent — see SYSTEM_STATE.md §C1b). Then the
      reverse: redraw in flight, fire a clip animate → must also not 409.
- [ ] **Cross-process gap (inherited from C1, not new to this chunk):** the
      `redraw_manual` lane and the `redraw_asset_claims` per-asset guard are BOTH
      in-process only (module-level Python dicts), same limitation as C1's `clip_manual`/
      `clip_asset_claims`. If StoryEngine ever runs more than one API server process/pod
      without a shared cache (Redis, or a `generation_claims`-style DB table), two manual
      redraw requests landing on DIFFERENT processes would not see each other's claims and
      could both redraw the same asset. Today's deploy is single-process (`se deploy`
      kills+revives one uvicorn), so this is inert — flag if that ever changes. If it does,
      the fix is the same pattern `generation_claims.py` already uses (a DB-backed
      advisory-lock claim) applied per-asset instead of per-stage — same fix C1's own note
      already calls for on the clip side; if this is ever done, do BOTH claim modules at
      once rather than fixing one and leaving the other stale.
- [ ] **Message-text edge case (known, deliberate, low-risk):** a redraw for an
      asset_id that doesn't exist under this (video_id, tenant_id) now returns
      `{"status": "failed", "error": "picture not found"}` for a single id via
      `redraw_asset_images`' own candidate-scoping check, same literal string the old
      direct call produced — but a MULTI-id request where every id is bogus returns the
      new generic `"no matching pictures found for the requested ids"` instead (there is
      no pre-C1b precedent for that shape, since a multi-id redraw request didn't exist
      before). Never reachable from the current UI (which only ever sends a real
      `asset_id` for one card); worth a glance if C3 (frontend) ever surfaces a raw error
      string to the user for this path.
- [ ] **UI status-pill accuracy during overlapping manual redraws (cosmetic, not a spend/
      safety issue) — same pre-existing gap C1 flagged for clips:** `routes/pipeline.py`'s
      `_running_tasks` dict is one slot per (tenant, video) — when 2+ manual redraw runs
      overlap, whichever run's `_set_task_status` write landed last "owns" the status-poll
      pill. The underlying spend/clobber safety (`redraw_asset_claims`) is unaffected —
      this only affects what the polling UI displays mid-run. Same note as C1's own list;
      worth a look together when a frontend chunk for redraw coalescing (this chunk's C2
      counterpart) is built.

# Deferred verification — C3 frontend image redraw coalescing + live cost counter (feat/per-card-parallel-clips)

Frontend chunk, the redraw sibling of C2: `frontend/src/hooks/use-clip-trust-ladder.ts`
gained a second, parallel track — `redrawOne`, `dispatchPendingRedraws`, `pendingRedrawRef`,
`generatingRedrawIds`/`failedRedrawIds`/`queuedRedrawIds` — mirroring `animateOne`/
`dispatchPendingClips`/`pendingClipRef` line for line (no `force` concept; every redraw call
is inherently a redo). SegmentCard (ScenesWorkspaceTab.tsx) gained matching
`isRedrawing`/`isRedrawQueued`/`isRedrawFailed` props and overlay states. Also added: a
`dispatchInFlightRef` cross-track guard (clip and redraw dispatch now share one "a network
call is mid-flight" ref, closing a same-tick race the running→idle effect could otherwise
hit once two independently-dispatchable queues exist — see the hook's file-header comment
for the full mechanics), and a live-cost-counter tweak (`onProgress` now also invalidates
`["video", video.id]`, the SAME query key the existing header `CostLedgerChip` already reads
`video.total_cost` from — no new component, no new endpoint). `npx tsc --noEmit` and
`npm run build` (34 routes, same as C2) both pass clean. No live backend/DB/paid API was
reachable in this sandbox — everything below needs a real browser against a real video.

**Design note carried over from C1b's own deferred list (its last bullet, above):** the
backend's `redraw_manual` lane genuinely does NOT block a concurrent `clip_manual` run (or
vice versa) — C1b proved that server-side. This chunk deliberately does NOT let the
frontend exploit that: `dispatchInFlightRef` serializes clip and redraw dispatch to at most
one network call at a time, because `_running_tasks[(tenant,video_id)]` is a single slot
that either call's progress callback can overwrite, and letting both race could misfire the
shared `useSharedTaskWatcher`'s completion detection for whichever track is still working.
Within EACH track, multiple cards still fire as one truly parallel `asset_ids=a,b,c` call —
that's what this chunk asked for. A real cross-track proof (queue a redraw AND a clip batch
at the same time and confirm they run back-to-back, not concurrently, without either one's
state going stale) is in the live-browser list below.

**What IS verified — a documented code trace:**

- *N redraw clicks → one `asset_ids` call.* `redrawOne` (use-clip-trust-ladder.ts, added
  after `animateOne`) never dials the network — it only adds the id to `pendingRedrawRef`
  (a plain `Set<string>`, no `force` field needed) and (re)arms `redrawFlushTimerRef` via
  `setTimeout(..., CLIP_BATCH_DEBOUNCE_MS)`, same 500ms/2000ms-cap shape as clip. When it
  fires, `dispatchPendingRedraws` builds ONE params object:
  `const params = ids.length > 1 ? { asset_ids: ids.join(",") } : { asset_id: ids[0] };`
  then `void startRedrawTask(params, ids)` — one `runPipelineStage(videoId, "redraw-image",
  params)` → one `fetch` call, regardless of how many cards were clicked inside the window.
- *The old blocking gate is gone from the per-card path.* The PRE-C3 `redrawOne` (removed;
  see git history) opened with
  `if (running) { toast.info(...); return; }` before ever calling the backend — that
  early-return is GONE from the new `redrawOne`. The only remaining `running`/`runningRef`
  check on the redraw path lives inside `dispatchPendingRedraws`
  (`if (runningRef.current || dispatchInFlightRef.current) return;`) and — exactly like
  clip's — it does NOT toast or error, it just leaves the batch queued (`isRedrawQueued`)
  for the running→idle effect to retry once the slot frees. `startRedrawTask` still carries
  a `runningRef.current` guard + toast, but that path is unreachable from the coalesced
  per-card click (the caller already checked the same ref synchronously); it exists only in
  case a future direct caller (mirroring `animateScene`/`animateAll`'s relationship to
  `startClipTask`) ever calls `startRedrawTask` without going through the queue — none does
  today.
- *Singular `asset_id=` still works for a lone click.* `dispatchPendingRedraws`'s
  `ids.length > 1 ? {asset_ids: ...} : {asset_id: ids[0]}` branch is byte-identical in
  shape to the PRE-C3 single-target call (`{ asset_id: asset.id }`) for the `ids.length ===
  1` case — a lone Redraw tap still produces
  `POST /api/pipeline/redraw-image/{video_id}?asset_id=<id>`, exactly the route's
  documented "single-target passthrough" path (`routes/pipeline.py`'s
  `run_redraw_image`/`_normalize_manual_redraw_ids`, confirmed by reading the route: `asset_id
  = redraw one card (unchanged single-target path)`).
- *queued → running → done/failed, mutually exclusive.* SegmentCard's overlay order
  (ScenesWorkspaceTab.tsx, the "State overlays" block) now checks, in order: `(isQueued ||
  isRedrawQueued) && !isGenerating && !isRecropping && !isRedrawing` (Clock, dimmed) →
  `(isGenerating || isRecropping || isRedrawing)` (spinner, label swaps on which) →
  `isFailed && !isGenerating` (clip's red "Try again") → `isRedrawFailed && !isFailed &&
  !isGenerating && !isRecropping && !isRedrawing` (redraw's own red "Redraw failed — try
  again", with its OWN `onClick={(e) => {e.stopPropagation(); onRedraw();}}` — deliberately
  NOT folded into the clip overlay, since clicking through to the card's `onTap` would
  wrongly trigger a clip animate instead of a redraw retry for a redrawn-but-failed
  picture). `isRedrawQueued`/`isRedrawing`/`isRedrawFailed` are set/cleared by
  `dispatchPendingRedraws` (clears queued before dispatch), `startRedrawTask` (sets
  generating before the call, clears on failure), and ScenesWorkspaceTab's `onComplete`/
  `onFailed` (clear generating, conditionally add to failed) — same lifecycle shape as
  clip's three states, verified by reading each setter's call site.
- *Partial-failure reconcile, via message parsing (NOT a DB diff — see why below).*
  `redraw_asset_images` (coverage_to_app.py) reports overall `status: "completed" if
  redrawn or not failed else "failed"` — same partial-failure gap C2 found for clips. Unlike
  clip, redraw has no field like `video_clip_url` to diff a before/after fetch against — the
  storage path is deterministic (`_stable_url` overwrites the same
  `{video_id}/coverage/S{scene}_i{index}.png` path every time), so `image_url` stays
  byte-identical whether the redraw succeeded or not, and `GET /{video_id}/assets` doesn't
  select `updated_at` (confirmed by reading `routes/videos.py::get_video_assets`'s SQL).
  Instead, ScenesWorkspaceTab's `onComplete(message)` now parses the completion message
  redraw_asset_images itself builds — `errors.append(f"S{r['scene']}.{r['image_index']}:
  {e}")` per failed picture, joined into the batch's message — via
  `message.matchAll(/S(\d+)\.(\d+):/g)`, and matches the extracted (scene, image_index)
  pairs against `finishedRedrawIds`' underlying assets (looked up in the already-fetched
  `assets` array) to mark exactly those ids failed. Known, accepted gap: the backend
  truncates that message at 400 chars (`errors[:400]`... `'; '.join(errors)[:400]`), so a
  batch with enough failures could omit a later label — that card would then silently read
  as succeeded. `onFailed` (overall-failure case, no partial parsing needed since `redrawn
  === 0` there) marks every dispatched id failed directly.
- *Cross-track guard closes a real synchronous race.* Before `dispatchInFlightRef` was
  added, the running→idle effect could call `dispatchPendingClips()` then
  `dispatchPendingRedraws()` in the SAME synchronous tick — `startClipTask`/`startRedrawTask`
  don't call `markStarted()` (which is what flips `running`/`runningRef`) until AFTER their
  `await runPipelineStage(...)` resolves, so `runningRef.current` is still `false` for the
  whole synchronous portion of the first dispatch, meaning the second dispatch's own
  `if (runningRef.current) return;` check would NOT have caught it — both could have fired
  concurrently. `dispatchInFlightRef.current = true` is now set synchronously (before the
  `await`), read by BOTH dispatch functions, and reset in a `finally` inside `start*Task`
  once the call settles — confirmed by reading the exact sequencing (no test framework
  available to exercise the timing directly; this is a static trace of the code, not a
  run).

**What is NOT verified (needs a live browser + real video + prod deploy — do NOT deploy
from this chunk):**

- [ ] **Redraw coalescing, visually, in the real UI.** Recipe: `se deploy` this branch
      (after review — this chunk does not deploy), open a video with 3+ drawn pictures in
      the Scenes tab, open Chrome DevTools → Network, expand 3 different cards' "Image
      prompt" accordions and click "Redraw picture" on each within ~1s (or edit the prompt
      text first — the save-then-redraw path via the same button). Expected: exactly ONE
      `POST /api/pipeline/redraw-image/{video_id}?asset_ids=<A>,<B>,<C>` — NOT three
      separate requests. Each card's picture should show "Queued…" (both the full-card
      overlay and the button label) for under a second, then the spinner ("Redrawing…"),
      then either the fresh picture or (if it genuinely fails) the red overlay/button
      reading "Redraw failed — try again".
- [ ] **Singular click still fires solo.** Redraw exactly ONE card with nothing else
      queued; confirm the request is `?asset_id=<id>` (not `asset_ids=`) in the Network
      tab, matching the pre-C3 shape exactly.
- [ ] **Partial-failure reconcile, live.** Force one card in a multi-card redraw batch to
      fail (e.g. temporarily blank its image_prompt server-side, or pick a scene/index
      combo likely to trip a content-policy rejection) mixed with a normal card in the same
      click-batch, and confirm ONLY the failing card gets "Redraw failed — try again" while
      the other card shows its fresh picture — this is the message-parsing reconcile in
      ScenesWorkspaceTab's `onComplete`. Watch the Network tab's `/api/pipeline/task/{id}`
      poll responses for the completion message and manually confirm it contains
      `S<scene>.<index>:` for the failing card.
- [ ] **Redraw retry click calls the RIGHT action.** With a card in the `isRedrawFailed`
      state, click anywhere on the red overlay (not just the button) and confirm the
      Network tab shows a NEW `redraw-image` call for that asset — NOT a `clip` call. This
      is the overlay's own `stopPropagation` + direct `onRedraw()` call, added specifically
      because falling through to the card's `onTap` would have called `animateOne` instead
      (wrong action) for a redraw failure.
- [ ] **Cross-track serialization, live.** Queue a redraw batch (2+ cards) AND a clip batch
      (2+ different cards) as close together as possible (e.g. two browser tabs, or very
      fast alternating clicks). Expected: only ONE of the two batches' network calls fires
      first; the other stays queued (`isQueued`/`isRedrawQueued` showing on its cards) until
      the first batch's task-status poll reports done, at which point the running→idle
      effect fires the second batch. Neither should ever show 0% progress forever or get
      silently dropped. This is the `dispatchInFlightRef` behavior described above —
      unverified live because it requires precise timing a sandbox can't reproduce without
      a real network round-trip.
- [ ] **Live cost counter, actually climbing.** Recipe: open a video's Scenes tab with the
      header visible, note the "Est. → Actual" `CostLedgerChip` reading, kick off a
      multi-card clip or redraw batch, and watch the "Actual" number over the next
      10-15 seconds. Expected: it climbs incrementally (not just once at the very end of
      the whole batch) — each individual clip/redraw that lands calls
      `record_ledger_entry`, which bumps `videos.total_cost` immediately
      (`routes/videos.py`'s `/ledger` endpoint docstring), and `onProgress`'s new
      `invalidateQueries({queryKey: ["video", video.id]})` (added this chunk) refetches
      that number on the same ~3s task-poll tick the asset thumbnails already refresh on —
      so it should visibly tick up more than once per batch, not just jump at the end.
      Compare against the ledger drawer (click the chip) to confirm the per-stage
      breakdown matches.
- [ ] **No test framework installed (same note as C2).** `frontend/package.json` has no
      jest/vitest/RTL — a unit test for `dispatchPendingRedraws`'s coalescing, the
      cross-track `dispatchInFlightRef` race, and the message-parsing reconcile would be
      the natural first candidates if a harness is ever added (all three are pure,
      ref/state-driven logic with no DOM dependency).

# Deferred verification — M6 layered Custom Film orchestration

M6-0 through M6-2 are accepted locally on `agent/storyengine-remotion-showcase`.
The creative master and inspection evidence live under
`remotion-video/out/full-showcase-proof/`; the unrelated ceramic proof lives under
`remotion-video/out/test-results/`. No provider call, paid generation, push, deploy,
upload, or publication occurred.

- [x] **Production-host activation and no-provider proof.** PR #462 deployed production
      commit `3ed9e61a` through the sanctioned zero-active-work drain with
      `--with-frontend --with-remotion`. Backend/frontend/worker/Redis, 140 migrations,
      Chromium/Remotion, storage, frontend HTTP 200, exact renderer hash parity, and
      automatic undrain passed. The host resolved 34 layered recipes across 7,200 frames
      and rendered/inspected the 1920x1080 frame-7080 product composition. One synthetic
      staged-fixture file-hash assertion is FFmpeg-platform-dependent on Linux; it does
      not affect approved source hashing or runtime staging and remains portability debt.
- [ ] **Real creator UI proof.** In the deployed chat flow, submit the exact request in
      `custom-film-flagship-runbook.md`. Confirm the approval card shows four narrative
      sections plus the Director's shot blueprint; each beat must expose creator-safe
      approved media, simultaneous capability labels, transformation, camera, captions,
      sound, exact timing, and the unchanged BYOK estimate/cap without provider/model
      internals. Inspect desktop and 390px widths for clipping and overflow.
- [ ] **Paid BYOK flagship gate.** Paid footage remains unproduced. The next valid
      authorization is Ryan explicitly approving the refreshed five-minute estimate
      (currently $5.57) with a hard total cap of $15. Approval authorizes only generation
      through the approved plan/recipe identity; upload, publication, and rerolls remain
      separate decisions.
- [ ] **Post-paid creative acceptance.** After a separately approved BYOK run, inspect
      identity/framing of real media, speech and music ducking, bilingual timing, every
      act transition, centered 9:16 excerpts, and every second from 4:45–5:00. Reject any
      provider output or finishing result that no longer matches the approved semantic
      beat recipes or silently changes duration, media, captions, quote, cap, or
      provenance.

# Deferred verification — M9 Scene-by-Scene Control

Nothing is deferred for the no-spend Scene Control mission. Production revisions
`c5b96e0e` and `210a86bf` applied migration 137 and the exact flags through the
sanctioned drain. The live synthetic API/browser proof exercised stale-CAS rejection,
all explicit Scene 1 gates, acceptance-only Scene 2 unlock, and a separate fresh Scene 1
stopped at its read-only exact $0.25 storyboard quote. The canonical generation ledger
remained 148 rows/$25.14 and director schedules/calls/executions plus generation claims
remained zero. Any provider generation, repair, upload, or publication still requires a
separate refreshed exact approval and is not implied by this completion.

## Director Chat Phase 0 (2026-07-24, branch feat/director-chat)

### [CLOSED 2026-07-24] DV-1: Authenticated visual check of `/` and `/pipeline` after @theme tokens
- Proof reached in sandbox: `npm run build` clean (0 errors / 0 warnings / 34 routes); diff on
  `globals.css` is +43/-0, purely additive; `page.tsx` confirmed byte-identical; the four new
  utility classes proven to resolve via `getComputedStyle` (`bg-surface`=rgb(15,20,32),
  `text-ink`=rgb(240,242,248), `border-edge`=rgba(0,212,170,0.12), `rounded-card`=16px).
- NOT reached: a logged-in eyeball pass on `/` (ChatHome) and `/pipeline/[videoId]` confirming
  they look unchanged. The C3 worker's browser sandbox could not fetch the prod API.
- Recipe: `~/economy-fastforward/storyengine/scripts/se.sh devtoken`, then run the frontend dev
  server ON PORT 3000 (see DV-3 — other ports are CORS-blocked), open `/` and `/pipeline/<any
  video id>`, and confirm they render exactly as they did before this branch.
- Expected result: identical appearance. Any color or radius shift means an `@theme` token
  collided with a Tailwind default.
- CLOSED: fresh-eyes verifier reached the authenticated app on port 3000 and confirmed body computed styles are the pre-existing values (bg rgb(5,8,13), text rgb(240,242,248)). No visual change.

### [CLOSED 2026-07-24] DV-2: Write paths behind the harvested sheets
- Proof reached in sandbox: `BoardLightbox`, `ModelOverrideSheet`, `CameraPresetSheet` and 73
  `ShotCard`s all open, render correct data, and close (Escape) on video
  `f32ed182-be1f-4a24-a8de-bb8db4ac88df`, verified by DOM assertion, zero console errors.
- NOT reached: the POST/write paths — actually applying a model override, actually changing a
  camera preset, actually redrawing a shot. Deliberately skipped: they spend money.
- Recipe: on a throwaway video, apply one model override and one camera preset change and
  confirm the value persists after a refresh. Cost: model override and camera preset are
  metadata writes and should be free; do NOT redraw or animate to test this.
- Expected result: the override saves and survives reload, exactly as before the refactor.
- CLOSED (partially): all three sheets confirmed opening with correct data and closing on video f32ed182-be1f-4a24-a8de-bb8db4ac88df. The metadata WRITE path (actually saving a model override / camera preset) is still unproven and stays open as a Phase 1 check.

### DV-3 (INFRA BUG, not a Phase 0 regression): VPS CORS allowlist ignores ALLOWED_ORIGINS
- Found while verifying C2. The live backend's CORS allowlist permits only `localhost:3000`
  and `localhost:3001`; the `ALLOWED_ORIGINS` env var set in the repo's `.env` files is
  silently ignored by the running process. Confirmed by curl preflight against the live
  process, not by reading the env file.
- Consequence: any local dev walk on a port other than 3000/3001 fails with no useful error.
- Not fixed here. Needs a look at how the backend builds its CORS origin list.

### DV-4 (MINOR BUG, not a Phase 0 regression): `npm run dev` ignores PORT
- `package.json`'s `dev` script hardcodes `--port 3001`, so `PORT=3021 npm run dev` silently
  uses 3001. Workaround: `npx next dev --webpack --port <N>`. One-line fix, not done here.

# Deferred verification — D3-53b storyboard sequential through-line

Ryan's complaint: boards/frames play as "a whole bunch of random shots with no real
through line." Diagnosed root cause: `_coverage_system_prompt()`
(`skills/video-pipeline/storyboard/coverage.py`) had no sequencing law for silent/
narration moments (only "pick the moments that carry the scene") and no rule requiring a
bridge shot on a location change — dialogue moments were fine because rule 5 already
forces them into script-turn order. This chunk added rule 4b (causal-chain sequencing +
mandatory "(BRIDGE)" tag on a location change, reusing the EmotionalArc setup→build→turn→
payoff vocabulary from `shared/channel_profile.py`) plus a code-side SEQUENCE LOCK that
stamps each shot's chain position and the previous moment's summary into every draw prompt
(and, since `assets.image_prompt` is stamped verbatim from that same text, into a later
manual `redraw_asset_image` repair call too — the contract-triangle repair leg). No
deterministic gate was built: today's schema has exactly ONE `[SET | ...]` line per whole
scene (no per-moment location field), so "does moment i's location differ from moment
i-1's" isn't a structured comparison — see the `NOT BUILT` comment directly above the
PROP MANIFEST LOCK in `run_coverage()` for the full reasoning.

Everything reached here is $0: `_coverage_system_prompt`/`_coverage_user_prompt` called
directly against fixtures, a stash/pop presence proof, and the full backend + dedicated
`skills/video-pipeline/tests/test_coverage.py` suites. No planner call, no image
generation, no video/scene was touched or regenerated.

- [ ] **Paid planner proof — does a real coverage plan now read as one through-line?**
  Proof reached now: the prompt-level fixtures above prove rule 4b's text reaches the live
  system prompt for both dialogue and silent scenes, and that rule 5 (dialogue script-turn
  order) is byte-unchanged. What is NOT provable without a real LLM call: whether Claude
  actually FOLLOWS the new causal-chain/bridge instruction on a real scene, especially one
  matching the original repro (a scene whose narration moves from inside a sealed space to
  an exterior corridor/hallway partway through).
  - Recipe: use video `686b4651-e495-44be-baf6-97fc6dd527e9` (tenant
    `ee93e6d1-a9cc-44c3-81e9-84adee8329aa`), **scene 1** — confirmed via `se db` (2026-07-28)
    to be the scene with the mid-scene location change: Nyla wakes inside a glass bubble-pod
    then runs down the warren hallway, i.e. the exact pod-interior → exterior-hallway repro
    D3-53's original diagnosis names. **Not scene 2** — that scene is single-location
    dialogue (the elites watching from their viewing room), so there is no location change
    for rule 4b's BRIDGE tag to ever fire on; it can't exercise this fix. Call the MCP
    `storyboards` tool (or `POST /api/pipeline/coverage/{video_id}?scene=1&plan_only=1` —
    the route DOES support a plan-only/no-draw mode, confirmed in `routes/pipeline.py`; and
    as of the D3-59 fix in this commit, `plan_only=1` is now a true dry run — it persists
    nothing to the DB, so it's safe to call against this video without disturbing its
    already-drawn boards or its pending confirm). This step is a single Anthropic text
    call, not an image draw — effectively free (a few cents of LLM tokens), but still needs
    Ryan's go given the "quote the cost, wait for yes" rule for anything that spends against
    workspace API keys.
  - Expected "pass": every adjacent panel pair in the returned plan is either (a) the same
    location as its neighbor and a plausible direct consequence/escalation of it, or (b) an
    explicit "(BRIDGE)" tagged moment showing the exit/travel/arrival between two different
    locations. Expected "fail": any silent cut from one location's moments straight to a
    different location's moments with no bridge tag between them, or moments that read as
    disconnected "pretty shots" rather than a chain.
  - If it fails: the prose-only rule 4b isn't strong enough on its own — revisit whether a
    real per-moment location field (structured gate) is worth the schema change this chunk
    deliberately deferred.

## T3 / T2b / T5b (2026-07-28, branch feat/t3-t2b-t5b, worktree .claude/worktrees/t-lane)

### DV-5: T2b's live curl proof against the REAL DB, from THIS Mac, was blocked by a Supabase pooler error
- Goal: quote a real `curl` against `GET /api/videos/{id}/assets` showing `video_duration`
  in the JSON, using a local backend running this branch's code against the real Supabase
  DB (the code isn't deployed yet, so the already-deployed VPS API can't be used for this).
- What was tried: `backend/.env` copied from the main checkout (real `DATABASE_URL`),
  `uvicorn main:app --port 8020` started from the worktree with the env exported, plus a
  local-only `DEV_MODE=true`/`DEV_TOKEN` auth bypass scoped to the real owner tenant
  (`ee93e6d1-a9cc-44c3-81e9-84adee8329aa`, video `973c9bd6-1fc7-43d8-802a-83a743a48d66`,
  confirmed via `se db` to have real `video_duration` values — 7,6,7,6,9,6,6,10,6,7,7,6 —
  on every one of its 44 coverage assets).
- Every request against that live-DB-connected local backend, including a plain
  `GET /api/health`, returned `"database": false` / a 500 with
  `asyncpg.exceptions.InternalServerError: (ENOTFOUND) tenant/user postgres.rcbobwaldrefnyllhjyo
  not found` (a Supavisor pooler error). Confirmed this is NOT specific to this worker's
  setup: the OTHER active worker's pre-existing local backend on port 8001 (different
  worktree, running before this session started) showed the identical `"database": false`
  at the same time. The VPS's own backend connected fine in the same window (`se health`
  showed `"database": true`) — so this is a Mac-to-Supabase-pooler connectivity issue from
  this machine/network right now, not a project-wide outage and not a credentials mistake
  (same `backend/.env`, same `DATABASE_URL`).
- What WAS proven instead, as the substitute evidence (see the T2b report section for the
  exact commands/output):
  1. `backend/tests/functional/test_t2b_asset_duration_serializer.py` drives the REAL
     `routes.videos.get_video_assets` coroutine with `fetch_all` monkeypatched, asserts the
     SQL literally selects `video_duration`/`assigned_video_duration`, and asserts real
     values (7.0/6.5) and honest nulls both round-trip unmodified. Stash-proofed (fails
     against the pre-fix code with the exact "not in query" assertion).
  2. `se db "SELECT ... FROM assets WHERE video_id='973c9bd6...' AND image_index>=100"`
     independently confirms the DB genuinely holds those real per-clip second values today.
  3. A local mock backend (scratchpad/t_lane_mock_backend.py, zero DB, zero prod traffic)
     serving the exact JSON shape the fixed serializer produces drove the REAL, unmodified
     `TimelineAltitudeView.tsx` in the Browser pane and showed "Real timecodes" + correct
     `0:00/0:05/0:10` ticks — proving the frontend's consuming half of T2b.
- Recipe to close this once local-Mac connectivity works again (or from a machine/network
  that can reach the pooler): `cp storyengine/backend/.env <worktree>/backend/.env`, add
  `DEV_MODE=true`, `DEV_TOKEN=<any string>`, `DEV_TENANT_ID=ee93e6d1-a9cc-44c3-81e9-84adee8329aa`
  to that copied `.env`, `set -a && source backend/.env && set +a`, run
  `uvicorn main:app --port 8020` from `<worktree>/backend`, then
  `curl -H "Authorization: Bearer <DEV_TOKEN value>" http://127.0.0.1:8020/api/videos/973c9bd6-1fc7-43d8-802a-83a743a48d66/assets`
  and confirm `video_duration`/`assigned_video_duration` appear with real numbers in the
  JSON. Expected result: matches the `se db` values already confirmed above.

### DV-6: D3-65's fix (redraw now anchors a non-master shot on its moment's master frame) — 4 real re-rolls, $0.05 each

- Why deferred: the chunk is capped at $0 (code diagnosis + fix + unit tests only). The
  fix is proven at the code level (field-identical-to-coverage assembly, unit-tested,
  stash-proofed — see the D3-65 report) but NOT yet proven on real pixels. This is the
  orchestrator's call to spend the $0.20.
- Mechanism being tested: `redraw_asset_image` (`storyengine/backend/scripts/coverage_to_app.py`)
  now looks up the nearest EARLIER `hero_shot=true` row in the same
  (`video_id`, `tenant_id`, `scene`) — that row IS the failed shot's moment's master frame
  — and attaches its `image_url` as a reference (`cast_refs + [master_url] + env_refs`,
  matching `generate_coverage_frames`' `angle_base` exactly) plus the `_SAME_SUBJECT` text
  guard in the prompt. Before the fix, a non-master redraw got only `cast_refs + env_refs`
  — no shot-specific photo anchor — and regressed toward the scene's one generic
  environment reference regardless of its own correct, full-length text.
- Fixture: video `686b4651-e495-44be-baf6-97fc6dd527e9`, scene 1. Masters at image_index
  100/103/107 (hero_shot=true) are untouched and correct — do NOT redraw them. The four
  broken angles are 101, 102, 108, 109 (all hero_shot=false), saved "before" at
  `storyengine/tasks/evidence/d3-64-fixes/S-01.101/102/108/109.png` with untouched
  neighbors in `context/`.
- Recipe (run from the deployed/merged code, NOT this worktree — this branch is
  uncommitted-to-main by design):
  1. Confirm current DB state per asset first: `se db "SELECT image_index, hero_shot,
     image_url FROM assets WHERE video_id='686b4651-e495-44be-baf6-97fc6dd527e9' AND
     scene=1 ORDER BY image_index"` — the 4 target rows' `image_url` should still be the
     failed-redraw pixels (or whatever they were last set to); masters 100/103/107 must
     show real, non-null `image_url`s (the fix silently no-ops to the pre-fix behavior if
     a moment's master row is missing or has a null `image_url` — that's an acceptable
     fallback, not a bug, but it must not be the reason a re-roll "passes").
  2. One `POST /api/pipeline/redraw-image/{video_id}?asset_id=<id>` call per asset
     (owner token), same as the original failed run — 101, 102, 108, 109, one at a time or
     as `asset_ids=101,102,108,109` in a single call (both paths go through
     `redraw_asset_image` per-asset). Cost: 4 × $0.05 = $0.20 (GPT Image 2 @ 1K, unchanged
     by this fix).
  3. Judge each redrawn frame against its ORIGINAL labeled defect, not against a vague
     "looks better":
     - **101**: must show an MCU **through the glass** (per SETUP B's own prompt head),
       NOT a repeat of frame 100's WIDE pod-interior composition.
     - **102**: must show a **NEUTRAL ECU on Nyla's eyes alone** (per SETUP C's prompt
       head), NOT a medium/wider shot that includes the bed.
     - **108**: must be a **corridor** shot (SETUP E, following master 107's corridor
       establishing shot), NOT the pod bedroom — facing/expression was already correct
       before, so judge location only.
     - **109**: must show **Moment 3's receding-tunnel/corridor beat** (SETUP D, same
       setup as master 107), NOT Moment 2's hand-on-glass beat (that's asset 104's
       content, a different moment entirely).
  4. Pass criteria for the chunk: all 4 redraws land the correct SETUP-tagged composition
     AND correct location for their own moment — 4/4, not "improved but still off." A
     partial pass (e.g. 3/4 correct) means the master-anchor fix is real but insufficient
     alone (candidate next layer: the SETUP anchor for same-setup repeats — 109 shares
     SETUP D with its own master 107, so it already gets fully covered by this fix; but a
     shot whose setup differs from its moment's master's setup, e.g. an INSERT under a
     different SETUP letter, only gets the moment-master photo, not a same-setup one —
     watch for that specific pattern in the judged results before scoping a follow-up).
  5. Record the actual before/after frames under
     `storyengine/tasks/evidence/d3-65-fixes/` (mirroring the `d3-64-fixes/` layout this
     chunk's repro evidence already uses) so the judgment is reviewable, not just narrated.

### DV-7: BOARD LAWS (BOARD-LAWS.md) — a real board generated by the fixed planner, judged against the laws

- Why deferred: this chunk is capped at $0 (recon + PROMPT/GATE/REPAIR legs + deterministic
  parser/gate/repair tests only — see the board-laws build-lane report). Every law's PROMPT
  text and the deterministic gates/repair stamps are proven at the code level (unit tests
  running the REAL planner-prompt-assembly path on fixture directives, asserting the
  emitted text — both the `_coverage_system_prompt` LLM instructions and the FINAL sheet
  text `_plan_sheet_prompts` composes — carries each law's required element; see
  `skills/video-pipeline/tests/test_board_laws.py` and `storyengine/backend/tests/
  functional/test_board_laws_sheet_and_quality_rules.py`), but NOT yet proven against a
  real Claude-planned directive or a real drawn board. Two different things need proving
  and this recipe covers both:
  1. Does the PLANNER LLM (Claude, reading the new `_coverage_system_prompt`) actually
     PRODUCE the multi-location `[LOCSET|]`/`[MATERIAL|]`/`LOCATION:`-tagged output the
     fixtures assume, unprompted, on a real scene — or does it need a nudge/example fix?
  2. Does the DRAWN board (GPT Image 2, reading the final sheet prompt `_plan_sheet_prompts`
     composes from that real directive) actually satisfy the laws a human judges by eye —
     the same rubric BOARD-LAWS.md's own "Method" section describes (per-shot purpose vs
     facing/framing, pairwise axis/eyelines/cut grammar, scene-level causality).

- Recipe (from the merged/deployed code, not this worktree):
  1. Pick TWO scenes from a real (or test) video's script: one that changes location
     mid-scene with a clear exit/arrival beat (to exercise L3/L4/L7/L8/L9/L10/L21), and one
     two-or-more-character dialogue scene (to exercise L5/L6/L12/L15/L16/L17/L22/L27). The
     bubble-pod scenes this law set was researched against
     (`storyengine/tasks/evidence/d3-64-fixes/`) are a ready-made pair if a fresh video
     isn't wanted — scene 1 (pod → hatch → corridor) and scene 2 (the elite viewing hall).
  2. Call the STORYBOARD GATE (`generate_storyboard_sheet_for_scene` via the
     `storyboards`/chat "generate storyboard" path — NOT the old 3×3 grid path) fresh for
     each scene, so the directive is planned live by Claude against the new system prompt,
     not read from an old saved `coverage_directive`. Cost: the sheet-preview draws only
     (GPT Image 2 sheet boards), roughly $0.05-0.15 per scene depending on panel count —
     no full per-shot PICTURES draw needed for this proof.
  3. Before looking at the drawn board, read the SAVED `coverage_directive` text
     (`scripts.coverage_directive`, or the plan-only response) and check it against PROMPT
     leg §1: does it carry `[LOCSET|]` blocks for the multi-location scene (not one
     blanket `[SET|]` line), a `[MATERIAL|]` line if the set is mixed-material, per-moment
     `LOCATION:` tags, motion-capable setup language on the BRIDGE/run moments, and no
     labelled "WORD: ..." directive text inside any panel brief? A planner drift here (the
     LLM ignoring the new instructions) is a DIFFERENT failure than a drawing failure and
     should be logged separately — the fix for it is prompt wording, not the drawing model.
  4. Then judge the DRAWN sheet(s) panel by panel against the FULL rubric BOARD-LAWS.md's
     "Method" section describes, unprompted — not just the laws this chunk targeted:
     per-shot purpose vs facing/framing, pairwise axis/eyelines/cut grammar, scene-level
     causality and style drift. Trace every failure back to its prompt text and classify it
     (the model disobeyed a correct instruction = re-roll; the instruction itself was wrong
     or missing = a law gap this chunk's report should have flagged but didn't, or a new
     law).
  5. Pass criteria: the multi-location scene's board shows NO cross-location prop leakage
     (L3), the exit/hatch is visible before it's used (L7) at a plausible scale (L8), the
     corridor run reads as continuous travel along a visible line (L10), and no panel is a
     duplicate of an earlier one (L21). The dialogue scene's board states a correct,
     consistent headcount and seating order across its wide and its reverse (L17/L22), and
     no panel's caption strip shows leaked directive text (L27). A partial pass — most laws
     hold, a specific one doesn't — is the expected, useful outcome; report it exactly as
     seen, panel by panel, the same way the original free-tuning arc in
     `tasks/evidence/d3-64-fixes/` was judged.
- $0 estimate for the full recipe (2 scenes, sheet previews only, no full picture draw):
  roughly $0.10-0.30 total.

### Recommended follow-up chunk: the film-level scene-boundary pass (L23-L26)

Not built in this chunk, by explicit scope (see the board-laws build-lane report) — only
the RENDERING half exists (`storyboard.coverage.format_boundary_blocks`, threaded as
optional `incoming`/`outgoing` params through `generate_coverage_directive`/
`_coverage_user_prompt`/`_plan_sheet_prompts`). A future chunk needs to build the PASS
itself:
- **Where it would live:** a new module, e.g. `skills/video-pipeline/storyboard/
  transitions.py`, alongside `coverage.py` — NOT inside `coverage_to_app.py`'s per-scene
  loop, because it is explicitly NOT scene-scoped (it reads every scene's boundary at once).
- **When it would run:** once per video, after the script is finalized (scene text stable)
  and before the FIRST scene's storyboard gate call — a scene can't receive its INCOMING/
  OUTGOING blocks until the pass has run. It would need to re-run (at least for the
  affected boundary) whenever an adjacent scene's text changes after an initial run — the
  same "hash the scene text, compare to what a stored plan was built from" pattern
  `coverage_to_app._scene_text_hash`/`coverage_directive_hash` already uses for one-scene
  staleness detection, extended to a boundary's PAIR of scene hashes.
- **What it would read:** every scene's `scene_text`, IN ORDER, for one video — the same
  `scripts` rows the storyboard gate already reads scene-by-scene, but ALL of them at once
  (this is exactly why a scene-scoped planner cannot do this: `generate_coverage_directive`
  only ever sees one scene's `beat_text`).
- **What it would write:** a per-BOUNDARY record (relationship type, OUT description, IN
  description) — most naturally a new column or small satellite table keyed on
  `(video_id, tenant_id, scene_number)` pairs (e.g. `scene_boundary_out`/
  `scene_boundary_in` jsonb columns on `scripts`, one boundary "belongs" to the EARLIER
  scene's row as its OUTGOING half and the LATER scene's row as its INCOMING half — mirrors
  how `coverage_directive` already lives per-scene-row). `generate_storyboard_sheet_for_
  scene` would read its own scene's `incoming`/`outgoing` from that storage and pass them
  straight into the now-already-wired `generate_coverage_directive(incoming=..., 
  outgoing=...)` and `_plan_sheet_prompts(incoming=..., outgoing=...)` calls this chunk
  built.
- **How it would decide relationships:** almost certainly one more Claude call per
  boundary (or one call per video reasoning about all boundaries at once, cheaper but
  coarser) — reading both scenes' text/`[SET|]`/`[LOCSET|]` geography and picking one of
  L24's six relationships plus writing the OUT/IN description text
  `format_boundary_blocks` already knows how to render. `tasks/evidence/d3-64-fixes/
  TRANSITION-PLAN-example.txt` is the worked example of exactly this artifact's shape and
  is the right acceptance target for that future chunk, the same way `scene1_board_prompt_
  CORRECTED_v3.txt` was this chunk's.
- **Cost:** roughly one extra Claude call per scene boundary (N-1 calls for an N-scene
  video) — cheap relative to the per-scene coverage-planning call already made, but real
  spend; scope it as its own $0.05-0.20-per-video chunk, verified the same way DV-7 above
  verifies this chunk (read the produced INCOMING/OUTGOING text before judging any drawn
  pixels).
## Static-docu roster reference-photo loop (2026-07-29)

### 1. Roster panel live progress — real visual walk
PROOF LEVEL REACHED IN SANDBOX: the panel was driven in a browser against the real
backend and the real idle state was confirmed ("17/23 verified"). The RUNNING state
was simulated with a browser fetch mock intercepting the roster-recheck POST and the
task GET. No clean per-card grid screenshot was captured — the browser screenshot
pipeline stalled — an accessibility-tree dump was substituted and did confirm all six
missing cards flipped to the "checking..." badge.
NOT PROVEN: the panel behaving correctly against a genuine multi-minute sweep.
RECIPE:
  1. Open https://storyengine.dev/pipeline/d2e37cd6-521a-43aa-a14d-ce096a783c1e
     on the Designed vs Used channel.
  2. Click "Re-check missing".
  3. EXPECTED: within ~5 seconds the header shows a spinner and
     "Re-checking machine references — N/23 verified so far", the count climbs on its
     own without a page reload, and each still-missing card shows a turquoise
     "checking..." badge instead of the red "missing" badge plus URL box.
  4. EXPECTED on completion: the header settles back to "X/23 verified" on its own and
     the "Re-check missing" button re-enables.
  Note the sweep takes roughly 10 minutes for 23 machines.

### 2. Research contract + gate severity — live path
PROOF LEVEL REACHED IN SANDBOX: unit/function level only. The 23-ship roster shape was
run through _roster_validation directly and confirmed to return passed=true /
needs_review=true and to gate to next_status="ready_for_scripting".
NOT PROVEN: the same behaviour through the live paid `research` verb or the MCP
`submit_research` path against a real database row.
RECIPE:
  1. Run research on a static-docu video whose roster will exceed the runtime pacing
     target (e.g. a 20-minute video that yields 23+ machines).
  2. EXPECTED: the video reaches ready_for_scripting rather than stalling at
     idea_logged, and the roster validation payload carries needs_review=true with the
     pacing complaint in soft_warnings and hard_warnings empty.
  3. Confirm via: se db "SELECT status, research_payload->'unit_roster_validation'
     FROM videos WHERE id='<video id>';"

## D6-1 — canonical cast/style/set inputs inserted verbatim (2026-07-30)

Migration 142 (`video_characters.identity_tag`, `video_environments.material_map`),
the `_resolve_style` precedence contract, the two live L28/L29 bug fixes in
`_sheet_header`/`_plan_sheet_prompts`, the L3/L28/L29 hard gates
(`SheetPromptContractViolation`), the L20 canonical-material-map resolver
(`_canonical_material_line`), the L6 identity-tag preference in
`load_character_bible`, and the redraw_asset_image repair-leg extension were all
proven at unit/function level (34 tests, `tests/functional/test_d6_1_canonical_
inputs.py` + the pre-existing `test_board_laws_sheet_and_quality_rules.py`) —
zero spend, no DB. See the D6-1 chunk report for the stash-proof result and the
before/after emitted-prompt evidence.

### 1. Migration 142 — never applied to any real database
PROOF LEVEL REACHED IN SANDBOX: static review only (read against migrations 046,
051, 115's exact idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` shape) — no
local Postgres was available in this worktree/session to actually run it, and prod
is off-limits per this chunk's zero-spend/read-only constraint.
NOT PROVEN: the migration runs clean against the real schema, or that
`COMMENT ON COLUMN` succeeds against prod's actual grants.
RECIPE:
  1. `se db "SELECT column_name FROM information_schema.columns WHERE
     table_name='video_characters' AND column_name='identity_tag';"` — expect no
     rows (pre-migration state), confirming the column doesn't already exist under
     a different name.
  2. Apply migrations/142_canonical_inputs.sql through this project's normal
     migration runner (NOT raw `se db`, which is SELECT-only per this chunk's
     cost cap) in a real deploy.
  3. `se db "SELECT identity_tag FROM video_characters LIMIT 1;"` and
     `se db "SELECT material_map FROM video_environments LIMIT 1;"` — expect both
     to return NULL for every existing row (the "existing videos keep working with
     NULLs" contract), not an error.

### 2. A real board draw with the canonical fields populated — never drawn
PROOF LEVEL REACHED IN SANDBOX: the composer functions were proven with
hand-built fixture data (`_canonical_material_line`, `_character_identity_line`
via `load_character_bible`'s new identity_tag preference, `_sheet_header`'s
conditional reference clause) — never against a real video with real
`video_characters.identity_tag` / `video_environments.material_map` values and a
real GPT Image 2 draw. This chunk's cost cap forbids spending on this.
NOT PROVEN: an actual drawn board reads the canonical cast tag / material map
correctly end-to-end through the live app, or that PATCH
/api/videos/{id}/characters/{id} and /environments/{id} genuinely persist
identity_tag/material_map through a live server (only reviewed as code, not
exercised against a running FastAPI app + DB).
RECIPE:
  1. On a NEW test video (never 686b4651 — that video is frozen, read-only, no
     exceptions), design + approve one character and one environment.
  2. PATCH /api/videos/{id}/characters/{char_id} with
     {"identity_tag": "red jacket, undercut, mid-20s"}; confirm 200 + the field
     round-trips on GET.
  3. PATCH /api/videos/{id}/environments/{env_id} with
     {"material_map": "the wall is glass from floor to shoulder height; above that
     it is solid metal"}; confirm 200 + round-trip.
  4. Generate a storyboard sheet for one scene in that location. EXPECTED: the
     persisted `scripts.storyboard_prompts` blob contains the identity_tag text
     verbatim in the CHARACTER block and the material_map text verbatim in the
     MATERIAL MAP block — NOT the planner LLM's own paraphrase of either.
  5. Redraw one picture in that scene (`redraw_asset_image` — a paid GPT Image 2
     call, quote the ~$0.05 cost and get a yes first). EXPECTED: the same
     identity_tag/material_map text is echoed in the logged draw prompt (no
     progress/log currently surfaces the exact composed redraw prompt to the UI —
     verify via a temporary print or by reading assets.image_prompt's neighbor
     state before/after, since the composed prompt itself isn't persisted anywhere
     for redraws).

### 3. Known, documented (not silently hidden) gaps — not bugs, just unclosed
  - `_resolve_style` does not consult `style_preset_id`/`production_style_id` —
    a video whose ONLY style signal is a chosen preset (no image_style_override/
    visual_style text) gets the sheet composer's neutral photoreal default while
    the real pictures path (pipeline_executor._resolve_visual_profile_id) renders
    in the chosen preset engine. See `_resolve_style`'s docstring for the full
    trace. Fixing it is a separate, scoped chunk (unify or mirror the two
    resolvers), not attempted here.
  - `_canonical_material_line` for a multi-location scene only emits a clause for
    locations that HAVE an authored `material_map`; a location with none is
    simply omitted from the MATERIAL MAP block (not backfilled from the LLM's
    line) rather than mixing a canonical clause and an LLM clause in the same
    block. Verify by authoring `material_map` for only one of two locations in a
    multi-location scene and confirming the MATERIAL MAP block names only that
    one location.
  - The canonical material-map WIN is wired into `generate_storyboard_sheet_for_
    scene` (the SHEET PREVIEW path) and `redraw_asset_image` (the repair leg),
    but NOT into `run_coverage` in `skills/video-pipeline/storyboard/coverage.py`
    (the real per-shot PICTURES path's own MATERIAL MAP LOCK stamp, which still
    reads only `parse_material_map(directive_text)` — the LLM's line). A video
    whose sheet preview shows the canonical map correctly can still have its real
    drawn pictures stamped with the LLM's paraphrase instead. This is the
    concrete "where I would split it" boundary for a D6-1b follow-up.

## D6-3 — STORY-LAWS S3 (2026-07-29)

Everything provable read-only or by mock was proven in the D6-3 report (25 new tests in
`backend/tests/test_d6_3_story_law_s3.py`, stash-proof, full suite at baseline). These
four things need a live LLM call, a prod migration, or a downstream consumer that does
not exist yet, so none of them could be verified this chunk under the zero-spend /
no-prod-mutation constraint.

### 1. Migration 144 has never actually run against any database
PROOF LEVEL REACHED: static SQL review only (`ADD COLUMN IF NOT EXISTS`, idempotent,
matches migration 141's shape). No local Postgres exists in this repo to apply it to
(no conftest.py DB fixture, no DATABASE_URL in the dev environment) — confirmed by
grepping the backend for a local DB harness before concluding this.
NOT PROVEN: the migration actually applies cleanly to the real schema.
RECIPE:
  1. `se db "SELECT column_name FROM information_schema.columns WHERE table_name='scripts' AND column_name='location'"` — expect zero rows before migration 144 runs.
  2. Apply migration 144 through the normal deploy path (never by hand).
  3. Re-run the same query — expect one row, `location`.
  4. `se db "SELECT scene, location FROM scripts WHERE video_id='686b4651-e495-44be-baf6-97fc6dd527e9' ORDER BY scene"` — expect all 6 rows with `location = NULL`, unchanged from before the migration (proves the NULL-safety claim against the real column, not just by grep-absence-of-consumers).

### 2. Does the model actually comply with the LOCATION: header when asked for real?
PROOF LEVEL REACHED: the prompt text is in place and reaches all three generation call
sites (see report). No real Claude call was made — that would spend money and this
chunk is zero-spend.
NOT PROVEN: real generation output actually opens each scene with `LOCATION: <place>`
at a rate high enough that the GATE rarely fires on legitimate videos, rather than
constantly blocking generation on `needs_review`.
RECIPE:
  1. Generate a script on a cheap/short test video via each of the two generation paths
     (`script` verb on a short animated/narrative video for path a; a modeled/style-
     replicated video for path b).
  2. `se db "SELECT scene, location, left(scene_text,80) FROM scripts WHERE video_id='<id>' ORDER BY scene"`.
  3. EXPECTED: every row has a non-NULL `location`, and `scene_text` never contains the
     literal string "LOCATION:" (proves the header was both supplied and stripped).
  4. If violations are common, the GATE is doing its job (S3 is enforced) but the PROMPT
     leg's wording may need tightening — that would be a follow-up chunk, not a D6-3 bug.

### 3. static_docu is deliberately exempted from S3 — is that the right call?
PROOF LEVEL REACHED: `_resplit_static_scenes` (pipeline_executor.py) rewrites static-docu
scripts rows AFTER path (a)'s act-based generation already ran `create_script_record`
(which DOES extract a location) — the resplit's raw INSERT never carries a `location`
forward, and D6-3 deliberately did not touch it, reasoning that a static documentary's
"scenes" are one-machine unit paragraphs (product reviews), not physical locations, so
S3 doesn't obviously apply. This reasoning was not checked against a real static_docu
script's actual content.
NOT PROVEN: whether static_docu content ever legitimately needs S3 (e.g., a documentary
that stages each machine in a different room/environment, where "location" would matter
for the board layer's L3 after all).
RECIPE:
  1. Read 3-5 real static_docu scripts' scene_text (`se db "SELECT scene_text FROM
     scripts s JOIN videos v ON v.id=s.video_id WHERE v.render_mode='static_docu' ORDER BY random() LIMIT 5"`).
  2. If they never describe a physical setting, the exemption stands as documented.
  3. If they DO (e.g. "In the kitchen, the blender..."), file a follow-up chunk to extend
     the LOCATION header + gate to `_resplit_static_scenes` too.

### 4. Board/render live walkthrough with a NULL-location video after S5 wires it in
NOT APPLICABLE YET — no board or render code reads `scripts.location` as of this
commit (verified by grep, see report's NULL-safety proof), so there is nothing to
walk yet. This entry is a placeholder for whichever chunk wires L3 (BOARD-LAWS.md) to
this column: at that point, re-run the "run it like a user" board/render walk on an
existing pre-migration video (location=NULL on every scene) and confirm boards/renders
exactly as before.

## D6-3b — independent-verifier fixes (2026-07-29)

An independent verifier ran the D6-3 gate live and found four real defects (false
"checked before any DB write" claim for path (a), needs_review silently persisting as
"completed" through the arq worker path, cross_location_text hard-blocking on legal
prose like S1-required transit sentences, and a fourth ungated writer). All fixed on
the same branch except item 5 below, which is filed as its own chunk.

### 5. The fourth writer — `custom_film_production_runner.py`'s `_script` method — is UNGATED, filed as its own chunk
STOPPED rather than implemented: this is the Custom Film / Director Loop generation
path (~700-line method spanning roughly lines 3859-4560), with its own whole-arc AV
screenplay contract, per-section continuity validation across the whole arc
(`_validate_custom_film_av_arc`), dialogue-segment extraction, bilingual/dubbing
language-mode branching, and placeholder/language-tag normalization passes that all
run on `script_text` BEFORE the `INSERT INTO scripts` at line ~4535. Bolting on a
LOCATION-header requirement safely means understanding how it interacts with EVERY
one of those transformations (would a stripped header confuse
`_remove_custom_film_av_empty_audible_placeholders` or
`_canonicalize_custom_film_av_language_tags`? does "scene" here mean the same thing
as `request.section_id`, given the whole-arc barrier operates across MULTIPLE
sections at once?) — genuinely a separate chunk's worth of investigation, not a
same-day addition. `scripts.location` stays NULL for every row this path writes,
which is safe (nullable, unread column) but means S3 does not reach it.
RECIPE for the follow-up chunk:
  1. Read `_script` in full (`storyengine/backend/custom_film_production_runner.py`,
     starts ~line 3859) and `_validate_custom_film_av_arc` to establish whether
     "section" (`request.section_id`) is the right unit to attach a `location` to,
     or whether Custom Film scenes are sub-divided further downstream.
  2. Confirm whether the AV screenplay's dialogue-segment/language-tag/placeholder
     passes would strip or mangle a `LOCATION:` header line if the prompt asked for
     one — test against a real (or synthetic) AV screenplay sample before adding it
     to the live prompt.
  3. Only then add the PROMPT text (reuse `story_laws.SCENE_LOCATION_LAW` — do not
     hand-roll a copy), the parser (`story_laws.extract_scene_location`) before the
     INSERT, the `location` column on the INSERT, and the GATE
     (`story_laws.check_scene_location_law`) at whatever point in this path mirrors
     "before any DB write, per-section" or "after write with cleanup," matching
     whichever write-ordering is actually true here (do not assume — verify, the
     way D6-3b had to correct D6-3's wrong assumption for path (a)).

### 6. Live end-to-end proof that a real `needs_review` script surfaces through the UI via the arq path
PROOF LEVEL REACHED: unit-level, `worker.py`'s `_run_stage` proven directly (mocked
`PipelineExecutor.run_script` returning `needs_review`, asserts `db_persist_task` is
called with `status="failed"` and the violation text as `error`, not `"completed"`).
NOT PROVEN: that a real arq-queued job (Redis up, a genuine S3-violating script) ends
with a `background_tasks` row a real frontend poller reads as "this failed, here's
why" rather than silently showing nothing changed.
RECIPE:
  1. With Redis running locally (`arq storyengine.backend.worker.WorkerSettings`),
     enqueue a `script` job for a cheap test video where the writer's response is
     forced/mocked to omit LOCATION headers (or use a fixture script known to
     violate S3).
  2. `se db "SELECT status, error_message FROM background_tasks WHERE video_id='<id>' ORDER BY created_at DESC LIMIT 1"`.
  3. EXPECTED: `status = 'failed'`, `error_message` contains the S3 violation text
     (not a generic exception string), and `videos.status` never advanced past
     `ready_for_scripting`.

## D6-2 — repair stamps + deterministic assembly for L11/L12/L15/L16/L17/L18/L19/L22 (2026-07-30)

Migration 143 (`assets.shot_location`, `assets.group_arrangement`), seven new
`apply_*` repair-leg functions in `skills/video-pipeline/storyboard/coverage.py`
(nested-frame content, population, group-arrangement/reverse-background —
computed — attention-orientation, diegetic-POV), three new warning-only gates
(L12, L15, L18), and the `redraw_asset_image` fresh-re-derivation extension for
L16/L22 were all proven at unit/function level (23 new coverage.py tests +
4 new redraw-level tests, zero spend, no DB) — see the D6-2 chunk report for the
full per-law route table and the stash-proof result (a real ASSERTION failure
with the implementation stashed, not an ImportError).

### 1. Migration 143 — never applied to any real database
PROOF LEVEL REACHED IN SANDBOX: static review only (idempotent `ALTER TABLE ...
ADD COLUMN IF NOT EXISTS` + `COMMENT ON COLUMN`, byte-identical shape to
migrations 115/140/142) plus a LIVE, free confirmation against prod via
`se db "SELECT column_name FROM information_schema.columns WHERE
table_name='assets' AND column_name IN ('shot_location','group_arrangement');"`
— returned 0 rows, confirming neither column exists yet and migration 143 is
genuinely free to apply. No local Postgres was available in this worktree/
session to actually RUN the migration, and prod is off-limits per this chunk's
zero-spend constraint.
NOT PROVEN: the migration runs clean against the real schema (only static
review + the negative existence check above), or that assets rows written by
`store_scene` actually populate the two new columns end to end against a real
insert.
RECIPE:
  1. `se db "SELECT column_name FROM information_schema.columns WHERE
     table_name='assets' AND column_name IN ('shot_location','group_arrangement');"`
     — expect 0 rows (confirmed above, re-run to catch drift before applying).
  2. Apply `storyengine/backend/migrations/143_per_shot_location_and_arrangement.sql`
     through this project's normal migration runner (NOT raw `se db`, which is
     SELECT-only per this chunk's cost cap) in a real deploy.
  3. `se db "SELECT shot_location, group_arrangement FROM assets LIMIT 5;"` —
     expect both NULL for every existing row (the "existing videos keep working
     with NULLs" contract), not an error.
  4. Generate coverage frames for one NEW scene that has a genuine reverse-setup
     pair (a `[SETUPS|...]` line containing "the matched reverse of X" — the
     planner writes this per the existing rule 17/L16 system-prompt text, so a
     scene with 2+ opposing camera angles on a group is likely to produce one
     naturally; not guaranteed on any single try). EXPECTED: `se db "SELECT
     image_index, shot_location, group_arrangement FROM assets WHERE video_id=
     '<new video>' AND scene=<N> ORDER BY image_index;"` shows a non-NULL
     `group_arrangement` on the establishing shot and its reverse, with the
     reverse's text carrying flipped frame-left/frame-right tokens.

### 2. A real single-shot redraw of an OLD (pre-143) row on a live video — never run
PROOF LEVEL REACHED IN SANDBOX: the decisive test (`storyengine/backend/tests/
functional/test_d6_2_repair_stamps.py`) proves the prompt-construction path with
a MOCKED database row shaped exactly like a legacy asset (no reverse-background
stamp baked in, `group_arrangement` populated only via the new column) — this is
the strongest proof available without spend, but it is still a synthetic fixture,
not a real row.
NOT PROVEN: a REAL pre-143 asset row (e.g. one of the frozen 686b4651 scene-1
rows — READ-ONLY, must never be redrawn per this chunk's hard constraint) run
through the real `redraw_asset_image` end to end with a real ~$0.05 GPT Image 2
call, confirming the emitted prompt visibly carries the fresh L16/L22 text and
that the drawn picture doesn't regress on any OTHER law this chunk didn't touch.
RECIPE (needs Ryan's go — real spend):
  1. Pick a NEW (non-686b4651) video with an existing scene that has a
     reverse-setup pair and at least one group shot.
  2. Temporarily log the exact composed prompt in `redraw_asset_image` (no
     existing log surfaces it) or capture it via a debugger/print before the
     `generate_scene_image_for_model` call.
  3. Call the redraw route for one non-master shot in that scene (~$0.05).
  4. EXPECTED: the logged prompt contains "matched reverse of SETUP" (if that
     shot's setup has a partner) and/or "Group arrangement (canonical): ..."
     text pulled from `assets.group_arrangement`, and the drawn picture is
     judged against BOARD-LAWS.md the normal way (per-shot purpose, axis,
     facing).

### 3. Known, documented (not silently hidden) gaps — not bugs, just unclosed
  - **L18 (A DISCOVERY OBJECT IS PLANTED WITHOUT BEING ANNOUNCED) has NO repair
    leg**, by design — admitted in `check_discovery_object_unremarked`'s
    docstring and the D6-2 commit message. The fact it protects (an object
    staying un-emphasized until its notice beat) is one-off narrative content
    specific to a single moment, not a scene-wide constant that can be captured
    once and repeated the way SET dressing or a headcount can; a naive stamp
    would contradict rule 19's own "shot size legitimately changes as coverage
    moves in" instruction. It got a NEW warning-only gate instead.
  - **`run_coverage`'s real PICTURES path still stamps [MATERIAL|...] from the
    planner's own LLM text, never the canonical `video_environments.material_map`
    column** — this is D6-1c, a pre-existing, separately tracked gap this chunk
    did not touch (it lives in the exact same function this chunk edited, but is
    out of scope for D6-2's mandate).
  - The L16/L22 computed flip (`compute_reverse_arrangement`) is a MECHANICAL
    clause-reversal + frame-side swap, not a semantic rewrite — on a long or
    grammatically unusual arrangement sentence the flipped prose can read
    awkwardly (verified live: a 6-clause fixture produced a technically-correct
    but clunky flipped sentence — see the D6-2 chunk report for the exact
    output). The ORDER and SIDES are always correct; the PROSE QUALITY is not
    guaranteed elegant. Never silently wrong, just occasionally ugly — the
    honest tradeoff of preferring a real computation over a second LLM call.
  - L18's new gate (`check_discovery_object_unremarked`) is SCENE-scoped, not
    per-shot: it cannot confirm the emphasis lands on the same object or
    appears strictly before the notice beat (no per-shot object identity exists
    in today's schema) — it only flags the higher-level co-occurrence.

## D6-4 (STORY-LAWS S1 narrate every location change, S5 resolved, S2/S4
## admitted) — deferred verification

### 1. Migration 144 (`scripts.location`) is NOT applied on the production
database as of this chunk — confirmed live, not assumed
`se db "SELECT column_name FROM information_schema.columns WHERE
table_name='scripts'"` against prod returned 38 columns, no `location` among
them, and `se db "SELECT filename FROM _migrations WHERE filename LIKE
'14%' ORDER BY filename"` shows only `140_...` and `141_...` applied — 142-146
are all still pending. This means D6-3's ENTIRE S3 gate (and by extension
D6-4's S1 canonical leg and the S5 finding) is currently DORMANT on prod: the
code path exists and is correct against a migrated schema, but has never run
against the real column. RECIPE for the actual first live proof, needs a real
deploy (out of scope for this zero-spend chunk):
  1. `se deploy` (this alone triggers `main.py`'s `_run_pending_migrations` at
     startup, which applies 142-146 including 144 — confirm this in the deploy
     logs: `se logs | grep -i migrat`).
  2. `se db "SELECT column_name FROM information_schema.columns WHERE
     table_name='scripts' AND column_name='location'"` — EXPECTED: one row.
  3. Generate ONE new short (1-2 min) video's script through the normal flow
     (modeled or docu path) and confirm via `se db "SELECT scene, location
     FROM scripts WHERE video_id='<new video>' ORDER BY scene"` that every row
     has a non-NULL `location` — proves S3/S5's PROMPT+GATE actually fire
     against a live model call, not just the pure-function tests here.
  4. Deliberately edit that video's scene 1 text via the UI to remove any
     transit language while changing nothing about scene 2's location, save,
     and confirm the response carries a non-empty `story_law_s1_warnings` —
     the first live proof of S1's GATE+REPAIR against a real request, not a
     monkeypatched fake.

### 2. `check_location_transit_law` run read-only against video `686b4651` —
proof level reached, exact output
This chunk's HARD CONSTRAINT forbids touching `686b4651`, so this is the
decisive read-only proof, not a placeholder. Fetched via `se db "SELECT scene,
scene_text FROM scripts WHERE video_id='686b4651-e495-44be-baf6-97fc6dd527e9'
ORDER BY scene"` (the `location` column doesn't exist on prod yet — see item 1
above — so every scene's location is treated as NULL, matching the video's own
real pre-migration state). Feeding the 6 real rows (location=None on all) into
`story_laws.check_location_transit_law` returns `{"location_changes": [],
"warnings": []}` — correctly silent: with no canonical location data at all,
S1 cannot be verified against this video, which is the honest answer, not a
false negative (see `check_location_transit_law`'s own docstring for why this
is by design). `check_scene_location_law` (S3/S5) against the same 6 rows
returns 6 `no_location` violations, `passed: False` — matching D6-3's own
report. NOT PROVEN, and cannot be without migration 144 applied: S1's
canonical leg (comparing two real `location` column values) actually firing
against this video's real data — that requires the column to exist, which per
item 1 it does not yet on prod. RECIPE once migration 144 is live: manually
backfill `686b4651`'s 6 scenes' `location` columns via a plain `UPDATE`
(READ-ONLY constraint is about `scene_text`/regeneration, not adding a
location label to a frozen row for testing — but get an explicit go from Ryan
first since this chunk's brief was unambiguous about not touching this video
at all) and re-run the same read-only check to see the canonical leg produce
real `location_changes` entries.

### 3. `check_cast_consistency_law`'s wiring into `approve_cast` — not
integration-tested against a real request
The route-level GATE leg is proven only by manual code reading plus the pure
`story_laws.check_cast_consistency_law` unit tests
(`tests/test_d6_4_story_law_s1.py`) — `approve_cast`'s own background-task
closure (`routes/characters.py`, the `_run()` function inside the route
handler) was judged too costly to fully monkeypatch for this chunk (it also
does a paid vision pass this chunk must not trigger even in a mocked form
without careful isolation). The `update_character` REPAIR leg IS integration-
tested directly (`test_update_character_surfaces_s4_warning_on_name_edit`),
since that endpoint is synchronous and has no paid calls. RECIPE for the
GATE leg's first live proof, needs a real video with both a script and a cast
member whose name doesn't appear in it:
  1. Pick or create a test video with a script already written.
  2. Design characters normally (`POST .../characters/generate`, ~$0.025/each
     — needs Ryan's go, this is real spend), then rename one via the
     characters tab to something NOT in the script text (e.g. a name the
     writer never used).
  3. Call `POST .../characters/approve`.
  4. `se db` or the task-status poller: confirm the completion message
     contains "Story law S4 advisory" naming that character — the first live
     proof the GATE leg fires from a real HTTP request, not a synthetic
     `check_cast_consistency_law([...], [...])` call.

### 4. S2 (A PAYOFF MUST BE PAID FOR EARLIER) has no gate and none is planned
Not a deferred item in the "will verify later" sense — a permanent admission.
Documented in `STORY-LAWS.md`'s S2 status entry and `backend/story_laws.py`'s
module docstring. Nothing to verify because nothing was built; listed here
only so a future reader doesn't mistake the silence for an oversight.

### 5. D6-1c: the REAL pictures path (`run_coverage`) now prefers canonical
`video_environments.material_map` over the planner's `[MATERIAL | ...]`
prose (L20) — proven only with mocked frames, never a real paid draw
Everything logical was proven for free: `skills/video-pipeline/tests/
test_board_laws.py::test_run_coverage_material_map_canonical_wins_over_
planner_prose` shows the canonical string reaching every shot's
`description` field and the planner's own prose text absent once a
canonical `material_map` exists (a real stash-proof — reverting just the
precedence line makes this test fail on `AssertionError`, not an import
error). `test_run_coverage_material_map_null_canonical_unchanged` proves
byte-identical fallback behavior when `canonical_envs=None` (today's only
production case — all 38 `video_environments` rows have `material_map`
NULL). NOT PROVEN, and can't be without paid spend: that GPT Image 2
actually RENDERS the canonical material text differently than it would
have rendered the old planner prose — i.e. that the string landing in the
prompt changes the PIXELS, not just the prompt text. This chunk's cost cap
was zero spend.

RECIPE for the first live proof (needs Ryan's go — real money):
  1. Pick a test video with an approved environment that has a genuinely
     mixed-material set (part glass, part solid) and NO `material_map` row
     yet (true of every video today).
  2. `se db "UPDATE video_environments SET material_map='<some deliberately
     DIFFERENT boundary than what the planner would improvise, e.g. an
     unusual material like frosted resin or exposed brick> WHERE id='<env
     id>'"` — a free write, no generation triggered.
  3. Run coverage for one scene in that environment (paid — quote cost to
     Ryan first, this is exactly the real per-shot picture draw this
     chunk's whole brief was about, ~$0.02-0.05/frame depending on model).
  4. Pull the stored `assets.image_prompt` for the drawn frames (`se db
     "SELECT image_prompt FROM assets WHERE video_id='<vid>' AND scene=<n>
     LIMIT 1"`) and confirm it contains the canonical text you set in step
     2, not the planner's own [MATERIAL|] line (compare against `scripts.
     coverage_directive` for that scene, same row).
  5. Eyeball the drawn frame: does the material boundary in the picture
     match the canonical text rather than whatever the planner's directive
     said? This is the one step no test (mocked or not) can stand in for.

### 6. D8-1 / D5 chunk A6 — Frame Arbiter (board station) flag-gated wiring:
never run live, no vision spend, no ledger row exists yet
Built in an isolated worktree only (`d8-1-arbiter-a6` branch) — BUILD ONLY,
per the brief, no deploy, no push, no live run. Everything below is proven
with mocked DI seams (`tests/functional/test_d5_a6_arbiter_hook.py`, 22
tests, $0): the flag-off path makes zero DB/network calls and returns the
storyboard stage's own result byte-identical (no `frame_arbiter` key added);
the flag-on path judges every drawn board sheet for the scoped scene and
writes a ledger row per judge call; a fingerprint that fires twice (a real
judge, then the post-repair re-judge, per `arbiter_repair.py`'s own RULING)
freezes and the next repair attempt is refused before budget or the reroll
leg (no second spend); the `FRAME_ARBITER_A6_REDRAW_ENABLED` sub-flag being
off means the real, paid `arbiter_repair._default_board_reroll` is never
imported let alone invoked (proven by patching that exact name and asserting
zero calls, plus the inverse test proving the same wiring DOES reach it when
the sub-flag is on). NOT PROVEN, and cannot be without a live deploy: that
`judge_board_sheet`'s real vision call against a REAL drawn board sheet in
prod actually returns a parseable verdict, that a real `generation_ledger`
row lands with `stage='frame_qa'`, and that a REAL repeat fingerprint (not a
scripted one) actually freezes on prod's real `arbiter_fingerprints` table.

Two flags added, code (not this doc) is the source of truth for the exact
env var names and defaults — see `backend/frame_arbiter_hook.py`'s own
module docstring:
  - `FRAME_ARBITER_A6_ENABLED` (default off) — master switch.
  - `FRAME_ARBITER_A6_VIDEO_ID` / `FRAME_ARBITER_A6_SCENE` — the ONE
    (video_id, scene) pair in scope; unset = nothing runs even if the
    master switch is on.
  - `FRAME_ARBITER_A6_REDRAW_ENABLED` (default off) — the repair ladder's
    paid redraw leg; independent of the master switch.
  - `FRAME_QA_SCENE_CAP` / `FRAME_QA_VIDEO_CAP` (optional env overrides on
    `backend/frame_arbiter_budget.py`'s existing $0.25/$0.50 caps — unset
    keeps today's defaults).

RECIPE for the first live proof (needs Ryan's go — this fires real Anthropic
vision spend, and if the sub-flag is also turned on, real GPT Image 2 redraw
spend on top):
  1. Pick a video on tenant `f6839de2-368c-440d-8559-0292026179fa` that
     already has at least one scene with a drawn storyboard board (a
     `scripts.storyboard_1_url` populated) — do NOT use `686b4651` per
     HANDOFF-D6-boardlaws.md's hard constraint (frozen, do not touch).
  2. On the VPS, in `storyengine/.env` (the PARENT env file, not
     `backend/.env` — see this repo's own CLAUDE.md hard rule), set:
     ```
     FRAME_ARBITER_A6_ENABLED=true
     FRAME_ARBITER_A6_VIDEO_ID=<that video's id>
     FRAME_ARBITER_A6_SCENE=<that scene's number>
     ```
     Leave `FRAME_ARBITER_A6_REDRAW_ENABLED` UNSET for the first pass
     (judge-only, zero redraw risk) — only add it, and only after Ryan
     reviews the first pass's findings, for a second pass that tests the
     real repair leg.
  3. `se restart` (env is read at process start, not live-reloaded).
  4. Trigger the scene's board sheet redraw — the SAME entry point every
     chat verb / button / MCP tool already converges on
     (`actions.py ACTIONS["storyboards"]` -> `PipelineExecutor.
     run_storyboard_sheet`): either redraw one board via the UI's per-board
     redo action for that scene, or call the `storyboards` MCP tool /
     `POST /api/pipeline/storyboard-images/{video_id}?scene=<N>` for that
     video/scene. Cost: the sheet redraw itself (~$0.05/board, existing
     GPT-Image-2 sheet price, unaffected by this chunk) PLUS the arbiter's
     own judge call.
  5. Expected ledger rows — `se db "SELECT stage, scene, model, actual_cost,
     fingerprint FROM generation_ledger WHERE video_id='<video_id>' AND
     stage='frame_qa' ORDER BY created_at"`: one row per board sheet drawn
     for that scene, `model` = the vision model
     (`shared.channel_profile.CLAUDE_MODELS["anthropic"]["smart"]`, read via
     `frame_arbiter.VISION_MODEL`), `actual_cost` near the module's own
     measured board-station rate (~$0.0273/call, `arbiter_repair.py`'s own
     docstring quoting the graduated A3b eval — the pre-call quote checked
     against the cap is `frame_arbiter.DEFAULT_BOARD_QUOTE = $0.03`),
     `fingerprint` NULL (judge_board_sheet's own ledger row is call-level,
     not per-fingerprint — see that function's own comment). If the redraw
     sub-flag was also on and a MODEL_DEFECT fired, expect one MORE row per
     repaired sheet with `model='gpt-image-2'`, `actual_cost=0.05`
     (`arbiter_repair.DEFAULT_BOARD_REPAIR_QUOTE`), `fingerprint` = the
     rule_id or failure_class that triggered it.
  6. Expected total spend for ONE scene, judge-only pass (redraw sub-flag
     off): number of drawn board sheets for that scene (1-5) times
     ~$0.0273-0.03 — e.g. a 3-sheet scene lands near $0.08-0.09, comfortably
     under the $0.25 scene cap. A judge-plus-repair pass (sub-flag on, one
     sheet needing a redraw) adds ~$0.05 (redraw) + ~$0.03 (the mandatory
     post-repair rejudge) for that one sheet.
  7. Freeze-confirmation query — after a SECOND landing that reproduces the
     SAME defect on the SAME sheet/class (e.g. redraw the same board again
     without fixing the upstream prompt): `se db "SELECT fingerprint_key,
     stage, failure_class, violation_count, frozen FROM arbiter_fingerprints
     WHERE tenant_id='f6839de2-368c-440d-8559-0292026179fa' AND
     stage='frame_qa' ORDER BY last_seen_at DESC"` — expect `violation_count
     >= 2` and `frozen = true` for that fingerprint, and a THIRD repair
     attempt on it should show NO new `generation_ledger` row with
     `model='gpt-image-2'` for that scene (the freeze refused it before any
     spend — confirm by re-running the ledger query from step 5 and seeing
     the redraw-row count unchanged from the prior check).
  8. Only after this judge-only (and, on a later explicit go, judge+repair)
     pass is reviewed clean should A9 (FRAME-ARBITER-PLAN.md) even be
     considered for widening the flag beyond this one scene.

## D6-6c/d/e — deterministic bridge, L28 style-lock wording, LOCSET material matching (2026-07-30)

Three surgical fixes coming out of the D6-6a $0 dry-run gate's conditional pass
(`tasks/evidence/d6-6a-dryrun/README.md`). All three proven at unit level, zero
spend, no DB, no VPS. Full recipe below is the live $0 dry-run re-run this
worktree is NOT authorized to execute (deploys are held).

### 1. D6-6c (deterministic BRIDGE exemption) — never re-run live against
   video 8d90df90
PROOF LEVEL REACHED IN SANDBOX: `enforce_shot_budget`'s new structural signals
(a per-moment LOCATION change, and S1 transit language in a moment's own
one-line summary — both gated on `location_sets`, rule 8) proven with hand-built
fixture moments mirroring the REAL evidence transcript byte-for-byte (the exit
moment tagged "Pod" — same as its predecessor — with no "(BRIDGE)" tag at all);
stash-proof confirmed (neutered signal -> AssertionError, restored -> pass).
NOT PROVEN: a real coverage-planner LLM call against video 8d90df90 scene 1,
run 3 times, now keeps the corridor-exit beat on 3 of 3 calls instead of 1 of 3.
RECIPE (deploy window only):
  1. `se db` read scene 1's current `scripts.scene_text` for video
     8d90df90-be0f-4328-b9d3-20f6bb5b71a6 (tenant ee93e6d1) — confirm it still
     narrates the exit ("...climbs out into the corridor").
  2. Call `generate_coverage_for_video` (or the `storyboards`/`images` MCP tool)
     for scene 1 three separate times, forcing a fresh directive each call
     (bypass the saved-directive skip — e.g. `force=true` or delete the row's
     `coverage_directive` first). This IS a $0.05-per-sheet-preview or real
     per-shot pictures spend depending on which path is exercised — quote cost
     and get a yes first if using the real PICTURES path; the sheet PREVIEW
     path's `plan_only` mode stays $0.
  3. EXPECTED: all 3 runs' final shot list includes a moment whose master/
     angle description shows Nyla actually stepping into the corridor — 3/3,
     not 1/3 — regardless of whether that run's LLM output happens to carry
     the literal "(BRIDGE)" tag.
  4. Check backend logs for the `🌉 N BRIDGE moment(s) kept as ADDITIVE` line
     on every run that needed the exemption (confirms the code path fired,
     not just that the shot count happened to look right).

### 2. D6-6d (L28 style-lock wording) — never proven against a genuine
   allow_auto_cast_generation=False call with zero attachments
PROOF LEVEL REACHED IN SANDBOX: `_style_block_for`'s per-shot ref check proven
with a fake image client capturing the exact prompt text sent to the drawer
(cast_url=None + env_url=None -> master prompt omits "attached reference
image(s)"; angle prompt keeps it, since angle_base always carries the
just-drawn master frame). Stash-proof confirmed.
NOT PROVEN: a real Custom Film / section-contract build (the actual caller that
sets `allow_auto_cast_generation=False`) reaching this code path live, with a
video that genuinely has zero locked characters and zero matched environment,
and the ACTUAL provider response to the reworded prompt (does GPT Image 2 draw
something reasonable with no reference at all, given only the shot's own prose
description — untested, this fix only proves the CLAIM is now honest, not that
the resulting image quality is acceptable).
RECIPE (deploy window only, real spend — quote first):
  1. Create a NEW test video with a Custom Film / section-contract production
     plan (whatever route sets `allow_auto_cast_generation=False` — see
     `coverage_to_app.py`'s `section_contract` branch) and skip locking any
     character or approving any environment.
  2. Trigger coverage generation for one scene. EXPECTED: no crash, no
     content-policy rejection attributable to a false reference claim; the
     logged/captured draw prompt for the MASTER shot of the first moment
     contains "STYLE LOCK: render this frame as a photoreal..." (the no-refs
     wording), not "matching...the attached reference image(s)".
  3. Visually inspect the resulting image (Visual Output Verification Rule) —
     does it look like a coherent scene, or does the missing reference produce
     worse identity/style drift than before? This chunk only fixes the FALSE
     CLAIM (BOARD-LAWS L28); it does not and cannot improve image quality when
     there is genuinely nothing to anchor on.

### 3. D6-6e (LOCSET material-map matching) — never proven against a real
   multi-location scene whose LOCSET key carries stylistic drift
PROOF LEVEL REACHED IN SANDBOX: `_canonical_material_line`/`canonical_material_
line`'s `_find()` (both the sheet-preview and pictures-path mirrors) proven
with hand-built envs where a LOCSET key ("The Elite Viewing Hall") differs from
its approved environment's name ("Elite Viewing Hall") only by a leading
article — before the fix, that location's material silently dropped out of the
combined MATERIAL MAP string while a plainer-named sibling ("Pod") appeared
alone; after the fix, both appear, correctly keyed. Stash-proof confirmed on
both mirrors.
IMPORTANT CAVEAT, stated honestly: reconstructing video 8d90df90 scene 4's
ACTUAL directive text against the CURRENT main branch (which already includes
commit bd384402, "D6-6b: a scene's own declared location beats a nested-frame
mention", landed BEFORE this worktree started) did NOT reproduce the original
evidence symptom — `_match_scene_env` already resolves that scene to "Elite
Viewing Hall" correctly, and `_canonical_material_line`'s SINGLE-location
branch (which is what actually fires for that specific single-location scene)
already returns the Hall's material correctly. The evidence file most likely
captured a run against code that predated D6-6b, committed to git later than
D6-6b landed. The bug this chunk (D6-6e) fixes is REAL and independently
reproducible (see the test), but is a DIFFERENT code path (the MULTI-location
LOCSET `_find()` helper, exercised only when a scene's coverage plan uses
`[LOCSET|...]` blocks — e.g. video 8d90df90 scene 1's Pod/Corridor escape
scene) than the one the original evidence transcript literally shows. Both are
real; only the second was still open in this code.
RECIPE (deploy window only, real spend for step 2 — quote first):
  1. `se db "SELECT name, material_map FROM video_environments WHERE video_id=
     '8d90df90-be0f-4328-b9d3-20f6bb5b71a6'"` — confirm whether any row has a
     leading-article-style name mismatch against how the coverage planner's
     own [LOCSET|...] key names it (read the saved `scripts.coverage_directive`
     for scene 1, a genuinely multi-location scene, and compare its LOCSET
     key text to `video_environments.name` verbatim).
  2. If `video_environments.material_map` is populated for Pod/Corridor (or
     once it is, per BOARD-LAWS.md's "every canonical column is NULL today"
     status), regenerate scene 1's sheet preview and pictures-path prompts;
     EXPECTED: the MATERIAL MAP block names BOTH "POD:" and "CORRIDOR:"
     clauses (previously, a LOCSET key stylistic mismatch could drop one).

## D8-3 — Review feed Findings tab (2026-07-30)

Built in an isolated worktree only (`d8-3-review-feed` branch) — BUILD ONLY,
per the brief, no deploy, no push, no live run.

### 1. Findings tab shape — never sanity-checked against real arbiter data
   (D8-2's first live run hasn't happened yet)
PROOF LEVEL REACHED IN SANDBOX: `GET /api/review/findings`
(`backend/routes/review.py::get_findings`) reads the two tables that ARE
real and persisted — A2's `arbiter_fingerprints` (migration 139: one row per
CLASS of defect, tenant-scoped, with the violation_count/frozen ratchet
state) and A1's `generation_ledger` frame_qa-stage rows (migration 140: real
QA-pass spend, grouped per video/scene) — proven with a fake `fetch_all`
asserting both queries are tenant-scoped and shaping rows into the exact
`ArbiterFinding`/`ArbiterSpend` field names (`tests/functional/
test_d8_3_review_findings.py`, 3 tests, stash-proofed as a real
AssertionError via an explicit `hasattr(review, "get_findings")` guard —
see that file's own docstring). The frontend (`review/page.tsx`'s Findings
tab) renders `TASTE_QUESTION` findings as a decision card that only ever
toggles local expand/collapse state — no mutation, no fetch, structurally
incapable of auto-acting.
HONEST GAP, not an oversight of this chunk: no per-instance findings table
exists anywhere in the codebase today. A3/A3b's judge calls
(`frame_arbiter.judge_frame`/`judge_board_sheet`) return per-frame/per-panel
finding dicts (image reference, description text, classification) ONLY in
the HTTP response of the call that produced them —
`frame_arbiter_hook.run_after_storyboard_sheet` attaches that dict to
`run_storyboard_sheet`'s own return value, which is never persisted
(`task_store.db_persist_task` only stores a status + a message STRING, no
JSON payload — confirmed by reading it, not assumed). So the Findings tab
cannot show a frame image or a free-text reason per finding — it shows
everything that A1/A2 actually persist (class, fingerprint, freeze state,
violation count, QA spend) and nothing more. This is a real architecture gap
in A3/A5's design, not something this chunk was scoped to fix.
NOT PROVEN, and cannot be without D8-2's live run: that real
`arbiter_fingerprints`/`generation_ledger` rows actually render as expected
in the tab, that the tenant used for the live check is the one the frontend
session is authed as, and whether the "no per-frame image" gap above turns
out to matter enough in practice that A8 (or a new chunk) needs to close it
before this tab is genuinely useful to Ryan day-to-day.
RECIPE (after D8-2's first live run — no spend, this is a read-only check):
  1. Confirm D8-2 actually produced rows: `se db "SELECT count(*) FROM
     arbiter_fingerprints"` and `se db "SELECT count(*) FROM
     generation_ledger WHERE stage='frame_qa'"` — both should be >0.
  2. Load `/review` in the browser as Ryan (`se devtoken` + local dev
     server, or prod directly), click the "Findings" tab, and confirm real
     rows render: at least one finding card (or, if D8-2's scene judged
     clean, the "judge has run and found nothing wrong" spend-only state)
     — NOT the "No arbiter findings yet — the judge has not run" empty
     state, which would mean either D8-2 didn't run against this tenant or
     the endpoint has a live-data bug this sandbox pass couldn't catch.
  3. If D8-2's scene produced a TASTE_QUESTION finding, confirm its decision
     card renders and that tapping it only expands/collapses — no network
     request fires (check the browser's network tab) confirming "never
     auto-acted" holds with real data, not just the mocked test.

# Deferred verification — D7-4 staleness visibility (feat/d7-4-staleness-ui)

Frontend-only chunk: surfaces D7-2's `video_characters.status`/
`video_environments.status = 'stale'` flag (set when a script edit no longer
matches the script snapshot cast/environments were generated from) in the
production UI, so a redraw/approve spend from a stale reference is a seen
choice, not a silent one. No backend changes — both GET endpoints
(`routes/characters.py::list_characters`, `routes/environments.py::
list_environments`) already `SELECT *` and their Pydantic `CharacterRead`/
`EnvironmentRead` models already type `status` as a plain `str`, so 'stale'
was already flowing over the wire; only the frontend type union and the UI
never rendered it. Changed: `frontend/src/lib/api.ts` (`VideoCharacter.status`/
`VideoEnvironment.status` unions gain `"stale"`), `CharactersTab.tsx` and
`EnvironmentsTab.tsx` (per-card orange "stale" badge + explanatory line, plus
a warning banner near the Approve bar), `ScenesWorkspaceTab.tsx` (a warning
banner near the storyboard-generating actions when any APPROVED cast/
environment member has since gone stale — the existing `castReady`/
`environmentsReady` gates only check `approved_at`, not freshness, so an
approved-then-edited cast/environment set passes the gate silently without
this addition). Advisory only, exactly like the backend flag: nothing here
blocks Redesign/Redo/Approve/storyboard generation. `npx tsc --noEmit` and
`npm run build` (34 routes, `NEXT_PUBLIC_API_URL` set for the prerender step)
both pass clean.

- [ ] **Live staleness-visible proof (no spend — this is a read-only UI
      check).** Recipe: on a video with an APPROVED cast and/or environments,
      edit the script (Scenes tab or chat) so `sync_video_script`'s
      characters_hash/environments_hash comparison (migration 145,
      `routes/videos.py`) trips — confirm via `se db "SELECT id, name, status
      FROM video_characters WHERE video_id='<id>'"` (and the
      `video_environments` sibling) that at least one row flips to `status =
      'stale'`. Then, in the browser (`se devtoken` + local dev server, or
      prod): open the Characters tab and confirm the edited character's card
      shows the orange "stale" badge + "Script changed after this was
      generated — regenerate before drawing." line, AND the approve-bar
      warning banner names it. Repeat for Environments. Then open the Scenes
      tab and confirm the new orange banner above the scene-progress section
      names the same stale character/environment and offers "Review cast" /
      "Review environments" buttons that jump to the right tab — and confirm
      storyboard generation / redraw buttons are still clickable throughout
      (advisory, not a block).
  - Expected result: the stale badge, explanatory line, and both warning
    banners appear exactly when D7-2's backend flag is set, disappear once
    the flagged character/environment is regenerated (or the whole set is
    re-approved — re-approving unconditionally sets every row back to
    `status = 'approved'`, which is an existing D7-2 behavior this chunk
    does not change, just makes visible beforehand), and never block any
    action.
- [ ] **Component-level test — not written, infra doesn't exist for it.**
  `frontend/package.json` has a `test:unit` script (vitest), but
  `vitest.config.ts` is scoped to `src/**/*.test.ts` with `environment:
  "node"` (no jsdom, no @testing-library/react, no existing component
  test) — added for one pure-function module (`timeline-slots.test.ts`),
  not React component rendering. Adding jsdom + RTL to test three JSX
  conditionals is a real infra change outside this chunk's scope (and would
  need the "ask before installing packages" rule cleared first) — stating
  this plainly rather than inventing a component-test harness. `npx tsc
  --noEmit` + `npm run build` are the only automated coverage this chunk
  has.

# Deferred verification — D10-3b (script critic checks the Story Bible's narrative/arcs/relationships)

Backend-only chunk: `backend/script_quality.py`'s `critique_script` now
best-effort fetches `videos.story_bible` (`_fetch_story_bible`) and, when the
D10-2ab-native `narrative`/`relationships`/`arcs` sections are present and
carry real content, appends a "STORY STRUCTURE TO HONOR" block to the judge's
system prompt (`_story_structure_addendum`) asking it to flag scenes that
contradict a character's stated arc, a payoff that ignores the stated stakes,
or an uncaused relationship reversal — named in `failing_gates`, flowing
through the SAME violation/edit machinery (`edit_draft_with_violations`'s
`@@@SCENE n@@@` round trip) every other violation already uses. Legacy bibles
(no new sections) and freshly-normalized native bibles whose new sections are
present-but-empty both produce a byte-identical prompt to pre-D10-3b — proven
in `tests/test_d10_3b_critique_bible.py` against the literal
`originality._SCRIPT_JUDGE_SYSTEM` constant, not just a before/after diff.
Scoped OFF entirely for `strict_rule_ids` callers (Custom Film's per-section
quality pass — a different, role/purpose-grounded production style that never
populates a Story Bible narrative/arcs/relationships), which also preserves
that path's proven "total critic failure touches no DB at all" contract
(`tests/functional/test_m7_4f_av_screenplay_adversarial.py::
test_two_malformed_strict_critic_responses_fail_before_persistence`). Fail-open
is scoped to the addendum only — a DB/JSON error there never skips the actual
grading call. `tests/test_script_quality.py`, `tests/test_c46a_quality_critic_
wiring.py`, `tests/test_c46d_trust_boundaries.py` all pass unmodified; full
backend suite reverted-vs-applied FAILED sets are byte-identical (29/29, same
names, unrelated pre-existing failures).

- [ ] **Live story-structure-visible proof (real spend: one script critique
      pass on a video that already has a D10-2ab native bible — cheap, a
      few cents of Claude tokens, no image/video/voice spend).** Recipe: pick
      or produce a video whose `videos.story_bible` carries non-empty
      `narrative`/`relationships`/`arcs` (`se db "SELECT story_bible->
      'narrative', story_bible->'arcs' FROM videos WHERE id='<id>'"` to
      confirm), then trigger a script critique pass on it (re-running the
      script stage, or any path that calls `_grade_and_maybe_revise_script`/
      `_telemetry_quality_critique`) and tail the backend log for the
      `[script_quality] critique ... verdict=...` line. Eyeball that the
      assembled prompt actually included the "STORY STRUCTURE TO HONOR"
      section (temporarily log `system_prompt` length or grep for the marker
      string) and that any violation it produces reads sensibly (names a
      real arc/relationship/stakes contradiction, not noise) before trusting
      it in production judgment.
  - Expected result: the story-structure section renders with the real
    genre/conflict/stakes/arc/relationship text (not placeholders), and a
    planted or organic contradiction in a real script surfaces as a
    `failing_gates` entry a human would recognize as correct — same bar the
    existing hook/causality/escalation/payoff gates are already held to.

# Deferred verification — D9-4 (forbidden_drift made live: prompts + judge rubric)

- [x] **$0 verification — done.** Both consumption points wired, tested,
  proven byte-identical when forbidden_drift is NULL/absent:
  - PROMPTS (`backend/scripts/coverage_to_app.py`): `_never_clause`/
    `_character_tag` (new, D9-4) feed `load_character_bible` ->
    `_character_identity_line` (board-sheet CHARACTER lines) and
    `redraw_asset_image`'s inline CHARACTER-block composer — the SAME two
    points D9-2's face_body_lock/wardrobe_lock already reach. Populated
    forbidden_drift renders verbatim as a trailing " NEVER: ..." clause;
    NULL is byte-identical (proven directly against the pre-chunk shape,
    not just "no exception").
  - JUDGE RUBRIC (`backend/frame_arbiter.py` + `backend/frame_arbiter_hook.py`):
    `compose_character_drift_text` (new) composes forbidden_drift into
    "flag as MODEL_DEFECT if: <entry>" check items; `_board_rubric_prompt`
    (the board station `judge_board_sheet` uses — the ONE thing
    `frame_arbiter_hook.run_after_storyboard_sheet` actually calls per its
    own docstring) gains an optional CHARACTER DRIFT CONSTRAINTS section +
    a 5th judge instruction, gated on a non-empty `character_drift_text`.
    The hook's `_fetch_character_drift_text` (new DB read, fail-soft) is
    threaded in via an OPTIONAL `sheet["character_drift_text"]` key — the
    SAME dict `spec_text`/`image_url` already ride in on — deliberately
    NOT a new `judge_fn` parameter, so `run_after_storyboard_sheet`'s call
    site (`judge_fn(tenant_id, video_id, scene, sheet)`) is untouched and
    every existing 4-positional-arg fake judge_fn in
    test_d5_a6_arbiter_hook.py / test_d8_3b_findings_persist.py still
    works unmodified. parse_verdict's reply format (CLASSIFICATION/
    FAILURE_CLASS/... block) is untouched — only the judge CRITERIA text
    gained a conditional section, per D9-5's sweep ruling.
  - New test file `backend/tests/functional/test_d9_4_forbidden_drift.py`
    (34 tests): helper unit tests, load_character_bible/_character_
    identity_line/redraw_asset_image byte-identical + populated proofs,
    compose_character_drift_text unit tests, _board_rubric_prompt
    byte-identical + populated proofs, judge_board_sheet prompt-assembly
    proof (including a DI-seam-signature-unchanged proof), and
    frame_arbiter_hook's `_fetch_character_drift_text`/`_fetch_scene_sheets`
    DB-read + fail-soft + conditional-attach proofs. `test_d9_2_character_
    locks.py`, `test_d5_a6_arbiter_hook.py`, `test_d8_3b_findings_persist.py`
    all pass UNMODIFIED. Full backend suite reverted-vs-applied (worktree
    at commit 466c517c vs this branch) sorted FAILED sets are byte-identical
    — one single pre-existing failure both sides
    (`test_youtube_oauth_diagnostics_reports_missing_config_without_secret_
    values`, unrelated to this chunk), 4085 -> 4119 passed (the +34 delta is
    exactly this chunk's own new test file), 4 skipped both sides. Fresh-
    worktree gitignored `backend/venv`, `remotion-video/node_modules`, and
    `remotion-video/public` (which contains `motion-audio`) were symlinked
    from the main checkout for this verification run, per D12-1's finding
    that most "pre-existing failures" in a bare fresh worktree are missing-
    artifact noise, not real failures — confirmed here too (only the one
    real pre-existing failure showed up, both reverted and applied).
    Guard-neuter stash-proofs (in-place edit + real AssertionError + revert,
    never `git stash`) ran on all four conditional guards this chunk added
    (`_never_clause`'s empty check, `_board_rubric_prompt`'s
    `character_drift_text` context-block gate, `judge_board_sheet`'s
    sheet-dict read, `_fetch_scene_sheets`'s conditional-attach gate) — each
    neuter produced the expected real test failure(s), then was reverted;
    `git diff` + `grep STASH-PROOF` confirm no neuter markers remain.

- [ ] **Live proof deferred (real spend: cast-approval vision pass already
      populates forbidden_drift per D9-2 — one board-sheet generation +
      one arbiter judge call on a video with a populated
      video_characters.forbidden_drift row; cents of spend, no separate
      video/voice cost).** Recipe:
  1. Approve a cast on a real video so D9-2's vision pass populates
     `forbidden_drift` (`se db "SELECT name, forbidden_drift FROM
     video_characters WHERE video_id='<id>'"` to confirm it's non-NULL).
  2. Generate a board sheet or redraw a picture for that video/scene and
     grep the backend log / captured prompt for " NEVER: " — confirm the
     character's real forbidden_drift text appears verbatim in the
     CHARACTER block.
  3. With `FRAME_ARBITER_A6_ENABLED`/`FRAME_ARBITER_A6_VIDEO_ID`/
     `FRAME_ARBITER_A6_SCENE` set to that video/scene, trigger a board-sheet
     judge pass and inspect the assembled judge prompt (log it once,
     temporarily) for the "CHARACTER DRIFT CONSTRAINTS" section and the
     "flag as MODEL_DEFECT if: <name>: <entry>" lines.
  4. If feasible, stage a panel that actually violates a drift constraint
     (e.g. redraw with hair recolored) and confirm the judge classifies it
     MODEL_DEFECT with a failure_class naming the drift, not a generic tag.
  - Expected result: forbidden_drift reaches both surfaces with real data,
    unmodified from the column, and a genuine violation gets caught by the
    judge — not just the $0 plumbing proof above.
## SFX render-path guard (commits a3453902, 9d83c621, branch `claude/exciting-swirles-4d8fba`) — 2026-07-24 night session

### 1. Local dev servers could not reach the production DB from this Mac — UI never actually verified live

**Blocker, not a code problem.** Backend started cleanly (`uvicorn main:app --port 8001`,
process up, `/api/health` responding), but every DB-backed request failed. Isolated with a raw
`asyncpg.connect()` test outside FastAPI — same `DATABASE_URL` that `se db` uses successfully
from the VPS returns `asyncpg.exceptions.InternalServerError: (ENOTFOUND) tenant/user
postgres.<project> not found` on every attempt from this local network (8/8 failures,
deterministic, not transient). See tasks/lessons.md 2026-07-24 (night) for the full
reproduction. Best guess: Supabase Network Restrictions (IP allowlist) scoped to the VPS's IP —
not confirmed, no Supabase dashboard access this session.

**What to run once this is fixed (or from a session that HAS prod DB access, e.g. on the VPS
itself):**

```bash
# 1. Confirm servers + DB reachable
curl -s localhost:8001/api/health | python3 -m json.tool | grep database   # expect "database": true

# 2. Confirm the new API fields, both videos
TOKEN=$(grep NEXT_PUBLIC_DEV_TOKEN storyengine/frontend/.env.local | cut -d= -f2)
curl -s localhost:8001/api/videos/65a8021e-eafa-4cff-94dc-31982ae7b63d \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool | grep -i sound_effects
# Expected: "sound_effects_supported": false,
#           "sound_effects_unsupported_reason": "this video uses character-dialogue performance
#           rendering, which has no sound-effects track."

curl -s localhost:8001/api/videos/b4067bf5-9d6b-484e-8f7d-6fe7eb11416e \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool | grep -i sound_effects
# Expected: "sound_effects_supported": true,
#           "sound_effects_unsupported_reason": null

# 3. Browser walk (Claude Browser tools or Playwright), both video IDs' Sound tab:
#    /production/65a8021e-eafa-4cff-94dc-31982ae7b63d  -> Generate buttons DISABLED,
#      amber banner visible, text names the render path ("character-dialogue performance
#      rendering, which has no sound-effects track")
#    /production/b4067bf5-9d6b-484e-8f7d-6fe7eb11416e  -> normal Sound tab, buttons enabled,
#      NO banner (regression check — this is one of the ~44 legacy videos everything used to work
#      on)
#    Check browser console for errors on both.
```

**What IS verified (code-level, not live):** `storyengine/backend/status_map.py`'s
`_render_path_sfx_reason()` was read directly and manually evaluated against each video's real
DB row (pulled via `se db`, read-only):
- BLOCKED video `65a8021e-eafa-4cff-94dc-31982ae7b63d` ("El Mercado..."):
  `dialogue_mode='character_dialogue'`, `render_mode=NULL`, `dialogue_audio=NULL`,
  `custom_film_plan_id=NULL` → falls through to the `dialogue_mode == 'character_dialogue'`
  branch → `sound_effects_supported=False`, reason = "this video uses character-dialogue
  performance rendering, which has no sound-effects track."
- ALLOWED video `b4067bf5-9d6b-484e-8f7d-6fe7eb11416e` ("She Wanted To Bake A Cake..."): all
  four fields NULL → `_render_path_sfx_reason` returns `""` → `sound_effects_supported=True`,
  `sound_effects_unsupported_reason=None`.
- `storyengine/frontend/src/components/production/SoundTab.tsx` was read directly:
  `sfxSupported = video.sound_effects_supported !== false` (line 187) gates both Generate
  buttons' `disabled` prop (lines 405, 417) and the amber banner block (lines 385–396), which
  renders `video.sound_effects_unsupported_reason` verbatim. The wiring is present and
  self-consistent; it has NOT been watched render in a browser against real data.

This is a real gap: "the code reads correctly" is not the same as "a user sees the right thing."
Do not treat this as done until step 3 above has actually run.

### 2. Advance-button behavior on a blocked video — mutates prod, needs a human

Not attempted this session (mutation ban — see the session's safety rule, live prod DB, no user
awake to approve). What to check once someone can click things:

1. Open a video on a blocked render path (e.g. `65a8021e-eafa-4cff-94dc-31982ae7b63d`, or any
   live `dialogue_mode='character_dialogue'` video that hasn't reached the sound stage yet).
2. Advance it through the pipeline up to the sound design stage (`POST
   /api/pipeline/advance/{id}` or the UI's Advance button) and confirm it **skips the Sound
   stage automatically** rather than getting stuck — `pipeline_executor._enabled_stages()`
   should exclude `"sound"` for this video (per `status_map.stages_excluding_blocked_sound`),
   and `_run_next_step_status_map()` should skip-and-advance past
   `ready_for_sound_design`/`ready_for_sound_effects` without deadlocking.
3. Confirm via `se db "SELECT status FROM videos WHERE id='<id>'"` that status lands on the next
   real stage (thumbnail/render), not stuck at a sound status.
4. Also worth a click: try `POST /api/sound-prompts/{id}` and `POST /api/sound-effects/{id}`
   directly on the blocked video and confirm a 400 with the render-path reason in the body (this
   IS safe to test with a mutating-looking call since it's expected to be REFUSED, not to spend
   money — but skipped this session anyway per the blanket "no mutating clicks" rule; use
   judgment if re-attempting).
5. Sanity-check on an ALLOWED (legacy) video: confirm Sound generation still actually starts
   normally (a real, tiny paid call — get explicit cost approval first, this is real money).

### 3. Frontend `/pipeline` create-page checkbox (mentioned in commit a3453902's message)

The commit says the pipeline create page disables the "Sound design" stage checkbox when the
selected production style is static-documentary. Not walked live this session (same DB
blocker as above). Once the DB blocker is fixed: open `/pipeline` (create-video flow), pick the
static-documentary production style, and confirm the Sound design stage checkbox is disabled
with an explanatory tooltip/label, not just unchecked-but-clickable.

---

## D7-2 staleness hash (branch `d7-2-staleness-hash`) — apply migration 145 on next deploy window

**Built and tested in a worktree only — migration 145 was NOT applied to prod this session**
(no prod-migration writes allowed from a build-only chunk). NOTE: `backend/main.py`'s startup
hook auto-applies every not-yet-applied file under `backend/migrations/*.sql` (tracked in a
`_migrations` table) — so the normal `se deploy` for this branch (which restarts the backend
service) applies migration 145 automatically. There is no separate manual-SQL step; the
"deferred" part is verifying it actually landed, since a per-migration failure there only logs
a warning and does NOT fail the boot (`except Exception as e: logger.warning(...)` inside
`main.py::_run_pending_migrations`) — a broken migration could silently no-op forever unless
someone checks:

```bash
# 1. Lock the deploy window first (see storyengine/CLAUDE.md's VPS coordination rule), then
#    deploy this branch normally: push main, then
#    scripts/se.sh deploy <session-name> [--with-frontend]

# 2. Confirm the migration actually ran (not just that the file shipped) —
#    check the startup log line and the tracking table:
se logs backend 200 | grep "145_script_staleness_hash"
# Expect: "Migration applied: 145_script_staleness_hash.sql"
se db "SELECT filename FROM _migrations WHERE filename = '145_script_staleness_hash.sql'"
# Expect exactly 1 row. If it's missing, check `se logs backend` around boot time for
# "Migration 145_script_staleness_hash.sql failed: ..." and fix forward — do NOT hand-apply
# the raw SQL over `se db --write` as a workaround without first finding out WHY the
# auto-apply failed (silent partial-schema drift is worse than a slow fix).

# 3. Verify the columns exist
se db "SELECT column_name FROM information_schema.columns WHERE table_name = 'videos' \
  AND column_name IN ('characters_hash', 'environments_hash')"
# Expect 2 rows.

# 4. Verify the CHECK constraints were actually extended (not left as two constraints —
#    the DROP/ADD pattern in the migration is idempotent, but confirm the OLD constraint
#    name matched what migration 046/051 actually created)
se db "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint \
  WHERE conname IN ('video_characters_status_check', 'video_environments_status_check')"
# Expect both definitions to read: CHECK (status = ANY (ARRAY['draft'::text, 'approved'::text, 'stale'::text]))
# If either constraint is MISSING (name didn't match, e.g. renamed by some migration
# between 046/051 and now that this session's grep didn't find), migration 145's ADD
# CONSTRAINT line would have thrown and step 2's log/table check above would already have
# surfaced the failure — so a clean "applied" record already proves the name matched.

# 5. Sanity check no existing rows already sit outside (draft, approved, stale) — the
#    migration would have refused to apply if any did, but confirm anyway:
se db "SELECT status, count(*) FROM video_characters GROUP BY status"
se db "SELECT status, count(*) FROM video_environments GROUP BY status"

# 6. Smoke the round trip on ONE real video with an existing cast/environments:
#    a. Note its current video_characters/video_environments status values.
#    b. Edit one scene's text (PATCH .../scenes/{n}/text or the Director chat) enough
#       to change the wording.
#    c. se db "SELECT status FROM video_characters WHERE video_id='<id>'" -- expect 'stale'
#       (unless characters_hash was NULL because this video predates the migration and
#       nothing was ever regenerated since — that's the expected no-op case, not a bug).
#    d. Regenerate the cast (Characters tab -> Design characters) and confirm status
#       goes back to 'draft' (regeneration heals, per design).
```

**What IS verified (code-level + a full local test suite pass, not live prod):** all 4 writers
(`update_scene_text`, `rewrite_scene_text`, chat's `_apply_prompt_draft`, Drive pull-sync) plus
the 2 inline pipeline/Custom-Film script-write paths were exercised against a fake DB in
`storyengine/backend/tests/functional/test_d7_2_staleness_hash.py` (12 tests, all passing) —
including a stash-proof (neutering `_flag_stale_cast_and_environments` to a no-op produces 6
real `AssertionError` failures, reverted after confirming) and a second stash-proof substituting
a `DELETE` for the `UPDATE video_characters SET status='stale'` write (caught by the `_no_deletes`
helper). The full backend suite (`./venv/bin/python -m pytest tests/ -q`) passes 3848/3877 both
with and without this branch's changes — the same 29 pre-existing failures (`test_custom_film_
remotion.py`, `test_youtube_oauth_diagnostics.py`), byte-identical sorted FAILED sets stashed vs
applied. What is NOT verified: the migration actually running against the real Supabase
Postgres instance, and a real browser/UI walk of a script edit flagging a real video's cast card
"stale" (there is no UI for this yet — D7-4, per the chunk spec, is UI-out-of-scope for D7-2).

---

## D8-3b arbiter findings persistence (branch `d8-3b-findings-persist`) — apply migration 146 BEFORE D8-2's live run

**Built and tested in a worktree only — migration 146 was NOT applied to prod this session**
(no prod-migration writes allowed from a build-only chunk). Same auto-apply mechanism as
migration 145 above (`backend/main.py`'s startup hook applies every not-yet-applied file under
`backend/migrations/*.sql`, tracked in `_migrations`, a per-file failure only logs a warning and
does not fail boot) — so the normal `se deploy` for this branch applies migration 146
automatically, but landing it must happen BEFORE D8-2's first live arbiter run (parked on Ryan's
deploy window) or that run's per-instance findings are lost the same way D8-3 found them lost
before this chunk.

```bash
# 1. Lock the deploy window first (storyengine/CLAUDE.md's VPS coordination rule), then deploy
#    this branch normally: push main, then scripts/se.sh deploy <session-name> [--with-frontend]
#    — BEFORE letting D8-2's live run fire.

# 2. Confirm the migration actually ran:
se logs backend 200 | grep "146_arbiter_findings"
# Expect: "Migration applied: 146_arbiter_findings.sql"
se db "SELECT filename FROM _migrations WHERE filename = '146_arbiter_findings.sql'"
# Expect exactly 1 row. If missing, check `se logs backend` around boot time for
# "Migration 146_arbiter_findings.sql failed: ..." and fix forward — never hand-apply the raw
# SQL over `se db --write` without first finding out WHY the auto-apply failed.

# 3. Verify the table + both indexes exist:
se db "SELECT column_name FROM information_schema.columns WHERE table_name = 'arbiter_findings' ORDER BY ordinal_position"
# Expect all 17 columns: id, tenant_id, video_id, scene, station, reference, label, image_url,
# classification, failure_class, rule_id, fingerprint_key, rubric_level,
# decisive_prompt_fragment, description, new_vs_previous, cost, created_at (18 incl. id).
se db "SELECT indexname FROM pg_indexes WHERE tablename = 'arbiter_findings'"
# Expect arbiter_findings_pkey, arbiter_findings_tenant_created_idx, arbiter_findings_video_scene_idx.

# 4. AFTER D8-2's first live run fires (the actual point of this chunk): confirm rows exist and
#    match what the board station judged:
se db "SELECT station, reference, classification, failure_class, cost, created_at \
  FROM arbiter_findings ORDER BY created_at DESC LIMIT 20"
# Expect one row per panel judged in that run, station='board' (judge_scene_batch/judge_frame
# are not wired to any hook yet, only judge_board_sheet is), classification one of
# MODEL_DEFECT/AUTHORING_DEFECT/TASTE_QUESTION/OK.

# 5. Confirm GET /api/review/findings returns those same rows under `instances`:
TOKEN=$(grep NEXT_PUBLIC_DEV_TOKEN storyengine/frontend/.env.local | cut -d= -f2)
curl -s https://<prod-api-host>/api/review/findings -H "Authorization: Bearer $TOKEN" \
  | python3 -m json.tool | grep -A3 '"instances"' | head -20
# Expect a non-empty `instances` array shaped per backend/models.py's ArbiterFindingInstance.

# 6. Walk the Findings tab in the browser (webapp-testing / se-smoke skill): /review -> Findings
#    tab -> confirm a "Judged frames & panels" section renders below the existing fingerprint/
#    spend sections, with a classification badge, station/reference, description, and (when the
#    judge call attached one) an image thumbnail per row.
```

**What IS verified (code-level + a full local test suite pass, not live prod):**
`storyengine/backend/tests/functional/test_d8_3b_findings_persist.py` (14 tests) covers
`arbiter_findings.record_finding_instances`'s field-mapping (board `panel`->`reference`/`label`
vs frame `image_index`->`reference`/`shot_type`->`label`, per-finding cost winning over call-level
cost, skipped/unrecognized-classification entries never persisted, one bad row never blocking the
rest of a batch) and `frame_arbiter_hook.run_after_storyboard_sheet`'s wiring (a write fires with
the right tenant/video/scene/station/cost/image_url after BOTH the first judgment and a
successful post-repair rejudge; a raised exception from `write_findings_fn` never propagates out
of the hook and never skips a later sheet's own judge/repair pass). `test_d8_3_review_findings.py`
was extended for the endpoint's third query (per-instance rows, scoped to tenant_id + the
`_FINDING_INSTANCES_LIMIT` cap). Three real stash-proofs were run (patch-file technique, never
`git stash`, per tasks/lessons.md's fleet rule): (a) neutering `_finding_cost` to always return
`call_cost` broke the frame-station cost assertion with a real `AssertionError` (999.0 == 0.019
mismatch); (b) removing the `try/except` around the hook's write call let a simulated
`RuntimeError` propagate all the way out of `run_after_storyboard_sheet`, failing the test with
that real exception; (c) neutering `get_findings` to always return `instances=[]` broke the
endpoint shape test with a real `AssertionError` (`0 == 1`) — all three reverted immediately
after confirming. The full backend suite (`./venv/bin/python -m pytest tests/ -q`, main checkout's
venv binary against worktree code) passes 3867/3896 stashed-technique baseline vs applied — the
same pre-existing 29 failures (`test_custom_film_remotion.py`, `test_youtube_oauth_diagnostics.py`),
sorted FAILED sets byte-identical (diffed, empty output, exit 0). Frontend: `npx tsc --noEmit`
clean, `npm run build` passes (34/34 static pages) once `frontend/node_modules` and
`frontend/.env.local` are present in the worktree — neither is git-tracked, so a fresh worktree
needs `npm install` (or a symlink to an existing checkout's `node_modules`) and a copy of
`.env.local` (or `scripts/se.sh devtoken`) before running the frontend checks; this was done
locally for verification and removed afterward, not committed. What is NOT verified: the
migration actually running against the real Supabase Postgres instance, any real per-instance row
from a live judge call (D8-2's first live run hasn't happened yet — that is the entire point this
chunk exists to protect), and a real browser walk of the Findings tab's new "Judged frames &
panels" section against live data.

## D10-3a: coverage/board planner learns per-video narrative signal (branch `d10-3a-planner-narrative`) — eyeball a real native-bible board plan on next deploy window

**What changed:** `scripts/coverage_to_app.py`'s `scene_aware_bible()` now attaches `narrative`
(and `relationships`, if present) straight off `videos.story_bible` — a NEW, unconditional read
(`_story_bible_narrative_context`), separate from `_scene_locations`' story-bible fallback which
only fires when a video has no approved `video_environments` rows. The final `bible if (...) else
None` gate was widened to include `narrative`, so a video whose ONLY signal is narrative (no
locked characters, no environments) no longer collapses to `None`. A new pure formatter,
`_narrative_context_block`, renders that into a delimited `<narrative>...</narrative>` block
(genre/tone/themes/conflict/stakes/time_period/world_rules, plus one `<relationships>` line per
character pair when present); `_board_rules_text_with_narrative` composes it ahead of whatever
board-scoped `quality_rules` text a call already has. Both `scene_aware_bible()` call sites
(`generate_storyboard_sheet_for_scene` and `generate_coverage_for_video`) route their
`board_rules_text` argument to `generate_coverage_directive` through this helper — the ONE
free-text hook that reaches `storyboard/coverage.py`'s planner system prompt without editing that
file (out of scope for this chunk; BOARD LAWS coverage.py stays untouched). Call site 2 needed one
extra branch: when a scene has no saved plan (`directive is None`), `run_coverage`'s OWN internal
`generate_coverage_directive` call has no `board_rules_text` parameter at all, so for a
narrative-bearing bible the directive is now precomputed directly (same call shape as site 1)
before falling into `run_coverage`; for every bible without narrative, that branch never fires and
`directive_text` stays `None` exactly as before this chunk.

**What IS verified (code-level + a full local test suite pass, no real LLM call, $0):**
`storyengine/backend/tests/functional/test_d10_3a_planner_narrative.py` (37 tests) covers:
`_narrative_context_block` (empty/None/absent-key/empty-dict bible all render "", full narrative
renders every field, partial narrative omits absent fields, relationships render one line each and
are dropped when malformed or when narrative itself is empty); `_board_rules_text_with_narrative`
(narrative-first-then-rules composition, "" + "" => ""); `_story_bible_narrative_context` (NULL
column, missing row, legacy pre-D10-2ab dict, unparseable JSON string, non-object JSON, dict vs.
JSON-string column shapes, wrong-typed narrative/relationships); `scene_aware_bible()` end to end
(legacy video carries no `narrative`/`relationships` keys at all, a native video attaches both, a
narrative-only video — no characters, no environments — no longer returns `None`, a truly empty
video still returns `None`, an unparseable `story_bible` JSON string degrades to legacy behavior
without crashing). **THE key byte-identical proof** renders `storyboard.coverage`'s REAL
`_coverage_system_prompt`/`_coverage_user_prompt` (no mocks, no LLM call — both are pure string
builders, imported directly, `storyboard/coverage.py` itself untouched) against a legacy bible
fixture with and without this chunk's wrapper and asserts the two prompts are byte-identical,
across four bible/board-rules-text combinations (both absent, board-rules-only, legacy
characters+locations, and a bible carrying an explicit-but-empty `narrative: {}` section — the
degenerate-generation case). A companion test proves the `<narrative>` block, when present, sits
between `</channel_style>` and `<rules>` in that SAME real system prompt (the exact slot
`board_rules_block` already occupies today) and that narrative sorts ahead of quality-rule text
when both exist. Wiring proofs at both real call sites (`generate_coverage_for_video`,
`generate_storyboard_sheet_for_scene`, DB/Claude/ImageClient all mocked, the site-1 test exploits
`plan_moments_deterministic("")` returning `None` so the mocked empty directive short-circuits
before any image-drawing code runs — a genuinely $0 test) confirm: a native bible makes
`generate_coverage_directive` get called with `<narrative>`/`Genre: heist thriller` inside
`board_rules_text`; a legacy bible at call site 2 never calls `generate_coverage_directive` at all
(directive stays `None`, `run_coverage` plans internally exactly as it did before this chunk —
control-flow-level byte-identical, not just prompt-text-level); a legacy bible at call site 1
passes `board_rules_text=""` through unchanged. Real stash-proof (patch-file technique, never `git
stash`, per `tasks/lessons.md`'s fleet rule): `git diff` of `coverage_to_app.py` saved to a patch,
`git apply -R` reverted the tree to byte-identical pre-chunk state (`git status --porcelain` empty
except the new test file), and separately the new test file fails at COLLECTION
(`ImportError: cannot import name '_story_bible_narrative_context'`) on the reverted tree — the
loudest possible "before" signal. Full backend suite (`./venv/bin/python -m pytest tests/ -q`,
main checkout's venv binary against worktree code) run on both trees with the new test file
excluded for a fair comparison: 29 failed / 3930 passed (both reverted and applied), sorted
FAILED-test-name sets byte-identical (diffed, empty output) — the same pre-existing 29 failures
(`test_custom_film_remotion.py`, `test_youtube_oauth_diagnostics.py`) as every other recent
D-series chunk. With the new test file included, applied: 29 failed / 3967 passed / 4 skipped.

**What is NOT verified — deploy-window check owed:**

### 1. A real board plan on a native-bible video, eyeballed via the $0(ish) dry-run path

No video in prod has a StoryEngine-native `story_bible` yet — D10-2ab (the generator that writes
`narrative`/`relationships`) landed the same day as this chunk and its own deferred-verification
entry above still owes a real generation. This chunk's `<narrative>` block has therefore never
been seen inside a REAL Claude-planner prompt, only in synthetic fixtures. Once D10-2ab's real
generation has run on a test video (owed by that chunk's own deploy-window check) and
`videos.story_bible` carries a non-empty `narrative` section, plan that video's board with
`plan_only=True` (`generate_storyboard_sheet_for_scene(..., plan_only=True)` — the D3-59 dry-run
path: plans and returns the shot list, persists nothing, draws no images) and confirm:
- The `<narrative>` block actually appears in the assembled system prompt sent to Claude (add a
  temporary print of `board_rules_text`, or inspect via a debugger/log — this repo has no existing
  "show me the raw prompt" endpoint for this call).
- The plan Claude returns actually reads as tonally/genre-consistent with the injected block (e.g.
  a "heist thriller, tense" narrative should visibly influence shot framing/pacing choices, not
  just sit inertly in the prompt) — a real qualitative read, not something a parser test can prove.
- `relationships` lines (when the bible has 2+ characters) don't crowd out or contradict the
  existing `VISUAL BIBLE` character block already in the same user prompt.

**Recipe:** after D10-2ab's real generation check has run and produced a native bible, `se db
"SELECT story_bible->'narrative' FROM videos WHERE id = '<video_id>'"` to confirm the column is
populated, then call the storyboard-planning entry point (`POST
/api/pipeline/{video_id}/scenes/{scene}/storyboard` or the equivalent chat/action verb) with
`plan_only=True` for one scene. **Cost: one Claude Sonnet call, ~$0.01-0.05** (per
`docs/cost-awareness.md`'s "Claude API (Sonnet)" line — `plan_only=True` draws zero images, so
this is the LLM-call-only cost, not the ~$0.05/board sheet-preview cost) — quote this and get a
yes before running it live.

---

## D10-3a addendum: call-site-2 precomputed-directive branch never persists (pre-existing gap, not a regression) — manager review finding

Manager review on D10-3a asked for a traced parity check between `run_coverage`'s two ways of
obtaining `directive_text` — planned internally (`directive_text=None`, the pre-existing path) vs.
precomputed by `generate_coverage_for_video`'s new fallback branch (this chunk, when the bible
carries narrative and no saved plan exists). Traced with quoted lines:

**(c) Post-parse warn checks — YES, identical either way.** `storyboard/coverage.py::run_coverage`
(`skills/video-pipeline/storyboard/coverage.py:3906-3925`):
```python
    if directive_text is None:
        directive_text = await generate_coverage_directive(
            beat_text, video_title, profile, story_bible, beat_scenes, image_prompts or [],
            max_moments=max_moments, angles_min=angles_min, angles_max=angles_max,
            anthropic_client=anthropic_client, model=directive_model)
    with open(os.path.join(outdir, "directive.txt"), "w") as f:
        f.write(directive_text)
    ...
    moments = plan_moments_deterministic(directive_text, max_moments, angles_max,
                                         max_frames=max_frames, verbose=True, props=props)
    if not moments:
        return {"error": "no moments parsed from directive", "directive_chars": len(directive_text)}
```
The `if directive_text is None:` check is the ONLY branch point — both the local `directive.txt`
file write immediately below it and every check that follows (`plan_moments_deterministic`'s own
"parse -> budget -> floors -> variety" pipeline, then `coverage.py:3927-3965`'s
`check_facing_law_compliance`, `check_headcount_stated`, `check_shot_purpose_present`,
`check_shot_transition_present`/`check_shot_transition_bridge_present`,
`check_shot_causality_present`/`check_shot_causality_valid`, and the rest of the BOARD LAWS gate
leg) run unconditionally on `directive_text`/`moments` regardless of which branch supplied it.
Setup variety is enforced inside `plan_moments_deterministic` itself (its own docstring: "parse ->
budget -> floors -> variety, in that exact order"), same unconditional call. Argument parity
confirmed too: `generate_coverage_for_video`'s new precomputed call
(`scripts/coverage_to_app.py`'s `if _narrative_board_text:` branch) passes the exact same
`beat_text`/`video_title`/`profile`/`story_bible`/`beat_scenes`/`max_moments`/`angles_min`/
`angles_max`/`anthropic_client`/`model` values `run_coverage`'s own internal call would have used
— `board_rules_text` is the only argument that differs (narrative text vs. the internal call's
implicit `""` default).

**(a) Persist the directive / (b) stamp `coverage_directive_hash` — NO, identical either way (a
PRE-EXISTING gap, not introduced by this chunk).** `run_coverage`'s own docstring
(`storyboard/coverage.py:3849-3850`): `"Saves frames + coverage.json locally with angle/shot-type
metadata. No DB writes (storing into Image records is Phase 2, where the animator consumes
them)."` — confirmed by grep: zero `await execute(...)` calls anywhere in `run_coverage`.
`generate_coverage_for_video`'s entire body (`scripts/coverage_to_app.py:4388-4729`) was swept the
same way — zero `UPDATE scripts` / `await execute(...)` calls touching `coverage_directive` or
`coverage_directive_hash` anywhere; the only DB write in that function is `store_scene`
(`scripts/coverage_to_app.py:732`, `"INSERT INTO assets (...)"`), a different table entirely. So
when this fallback branch fires (no saved plan for the scene — `directive is None` going in), the
resulting directive is NEVER written back to `scripts.coverage_directive`/`coverage_directive_hash`
— not by the pre-existing internal-planning path, and not by this chunk's new precomputed-directive
path. Contrast with call site 1 (`generate_storyboard_sheet_for_scene`), which DOES persist —
the STREAMING CONTRACT UPDATE (`scripts/coverage_to_app.py:2830-2837`):
```python
            if not plan_only:
                blocks = "\n\n".join(f"--- BEAT {i} ---\n{p}" for i, p in enumerate(prompts, start=1))
                await execute(
                    "UPDATE scripts SET coverage_directive=$1, coverage_directive_hash=$2, "
                    "storyboard_prompts=$3, storyboard_beat_count=$4, storyboard_1_url=NULL, "
                    "storyboard_2_url=NULL, storyboard_3_url=NULL, storyboard_4_url=NULL, "
                    "storyboard_5_url=NULL, storyboard_errors=NULL, updated_at=now() WHERE id=$5",
                    directive, _scene_text_hash(s["scene_text"] or ""), blocks, len(prompts), srow["id"])
```
which is exactly why call site 2's designed, gated flow is to plan via call site 1 first (its own
docstring, `generate_storyboard_sheet_for_scene:2450-2451`: "'Generate pictures' then executes THIS
EXACT saved plan (generate_coverage_for_video reuses it via coverage_directive)") — the fallback
this chunk touches only fires when that gate was bypassed (a scene that reached "Generate all
pictures" without ever going through the sheet-preview step).

**Consequence (unchanged by this chunk, quantified):** a scene that repeatedly hits this fallback
(no saved plan, every "Generate all pictures" call) re-runs a fresh Claude planning call EVERY TIME
— true before D10-3a (`run_coverage` planned internally, uncached, on every such call) and equally
true after (this chunk's precomputed call is equally uncached). This chunk does not add a new
re-spend; it relocates the SAME already-uncached spend so narrative can ride along on it.

**Why not fixed here:** adding persistence (an `UPDATE scripts SET coverage_directive=...,
coverage_directive_hash=...` in `generate_coverage_for_video`) would (1) be a real behavioral
change to the D3-59 plan_only / D7 staleness-hash contract, not a narrative-injection change —
outside this chunk's declared scope ("this chunk is coverage_to_app.py + tests only" meant the
narrative feature, not a persistence-model change); (2) directly touch the exact machinery three
OTHER active fleet workers on this same loop currently own (`d7-2-staleness`, `d7-3-invalidation`,
`d7-7-external-stale` — see their own entries above and `tasks/deferred-verification.md`'s D7-2/
D7-3 sections) — editing it here risks a merge collision or a silent contract disagreement with
their in-flight work; (3) site 1's UPDATE also nulls `storyboard_1_url..5_url`/`storyboard_errors`/
`storyboard_beat_count`, fields that mean nothing in call site 2's real-picture-draw context —
porting it naively would be semantically wrong, not a copy-paste fix. Flagging instead: this is a
good small follow-up chunk (persist the fallback-planned directive + hash in
`generate_coverage_for_video`, scoped and tested on its own, coordinated with whichever D7 worker
currently owns `coverage_directive_hash` semantics) — NOT bundled into D10-3a.

---

## D10-3d — channel profile doc: Story Bible narrative summary (2026-07-30)

**What shipped:** `backend/channel_profile_documents.py::_visual_generation_lines`
no longer treats `videos.story_bible` as an opaque string it blindly truncates
to 1800 chars. A new pure helper, `_story_bible_narrative_summary_lines(raw_bible)`,
parses the bible JSON and — only when a StoryEngine-native bible (D10-2ab) is
present with a non-empty `narrative` section (genre/tone/conflict/stakes) —
prepends a compact 1-2 line human-readable summary before the existing
truncated raw-JSON section. A legacy bible, an unparseable string, a non-dict
JSON value, or a freshly-normalized-but-empty `narrative` section all fall
through to today's exact byte-identical single-line output; the helper never
raises (wrapped in `try/except Exception: return []`). Tests:
`backend/tests/test_d10_3d_docs_narrative.py` (10 tests, pure-function
coverage over `_visual_generation_lines` and the new helper directly — no DB,
no network).

**Verification:** full backend suite (main venv binary
`storyengine/backend/venv/bin/python`, worktree code) run twice — reverted
(HEAD's `channel_profile_documents.py`, new test file moved out) and applied
— sorted `FAILED` test-name sets are byte-identical: 29 failures both runs,
same names, same order (`diff` empty). Applied run: 4005 passed / 29 failed /
4 skipped (exactly 10 more passing than reverted's 3995, matching the 10 new
tests added). Guard-neuter proof: forcing the summary helper to `return []`
unconditionally turned 3 of the new tests into real `AssertionError` failures
(the ones asserting a populated bible DOES get a summary); reverting the
neuter returned all 10 to green — proves the tests exercise real behavior,
not import/collection errors. No other test file in the suite references
`channel_profile_documents` — the "existing tests pass unmodified" checklist
item is vacuously satisfied (there were none before this chunk).

**Not touched, flagged for awareness:** `relationships`/`arcs` sections of
the native bible (also new in D10-2ab) are NOT summarized here — the brief
scoped this chunk to genre/tone/conflict/stakes only. A follow-up could add a
one-line "N characters, M relationships tracked" note the same way, if the
transparency-doc's audience (a customer inspecting their own channel's AI
inputs) wants that visibility too. Not blocking; small, isolated addition
if wanted later.

---

---

## D9-2 character-lock harvest (branch `d9-2-character-locks`) — apply migration 151 on next deploy window; RE-APPROVE a cast so the locks actually populate (populate-or-inert trap)

**Built and tested in a worktree only — migration 151 was NOT applied to prod this session**
(no prod-migration writes allowed from a build-only chunk). Same auto-apply mechanism as every
prior migration (`main.py`'s startup hook, tracked in `_migrations`, warn-not-fail on a per-file
error). Unlike D9-1/D9-6/D9-7/D11-1 (which harvest a planner-LLM tag that appears the next time
ANY scene is planned), this chunk's three columns populate ONLY at cast-APPROVAL time — every
existing character row has NULL locks today, and stays NULL forever unless its video's cast is
re-approved. The canonical branch in `load_character_bible`/`redraw_asset_image` never runs on a
single real video until that happens. The deploy-window recipe below MUST include a
re-approval step, not just a migration check:

```bash
# 1. Lock the deploy window first (see storyengine/CLAUDE.md's VPS coordination rule), then
#    deploy this branch normally: push main, then
#    scripts/se.sh deploy <session-name> [--with-frontend]

# 2. Confirm the migration actually ran
se logs backend 200 | grep "151_character_locks"
# Expect: "Migration applied: 151_character_locks.sql"
se db "SELECT filename FROM _migrations WHERE filename = '151_character_locks.sql'"
# Expect exactly 1 row.

# 3. Verify the columns exist
se db "SELECT column_name FROM information_schema.columns WHERE table_name = 'video_characters' \
  AND column_name IN ('face_body_lock', 'wardrobe_lock', 'forbidden_drift')"
# Expect 3 rows.

# 4. THE POPULATE-OR-INERT TRAP: confirm today's rows are NULL (expected, not a bug)
se db "SELECT id, name, face_body_lock, wardrobe_lock, forbidden_drift FROM video_characters \
  WHERE video_id='8d90df90-...' " # full id from tasks/ notes
# Expect all three NULL for every row — proves nothing yet, this is the baseline.

# 5. Re-approve that video's cast (Characters tab -> "Approve cast" again; this re-runs the
#    SAME vision pass that already exists in prod today, now with the extended prompt — no NEW
#    paid call is introduced, this is not an extra spend beyond what approval already costs).
#    Then re-check:
se db "SELECT id, name, face_body_lock, wardrobe_lock, forbidden_drift FROM video_characters \
  WHERE video_id='8d90df90-...'"
# Expect face_body_lock/wardrobe_lock populated for characters whose portrait vision call
# succeeded and followed the labeled format; forbidden_drift populated too (stored only, not
# consumed yet). A character with all three still NULL after this step means the vision reply
# didn't follow the labeled format that pass — check `se logs backend` for
# "[characters] D9-2 lock extraction partial for <name>" (this chunk's own warning) to confirm
# it degraded loudly rather than silently.

# 6. Plan (free) or draw (paid — confirm cost with Ryan first) that video's storyboard for a
#    scene with a locked character, and confirm the assembled CHARACTER block actually carries
#    the lock text verbatim. The D6-1 board-laws evidence at
#    tasks/evidence/d6-6a-dryrun/sheet-preview_scene1_*.txt shows this project already has a
#    free way to dump the assembled sheet-prompt text for review before any paid draw — reuse
#    that path for a scene with a re-approved character and grep the dump for the exact
#    face_body_lock/wardrobe_lock string stored in step 5. This is the one step this chunk could
#    not run itself (no live prod DB access from this Mac — see MEMORY.md's
#    "Backend loads env from storyengine/.env..." note) and is the strongest remaining proof gap:
#    every consumer of `costume`/`_identity_tag_or_locks` is unit-tested against synthetic rows,
#    but no test here proves a REAL re-approval's extracted text survives unchanged into a REAL
#    assembled prompt end to end.
```

**What IS verified (code-level + full local test suite passes, not live prod):**
`storyengine/backend/tests/functional/test_d9_2_character_locks.py` (24 tests) covers
`_parse_character_lock_reply` (full labeled reply, a reply missing one or more labels, a reply
that ignores the format entirely — parses to `{}`, never raises — multi-line values, case
insensitivity), `approve_cast`'s background task with the vision call stubbed: the happy path
writes all three lock columns AND `description` in exactly ONE `UPDATE` (proving the "one call,
not two" requirement at the SQL-write level, not just prompt level), a reply with no labels falls
back to the exact pre-D9-2 whole-reply-as-description behavior and writes zero lock columns, a
partial reply (some labels present, some missing) writes only the fields that parsed and leaves
the others untouched (not nulled — a deliberate choice so a transient miss on re-approval can't
erase a prior good extraction; documented in migration 151's own comment), a raising vision call
degrades exactly as fail-soft as the pre-existing description-refresh pass, and the no-Claude-
creds case skips the whole vision pass (zero calls) with approval still completing.
`scripts/coverage_to_app.py`'s consumer side: `_locks_text`/`_identity_tag_or_locks` (the two
helpers `load_character_bible` and `redraw_asset_image` now share) tested directly for every
precedence combination, `load_character_bible`'s SELECT proven to include the new columns, the
KEY backward-compat case (NULL locks -> costume falls back to description/identity_tag exactly as
before this migration, asserted byte-identical) plus the populated case (locks appear verbatim,
description text is provably absent from the result) plus the override case (a creator-set
identity_tag still wins over populated locks). `_character_identity_line` proven to render the
locks verbatim once they flow through the bible, and proven byte-identical on a NULL-locks
character. All 37 pre-existing tests in `test_characters.py` / `test_c4_prop_manifest.py` /
`test_money_safety_character_environment_metering.py` pass unmodified. Real stash-proof (checkout-
swap technique, never `git stash`, per tasks/lessons.md's fleet rule): after committing the chunk,
the 3 modified files were checked out back to their pre-chunk (`HEAD~1`) content and the 2 new
files (migration + test) moved out to the scratchpad, full backend suite
(`./venv/bin/python -m pytest tests/ -q`, main checkout's venv binary against worktree code) run
reverted (29 failed / 3958 passed / 4 skipped), then the 3 files checked back out to `HEAD` and the
2 new files restored (`git diff --stat HEAD` empty, confirming byte-identical restoration) and the
suite run again applied (29 failed / 3982 passed / 4 skipped — the +24 delta is exactly this
chunk's own new test file). Sorted `FAILED` test-name sets diffed byte-identical (empty diff)
between reverted and applied. `schema.sql`'s `video_characters` table updated with the 3 new
columns and a comment cross-referencing migration 151 (note: `identity_tag`/`material_map` from
migration 142 were ALREADY missing from `schema.sql` before this chunk touched the table — a
pre-existing drift this chunk did not introduce and left alone, same class of gap D9-1's entry
above flagged for `assets.shot_location`/`group_arrangement`).

What is NOT verified: the migration actually running against the real Supabase Postgres instance;
whether the extended vision prompt reliably produces the labeled format on a real, unseen portrait
(prompt compliance is never provable from a parser unit test — steps 5-6 above are what that's
for); a real re-approval's extracted face_body_lock/wardrobe_lock text surviving unchanged into a
REAL assembled board or final-picture prompt (step 6 — the strongest remaining gap, no live DB
access from this Mac); and whether the "identity_tag always wins over locks" precedence call
(this chunk's own judgment, not explicitly specified by the brief) is what Ryan actually wants
once a creator has both an authored identity_tag and freshly-extracted locks disagreeing — flagged
for a look at the next opportunity, not re-litigated silently.
successful post-repair rejudge; a raised exception from `write_findings_fn` never propagates out
of the hook and never skips a later sheet's own judge/repair pass). `test_d8_3_review_findings.py`
was extended for the endpoint's third query (per-instance rows, scoped to tenant_id + the
`_FINDING_INSTANCES_LIMIT` cap). Three real stash-proofs were run (patch-file technique, never
`git stash`, per tasks/lessons.md's fleet rule): (a) neutering `_finding_cost` to always return
`call_cost` broke the frame-station cost assertion with a real `AssertionError` (999.0 == 0.019
mismatch); (b) removing the `try/except` around the hook's write call let a simulated
`RuntimeError` propagate all the way out of `run_after_storyboard_sheet`, failing the test with
that real exception; (c) neutering `get_findings` to always return `instances=[]` broke the
endpoint shape test with a real `AssertionError` (`0 == 1`) — all three reverted immediately
after confirming. The full backend suite (`./venv/bin/python -m pytest tests/ -q`, main checkout's
venv binary against worktree code) passes 3867/3896 stashed-technique baseline vs applied — the
same pre-existing 29 failures (`test_custom_film_remotion.py`, `test_youtube_oauth_diagnostics.py`),
sorted FAILED sets byte-identical (diffed, empty output, exit 0). Frontend: `npx tsc --noEmit`
clean, `npm run build` passes (34/34 static pages) once `frontend/node_modules` and
`frontend/.env.local` are present in the worktree — neither is git-tracked, so a fresh worktree
needs `npm install` (or a symlink to an existing checkout's `node_modules`) and a copy of
`.env.local` (or `scripts/se.sh devtoken`) before running the frontend checks; this was done
locally for verification and removed afterward, not committed. What is NOT verified: the
migration actually running against the real Supabase Postgres instance, any real per-instance row
from a live judge call (D8-2's first live run hasn't happened yet — that is the entire point this
chunk exists to protect), and a real browser walk of the Findings tab's new "Judged frames &
panels" section against live data.

## G1 — gatherer fallbacks: normalizer, NA/Wayback chain, source steering — 2026-07-30

Ported into `storyengine/backend/pipeline_executor.py::_gather_verified_machine_source_package`
from the DVsU research simulator (`storyengine/tasks/evidence/dvsu-research-simulator/
build_package.py`, untracked, main checkout only): (a) the tolerant `_normalized_source_text`
fold (citation markers, smart quotes/dashes, NBSP, orphan punctuation/hyphen spaces), (b) the
National Archives Discovery JSON API + real-Wayback-availability fallback chain (new capture
methods `national_archives_api` and `wayback:<url>`, threaded through
`_verified_source_candidate_traceable` and the `unsupported_capture_methods` quality gate via a
new shared `_is_approved_source_capture_method` helper), (c) source steering — every Tavily call
now sends `exclude_domains: ["iwm.org.uk", "www.iwm.org.uk"]`, plus one additional
`include_domains`-scoped call to `awm.gov.au / rmg.co.uk / gov.uk / naval-encyclopedia.com /
naval-history.net / uboat.net` when `_is_naval_gather_context(title, machine)` detects a
ship/naval machine from the video title or machine name.

Cost cap respected: every test (`storyengine/backend/tests/test_machine_documentary_hold.py`,
15 new tests) runs fully offline against a fake `httpx.AsyncClient` — no live Tavily, National
Archives, or Wayback calls were made this session. **What is NOT verified live:**

### 1. The real National Archives Discovery API and Wayback availability API were never called live
The retry-on-empty-202 logic and the Wayback `archived_snapshots` response shape are both typed
from the reference simulator's own hard-won notes (`STATE.md`: "National Archives API 202s when
cold — retry or sidecar") and from `build_package.py`'s working implementation, not from a fresh
live call this session. Recipe to confirm against the real APIs (no API key needed, both are
public/unauthenticated):
```bash
# National Archives Discovery record -> its own JSON API. Use any real record id, e.g. one
# already gathered in the simulator's raw/ directory, or search discovery.nationalarchives.gov.uk
# for a British WW2-era ship-file record and take the id from its /details/r/<ID> URL.
curl -s "https://discovery.nationalarchives.gov.uk/API/records/v1/details/<ID>" | head -c 500
# Expect: JSON (may be empty/202-shaped on a cold record — the pipeline retries 3x, 3s apart).

# Wayback availability API for a real URL known to be archived.
curl -s "http://archive.org/wayback/available?url=https://www.iwm.org.uk/collections/item/object/205211678"
# Expect: {"archived_snapshots": {"closest": {"url": "https://web.archive.org/web/...", ...}}}
```
If either shape has drifted from what's coded (e.g. NA now nests the payload differently, or the
availability API renamed a key), `_fetch_source_fallback_text`/`_wayback_snapshot_url` in
`pipeline_executor.py` need a matching update — the fixture-based tests would keep passing
(they pin the CODED shape) while the live path silently stopped working, so a periodic live
recipe re-run is worth keeping.

### 2. Not yet run through a real gather for a machine whose ONLY sources are behind the iwm.org.uk bot-wall
The Definition of Complete's "a machine whose best sources sit behind a bot-wall must still yield
a passing package" is proven at the unit/fixture level (traceable capture methods, exclude/
include domains wired correctly) but not end-to-end against a live video. Recipe once Ryan
authorizes a paid Tavily run: pick one of the DVsU carrier roster machines noted in
`dvsu-research-simulator/STATE.md` as gathered mostly from IWM-adjacent pages, clear its cached
`machine_raw_source_packages` entry, and re-run research through the pipeline's own API path —
confirm the resulting package's sources include at least one `national_archives_api` or
`wayback:` capture method and still passes `_verified_machine_source_package_quality_errors`.

### 3. `static_docu.py`'s "reference fetching" was investigated and deliberately NOT touched
The chunk brief named `static_docu.py`'s reference fetching alongside
`_gather_verified_machine_source_package` as a second port target. Read in full
(`storyengine/backend/static_docu.py:770-894`, `_host_reference` / `_gather_reference_candidates`):
it is a Wikimedia Commons IMAGE-reference fetcher for ship-roster PHOTOS, unrelated to the
text-excerpt research package — it never touches iwm.org.uk, awm.gov.au, rmg.co.uk,
naval-encyclopedia.com, naval-history.net, or uboat.net, and has no citation-marker/excerpt
normalization concern at all. Porting the three GAP-1 capabilities there would not address any
real failure mode in that code. Flagging instead of silently dropping: if Ryan wants a
Wayback-image fallback for `_host_reference` (e.g. when a Commons file 404s), that is a distinct,
separately-scoped follow-up, not part of this chunk's Definition of Complete.

---

## D9-1 shot-purpose harvest (branch `d9-1-shot-purpose`) — apply migration 147 on next deploy window; confirm the PURPOSE tag actually shows up in a real plan

**Built and tested in a worktree only — migration 147 was NOT applied to prod this session**
(no prod-migration writes allowed from a build-only chunk). Same auto-apply mechanism as every
prior migration (`main.py`'s startup hook, tracked in `_migrations`, warn-not-fail on a per-file
error) — the "deferred" part is confirming it actually landed AND that a real planner call
actually emits the new PURPOSE row (a prompt-only change; no test in this chunk calls the real
Claude API):

```bash
# 1. Lock the deploy window first (see storyengine/CLAUDE.md's VPS coordination rule), then
#    deploy this branch normally: push main, then
#    scripts/se.sh deploy <session-name> [--with-frontend]

# 2. Confirm the migration actually ran
se logs backend 200 | grep "147_shot_purpose"
# Expect: "Migration applied: 147_shot_purpose.sql"
se db "SELECT filename FROM _migrations WHERE filename = '147_shot_purpose.sql'"
# Expect exactly 1 row.

# 3. Verify the columns exist
se db "SELECT column_name FROM information_schema.columns WHERE table_name = 'assets' \
  AND column_name IN ('purpose_kind', 'shot_purpose')"
# Expect 2 rows.

# 4. Plan ONE real scene's coverage (sheet-preview planning, no spend — Scenes page ->
#    "plan the shots" / plan_only path) and read the raw directive.txt/coverage_directive
#    back out:
se db "SELECT coverage_directive FROM scripts WHERE video_id='<id>' AND scene=<n>"
# Confirm the planner ACTUALLY wrote "PURPOSE: <kind> | <text>" rows under real MASTER/ANGLE
# lines — this chunk only proves the PARSER handles the tag correctly if the LLM writes it;
# it does not prove Claude reliably follows a brand-new prompt rule on its first live call.
# If PURPOSE rows are sparse/absent on a real plan, check_shot_purpose_present's WARN log line
# ("shot-purpose check (D9-1): ... carries no PURPOSE: line") should be showing up in
# `se logs backend` around that plan's generation — confirms the WARN gate itself is live,
# even if the prompt compliance needs a follow-up nudge.

# 5. Draw that same scene's real pictures (spend gate — confirm cost with Ryan first) and
#    confirm the columns actually populate:
se db "SELECT scene, image_index, purpose_kind, shot_purpose FROM assets \
  WHERE video_id='<id>' AND scene=<n> AND generation_method='coverage' ORDER BY image_index"
# Expect purpose_kind/shot_purpose populated (non-NULL) for shots whose PURPOSE row survived
# step 4's plan, NULL for any shot the planner didn't tag (floor-added REACTION/INSERT shots,
# or a plain miss) — NULL here is not itself a bug, see step 4.
```

**What IS verified (code-level + full local test suite passes, not live prod):**
`skills/video-pipeline/tests/test_d9_1_shot_purpose.py` (11 tests) covers `parse_coverage`'s
extraction of the per-shot `PURPOSE: <kind> | <text>` row (master and angle independently, bold
markdown tolerated, kind lowercased), the row never surviving into the stored `description` (the
whole reason it lives on its own line — rule 23/L27, INSTRUCTIONS ARE NOT CAPTIONS), BACKWARD
COMPATIBILITY against `SAMPLE` — the exact pre-existing fixture `test_coverage.py` already used
before this chunk — parsing byte-identical on `shot_type`/`description` with purpose fields simply
`None`, the new `check_shot_purpose_present` WARN gate (silent when every shot is tagged, flags
exactly the untagged ones, flags all 5 shots on the legacy `SAMPLE` fixture with no crash),
`generate_coverage_frames` threading `purpose_kind`/`shot_purpose` onto its frame dicts AND proof
the purpose text never reaches the actual image-generation prompt string (a planted marker string
in `shot_purpose` is asserted absent from the prompt `_gen_ref` receives), `enforce_setup_variety`'s
content-swap carrying purpose fields along with `shot_type`/`description` (so a swap never leaves
a shot's stated purpose describing a framing that moved elsewhere), and `plan_moments_deterministic`
(the ONE shared parse->budget->floors->variety pipeline both the sheet-preview planning path and
the real-pictures path call) preserving purpose fields end to end including a floor-added filler
shot correctly landing with none. `storyengine/backend/tests/functional/
test_d9_1_shot_purpose_stamp.py` (3 tests) proves `store_scene`'s INSERT actually stamps
`purpose_kind`/`shot_purpose` from a frame dict's fields (present, NULL-default, and independently
per-shot within one moment) — the sheet-preview planning path never inserts an asset row at all
("Storyboard SHEETS are a preview, not an asset row" is coverage_to_app.py's own comment, confirmed
by reading it — nothing to stamp there), so `store_scene` is the one real stamping site and both
paths feed it identical parsed fields via the shared `plan_moments_deterministic`. Real stash-proof
(patch-file technique, never `git stash`, per tasks/lessons.md's fleet rule): `git diff --cached`
of the full chunk saved to a patch, reverse-applied cleanly (`git apply -R`, working tree confirmed
clean after), pipeline suite (`test_board_laws.py` + `test_d6_2_repair_stamps.py` + `test_coverage.py`)
still 150/150 passing reverted (new D9-1 test files gone with the revert, no orphaned failures),
full backend suite (`./venv/bin/python -m pytest tests/ -q`, main checkout's venv binary against
worktree code) 29 failed / 3867 passed reverted vs 29 failed / 3882 passed applied (the +15 are
this chunk's own new tests) — sorted FAILED sets byte-identical (diffed, empty output), then the
patch forward-applied cleanly to restore the chunk. `schema.sql`'s `assets` table updated with the
2 new columns (with a note: `assets.shot_location`/`assets.group_arrangement` from migration 143
were ALREADY missing from `schema.sql` before this chunk touched it — a pre-existing drift, not
something this chunk introduced or fixed; flagged separately, not folded into this migration).
What is NOT verified: the migration actually running against the real Supabase Postgres instance,
whether Claude reliably follows the new PURPOSE-row prompt rule on a real, unseen scene (prompt
compliance is never provable from a parser unit test — that's what step 4 above is for), and a
real `assets.purpose_kind`/`shot_purpose` value landing from an actual paid coverage-picture draw.

---

## D10-2ab: StoryEngine-native Story Bible generator (backend/story_bible_native.py)

**What changed:** `PipelineExecutor.run_story_bible` no longer imports the legacy
`storyboard.bot._generate_story_bible_for_storyboard` (a sys.path reach into
`skills/video-pipeline`) or persists through the Airtable-shim
`supabase_adapter.update_idea_fields`. It now calls a new backend-native module
(`story_bible_native.generate_story_bible_native`, ONE extended Claude call via the same
`self._pipeline.anthropic` bridge every other `run_*` step already uses) and persists with a
direct, tenant-scoped `UPDATE videos SET story_bible = $1 WHERE id = $2 AND tenant_id = $3`. The
document schema is unchanged for consumers (`characters`/`locations`/`scene_blocks`, matching the
legacy V2 normalizer field-for-field) plus three new top-level sections (`narrative`,
`relationships`, `arcs`) that dangling-reference-validate against the same generation's character
ids and drop bad refs with a logged warning rather than failing generation.

**What IS verified (code-level + a full local test suite pass, no real LLM call, $0):**
`storyengine/backend/tests/test_story_bible_native.py` (22 tests, pure module — no DB, no
PipelineExecutor) covers the ported normalizer defaults for characters/locations/scene_blocks
(costume/description fallback, first-image-forced-wide, location lookup by id, image-count and
consecutive-same-location warnings that never abort generation), the three new sections'
defaults, and dangling-character-id drops for both `relationships` and `arcs` (asserted via
`capsys`, never a raised exception). `storyengine/backend/tests/test_d10_2ab_run_story_bible.py`
(9 tests) covers the wiring: scripts are fetched tenant-scoped by `video_id`, the persisted
UPDATE query text and args are tenant-scoped and match the full generated document byte-for-byte
after a JSON round trip, and every failure path (Claude raises, no script rows, missing Anthropic
client, unparseable response, video not found) returns `status: "failed"` with zero writes to
`videos.story_bible` and never logs `bot_activity` as `"completed"`. `tests/functional/
test_characters.py` and `tests/functional/test_c66_production_guide.py` (the two named
"unaffected consumer" checks) pass unmodified. Two real stash-proofs were run (patch-file
technique, never `git stash`, per tasks/lessons.md's fleet rule): the full backend suite
(`./venv/bin/python -m pytest tests/ -q`, main checkout's venv binary against worktree code) was
run BOTH on the reverted tree (`git checkout -- pipeline_executor.py` + the three new files moved
out of the tree, restored via `git apply` on a saved patch afterward) and on the applied tree —
29 failed / 3886 passed (reverted) vs 29 failed / 3908 passed (applied, +22 for the new test
files), sorted FAILED sets byte-identical (diffed, empty output, exit 0) — the same pre-existing
29 failures (`test_custom_film_remotion.py`, `test_youtube_oauth_diagnostics.py`) as every other
recent D-series chunk.

**What is NOT verified — deploy-window check owed:**

### 1. A real Story Bible generation on a test video with a live Claude call

No live LLM call was made (every test above stubs `self._pipeline.anthropic`). Before this ships
to a real customer's build, run one real generation end to end and confirm:
- The new `narrative`/`relationships`/`arcs` sections are actually present and sensible on a
  REAL script (not just the hand-written fixture the tests use) — in particular, whether Claude
  reliably keeps `relationships`/`arcs` character ids matching `characters` ids without the
  dangling-ref dropper silently emptying them out on a real generation.
- `scene_blocks` total image count roughly matches the requested `total_images` (a mismatch only
  warns, never fails — worth eyeballing on a real script rather than assuming the model complies).
- The downstream legacy consumers (`routes/characters.py`'s bible<->cast sync,
  `scripts/coverage_to_app.py`'s `_story_bible_locations`, `channel_profile_documents.py`) render
  correctly against a bible that now has 3 extra top-level keys they've never seen live before.
- `run_storyboard_prompts` (still on the legacy `storyboard/run.py` path, untouched by this
  chunk) does NOT regenerate its own bible when one from this native path is already persisted —
  confirm `videos.story_bible` is non-empty after `run_story_bible` so its own
  `_generate_story_bible_for_storyboard` fallback never fires.

**Recipe:** pick a test video already past scripting (`ready_for_storyboards` or earlier, with
scripted scenes), call `POST /api/pipeline/{video_id}/story-bible` (or the equivalent chat/action
verb) once, then `se db "SELECT story_bible FROM videos WHERE id = '<video_id>'"` and eyeball the
JSON. **Cost: one Claude Sonnet call, ~$0.02-0.05** (per docs/cost-awareness.md's "Claude API
(Sonnet) ~$0.01-0.05/call" line — no image/video/voice spend, this step is text-only) — quote
this and get a yes before running it live.

---

## D9-6/D9-7 transition + causality harvest (branch `d9-67-transitions`) — apply migration 148 on next deploy window; confirm TRANSITION/CAUSED_BY rows actually show up in a real plan

**Built and tested in a worktree only — migration 148 was NOT applied to prod this session** (no
prod-migration writes allowed from a build-only chunk). Same auto-apply mechanism as every prior
migration (`main.py`'s startup hook, tracked in `_migrations`, warn-not-fail on a per-file error) —
the "deferred" part is confirming it actually landed AND that a real planner call actually emits
the new TRANSITION/CAUSED_BY rows (a prompt-only change; no test in this chunk calls the real
Claude API):

```bash
# 1. Lock the deploy window first (see storyengine/CLAUDE.md's VPS coordination rule), then
#    deploy this branch normally: push main, then
#    scripts/se.sh deploy <session-name> [--with-frontend]

# 2. Confirm the migration actually ran
se logs backend 200 | grep "148_shot_transition_causality"
# Expect: "Migration applied: 148_shot_transition_causality.sql"
se db "SELECT filename FROM _migrations WHERE filename = '148_shot_transition_causality.sql'"
# Expect exactly 1 row.

# 3. Verify the columns exist
se db "SELECT column_name FROM information_schema.columns WHERE table_name = 'assets' \
  AND column_name IN ('transition_kind', 'continuity_bridge', 'caused_by')"
# Expect 3 rows.

# 4. Plan ONE real scene's coverage (sheet-preview planning, no spend — Scenes page ->
#    "plan the shots" / plan_only path) and read the raw directive.txt/coverage_directive
#    back out:
se db "SELECT coverage_directive FROM scripts WHERE video_id='<id>' AND scene=<n>"
# Confirm the planner ACTUALLY wrote "TRANSITION: <kind> | <bridge>" and "CAUSED_BY: M<n>-..."
# rows under real MASTER/ANGLE lines, in ADDITION to D9-1's PURPOSE rows — this chunk only
# proves the PARSER handles the two new tags correctly if the LLM writes them; it does not
# prove Claude reliably follows two brand-new prompt rules (25/26) stacked on top of an
# existing one (24) on its first live call, or that it correctly derives the M<n>-MASTER/
# M<n>-ANGLE<k> label format for a CAUSED_BY reference without being shown a worked example
# beyond the prompt's own template. If TRANSITION/CAUSED_BY rows are sparse/absent/malformed
# on a real plan, the four new WARN log lines ("shot-transition check (D9-6): ...", "shot-
# transition-bridge check (D9-6): ...", "shot-causality check (D9-7): ...") should be showing
# up in `se logs backend` around that plan's generation — confirms the WARN gates themselves
# are live, even if prompt compliance needs a follow-up nudge. Pay particular attention to
# whether Claude gets the CAUSED_BY label format right (M<n>-MASTER / M<n>-ANGLE<k>) — this is
# the one place this chunk asks the planner to do something more structured than free prose,
# and check_shot_causality_valid's "does this label exist / is it earlier" check depends on it
# being syntactically exact.

# 5. Draw that same scene's real pictures (spend gate — confirm cost with Ryan first) and
#    confirm the columns actually populate:
se db "SELECT scene, image_index, transition_kind, continuity_bridge, caused_by FROM assets \
  WHERE video_id='<id>' AND scene=<n> AND generation_method='coverage' ORDER BY image_index"
# Expect transition_kind/caused_by populated (non-NULL) for shots whose rows survived step 4's
# plan, continuity_bridge populated only for a non-continuous/non-opening kind that stated one,
# NULL for any shot the planner didn't tag (floor-added REACTION/INSERT shots, or a plain miss,
# or the scene's true first shot for caused_by specifically) — NULL here is not itself a bug,
# see step 4.
```

**Grammar decision (documented here since it drives what step 4 above needs to confirm):** TWO
separate trailing rows, `TRANSITION: <kind> | <bridge>` (rule 25) and `CAUSED_BY: <label>` (rule
26) — not folded into one row, and not folded into D9-1's PURPOSE row. Each is independently
optional, independently gated by its own warn check(s), and Custom Film itself keeps
transition_from_previous/continuity_bridge and caused_by as separate ShotDraft fields — combining
them would conflate distinct warn conditions behind one piece of text for no reduction in grammar
surface. CAUSED_BY carries a SINGLE reference (not a tuple like Custom Film's `caused_by`): the
flagship grammar has no LLM-assigned `shot_key` the way ShotDraft does, so the reference format
taught here is a label the planner can derive purely from context already on the page —
`M<moment_number>-MASTER` / `M<moment_number>-ANGLE<k>` — never a running global shot count it
would have to track across the whole scene; one clear reference is more likely to be authored
correctly than a list the planner has to keep internally consistent.

**What IS verified (code-level + full local test suite passes, not live prod):**
`skills/video-pipeline/tests/test_d9_6_7_transition_causality.py` (29 tests) covers `parse_
coverage`'s extraction of the per-shot `TRANSITION: <kind> | <bridge>` row (bridge optional,
omitted entirely for "continuous") and `CAUSED_BY: <label>` row, independently and together with
D9-1's PURPOSE row IN ANY ORDER the planner writes them (the decisive robustness property: a
naive "check PURPOSE first" scan let PURPOSE's own `.+?` capture swallow trailing TRANSITION/
CAUSED_BY rows whole before the fix — `_strip_shot_metadata_rows` now picks whichever candidate
regex match starts LATEST in the current text each pass, peeling the true tail row first
regardless of which of the three it is), the rows never surviving into the stored `description`,
BACKWARD COMPATIBILITY against BOTH the legacy zero-metadata-row `SAMPLE` fixture (byte-identical
shot_type/description, all five fields None) AND a synthesized D9-1-era fixture (PURPOSE rows
present, TRANSITION/CAUSED_BY absent — the real shape of every plan generated between D9-1
landing and this chunk landing), the four new WARN gates (`check_shot_transition_present`,
`check_shot_transition_bridge_present` — including the "opening" exemption alongside
"continuous", a deliberate refinement over the task brief's literal wording to faithfully mirror
Custom Film's own model where an opening shot structurally never carries a bridge —
`check_shot_causality_present`, `check_shot_causality_valid` — nonexistent-reference, forward-
reference, and self-reference all correctly flagged, a correct earlier reference correctly
silent), `generate_coverage_frames` threading all three new fields onto its frame dicts AND proof
the bridge/caused_by text never reaches the actual image-generation prompt string (planted marker
strings in both fields asserted absent from the prompt `_gen_ref` receives), `enforce_setup_
variety`'s content-swap carrying transition_kind/continuity_bridge/caused_by along with shot_type/
description/purpose_kind/shot_purpose (documented judgment call: these three describe WHY/HOW a
specific piece of content cuts in and what it follows from, not a fact about the position it
occupies, so they travel with content on a swap exactly like D9-1's purpose fields do — a known
residual: since caused_by is a positional LABEL and enforce_setup_variety only trades within the
same/adjacent moment, a swap can in rare cases leave a shot's caused_by pointing at itself or at
the position it just vacated; `check_shot_causality_valid` catches this post-swap as an ordinary
warn, by design, rather than needing a special case), and `plan_moments_deterministic` (the ONE
shared parse->budget->floors->variety pipeline both the sheet-preview and real-pictures paths
call) preserving all fields end to end including a floor-added filler shot correctly landing with
none. `storyengine/backend/tests/functional/test_d9_6_7_transition_causality_stamp.py` (4 tests)
proves `store_scene`'s INSERT stamps `transition_kind`/`continuity_bridge`/`caused_by` from a
frame dict's fields (present, NULL-default, independently per-shot within one moment, and a
non-continuous kind WITH a bridge stamping both) — same "store_scene is the one real stamping
site" reasoning as D9-1 (re-confirmed by re-reading coverage_to_app.py, nothing changed about
that). `storyengine/backend/tests/functional/test_d9_1_shot_purpose_stamp.py` was UPDATED (not
left broken): this chunk's migration 148 appends three columns AFTER migration 147's purpose_kind/
shot_purpose in the INSERT's column list, which shifted D9-1's own hardcoded `params[-2]`/
`params[-1]` positional assertions off target (they silently started reading continuity_bridge/
caused_by instead, or in one case still passed by coincidence since both new-and-old values were
None) — caught by running D9-1's stamp test after this chunk's change, fixed to `params[-5]`/
`params[-4]` (and `[-5:-3]` for the two-shots-in-one-moment test) with a comment explaining why,
re-verified passing. Real stash-proof (patch-file technique, never `git stash`, per tasks/
lessons.md's fleet rule): `git diff --cached` of the full chunk (all 7 touched/new files) saved to
a patch, `git checkout --`/`rm` reverted the tree to byte-identical pre-chunk state (confirmed via
`git status --porcelain` empty except for the untouched worktree baseline), pipeline suite
(`test_board_laws.py` + `test_d6_2_repair_stamps.py` + `test_coverage.py` + `test_d9_1_shot_
purpose.py`) back to 161/161 passing reverted, full backend suite (`./venv/bin/python -m pytest
tests/ -q`, main checkout's venv binary against worktree code) 29 failed / 3904 passed / 4 skipped
reverted — IDENTICAL to this chunk's own pre-change baseline capture, sorted FAILED-test-name sets
diffed byte-identical (empty diff) — then the patch forward-applied cleanly (`git apply`, no
conflicts) to restore the chunk; broader pipeline suite sweep (`tests/` minus two files with
pre-existing, unrelated collection errors on main) also diffed clean: same 18 failed/3 errors on
both main and this worktree, only the passed-count delta (+29) accounted for by this chunk's own
new tests. `schema.sql`'s `assets` table updated with the 3 new columns, comment cross-referencing
migration 148.

What is NOT verified: the migration actually running against the real Supabase Postgres instance;
whether Claude reliably follows the two new prompt rules (25/26) on a real, unseen scene, including
whether it gets the CAUSED_BY label format (`M<n>-MASTER`/`M<n>-ANGLE<k>`) syntactically right
without more than the prompt template as an example (prompt compliance is never provable from a
parser unit test — that's what step 4 above is for); real `assets.transition_kind`/
`continuity_bridge`/`caused_by` values landing from an actual paid coverage-picture draw; and
whether the D12-2 render-layer consumption of `transition_kind` (explicitly out of scope for this
chunk — data + warn checks only) will want the stored value in a different shape than "as
authored, lowercased" once that chunk is built.

---

## D11-1 professional shot-archetype library (branch `d11-1-archetypes`) — apply migration 149 on next deploy window; confirm ARCHETYPE rows actually show up in a real plan, and that the planner's chosen ids land in the catalog

**Built and tested in a worktree only — migration 149 was NOT applied to prod this session** (no
prod-migration writes allowed from a build-only chunk). Same auto-apply mechanism as every prior
migration (`main.py`'s startup hook, tracked in `_migrations`, warn-not-fail on a per-file error) —
the "deferred" part is confirming it actually landed AND that a real planner call actually emits
well-formed `ARCHETYPE: <id>` rows using ids that are IN `storyboard.shot_archetypes.
SHOT_ARCHETYPES` (a prompt-only change; no test in this chunk calls the real Claude API — the
whole point of rule 27 being OPTIONAL is the planner may simply never use it, which is fine, but
if it DOES use it, the id vocabulary needs to actually match):

```bash
# 1. Lock the deploy window first (see storyengine/CLAUDE.md's VPS coordination rule), then
#    deploy this branch normally: push main, then
#    scripts/se.sh deploy <session-name> [--with-frontend]

# 2. Confirm the migration actually ran
scripts/se.sh db "SELECT column_name FROM information_schema.columns WHERE table_name='assets' AND column_name='shot_archetype'"
# Expect one row back.

# 3. Generate a real scene's coverage directive (any normal chat/coverage-build flow) and read
#    the raw directive text (scripts/coverage_to_app.py writes it, or grab it from
#    scripts.coverage_directive on the scene row) — look for ARCHETYPE: rows under some of the
#    MASTER/ANGLE lines. Since rule 27 says "MAY", zero rows on any given scene is NOT a failure;
#    the interesting failure mode is an ARCHETYPE row present with an id NOT in
#    storyboard.shot_archetypes.SHOT_ARCHETYPES (the exact thing check_shot_archetype_valid warns
#    on — check the coverage-run logs for "⚠️ shot-archetype check (D11-1)" lines).

# 4. Draw that same scene's real pictures (spend gate — confirm cost with Ryan first) and confirm
#    the column actually populates:
scripts/se.sh db "SELECT id, shot_type, shot_archetype FROM assets WHERE video_id='<vid>' AND scene=<n> ORDER BY image_index"
# Expect shot_archetype populated (non-NULL) for whichever shots the planner chose to tag — very
# likely a MINORITY of shots (optional, unlike PURPOSE/TRANSITION/CAUSED_BY), NULL is expected and
# fine for the rest.
```

**What IS verified (code-level + full local test suite passes, not live prod):**
`skills/video-pipeline/tests/test_d11_1_shot_archetype.py` (27 tests) covers catalog integrity
(`storyboard/shot_archetypes.py`: 45 unique ids across the six required categories — establishing/
coverage/detail/angle/composition/specialty — every required text field non-empty, every
`pairs_well_after` reference resolves to a real catalog id, `format_archetype_menu()` renders under
an 8000-char budget at 5799 chars/~1450 tokens actual, `get_archetype()` case/whitespace tolerant),
`parse_coverage`'s extraction of the per-shot `ARCHETYPE: <id>` row (lowercased, tolerant of bold,
correctly independent when stacked with PURPOSE/TRANSITION/CAUSED_BY in ANY order — same
latest-starting-candidate mechanism D9-6/D9-7 built, now handling four row types instead of three),
BACKWARD COMPATIBILITY against ALL THREE prior directive eras (legacy zero-metadata-row `SAMPLE`,
D9-1-era PURPOSE-only, D9-6/D9-7-era PURPOSE+TRANSITION+CAUSED_BY — all three byte-identical on
shot_type/description, shot_archetype simply None), the new WARN gate `check_shot_archetype_valid`
firing ONLY on an invalid catalog id — never on an absent one, since tagging is optional (unlike
every prior D9-1/D9-6/D9-7 "present" check), `generate_coverage_frames` threading shot_archetype
onto its frame dicts AND proof the id never reaches the actual image-generation prompt string,
`enforce_setup_variety`'s content-swap carrying shot_archetype along with shot_type/description/
purpose_kind/etc (same "travels with content, not position" judgment call as D9-1/D9-6/D9-7), and
`plan_moments_deterministic` preserving shot_archetype end to end including a floor-added filler
shot correctly landing with none. `storyengine/backend/tests/functional/test_d11_1_shot_archetype_
stamp.py` (3 tests, new) proves `store_scene`'s INSERT stamps `shot_archetype` from a frame dict's
field (present as the LAST positional param, NULL-default, independently per-shot within one
moment) — same "store_scene is the one real stamping site" reasoning as D9-1/D9-6/D9-7.
`storyengine/backend/tests/functional/test_d9_1_shot_purpose_stamp.py` (3 assertions) and
`test_d9_6_7_transition_causality_stamp.py` (4 assertions) were UPDATED (not left broken): this
chunk's migration 149 appends `shot_archetype` AFTER migration 148's caused_by in the INSERT's
column list, which shifted their hardcoded negative-index positional assertions off target by one
— caught by running both stamp tests after this chunk's change, fixed (`params[-5]`/`params[-4]` →
`params[-6]`/`params[-5]` for D9-1's; `params[-3]/-2/-1` → `params[-4]/-3/-2` for D9-6/D9-7's) with
comments explaining why, re-verified passing — same discipline D9-6/D9-7 itself used when it
shifted D9-1's stamp test the same way one migration earlier. Real stash-proof (patch-file
technique, never `git stash`, per tasks/lessons.md's fleet rule): `git diff --cached` of the full
chunk (9 touched/new files) saved to a patch, `git apply -R` reverted the tree to byte-identical
pre-chunk state (confirmed via `git status --short` empty), pipeline suite (`test_board_laws.py` +
`test_d6_2_repair_stamps.py` + `test_coverage.py` + `test_d9_1_shot_purpose.py` +
`test_d9_6_7_transition_causality.py`) back to 190/190 passing reverted, full backend suite
(`./venv/bin/python -m pytest tests/ -q`, main checkout's venv binary against worktree code) 29
failed / 3946 passed / 4 skipped reverted — sorted FAILED-test-name sets diffed byte-identical
(empty diff) against this chunk's own applied-state run (29 failed / 3949 passed — the +3 delta is
exactly this chunk's own new `test_d11_1_shot_archetype_stamp.py` tests) — then the patch
forward-applied cleanly (`git apply`, no conflicts) to restore the chunk. `schema.sql`'s `assets`
table updated with the new `shot_archetype` column, comment cross-referencing migration 149.

What is NOT verified: the migration actually running against the real Supabase Postgres instance;
whether Claude ever spontaneously reaches for the ARCHETYPE row at all given it's purely optional
(rule 27 says "MAY", so a real planner might simply never use it — that's a legitimate outcome, not
a bug, but it also means the catalog's real-world value is unproven until a session watches actual
plans use it); whether the ids Claude picks, when it does tag a shot, cluster sensibly by category
or drift toward a handful of favorites; and whether `check_shot_archetype_valid`'s WARN-only
posture should be promoted to a hard gate once that track record exists (explicitly flagged as
hard-eligible under Ruling 1 in the check's own docstring, but promotion is a separate, deliberate
call, not automatic).

## D11-2: per-shot DP (director of photography) fields as structured data (migration 150)

**What is deferred:** live proof that the coverage planner (Claude, via the coverage system
prompt) actually writes the new OPTIONAL `DP: <lens_mm> | <camera_height> | <dof>` row (rule 28)
on a real scene, and that `check_shot_dp_valid`'s WARN gate fires correctly against whatever
Claude actually writes — a prompt-only change; no test in this chunk calls the real Claude API,
mirroring exactly the deferred-verification gap D11-1 (ARCHETYPE) logged one chunk earlier. Rule
28 being OPTIONAL means the planner may simply never use it, which is fine — but if it DOES, the
lens_mm/camera_height/dof vocabulary needs to actually match what the checker enforces:

```bash
# 1. Lock the deploy window first (see storyengine/CLAUDE.md's VPS coordination rule), then
#    deploy this branch normally: push main, then
#    scripts/se.sh deploy <session-name> [--with-frontend]

# 2. Confirm the migration actually ran
scripts/se.sh db "SELECT column_name FROM information_schema.columns WHERE table_name='assets' AND column_name IN ('lens_mm','camera_height','dof')"
# Expect three rows back.

# 3. Generate a real scene's coverage directive (any normal chat/coverage-build flow) and read
#    the raw directive text (scripts/coverage_to_app.py writes it, or grab it from
#    scripts.coverage_directive on the scene row) — look for DP: rows under some of the
#    MASTER/ANGLE lines (and their PURPOSE/TRANSITION/CAUSED_BY/ARCHETYPE siblings, if present).
#    Since rule 28 says "MAY", zero rows on any given scene is NOT a failure; the interesting
#    failure mode is a DP row present with a camera_height/dof word NOT in
#    storyboard.coverage.CAMERA_HEIGHT_KINDS/DOF_KINDS, or a lens value outside 10-200mm or not
#    shaped like "<digits>mm" (the exact things check_shot_dp_valid warns on — check the
#    coverage-run logs for "⚠️ shot-DP check (D11-2)" lines).

# 4. Draw that same scene's real pictures (spend gate — confirm cost with Ryan first) and confirm
#    the columns actually populate:
scripts/se.sh db "SELECT id, shot_type, lens_mm, camera_height, dof FROM assets WHERE video_id='<vid>' AND scene=<n> ORDER BY image_index"
# Expect lens_mm/camera_height/dof populated (non-NULL) for whichever shots the planner chose to
# tag — very likely a MINORITY of shots (optional, unlike PURPOSE/TRANSITION/CAUSED_BY), NULL is
# expected and fine for the rest. A shot may carry only SOME of the three (e.g. lens_mm set,
# camera_height/dof NULL) — that's the taught grammar working as designed, not a bug.
```

**What IS verified (code-level + full local test suite passes, not live prod):**
`skills/video-pipeline/tests/test_d11_2_shot_dp.py` (28 tests, new) covers the vocabulary
constants (`CAMERA_HEIGHT_KINDS` = ground/low/waist/chest/eye/high/overhead, `DOF_KINDS` =
shallow/medium/deep, `DP_LENS_MIN_MM`/`DP_LENS_MAX_MM` = 10/200), `parse_coverage`'s extraction of
the per-shot `DP: <lens_mm> | <camera_height> | <dof>` row — each of the three pipe-separated
slots independently optional (lens-only with no pipes at all, middle slot skipped but its pipe
kept, only the first slot populated, etc), tolerant of bold/case, correctly independent when
stacked with PURPOSE/TRANSITION/CAUSED_BY/ARCHETYPE in ANY order (same latest-starting-candidate
mechanism D9-6/D9-7/D11-1 built, now handling five row types instead of four), BACKWARD
COMPATIBILITY against ALL FOUR prior directive eras (legacy zero-metadata-row `SAMPLE`, D9-1-era
PURPOSE-only, D9-6/D9-7-era PURPOSE+TRANSITION+CAUSED_BY, D11-1-era +ARCHETYPE — all four
byte-identical on shot_type/description, lens_mm/camera_height/dof simply None), the new WARN gate
`check_shot_dp_valid` firing on an out-of-range lens (parsed but outside 10-200mm), a MALFORMED
lens value (text present but not shaped like "<digits>mm" — proven to not silently vanish to a
false "nothing written" None), an out-of-vocabulary camera_height, an out-of-vocabulary dof, and
all three independently on one shot (3 separate warnings, not 1 merged one) — never on an absent
row/slot, since the whole row is optional (unlike every prior D9-1/D9-6/D9-7 "present" check),
`generate_coverage_frames` threading lens_mm/camera_height/dof onto its frame dicts AND proof none
of the three (nor the literal "DP" label) ever reaches the actual image-generation prompt string,
`enforce_setup_variety`'s content-swap carrying all three DP fields along with shot_type/
description/purpose_kind/shot_archetype/etc (same "travels with content, not position" judgment
call as D9-1/D9-6/D9-7/D11-1), and `plan_moments_deterministic` preserving all three end to end
including a floor-added filler shot correctly landing with none.
`storyengine/backend/tests/functional/test_d11_2_shot_dp_stamp.py` (4 tests, new) proves
`store_scene`'s INSERT stamps lens_mm/camera_height/dof from a frame dict's fields (NULL-default,
independently per-shot within one moment, and a PARTIAL row — only one of the three slots stated —
stamps that one value with the other two staying NULL rather than getting invented) — same
"store_scene is the one real stamping site" reasoning as D9-1/D9-6/D9-7/D11-1, written name-keyed
via `_param_index` from the start (see below) rather than a positional index that would break on
the next chunk's trailing column.

**Stamp-test fragility fix (explicitly asked for in this chunk's brief):**
`test_d9_1_shot_purpose_stamp.py`, `test_d9_6_7_transition_causality_stamp.py`, and
`test_d11_1_shot_archetype_stamp.py` each shipped with a HARDCODED negative-index positional
assertion (`params[-6]`, `params[-4]`, `params[-1]`, etc) into `store_scene`'s INSERT params tuple
— three chunks running (D9-6/D9-7, D11-1, and now D11-2) each broke a different one of these files
by appending trailing columns after the ones the file was asserting on, requiring a manual
index-math fix every time. This chunk converts all three (plus the new D11-2 stamp test, written
name-keyed from the start) to compute a column's position from the INSERT's own column-name text
(which `_insert_columns()` already re-read from source for a `"X" in cols` sanity check) via a new
shared-shape `_column_names()` + `_param_index(name)` pair, duplicated per-file (matching the
existing per-file duplication convention rather than introducing a new shared test-util import).
`_column_names()` needed one wrinkle beyond a naive `.split(",")` + `.strip()`: the INSERT's SQL
string is built from several adjacent Python string literals split across source lines (for
readability), so the RAW SOURCE TEXT between two literals contains a stray
`"\n<indentation>"` artifact that glues onto the front of whichever column name sits right after a
line break (e.g. splitting on "," yields a token like `'"\n                "camera_height'`
instead of a clean `'camera_height'`) — confirmed live by actually running the split against the
real file before trusting it, not assumed. Fixed by taking the LAST identifier-like regex match
(`[A-Za-z_][A-Za-z0-9_]*`) in each token rather than a plain `.strip()`, which correctly recovers
`'camera_height'`, `'transition_kind'`, and every other affected token — verified end to end with a
standalone script that printed the parsed column list and each computed `_param_index()` result
against the ACTUAL current 34-column/32-param INSERT before trusting the fix in the test files
(shot_archetype→28, lens_mm→29, camera_height→30, dof→31, all correct against the real `$29`-`$32`
placeholders). `_param_index` also subtracts the two SQL-literal columns (`status`='done',
`generation_method`='coverage') that occupy a column-list slot but no `$N` placeholder. This ends
the recurring fragility going forward: a FUTURE chunk appending more trailing columns after `dof`
cannot break any of these four files' assertions again, since they no longer encode a position,
only a name.

Real stash-proof (patch-file technique, never `git stash`): `git diff` of the full chunk (6
touched + 3 new files) saved to a patch; the 3 new untracked files moved aside (not deletable via
`git checkout`, since they don't exist in `HEAD`); `git checkout --` on the 6 tracked files
reverted the tree to byte-identical pre-chunk state (confirmed via `git status --short` empty).
Pipeline suite (`tests/` minus two PRE-EXISTING, unrelated collection errors —
`test_sound_curation.py`/`test_ctr_12h_tracking.py` fail to import `sound_prompt_bot`/
`performance_tracker` under system `python3` 3.9.6 regardless of this chunk, confirmed via `git
status --short` showing zero diff on either file) ran 18 failed/546 passed reverted vs 18
failed/574 passed applied — the +28 delta is exactly this chunk's own new
`test_d11_2_shot_dp.py` tests — sorted FAILED-test-name sets diffed byte-identical (empty diff).
Full backend suite (`/Users/ryanayler/economy-fastforward/storyengine/backend/venv/bin/python -m
pytest tests/ -q`, the MAIN checkout's venv binary run against this WORKTREE's code, per this
chunk's own instructions) ran 29 failed/3958 passed reverted vs 29 failed/3962 passed applied —
sorted FAILED-test-name sets diffed byte-identical (empty diff); the applied run's 29 failures are
all in `test_custom_film_remotion.py` and `test_youtube_oauth_diagnostics.py`, pre-existing and
untouched by this chunk. The patch then forward-applied cleanly (`git apply`, no conflicts) and the
3 new files were moved back, restoring the chunk exactly (`git status --short` confirmed identical
to pre-revert). `schema.sql`'s `assets` table updated with the three new `lens_mm`/`camera_height`/
`dof` columns, comments cross-referencing migration 150. `coverage_to_app.py`'s `store_scene` INSERT
touched SURGICALLY — only the one SQL statement's column list, `VALUES` placeholder list, and
trailing `execute()` args, per this chunk's brief warning that another worker was editing a
different region of that same file concurrently (confirmed via `git diff --stat` showing only that
one file's 13-line diff, no unrelated hunks).

**Vocabulary decision worth a human glance:** rule 11 (FOUR CAMERA FACTS) states camera height as
FREE PROSE with illustrative examples ("bed height, eye height, low tilted up, standing height"),
not a fixed enum — that's WHY `check_camera_facts_present`'s own docstring calls facts (b)/(c) not
mechanically checkable. This chunk's `camera_height` field is therefore a NEW controlled
vocabulary, not a literal extraction of rule 11's words — it reuses rule 11's own recognizable
single words where they exist ("eye" from "eye height", "low" from "low tilted up") and extends
with ground/waist/chest/high/overhead to cover the same range of heights a director would actually
call out. If a future session sees Claude's real DP rows drifting toward height phrases NOT in
this set (e.g. writing "bed height" or "standing" literally, copying rule 11's own prose instead of
the DP row's controlled vocabulary), that's a prompt-wording issue in rule 28, not a parser bug —
worth tightening rule 28's phrasing rather than silently widening `CAMERA_HEIGHT_KINDS` to catch
whatever Claude happens to write.

What is NOT verified: the migration actually running against the real Supabase Postgres instance;
whether Claude ever spontaneously reaches for the DP row at all given it's purely optional (rule 28
says "MAY", so a real planner might simply never use it — that's a legitimate outcome, not a bug,
but it also means the field's real-world value is unproven until a session watches actual plans use
it); whether Claude, when it DOES use the row, keeps `camera_height` inside the taught vocabulary
or drifts toward rule 11-style prose phrases instead (see the vocabulary note above); whether the
ARCHETYPE-SYNERGY guidance in rule 28 (an archetype's typical_lens as lens_mm's default) actually
influences what Claude writes, since `shot_archetypes.format_archetype_menu()` does not surface
each archetype's `typical_lens` value to the planner at all (that field exists only in the Python
catalog, read-only for this chunk) — the synergy note is pure prompt guidance the planner would
have to already know or infer, not a value it can look up from what it's shown; and whether
`check_shot_dp_valid`'s WARN-only posture should be promoted to a hard gate once a track record
exists (explicitly flagged as hard-eligible under Ruling 1 in the check's own docstring for all
three checkable facts, but promotion is a separate, deliberate call, not automatic).

## D9-3 environment-lock harvest (branch `d9-3-environment-locks`) — apply migration 152 on next deploy window; RE-APPROVE environments so the locks actually populate (populate-or-inert trap, same shape as D9-2)

**Built and tested in a worktree only — migration 152 was NOT applied to prod this session**
(no prod-migration writes allowed from a build-only chunk). Same auto-apply mechanism as every
prior migration (`main.py`'s startup hook, tracked in `_migrations`, warn-not-fail on a per-file
error). Same shape as D9-2 (migration 151, character locks): these three columns populate ONLY at
environment-APPROVAL time — every existing environment row has NULL locks today, and stays NULL
forever unless its video's environments are re-approved. The canonical branch in
`_canonical_environment_locks_line`/`redraw_asset_image` never runs on a single real video until
that happens. The deploy-window recipe below MUST include a re-approval step, not just a migration
check — and per this chunk's own brief, it must specifically cover video
8d90df90-be0f-4328-b9d3-20f6bb5b71a6 (tenant ee93e6d1)'s three environments (Pod, Corridor, Elite
Viewing Hall — the same video D6-6b's material_map location-matching fix was proven against):

```bash
# 1. Lock the deploy window first (see storyengine/CLAUDE.md's VPS coordination rule), then
#    deploy this branch normally: push main, then
#    scripts/se.sh deploy <session-name> [--with-frontend]

# 2. Confirm the migration actually ran
se logs backend 200 | grep "152_environment_locks"
# Expect: "Migration applied: 152_environment_locks.sql"
se db "SELECT filename FROM _migrations WHERE filename = '152_environment_locks.sql'"
# Expect exactly 1 row.

# 3. Verify the columns exist
se db "SELECT column_name FROM information_schema.columns WHERE table_name = 'video_environments' \
  AND column_name IN ('architecture_lock', 'lighting_time_weather_lock', 'palette_lock')"
# Expect 3 rows.

# 4. THE POPULATE-OR-INERT TRAP: confirm today's rows are NULL (expected, not a bug)
se db "SELECT id, name, architecture_lock, lighting_time_weather_lock, palette_lock \
  FROM video_environments WHERE video_id='8d90df90-be0f-4328-b9d3-20f6bb5b71a6'"
# Expect all three NULL for every row (Pod, Corridor, Elite Viewing Hall) — proves nothing yet,
# this is the baseline.

# 5. Re-approve that video's environments (Environments tab -> "Approve environments" again; this
#    re-runs the SAME vision pass that already exists in prod today (the description-refresh
#    call), now with the extended labeled prompt — no NEW paid call is introduced beyond what
#    approval already costs; the prop-manifest extraction is a separate call, unaffected). Then
#    re-check:
se db "SELECT id, name, architecture_lock, lighting_time_weather_lock, palette_lock \
  FROM video_environments WHERE video_id='8d90df90-be0f-4328-b9d3-20f6bb5b71a6'"
# Expect architecture_lock/lighting_time_weather_lock/palette_lock populated for whichever
# environments' vision call succeeded and followed the labeled format. An environment with all
# three still NULL after this step means the vision reply didn't follow the labeled format that
# pass — check `se logs backend` for "[environments] D9-3 lock extraction partial for <name>"
# (this chunk's own warning) to confirm it degraded loudly rather than silently.

# 6. Plan (free) or draw (paid — confirm cost with Ryan first) that video's storyboard for a scene
#    set in a re-approved location, and confirm the assembled sheet-prompt text actually carries
#    an "ENVIRONMENT LOCKS — fixed for this whole set: ..." block with the exact lock text stored
#    in step 5. The D6-1 board-laws evidence at tasks/evidence/d6-6a-dryrun/sheet-preview_scene1_*
#    .txt shows this project already has a free way to dump the assembled sheet-prompt text for
#    review before any paid draw — reuse that path. This is the one step this chunk could not run
#    itself (no live prod DB access from this Mac — same gap D9-2's entry logged) and is the
#    strongest remaining proof gap: every consumer of `_env_locks_text`/
#    `_canonical_environment_locks_line` is unit-tested against synthetic rows, but no test here
#    proves a REAL re-approval's extracted text survives unchanged into a REAL assembled prompt
#    end to end.
```

**Scope call, stated plainly — the FINAL COVERAGE PICTURE batch path is NOT wired to these locks
in this chunk.** `_canonical_material_line`'s two production callers inside
`scripts/coverage_to_app.py` (the initial board-sheet-preview plan and its sweep/escalation
re-plan) both got an `env_locks_line` sibling this chunk, feeding a new `ENVIRONMENT LOCKS` block
into `_plan_sheet_prompts` — that covers "board... prompts" per the brief. For "final-picture
prompts", the ONLY final-picture composer that lives inside `coverage_to_app.py` itself is
`redraw_asset_image`'s repair leg (the material_map REPAIR LEG's exact sibling, now also emitting
an "Environment locks, fixed for this whole set: ..." clause). The FIRST-DRAW final-picture batch
path (`generate_coverage_for_video`'s call to `run_coverage()`) delegates its own prompt
composition entirely to `skills/video-pipeline/storyboard/coverage.py`, which this chunk's brief
explicitly forbade touching (another worker's region). That module already has its own "MATERIAL
MAP LOCK" section reading `matched_env.get("material_map")` from the SAME `canonical_envs`/
`matched_env` dicts `_approved_envs` now also populates with `architecture_lock`/
`lighting_time_weather_lock`/`palette_lock` — so the DATA is already flowing into that call
(`coverage_to_app.py:4709-4735`'s `canonical_envs=envs, matched_env=env`), but nothing in
`coverage.py` reads the three new keys yet. Wiring that in is real, valuable follow-up work for
whichever chunk next has clearance to edit `coverage.py`'s material-lock section — flagged here
rather than silently left unstated.

**No WARN drift check was added.** The brief asked for one "mirroring `check_material_map_
consistency`'s shape if one fits naturally; skip if it doesn't — state your call." Grepped the
whole backend (`story_laws.py`, `routes/*.py`) for that name and for any material_map-consistency
WARN check: none exists anywhere in this codebase today — `story_laws.py` has exactly three
`check_*` functions (`check_scene_location_law`, `check_location_transit_law`,
`check_cast_consistency_law`), none of which compare a canonical field's text against anything.
D9-2 (character locks, the direct sibling chunk this one templates from) made the identical call
one chunk earlier: `forbidden_drift` is "STORED ONLY... not yet read by any prompt or the frame
arbiter" with no drift check either, deferred to D9-4. Skipped here for the same reason —
inventing a drift check against a function that doesn't exist would be building new law, not
mirroring existing law, and the brief's own phrasing ("if one fits naturally") anticipated this.

**What IS verified (code-level + full local test suite passes, not live prod):**
`storyengine/backend/tests/functional/test_d9_3_environment_locks.py` (24 tests, new) covers
`_parse_environment_lock_reply` (full labeled reply, a reply missing one or more labels, a reply
that ignores the format entirely — parses to `{}`, never raises — multi-line values, case
insensitivity), `approve_environments`' background task with the vision call stubbed AND the
separate `_extract_env_props` call stubbed to fail (isolating the lock-population assertions from
the unrelated prop-manifest call): the happy path writes all three lock columns AND `description`
in exactly ONE `UPDATE` (proving the "one call, not two" requirement at the SQL-write level, not
just prompt level) while confirming the description/locks vision call itself only fires ONCE, a
reply with no labels falls back to the exact pre-D9-3 whole-reply-as-description behavior and
writes zero lock columns, a partial reply (some labels present, some missing) writes only the
fields that parsed and leaves the others untouched (not nulled), a raising vision call degrades
exactly as fail-soft as the pre-existing description-refresh pass, and the no-Claude-creds case
skips the whole vision pass (zero calls) with approval still completing. `scripts/coverage_to_app
.py`'s consumer side: `_env_locks_text` (join-skip-empty, mirrors `_locks_text`) tested for every
presence combination, `_canonical_environment_locks_line` (mirrors `_canonical_material_line`
exactly) tested for the single-location case, the multi-location/LOCSET case (one clause per
location that has locks, a location with none simply omitted, never invented), the KEY backward-
compat case (all-NULL locks -> "", proven directly), and the no-match case. `_approved_envs`
proven to SELECT the three new columns and carry their values through unmodified. `_plan_sheet_
prompts` proven to stamp locks VERBATIM into their own "ENVIRONMENT LOCKS" block positioned
immediately after "MATERIAL MAP" (matching the concatenation order in the source), AND — the key
NULL-locks byte-identical test — a call with `env_locks_line=""` produces OUTPUT BYTE-IDENTICAL to
a call that never passes the parameter at all (`with_default == with_explicit_empty`, asserted
directly), proving every pre-migration-152 call site is unaffected. All pre-existing tests in
`test_c4_prop_manifest.py`, `test_money_safety_character_environment_metering.py`, and
`test_d9_2_character_locks.py` pass unmodified (97 passed across the targeted `-k
"environ or material or D6_1 or d6_1"` sweep). Real stash-proof (patch-file technique, never `git
stash`, per tasks/lessons.md's fleet rule): `git diff` of the 3 modified files saved to a patch;
the 2 new untracked files (migration + test) moved to the scratchpad; `git checkout --` on the 3
tracked files reverted the tree to byte-identical pre-chunk state (confirmed via `git status
--short` empty). Full backend suite (`/Users/ryanayler/economy-fastforward/storyengine/backend/
venv/bin/python -m pytest tests/ -q`, the MAIN checkout's venv binary run against this WORKTREE's
code) ran 29 failed / 4033 passed / 4 skipped reverted vs 29 failed / 4057 passed / 4 skipped
applied — the +24 delta is exactly this chunk's own new test file; sorted FAILED-test-name sets
diffed byte-identical (empty diff, exit 0) — the applied run's 29 failures are all in
`test_custom_film_remotion.py` and `test_youtube_oauth_diagnostics.py`, pre-existing and untouched
by this chunk. The patch then forward-applied cleanly (`git apply`, no conflicts) and the 2 new
files were moved back, restoring the chunk exactly (`git status --short` confirmed identical to
pre-revert). `schema.sql`'s `video_environments` table updated with the three new columns and
comments cross-referencing migration 152 (note, matching D9-2's own honest flag: migration 142's
`material_map` is ALSO still missing from `schema.sql`'s `video_environments` definition — a
pre-existing drift from before D9-3 touched the table, left alone, same class of gap D9-1's and
D9-2's entries above both flagged).

**Diff confined to the environment/material canonical-insert region, per this chunk's own
file-boundary rule** (another worker was in `coverage.py`'s narrative/pacing region and in
`routes/characters.py` concurrently): `git diff --stat` shows exactly 3 files touched
(`routes/environments.py` +123/-managed, `scripts/coverage_to_app.py` +110/-managed, `schema.sql`
+13) plus 2 new files (migration, test); every hunk in `coverage_to_app.py` sits inside
`_approved_envs`, `_canonical_material_line`'s neighborhood, `_plan_sheet_prompts`,
`generate_storyboard_sheet_for_scene`, or `redraw_asset_image` — confirmed via `git diff -- ... |
grep "^@@"` showing only those five functions' line ranges, nothing in the narrative/pacing region
and nothing in `characters.py`/`script_quality.py`/`pipeline_executor.py`/`skills/video-pipeline/**`.

What is NOT verified: the migration actually running against the real Supabase Postgres instance;
whether the extended vision prompt reliably produces the labeled format on a real, unseen reference
image (prompt compliance is never provable from a parser unit test — steps 5-6 above are what
that's for); a real re-approval's extracted architecture_lock/lighting_time_weather_lock/
palette_lock text surviving unchanged into a REAL assembled board or final-picture prompt (step 6
— the strongest remaining gap, no live DB access from this Mac); whether `coverage.py`'s own
MATERIAL MAP LOCK section should be extended to also read the three new keys now flowing through
`matched_env` (a real, valuable follow-up, out of scope per this chunk's file-boundary rule — see
the scope call above); and whether skipping a WARN drift check entirely (no analogous check exists
to mirror) is the right permanent posture once D9-4 (or a sibling chunk) revisits `forbidden_drift`
consumption for characters — the two decisions should probably be made together, not separately.

## G5: machine_research_cards roster-index identity + recovery replay — 2026-07-30

**What shipped:** migration `153_machine_research_cards_roster_index_identity.sql` moves
`machine_research_cards`' PRIMARY KEY from `(tenant_id, video_id, machine_key)` to `(tenant_id,
video_id, roster_index)` — `machine_key` (`_normalized_unit_code(machine)`) is a lossy
derivation two DISTINCT locked roster entries can share, e.g. roster item 9 ("Audacious class /
Malta class") and item 13 ("CVA-01 class") on video `d2e37cd6-521a-43aa-a14d-ce096a783c1e` both
normalize to `CVA01`, so the old `ON CONFLICT (tenant_id, video_id, machine_key)` let the second
write silently clobber the first row. `_upsert_machine_research_card` / `_update_machine_research_
validation` / `_load_machine_research_cards` / `enrich_research_payload_readiness` /
`run_roster_orchestrator` / `roster_repair_dashboard` were all switched to roster_index as the
real identity (`pipeline_executor.py`).

### 1. Migration NOT applied to prod (build-only chunk, no prod-migration writes)

Same pattern as migration 145/148 above: `main.py`'s `_run_pending_migrations()` auto-applies
every unrun `.sql` file in `backend/migrations/` on the next backend restart/deploy (tracked in
the `_migrations` table), so this does not need a manual apply step — verifying it landed after
the next deploy matters more. Confirm with:

```bash
storyengine/scripts/se.sh db "SELECT filename, applied_at FROM _migrations WHERE filename = '153_machine_research_cards_roster_index_identity.sql'"
```

### 2. Recovery replay for the confirmed-damaged video — NOT run against prod by this chunk (read-only DB access only, per the G5 cost cap)

Confirmed live (read-only, 2026-07-30): video `d2e37cd6-521a-43aa-a14d-ce096a783c1e`
(tenant `561b872d-7b73-45e3-9c44-7f30c3566eda`, "Every British Aircraft Carrier Class Ever
Built") has a 23-entry locked roster but only **21** `machine_research_cards` rows / 21 distinct
`machine_key` values. Confirmed by reading `roster_index` for every stored row (`SELECT
roster_index, machine_key, machine_name FROM machine_research_cards WHERE video_id = '...'
ORDER BY roster_index`): **roster_index 9 and roster_index 21 are the two missing slots** - the
"last write wins" clobber kept roster_index 13 (machine_key `CVA01`, "CVA-01 Queen Elizabeth
class (1960s design) CVA-01 class") over roster_index 9 (same `CVA01`, "CVA-01 predecessors
Audacious class / Malta class"), and kept roster_index 22 (machine_key
`LENDLEASEESCORTCARRIERS`, "Lend-Lease escort carriers Ruler class (US-built)") over
roster_index 21 (same key, "Lend-Lease escort carriers Attacker class (US-built)").
`research_payload->unit_research_cards` still has all 23 entries intact (never keyed by
machine_key), so `scripts/replay_research_cards.py` can recover both dropped rows once migration
153 has been applied (the script's own upsert uses the same roster_index-keyed ON CONFLICT, so
running it against the OLD schema would just repeat the original collision).

**Exact invocation, once migration 153 is live on prod:**

```bash
# Dry run first - reports what WOULD change, writes nothing:
python3 scripts/replay_research_cards.py \
  --video-id d2e37cd6-521a-43aa-a14d-ce096a783c1e \
  --tenant-id 561b872d-7b73-45e3-9c44-7f30c3566eda

# Expected dry-run report: before=21, unchanged=21, recover=2 (roster slots 9 and 21 - the two
# confirmed-missing roster_index values above), missing_card=0, after=23. Re-run the SELECT
# above first if this has drifted (another session may have already repaired or re-researched
# one of these two roster slots between this note and the actual apply).

# Then actually write:
python3 scripts/replay_research_cards.py \
  --video-id d2e37cd6-521a-43aa-a14d-ce096a783c1e \
  --tenant-id 561b872d-7b73-45e3-9c44-7f30c3566eda \
  --apply --json
```

**Expected before/after row counts:** `machine_research_cards` rows for this video go from
**21 -> 23**, `COUNT(DISTINCT machine_key)` stays **21** (both recovered rows legitimately share
a machine_key with their surviving sibling — that's the whole point of the fix), verified via:

```bash
storyengine/scripts/se.sh db "SELECT COUNT(*) AS row_count, COUNT(DISTINCT machine_key) AS distinct_keys FROM machine_research_cards WHERE video_id = 'd2e37cd6-521a-43aa-a14d-ce096a783c1e'"
# before: {"row_count": 21, "distinct_keys": 21}
# after:  {"row_count": 23, "distinct_keys": 21}
```

What is NOT verified: the migration actually running against the real Supabase Postgres
instance; the replay script actually invoked against prod (this chunk's cost cap was read-only
SQL only — no prod writes of any kind); whether any OTHER video in prod has the same
machine_key-collision damage (this chunk only confirmed and sized the one video named in the
brief — a fleet-wide `SELECT video_id, COUNT(*) FROM machine_research_cards GROUP BY video_id
HAVING COUNT(*) < (roster length)`-style sweep across all static_docu videos was out of scope
and has not been run).

---

## D12-2 — distinct render treatments per transition_kind (2026-07-30)

**Scope:** transition_engine.determine_transition (skills/video-pipeline/render/audio_sync/) now
maps assets.transition_kind (migration 148, D9-6 harvest — opening/continuous/time_cut/
location_cut/montage/memory) to a distinct treatment where act-boundary/style-change don't already
fire; render_static_ffmpeg.build_transition_plan/build_group_join_filter_complex (storyengine/
backend/) honor two new join shapes (reused "cut"/"fade"; new "dissolve" — a true
`xfade=transition=fade` cross-dissolve, distinct from the fade-through-black "fadeblack" every
prior type used); render_static._gather_segments/_build_render_config thread assets.transition_kind
from the DB row into the scene dicts determine_transition reads. render_stitch.py (grok-native
concat) is untouched by design — literal concatenation, no transition grammar exists there to
extend; documented as a standing limitation, not a gap of this chunk.

**Threading trace (assets row -> render config -> transition):** render_static._gather_segments's
assets SELECT now fetches `transition_kind`; each image dict in a segment's `images` list carries
it through unchanged (`_images_for_segment` already passed the full dict, no change needed there);
`_build_render_config` copies it onto each per-image scene dict it appends to `scenes` (key:
`transition_kind`); `assign_transitions(scenes)` (unchanged call site) invokes
`determine_transition(scenes[i], scenes[i+1])` per boundary, which reads
`next_scene.get("transition_kind")` — the INCOMING shot's own kind, mirroring
ShotDraft.transition_from_previous's semantics (the kind describes how THAT shot cuts in from the
one before it, matching custom_film_director.py:288-291). `render_static_ffmpeg.build_transition_
plan` then reads the resulting `transition_out.type`/`duration` off each scene dict (unchanged
contract) and maps it to a join style; `build_group_join_filter_complex` picks the xfade
`transition=` name per-boundary from that join's own `style` (`_XFADE_TRANSITION_BY_STYLE`), not a
group-wide mode, so a "fade" boundary and a "dissolve" boundary can sit in the same fade-chain
group with each keeping its own shape.

**Treatment map** (skills/video-pipeline/render/audio_sync/config.py, all new constants):
continuous/time_cut -> `{"type": "cut", "duration": HARD_CUT_DURATION=0.0}` (same hard-cut
treatment for both — the spec draws no render distinction between them); location_cut ->
`{"type": "crossfade", "duration": LOCATION_CUT_FADE=0.4}` (same shape/duration as today's generic
default, kept as its own named constant for independent tuning); montage -> `{"type": "crossfade",
"duration": MONTAGE_FADE=0.25}`; memory -> `{"type": "dissolve", "duration": MEMORY_DISSOLVE=0.8}`
(the one genuinely new render treatment — true cross-dissolve in the ffmpeg engine). "opening" has
no map entry by design: assign_transitions never routes the FIRST scene's transition_in through
determine_transition at all (hardcoded fade_from_black), so nothing needed to special-case it;
confirmed with a test asserting a stray "opening" kind still falls through to the generic default
unchanged.

**Precedence proof:** `test_act_change_wins_over_kind` and `test_style_change_wins_over_kind`
(skills/video-pipeline/render/audio_sync/tests/test_transitions.py) construct a boundary with BOTH
an act/style change AND a kind (e.g. act change + `transition_kind: "memory"`) and assert the
dip_to_black/STYLE_CHANGE_FADE result wins, kind never consulted — matches the rule ordering in
determine_transition's docstring (1: act, 2: style, 3: kind, 4: generic default) where kind sits
strictly between style and the old generic fallback, never above either proven rule.

**Absent-kind byte-identical proof:** three layers — (a) determine_transition:
`test_absent_kind_is_byte_identical_to_pre_d12_2_behavior` / `test_null_kind_is_byte_identical_to_
absent_kind` assert the exact pre-chunk dict; (b) assign_transitions:
`test_full_scene_list_byte_identical_with_and_without_kind_key_present_but_null` diffs a full
multi-scene plan built with the key omitted vs the key present-but-None, scene-by-scene equal; (c)
render_static._build_render_config: `test_build_render_config_backward_compat_no_kind_anywhere`
proves the real render-config builder (not a hand-built scene dict) produces the exact pre-D12-2
generic-crossfade result when no asset row in the batch carries a kind — the realistic "every video
before migration 148" case, since transition_kind is NULL on every pre-migration asset row.

**A genuine bug found and fixed in the same diff:** render_static_ffmpeg.build_transition_plan's
duration line was `float(t.get("duration") or 0.4)` — Python falsy-0.0 discards an EXPLICIT zero
duration and silently substitutes 0.4. Harmless before this chunk (no type ever legitimately
carried 0.0), but HARD_CUT_DURATION=0.0 now flows through this exact line for continuous/time_cut,
so it was fixed to an explicit `is not None` check (surfaced by
`test_build_transition_plan_kind_cut_type_still_maps_to_cut_style` failing with 0.4 instead of 0.0
before the fix). The duration is not consumed downstream for "cut"-style joins today (group_by_cuts
only reads `style`, never a cut join's duration inside the fade-chain filter builder), so this had
no live behavioral consequence pre-fix, only a wrong value sitting in the plan dict — fixed anyway
since the plan dict is exactly what this chunk's tests (and any future consumer) assert against.

**Stash-proof method:** never used `git stash` or any in-place revert of this worktree's own
tracked files. "Reverted" state = the untouched MAIN checkout
(`/Users/ryanayler/economy-fastforward/storyengine` + its sibling `skills/video-pipeline` and
`remotion-video`, confirmed clean of any change to the touched files via `git status --short`
before starting) run with the SAME venv binary
(`/Users/ryanayler/economy-fastforward/storyengine/backend/venv/bin/python`) the worktree tests
also ran under. This is safer than an in-place patch/checkout cycle — zero risk to this branch's
own git state — and mathematically equivalent, since main's backend/skills files at the commit this
branch forked from ARE the pre-chunk code.

**Full backend suite, reverted vs applied, sorted FAILED-test-name sets:** initial applied run
showed 29 failures (28 in test_custom_film_remotion.py + 1 pre-existing) vs reverted's 1 — traced
to a FRESH-WORKTREE ENVIRONMENT GAP, not a code regression: `custom_film_remotion.renderer_bundle_
hash()` hashes real files under `remotion-video/node_modules/@fontsource/...` and
`remotion-video/public/motion-audio/*.wav`, both entirely gitignored (`remotion-video/public/` line
41 of root .gitignore; `remotion-video/node_modules/` via remotion-video/.gitignore) and therefore
never materialized by `git worktree add` — present in the main checkout only because `npm install`
+ `scripts/generate-motion-audio.mjs` were run there at some point outside git. Confirmed root
cause by symlinking both paths from the main checkout into the worktree (read-only, for
verification only, removed again after — never committed, `git status --short` empty of them) and
re-running: all 81 test_custom_film_remotion.py tests then passed. This is a standing gap for ANY
worker in ANY fresh worktree touching that test file, unrelated to this or any specific chunk's
diff — not something a python transitions-render chunk should fix (touches `custom_film_*`,
explicitly out of scope). With the environment gap corrected for a true apples-to-apples run:
reverted 1 failed / 4085 passed / 4 skipped vs applied 1 failed / 4108 passed / 4 skipped (delta
+23 = exactly this chunk's new test file, `tests/test_d12_2_transition_kind_render.py`); sorted
FAILED-name sets diffed BYTE-IDENTICAL (`diff` exit 0) — both sides' one failure is
`test_youtube_oauth_diagnostics.py::test_youtube_oauth_diagnostics_reports_missing_config_without_
secret_values`, pre-existing (a missing `youtube_oauth_diagnostics` attribute on `routes.google_
auth`, unrelated to rendering), confirmed present on the untouched main checkout too.

**audio_sync suite, reverted vs applied:** `render/audio_sync/tests/test_run_audio_sync_keyless.py`
makes REAL network calls to the OpenAI Whisper API (visible in captured output: real HTTP 401s
against a fake key) and is demonstrably flaky independent of any code change — proven by running it
in isolation twice on the UNMODIFIED main checkout and getting the SAME 4 failures both times, then
running the byte-identical file (confirmed via `diff`, exit 0, on both the test file and
`run_audio_sync.py` under test) on the worktree and getting a DIFFERENT 5-failure set depending on
whether it ran alone or alongside the rest of the directory. It imports only `render.audio_sync.
transcriber` and `render.run_audio_sync` — zero dependency on transition_engine.py or config.py, so
this chunk cannot be the cause. Excluding that one pre-existing flaky file
(`--ignore=render/audio_sync/tests/test_run_audio_sync_keyless.py`), the REST of the audio_sync
suite is fully deterministic and byte-identical in shape: reverted 52 passed / 0 failed vs applied
68 passed / 0 failed (delta +16 = exactly the new TestTransitionKindTreatments tests added to
test_transitions.py). test_transitions.py alone: reverted 8 passed vs applied 24 passed (the same
+16), 0 failed either side.

**What is NOT verified:** an actual rendered video frame — every assertion here is on constructed
plan dicts / filtergraph strings, never a real ffmpeg or Remotion invocation (matches this chunk's
$0 budget; a real eyeball pass on a rendered video with each kind belongs in the deploy-window
verification pass, per the brief). The Remotion engine (default, `STATIC_RENDER_ENGINE=remotion`)
was NOT modified — Scene.tsx has no true cross-dissolve compositing, so the memory kind's
"dissolve" only becomes a literal cross-dissolve on the ffmpeg engine
(`STATIC_RENDER_ENGINE=ffmpeg`); on Remotion it still renders as a longer fade-through-black
(duration-driven from the same 0.8s, since Scene.tsx's opacity curve only special-cases "cut", not
type-by-name — verified by reading Scene.tsx:403-426, not modified). Whether STATIC_RENDER_ENGINE=
ffmpeg is even the production-default engine for any current customer video was not checked — if
it isn't, this chunk's distinct treatments are real in the constructed plan but only visually
distinct on a render that opts into the ffmpeg engine today. No migration, no planner/prompt
changes (none needed — migration 148 and its planner-side TRANSITION line already ship, per the
brief). No live DB read of a real video's assets.transition_kind values to confirm the planner is
actually populating non-NULL kinds at the volume assumed — not checked from this Mac.

## D9-3b: environment locks threaded into run_coverage's FIRST-DRAW batch path (branch `d9-3b-batch-locks`) — closes the KNOWN GAP D9-3 flagged in its own entry above

D9-3 harvested `video_environments.architecture_lock`/`lighting_time_weather_lock`/
`palette_lock` (migration 152) and wired them into `coverage_to_app.py`'s sheet-PREVIEW path
(`_plan_sheet_prompts`) and the redraw/repair leg (`redraw_asset_image`), but explicitly left
`storyboard/coverage.py`'s `run_coverage()` — the FIRST-DRAW final-picture batch path — untouched,
naming it as a known gap in its own entry above ("whether `coverage.py`'s own MATERIAL MAP LOCK
section should be extended to also read the three new keys now flowing through `matched_env`").
This chunk closes exactly that gap and nothing else.

**What changed** (`skills/video-pipeline/storyboard/coverage.py` only, plus its test file):
1. New `_env_locks_text(row)` — join-skip-empty helper, hand-mirrors
   `coverage_to_app._env_locks_text` byte-for-byte (kept in sync, not imported: this module is the
   one `coverage_to_app.py` imports FROM, never the reverse — the same boundary
   `canonical_material_line` already respects for `material_map`).
2. New `canonical_environment_locks_line(canonical_envs, location_sets, matched_env)` —
   hand-mirrors `coverage_to_app._canonical_environment_locks_line`'s exact shape (same
   multi-location LOCSET loop + single-location fallback, same whole-word `_find` matcher),
   itself modeled one-to-one on `canonical_material_line` (D6-1c) one clause over.
3. `run_coverage()`: a new ENVIRONMENT LOCKS block stamped into every shot's draw-prompt
   description, immediately after the existing MATERIAL MAP LOCK block (`coverage.py` around the
   line stamping "Material map, fixed for this whole set: ..."), using the EXACT phrasing D9-3's
   own REPAIR LEG already uses in `redraw_asset_image` — "Environment locks, fixed for this whole
   set: {joined locks}." — so the batch-drawn prompt and a later manual redraw of the same shot
   read byte-identical lock text.

**No new plumbing.** `run_coverage(canonical_envs=, matched_env=)` already existed (D6-1c) and
`coverage_to_app.py`'s one call site that passes them (`generate_coverage_for_video`, ~line 4807)
already sources both from `_approved_envs`/`_match_scene_env` — and `_approved_envs`'s SELECT was
already extended to fetch all three lock columns by D9-3 itself. So the env dicts landing in
`canonical_envs`/`matched_env` inside `run_coverage` already carried `architecture_lock`/
`lighting_time_weather_lock`/`palette_lock` before this chunk touched anything; this chunk only
added the READER. The CLI's `main()` (second `run_coverage` call site, ~line 5008) still passes
neither kwarg — unchanged, exactly as D6-1c's material_map plumbing already left it.

**Verification ($0, no live DB/API access from this Mac):**
- Threading trace: `coverage_to_app.py:4830-4831` (`canonical_envs=envs, matched_env=env`, envs
  from `_approved_envs` which SELECTs the three lock columns since D9-3) → `run_coverage`'s
  `canonical_envs`/`matched_env` params (already existed) → new
  `canonical_environment_locks_line(canonical_envs, location_sets, matched_env)` call → new
  ENVIRONMENT LOCKS block → every shot's `description` field, which `store_scene`/`assets.
  image_prompt` persist verbatim (unchanged downstream — same mechanism the SEQUENCE/FACING/
  MATERIAL locks already ride on).
- 6 new tests added to `skills/video-pipeline/tests/test_board_laws.py`: 3 unit tests on
  `canonical_environment_locks_line` (single-location match, NULL/no-match → `""`, LOCSET key
  with a leading article still resolves per-location without cross-contamination — mirrors the
  three `canonical_material_line` unit tests exactly) and 3 `run_coverage` integration tests
  (populated locks land on every shot, adjacent to and after Material map; `canonical_envs=None`
  produces a description byte-identical to a sibling `run_coverage` call with the kwargs omitted
  entirely and contains no "Environment locks" text anywhere; a matched env row with all three
  lock columns NULL — every production row today, pre-re-approval — also omits the block). Ran
  standalone (`python3 tests/test_board_laws.py`) and via pytest; the "🔒 environment-locks lock
  applied" print line appears exactly once across the whole run, confirming it never fires for the
  two NULL-locks tests.
- `skills/video-pipeline` suite: `tests/test_coverage.py` + `tests/test_board_laws.py` +
  `tests/test_d9_1_shot_purpose.py` + `tests/test_d9_6_7_transition_causality.py` +
  `tests/test_d11_1_shot_archetype.py` + `tests/test_d11_2_shot_dp.py` = 241 passed (well above
  the 179+ baseline named in this chunk's brief).
- Full `skills/video-pipeline/tests/` sweep (excluding two pre-existing collection errors,
  `test_ctr_12h_tracking.py`/`test_sound_curation.py`, both `ModuleNotFoundError` on unrelated
  modules, present before this chunk touched anything): patch-file stash-proof (`git diff` saved to
  a scratchpad patch, `git apply -R` to revert in place, run, `git apply` to reforward — never
  `git stash`, per the fleet rule). Reverted: 18 failed / 585 passed. Applied: 18 failed / 591
  passed (+6 = exactly this chunk's own new tests). Sorted FAILED-test-name sets diffed
  byte-identical (empty diff, exit 0).
- Full backend suite: this worktree has no `backend/venv` of its own (never provisioned here), so
  — mirroring D12-1's node_modules/motion-audio scaffolding trick, stated here — `storyengine/
  backend/venv` was a **temporary symlink** to the MAIN checkout's own `backend/venv` (`ln -s
  /Users/ryanayler/economy-fastforward/storyengine/backend/venv venv`), used only to run
  `./venv/bin/python -m pytest tests/ -q` against THIS worktree's code, then deleted immediately
  after (`git status --short` before AND after the symlink existed is confirmed identical — the
  symlink is untracked scaffolding, never staged, never part of the diff). Note for whoever reads
  this next: because `venv` is now a broken/absent path again, `git check-ignore` on it behaved
  inconsistently while the symlink existed (a directory-only gitignore pattern like `venv/` does
  not match a *symlink* named `venv`, only a real directory — worth knowing if this trick is reused
  and `git status` unexpectedly shows the symlink as untracked instead of ignored). Reverted: 29
  failed / 4057 passed / 4 skipped. Applied: 29 failed / 4057 passed / 4 skipped (pass count
  unchanged — this chunk added zero backend-suite tests, only pipeline-suite tests, since the
  touched code lives entirely in `skills/video-pipeline/`). Sorted FAILED-test-name sets diffed
  byte-identical (empty diff, exit 0) — all 29 failures are in `test_custom_film_remotion.py` and
  `test_youtube_oauth_diagnostics.py`, the same pre-existing, unrelated set D9-3's own entry above
  already named.

**File-boundary discipline honored per this chunk's brief:** `git diff --stat` shows exactly 2
files touched — `skills/video-pipeline/storyboard/coverage.py` and its test file
`skills/video-pipeline/tests/test_board_laws.py`. `coverage_to_app.py` was read but NOT written
(another worker was flagged as active in its character-block region); no migration, no parser/
grammar changes, no route/frame_arbiter/render files touched.

**What is NOT verified:** a real re-approved environment's harvested locks surviving unchanged
into a REAL batch-drawn first-picture prompt end-to-end against live Supabase/Kie (no live DB/API
access from this Mac — same standing gap D9-3's own entry names for its two paths); whether the
CLI's `main()` (the second, un-wired `run_coverage` call site) should ALSO be threaded with
`canonical_envs`/`matched_env` someday — it wasn't threaded for `material_map` either (D6-1c), so
leaving it alone here is consistent with that precedent, not a new gap; and whether a WARN-only
drift check (mirroring `check_material_map_consistency`) should exist for a canonical-locks-vs-
prose disagreement — skipped deliberately, same reasoning D9-3's own entry gives (no planner-LLM
`[LOCKS | ...]` line exists to compare against in the first place, so there is nothing for such a
check to diff).

---

## D13-1: provider-dialect adapter (backend/provider_dialect.py)

**What shipped:** `backend/provider_dialect.py` — one adapter
(`dialect_for_model`, `decorate_grok_prompt`, `build_call`) that turns a
neutral `ClipDialectRequest` (prompt text, image url, ordered reference-image
slots, motion/duration params) into a provider-shaped `ClipDialectCall`
(final prompt string + kwargs dict) for whichever dialect a model id speaks
(grok / seedance / veo). `pipeline_executor.py`'s `_animate_for` (picked
which client method + kwarg shape to call), `_decorate` (Grok's
`@image1`/`@image2` token decoration), and the inline Veo branch (raw prompt
+ `image_url=` kwarg shape) were DELETED and replaced with calls into this
adapter — moved verbatim, not duplicated. `shared/clients/image_client.py`
is untouched; the adapter only shapes the request, the client still executes
it.

**Verified ($0, build-only, this chunk's cost cap):**
- Golden tests (`tests/functional/test_d13_1_provider_dialect_golden.py`, 6
  cases) drive the REAL `PipelineExecutor.run_clip_generation` end-to-end
  (DB/storage/ledger/network faked, shot-composition + dialect code real)
  and assert byte-identical prompt strings + kwargs for grok (bare, +sheet,
  +sheet+cast-names), seedance, and veo (fast + quality) — captured against
  pipeline_executor.py AS IT EXISTED BEFORE this chunk, then re-run
  unmodified after the refactor. All 6 pass in both states.
- Adapter unit tests (`tests/functional/test_provider_dialect.py`, 12 cases).
- Guard-neuter: `decorate_grok_prompt` short-circuited to return
  `core_prompt` unwrapped -> 4/6 golden tests failed with a real
  AssertionError (the 2 veo cases correctly kept passing, since veo never
  decorates) -> reverted, all 18 pass again.
- Full backend suite, reverted vs applied, sorted FAILED-test-name sets
  compared byte-identical: reverted baseline (scaffolded — see below) is
  4100 collected / 1 failed / 4095 passed / 4 skipped; applied state (with
  this chunk's 2 new test files, +18 tests) is 4118 collected / 1 failed /
  4113 passed / 4 skipped. Both FAILED sets are exactly
  `{test_youtube_oauth_diagnostics_reports_missing_config_without_secret_
  values}` — unrelated to clip generation, not touched by this chunk,
  `diff`-confirmed identical.
- Every pre-existing clip-generation/model-routing test file passed
  unmodified against the refactored code: test_c13_clip_model_routing.py,
  test_c25a_fix7_seedance_payload.py, test_per_card_parallel_clips_executor.py,
  test_per_card_parallel_redraws_executor.py, test_scene_model_routing.py,
  test_c17_draft_pass_and_finalize.py, test_c23_camera_presets.py,
  test_motion_gate_fail_closed_clip_and_render.py, test_t5b_clip_failure_
  marker.py, test_model_registry.py, test_dialogue_guard_laws.py,
  test_c14_model_override_and_render_style.py — 125 passed, 0 failed.

**Environment scaffolding needed to get a clean baseline (worktree-local,
NOT committed):** `storyengine/backend/venv` symlinked from the main
checkout's `backend/venv` (Python 3.11 venv with deps already installed —
building a fresh one is slow and this worktree's fresh checkout has none);
`remotion-video/public` and `remotion-video/node_modules` symlinked from the
main checkout's `remotion-video/` (both entirely gitignored — without them,
28 of the reverted baseline's tests in test_custom_film_remotion.py fail on
missing `public/motion-audio/*.wav` fixtures and a missing pinned Remotion
CLI; this matches the same "29 pre-existing failures are fresh-worktree
environment artifacts" finding D12-1/D12-2 already recorded in
tasks/loop-checklist.md). These three symlinks are untracked and must NOT be
committed — they're local scaffolding for running tests in an isolated
worktree, not part of the change.

**NOT verified (out of this chunk's $0/build-only scope):**
- No live provider call was made against Kie's real API for any of grok/
  seedance/veo — the golden tests' fake image client only proves the
  ARGUMENT SHAPE handed to `shared/clients/image_client.py`'s real method
  signatures (`generate_video`/`generate_video_seedance`/`generate_video_veo`,
  read directly from that file to build the fakes) matches what those
  methods actually declare; it does not prove Kie accepts that payload today.
- No frontend/UI touched or walked (this chunk is backend-only, no
  user-visible surface changed).
- Not deployed; not run on the VPS; not folded to main.
- Custom Film's hardcoded `gpt-image-2` path
  (`storyengine/backend/custom_film_scene_storyboards.py`) was found during
  the dialect-surface sweep and is explicitly OUT OF SCOPE per the sweep
  ruling (dormant subsystem) — noted, not touched, not tested.

---

## D12-3: board rhythm report (skills/video-pipeline/storyboard/coverage.py + storyengine/backend/scripts/coverage_to_app.py)

- **What was built:** `build_rhythm_report(moments)` — a pure, no-printing, no-mutation function
  returning `{shot_type_counts, longest_size_run, longest_lens_run, longest_purpose_run,
  archetype_diversity, transition_mix}` — plus three warn-only checks in the existing check_*
  family style (`check_shot_size_rhythm` >2 consecutive identical `shot_type` on non-INSERT shots,
  `check_lens_rhythm` >3 consecutive identical `lens_mm`, `check_purpose_monotony` >3 consecutive
  identical `purpose_kind`), wired into `run_coverage`'s post-parse block right after
  `check_shot_dp_valid`. Surface: `coverage_to_app.py`'s sheet-preview path
  (`generate_storyboard_sheet_for_scene`) gained a pure helper `_rhythm_notes_for_scene(scene,
  moments)` (factored out for DB-free unit testing) that turns the report into 0-3 short
  human-readable lines, additively attached as `"rhythm_notes"` on the function's return dict ONLY
  when non-empty — `routes/pipeline.py:1671-1673` reads only `.get("status")`/`.get("message")`/
  `.get("error")` off that dict (confirmed by reading the call site), so the new key is inert
  today, never forwarded to the frontend, purely additive.
- **Stash-proof used:** patch-file, never `git stash` — `git diff` on the two touched files saved
  to a scratchpad patch, `git apply -R` to revert in place (the two new test files moved aside for
  the reverted run so they don't ImportError-fail collection), full backend suite run, `git apply`
  to reforward, test files moved back. Reverted: 1 failed (`test_youtube_oauth_diagnostics_
  reports_missing_config_without_secret_values`, the known pre-existing failure) / 4118 passed / 4
  skipped. Applied (with this chunk's 7 new backend surface tests present): 1 failed / 4125 passed
  (4118 + 7) / 4 skipped. Sorted FAILED-test-name sets diffed byte-identical (empty diff).
- **Worktree scaffolding (temporary, deleted after use, per D12-1/D9-3b's own documented trick):**
  this worktree had no `backend/venv`, `remotion-video/node_modules`, or `remotion-video/public` of
  its own — all three were symlinked from the MAIN checkout to run the real backend venv's pytest
  against this worktree's code, then the three symlinks were removed immediately after (`git
  status --short` confirmed untracked/absent before, during, and after — never staged, never part
  of the diff).
- **Pipeline suite (own measurement, no prior-chunk baseline number to match):** every test file
  that imports `storyboard.coverage` (`test_board_laws.py`, `test_coverage.py`,
  `test_d11_1_shot_archetype.py`, `test_d11_2_shot_dp.py`, `test_d12_3_board_rhythm.py` (new, 25
  tests), `test_d6_2_repair_stamps.py`, `test_d9_1_shot_purpose.py`,
  `test_d9_6_7_transition_causality.py`, `test_prop_manifest.py`) run together: 304 passed, 0
  failed. `tests/test_ctr_12h_tracking.py` and `tests/test_sound_curation.py` fail at COLLECTION
  (`ModuleNotFoundError` on `performance_tracker`/`sound_prompt_bot`) when the bare `tests/`
  directory is run as a whole — pre-existing, unrelated to this chunk (confirmed: neither file
  imports `storyboard.coverage` or anything this chunk touched), and per this repo's own
  `tests/conftest.py`-isolation note in CLAUDE.md, per-file/per-family runs are the reliable
  signal, not the bare-directory run. `image_prompts/engine/tests/` (18 failed) and
  `render/audio_sync/tests/` (4 failed, OPENAI_API_KEY-shaped) were also run for completeness —
  both pre-existing and structurally unrelated (grepped: zero references to `storyboard` in either
  failing test file).
- **What is NOT verified:** a real end-to-end call to `generate_storyboard_sheet_for_scene` against
  a live Supabase/Kie backend actually returning a `rhythm_notes` key in its JSON response (no
  live DB/API access from this Mac — same standing gap every prior coverage_to_app.py chunk's own
  entry above names); whether a future frontend surface should actually RENDER `rhythm_notes`
  to the creator (out of scope per the brief — "frontend untouched, it simply ignores unknown
  fields" — this chunk only proves the field is additive and inert, not that anyone reads it yet);
  and `run_coverage`'s three new checks were proved via direct unit calls (same pattern every
  other check_* function in this file uses) rather than via a full paid `run_coverage()` invocation
  with a real image client, since that would cost money for zero additional signal on pure warn-log
  logic.

# Deferred verification — D14-2b (youtube_oauth_diagnostics test lock repair)

- [ ] **Live "ready: true" path never exercised.** The archaeology: `git log -S
  youtube_oauth_diagnostics` across all branches/history shows exactly one hit, the giant
  `ed1d746a` "snapshot: VPS prod working tree" commit — it added
  `tests/functional/test_youtube_oauth_diagnostics.py` (whole file, including
  `test_youtube_oauth_diagnostics_reports_missing_config_without_secret_values`) but never added a
  matching `youtube_oauth_diagnostics` function to `routes/google_auth.py`. So the helper never
  accidentally regressed — it was never built. A same-day peer chunk (`87d52dbf`, "Discovery:
  humanize the inner idea-generation error; refresh 13 stale test locks") had already triaged this
  exact test and explicitly left it failing on purpose: "the one remaining failure is the orphaned
  youtube_oauth_diagnostics test for an endpoint that has never existed — left failing deliberately
  pending a product decision." This chunk was the product decision: added
  `GET /api/auth/youtube/oauth-diagnostics` (`routes/google_auth.py`, `Depends(verify_token)`,
  same DI pattern as `get_me`) reporting `ready`/`redirect_uri`/`missing_env`/`scope_mode`/
  `requires_google_verification` without ever echoing `GOOGLE_OAUTH_CLIENT_ID`/`_SECRET` values —
  matching the test's asserted contract exactly. The test only patches env to the ALL-MISSING case
  (`ready: False`); the `ready: True` branch (both env vars actually set, no missing_env) is
  logically symmetric and trivial (same `os.getenv` reads, just non-empty) but was never called
  against a live process — no curl, no browser hit, no prod env with real
  `GOOGLE_OAUTH_CLIENT_ID`/`GOOGLE_OAUTH_CLIENT_SECRET` set was reachable from this worktree.
  Whoever wires a frontend caller to this endpoint should hit it once locally with real OAuth env
  vars present and confirm `ready: true`, `missing_env: []`, and that `repr()` of the response still
  never contains `client-`/a raw secret.
- **Stash-proof used:** before/after suite runs, not a stash — the "before" state is the
  pre-existing baseline every prior D14 chunk already measured (this exact test failing with
  `AttributeError: module 'routes.google_auth' has no attribute 'youtube_oauth_diagnostics'`), and
  re-running it clean in this worktree before editing reproduced that identically. "After" is the
  full backend suite green.
- **Full backend suite, this worktree (backend venv, `./venv/bin/python -m pytest tests/ -q`):
  4178 passed, 4 skipped, 0 failed** — this was the only known real pre-existing failure at the
  time this chunk started; suite is now fully green.
- **Worktree scaffolding (temporary, deleted after use):** this worktree had no `backend/venv`,
  `remotion-video/node_modules`, or `remotion-video/public` of its own — all three were symlinked
  from the MAIN checkout to run the real backend venv's pytest against this worktree's code, then
  removed immediately after (`git status --short` confirmed untracked/absent before, during, and
  after — never staged, never part of the diff).
- **Scope held to the brief:** only `routes/google_auth.py` was touched (new route, ~27 lines,
  zero other functions edited) plus this file. The test file itself needed no change — its
  assertions were already exactly satisfiable by a correctly-built helper. No `main.py` edit was
  needed either: `google_auth.router` was already registered (`app.include_router(google_auth.router)`,
  confirmed by grep) before this chunk, so the new route is live the moment the process restarts —
  no additional wiring step exists to forget.


## D11-3: mechanical prompt compiler (film-studio audit point 18 closure)

- **What shipped:** `compose_shot_cinematography(shot)` in
  `skills/video-pipeline/storyboard/shot_archetypes.py` — a PURE function translating a shot's
  structured `shot_archetype`/`lens_mm`/`camera_height`/`dof` (D11-1/D11-2) fields into the
  cinematography clause that now LEADS every draw prompt, at all three assembly points:
  `coverage.py::generate_coverage_frames` (first-draw), `coverage_to_app.py::_plan_sheet_prompts`
  (sheet-preview), and `coverage_to_app.py::redraw_asset_image` (redraw, with a freshly-added
  `shot_archetype`/`lens_mm`/`camera_height`/`dof`/`shot_location` SELECT — migrations 149/150/143,
  no new migration). A new rule 29 in the coverage system prompt tells the planner the compiler now
  owns camera/composition language for a tagged shot; rule 11 is reconciled to point at it. A new
  warn-only check, `check_shot_camera_prose_redundant`, flags a tagged shot whose own description
  still repeats obvious camera vocabulary.
- **Amendment mid-chunk (Ryan, cookie-cutter guard):** the clause stays craft-only (never
  mood/lighting/palette — those keep flowing from existing channels), compact (at most two
  sentences even with archetype+location+DP all present), and interpolates the shot's own
  `shot_location` (D6-2/migration 143, plain data, never LLM prose) ONLY for the ESTABLISHING
  archetype category, folded into the SAME sentence (never a third). Verified live: the identical
  archetype drawn in two scenes with different mood/environment/genre profiles produces an
  identical craft clause (except the interpolated location) and a completely different full prompt
  — see `test_cookie_cutter_defense_same_archetype_two_scenes_different_full_prompts` in the new
  pipeline test file.
- **Byte-identical legacy proof:** every shot with neither a valid archetype nor any DP field
  (every plan before D11-1/D11-2, and any untagged shot going forward) gets
  `compose_shot_cinematography` returning `""` — the exact same description string flows through
  all three assembly points unchanged. Proven directly at the REAL assembly points (not just the
  helper level) for the SAMPLE/D9_1_ERA/D9_6_7_ERA directive-era fixtures, through
  `generate_coverage_frames`, `_plan_sheet_prompts`, and a mocked `redraw_asset_image`.
- **Planted-marker proof:** a marker planted into a monkeypatched catalog entry's `image_setup`
  lands in the clause; a different marker planted into the shot's `description` never does —
  `compose_shot_cinematography` never reads `shot["description"]` at all.
- **Existing test updated (intentional behavior change, not a regression):**
  `test_d11_2_shot_dp.py::test_generate_coverage_frames_dp_text_never_reaches_the_draw_prompt` was
  renamed to `..._dp_row_syntax_never_reaches_the_draw_prompt` and its assertions flipped from
  "lens_mm/camera_height values never appear in the prompt" (true when D11-2 shipped, since DP was
  inert metadata) to "the raw `DP:` row syntax never appears, but the TRANSLATED values now do" —
  this chunk's whole point is to start consuming those fields mechanically. The `if __name__ ==
  "__main__":` block's call list was updated to match the renamed function.
- **Pipeline suite (repo-root `python3`, `skills/video-pipeline && python3 -m pytest tests/ -q
  --continue-on-collection-errors`):** reverted (main, unmodified) = 18 failed, 616 passed, 5
  errors. Applied (this worktree, new test file excluded for a fair diff) = 18 failed, 616 passed,
  5 errors. `diff` of the sorted FAILED/ERROR name sets: **empty — byte-identical.** All 18
  failures + 5 collection errors are pre-existing environment issues (missing `sound_prompt_bot`
  module, Haiku-mock assumptions in `test_music_selector.py`, an Airtable import error) unrelated
  to this chunk. Full run including the new `test_d11_3_prompt_compiler.py` (33 tests): 649 passed.
- **Full backend suite (backend venv, `./venv/bin/python -m pytest tests/ -q
  --continue-on-collection-errors`):** reverted (main) = 4178 passed, 4 skipped, 0 failed. Applied
  (this worktree, new assembly test file excluded for a fair diff) = 4178 passed, 4 skipped, 0
  failed. Sorted FAILED/ERROR sets both empty — **byte-identical.** Full run including the new
  `test_d11_3_prompt_compiler_assembly.py` (7 tests): 4185 passed, 4 skipped, 0 failed.
- **Worktree scaffolding (temporary, deleted after use):** `backend/venv`, `remotion-video/
  node_modules`, and `remotion-video/public` were symlinked from the MAIN checkout to run the real
  backend venv's pytest and the pipeline's node/remotion-adjacent imports against this worktree's
  code, then removed immediately after (`git status --short` confirmed absent/untracked before,
  during, and after the redraw's SELECT/`_setup_id` regression check — never staged, never part of
  the diff).
- **v1 limitations, stated plainly:** (1) no fuzzy deduplication — a planner shot that disobeys
  rule 29 and writes camera prose anyway on a tagged shot gets that fact stated twice (once by the
  compiler, once by its own sentence); `check_shot_camera_prose_redundant` only flags a small,
  deliberately incomplete starter vocabulary (a lens-mm pattern, "close-up", "wide shot"), warn-only.
  (2) location interpolation only fires for the ESTABLISHING archetype category — a coverage/detail/
  angle/composition/specialty shot never interpolates a location even when one is known, by design
  (a location name reads as noise on a tight face shot). (3) a HANDFUL of the 45 catalog entries
  (predating this chunk, from D11-1) embed an archetype-intrinsic optical trait in their own
  `image_setup` text where the treatment defines the shot itself (silhouette's required backlight,
  hero_shot's dramatic light, texture_detail's raking light) — this is catalog content, not
  something this compiler invents, and reproducing it verbatim is the whole point.
# Deferred verification — G8 (engine-side per-machine research loop)

- [ ] **The real 5-ship paid run has never re-executed against this fix.** Live subject: video
  `d05efae3-46f8-4ee3-b690-849c3ca31fbc` (a static_docu KGV-class build, capped, roster = 41 HMS
  King George V, 53 HMS Prince of Wales, and 3 more) — this is the exact video the bug report was
  filed against, still parked at `idea_logged` with no per-machine research. Recipe to close this
  out for real: `se db "SELECT status, max_spend, total_cost, render_mode FROM videos WHERE id=
  'd05efae3-46f8-4ee3-b690-849c3ca31fbc'"` to confirm current state, then trigger the SAME autobuild
  chain that dead-ended it in prod (chat "keep building" / the build verb) and watch task-status via
  `se logs backend` or the SSE stream for a `"Researching machine N/5: <ship>"` sequence instead of
  a dead task. Expect either `ready_for_scripting` (all 5 pass) or a `needs_review` park message
  naming whichever ships fail referee review — never a bare "Unit research-hold failed" dead end
  again. Confirm in `se db "SELECT research_payload->'unit_research_hold_validation' FROM videos
  WHERE id=...'"` that `passed` flips true machine-by-machine. **Cost cap for this task forbade any
  paid Anthropic call**, so this is unverified against the real model, the real referee, and the
  real per-video budget ledger (see next point) — only against fakes.
- **The per-machine budget-cap re-check is real (reuses `SELECT max_spend, total_cost FROM videos`,
  the same fields/pattern as the rest of make_autobuild_step), but per-machine research spend is
  NOT recorded to `videos.total_cost` anywhere in `_run_unit_research_hold`/`run_one_machine_research`
  today (confirmed by grep: zero `record_ledger_entry` calls in that whole code path, unlike
  script/storyboard/image/clip/thumbnail generation, which all call it) — a PRE-EXISTING gap, not
  introduced by this chunk (the untargeted bulk-hold path this replaces had the identical gap; so
  does `run_roster_orchestrator`, which tracks its own separate `est_spend_usd` counter instead of
  `total_cost` too). Practical effect: the cap re-check between machines will only ever fire if
  SOME OTHER paid stage in the same build (voice, images, etc.) already pushed `total_cost` over the
  cap before or during the roster loop — it will not by itself stop a runaway multi-machine research
  pass whose own cost is what breaches the cap. Fixing that properly means wiring
  `record_ledger_entry` into the per-machine research path with a real per-call cost estimate — out
  of scope for this chunk (it's a metering gap in a different, pre-existing function, not the
  autobuild wiring this chunk was asked to fix) but worth its own follow-up chunk.
- **Referee continue-vs-abort choice tested only against fakes, not a real referee's actual failure
  modes.** The loop continues past a `needs_review` machine to attempt the rest of the roster
  (mirrors `run_roster_orchestrator`'s own design one level down, minus its 3-in-a-row circuit
  breaker — see the test file's own docstring for the full rationale). Whether a REAL referee ever
  produces a systemic failure mode (e.g. every machine fails because the shared source-package
  gatherer itself is broken) that would burn through an entire large roster's worth of paid calls
  before the (currently ledger-blind, see above) cap catches it, is unverified — the fakes can only
  prove the CONTROL FLOW continues, not real-world failure correlation across machines.
- **Full backend suite, this worktree (backend venv, `./venv/bin/python -m pytest tests/ -q`):
  28 failed / 4150 passed / 4 skipped before this chunk's changes, 28 failed / 4156 passed (4150 +
  6 new) / 4 skipped after — sorted FAILED-test-name sets diffed byte-identical (empty diff). All 28
  are `tests/functional/test_custom_film_remotion.py` failing on "Custom Film Remotion local font
  assets are missing" — this worktree has no `remotion-video/public`/`node_modules` symlinked in
  from the main checkout (a prior chunk in this same worktree, D14-2b above, documented deleting
  those exact symlinks after its own run), matching this chunk's brief's own named pre-existing gap
  ("custom_film remotion in worktree venvs"). No oauth-diagnostics failures were present in either
  run (D14-2b, above, already fixed that one in this worktree's history).
- **Swap-proof used (never git stash, per this chunk's own hard rule):** `cp
  storyengine/backend/actions.py /tmp/...`, `git show HEAD:storyengine/backend/actions.py >
  /tmp/...-original.py`, swapped the ORIGINAL (pre-fix) file in via `cp`, reran the 6 new tests: 4
  failed (`test_all_machines_pass_in_order_and_status_advances`,
  `test_progress_messages_sequence_names_each_machine`,
  `test_machine_2_failure_does_not_abort_remaining_roster`,
  `test_budget_cap_reached_after_machine_one_stops_before_machine_two` — every test that exercises
  the NEW loop) / 2 passed (the two "not this loop's job, byte-identical fallback" guard tests,
  which are SUPPOSED to pass unchanged against the old code too, since they assert the pre-existing
  behavior). Restored the fixed file via `cp` from the saved copy; all 6 passed again; `git status`
  showed only the intended single-file diff at every point, never a stash.
- **Scope held to the brief:** only `storyengine/backend/actions.py` was touched (one new nested
  function, `_run_static_docu_roster_research`, plus the ~15-line call-site change in
  `make_autobuild_step`'s static_docu branch) and one new test file,
  `storyengine/backend/tests/functional/test_g8_roster_research_loop.py`. `pipeline_executor.py`
  was read extensively but never edited — `run_one_machine_research`/`_run_unit_research_hold`/the
  hallucination-safety gate are all reused exactly as they already exist; the bulk gate is never
  bypassed, only walked around one verified machine at a time, same as a human clicking through
  `/machine-research-one/{video_id}` would do by hand.

**G8b update (independent verification against dee6b6c8 caught a real gap, fixed same worktree):**
a retried/resumed build unconditionally re-called `ex.run_research` — a full paid roster-discovery
pass that wholesale-overwrites `research_payload`, risking a differently-shaped fresh roster and
re-researching already-PASSED machines with no bound. Fixed: the static_docu branch now skips
`run_research` entirely once the persisted payload already shows a passed roster gate, going
straight to the per-machine loop; a new `research_payload.roster_loop_attempts` field bounds
auto-retry to 2 failed rounds per machine before parking it as "needs manual one-machine research".
New test `test_retry_only_re_researches_the_failed_machine_and_respects_attempt_bound` (3
consecutive `make_autobuild_step` calls against a shared in-memory fake DB) proves both properties
and fails against dee6b6c8. Full suite after this fix: 28 failed (same pre-existing set) / 4157
passed (+1) / 4 skipped. The ledger-metering gap and untested real paid run noted above still
stand unchanged.
# Deferred verification — G9 (chat approval dead-end: compound replies to a pending confirm card)

- [ ] **Live UI walk never done — offline-only chunk by design (no paid API calls allowed).**
  Recipe for whoever picks this up:
  1. `scripts/se.sh devtoken` then run the frontend dev server against prod data
     (launch.json `storyengine`), open a video's Director chat, and get it to a state
     with a genuine pending `confirm_action` card showing (e.g. type "build it" on a
     fresh video and stop before tapping the card).
  2. Reply with a compound message that both asks for a real edit AND ends in consent —
     e.g. `Before running: change the title to exactly "Test Title Please Ignore" - nothing
     else. Then go ahead.` — and confirm in the UI: (a) the video's title actually changes
     (check the header/dashboard), (b) the SAME turn shows both the title confirmation and
     the build starting (no second "yes" needed), (c) `chat_conversations.state.pending_action`
     is null afterward (`se db "SELECT state FROM chat_conversations WHERE video_id = '<id>'
     ORDER BY updated_at DESC LIMIT 1"`).
  3. Repeat step 2 without the "Then go ahead." tail — confirm the SAME confirm card
     reappears with a "Still waiting on: Build the video" line, the title still updated,
     and NOTHING started running (no task-status banner, no `background_tasks` row).
  4. With a pending card open, ask a genuine unrelated question ("how much has this video
     cost so far?") — confirm it gets answered AND the card is still there/tappable
     afterward (reload the page to be sure it rehydrates from the transcript).
  Not done here because every one of these paths can trigger a real classifier call
  (`kie_unified`/`agent_brain`, tenant API keys) and, if step 2/3 is done wrong, real
  generation spend — out of scope for an offline-only, no-paid-calls chunk. All four were
  instead proven with an exact-transcript regression test (real DB rows pulled via `se db`
  for video `d05efae3-46f8-4ee3-b690-849c3ca31fbc`, replayed through `chat._handle_copilot`
  with the DB/classifier/claims layer stubbed) — see
  `storyengine/backend/tests/functional/test_g9_pending_approval_survives_compound_replies.py`.
- **Swap-proof used:** the primary reproduction test
  (`test_compound_reply_applies_title_edit_and_resumes_pending_build`) was run against the
  unmodified `HEAD` copy of `routes/chat.py` (swapped in via `git show HEAD:...` into the
  worktree, suite re-run, original restored immediately after — `git status --short` clean
  before/during/after) and **fails** there: the title write never happens and the pending
  build never resumes (falls through to the classifier's own "I need an API key" fallback,
  same dead end the real transcript hit). The three other new-behavior tests
  (`test_compound_reply_without_consent_tail_represents_the_pending_card`,
  `test_classifier_action_verb_does_not_override_a_pending_confirm`, and a manual variant of
  the reproduction test) fail the same way pre-fix (either a clean assertion failure or an
  `AttributeError` on a helper name that doesn't exist yet). The four bare-yes/no/button-tap/
  unrelated-question tests pass identically on both the original and fixed `chat.py` — proof
  those paths are untouched.
- **Full backend suite, this worktree (backend venv, `./venv/bin/python -m pytest tests/ -q`):
  28 failed, 4157 passed, 4 skipped**, both with and without this chunk's diff (`diff`'d the
  exact `FAILED` line sets from both runs — byte-identical). All 28 are pre-existing
  `tests/functional/test_custom_film_remotion.py` failures unrelated to chat.py — this
  worktree, unlike the one D14-2b ran in, has no `remotion-video/node_modules` symlinked in
  from the main checkout, so that file's real-renderer-CLI tests fail closed the same way
  before and after this change. With the diff: 7 more tests pass (the new G9 file). `git
  diff --stat` confirms only `storyengine/backend/routes/chat.py` changed (177 insertions,
  0 deletions) plus the new test file — `actions.py`/`pipeline_executor.py` untouched, per
  the chunk brief's file-ownership boundary with the concurrent actions.py/pipeline_executor.py
  worker.

# Deferred verification — G13 (ship-aware gather quality: KGV battleship rosters)

- [ ] **Real paid re-run of video d05efae3 never done — offline-only chunk by design (no
  Tavily/Anthropic spend allowed).** All three ranked fixes plus the bonus mislabel fix are
  proven with unit/fixture tests only (real excerpt/URL shapes pulled read-only via
  `scripts/se.sh db` from the actual failed packages, but no live Tavily/Anthropic call was
  made in this chunk). Recipe for whoever runs the real re-verification:
  1. Confirm the deploy landed: `se db "SELECT id FROM videos WHERE id =
     'd05efae3-46f8-4ee3-b690-849c3ca31fbc'"` then check `se logs backend` for a clean
     restart after `se deploy`.
  2. Clear the 5 KGV machines' cached raw source packages so gather actually re-runs instead
     of serving the stale cached (aircraft-templated, off-topic-tier) packages — the cache
     check in `_gather_verified_machine_source_package` returns early whenever the cached
     package already has zero quality errors, and 3 of the 5 (Howe, Prince of Wales, King
     George V) currently DO read as `passed: true` at the package level despite being
     referee-rejected downstream, so they will NOT auto-refresh on their own:
     `se db --write "UPDATE videos SET research_payload = research_payload::jsonb #-
     '{machine_raw_source_packages}' WHERE id = 'd05efae3-46f8-4ee3-b690-849c3ca31fbc'"`
     (or scope to the 5 keys individually with `#-` if a wider reset is undesirable).
  3. Trigger one-machine research for each of the 5 (`/machine-research-one` chat command,
     or the roster-repair dashboard's per-machine "research" action) — this is the paid leg:
     8-12 Tavily calls per machine now (naval queries + 3 grouped steering calls + at most 1
     reworded retry, bounded by `_MAX_VERIFIED_SOURCE_TAVILY_CALLS_PER_MACHINE = 15`), plus
     one Anthropic card-write call per machine once the package gate passes.
  4. Expected outcome per machine: `search_queries` in the saved
     `machine_raw_source_packages[<key>]` contain naval vocabulary ("class battleship
     displacement armament beam", "naval-history.net", "uboat.net",
     "discovery.nationalarchives.gov.uk") and zero "USAF"/"wingspan"/"National Museum of the
     United States Air Force" strings. `machine_research_cards.validation.passed` should be
     `true` for all 5, or if still `false`, the warnings should no longer include a Tier 1-2
     source whose only candidate excerpt is off-topic (spot-check by pulling the cited
     `evidence_segments[].source_excerpt_id` back against `candidate_excerpts` and reading
     the excerpt text).
  5. **G8b interaction:** if step 3 is instead driven by re-running the full autobuild loop
     (rather than the one-machine command directly), the G8b round guard
     (`research_payload.roster_loop_attempts`, `actions.py` `_MAX_AUTO_ATTEMPTS = 2`) means a
     machine already recorded as failed once on this video gets exactly ONE more automatic
     retry attempt before being parked as "needs manual one-machine research" — check
     `roster_loop_attempts` in `research_payload` first (`se db "SELECT research_payload::jsonb
     -> 'roster_loop_attempts' FROM videos WHERE id = 'd05efae3-46f8-4ee3-b690-849c3ca31fbc'"`)
     so a machine already at count 2 doesn't silently get skipped by the loop instead of
     re-researched — use the direct one-machine command (step 3) to bypass that bound
     entirely if needed.
  Not done here because every one of these steps is real Tavily + Anthropic spend against a
  production video, and the task brief's cost cap for this chunk was zero paid calls,
  offline/mocked-HTTP tests only.
- **Swap-proof used (file-copy, no git stash per the task's explicit prohibition):**
  `git show HEAD:storyengine/backend/pipeline_executor.py` copied to the scratchpad and
  diffed against the working copy (confirms every change is additive on top of the merge
  base, nothing silently reverted) — the working copy differs from HEAD as expected and the
  on-disk file matches the diffed copy (no accidental clobber). `git status --short` shows
  only the two owned files (`pipeline_executor.py`, `tests/test_machine_documentary_hold.py`)
  touched.
- **Full backend suite, this worktree (backend venv, `./venv/bin/python -m pytest tests/ -q`):
  28 failed, 4180 passed, 4 skipped** (before this chunk: 28 failed, 4171 passed, 4 skipped —
  net +9 new/updated tests, zero regressions). The exact sorted `FAILED` line sets from
  before and after this chunk's diff are byte-identical (`diff` on the two sorted lists
  produced no output) — all 28 are pre-existing `tests/functional/test_custom_film_remotion.py`
  failures (this worktree has no `remotion-video/node_modules` symlinked in, unrelated to
  this chunk). `py_compile` clean on both changed files.

# Deferred verification — G14 (tier floor demoted to advisory; amends the G13 KGV retry recipe above)

- **Ryan's ruling, decisions.md 2026-07-31:** the research referee's Tier 1-2 source
  requirement drops from HARD BLOCK to advisory note. Wikipedia-grade (Tier 3-4) sources
  may carry a card. Card writing proceeds regardless of tier; the anti-hallucination
  grounding core (excerpt-verbatim-in-fetched-text matching, url/locator matching, capture
  method, machine-identity checks) is untouched and still hard-blocks.
- **Amendment to the G13 KGV live retry recipe (item 4, immediately above in this file):**
  that recipe's "Expected outcome per machine" was written when a missing/off-topic Tier 1-2
  source could still leave `machine_research_cards.validation.passed = false` even after the
  G13 excerpt-relevance fix. That is no longer the live expectation. Re-reading it against
  the current code: for all 5 KGV machines (Howe, Prince of Wales, King George V, and the
  other two in that roster), `machine_research_cards.validation.passed` should now read
  `true` even if none of the 5 ever turns up a genuinely on-topic Tier 1-2 primary/museum
  source — a missing or off-topic Tier 1-2 source now only produces an advisory-tagged
  warning (`tier_floor_advisory` and/or `caution_only_sources_advisory` in
  `validation.warnings`, both prefixed `"advisory: "`), never a blocking one. If any of the
  5 still reads `passed: false` after a real re-run, the warnings list should contain ONLY
  non-tier-floor entries (missing/untraceable Anton slot coverage, excerpt-not-found grounding
  failures, unsupported capture method, etc.) — a warning naming only a Tier 1-2/caution gap
  is now a bug, not an expected pass condition.
- **G8b attempt-bound note (unchanged by G14, restated since the KGV recipe references it):**
  the `research_payload.roster_loop_attempts` / `actions.py` `_MAX_AUTO_ATTEMPTS = 2` round
  guard from G8b still applies exactly as documented in the G13 entry above — a machine
  already recorded as failed once on video `d05efae3-46f8-4ee3-b690-849c3ca31fbc` still gets
  only ONE more automatic retry via the autobuild loop before parking as "needs manual
  one-machine research." G14 does not touch this bound; it only changes whether a tier-only
  gap counts as a "failed" attempt in the first place — since tier gaps no longer block,
  fewer machines should burn an attempt on a tier-only rejection now, but a machine that
  still fails for a genuine (non-tier) reason still consumes an attempt exactly as before.
- **Not independently re-verified live** — same zero-paid-call constraint as G13; this is a
  documentation amendment to the existing deferred recipe, not a new paid re-run. Whoever
  next runs the real KGV re-verification should read this note alongside the G13 recipe
  above, not the G13 recipe alone (its step-4 expected outcome is superseded by the
  paragraph above).
- **G14 own verification (offline, this chunk):** file-copy swap-proof (never git stash) —
  `pipeline_executor.py` reverted to `git show HEAD:...` (pre-G14, i.e. the merged G13 tip)
  while the 5 new/updated G14 tests stayed in place; 4 of 5 fail against the pre-change code
  (the 5th, a "non-tier warnings still block" regression guard, correctly passes on both,
  since it asserts behavior G14 did not change) — restored, all 5 pass. Full suite
  (`./venv/bin/python -m pytest tests/ -q`) run against the full pre-G14 trio (code + both
  test files) and again against the full post-G14 trio: sorted `FAILED` line sets are
  byte-identical (28 pre-existing `test_custom_film_remotion.py` failures, same env gap as
  G13 — missing `remotion-video/node_modules` font assets in this worktree, unrelated to
  research cards). 4185 passed / 28 failed / 4 skipped post-G14 (4180 passed pre-G14, +5 new
  tests, zero regressions). `py_compile` clean on all three changed files.

# Deferred verification — G16 (pennant-tolerant identity match + writer prompt carries content rules)

- **What shipped:** (1) `_locked_machine_identity_codes()` — a locked machine's leading
  standalone digit/pennant token ("53 HMS Prince of Wales") is now optional when matching a
  card's `unit` field or a content field's specificity check against the locked name; a
  sibling with its own different name/pennant ("53 HMS King George V") is never pulled in.
  Applied at all four sites that compare a card/content string against the locked machine
  name: the `"card unit does not match locked machine"` emitter
  (`_research_card_contract_warnings`), and the "must be specific to the locked machine"
  first-4-tokens/last-token check inside `_paragraph_worth_warnings`,
  `_visual_identity_warnings`, and `_timeframe_warnings`. (2) The two content-shape warning
  strings (`visual_identity must include concrete visible machine features` and
  `why_this_unit_deserves_a_paragraph must name a concrete engineering decision, problem,
  tradeoff, or consequence`) are now module-level constants (`_VISUAL_IDENTITY_CONTENT_RULE`,
  `_WHY_PARAGRAPH_CONTENT_RULE`) built from the SAME word lists the validator regexes match
  against (`_VISUAL_IDENTITY_FEATURE_WORDS`, `_ENGINEERING_DECISION_WORDS`); the validators
  now emit these constants instead of retyped literals, and `_run_unit_research_hold`'s
  FIRST-pass writer prompt embeds a new "CONTENT-SHAPE RULES" block
  (`_visual_identity_writer_rule_line()` / `_why_paragraph_writer_rule_line()`) that states
  both rules verbatim with example vocabulary pulled from those same word lists — a first
  draft now sees the rules that used to arrive only via a paid repair round's raw warning text.
- **Real evidence this fixes:** video `d05efae3-46f8-4ee3-b690-849c3ca31fbc`'s live 5-ship
  run, card roster_index 2 (machine `"53 HMS Prince of Wales"`) blocked on `"card unit does
  not match locked machine 53 HMS Prince of Wales"` because the model wrote the unit as `"HMS
  Prince of Wales"` (no pennant) — same shape for the roster's other pennant-prefixed names
  (`"41 HMS King George V"`, `"17 Duke of York"`, `"79 Anson"`, `"32 HMS Howe"`). Card
  roster_index 1 blocked on the two content-shape warnings above.
- **Live proof deferred — cost cap for this chunk was zero paid calls, offline/fixture tests
  only.** `d05efae3-46f8-4ee3-b690-849c3ca31fbc`'s own machines are at the G8b
  `roster_loop_attempts` bound (see the G13 entry above), so the real live proof for G16 is a
  **FRESH 5-ship video**, not a retry of d05efae3. Recipe for whoever runs it next:
  1. Create a new video via chat with a title that reads as an "All ..." roster prompt (the
     `_title_needs_complete_roster` / `_title_is_broad_machine_roster` gate needs `every` /
     `all` / `ever built` language plus a machine-roster noun to auto-select a 5-item
     ship-with-pennant-style roster the way tonight's run did — e.g. something in the shape
     of "All King George V-Class Battleships Ever Built" or similar naval roster framing).
  2. Set a **$5 cost cap** on the video (this is real Tavily + Anthropic spend — confirm the
     quote in the UI/chat before letting it run, per the money rule).
  3. Run the build end to end (`mcp__storyengine__build` or the dashboard "Build" action) and
     let the DVsU one-machine research-hold loop process all 5 roster entries.
  4. **Expected outcome:** the video reaches `ready_for_scripting` with **5/5 research cards
     passing** (`machine_research_cards.validation.passed = true` for all 5 roster rows,
     `unit_research_hold_validation.passed = true` overall) — specifically, zero cards should
     block on `"card unit does not match locked machine"` for a name that differs from the
     locked roster entry only by a missing leading pennant/hull number, and zero cards should
     block on `"visual_identity must include concrete visible machine features"` or
     `"why_this_unit_deserves_a_paragraph must name a concrete engineering decision, problem,
     tradeoff, or consequence"` on the FIRST research pass (a first-pass failure on either of
     those two specific rules, after this fix, is a regression worth flagging even if a later
     repair round recovers it).
  5. If any card still fails, pull its `card.unit` and the roster's locked display name
     (`se db "SELECT machine_name, card->>'unit', validation FROM machine_research_cards
     WHERE tenant_id = ... AND video_id = '<new-video-id>' ORDER BY roster_index"`) and check
     whether the mismatch is a genuinely different name (correct rejection) or a new
     name-formatting drift this fix's pennant tolerance doesn't cover (e.g. a trailing
     hull-number suffix instead of a leading one — out of scope for this chunk, worth its own
     follow-up if seen).
- **G16 own verification (offline, this chunk):** file-copy swap-proof (never git stash) —
  `pipeline_executor.py` copied aside post-fix, then overwritten with `git show
  HEAD:storyengine/backend/pipeline_executor.py` (pre-G16, the merged G14 tip) while the new
  `tests/test_g16_pennant_identity_and_writer_rules.py` (10 tests) stayed in place: 7 of 10
  fail against the pre-change code, including the two tests the brief specifically named —
  `test_card_unit_matches_locked_machine_despite_missing_pennant_prefix` (the pennant-tolerance
  emitter test) and `test_writer_prompt_rendering_teaches_both_content_rules_upfront` (the
  rendered-prompt test). The 3 that pass on both sides are intentional non-regression checks
  (exact-match-still-passes, sibling-still-rejected, and the field-specificity checks — the
  last of which also passes pre-fix because the pre-existing last-token fallback already
  covered these particular field-check cases; `_locked_machine_identity_codes` is unit-tested
  directly to isolate the new code path from that overlap). Restored post-fix, all 10 pass.
  Full suite (`./venv/bin/python -m pytest tests/ -q`) run against the full pre-G16 pair (code
  reverted, test file moved out) and again against the full post-G16 pair: sorted `FAILED`
  line sets are byte-identical (28 pre-existing `test_custom_film_remotion.py` failures, same
  env gap as G13/G14 — missing `remotion-video/node_modules` in this worktree, unrelated).
  4195 passed / 28 failed / 4 skipped post-G16 (4185 passed pre-G16, +10 new tests, zero
  regressions). `py_compile` clean on both changed files.

- **G17 (2026-08-01), the script-stage cousin — LIVE CHECK NEEDED:** fixed
  `_validate_static_unit_paragraph`'s "missing locked machine designation" check (glued
  4-token blob substring, no pennant tolerance, no last-token fallback — the exact G16 disease
  one level downstream, on the final SCRIPT paragraph rather than the research card). All
  offline tests pass against real roster fixtures pulled from video d2e37cd6-521a-43aa-a14d-
  ce096a783c1e ("Every British Aircraft Carrier Class Ever Built") via `se db` — including the
  sharpest real edge case, "HMS Ark Royal (91) Ark Royal (1937)" (two Ark Royals in this
  roster's own history, so the NAME half carries its own trailing disambiguating bracket, not
  just the designation half). **The one thing that cannot be verified offline: does the LIVE
  model-written paragraph for each of the 23 real machines actually pass this gate on the
  first or second round, with real Anthropic output rather than hand-written test fixtures?**
  Recipe for whoever runs it next:
  1. On this same video (d2e37cd6), run script card 1 (`run_machine_script_preview` /
     `mcp__storyengine__script` preview, or the Script/Voice tab's "Run Script" button) for
     **HMS Argus** specifically — the simplest single-ship entry and the one named in the
     original bug report.
  2. **Expected outcome:** the preview reaches `completed` with the paragraph passing
     (`preview.passed = true`), and zero warnings starting with `"missing locked machine
     designation"` — a first-pass failure on that exact message is a regression worth
     flagging even if a later repair round recovers it.
  3. Repeat for at least one CLASS-style entry (e.g. "Courageous, Glorious Courageous class"
     or "CVA-01 predecessors Audacious class / Malta class") and, if time allows, the Ark
     Royal (1937) entry specifically (roster_index 6) — the one this chunk's fallback fix was
     built to unblock.
  4. If any of these still fails on `"missing locked machine designation"`, pull the exact
     model-written paragraph and the roster's locked display name (`se db "SELECT machine_key,
     machine_name FROM machine_research_cards WHERE video_id = 'd2e37cd6-521a-43aa-a14d-
     ce096a783c1e' ORDER BY roster_index"`) and check whether the paragraph genuinely never
     names the machine at all (correct rejection) or names it in a shape this fix's tolerance
     doesn't cover (e.g. neither the pennant-tolerant code nor the last-name-word fallback
     matches — out of scope for this chunk, worth its own follow-up if seen).
- **G17 own verification (offline, this chunk):** file-copy swap-proof (never git stash) —
  `pipeline_executor.py` copied aside post-fix, then overwritten with `git show
  HEAD:storyengine/backend/pipeline_executor.py` (pre-G17, the merged G16 tip) while the new
  `tests/test_g17_script_paragraph_identity_tolerance.py` (8 tests) was moved out for the
  baseline run, then restored: 5 of 8 fail against the pre-change code (the natural-paragraph-
  passes tests, the Ark Royal edge case, the fallback-term unit test, the shared-constant
  content check, and the end-to-end writer-prompt test); the 3 that pass on both sides are
  intentional non-regression checks (sibling-still-rejected, the identity-codes-widening
  superset check, and the exact-glued-code-still-passes regression). Full suite
  (`./venv/bin/python -m pytest tests/ -q`) run against the full pre-G17 pair (code reverted,
  new test file moved out) and again against the full post-G17 pair: sorted `FAILED` line sets
  are byte-identical (28 pre-existing `test_custom_film_remotion.py` failures, same env gap as
  G13/G14/G16 — missing Remotion font/asset files in this worktree, unrelated). 4203 passed /
  28 failed / 4 skipped post-G17 (4195 passed pre-G17, +8 new tests, zero regressions).
  `py_compile` clean.

