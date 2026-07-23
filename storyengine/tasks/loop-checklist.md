# Loop checklist — Custom Film composer (Milestone 2)

## Definition of Complete
1. A creator can ask for a Custom Film naturally in chat and receive an ordered section-by-section production plan without seeing a fifth public preset card, an advanced-knob form, provider jargon, or internal profile names.
2. Every section is a validated immutable contract over the Milestone 1 production dimensions. Each knob value is allowlisted, records its public-profile provenance, obeys a compatibility matrix, and is applied by the runtime at section scope rather than collapsing back to one video-wide `render_mode`, script profile, visual profile, language, dubbing, density, camera, or quality-law choice.
3. Before generation, StoryEngine explains the assembled film in plain English: what each section will feel like, why it was chosen, the expected still/clip/voice shape, the user-owned providers involved, and one section-aware BYOK estimate. Editing the plan invalidates its approval and quote; only explicit approval of the exact current plan can start generation.
4. Custom Film remains BYOK and fail-closed. Planner/runtime/provider resolution never reads StoryEngine-funded credentials, missing tenant keys produce a useful pre-spend stop, and the existing drain, generation-claim, budget-cap, quote, confirmation, and retry/idempotency laws still guard every start.
5. A genuinely novel approved composition can become a reusable tenant-owned profile only through a separate explicit save confirmation. The saved artifact is a topic-free, versioned recipe of section roles/proportions/knobs, never the source video's subject matter; canonical signatures prevent copies of a public preset or an existing saved recipe from being presented as novel.
6. A mixed plan can produce one coherent ordered film across static photo, animated investigative, bilingual character, and simple-language sections. Shared transitions, audio continuity, captions, aspect/resolution, and final assembly stay deterministic; legacy and single-profile videos remain byte-compatible where their paths are not involved.
7. Focused backend/frontend tests, migration/RLS checks, negative and stash-proof evidence where useful, full relevant regressions/builds, a no-provider synthetic mixed-film render, and a no-spend first-user browser walkthrough pass. The verified implementation is published in a separate draft PR; paid mixed-style proof, live migration, production deployment, Drive writes, uploads, and merge remain explicit Ryan approval gates.

## Milestone boundary
- Milestone 1 is complete at `836e8c25` and remains sealed in draft PR #459.
- Milestone 2 lives on `agent/storyengine-custom-film`, based on the Milestone 1 tip because it consumes the production-style contract. Its eventual PR targets `main` only after #459 is merged or is otherwise rebased onto the merged equivalent.
- This pass prepares architecture and acceptance only. It does not implement Custom Film, push the branch, open a PR, call a provider, migrate a database, deploy, write to Drive, upload, or merge.

## Clarifications and architecture decisions
- **DEC-M2-CHAT-HIDDEN — resolved 2026-07-23**
  - Decision: Custom Film is a chat capability, not a fifth card in `ProductionStyleSelector`. The public creation selector remains exactly four profiles.
  - Why: the composer should translate intent into safe structure while keeping advanced controls private.
- **DEC-M2-COMPONENT-BOUNDARY — resolved 2026-07-23**
  - Decision: the planner may compose only the named dimensions and values supplied by the four public profile snapshots, plus explicitly implemented compatibility rules. It cannot invent provider IDs, arbitrary knobs, or a new generation path.
  - Why: Custom Film is a control-plane composer over proven components, not an unbounded provider prompt.
- **DEC-M2-SECTION — resolved 2026-07-23**
  - Decision: a section is a stable ordered production unit with a topic-specific purpose, relative duration, knob snapshot, public-profile provenance, estimated media, and one or more eventual scene numbers. A compiler assigns scenes/assets to section IDs; scene-number heuristics are not the source of truth.
  - Why: script acts and scene counts can change during planning, so the production contract needs a durable identity independent of display numbering.
- **DEC-M2-RUNTIME — resolved 2026-07-23**
  - Decision: compile every validated section into the existing runtime adapters, then assemble their outputs through one ordered mixed-section composition contract. Do not spread `if custom_film` branches through provider callers or choose one video-wide render mode as a lossy fallback.
  - Why: Milestone 1 currently stores decisive runtime values at video scope; a planner-only change would explain a mix that the executor cannot actually honor.
- **DEC-M2-APPROVAL — resolved 2026-07-23**
  - Decision: canonicalize and hash the full instantiated plan plus quote inputs. Generation approval records that hash; any plan, model, duration, or estimate-affecting change clears approval. The generation door re-resolves the current hash, tenant keys, drain state, claim, and budget before dispatch.
  - Why: approval must bind to what will spend, not to an earlier description.
