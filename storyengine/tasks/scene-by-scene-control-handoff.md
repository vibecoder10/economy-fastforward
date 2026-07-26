# StoryEngine Custom Film — Scene-by-Scene Control Handoff

## Mission

Replace the current whole-director-stage approval experience with a human-driven
Scene Control mode. Ryan must be able to plan, quote, generate, inspect, revise,
and accept one scene at a time. A later scene must remain locked until Ryan
accepts the completed current scene.

This is a control-system build, not authorization to generate a film.

## Current verified production state

- Production commit: `9a918466a110346dabb5300286f5e77a2ccd843c`
- Merged PR: `https://github.com/vibecoder10/economy-fastforward/pull/516`
- `CUSTOM_FILM_DIRECTOR_V2=true`
- Migrations `135_custom_film_director_loop.sql` and
  `136_custom_film_director_production_activation.sql` are applied.
- Backend, worker, frontend, database, storage, and ARQ were healthy after the
  deployment.
- The live director can plan and quote the full text-direction stage, but it
  has not proven the complete storyboard-to-video production path.
- Live no-spend proof after deployment: zero director schedules, zero director
  call events, zero director executions, and no change to the canonical
  generation ledger.

## Money boundary

- Verified completed-spend context: `$8.57`.
- The current director card offers a `$12.88` maximum text-direction stage and
  a new exact cumulative ceiling of `$21.45`.
- `$21.45` is **not approved**. Ryan must not approve or use that whole-stage
  card for the scene-control pilot.
- The old `$8.57` ceiling is an accounting boundary, not remaining headroom.
- No provider call, generated reference, image, animation, voice, repair,
  fallback, render-provider operation, or helper asset may run without a new
  exact cumulative amount explicitly approved by Ryan.
- Deterministic local planning, validation, UI work, tests, and synthetic
  Remotion proofs may run without provider spend.

## Governing product rule

The system may know the whole-film plan, but production authority exists for
only one explicit operation on one explicit scene at a time.

No stage may automatically trigger the next stage. No accepted scene may
silently mutate. No later scene may generate while the current scene is
unaccepted.

## Required film-level locks

Before Scene 1 can reach paid media generation, Ryan must review and approve:

1. The complete story throughline and scene order.
2. The final dialogue and narration assignment for each scene.
3. One visual style and rendering grammar for the entire film.
4. Every recurring character identity, wardrobe, proportions, and immutable
   reference set.
5. Every recurring environment identity, geography, lighting rules, persistent
   props, and immutable reference set.
6. The allowed use of DvsU, Poco a Poco, and Power Doctrine techniques by
   scene, without changing the locked film identity.

These locks are film-wide inputs. A scene may select from them but may not
rewrite them.

## Scene state machine

Each scene must persist and visibly expose this fail-closed state machine:

`draft`
→ `plan_approved`
→ `storyboard_approved`
→ `imagery_approved`
→ `animation_approved`
→ `audio_approved`
→ `assembled`
→ `accepted`

Transitions require a Ryan approval bound to the exact scene revision hash.
Revising an upstream artifact invalidates every downstream approval for that
scene. Only `accepted` unlocks the next scene.

## Required scene contract

Every scene must define:

- Scene number, purpose, target duration, and story time.
- Narrative state at the opening and the exact state change by the ending.
- Characters present and their locked reference IDs.
- Environment and locked reference ID.
- Active props and continuity inherited from the prior accepted scene.
- Dialogue turns with speaker IDs, performance intent, and timing.
- Third-person exposition only where it is purposeful.
- Intentional silent-action beats.
- Shot list in synchronous order.
- For each shot: narrative function, starting frame, ending frame, character
  action, camera action, dialogue/audio ownership, transition, continuity
  inputs, and continuity outputs.
- A plain-English answer to: “How does this shot advance the film?”

A shot that does not advance story, reveal information, intensify emotion,
establish necessary geography, or complete a transition must fail validation.

## Per-scene control loop

1. Show the scene plan and shot board with no generation.
2. Ryan revises or approves the scene plan.
3. Show the exact next-operation cost and exact cumulative ceiling.
4. Generate only the explicitly approved storyboard/reference operation.
5. Ryan inspects every result; failed assets do not unlock animation.
6. Show a new exact animation cost for only the approved shot or scene.
7. Animate only the approved images with explicit beginning-to-ending action.
8. Ryan inspects motion and continuity; rejected shots return to their last
   accepted upstream state.
