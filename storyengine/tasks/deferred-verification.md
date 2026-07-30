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