- **DEC-M2-BYOK-PLANNING — resolved 2026-07-23**
  - Decision: the creator's ordinary BYOK chat turn may perform the planning inference, as chat already does. That turn cannot launch script/media generation. The resulting plan and generation estimate always require a separate explicit approval before pipeline work begins.
  - Why: separating conversational planning from generation keeps the UX usable while preserving the spend gate.
- **DEC-M2-NOVELTY — resolved 2026-07-23**
  - Decision: derive a canonical topic-free recipe signature from ordered section roles, duration proportions, normalized knob values, and compatibility version. Ignore titles, subject matter, rationale prose, and scene numbers. Offer Save only when the signature differs from all four single-profile recipes and the tenant's active saved recipes; saving is a separate confirmation.
  - Why: a reusable profile must capture a production grammar, not accidentally preserve one video's content or create duplicates.
- **DEC-M2-PR — resolved 2026-07-23**
  - Decision: no Milestone 2 commit belongs to PR #459. Planning begins on the local separate branch; pushing and opening the Milestone 2 draft PR are final-chunk actions only.

## Architecture pass
- **Existing reusable foundation**
  - `backend/production_styles.py` owns the allowlisted dimension schema, public catalog validation, immutable video snapshots, video-level runtime translation, and script guidance.
  - `routes/chat.py` already owns chat planning, authoritative card selections, the create approval turn, persisted conversation state, and the existing plan estimate.
  - `actions.py` is the shared quote/budget/dispatch law; `generation_claims.py` and drain mode guard duplicate or unsafe starts.
  - `coverage_to_app.py` already consumes `production_style_snapshot.knobs.image_density` for visual-cue planning.
- **Load-bearing gap**
  - Milestone 1 resolves `render_mode`, `script_profile`, `style_preset_id`, and `dialogue_audio` once in `routes/videos.py` and stores them on `videos`.
  - Static/coverage stage routing, dialogue behavior, renderer selection, and finish UX still branch mainly on those video-wide fields. Only copying a mixed plan into JSON would not change the actual film.
  - The current pre-creation estimate is video-level and approximate; it is not an executable per-section bill of materials.
  - `style_presets` describes visual look and is not a tenant-owned production-recipe store. Custom Film needs a distinct tenant-isolated, versioned recipe contract.
- **Target control flow**
  1. Chat recognizes Custom Film intent and gathers only missing creative constraints.
  2. A planner receives the current public profile snapshots plus a compatibility manifest and returns schema-constrained section intentions.
  3. A deterministic validator/compiler rejects unknown values, incompatible combinations, unsupported transitions, missing key capabilities, and topic leakage in reusable-recipe fields.
  4. The compiler persists the instantiated plan and section rows, calculates a section-aware media/provider bill of materials, and renders the plain-English explanation.
  5. Explicit approval binds to the canonical plan-and-quote hash.
  6. Existing stage runners execute against section IDs and adapters; a mixed compositor joins ordered section outputs into one video.
  7. After approval, the novelty checker may offer a separate Save Profile confirmation for a topic-free recipe.

## Assumptions
- PR #459's schema and runtime contract are the dependency base; if review changes them, M2-0 is rerun before implementation.
- Custom Film does not expose a public fifth preset and does not modify the four public catalog rows.
- The four profiles define the initial capability vocabulary. A new provider/mode is a separate product decision, not something the planner may infer.
- Planner prose is untrusted. Only the deterministic compiler's allowlisted output reaches persistence, estimation, or runtime.
- A saved recipe is tenant-private by default. Sharing or publishing community recipes is out of scope.
- Saving and generating are independent confirmations: a creator can generate without saving or save a recipe without triggering generation.
- No paid/live proof is required to complete the separate no-spend implementation PR; those checks remain honestly deferred.

## Chunks
- [x] M2-0 SWEEP + ARCHITECTURE [D][B][U][V] Restore the Milestone 1 handoff, verify PR/worktree isolation, trace the style/chat/quote/runtime persistence seams, define the section contract, close plan-changing clarifications with explicit assumptions, and create the separate local planning branch.
      Evidence: all four governing files were read completely. PR #459 is open, draft, mergeable/CLEAN, has no reviews/comments/check rollup, and still points from `agent/storyengine-beta-ux-styles` to `main` at `836e8c25`. Local branch `agent/storyengine-custom-film` was created from that exact tip; only pre-existing ignored-by-practice directories `storyengine/backend/venv` and `storyengine/frontend/node_modules` are untracked. The protected `/Users/ryanayler/economy-fastforward` checkout remains on `feat/per-card-parallel-clips` at `642e5b1e` with its pre-existing `storyengine/HANDOFF.md`, `storyengine/.claude/`, and `storyengine/tasks/ref-dryrun-2026-07-21.txt` state untouched; stash `19be0af…` remains present. Read-only code tracing proved the video-wide runtime gap and identified the existing chat approval, quote, BYOK, claim, and density seams above. No provider call, product-code edit, remote write, migration, deployment, Drive write, upload, or merge occurred.