9. Quote and generate only the approved dialogue/voice operation.
10. Assemble the accepted scene deterministically in Remotion with layered
    media, camera motion, dialogue, ambience, effects, captions, and
    transitions.
11. Ryan watches the completed scene and either accepts it or sends it back to
    a specific upstream gate.
12. Scene acceptance unlocks only the next scene.

## Approval-card requirements

Every spend-bearing button must state:

- Scene and shot scope.
- Provider operation being authorized.
- Number of initial calls.
- Maximum repair calls.
- Exact incremental maximum.
- Prior completed cumulative spend.
- New exact cumulative ceiling.
- Whether imagery, animation, voice, or other media is included.
- What remains explicitly unapproved.

Approval must be immutable, hash-bound, transactionally reserved with the
outbox and per-video claim, durably receipted, and reconciled before releasing
the spend hold.

There must be no “approve scene” button that authorizes several hidden provider
types. Use explicit actions such as:

- `Approve Scene 1 plan — no generation`
- `Generate Scene 1 storyboard images — exact ceiling $X`
- `Animate Shot 1.3 — exact ceiling $Y`
- `Generate Scene 1 dialogue audio — exact ceiling $Z`
- `Assemble Scene 1 in Remotion — deterministic/no provider spend`
- `Accept Scene 1 and unlock Scene 2`

## Reuse before invention

Audit and extend the deployed director tables and contracts before adding new
ones:

- `custom_film_director_contracts`
- `custom_film_shots`
- `custom_film_lock_references`
- `custom_film_storyboard_reviews`
- `custom_film_picture_reviews`
- `custom_film_visual_verifications`
- `custom_film_stage_authorities`
- `custom_film_director_stage_schedules`
- `custom_film_director_call_events`
- `custom_film_director_executions`
- `generation_claims`
- `generation_ledger`

Prefer a small scene-control layer over a parallel production system. Preserve
tenant isolation, drain-mode ordering, exact claim ownership, durable outbox
recovery, canonical spend reconciliation, and stale ambiguous-call holds.

## UI requirements

Build a production cockpit that lets Ryan drive the film:

- Film-level lock panel for story, cast, environments, and style.
- Scene rail showing locked, current, accepted, and invalidated scenes.
- Current-scene shot board in synchronous order.
- Per-shot continuity, dialogue, action, and motion inspection.
- Artifact comparison and reject/regenerate controls.
- Clear deterministic-versus-paid labels.
- Exact incremental and cumulative cost displayed before every provider call.
- No autoplay, auto-advance, multi-scene run, hidden repair, or provider
  fallback.

## Mandatory one-scene acceptance proof

Do not claim the system can produce a film until one 15–30 second pilot scene
passes all gates with:

- Two locked recurring characters.
- One locked environment.
- Four to six progressive shots.
- Back-and-forth dialogue.
- One intentional silent-action beat.
- Consistent storyboard and generated imagery.
- Animation that visibly advances each shot from its start state to end state.
- No repeated narration or dialogue.
- Layered Remotion assembly with dialogue, ambience, effects, transitions, and
  verified captions.

Build and browser-test this proof first with synthetic/local assets. Stop at a
new exact paid approval card before any real provider generation. Ryan must
personally approve the amount and drive the real Scene 1 pilot.

## Implementation and deployment authority

The next session is authorized to inspect, implement, test, browser-verify, and
deploy the scene-control code and deterministic synthetic proof. It is not
authorized to call paid providers or generate real production media.

Use the Maestro protocol, preserve unrelated work, use a feature flag such as
`CUSTOM_FILM_SCENE_CONTROL_V1`, independently verify spend and recovery
boundaries, and deploy through the sanctioned drain/migration workflow. End
with the system live but stopped at Scene 1’s first exact provider approval.

## Definition of done

- Scene Control is live behind its intended production flag.
- Ryan can lock film-level foundations and drive one scene through explicit
  gates.
- Later scenes remain locked until current-scene acceptance.
- Every paid operation has its own exact cumulative approval.
- Synthetic one-scene Remotion proof passes visually and technically.
- No real provider work has run.
- The live system is stopped at Scene 1’s first exact paid approval for Ryan.