- [ ] M2-1 CONTRACT + PERSISTENCE [D][B][V] Add the validated section/plan schemas, capability/compatibility manifest, tenant-owned versioned reusable-recipe store, instantiated per-video section persistence, canonical signatures, approval hash fields, RLS, and legacy-safe serialization. Recheck the next migration number immediately before editing.
      Acceptance: malformed/unknown/incompatible plans fail closed; section identity survives scene replanning; tenant isolation and topic-free recipe storage are proven; untouched legacy videos serialize and execute as before.
      Risk/prohibited: high data-contract risk; no live migration, provider call, or remote write.
      Depends on: M2-0 and the merged-equivalent Milestone 1 schema.
- [ ] M2-2 PLANNER + COMPILER [B][V] Build the chat-hidden Custom Film intent path, constrained planner schema, deterministic compiler, plain-English section explanation, provenance, novelty classifier, and no-key/error behavior.
      Acceptance: fixtures produce stable plans; adversarial output cannot inject knobs/providers; a single-profile request does not masquerade as novel; no generation starts from planning.
      Risk/prohibited: planner output is untrusted; tests use fakes only and make no provider call.
      Depends on: M2-1.
- [ ] M2-3 SECTION-AWARE ESTIMATE + APPROVAL [B][U][V] Compile section media/provider counts through the shared estimator, show one BYOK plan/estimate in chat, bind approval to the current canonical hash, invalidate it on edits, and route the confirmed start through drain/claim/budget/key gates.
      Acceptance: estimate totals equal their itemized section rows; stale/double approvals cannot dispatch; missing keys and cap breaches stop before work; no advanced controls leak into the UI.
      Risk/prohibited: money/auth hot path; no paid call.
      Depends on: M2-1 and M2-2.
- [ ] M2-4 SECTION RUNTIME [B][R][V] Carry section IDs and compiled runtime values through script, coverage/static imagery, language/dubbing, voice, motion/clip, quality-law, and stage-plan seams without `custom_film` conditionals in provider callers.
      Acceptance: each stage consumes the compiled section contract; unsupported cross-mode combinations stop before spend; single-profile and legacy regression suites stay at baseline.
      Risk/prohibited: highest backend/provider blast radius; no paid provider call.
      Depends on: M2-1 and M2-3.
- [ ] M2-5 MIXED COMPOSITOR [B][R][U][V] Normalize static and animated section outputs into one ordered composition, preserving transitions, audio continuity, captions, aspect/resolution, progress, and honest finish/co-pilot status.
      Acceptance: a local fixture film mixes all four section types in order with deterministic timing and no generated media; screenshots/frame inspection prove the user-visible result.
      Risk/prohibited: high render/UX risk; synthetic local assets only.
      Depends on: M2-4.
- [ ] M2-6 REUSABLE NOVEL PROFILES [D][B][U][V] Offer and confirm saving only after canonical novelty passes; store a topic-free recipe; list/reuse/rename/archive tenant recipes through chat while keeping advanced knobs hidden.
      Acceptance: duplicates/public clones are not offered as novel; cross-tenant reads fail; reuse instantiates a fresh topic-specific plan without mutating the saved version; save never starts generation.
      Risk/prohibited: tenant data writes only in local tests; no external write.
      Depends on: M2-1, M2-2, and M2-3.
- [ ] M2-7 FINAL + SEPARATE PR [V][G] Re-grade all seven criteria from a first-user path, run focused and full relevant regressions/builds, inspect the no-provider mixed render and browser flow, update deferred recipes, commit intentionally, push only this branch, and open a separate draft PR.
      Acceptance: explicit Complete/Partial verdict with baseline comparison and exact residual risks; PR contains no Milestone 1 amendments unrelated to its M2 dependency and no paid/deploy evidence is implied.
      Risk/prohibited: remote write is limited to the separate branch/draft PR; no merge, deployment, live migration, paid run, Drive write, or upload.
      Depends on: M2-1 through M2-6 accepted.

## Previous completed mission

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
- [x] M3 CREATION UX [U][V] Add the required four-card selector, descriptions, calculated media/BYOK estimates, and no-default validation to both onboarding and main creation flows.
      Evidence: one API-backed `ProductionStyleSelector` now serves classic onboarding, the first-video modal, and the returning-user New Video modal, closing every first-party form entry rather than only the two obvious files. It renders exactly the four public catalog rows with generic label/description copy, no default, accessible radio state, duration-derived image/clip counts for animated profiles, three stills per item/no clips for Photo Documentary, and one explicit BYOK/quote warning. Every Create action remains disabled until a style is selected and every create payload sends `production_style_id`; Custom Film/Design Your Own is absent. The focused style/creation contract suite passes 21/21, TypeScript passes, and the complete Next production build passes all 34 routes. With the four implementation files hidden and the new contract test retained, the suite fails on the missing selector file and passes when restored, proving the wiring check is causal. No provider call, live migration, or deployment occurred.
- [x] M4 CO-PILOT TRUTH [B][U][V] Wire docked SSE progress, improve script/voice/image messages and counters, add the sequential stage map, and keep the selected style visible in all co-pilot modes.
      Evidence: home plans now require the same API-backed four-style pick as form creation and forward it through chat approval into `CreateVideoRequest`, while missing selections remain on the plan instead of receiving a hidden default. Both the post-create card and docked `ChatCore` fetch the current video, subscribe to the real SSE task/stage stream, keep the selected profile label/description visible, and render the actual persisted stage plan as Research → Script → Voice → Characters → Environments → Storyboards → Pictures → Sound → Clips → Thumbnail → Render, omitting stages the chosen profile does not run. Script and voice execution emit meaningful substage messages through manual and autobuild entry paths; coverage reports the real completed image count as `Scene N: drawing image X/Y…`. Chat still returns immediately after queuing the background build. Focused chat/style checks pass 71/71, the coverage suite passes 53/54 with its one unrelated pre-existing master-only parser expectation, Python and TypeScript compilation pass, and the full 34-route frontend build passes with a local verification-only API URL. No provider call, migration, deployment, or external write occurred.
- [x] M5 FINISH + DRIVE UX [U][V] Clarify animation actions, progress placement, voice-at-the-end, static-video treatment, style identity, and honest no-Drive storage messaging.
      Evidence: the Scenes/finish workspace now leads with the immutable selected-style label and description, explicitly distinguishes photo from animated output, and tells Photo Documentary creators that their stills are the intended final format with pan-and-zoom added at render and no clip-animation spend. A persistent finish-order row places sound/voice after picture review and before the final render; the deferred-voice banner remains visible without blocking picture review. Live task text and scene/board/picture/clip counts moved out of the narrow StageRail portal into a full-width progress row above the model controls. “Animate everything” remains the primary filled action while “Animate this scene” is a smaller outline secondary. One connection-aware `DriveStorageNotice` is consumed by the shared selector (therefore classic onboarding, first-video, returning-user, and home-chat creation) and the finish workspace; Settings carries the same honest warning and a direct connection target. It only appears when Drive is not connected and says StoryEngine storage is not guaranteed long-term. The focused contract passes 14/14, the new M5 check fails with the implementation hidden and passes restored, TypeScript passes, and the complete 34-route Next production build passes. No provider call, Drive write, live migration, or deployment occurred.
- [x] M6 FINAL + PR [V][G] Re-grade all seven criteria as a first-time user, run relevant full regressions/builds and a no-spend browser walkthrough, update deferred proof recipes, commit the verified result, push, and open a draft PR to `main`.
      Evidence: all seven Definition of Complete criteria were re-graded against the actual new-user, returning-user, chat-planning, co-pilot, finish, Settings, schema, and runtime surfaces. A local no-spend browser fixture rendered those real components and proved exactly four unselected public choices, required selection, calculated media estimates, BYOK and disconnected-Drive warnings, persisted style identity, the sequential live pipeline map with image counts, animated finish actions, and Photo Documentary's intended static finish. The browser review found two static-mode truth defects—an “0 of 3 animated” summary and a motion-prompt control—and the verified fix removes both; screenshots were visually reviewed and the console had no errors or warnings. The final focused production-style/chat-claim suite passes 39/39, M4's focused suite passes 71/71, the runtime suite passes 358/358, and coverage passes 53/54 with the same unrelated pre-existing master-only parser expectation. The complete backend run passes 2,602 tests with exactly the same 14 failures plus one collection error as the plan/base baseline, so this branch introduces no new regression. Standalone TypeScript and the final 34-route production build pass after the browser fix. No provider call, live migration, Drive write, deployment, or upload occurred. The isolated branch was pushed and draft PR #459 was opened to `main`: https://github.com/vibecoder10/economy-fastforward/pull/459. The dirty `feat/per-card-parallel-clips` checkout and the user's `19be0af…` stash remain untouched.

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
